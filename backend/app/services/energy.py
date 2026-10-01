"""能耗监测业务规则：状态流转、字段校验与筛选口径都收在这里。

监测视图（大类汇总 → 单台设备钻取）与流水台账共用同一份 store 数据，
汇总口径只有这一处实现，避免台账和视图各算一套。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.store import store

MODULE = "energy"
REQUIRED_FIELDS = ["记录编号", "设备类型", "设备编号"]
STATUS_ORDER = ["正常", "异常偏高", "异常偏低", "已核实"]
ACTION_RULES = {"记录能耗": "正常", "异常登记": "异常偏高", "核实确认": "已核实"}
NEGATIVE_ACTIONS = []

# 监测视图用到的业务字段（与流水列保持一致）
F_CATEGORY = "设备类型"
F_DEVICE = "设备编号"
F_POWER = "电耗度数"
F_FUEL = "油耗升数"
F_PERIOD = "记录时段"
F_READER = "抄表人员"

# 按设备大类配置单台设备单班次的超标阈值（度 / 升）；
# 不适用的能源种类置 None，不会被判定超标。
CATEGORY_LIMITS: dict[str, dict[str, float | None]] = {
    "岸桥": {"power": 3500.0, "fuel": None},
    "场桥": {"power": None, "fuel": 400.0},
    "内集卡": {"power": None, "fuel": 150.0},
}

PERIOD_RANGES = ["全日", "近30天", "本月", "本周"]


def _to_float(value: Any) -> float | None:
    """把抄表值转成数字；空串、None、无法解析的内容都视为未抄表（None），绝不兜底成 0。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_blank(value: Any) -> bool:
    return value is None or not str(value).strip()


def _parse_day(value: Any) -> date | None:
    """从“2026-09-25 早班”这类时段文本里取出日期；取不到返回 None（时段缺失/异常）。"""
    text = str(value or "").strip()
    if not text:
        return None
    head = text.split()[0]
    try:
        return date.fromisoformat(head[:10])
    except ValueError:
        return None


def _period_bounds(period: str, today: date | None = None) -> tuple[date | None, date | None]:
    today = today or date.today()
    if period == "近30天":
        return today - timedelta(days=29), today
    if period == "本月":
        return today.replace(day=1), today
    if period == "本周":
        # 周一切片
        return today - timedelta(days=today.weekday()), today
    return None, None


def _dedup_key(row: dict[str, Any]) -> tuple[str, int]:
    """同一次抄表重复提交时的先后依据：先比时段日期，再比记录入库 id，都取最大的一条。"""
    day = _parse_day(row.get(F_PERIOD))
    # 日期缺失用空串垫底，保证它永远旧于有日期的记录
    return (day.isoformat() if day else "", int(row.get("id", 0)))


def _reading_slot(row: dict[str, Any]) -> str:
    """一次抄表的归属班次：时段文本本身（如 2026-09-25 早班）。

    时段缺失时无法判断是否与别的记录同班次，退回记录 id 保证不会被误去重。
    """
    period = str(row.get(F_PERIOD) or "").strip()
    return period or f"__noperiod_{row.get('id')}"


