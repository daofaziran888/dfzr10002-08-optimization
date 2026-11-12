"""数据服务发布业务规则：状态流转、字段校验与筛选口径都收在这里。

服务输出数据集要跟随复核代次：清单里同步给出数据集最近刷新代次与引用该数据集的实验。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "service"
EXPERIMENT_MODULE = "experiment"
GENERATION_TABLE = "dataset_generation"
REQUIRED_FIELDS = ["服务编号", "服务名称", "输出数据集"]
STATUS_ORDER = ["草稿", "待审批", "已发布", "已停用"]
ACTION_RULES = {"提交审批": "待审批", "发布服务": "已发布", "停用服务": "已停用"}
NEGATIVE_ACTIONS = ["停用服务"]


def _current_generation(dataset_code: str) -> dict[str, Any] | None:
    rows = [
        row for row in store.aux_rows(GENERATION_TABLE)
        if str(row.get("数据集编号")) == dataset_code
    ]
    return max(rows, key=lambda row: int(row.get("代次", 0))) if rows else None


def _experiments_using(dataset_code: str) -> list[str]:
    return [
        str(row.get("实验编号"))
        for row in store.rows(EXPERIMENT_MODULE)
        if str(row.get("分析数据集")) == dataset_code
    ]


class ServiceService:
    def decorate(self, entry: dict[str, Any]) -> dict[str, Any]:
        dataset_code = str(entry.get("输出数据集") or "")
        current = _current_generation(dataset_code)
        return {
            **entry,
            "数据集代次": int(current.get("代次", 0)) if current else 0,
            "数据集最近刷新时间": str(current.get("最近刷新") or "—") if current else "—",
            "引用实验": _experiments_using(dataset_code),
        }

    def list_decorated(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        items, total = self.list_entries(keyword=keyword, status=status, page=page, size=size)
        return [self.decorate(item) for item in items], total

    def get_decorated(self, entry_id: int) -> dict[str, Any] | None:
        entry = self.get_entry(entry_id)
        return self.decorate(entry) if entry else None

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
            rows = [row for row in rows if keyword in str(row.get("服务编号", ""))]
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
            return None, f"数据服务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据服务发布可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"数据服务已{action}"
