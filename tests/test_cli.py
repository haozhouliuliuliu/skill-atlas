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


if __name__ == "__main__":
    unittest.main()
