"""打分与排序的回归测试。

每一条都对应一个真实踩过的坑 —— 这些断言在修 bug 之前都是**失败**的。
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from skill_atlas import Repo, activity_score, quality_score, rank_score, relevance  # noqa: E402
from skill_atlas.scoring import query_words, term_hit  # noqa: E402


def pushed_days_ago(days: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make(**kwargs) -> Repo:
    base = dict(
        full_name="owner/name",
        description="a tool",
        language="Python",
        stars=1000,
        forks=100,
        open_issues=10,
        size_kb=5000,
        license="MIT",
        pushed_at=pushed_days_ago(1),
    )
    base.update(kwargs)
    return Repo(**base)


class TestQualityScoreDoesNotSaturate(unittest.TestCase):
    """质量分必须在高星区间仍然有区分度。"""

    def test_huge_project_beats_small_project(self) -> None:
        """d3/d3（11.3 万星 / 2.26 万 fork）必须高于 bas3line/ascii（697 星 / 40 fork）。

        修 bug 前：bas3line/ascii 得 86 分，d3/d3 只得 84 分 —— 因为 stars/forks
        的对数分母太小，3 万星就满分了。
        """
        d3 = make(
            full_name="d3/d3", stars=113725, forks=22639, size_kb=59348,
            license="ISC", open_issues=100, pushed_at=pushed_days_ago(134),
        )
        small = make(
            full_name="bas3line/ascii", stars=697, forks=40, size_kb=2668,
            license="MIT", open_issues=0, pushed_at=pushed_days_ago(0),
        )
        self.assertGreater(quality_score(d3), quality_score(small))

    def test_star_term_not_saturated_at_30k(self) -> None:
        """3 万星与 18 万星必须拉得开差距（其他条件相同）。"""
        mid = make(stars=30_000, forks=1_000)
        top = make(stars=180_000, forks=1_000)
        self.assertGreater(quality_score(top) - quality_score(mid), 3)

    def test_license_and_size_contribute(self) -> None:
        with_license = make(license="MIT", size_kb=5000)
        without = make(license=None, size_kb=10)
        self.assertGreater(quality_score(with_license), quality_score(without))


class TestActivityScore(unittest.TestCase):
    def test_steps(self) -> None:
        self.assertEqual(activity_score(make(pushed_at=pushed_days_ago(1))), 1.0)
        self.assertEqual(activity_score(make(pushed_at=pushed_days_ago(20))), 0.8)
        self.assertEqual(activity_score(make(pushed_at=pushed_days_ago(60))), 0.5)
        self.assertEqual(activity_score(make(pushed_at=pushed_days_ago(300))), 0.2)
        self.assertEqual(activity_score(make(pushed_at=pushed_days_ago(900))), 0.05)

    def test_dormant_repo_is_penalised(self) -> None:
        """Tampermonkey 的真实情况：558 天未推送。"""
        fresh = make(pushed_at=pushed_days_ago(0))
        dormant = make(pushed_at=pushed_days_ago(558))
        self.assertGreater(quality_score(fresh) - quality_score(dormant), 10)


class TestTermHit(unittest.TestCase):
    """关键词必须按词边界匹配。"""

    def test_zep_does_not_match_zephyr(self) -> None:
        """检索词 zep 曾经命中 zephyrproject/zephyr 和 apache/zeppelin。"""
        self.assertFalse(term_hit("zephyrproject/zephyr", "zep"))
        self.assertFalse(term_hit("apache/zeppelin", "zep"))
        self.assertTrue(term_hit("getzep/zep", "zep"))

    def test_dify_does_not_match_modify(self) -> None:
        self.assertFalse(term_hit("someone/modify-tool", "dify"))
        self.assertTrue(term_hit("langgenius/dify", "dify"))

    def test_separators_count_as_boundaries(self) -> None:
        self.assertTrue(term_hit("vllm-project/vllm", "vllm"))
        self.assertTrue(term_hit("d3.js charts", "d3"))

    def test_phrase_is_substring(self) -> None:
        self.assertTrue(term_hit("a chart library for react", "chart library"))
        self.assertFalse(term_hit("a charting library", "chart library"))

    def test_cjk_is_substring(self) -> None:
        self.assertTrue(term_hit("艺术动画skill", "动画"))


class TestRelevance(unittest.TestCase):
    TERMS = 'd3 OR "animation library" OR "chart library" OR gsap'

    def test_name_hit_is_strongest(self) -> None:
        repo = make(full_name="d3/d3", description="bring data to life",
                    topics=["charts"])
        self.assertEqual(relevance(repo, self.TERMS), (3, "名字"))

    def test_topics_hit(self) -> None:
        """freeCodeCamp 的 topics 里真的有 d3（课程教 D3）。"""
        repo = make(full_name="freeCodeCamp/freeCodeCamp",
                    description="open-source codebase and curriculum",
                    topics=["d3", "javascript"])
        self.assertEqual(relevance(repo, self.TERMS), (2, "topics"))

    def test_description_only(self) -> None:
        repo = make(full_name="someone/thing", description="uses gsap internally",
                    topics=[])
        self.assertEqual(relevance(repo, self.TERMS), (1, "描述"))

    def test_no_hit(self) -> None:
        repo = make(full_name="someone/thing", description="a database",
                    topics=["sql"])
        self.assertEqual(relevance(repo, self.TERMS), (0, "—"))

    def test_empty_query_treated_as_ranking_source(self) -> None:
        self.assertEqual(relevance(make(), ""), (3, "榜单"))


class TestRankScore(unittest.TestCase):
    def test_topics_cannot_hijack_without_a_quality_margin(self) -> None:
        """freeCodeCamp（100 分，topics 命中）不得压过 d3/d3（84 分，名字命中）。"""
        self.assertLess(rank_score(100, "topics"), rank_score(84, "名字"))

    def test_no_cliff_between_tiers(self) -> None:
        """Bilibili-Evolved（87 分，topics）应当高于 polyfill（53 分，名字）。"""
        self.assertGreater(rank_score(87, "topics"), rank_score(53, "名字"))

    def test_manual_pin_wins(self) -> None:
        self.assertGreater(rank_score(50, "人工"), rank_score(100, "topics"))


class TestQueryWords(unittest.TestCase):
    def test_strips_operators_and_qualifiers(self) -> None:
        self.assertEqual(
            query_words('d3 OR "animation library" OR gsap stars:>200'),
            ["d3", "animation library", "gsap"],
        )

    def test_handles_trailing_qualifier_glued_to_term(self) -> None:
        """真实 bug：`gsap stars:>200` 曾被当成一个关键词。"""
        self.assertEqual(query_words("gsap stars:>200"), ["gsap"])

    def test_empty(self) -> None:
        self.assertEqual(query_words(""), [])


if __name__ == "__main__":
    unittest.main()
