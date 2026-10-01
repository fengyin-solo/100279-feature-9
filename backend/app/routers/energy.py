"""能耗监测接口：维护能耗记录，覆盖记录能耗、异常登记、核实确认等动作。"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.energy import PERIOD_RANGES, EnergyService

router = APIRouter(prefix="/api/energy", tags=["能耗监测"])

service = EnergyService()

LIST_FIELDS = ["记录编号", "设备类型", "设备编号", "电耗度数", "油耗升数", "记录时段", "抄表人员", "能耗状态"]
STATUSES = ["正常", "异常偏高", "异常偏低", "已核实"]


def _parse_bound(value: str | None, label: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{label}需为 YYYY-MM-DD 格式") from None


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="正常、异常偏高、异常偏低、已核实"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤能耗监测列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/monitor/summary")
def monitor_summary(
    period: str = Query(default="全日", description=f"统计周期：{'、'.join(PERIOD_RANGES)}"),
    start: str | None = Query(default=None, description="自定义起始日 YYYY-MM-DD，给出后覆盖 period"),
    end: str | None = Query(default=None, description="自定义截止日 YYYY-MM-DD，给出后覆盖 period"),
) -> dict[str, Any]:
    """设备大类层视图：电耗/油耗合计与排名，超标大类排在前面。"""
    if start is None and end is None and period not in PERIOD_RANGES:
        raise HTTPException(status_code=400, detail=f"统计周期仅支持：{'、'.join(PERIOD_RANGES)}")
    start_day, end_day = _parse_bound(start, "起始日"), _parse_bound(end, "截止日")
    if start_day and end_day and start_day > end_day:
        raise HTTPException(status_code=400, detail="起始日不能晚于截止日")
    return service.category_summary(period=period, start_day=start_day, end_day=end_day)


@router.get("/monitor/categories/{category_name}")
def monitor_category_detail(
    category_name: str,
    period: str = Query(default="全日", description=f"统计周期：{'、'.join(PERIOD_RANGES)}"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> dict[str, Any]:
    """设备明细层：某一大类下逐台设备的最新抄表记录与超标标记。"""
    if start is None and end is None and period not in PERIOD_RANGES:
        raise HTTPException(status_code=400, detail=f"统计周期仅支持：{'、'.join(PERIOD_RANGES)}")
    start_day, end_day = _parse_bound(start, "起始日"), _parse_bound(end, "截止日")
    detail = service.category_detail(
        category_name, period=period, start_day=start_day, end_day=end_day
    )
    if detail is None:
        raise HTTPException(status_code=404, detail=f"当前周期内没有「{category_name}」的抄表记录")
    return detail


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出能耗监测清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "energy", "total": total, "items": items}


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
