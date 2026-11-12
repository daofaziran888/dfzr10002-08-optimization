"""实验复核的数据口径与判定规则。

这里只放纯函数和示例样本，不依赖 store：数据集代次、复核结论都要按同一套
口径重算，避免前端或路由层各算一份导致数字对不上。
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

# 每组至少 100 个样本才做显著性判定；不足时只给「样本不足」，不给显著结论。
MIN_GROUP_SAMPLE = 100
# 样本不足时可以延期到下一档基准区间；只允许逐档延长，不允许回退。
WINDOW_TIERS = ["7 天", "14 天", "28 天"]
DEFAULT_WINDOW = "7 天"
DEFAULT_THRESHOLD = 0.05

# (实验编号, 数据集代次, 基准区间) -> (实验组样本量, 实验组转化数, 对照组样本量, 对照组转化数)
# 同一次实验在两个代次、两个基准区间下各自记一份样本，绝不复用或累加。
SAMPLE_FIXTURES: dict[tuple[str, int, str], tuple[int, int, int, int]] = {
    ("EXPE-0003", 1, "7 天"): (52, 9, 48, 7),
    ("EXPE-0003", 2, "7 天"): (127, 24, 124, 14),
    ("EXPE-0003", 3, "14 天"): (268, 53, 264, 31),
    ("EXPE-0004", 1, "7 天"): (150, 22, 148, 10),
    ("EXPE-0004", 2, "7 天"): (20, 3, 18, 2),
    ("EXPE-0004", 3, "7 天"): (20, 3, 18, 2),
    ("EXPE-0005", 1, "7 天"): (512, 61, 506, 42),
    ("EXPE-0005", 2, "7 天"): (238, 31, 234, 22),
    ("EXPE-0005", 3, "14 天"): (470, 55, 466, 48),
}

# 初始化时已经提交过的复核（数据集代次、区间、复核时间），结论由同一套规则现算。
SEED_REVIEWS: list[dict[str, Any]] = [
    {"实验编号": "EXPE-0003", "数据集代次": 1, "基准区间": "7 天", "复核时间": "2026-11-10 09:20"},
    {"实验编号": "EXPE-0003", "数据集代次": 2, "基准区间": "7 天", "复核时间": "2026-11-11 10:05"},
    {"实验编号": "EXPE-0003", "数据集代次": 3, "基准区间": "14 天", "复核时间": "2026-11-12 10:30"},
    {"实验编号": "EXPE-0004", "数据集代次": 1, "基准区间": "7 天", "复核时间": "2026-11-10 11:15"},
    {"实验编号": "EXPE-0004", "数据集代次": 2, "基准区间": "7 天", "复核时间": "2026-11-11 11:40"},
    {"实验编号": "EXPE-0005", "数据集代次": 1, "基准区间": "7 天", "复核时间": "2026-11-11 12:20"},
    {"实验编号": "EXPE-0005", "数据集代次": 2, "基准区间": "7 天", "复核时间": "2026-11-11 13:10"},
]


# 复核结论的三档口径，前端分栏与后端判定共用。
RESULT_BUCKETS = ["显著", "不显著", "样本不足"]


def window_days(window: str) -> int:
    digits = "".join(ch for ch in str(window) if ch.isdigit())
    return int(digits) if digits else 0


def next_window(window: str) -> str | None:
    """样本不足时允许逐档延长基准区间；已是最大档时返回 None。"""
    if window not in WINDOW_TIERS:
        return None
    index = WINDOW_TIERS.index(window)
    return WINDOW_TIERS[index + 1] if index + 1 < len(WINDOW_TIERS) else None


def resolve_samples(experiment_code: str, generation: int, window: str) -> tuple[int, int, int, int]:
    """取某个实验在某个数据集代次、某个基准区间下的样本。

    没有预置样本时按代次和区间确定性生成，保证同一代次重复复核得到同一份样本。
    """
    key = (experiment_code, int(generation), window)
    if key in SAMPLE_FIXTURES:
        return SAMPLE_FIXTURES[key]
    digest = hashlib.sha256(f"{experiment_code}|{generation}|{window}".encode("utf-8")).hexdigest()
    seed = int(digest, 16)
    days = max(window_days(window), 1)
    per_day = 30 + seed % 25
    exp_n = per_day * days + (seed >> 8) % 7
    ctrl_n = max(per_day - 2, 1) * days + (seed >> 16) % 7
    exp_x = round(exp_n * (0.06 + ((seed >> 24) % 50) / 1000))
    ctrl_x = round(ctrl_n * (0.035 + ((seed >> 32) % 40) / 1000))
    return exp_n, exp_x, ctrl_n, ctrl_x


def two_proportion_p(exp_n: int, exp_x: int, ctrl_n: int, ctrl_x: int) -> float | None:
    """双比例 z 检验的双侧 p 值；样本退化时返回 None。"""
    if exp_n <= 0 or ctrl_n <= 0:
        return None
    pooled = (exp_x + ctrl_x) / (exp_n + ctrl_n)
    variance = pooled * (1 - pooled) * (1 / exp_n + 1 / ctrl_n)
    if variance <= 0:
        return None
    z = (exp_x / exp_n - ctrl_x / ctrl_n) / math.sqrt(variance)
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))

def compute_conclusion(
    *,
    experiment_code: str,
    generation: int,
    window: str,
    threshold: float,
    target_metric: str,
) -> dict[str, Any]:
    """按数据集代次 + 基准区间重算一次复核结论。"""
    exp_n, exp_x, ctrl_n, ctrl_x = resolve_samples(experiment_code, generation, window)
    result: dict[str, Any] = {
        "实验编号": experiment_code,
        "数据集代次": int(generation),
        "基准区间": window,
        "目标度量": target_metric,
        "显著阈值": threshold,
        "实验组样本量": exp_n,
        "对照组样本量": ctrl_n,
        "样本量": exp_n + ctrl_n,
        "实验组转化数": exp_x,
        "对照组转化数": ctrl_x,
        "p值": None,
        "复核结论": "样本不足",
        "判定说明": (
            f"实验组 {exp_n} / 对照组 {ctrl_n} 未达到每组 {MIN_GROUP_SAMPLE} 的最小样本量，"
            "样本不足，不给出显著结论"
        ),
    }
    if exp_n < MIN_GROUP_SAMPLE or ctrl_n < MIN_GROUP_SAMPLE:
        return result

    p_value = two_proportion_p(exp_n, exp_x, ctrl_n, ctrl_x)
    if p_value is None:
        result["判定说明"] = "样本分布退化，无法计算显著阈值，按样本不足处理"
        return result

    rounded = round(p_value, 4)
    result["p值"] = rounded
    if p_value < threshold:
        result["复核结论"] = "显著"
        result["判定说明"] = f"p={rounded} < 阈值 {threshold}，差异显著"
    else:
        result["复核结论"] = "不显著"
        result["判定说明"] = f"p={rounded} ≥ 阈值 {threshold}，差异不显著"
    return result


def build_seed_reviews(
    experiments: list[dict[str, Any]],
    generation_refresh: dict[tuple[str, int], str],
) -> list[dict[str, Any]]:
    """把预置复核展开成带结论的明细行；是否历史在读取时再按当前代次判定。"""
    by_code = {str(row.get("实验编号")): row for row in experiments}
    rows: list[dict[str, Any]] = []
    for index, seed in enumerate(SEED_REVIEWS, start=1):
        experiment = by_code.get(seed["实验编号"])
        if experiment is None:
            continue
        dataset_code = str(experiment.get("分析数据集") or "")
        generation = int(seed["数据集代次"])
        window = str(seed["基准区间"])
        conclusion = compute_conclusion(
            experiment_code=str(experiment.get("实验编号")),
            generation=generation,
            window=window,
            threshold=float(experiment.get("显著阈值") or DEFAULT_THRESHOLD),
            target_metric=str(experiment.get("目标度量") or ""),
        )
        rows.append({
            "id": index,
            **conclusion,
            "数据集编号": dataset_code,
            "数据集最近刷新": generation_refresh.get((dataset_code, generation), "—"),
            "复核时间": seed["复核时间"],
            "复核人": "值班管理员",
            "延期状态": "未延期",
            "延期至": None,
            "延期申请": [],
        })
    return rows


def ensure_seed_reviews() -> None:
    """服务启动时展开一次预置复核，保证数据集/导出清单也能看到一致的复核口径。"""
    from app.store import store  # 延迟导入，避免 store 初始化时反向依赖

    rows = store.aux_rows("review")
    if rows:
        return
    refresh_map = {
        (str(row.get("数据集编号")), int(row.get("代次", 0))): str(row.get("最近刷新") or "—")
        for row in store.aux_rows("dataset_generation")
    }
    rows.extend(build_seed_reviews(store.rows("experiment"), refresh_map))


def latest_review(review_rows: list[dict[str, Any]], experiment_code: str) -> dict[str, Any] | None:
    """某实验最新一次的复核：先比数据集代次，再比复核时间。"""
    candidates = [
        row for row in review_rows if str(row.get("实验编号")) == experiment_code
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (int(row.get("数据集代次", 0)), str(row.get("复核时间") or "")),
    )
