"""分析数据集接口：维护数据集，覆盖提交校验、启用配置、停用配置等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.dataset import DatasetService

router = APIRouter(prefix="/api/dataset", tags=["分析数据集"])

service = DatasetService()

LIST_FIELDS = ["数据集编号", "数据集名称", "来源表名", "字段列表", "行数上限", "刷新频率", "最近刷新", "是否启用"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按数据集编号或来源表检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按数据集编号与状态过滤分析数据集列表；同时给出最近刷新代次与引用它的实验。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_decorated(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出分析数据集清单：代次与引用实验一并导出，与复核页口径一致。"""
    items, total = service.list_decorated(page=1, size=10000)
    return {"module": "dataset", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条数据集明细；最近刷新代次与引用实验一并返回。"""
    entry = service.get_decorated(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"数据集 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/generations", response_model=dict)
def list_generations(entry_id: int) -> dict:
    """列出该数据集的全部刷新代次；复核页切换代次时按这里选择。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"数据集 {entry_id} 不存在或已归档")
    dataset_code = str(entry.get("数据集编号") or "")
    rows = service.generations(dataset_code)
    return {
        "数据集编号": dataset_code,
        "items": rows,
        "latest": int(rows[-1].get("代次", 0)) if rows else 0,
    }


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条数据集，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="数据集已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条数据集执行提交校验、启用配置、停用配置、刷新数据集；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
