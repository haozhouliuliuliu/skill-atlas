"""从原始抓取结果构建能力位索引。

这一层是**纯逻辑**：输入是已抓取的仓库列表，输出是排好序的能力位索引，
不碰文件系统、不碰网络，因此可以完整地单元测试。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .models import Repo
from .quality import low_value_reason
from .scoring import quality_score, rank_score, relevance
from .slots import SLOT_EXCLUDE, SLOT_PIN, Slot, all_slots, assign_slot, slot_by_name

#: 榜单窗口 -> 中文标签
WINDOW_LABELS: dict[str, str] = {"day": "日", "week": "周", "month": "月"}
WINDOW_ORDER: tuple[str, ...] = ("day", "week", "month")

#: 数据来源标签
SOURCE_RANKING = "榜单"
SOURCE_SEARCH = "检索"

#: 相关性加成所对应的展示名
REL_MANUAL = "人工"
REL_RANKING = "榜单"
REL_NAME = "名字"
REL_TOPICS = "topics"
REL_DESCRIPTION = "描述"
REL_NONE = "—"


@dataclass
class RankingResult:
    """一次「新建榜」抓取的结果。"""

    window: str
    repos: list[Repo] = field(default_factory=list)
    since: str = ""
    total_count: int = 0
    fetched_at: str = ""


@dataclass
class Candidate:
    """一个进入索引的候选仓库，附带它在各能力位上的相关性。"""

    repo: Repo
    sources: set[str] = field(default_factory=set)
    #: 榜单窗口 -> 名次
    ranks: dict[str, int] = field(default_factory=dict)
    #: 能力位名 -> (相关性等级, 判定依据)。键集合同时也是**归位结果**。
    slots: dict[str, tuple[int, str]] = field(default_factory=dict)
    score: int = 0

    # -- 便捷访问 ------------------------------------------------------
    @property
    def full_name(self) -> str:
        return self.repo.full_name

    def add_slot(self, slot: Slot, level: int, why: str) -> None:
        # 同一能力位只保留更强的判定
        current = self.slots.get(slot.name)
        if current is None or level > current[0]:
            self.slots[slot.name] = (level, why)

    def relevance_why(self, slot_name: str) -> str:
        return self.slots.get(slot_name, (0, REL_NONE))[1]

    def rank_score(self, slot_name: str) -> int:
        return rank_score(self.score, self.relevance_why(slot_name))

    @property
    def windows(self) -> str:
        return "/".join(WINDOW_LABELS[w] for w in WINDOW_ORDER if w in self.ranks)

    @property
    def best_rank(self) -> int | None:
        return min(self.ranks.values()) if self.ranks else None

    @property
    def source_label(self) -> str:
        return "/".join(sorted(self.sources))

    @property
    def is_from_ranking(self) -> bool:
        return bool(self.ranks)


@dataclass
class Atlas:
    """构建好的能力位索引。"""

    candidates: dict[str, Candidate] = field(default_factory=dict)
    by_slot: dict[str, list[Candidate]] = field(default_factory=dict)
    junk: list[tuple[Repo, str]] = field(default_factory=list)
    rankings: dict[str, RankingResult] = field(default_factory=dict)
    enrichment: dict[str, list[Repo]] = field(default_factory=dict)

    def cap(self, per_slot: int) -> dict[str, list[Candidate]]:
        """每个能力位只保留前 N 个候选（避免能力位笔记被稀释）。"""
        return {slot: recs[:per_slot] for slot, recs in self.by_slot.items()}

    def note_repos(self, capped: dict[str, list[Candidate]]) -> list[Candidate]:
        """需要写独立笔记的仓库：榜单条目 + 任一能力位的入选候选。"""
        names = {c.full_name for c in self.candidates.values() if c.is_from_ranking}
        for recs in capped.values():
            for candidate in recs:
                names.add(candidate.full_name)
        chosen = [c for c in self.candidates.values() if c.full_name in names]
        chosen.sort(key=lambda c: (-c.score, -(c.repo.stars)))
        return chosen

    def slot_stats(self, capped: dict[str, list[Candidate]]):
        """按能力位定义顺序给出 (slot, 全部候选数, 展示候选列表)。"""
        for slot in all_slots():
            all_recs = self.by_slot.get(slot.name, [])
            yield slot, len(all_recs), capped.get(slot.name, [])


def build_atlas(
    rankings: dict[str, RankingResult],
    enrichment: dict[str, list[Repo]],
) -> Atlas:
    """合并榜单与定向检索结果，产出排好序的能力位索引。"""
    atlas = Atlas(rankings=dict(rankings), enrichment=dict(enrichment))
    #: 判定为不可复用的仓库，按 full_name 去重。
    #: 一个仓库可能同时出现在日榜和周榜里，若按出现次数统计，
    #: 垃圾数量会被重复计算（实测 92 个唯一仓库会被数成 115 条记录）。
    junk_seen: dict[str, tuple[Repo, str]] = {}

    def ensure(repo: Repo) -> Candidate:
        candidate = atlas.candidates.get(repo.full_name)
        if candidate is None:
            candidate = Candidate(repo=repo)
            atlas.candidates[repo.full_name] = candidate
        else:
            _merge_metrics(candidate.repo, repo)
        return candidate

    # 1) 榜单数据
    for window in WINDOW_ORDER:
        result = rankings.get(window)
        if not result:
            continue
        for rank, repo in enumerate(result.repos, 1):
            reason = low_value_reason(repo)
            if reason:
                junk_seen.setdefault(repo.full_name, (repo, reason))
                continue
            candidate = ensure(repo)
            candidate.sources.add(SOURCE_RANKING)
            candidate.ranks[window] = rank

    # 2) 定向检索补全
    for slot_name, repos in enrichment.items():
        slot = slot_by_name(slot_name)
        if slot is None:
            continue
        for repo in repos:
            if low_value_reason(repo):
                continue
            # 先判相关性再建档：关键词完全没命中的结果不该进入候选池，
            # 否则 candidates 会被大量无关仓库稀释（也会让笔记数量虚高）。
            level, why = relevance(repo, slot.query)
            if level == 0:
                continue
            candidate = ensure(repo)
            candidate.sources.add(SOURCE_SEARCH)
            candidate.add_slot(slot, level, why)

    # 3) 榜单条目的归位
    for candidate in atlas.candidates.values():
        if candidate.is_from_ranking:
            slot = assign_slot(candidate.repo)
            if slot.name != "待归位":
                candidate.add_slot(slot, 3, REL_RANKING)

    # 4) 打分
    for candidate in atlas.candidates.values():
        candidate.score = quality_score(candidate.repo)

    # 5) 按能力位聚集并排序
    for candidate in atlas.candidates.values():
        for slot_name in candidate.slots:
            atlas.by_slot.setdefault(slot_name, []).append(candidate)
    for slot_name, recs in atlas.by_slot.items():
        recs.sort(
            key=lambda c, s=slot_name: (
                -c.rank_score(s),
                -c.score,
                -c.repo.stars,
                c.full_name,
            )
        )

    # 6) 人工校准层
    for slot_name, exclusions in SLOT_EXCLUDE.items():
        recs = atlas.by_slot.get(slot_name)
        if not recs:
            continue
        atlas.by_slot[slot_name] = [c for c in recs if c.full_name not in exclusions]
    for slot_name, pinned in SLOT_PIN.items():
        for candidate in atlas.by_slot.get(slot_name, []):
            if candidate.full_name == pinned:
                candidate.slots[slot_name] = (99, REL_MANUAL)

    atlas.junk = sorted(junk_seen.values(), key=lambda pair: -pair[0].stars)
    return atlas


def _merge_metrics(target: Repo, other: Repo) -> None:
    """同一仓库在不同来源出现时，各指标取更强的那个。"""
    target.stars = max(target.stars, other.stars)
    target.forks = max(target.forks, other.forks)
    target.open_issues = max(target.open_issues, other.open_issues)
    target.size_kb = max(target.size_kb, other.size_kb)
    for attr in ("description", "language", "license", "pushed_at", "created_at",
                 "homepage"):
        if not getattr(target, attr) and getattr(other, attr):
            setattr(target, attr, getattr(other, attr))
    if not target.topics and other.topics:
        target.topics = list(other.topics)


def today() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d")
