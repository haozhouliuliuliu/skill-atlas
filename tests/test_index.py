"""索引构建（index）的测试。"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from skill_atlas.index import (  # noqa: E402
    SOURCE_RANKING,
    SOURCE_SEARCH,
    Atlas,
    RankingResult,
    build_atlas,
)
from skill_atlas.models import Repo  # noqa: E402


def repo(name: str, **kwargs) -> Repo:
    base = dict(
        description="a real project",
        language="Python",
        stars=1000,
        forks=100,
        open_issues=5,
        size_kb=8000,
        license="MIT",
        pushed_at="2026-10-09T00:00:00Z",
    )
    base.update(kwargs)
    return Repo(full_name=name, **base)


#: 能命中「本地推理引擎」检索式的描述。
#: 检索式是 '"llama.cpp" OR ollama OR vllm OR "inference engine"'，
#: 描述里必须真的出现这些词，否则相关性为 0，会被正确地丢弃。
LOCAL = "a local inference engine compatible with ollama"


def ranking(window: str, repos: list[Repo]) -> RankingResult:
    return RankingResult(window=window, repos=repos, since="2026-10-01T00:00:00Z",
                         total_count=len(repos))


class TestJunkHandling(unittest.TestCase):
    def test_low_value_repos_never_become_candidates(self) -> None:
        spam = repo("spammer/KMS-Pico", description="optimize your professional desktop",
                    size_kb=2, forks=0, open_issues=0, license=None, language=None)
        atlas = build_atlas({"day": ranking("day", [spam])}, {})
        self.assertEqual(atlas.candidates, {})
        self.assertEqual(len(atlas.junk), 1)

    def test_junk_is_deduplicated_across_windows(self) -> None:
        """同一垃圾仓库同时出现在日榜与周榜时，只应统计一次。"""
        spam = repo("spammer/x", description="professional desktop utility",
                    size_kb=2, forks=0, open_issues=0, license=None, language=None)
        atlas = build_atlas(
            {"day": ranking("day", [spam]), "week": ranking("week", [spam])}, {}
        )
        self.assertEqual(len(atlas.junk), 1)

    def test_junk_is_carried_with_its_reason(self) -> None:
        spam = repo("spammer/x", size_kb=2, forks=0, open_issues=0, license=None,
                    language=None)
        atlas = build_atlas({"day": ranking("day", [spam])}, {})
        _repo, reason = atlas.junk[0]
        self.assertIn("仅README", reason)


class TestSources(unittest.TestCase):
    def test_ranking_repo_is_tagged_and_assigned(self) -> None:
        chain = repo("langchain-ai/langchain", description="The agent engineering platform.")
        atlas = build_atlas({"week": ranking("week", [chain])}, {})
        candidate = atlas.candidates["langchain-ai/langchain"]
        self.assertIn(SOURCE_RANKING, candidate.sources)
        self.assertEqual(candidate.ranks, {"week": 1})
        self.assertIn("Agent 编排与 Harness", candidate.slots)
        self.assertEqual(candidate.relevance_why("Agent 编排与 Harness"), "榜单")

    def test_enriched_repo_is_tagged_by_search(self) -> None:
        ollama = repo("ollama/ollama", description="Get up and running with local models")
        atlas = build_atlas({}, {"本地推理引擎": [ollama]})
        candidate = atlas.candidates["ollama/ollama"]
        self.assertIn(SOURCE_SEARCH, candidate.sources)
        self.assertEqual(candidate.relevance_why("本地推理引擎"), "名字")

    def test_irrelevant_enriched_repo_is_dropped(self) -> None:
        """检索式关键词完全没命中的结果必须丢弃。"""
        unrelated = repo("someone/unrelated", description="a knitting pattern archive",
                         topics=["craft"])
        atlas = build_atlas({}, {"日志与监控": [unrelated]})
        self.assertNotIn("someone/unrelated", atlas.candidates)

    def test_repo_can_belong_to_several_slots(self) -> None:
        shared = repo("someone/tool", description="agent memory and knowledge graph engine")
        atlas = build_atlas({}, {"Agent 记忆与检索": [shared], "知识库与本体": [shared]})
        candidate = atlas.candidates["someone/tool"]
        self.assertEqual(set(candidate.slots), {"Agent 记忆与检索", "知识库与本体"})

    def test_metrics_are_merged_across_sources(self) -> None:
        thin = repo("a/b", stars=100, forks=1)
        rich = repo("a/b", stars=900, forks=90, description=LOCAL)
        atlas = build_atlas(
            {"day": ranking("day", [thin])},
            {"本地推理引擎": [rich]},
        )
        candidate = atlas.candidates["a/b"]
        self.assertEqual(candidate.repo.stars, 900)
        self.assertEqual(candidate.repo.forks, 90)


class TestOrdering(unittest.TestCase):
    def test_rank_score_then_quality_then_stars(self) -> None:
        top = repo("better/project", stars=50_000, forks=5_000, description=LOCAL)
        low = repo("worse/project", stars=500, forks=20, description=LOCAL)
        atlas = build_atlas({}, {"本地推理引擎": [low, top]})
        ranked = [c.full_name for c in atlas.by_slot["本地推理引擎"]]
        self.assertEqual(ranked[0], "better/project")

    def test_ordering_is_deterministic(self) -> None:
        repos = [repo(f"o{i}/p{i}", description=LOCAL) for i in range(20)]
        first = build_atlas({}, {"本地推理引擎": list(repos)})
        second = build_atlas({}, {"本地推理引擎": list(reversed(repos))})
        self.assertEqual(
            [c.full_name for c in first.by_slot["本地推理引擎"]],
            [c.full_name for c in second.by_slot["本地推理引擎"]],
        )

    def test_manual_exclusion_is_applied(self) -> None:
        """apache/ranger 在 SLOT_EXCLUDE 里登记过。"""
        ranger = repo(
            "apache/ranger",
            description="a file manager for data platforms",
        )
        atlas = build_atlas({}, {"磁盘与文件管理": [ranger]})
        self.assertNotIn(
            "apache/ranger", [c.full_name for c in atlas.by_slot["磁盘与文件管理"]]
        )

    def test_description_only_candidate_cannot_steal_the_top_pick(self) -> None:
        """只在描述里被提到的候选，即使指标更强也压不过「名字命中」的候选。

        这是一个**刻意的设计后果**，不是 bug：-15 分描述惩罚意味着
        「比 ollama 更快」这种描述不会让一个项目取代 ollama 本身。
        实测中 21 万星的仓库因此在 18 万星的 ollama 之后。
        """
        mentioned = repo(
            "newlab/ultra-engine",
            description="A local inference engine faster than ollama and vllm.",
            stars=210_000, forks=21_000,
        )
        named = repo("ollama/ollama", description="run models locally",
                     stars=182_604, forks=18_185)
        atlas = build_atlas({}, {"本地推理引擎": [mentioned, named]})
        ranked = [c.full_name for c in atlas.by_slot["本地推理引擎"]]
        self.assertEqual(ranked[0], "ollama/ollama")
        self.assertEqual(
            atlas.candidates["newlab/ultra-engine"].relevance_why("本地推理引擎"),
            "描述",
        )


class TestCappingAndNotes(unittest.TestCase):
    def _atlas(self, n: int) -> Atlas:
        repos = [repo(f"o{i}/p{i}", stars=10_000 - i * 10, description=LOCAL)
                 for i in range(n)]
        return build_atlas({}, {"本地推理引擎": repos})

    def test_cap_limits_candidates_per_slot(self) -> None:
        atlas = self._atlas(30)
        capped = atlas.cap(5)
        self.assertEqual(len(capped["本地推理引擎"]), 5)
        self.assertEqual(len(atlas.by_slot["本地推理引擎"]), 30)

    def test_note_repos_covers_ranking_and_capped(self) -> None:
        ranked = repo("ranked/one", description="The agent engineering platform.")
        atlas = build_atlas(
            {"day": ranking("day", [ranked])},
            {"本地推理引擎": [repo("o0/p0", description=LOCAL)]},
        )
        names = {c.full_name for c in atlas.note_repos(atlas.cap(10))}
        self.assertIn("ranked/one", names)
        self.assertIn("o0/p0", names)

    def test_slot_stats_follow_the_slot_definition_order(self) -> None:
        atlas = build_atlas({}, {"本地推理引擎": [repo("o0/p0", description=LOCAL)]})
        stats = list(atlas.slot_stats(atlas.cap(10)))
        self.assertEqual(len(stats), 54)
        self.assertEqual(stats[0][0].name, "Agent Skill 规范与范例")


if __name__ == "__main__":
    unittest.main()