class EnergyService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
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

    # ------------------------------------------------------------------
    # 监测视图：流水台账 → 周期过滤 → 同设备同班次去重留最新 → 设备/大类两级聚合
    # ------------------------------------------------------------------
    def _effective_rows(
        self,
        *,
        period: str = "全日",
        start_day: date | None = None,
        end_day: date | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """返回去重后的有效抄表记录（粒度：设备 + 班次）及窗口统计。"""
        if start_day is None and end_day is None:
            start_day, end_day = _period_bounds(period)
        rows = store.rows(MODULE)
        missing_period_rows = 0
        if start_day or end_day:
            kept: list[dict[str, Any]] = []
            for row in rows:
                day = _parse_day(row.get(F_PERIOD))
                # 时段缺失的记录无法归入周期：不参与任何合计，单独圈出来
                if day is None:
                    missing_period_rows += 1
                    continue
                if start_day and day < start_day:
                    continue
                if end_day and day > end_day:
                    continue
                kept.append(row)
            rows = kept
        else:
            missing_period_rows = sum(
                1 for row in rows if _is_blank(row.get(F_PERIOD)) or _parse_day(row.get(F_PERIOD)) is None
            )

        # 同一台设备同一班次重复提交抄表，只保留最新的一条
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        submitted = 0
        for row in rows:
            device = str(row.get(F_DEVICE) or "").strip()
            if not device:
                continue
            submitted += 1
            key = (device, _reading_slot(row))
            current = latest.get(key)
            if current is None or _dedup_key(row) > _dedup_key(current):
                latest[key] = row
        stats = {
            "dedupedCount": submitted - len(latest),
            "missingPeriodCount": missing_period_rows,
        }
        return list(latest.values()), stats

    @staticmethod
    def _reading_view(row: dict[str, Any], limits: dict[str, float | None]) -> dict[str, Any]:
        """单条（去重后）抄表记录的视图；没抄表的数值保持 None，绝不补 0。

        适用性按大类口径区分：岸桥不烧油，空油耗是“不适用”而不是“漏抄”。
        """
        power_applicable = limits["power"] is not None
        fuel_applicable = limits["fuel"] is not None
        power = _to_float(row.get(F_POWER))
        fuel = _to_float(row.get(F_FUEL))
        missing_reader = _is_blank(row.get(F_READER))
        missing_period = _is_blank(row.get(F_PERIOD))
        # 只有该大类适用的能源种类为空，才算“这一班没抄表”
        missing_power = power is None and power_applicable
        missing_fuel = fuel is None and fuel_applicable
        over_power = power_applicable and power is not None and power > limits["power"]  # type: ignore[operator]
        over_fuel = fuel_applicable and fuel is not None and fuel > limits["fuel"]  # type: ignore[operator]
        issues: list[str] = []
        if missing_reader:
            issues.append("抄表人缺失")
        if missing_period:
            issues.append("时段缺失")
        # 注意：当班未抄表不算“信息缺失”，由 missingPower/missingFuel 单独表达
        return {
            "recordId": row.get("记录编号"),
            "sourceId": row.get("id"),
            "period": None if missing_period else str(row.get(F_PERIOD)).strip(),
            "reader": None if missing_reader else str(row.get(F_READER)).strip(),
            "power": power,
            "fuel": fuel,
            "powerApplicable": power_applicable,
            "fuelApplicable": fuel_applicable,
            "missingPower": bool(missing_power),
            "missingFuel": bool(missing_fuel),
            "missingReader": missing_reader,
            "missingPeriod": missing_period,
            "overPower": bool(over_power),
            "overFuel": bool(over_fuel),
            "overLimit": bool(over_power or over_fuel),
            "issues": issues,
        }

    def _build_devices(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把去重后的抄表记录按设备聚合：设备合计 = 周期内各班次有效抄表之和。"""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            device = str(row.get(F_DEVICE) or "").strip()
            if device:
                grouped.setdefault(device, []).append(row)

        devices: list[dict[str, Any]] = []
        for device, items in grouped.items():
            category = str(items[0].get(F_CATEGORY) or "未分类").strip() or "未分类"
            limits = CATEGORY_LIMITS.get(category, {"power": None, "fuel": None})
            power_applicable = limits["power"] is not None
            fuel_applicable = limits["fuel"] is not None
            readings = [self._reading_view(row, limits) for row in items]
            readings.sort(key=lambda r: r["period"] or "", reverse=True)
            powers = [r["power"] for r in readings if r["power"] is not None]
            fuels = [r["fuel"] for r in readings if r["fuel"] is not None]
            devices.append({
                "category": category,
                "device": device,
                "powerApplicable": power_applicable,
                "fuelApplicable": fuel_applicable,
                # 不适用的能源种类给 None，前端显示“—”，避免和真实 0 混淆
                "powerTotal": round(sum(powers), 2) if power_applicable else None,
                "fuelTotal": round(sum(fuels), 2) if fuel_applicable else None,
                "powerAvg": round(sum(powers) / len(powers), 2) if powers else None,
                "fuelAvg": round(sum(fuels) / len(fuels), 2) if fuels else None,
                "readingCount": len(readings),
                "missingReadingCount": sum(1 for r in readings if r["missingPower"] or r["missingFuel"]),
                "issueReadings": [r for r in readings if r["issues"]],
                "latest": readings[0],
                "readings": readings,
                "overLimit": any(r["overLimit"] for r in readings),
                "hasIssues": any(r["issues"] for r in readings),
            })
        return devices

    @staticmethod
    def _apply_rank(items: list[dict[str, Any]], field: str, rank_field: str) -> None:
        ordered = sorted(
            (item for item in items if item[field] is not None),
            key=lambda item: item[field],
            reverse=True,
        )
        for index, item in enumerate(ordered, start=1):
            item[rank_field] = index

    def category_summary(
        self,
        *,
        period: str = "全日",
        start_day: date | None = None,
        end_day: date | None = None,
    ) -> dict[str, Any]:
        """大类层：电耗/油耗合计、两类排名，超标大类往前排。"""
        rows, window_stats = self._effective_rows(period=period, start_day=start_day, end_day=end_day)
        devices = self._build_devices(rows)

        grouped: dict[str, list[dict[str, Any]]] = {}
        for device in devices:
            grouped.setdefault(device["category"], []).append(device)

        categories: list[dict[str, Any]] = []
        for name, items in grouped.items():
            limits = CATEGORY_LIMITS.get(name, {"power": None, "fuel": None})
            power_applicable = limits["power"] is not None
            fuel_applicable = limits["fuel"] is not None
            categories.append({
                "category": name,
                "deviceCount": len(items),
                "powerTotal": round(sum(d["powerTotal"] for d in items), 2) if power_applicable else None,
                "fuelTotal": round(sum(d["fuelTotal"] for d in items), 2) if fuel_applicable else None,
                "powerApplicable": power_applicable,
                "fuelApplicable": fuel_applicable,
                "overLimit": any(d["overLimit"] for d in items),
                "overDeviceCount": sum(1 for d in items if d["overLimit"]),
                "missingReadingCount": sum(d["missingReadingCount"] for d in items),
                "issueDeviceCount": sum(1 for d in items if d["hasIssues"]),
            })

        # 排名：超标大类优先，其余按电耗+油耗合计从高到低（None 合计按 0 参排）
        categories.sort(
            key=lambda c: (not c["overLimit"], -((c["powerTotal"] or 0.0) + (c["fuelTotal"] or 0.0)))
        )
        for index, category in enumerate(categories, start=1):
            category["rank"] = index
        self._apply_rank(categories, "powerTotal", "powerRank")
        self._apply_rank(categories, "fuelTotal", "fuelRank")

        return {
            "period": period,
            "categories": categories,
            "totals": {
                "powerTotal": round(sum(c["powerTotal"] or 0.0 for c in categories), 2),
                "fuelTotal": round(sum(c["fuelTotal"] or 0.0 for c in categories), 2),
                "deviceCount": len(devices),
                "overDeviceCount": sum(c["overDeviceCount"] for c in categories),
                "missingReadingCount": sum(c["missingReadingCount"] for c in categories),
                "issueDeviceCount": sum(c["issueDeviceCount"] for c in categories),
                "dedupedCount": window_stats["dedupedCount"],
                "missingPeriodCount": window_stats["missingPeriodCount"],
            },
        }

    def category_detail(
        self,
        category_name: str,
        *,
        period: str = "全日",
        start_day: date | None = None,
        end_day: date | None = None,
    ) -> dict[str, Any] | None:
        """设备层：点开某一大类后钻取到单台设备的各班次抄表明细。"""
        rows, _ = self._effective_rows(period=period, start_day=start_day, end_day=end_day)
        devices = [
            device for device in self._build_devices(rows) if device["category"] == category_name
        ]
        if not devices:
            return None

        limits = CATEGORY_LIMITS.get(category_name, {"power": None, "fuel": None})
        # 单台排名：超标设备往前排，同口径按周期合计用量降序
        devices.sort(key=lambda d: (not d["overLimit"], -((d["powerTotal"] or 0.0) + (d["fuelTotal"] or 0.0))))
        self._apply_rank(devices, "powerTotal", "powerRank")
        self._apply_rank(devices, "fuelTotal", "fuelRank")

        return {
            "period": period,
            "category": category_name,
            "powerLimit": limits["power"],
            "fuelLimit": limits["fuel"],
            "devices": devices,
        }
