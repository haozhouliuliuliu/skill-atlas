"""命令行接线的测试。

前面的测试都直接调库函数。这一组测的是 **CLI 层**：
参数解析、子命令分发、输出、退出码，以及 build 推进 / diff 不推进基线这条约定。
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from tests import cleanup, make_temp_dir  # noqa: E402

from examples import sample_data  # noqa: E402
from skill_atlas import store  # noqa: E402
from skill_atlas.cli import main  # noqa: E402
from skill_atlas.snapshot import snapshot_path  # noqa: E402


def run_cli(*args: str) -> tuple[int, str]:
    """执行一个子命令，返回 (退出码, stdout)。"""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(list(args))
    return code, buffer.getvalue()


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_temp_dir()
        self.data = self.tmp / "data"
        self.vault = self.tmp / "vault"
        store.save_enrichment(self.data, sample_data.enrichment())
        for _window, result in sample_data.rankings().items():
            store.save_ranking(self.data, result)

    def tearDown(self) -> None:
        cleanup(self.tmp)

    # -- 基础子命令 ----------------------------------------------------
    def test_slots_lists_every_slot(self) -> None:
        code, out = run_cli("slots")
        self.assertEqual(code, 0)
        self.assertIn("54 capability slots", out)
        self.assertIn("apache/ranger", out)  # 人工剔除也要展示出来

    def test_query_answers_a_project_question(self) -> None:
        code, out = run_cli("query", "我想给项目加日志监控", "--data", str(self.data),
                            "--top", "2")
        self.assertEqual(code, 0)
        self.assertIn("日志与监控", out)
        self.assertIn("grafana/grafana", out)

    def test_query_on_missing_data_fails_loudly(self) -> None:
        empty = self.tmp / "empty"
        with self.assertRaises(SystemExit):
            run_cli("query", "anything", "--data", str(empty))

    # -- build / diff 的约定 -------------------------------------------
    def test_build_renders_and_creates_a_baseline(self) -> None:
        code, out = run_cli("build", "--data", str(self.data),
                            "--vault", str(self.vault), "--per-slot", "5")
        self.assertEqual(code, 0)
        self.assertIn("snapshot", out)
        self.assertTrue((self.vault / "01-能力位总表.md").exists())
        self.assertTrue(snapshot_path(self.data).exists())

    def test_diff_without_a_baseline_explains_itself(self) -> None:
        code, out = run_cli("diff", "--data", str(self.data))
        self.assertEqual(code, 0)
        self.assertIn("没有基线快照", out)

    def test_diff_does_not_advance_the_baseline(self) -> None:
        """这是核心约定：先看变化，确认后 build 才推进基线。"""
        run_cli("build", "--data", str(self.data), "--vault", str(self.vault),
                "--per-slot", "5")
        before = json.loads(snapshot_path(self.data).read_text(encoding="utf-8"))

        # 换掉一个候选，让当前状态与基线不同
        enrichment = sample_data.enrichment()
        enrichment["日志与监控"] = [
            r for r in enrichment["日志与监控"] if r.full_name != "grafana/grafana"
        ]
        store.save_enrichment(self.data, enrichment)

        code, out = run_cli("diff", "--data", str(self.data), "--per-slot", "5")
        self.assertEqual(code, 0)
        self.assertIn("日志与监控", out)

        after = json.loads(snapshot_path(self.data).read_text(encoding="utf-8"))
        self.assertEqual(before, after, "diff 不应改写基线快照")

    def test_build_advances_the_baseline(self) -> None:
        run_cli("build", "--data", str(self.data), "--vault", str(self.vault),
                "--per-slot", "5")
        before = json.loads(snapshot_path(self.data).read_text(encoding="utf-8"))
        enrichment = sample_data.enrichment()
        enrichment["日志与监控"] = []
        store.save_enrichment(self.data, enrichment)
        run_cli("build", "--data", str(self.data), "--vault", str(self.vault),
                "--per-slot", "5")
        after = json.loads(snapshot_path(self.data).read_text(encoding="utf-8"))
        self.assertNotEqual(before, after, "build 应当推进基线")

    def test_diff_json_is_machine_readable(self) -> None:
        run_cli("build", "--data", str(self.data), "--vault", str(self.vault),
                "--per-slot", "5")
        enrichment = sample_data.enrichment()
        enrichment["笔记与编辑器"] = sample_data.enrichment().get("语音识别与合成", [])
        store.save_enrichment(self.data, enrichment)
        code, out = run_cli("diff", "--data", str(self.data), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("top_changes", payload)
        self.assertIn("gaps_closed", payload)
        self.assertIn("baseline", payload)


class FakeClient:
    """替身客户端：让 update 能在完全离线的条件下被测到。"""

    token = None
    pace = 0.0

    def __init__(self, rankings, enrichment):
        self._rankings = rankings
        self._enrichment = enrichment

    def created_ranking(self, days, per_page=100):
        window = {1: "day", 7: "week", 30: "month"}[days]
        result = self._rankings.get(window)
        repos = result.repos if result else []
        meta = {"since": result.since if result else "", "total_count": 100}
        return repos, meta

    def slot_candidates(self, slot, min_stars=200, per_page=100):
        return self._enrichment.get(slot.name, [])


class TestUpdateCommand(unittest.TestCase):
    """`update` 是每日循环的入口，必须能离线验证。"""

    def setUp(self) -> None:
        self.tmp = make_temp_dir()
        self.data = self.tmp / "data"
        self.vault = self.tmp / "vault"
        self.rankings = sample_data.rankings()
        self.enrichment = sample_data.enrichment()
        self.client = FakeClient(self.rankings, self.enrichment)

    def tearDown(self) -> None:
        cleanup(self.tmp)

    def _run_update(self, *extra: str) -> tuple[int, str]:
        with mock.patch("skill_atlas.cli.SearchClient", return_value=self.client):
            return run_cli("update", "--data", str(self.data),
                           "--vault", str(self.vault), *extra)

    def test_runs_all_three_stages(self) -> None:
        code, out = self._run_update()
        self.assertEqual(code, 0)
        for stage in ("fetch", "enrich", "diff"):
            self.assertIn(stage, out)

    def test_fetch_wrote_the_rankings(self) -> None:
        self._run_update()
        self.assertTrue((self.data / "raw" / "day.json").exists())
        self.assertTrue((self.data / "raw" / "enriched.json").exists())

    def test_does_not_advance_the_baseline_by_default(self) -> None:
        """默认不建库 —— 否则 diff 的基线就是刚被覆盖的自己，等于没有比较。"""
        self._run_update()
        self.assertFalse(snapshot_path(self.data).exists())
        self.assertIn("没有基线快照", self._run_update()[1])

    def test_build_flag_renders_and_advances(self) -> None:
        code, out = self._run_update("--build")
        self.assertEqual(code, 0)
        self.assertTrue(snapshot_path(self.data).exists())
        self.assertTrue((self.vault / "01-能力位总表.md").exists())
        self.assertIn("snapshot", out)

    def test_second_update_reports_no_change(self) -> None:
        self._run_update("--build")
        _code, out = self._run_update()
        self.assertIn("没有任何变化", out)


if __name__ == "__main__":
    unittest.main()
