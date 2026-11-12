"""分析数据集业务规则：状态流转、代次刷新与「被实验引用」统计都收在这里。"""
from __future__ import annotations

from typing import Any

from app.review_data import ensure_seed_reviews
from app.store import store

MODULE = "dataset"
EXPERIMENT_MODULE = "experiment"
REQUIRED_FIELDS = ["数据集编号", "数据集名称", "来源表名"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用配置": "已启用", "停用配置": "已停用"}
NEGATIVE_ACTIONS = ["停用配置"]
GENERATION_TABLE = "dataset_generation"
REFRESH_TIME = "2026-11-12 15:00"


class DatasetService:
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
            rows = [row for row in rows if keyword in str(row.get("数据集编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def generations(self, dataset_code: str) -> list[dict[str, Any]]:
        return sorted(
            (row for row in store.aux_rows(GENERATION_TABLE) if row.get("数据集编号") == dataset_code),
            key=lambda row: int(row.get("代次", 0)),
        )

    def current_generation(self, dataset_code: str) -> dict[str, Any] | None:
        rows = self.generations(dataset_code)
        return rows[-1] if rows else None

    def experiments_using(self, dataset_code: str) -> list[dict[str, Any]]:
        """引用该数据集的实验；清单页同步显示用，与复核使用同一份引用关系。"""
        return [
            {
                "实验编号": row.get("实验编号"),
                "实验名称": row.get("实验名称"),
                "实验状态": row.get("实验状态") or row.get("status"),
            }
            for row in store.rows(EXPERIMENT_MODULE)
            if row.get("分析数据集") == dataset_code
        ]

    def review_summary_for(self, dataset_code: str) -> list[dict[str, Any]]:
        """引用该数据集的实验在当前代次的复核结论，供数据集清单与复核页对齐。"""
        ensure_seed_reviews()
        summaries: list[dict[str, Any]] = []
        for row in store.rows(EXPERIMENT_MODULE):
            if str(row.get("分析数据集")) != dataset_code:
                continue
            reviews = [
                item for item in store.aux_rows("review")
                if str(item.get("实验编号")) == str(row.get("实验编号"))
            ]
            latest = (
                max(reviews, key=lambda item: (int(item.get("数据集代次", 0)), str(item.get("复核时间") or "")))
                if reviews else None
            )
            is_current = latest is not None and int(latest.get("数据集代次", 0)) == int(
                (self.current_generation(dataset_code) or {}).get("代次", 0)
            )
            summaries.append({
                "实验编号": row.get("实验编号"),
                "实验名称": row.get("实验名称"),
                "复核代次": int(latest.get("数据集代次", 0)) if latest else None,
                "复核结论": latest.get("复核结论") if latest else "待复核",
                "是否当前代次": is_current,
                "基准区间": latest.get("基准区间") if latest else None,
            })
        return summaries

    def decorate(self, entry: dict[str, Any]) -> dict[str, Any]:
        """补齐数据集最近刷新代次与引用它的实验，供清单页与复核页共用。"""
        dataset_code = str(entry.get("数据集编号") or "")
        current = self.current_generation(dataset_code)
        references = self.experiments_using(dataset_code)
        return {
            **entry,
            "最近刷新代次": int(current.get("代次", 0)) if current else 0,
            "最近刷新时间": str(current.get("最近刷新") or "—") if current else "—",
            "被实验引用": [item["实验编号"] for item in references],
            "引用实验": references,
            "复核摘要": self.review_summary_for(dataset_code),
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

    def refresh(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """刷新数据集：追加一个新代次，旧代次的实验结论保留为历史记录。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"数据集 {entry_id} 不存在或已归档"
        dataset_code = str(entry.get("数据集编号") or "")
        rows = store.aux_rows(GENERATION_TABLE)
        latest = max(
            (int(row.get("代次", 0)) for row in rows if row.get("数据集编号") == dataset_code),
            default=0,
        )
        next_generation = latest + 1
        rows.append({"数据集编号": dataset_code, "代次": next_generation, "最近刷新": REFRESH_TIME})
        entry["最近刷新"] = REFRESH_TIME
        entry["刷新频率"] = entry.get("刷新频率") or "手动刷新"
        return self.decorate(entry), f"数据集已刷新到代次 {next_generation}"

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
        store.aux_rows(GENERATION_TABLE).append({
            "数据集编号": str(entry.get("数据集编号")),
            "代次": 1,
            "最近刷新": REFRESH_TIME,
        })
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if action == "刷新数据集":
            return self.refresh(entry_id)
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"数据集 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于分析数据集可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"数据集已{action}"
