"""能耗监测业务规则。

台账列表与钻取视图共用同一条数据管道（``canonical_rows``），
保证「能耗台账」和「能耗监测视图」永远是同一套数：

原始流水 -> 数值/字段清洗 -> 按「设备 + 日期 + 班次」去重（留提交时间最新的一条）
         -> 按统计周期过滤 -> 空值保持 None（绝不当 0 算）

状态流转、字段校验也收在这里。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "energy"
REQUIRED_FIELDS = ["记录编号", "设备类型", "设备编号"]
STATUS_ORDER = ["正常", "异常偏高", "异常偏低", "已核实"]
ACTION_RULES = {"记录能耗": "正常", "异常登记": "异常偏高", "核实确认": "已核实"}
NEGATIVE_ACTIONS = ["异常登记"]

# 各设备大类每班次的能耗上限（用于超标判定与排名前置）
CATEGORY_THRESHOLDS: dict[str, dict[str, float]] = {
    "岸桥": {"elec": 2200.0, "fuel": None},
    "场桥": {"elec": 900.0, "fuel": 200.0},
    "内集卡": {"elec": None, "fuel": 160.0},
    "冷藏箱插座": {"elec": 180.0, "fuel": None},
}
CATEGORY_LABELS: dict[str, str] = {
    "岸桥": "岸桥（电驱）",
    "场桥": "场桥（电油双驱）",
    "内集卡": "内集卡（油驱）",
    "冷藏箱插座": "冷藏箱插座（电驱）",
}
SHIFT_ORDER = ["夜班", "白班", "晚班"]
METRIC_LABELS = {"elec": "电耗（度）", "fuel": "油耗（升）"}

# 账期统一锚定当前自然周期（示例数据集中在 2026-09）
PERIODS: dict[str, tuple[date, date]] = {
    "week": (date(2026, 9, 28), date(2026, 9, 30)),
    "month": (date(2026, 9, 1), date(2026, 9, 30)),
    "quarter": (date(2026, 7, 1), date(2026, 9, 30)),
}
PERIOD_LABELS = {
    "week": "本周（09-28 ~ 09-30）",
    "month": "本月（2026-09）",
    "quarter": "本季度（2026 Q3）",
    "all": "全部周期",
}
VALID_PERIODS = tuple(PERIOD_LABELS)


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _to_number(value: Any) -> float | None:
    """抄表数值转浮点；空串 / 非数字一律视为「没抄」，返回 None，绝不补 0。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _round(value: float) -> float:
    result = round(value, 1)
    return int(result) if result == int(result) else result


def _parse_period(period: str) -> tuple[date | None, str | None]:
    """把「2026-09-29 白班」拆成 (日期, 班次)；无法识别日期时返回 (None, None)。"""
    text = _clean(period)
    if not text:
        return None, None
    shift = next((name for name in SHIFT_ORDER if name in text), None)
    head = text.split()[0] if " " in text else text[:10]
    try:
        day = datetime.strptime(head[:10], "%Y-%m-%d").date()
    except ValueError:
        return None, None
    return day, shift


def _parse_submitted(row: dict[str, Any]) -> datetime:
    """提交时间用于「同班重复抄表留最新」；历史数据没有该字段时退回 id 顺序。"""
    text = _clean(row.get("提交时间"))
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return datetime(2000, 1, 1)


def _in_period(day: date | None, period: str) -> bool:
    # 时段缺失的记录不进任何周期的数值汇总，由「问题清单」单独兜住
    if day is None:
        return False
    if period == "all":
        return True
    start, end = PERIODS[period]
    return start <= day <= end


