"""能耗监测接口：维护抄表流水，并提供「大类 -> 单台设备 -> 班次」的可钻取视图。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.energy import VALID_PERIODS, EnergyService, PERIOD_LABELS

router = APIRouter(prefix="/api/energy", tags=["能耗监测"])

service = EnergyService()

LIST_FIELDS = ["记录编号", "设备类型", "设备编号", "电耗度数", "油耗升数", "记录时段", "抄表人员", "能耗状态"]
STATUSES = ["正常", "异常偏高", "异常偏低", "已核实"]


def _check_period(period: str) -> str:
    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"统计周期仅支持：{'、'.join(VALID_PERIODS)}",
        )
    return period


@router.get("/analysis")
def analysis(
    period: str = Query(default="week", description="统计周期：week、month、quarter、all"),
) -> dict[str, Any]:
    """监测视图第一层：按设备大类列电耗/油耗合计与排名，超标大类往前排。

    与台账共用去重、空值、周期口径；缺抄表人、缺时段的记录在 summary.issues 里单独列出。
    """
    _check_period(period)
    return service.analysis_overview(period=period)


@router.get("/analysis/{category}")
def analysis_detail(
    category: str,
    period: str = Query(default="week", description="统计周期：week、month、quarter、all"),
) -> dict[str, Any]:
    """监测视图钻取层：某一大类下的单台设备合计、排名与「设备 × 班次」明细。"""
    _check_period(period)
    detail = service.analysis_category(category=category, period=period)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"设备大类「{category}」暂无能耗记录")
    return detail


@router.get("/periods")
def list_periods() -> dict[str, Any]:
    """统计周期选项：前端切换账期时与后端保持同一份锚点。"""
    return {"items": [{"value": value, "label": PERIOD_LABELS[value]} for value in VALID_PERIODS]}


@router.get("/export")
def export_entries(
    period: str = Query(default="all", description="统计周期：week、month、quarter、all"),
) -> dict[str, Any]:
    """导出能耗台账：输出去重后的规范流水（默认全部周期），与页面口径一致。

    注意：本路由必须声明在 ``/{entry_id}`` 之前，否则 ``export`` 会被当成记录编号。
    """
    _check_period(period)
    items, total = service.list_entries(period=period, page=1, size=10000)
    return {"module": "energy", "period": PERIOD_LABELS[period], "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号或设备编号检索"),
    status: str | None = Query(default=None, description="正常、异常偏高、异常偏低、已核实"),
    period: str = Query(default="week", description="统计周期：week、month、quarter、all"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """能耗台账：与监测视图同一份去重流水；没有数据时返回空页，不报错。"""
    _check_period(period)
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, period=period, page=page, size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条能耗记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"能耗记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条能耗记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="能耗记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条能耗记录执行记录能耗、异常登记、核实确认；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
