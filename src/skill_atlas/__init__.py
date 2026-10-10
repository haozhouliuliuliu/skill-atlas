"""skill-atlas —— 把 GitHub 检索结果组织成「可替换的能力位索引」。

设计目标
--------
做项目时最贵的一步不是写代码，而是不知道该用什么。
本工具把候选项目按「能力位」（一个会被替换的具体位置）组织好，
每个位置放多个候选、按**可验证指标**排序，于是"发现更好的就换掉"才有落点。

零运行时依赖：只用 Python 标准库。
"""

__version__ = "0.1.0"

from .index import Atlas, Candidate, RankingResult, build_atlas
from .models import Repo
from .quality import is_low_value, low_value_reason
from .query import Match, match_slots, query_atlas
from .scoring import activity_score, quality_score, rank_score, relevance
from .slots import (
    SLOTS,
    SLOT_EXCLUDE,
    SLOT_PIN,
    UNASSIGNED,
    Slot,
    all_slots,
    assign_slot,
    slot_by_name,
)
from .vault import render_vault, slot_index

__all__ = [
    "__version__",
    # data model
    "Repo",
    # quality
    "is_low_value",
    "low_value_reason",
    # scoring
    "activity_score",
    "quality_score",
    "rank_score",
    "relevance",
    # slots
    "Slot",
    "SLOTS",
    "SLOT_PIN",
    "SLOT_EXCLUDE",
    "UNASSIGNED",
    "all_slots",
    "assign_slot",
    "slot_by_name",
    # pipeline
    "Atlas",
    "Candidate",
    "RankingResult",
    "build_atlas",
    "render_vault",
    "slot_index",
    # retrieval
    "Match",
    "match_slots",
    "query_atlas",
]