class EnergyService:
    # ------------------------------------------------------------------ #
    # 统一数据管道：台账与监测视图都从这里取数，口径只有这一份
    # ------------------------------------------------------------------ #
    def canonical_rows(
        self,
        *,
        period: str = "week",
        include_periodless: bool = True,
    ) -> list[dict[str, Any]]:
        """清洗 + 去重 + 周期过滤后的规范流水。

        去重键为「设备类型 + 设备编号 + 日期 + 班次」，
        同一键下重复提交只保留「提交时间」最新（再以 id 兜底）的一条；
        去重前条数会一并记在返回值的「重复记录数」里，由调用方取 summary。
        """
        raw = store.rows(MODULE)
        chosen: dict[tuple[str, str, date | None, str | None], dict[str, Any]] = {}
        for row in raw:
            day, shift = _parse_period(row.get("记录时段"))
            key = (_clean(row.get("设备类型")), _clean(row.get("设备编号")), day, shift)
            current = chosen.get(key)
            if current is None or self._newer_than(row, current):
                chosen[key] = row

        result: list[dict[str, Any]] = []
        for (cat, dev, day, shift), row in chosen.items():
            if not _in_period(day, period) and not (day is None and include_periodless):
                continue
            elec = _to_number(row.get("电耗度数"))
            fuel = _to_number(row.get("油耗升数"))
            reader = _clean(row.get("抄表人员"))
            period_text = _clean(row.get("记录时段"))
            result.append({
                "id": row.get("id"),
                "记录编号": _clean(row.get("记录编号")),
                "设备类型": cat,
                "设备编号": dev,
                "电耗度数": elec,
                "油耗升数": fuel,
                "记录时段": period_text or None,
                "抄表人员": reader or None,
                "能耗状态": _clean(row.get("status")) or "正常",
                "提交时间": _clean(row.get("提交时间")) or None,
                "_day": day,
                "_shift": shift,
                "_missing_reader": reader == "",
                "_missing_period": period_text == "",
            })
        result.sort(key=lambda item: (item["_day"] is None,
                                      item["_day"] or date.min,
                                      SHIFT_ORDER.index(item["_shift"]) if item["_shift"] in SHIFT_ORDER else 99,
                                      item["设备编号"]))
        return result

    @staticmethod
    def _newer_than(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
        cand_time, cur_time = _parse_submitted(candidate), _parse_submitted(current)
        if cand_time != cur_time:
            return cand_time > cur_time
        return int(candidate.get("id", 0)) > int(current.get("id", 0))

    def dedup_stats(self) -> dict[str, int]:
        """原始流水 / 去重后条数：给页面标注「已自动合并 N 条重复抄表」。"""
        raw = store.rows(MODULE)
        keys: set[tuple[str, str, date | None, str | None]] = set()
        for row in raw:
            day, shift = _parse_period(row.get("记录时段"))
            keys.add((_clean(row.get("设备类型")), _clean(row.get("设备编号")), day, shift))
        return {"raw": len(raw), "deduped": len(keys), "duplicates": len(raw) - len(keys)}

    # ------------------------------------------------------------------ #
    # 监测视图：大类合计与钻取明细
    # ------------------------------------------------------------------ #
    def analysis_overview(self, period: str = "week") -> dict[str, Any]:
        """按设备大类汇总电耗/油耗合计、排名，并把超标大类往前排。"""
        rows = [r for r in self.canonical_rows(period=period)
                if not r["_missing_period"]]
        cats: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            cats.setdefault(row["设备类型"], []).append(row)

        device_universe = self._device_catalog()
        overview = []
        for cat, cat_rows in cats.items():
            elec_values = [r["电耗度数"] for r in cat_rows if r["电耗度数"] is not None]
            fuel_values = [r["油耗升数"] for r in cat_rows if r["油耗升数"] is not None]
            elec_total = sum(elec_values)
            fuel_total = sum(fuel_values)
            thresholds = CATEGORY_THRESHOLDS.get(cat, {"elec": None, "fuel": None})

            over_items: list[dict[str, Any]] = []
            for metric, field in (("elec", "电耗度数"), ("fuel", "油耗升数")):
                limit = thresholds.get(metric)
                # 以「单条抄表是否越过班次上限」判定超标，避免设备越多均值被摊薄
                exceeded = [r for r in cat_rows
                            if r[field] is not None
                            and limit is not None
                            and float(r[field]) > limit]
                if exceeded:
                    worst = max(exceeded, key=lambda r: float(r[field] or 0))
                    over_items.append({
                        "metric": metric,
                        "metric_label": METRIC_LABELS[metric],
                        "threshold": limit,
                        "count": len(exceeded),
                        "worst_device": worst["设备编号"],
                        "worst_value": _round(float(worst[field] or 0)),
                        "ratio": _round(max(float(r[field] or 0) / limit for r in exceeded)),
                    })

            shifts_expected, shifts_recorded = self._slot_counts(cat_rows, cat, period)
            blank_cells = max(shifts_expected - shifts_recorded, 0)
            overview.append({
                "category": cat,
                "category_label": CATEGORY_LABELS.get(cat, cat),
                "elec_total": _round(elec_total) if elec_values else None,
                "fuel_total": _round(fuel_total) if fuel_values else None,
                "reading_count": len(cat_rows),
                "device_count": len(device_universe.get(cat, set())),
                "blank_shift_count": blank_cells,
                "over_items": over_items,
                "is_over": bool(over_items),
            })

        # 超标大类往前排；同类里按最严重的超标倍数、再按合计能耗排
        def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
            ratio = max((o["ratio"] for o in item["over_items"]), default=0)
            head = (item["elec_total"] or 0) + (item["fuel_total"] or 0)
            return (0 if item["is_over"] else 1, -ratio, -head)

        overview.sort(key=sort_key)
        elec_rank = self._rank(overview, "elec_total")
        fuel_rank = self._rank(overview, "fuel_total")
        for item in overview:
            item["elec_rank"] = elec_rank.get(item["category"])
            item["fuel_rank"] = fuel_rank.get(item["category"])

        return {
            "period": period,
            "period_label": PERIOD_LABELS[period],
            "categories": overview,
            "summary": self._build_summary(rows, period),
        }

    def analysis_category(self, category: str, period: str = "week") -> dict[str, Any] | None:
        """钻取某一大类：列到单台设备，再可展开到「设备 × 班次」明细。"""
        valid = {_clean(r.get("设备类型")) for r in store.rows(MODULE) if _clean(r.get("设备类型"))}
        if category not in valid:
            return None

        rows = [r for r in self.canonical_rows(period=period)
                if r["设备类型"] == category and not r["_missing_period"]]
        thresholds = CATEGORY_THRESHOLDS.get(category, {"elec": None, "fuel": None})

        by_device: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_device.setdefault(row["设备编号"], []).append(row)

        # 设备全集：本期没抄表的设备也要露出来，提示「整期缺抄」
        catalog = self._device_catalog().get(category, set())
        for dev in catalog:
            by_device.setdefault(dev, [])

        devices = []
        for dev, dev_rows in by_device.items():
            devices.append(self._build_device_row(category, dev, dev_rows, thresholds, period))

        def dev_sort(item: dict[str, Any]) -> tuple[Any, ...]:
            ratio = max([o["ratio"] for o in item["over_items"]], default=0)
            head = (item["elec_total"] or 0) + (item["fuel_total"] or 0)
            return (0 if item["is_over"] else 1, -ratio, -head)

        devices.sort(key=dev_sort)
        elec_rank = self._rank(devices, "elec_total")
        fuel_rank = self._rank(devices, "fuel_total")
        for index, item in enumerate(devices, start=1):
            item["rank"] = index
            item["elec_rank"] = elec_rank.get(item["device"])
            item["fuel_rank"] = fuel_rank.get(item["device"])

        return {
            "period": period,
            "period_label": PERIOD_LABELS[period],
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, category),
            "thresholds": thresholds,
            "devices": devices,
        }

    def _build_device_row(
        self,
        category: str,
        dev: str,
        dev_rows: list[dict[str, Any]],
        thresholds: dict[str, float | None],
        period: str,
    ) -> dict[str, Any]:
        elec_values = [r["电耗度数"] for r in dev_rows if r["电耗度数"] is not None]
        fuel_values = [r["油耗升数"] for r in dev_rows if r["油耗升数"] is not None]

        over_items = []
        for metric, values, field in (
            ("elec", elec_values, "电耗度数"),
            ("fuel", fuel_values, "油耗升数"),
        ):
            limit = thresholds.get(metric)
            exceeded = [r for r in dev_rows if r[field] is not None
                        and limit is not None and float(r[field]) > limit]
            if exceeded:
                worst = max(exceeded, key=lambda r: r[field] or 0)
                over_items.append({
                    "metric": metric,
                    "metric_label": METRIC_LABELS[metric],
                    "threshold": limit,
                    "count": len(exceeded),
                    "worst_value": _round(float(worst[field] or 0)),
                    "worst_shift": worst["记录时段"],
                    "ratio": _round(max(float(r[field] or 0) / limit for r in exceeded)),
                })

        expected, recorded = self._slot_counts(dev_rows, category, period, dev)
        readings = []
        for row in dev_rows:
            marks = []
            if row["电耗度数"] is not None and thresholds.get("elec") is not None \
                    and row["电耗度数"] > thresholds["elec"]:
                marks.append("elec")
            if row["油耗升数"] is not None and thresholds.get("fuel") is not None \
                    and row["油耗升数"] > thresholds["fuel"]:
                marks.append("fuel")
            readings.append({
                "id": row["id"],
                "记录编号": row["记录编号"],
                "电耗度数": row["电耗度数"],
                "油耗升数": row["油耗升数"],
                "记录时段": row["记录时段"],
                "抄表人员": row["抄表人员"],
                "能耗状态": row["能耗状态"],
                "提交时间": row["提交时间"],
                "shift": row["_shift"],
                "missing_reader": row["_missing_reader"],
                "over_metrics": marks or None,
            })

        return {
            "device": dev,
            "elec_total": _round(sum(elec_values)) if elec_values else None,
            "fuel_total": _round(sum(fuel_values)) if fuel_values else None,
            "reading_count": recorded,
            "blank_shift_count": max(expected - recorded, 0),
            "missing_reader_count": sum(1 for r in dev_rows if r["_missing_reader"]),
            "is_over": bool(over_items),
            "over_items": over_items,
            "readings": readings,
        }

    # ------------------------------------------------------------------ #
    # 问题清单：缺抄表人、缺时段、整班漏抄，单独圈出来不与 0 混淆
    # ------------------------------------------------------------------ #
    def _build_summary(self, rows: list[dict[str, Any]], period: str) -> dict[str, Any]:
        dedup = self.dedup_stats()
        missing_reader = [
            self._issue_payload(r, "missing_reader")
            for r in rows if r["_missing_reader"] and not r["_missing_period"]
        ]
        # 缺时段的记录任何账期都要看见
        periodless = [
            self._issue_payload(r, "missing_period")
            for r in self.canonical_rows(period=period) if r["_missing_period"]
        ]
        elec_values = [r["电耗度数"] for r in rows if r["电耗度数"] is not None]
        fuel_values = [r["油耗升数"] for r in rows if r["油耗升数"] is not None]
        # 漏班只在账期对应窗口内核算，和大类层 / 设备层共用同一口径
        blank_total = 0
        for cat in self._device_catalog():
            cat_rows = [r for r in rows if r["设备类型"] == cat]
            expected_total, recorded_total = self._slot_counts(cat_rows, cat, period)
            blank_total += max(expected_total - recorded_total, 0)
        return {
            "elec_total": _round(sum(elec_values)) if elec_values else None,
            "fuel_total": _round(sum(fuel_values)) if fuel_values else None,
            "reading_count": len(rows),
            "blank_shift_count": blank_total,
            "missing_reader_count": len(missing_reader),
            "missing_period_count": len(periodless),
            "duplicate_count": dedup["duplicates"],
            "raw_count": dedup["raw"],
            "issues": {
                "missing_reader": missing_reader,
                "missing_period": periodless,
            },
        }

    @staticmethod
    def _issue_payload(row: dict[str, Any], kind: str) -> dict[str, Any]:
        return {
            "id": row["id"],
            "记录编号": row["记录编号"],
            "设备类型": row["设备类型"],
            "设备编号": row["设备编号"],
            "记录时段": row["记录时段"],
            "抄表人员": row["抄表人员"],
            "电耗度数": row["电耗度数"],
            "油耗升数": row["油耗升数"],
            "issue": kind,
        }

    # ------------------------------------------------------------------ #
    # 设备 / 班次骨架：用来算「应该有几个班次格子」，缺的格子就是空白
    # ------------------------------------------------------------------ #
    def _device_catalog(self) -> dict[str, set[str]]:
        catalog: dict[str, set[str]] = {}
        for row in store.rows(MODULE):
            cat, dev = _clean(row.get("设备类型")), _clean(row.get("设备编号"))
            if cat and dev:
                catalog.setdefault(cat, set()).add(dev)
        return catalog

    def _slot_counts(
        self,
        rows: list[dict[str, Any]],
        category: str | None,
        period: str,
        device: str | None = None,
    ) -> tuple[int, int]:
        """同一窗口下的「应抄班次数」与「实抄班次数」。

        - 周：按完整日历（09-28 ~ 09-30）逐台核算，漏抄直接暴露；
        - 月：只在该范围内「有设备抄过表」的日期上核算，未排产日不凑数；
        - 季度/全部：历史稀疏，只在近 7 天密集窗口内对有抄表的设备核算。
        """
        if period == "week":
            start, end = PERIODS["week"]
            devices = [device] if device else sorted(
                self._device_catalog().get(category or "", set()))
            expected = len(devices) * ((end - start).days + 1) * len(SHIFT_ORDER)
        elif period == "month":
            month_days = [r["_day"] for r in rows if r["_day"] is not None]
            if not month_days:
                return 0, 0
            start, end = min(month_days), max(month_days)
            devices = [device] if device else sorted(
                self._device_catalog().get(category or "", set()))
            expected = len(devices) * ((end - start).days + 1) * len(SHIFT_ORDER)
        else:
            # 季度/全部：历史抄表稀疏，漏班只在「本周密集抄表窗口」内核算；
            # 更长账期的意义在于汇总合计能纳入历史数据，而不是追历史排产空白。
            start, end = PERIODS["week"]
            if device is not None:
                devices = [device]
            else:
                devices = sorted({
                    r["设备编号"] for r in rows
                    if r["_day"] is not None and start <= r["_day"] <= end
                })
            expected = len(devices) * ((end - start).days + 1) * len(SHIFT_ORDER)

        recorded = len({
            (r["设备编号"], r["_day"], r["_shift"])
            for r in rows
            if r["_day"] is not None and start <= r["_day"] <= end
            and (device is None or r["设备编号"] == device)
        })
        return expected, recorded

    @staticmethod
    def _rank(items: list[dict[str, Any]], field: str) -> dict[Any, int]:
        """按合计值降序排名；值为 None（该类根本不烧这种能源）不参与排名。"""
        scored = [item for item in items if item.get(field) is not None]
        scored.sort(key=lambda item: item[field], reverse=True)
        return {item.get("category") or item.get("device"): index
                for index, item in enumerate(scored, start=1)}

    # ------------------------------------------------------------------ #
    # 台账：与监测视图共用 canonical_rows，不另算一套
    # ------------------------------------------------------------------ #
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        period: str = "week",
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self.canonical_rows(period=period)
        if keyword:
            rows = [row for row in rows
                    if keyword in row["记录编号"] or keyword in row["设备编号"]]
        if status:
            rows = [row for row in rows if row["能耗状态"] == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._public_row(row) for row in rows[start:start + size]], total

    @staticmethod
    def _public_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "status": row["能耗状态"],
            "记录编号": row["记录编号"],
            "设备类型": row["设备类型"],
            "设备编号": row["设备编号"],
            "电耗度数": row["电耗度数"],
            "油耗升数": row["油耗升数"],
            "记录时段": row["记录时段"],
            "抄表人员": row["抄表人员"],
            "能耗状态": row["能耗状态"],
            "提交时间": row["提交时间"],
            "missing_reader": row["_missing_reader"],
            "missing_period": row["_missing_period"],
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        for row in self.canonical_rows(period="all"):
            if int(row.get("id", 0)) == entry_id:
                return self._public_row(row)
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not _clean(values.get(field))]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ["记录编号", "设备类型", "设备编号", "电耗度数", "油耗升数",
                      "记录时段", "抄表人员", "能耗状态", "提交时间"]:
            entry[field] = values.get(field)
        entry["status"] = _clean(values.get("能耗状态")) or STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"能耗记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于能耗监测可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"能耗记录已{action}"
