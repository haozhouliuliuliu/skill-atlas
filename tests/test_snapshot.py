"""快照与差分的测试。

这是「同位置择优替换」的检测机制，所以断言集中在：
**什么算"发现更好的"，什么只是噪声。**
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from tests import cleanup, make_temp_dir  # noqa: E402

from skill_atlas import build_atlas  # noqa: E402
from skill_atlas.models import Repo  # noqa: E402
from skill_atlas.snapshot import (  # noqa: E402
    archive,
    diff,
    find_baseline,
    history_dir,
    load,
    save,
    snapshot_path,
    take,
)

LOCAL = "a local inference engine compatible with ollama"


def repo(name: str, *, stars: int, forks: int, description: str = LOCAL,
         pushed_days_ago: int = 1, size_kb: int = 20000) -> Repo:
    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    pushed = (now - dt.timedelta(days=pushed_days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Repo(
        full_name=name,
        description=description,
        language="Python",
        stars=stars,
        forks=forks,
        open_issues=10,
        size_kb=size_kb,
        license="MIT",
        pushed_at=pushed,
    )


def atlas_with(*repos: Repo):
    return build_atlas({}, {"本地推理引擎": list(repos)})


class TestTake(unittest.TestCase):
    def test_captures_only_slots_with_candidates(self) -> None:
        atlas = atlas_with(repo("a/one", stars=1000, forks=100))
        snap = take(atlas, per_slot=10)
        self.assertIn("本地推理引擎", snap.slots)
        self.assertNotIn("笔记与编辑器", snap.slots)

    def test_respects_per_slot(self) -> None:
        atlas = atlas_with(*[repo(f"o{i}/p{i}", stars=5000 - i, forks=100) for i in range(20)])
        snap = take(atlas, per_slot=3)
        self.assertEqual(len(snap.slots["本地推理引擎"]), 3)

    def test_records_rank_score_and_relevance(self) -> None:
        atlas = atlas_with(repo("ollama/ollama", stars=100000, forks=10000))
        entry = take(atlas, per_slot=5).slots["本地推理引擎"][0]
        self.assertEqual(entry.full_name, "ollama/ollama")
        self.assertEqual(entry.relevance, "名字")
        self.assertGreater(entry.rank_score, entry.quality)


class TestPersistence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_temp_dir()

    def tearDown(self) -> None:
        cleanup(self.tmp)

    def test_round_trip(self) -> None:
        atlas = atlas_with(repo("a/one", stars=1000, forks=100))
        snap = take(atlas, per_slot=5)
        path = save(self.tmp / "snap.json", snap)
        again = load(path)
        self.assertEqual(again.generated_at, snap.generated_at)
        self.assertEqual(again.per_slot, snap.per_slot)
        self.assertEqual(again.slots["本地推理引擎"][0].full_name, "a/one")

    def test_archive_writes_current_and_history(self) -> None:
        atlas = atlas_with(repo("a/one", stars=1000, forks=100))
        snap = take(atlas, per_slot=5, generated_at="2026-10-10 09:00")
        archive(self.tmp, snap)
        self.assertTrue(snapshot_path(self.tmp).exists())
        self.assertTrue((history_dir(self.tmp) / "2026-10-10.json").exists())

    def test_find_baseline_picks_the_most_recent_earlier_snapshot(self) -> None:
        atlas = atlas_with(repo("a/one", stars=1000, forks=100))
        for day in ("2026-10-01", "2026-10-05", "2026-10-20"):
            archive(self.tmp, take(atlas, per_slot=5, generated_at=f"{day} 09:00"))
        found = find_baseline(self.tmp, before="2026-10-10")
        self.assertIsNotNone(found)
        self.assertEqual(found.stem, "2026-10-05")

    def test_find_baseline_returns_none_when_nothing_earlier(self) -> None:
        self.assertIsNone(find_baseline(self.tmp, before="2026-10-10"))


class TestDiff(unittest.TestCase):
    def _diff(self, old_repos, new_repos, enrichment_extra=None):
        old = take(atlas_with(*old_repos), per_slot=5, generated_at="day1")
        new_atlas = atlas_with(*new_repos)
        new = take(new_atlas, per_slot=5, generated_at="day2")
        return diff(old, new), new_atlas

    def test_no_change_is_empty(self) -> None:
        one = repo("a/one", stars=1000, forks=100)
        report, _ = self._diff([one], [one])
        self.assertTrue(report.is_empty)

    def test_stronger_new_candidate_is_an_upgrade(self) -> None:
        """这才是「发现了更好的」—— 可执行的替换信号。"""
        weak = repo("old/engine", stars=2000, forks=200)
        strong = repo("new/engine", stars=120000, forks=12000)
        report, _ = self._diff([weak], [weak, strong])
        self.assertEqual(len(report.upgrades), 1)
        upgrade = report.upgrades[0]
        self.assertEqual(upgrade.slot, "本地推理引擎")
        self.assertEqual(upgrade.old_top.full_name, "old/engine")
        self.assertEqual(upgrade.new_top.full_name, "new/engine")
        self.assertGreater(upgrade.score_delta, 0)

    def test_weaker_new_top_is_a_downgrade(self) -> None:
        """原首选消失、顶上来的更弱 —— 值得确认原因，不是升级。"""
        strong = repo("new/engine", stars=120000, forks=12000)
        weak = repo("old/engine", stars=2000, forks=200)
        report, _ = self._diff([strong, weak], [weak])
        self.assertEqual(len(report.downgrades), 1)
        self.assertLess(report.downgrades[0].score_delta, 0)

    def test_same_score_swap_is_churn_not_upgrade(self) -> None:
        left = repo("aa/engine", stars=5000, forks=500)
        right = repo("bb/engine", stars=5000, forks=500)
        report, _ = self._diff([left], [right])
        self.assertEqual(report.upgrades, [])
        self.assertEqual(len(report.top_changes), 1)
        self.assertEqual(report.top_changes[0].direction, "churn")

    def test_new_entry_that_is_not_top_is_reported_separately(self) -> None:
        """列表末尾多了一个候选，不应被误报成替换信号。"""
        top = repo("top/engine", stars=100000, forks=10000)
        extra = repo("extra/engine", stars=300, forks=30)
        report, _ = self._diff([top], [top, extra])
        self.assertEqual(report.upgrades, [])
        self.assertEqual(len(report.slots_with_new_entries), 1)
        self.assertEqual(
            [e.full_name for e in report.slots_with_new_entries[0].entered],
            ["extra/engine"],
        )

    def test_gap_closed(self) -> None:
        report, _ = self._diff([], [repo("a/one", stars=1000, forks=100)])
        self.assertEqual(report.gaps_closed, ["本地推理引擎"])
        self.assertEqual(report.gaps_opened, [])

    def test_gap_filled_is_not_reported_as_an_upgrade(self) -> None:
        """空缺被填上是**另一类事件**，不能混进"出现更好的首选"。

        回归：早期实现把 `old_top is None` 当作 upgrade 的默认分支，
        于是输出里出现了「换下 —」这种不可能成立的表述，同一个能力位
        还在「新填上的空缺」里被报告了第二次。
        """
        report, _ = self._diff([], [repo("a/one", stars=1000, forks=100)])
        self.assertEqual(report.upgrades, [], "空缺填上不应算作替换首选")
        self.assertEqual(len(report.top_changes), 1)
        delta = report.top_changes[0]
        self.assertEqual(delta.direction, "filled")
        self.assertTrue(delta.is_actionable, "但它仍然值得注意")
        self.assertIsNone(delta.old_top)

    def test_gap_opened(self) -> None:
        report, _ = self._diff([repo("a/one", stars=1000, forks=100)], [])
        self.assertEqual(report.gaps_opened, ["本地推理引擎"])
        self.assertEqual(report.top_changes[0].direction, "emptied")
        self.assertEqual(report.downgrades, [], "空缺不属于「首位变弱」这一类别")

    def test_actionable_changes_sort_first(self) -> None:
        """升级信号必须排在列表最前，否则会被噪声淹没。"""
        weak = repo("old/engine", stars=2000, forks=200)
        strong = repo("new/engine", stars=120000, forks=12000)
        filler = repo("filler/engine", stars=400, forks=40)
        report, _ = self._diff([weak], [weak, strong, filler])
        self.assertTrue(report.deltas[0].is_actionable)

    def test_report_carries_both_timestamps(self) -> None:
        one = repo("a/one", stars=1000, forks=100)
        report, _ = self._diff([one], [one])
        self.assertEqual(report.old_at, "day1")
        self.assertEqual(report.new_at, "day2")


if __name__ == "__main__":
    unittest.main()
