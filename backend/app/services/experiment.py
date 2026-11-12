"""分析实验复核业务规则。

复核结论绑定「数据集代次 + 基准区间」：
- 同一实验在同一代次、同一区间重复提交，只返回既有结论，不生成第二条；
- 数据集刷新后，旧代次的结论进入历史区，新代次按新口径重算；
- 样本不足时只给「样本不足」，可以逐档延长基准区间申请延期；
- 延期不改写历史结论，而是把待复核口径推到新一档区间。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.review_data import (
    DEFAULT_THRESHOLD,
    DEFAULT_WINDOW,
    MIN_GROUP_SAMPLE,
    RESULT_BUCKETS,
    WINDOW_TIERS,
    compute_conclusion,
    ensure_seed_reviews,
    next_window,
    window_days,
)
from app.store import store
from app.services.dataset import DatasetService

EXPERIMENT_MODULE = "experiment"
REVIEW_TABLE = "review"
DEFERRABLE_RESULTS = ["样本不足"]


class ExperimentService:
    def __init__(self) -> None:
        self.datasets = DatasetService()

    # ---------- 示例数据的一键展开 ----------
    def ensure_seeded(self) -> None:
        """预置复核按当前规则现算，避免把结论硬编码进 seed 而与规则脱节。"""
        ensure_seed_reviews()

    # ---------- 公共读取 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(EXPERIMENT_MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("实验编号", "")) or keyword in str(row.get("实验名称", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("实验状态") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(EXPERIMENT_MODULE, entry_id)

    def latest_generation(self, dataset_code: str) -> int:
        current = self.datasets.current_generation(dataset_code)
        return int(current.get("代次", 0)) if current else 0

    def generation_refresh(self, dataset_code: str, generation: int) -> str:
        for row in self.datasets.generations(dataset_code):
            if int(row.get("代次", 0)) == generation:
                return str(row.get("最近刷新") or "—")
        return "—"

    # ---------- 复核结论 ----------
    def reviews_for(self, experiment: dict[str, Any]) -> list[dict[str, Any]]:
        self.ensure_seeded()
        experiment_code = str(experiment.get("实验编号") or "")
        rows = [
            dict(row) for row in store.aux_rows(REVIEW_TABLE)
            if str(row.get("实验编号")) == experiment_code
        ]
        return sorted(rows, key=lambda row: (int(row.get("数据集代次", 0)), str(row.get("复核时间"))))

    def decorate_review(self, row: dict[str, Any]) -> dict[str, Any]:
        dataset_code = str(row.get("数据集编号") or "")
        current_generation = self.latest_generation(dataset_code)
        row_generation = int(row.get("数据集代次", 0))
        is_history = row_generation != current_generation
        return {
            **row,
            "当前代次": current_generation,
            "是否为历史": is_history,
            "历史原因": (
                f"数据集已刷新到代次 {current_generation}，该结论基于代次 {row_generation}"
                if is_history
                else ""
            ),
            "每档最小样本量": MIN_GROUP_SAMPLE,
            "可延期": (
                (not is_history)
                and row.get("复核结论") in DEFERRABLE_RESULTS
                and row.get("延期状态") != "已延期"
            ),
        }

    def review_summary(self, experiment: dict[str, Any]) -> dict[str, Any]:
        experiment_code = str(experiment.get("实验编号") or "")
        dataset_code = str(experiment.get("分析数据集") or "")
        current = self.datasets.current_generation(dataset_code)
        current_generation = int(current.get("代次", 0)) if current else 0
        decorated = [self.decorate_review(row) for row in self.reviews_for(experiment)]
        history_rows = [row for row in decorated if row["是否为历史"]]
        # 按代次倒序，历史区最近一代在最上面；再按区间倒序，7 天 -> 14 天。
        history_rows = sorted(
            history_rows,
            key=lambda row: (int(row.get("数据集代次", 0)), window_days(str(row.get("基准区间"))),
                             str(row.get("复核时间"))),
            reverse=True,
        )
        current_rows = [row for row in decorated if not row["是否为历史"]]
        # 同代次下按复核时间排序，最后一条才是最近一次结论；区间只作为同时间的稳定次序。
        current_rows = sorted(
            current_rows,
            key=lambda row: (str(row.get("复核时间") or ""), window_days(str(row.get("基准区间"))), int(row.get("id", 0))),
        )
        latest_current = current_rows[-1] if current_rows else None
        deferred_current = bool(latest_current) and latest_current.get("延期状态") == "已延期"
        # 概览固定为实验当前口径：只跟最新代次与延期结果走，切代次查看历史不回退这里的值。
        overview_window = (
            str(latest_current.get("延期至") or latest_current.get("基准区间"))
            if latest_current and deferred_current
            else str(latest_current.get("基准区间"))
            if latest_current
            else str(experiment.get("基准区间") or DEFAULT_WINDOW)
        )
        overview_stable = {
            "目标度量": experiment.get("目标度量"),
            "基准区间": overview_window,
            "显著阈值": float(experiment.get("显著阈值") or DEFAULT_THRESHOLD),
            "分析数据集": dataset_code,
            "数据集最近刷新代次": current_generation,
            "数据集最近刷新时间": str(current.get("最近刷新") or "—") if current else "—",
            "最小样本量": MIN_GROUP_SAMPLE,
        }

        comparison = None
        other_windows = [
            row for row in decorated
            if latest_current is not None
            and int(row.get("数据集代次", 0)) == int(latest_current.get("数据集代次", 0))
            and str(row.get("基准区间")) != str(latest_current.get("基准区间"))
        ]
        earlier_rows = [
            row for row in decorated
            if latest_current is None or row.get("id") != latest_current.get("id")
        ]
        # 基准区间变化时优先和同代次旧区间对比，避免拿更早代次的数据混在一起。
        if other_windows:
            eligible = sorted(
                other_windows,
                key=lambda row: (str(row.get("复核时间") or ""), int(row.get("id", 0))),
                reverse=True,
            )
        else:
            eligible = sorted(
                earlier_rows,
                key=lambda row: (int(row.get("数据集代次", 0)), str(row.get("复核时间") or ""), int(row.get("id", 0))),
                reverse=True,
            )
        if eligible:
            previous = eligible[0]
            # 当前代次已延期时，新口径指向延期后的区间且尚无结论，不能拿旧区间的样本冒充新结论。
            if deferred_current:
                new_generation = latest_current.get("数据集代次")
                new_window_value = latest_current.get("延期至")
                new_samples = None
                new_result = "待复核"
            else:
                new_generation = latest_current.get("数据集代次") if latest_current else current_generation
                new_window_value = (
                    latest_current.get("基准区间") if latest_current
                    else experiment.get("基准区间") or DEFAULT_WINDOW
                )
                new_samples = latest_current.get("样本量") if latest_current else None
                new_result = latest_current.get("复核结论") if latest_current else "待复核"
            changed = previous.get("基准区间") != new_window_value
            changed_generation = int(previous.get("数据集代次", 0)) != int(new_generation or 0)
            same_metric = str(previous.get("目标度量") or "") == str(experiment.get("目标度量") or "")
            comparison = {
                "旧结论代次": previous.get("数据集代次"),
                "旧基准区间": previous.get("基准区间"),
                "旧样本量": previous.get("样本量"),
                "旧复核结论": previous.get("复核结论"),
                "旧结论是否为历史": bool(previous.get("是否为历史")),
                "新结论代次": new_generation,
                "新基准区间": new_window_value,
                "新样本量": new_samples,
                "新复核结论": new_result,
                "区间是否变化": changed,
                "代次是否变化": changed_generation,
                "同一目标度量": same_metric,
                "样本量不可相加": True,
                "说明": (
                    f"旧结论基于代次 {previous.get('数据集代次')} / {previous.get('基准区间')}"
                    f"（样本量 {previous.get('样本量')}），新结论基于代次 {new_generation} / {new_window_value}"
                    f"（样本量 {new_samples if new_samples is not None else '待复核'}）；"
                    + ("两次基准区间不同，样本量不能相加" if changed else "两代样本各自独立，不能相加")
                    + ("" if same_metric else "；两次复核的目标度量不一致，仅作参考")
                ),
            }

        return {
            "实验编号": experiment_code,
            "实验名称": experiment.get("实验名称"),
            **overview_stable,
            "当前结论": latest_current,
            "当前代次待复核": not current_rows,
            "当前代次需按新区间复核": deferred_current,
            "历史结论": history_rows,
            "全部结论": decorated,
            "数据集代次列表": [
                {
                    "代次": int(row.get("代次", 0)),
                    "最近刷新": str(row.get("最近刷新") or "—"),
                    "是否最新": int(row.get("代次", 0)) == current_generation,
                }
                for row in self.datasets.generations(dataset_code)
            ],
            "分档": {
                bucket: [row for row in current_rows if row.get("复核结论") == bucket]
                for bucket in RESULT_BUCKETS
            },
            "历史分档": {
                bucket: [row for row in history_rows if row.get("复核结论") == bucket]
                for bucket in RESULT_BUCKETS
            },
            "前后对比": comparison,
            "延期提示": (
                (
                    f"数据集已刷新到代次 {current_generation}，旧代次结论仅作历史参考；"
                    f"当前代次尚未复核，请按基准区间 {experiment.get('基准区间') or DEFAULT_WINDOW} 重新提交"
                )
                if not current_rows and decorated
                else (
                    f"最近一次复核为样本不足，基准区间已延至 {latest_current.get('延期至')}；"
                    "请按新区间重新提交复核，旧区间结论保留在历史记录"
                )
                if deferred_current
                else ""
            ),
        }

    def review_overview_rows(self) -> list[dict[str, Any]]:
        """复核页左侧清单：一行一个实验，摘要当前代次结论与历史条数。"""
        rows: list[dict[str, Any]] = []
        for experiment in store.rows(EXPERIMENT_MODULE):
            summary = self.review_summary(experiment)
            current = summary["当前结论"]
            rows.append({
                "id": experiment.get("id"),
                "实验编号": summary["实验编号"],
                "实验名称": summary["实验名称"],
                "目标度量": summary["目标度量"],
                "基准区间": summary["基准区间"],
                "显著阈值": summary["显著阈值"],
                "分析数据集": summary["分析数据集"],
                "数据集最近刷新代次": summary["数据集最近刷新代次"],
                "数据集最近刷新时间": summary["数据集最近刷新时间"],
                "当前复核结论": current.get("复核结论") if current else "待复核",
                "当前样本量": current.get("样本量") if current else None,
                "历史结论数": len(summary["历史结论"]),
                "当前代次待复核": summary["当前代次待复核"],
            })
        return rows

    # ---------- 提交复核 ----------
    def submit_review(
        self,
        experiment: dict[str, Any],
        *,
        generation: int | None = None,
        window: str | None = None,
    ) -> dict[str, Any]:
        """提交复核：同一实验 + 同一代次 + 同一区间只生成一条结论。"""
        self.ensure_seeded()
        experiment_code = str(experiment.get("实验编号") or "")
        dataset_code = str(experiment.get("分析数据集") or "")
        target_generation = int(generation or self.latest_generation(dataset_code))
        target_window = str(window or experiment.get("基准区间") or DEFAULT_WINDOW)
        threshold = float(experiment.get("显著阈值") or DEFAULT_THRESHOLD)

        latest_generation = self.latest_generation(dataset_code)
        if target_generation != latest_generation:
            return {
                "created": False,
                "review": None,
                "message": (
                    f"代次 {target_generation} 不是数据集最近刷新代次 {latest_generation}，"
                    "历史代次只保留既有结论，不生成新结论"
                ),
            }

        existing = [
            row for row in store.aux_rows(REVIEW_TABLE)
            if str(row.get("实验编号")) == experiment_code
            and int(row.get("数据集代次", 0)) == target_generation
            and str(row.get("基准区间")) == target_window
        ]
        if existing:
            row = self.decorate_review(existing[-1])
            return {
                "created": False,
                "review": row,
                "message": (
                    f"{experiment_code} 在代次 {target_generation} / 基准区间 {target_window} 已有复核结论，"
                    "重复提交未生成新记录"
                ),
            }
        if target_window not in WINDOW_TIERS:
            return {
                "created": False,
                "review": None,
                "message": f"基准区间 {target_window} 不在允许的档位（{'、'.join(WINDOW_TIERS)}）里",
            }
        if threshold <= 0 or threshold >= 1:
            return {
                "created": False,
                "review": None,
                "message": f"显著阈值 {threshold} 必须在 0 与 1 之间",
            }

        conclusion = compute_conclusion(
            experiment_code=experiment_code,
            generation=target_generation,
            window=target_window,
            threshold=threshold,
            target_metric=str(experiment.get("目标度量") or ""),
        )
        rows = store.aux_rows(REVIEW_TABLE)
        review = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            **conclusion,
            "数据集编号": dataset_code,
            "数据集最近刷新": self.generation_refresh(dataset_code, target_generation),
            "复核时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "复核人": "值班管理员",
            "延期状态": "未延期",
            "延期至": None,
            "延期申请": [],
        }
        rows.append(review)
        return {
            "created": True,
            "review": self.decorate_review(review),
            "message": f"{experiment_code} 复核完成：{review['复核结论']}",
        }

    # ---------- 样本不足：延期 ----------
    def request_deferral(
        self,
        experiment: dict[str, Any],
        *,
        generation: int | None = None,
        window: str | None = None,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """样本不足时允许逐档延期一次；延期只推进待复核区间，不改写既有结论。"""
        self.ensure_seeded()
        experiment_code = str(experiment.get("实验编号") or "")
        dataset_code = str(experiment.get("分析数据集") or "")
        current_generation = self.latest_generation(dataset_code)
        target_generation = int(generation or current_generation)
        base_window = str(window or experiment.get("基准区间") or DEFAULT_WINDOW)

        if target_generation != current_generation:
            return False, f"代次 {target_generation} 不是数据集最近刷新代次，历史代次不允许延期", None

        review = next((
            row for row in store.aux_rows(REVIEW_TABLE)
            if str(row.get("实验编号")) == experiment_code
            and int(row.get("数据集代次", 0)) == target_generation
            and str(row.get("基准区间")) == base_window
        ), None)
        if review is None:
            return False, "请先提交该代次的复核，再基于复核结论申请延期", None
        if review.get("复核结论") not in DEFERRABLE_RESULTS:
            return False, f"复核结论为「{review.get('复核结论')}」，只有样本不足才允许延期", None
        if review.get("延期状态") == "已延期":
            return False, f"该复核已延期至 {review.get('延期至')}，不允许重复延期", None

        target_window = next_window(base_window)
        if target_window is None:
            return False, f"基准区间 {base_window} 已是最大档，无法继续延期", None
        if window_days(target_window) <= window_days(base_window):
            return False, "延期区间必须大于当前基准区间", None

        review["延期状态"] = "已延期"
        review["延期至"] = target_window
        review["延期申请"] = [{
            "原基准区间": base_window,
            "新基准区间": target_window,
            "申请时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "申请原因": "样本不足，逐档延长基准区间等待样本累积",
            "状态": "已生效",
        }]
        experiment["基准区间"] = target_window
        return True, f"样本不足，基准区间由 {base_window} 延至 {target_window}，请按新区间重新提交复核", review

    # ---------- 数据集引用与代次一致性 ----------
    def referenced_datasets(self) -> list[dict[str, Any]]:
        """其它业务面的数据集清单：按复核当前代次同步展示被哪些实验引用。"""
        items, _ = self.datasets.list_decorated(page=1, size=10000)
        return items

    # ---------- 原有动作 ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field for field in ["实验编号", "实验名称", "分析数据集"]
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing
        dataset_code = str(values.get("分析数据集"))
        if self.datasets.current_generation(dataset_code) is None:
            return None, [f"分析数据集 {dataset_code} 不存在，无法登记实验"]
        rows = store.rows(EXPERIMENT_MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({
            "实验编号": values.get("实验编号"),
            "实验名称": values.get("实验名称"),
            "分析数据集": dataset_code,
            "分组字段": values.get("分组字段") or "用户分层",
            "目标度量": values.get("目标度量") or "转化率",
            "基准区间": values.get("基准区间") or DEFAULT_WINDOW,
            "显著阈值": str(values.get("显著阈值") or DEFAULT_THRESHOLD),
            "实验状态": "草稿",
        })
        entry["status"] = "草稿"
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(EXPERIMENT_MODULE, entry_id)
        if entry is None:
            return None, f"分析实验 {entry_id} 不存在或已归档"
        rules = {"启动实验": "运行中", "结束实验": "已完成", "关闭实验": "已关闭"}
        if action not in rules:
            return None, f"动作「{action}」不属于分析实验管理可执行范围"
        target = rules[action]
        entry["实验状态"] = target
        entry["status"] = target
        entry["pending"] = target != "已关闭"
        entry["abnormal"] = False
        return entry, f"分析实验已{action}"
