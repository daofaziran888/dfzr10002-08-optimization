"""分析实验管理接口：维护分析实验，覆盖启动实验、结束实验、关闭实验等动作。

另含实验复核：按数据集代次与基准区间给出结论，结论分显著/不显著/样本不足三档，
数据集刷新后旧结论转历史、新结论按新代次重算。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.review_data import MIN_GROUP_SAMPLE, RESULT_BUCKETS  # noqa: F401  (接口说明用)
from app.services.experiment import ExperimentService

router = APIRouter(prefix="/api/experiment", tags=["分析实验管理"])

service = ExperimentService()

LIST_FIELDS = ["实验编号", "实验名称", "分析数据集", "分组字段", "目标度量", "基准区间", "显著阈值", "实验状态"]
STATUSES = ["草稿", "运行中", "已完成", "已关闭"]


def _entry_or_404(entry_id: int) -> dict[str, Any]:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"分析实验 {entry_id} 不存在或已归档")
    return entry


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按实验编号或实验名称检索"),
    status: str | None = Query(default=None, description="草稿、运行中、已完成、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按实验编号与状态过滤分析实验管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出分析实验管理清单；先落在这里，避免被 /{entry_id} 抢先匹配。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "experiment", "total": total, "items": items}


@router.get("/review", response_model=dict)
def review_overview() -> dict:
    """复核页清单：每个实验一行，含目标度量、基准区间、显著阈值、样本量与当前代次结论。"""
    items = service.review_overview_rows()
    return {
        "items": items,
        "total": len(items),
        "分档口径": RESULT_BUCKETS,
        "最小样本量": MIN_GROUP_SAMPLE,
    }


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条分析实验明细；不存在时给出可读的错误说明。"""
    return _entry_or_404(entry_id)


@router.get("/{entry_id}/review", response_model=dict)
def get_review(entry_id: int) -> dict:
    """实验复核概览：目标度量、基准区间、显著阈值、数据集最近刷新代次与三档结论。"""
    entry = _entry_or_404(entry_id)
    return service.review_summary(entry)


@router.post("/{entry_id}/review", response_model=ActionResult)
def submit_review(entry_id: int, payload: EntryPayload) -> ActionResult:
    """提交复核：同一实验 + 同一代次 + 同一区间只生成一次结论。"""
    entry = _entry_or_404(entry_id)
    generation = payload.values.get("数据集代次")
    window = payload.values.get("基准区间")
    try:
        generation = int(generation) if generation is not None else None
    except (TypeError, ValueError):
        return ActionResult(ok=False, message="数据集代次必须是整数")
    result = service.submit_review(entry, generation=generation, window=str(window) if window else None)
    if result["review"] is None:
        return ActionResult(ok=False, message=str(result["message"]))
    return ActionResult(ok=True, message=str(result["message"]), entry=result["review"])


@router.post("/{entry_id}/review/deferral", response_model=ActionResult)
def request_deferral(entry_id: int, payload: EntryPayload) -> ActionResult:
    """样本不足时申请延期：逐档延长基准区间，历史结论保持原区间。"""
    entry = _entry_or_404(entry_id)
    generation = payload.values.get("数据集代次")
    window = payload.values.get("基准区间")
    try:
        generation = int(generation) if generation is not None else None
    except (TypeError, ValueError):
        return ActionResult(ok=False, message="数据集代次必须是整数")
    ok, message, review = service.request_deferral(
        entry, generation=generation, window=str(window) if window else None
    )
    return ActionResult(ok=ok, message=message, entry=review)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条分析实验，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="分析实验已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条分析实验执行启动实验、结束实验、关闭实验；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
