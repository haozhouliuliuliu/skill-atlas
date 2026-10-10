"""端到端测试：用离线样本跑完整条流水线，并对渲染结果做断言。

这是唯一一个覆盖「抓取结果 -> 索引 -> markdown 库 -> 检索」全链路的测试，
也是 ``examples/demo.py`` 的自动化版本。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from tests import cleanup, make_temp_dir  # noqa: E402

from examples import sample_data  # noqa: E402
from skill_atlas import build_atlas, query_atlas, render_vault  # noqa: E402


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = make_temp_dir()
        cls.atlas = build_atlas(sample_data.rankings(), sample_data.enrichment())
        cls.stats = render_vault(
            cls.atlas, cls.tmp, per_slot=5, generated_at="2026-10-10 12:00"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup(cls.tmp)

    # -- 质量过滤 ------------------------------------------------------
    def test_spam_repo_is_filtered_out(self) -> None:
        names = {repo.full_name for repo, _ in self.atlas.junk}
        self.assertIn("KindStatesman/KMS-Pico", names)
        self.assertNotIn("KindStatesman/KMS-Pico", self.atlas.candidates)

    def test_spam_reason_is_the_physical_one(self) -> None:
        reasons = {repo.full_name: why for repo, why in self.atlas.junk}
        self.assertIn("仅README", reasons["KindStatesman/KMS-Pico"])

    # -- 归位与排序 ----------------------------------------------------
    def test_ranking_repo_is_assigned_by_keyword(self) -> None:
        candidate = self.atlas.candidates["storytold/wordcraft"]
        self.assertIn("Office 文档生成与解析", candidate.slots)
        self.assertEqual(candidate.relevance_why("Office 文档生成与解析"), "榜单")

    def test_name_hit_ranks_first_for_local_inference(self) -> None:
        ranked = [c.full_name for c in self.atlas.by_slot["本地推理引擎"]]
        self.assertEqual(ranked[0], "ollama/ollama")
        self.assertIn("ggml-org/llama.cpp", ranked)

    def test_dormant_repo_loses_to_active_one(self) -> None:
        """Tampermonkey 558 天未推送，应当排在活跃的 XIU2/UserScript 之后。"""
        ranked = [c.full_name for c in self.atlas.by_slot["浏览器与插件"]]
        self.assertLess(ranked.index("XIU2/UserScript"),
                        ranked.index("Tampermonkey/tampermonkey"))

    def test_manual_exclusion_removes_collision(self) -> None:
        ranked = [c.full_name for c in self.atlas.by_slot["磁盘与文件管理"]]
        self.assertEqual(ranked, ["sxyazi/yazi"])

    # -- 空缺 ----------------------------------------------------------
    def test_untouched_slot_is_reported_as_gap(self) -> None:
        self.assertEqual(self.stats["gaps"], 54 - self._slots_with_candidates())

    def _slots_with_candidates(self) -> int:
        return sum(1 for recs in self.atlas.by_slot.values() if recs)

    # -- 渲染 ----------------------------------------------------------
    def test_vault_layout(self) -> None:
        self.assertTrue((self.tmp / "README.md").exists())
        self.assertTrue((self.tmp / "01-能力位总表.md").exists())
        self.assertTrue((self.tmp / "02-项目蓝图.md").exists())
        self.assertEqual(len(list((self.tmp / "10-能力位").glob("*.md"))), 54)
        self.assertEqual(len(list((self.tmp / "30-检索日志").glob("*.md"))), 2)

    def test_gap_slot_note_says_so(self) -> None:
        note = (self.tmp / "10-能力位" / "笔记与编辑器.md").read_text(encoding="utf-8")
        self.assertIn("空缺", note)

    def test_excluded_repo_is_recorded_in_note(self) -> None:
        note = (self.tmp / "10-能力位" / "磁盘与文件管理.md").read_text(encoding="utf-8")
        self.assertIn("apache/ranger", note)
        self.assertIn("同名撞车", note)

    def test_high_quality_project_scores_high(self) -> None:
        """d3/d3（11.3 万星 / 2.26 万 fork）必须拿到高分，尽管它 134 天未推送。"""
        candidate = self.atlas.candidates["d3/d3"]
        self.assertGreaterEqual(candidate.score, 80)

    # -- 检索 ----------------------------------------------------------
    def test_query_finds_logging_slot(self) -> None:
        matches = query_atlas(self.atlas, "日志监控和告警", top=3)
        names = [m.slot.name for m in matches]
        self.assertIn("日志与监控", names)
        logging_slot = next(m for m in matches if m.slot.name == "日志与监控")
        self.assertIn("grafana/grafana", logging_slot.candidates)

    def test_query_reports_empty_slot_as_opportunity(self) -> None:
        matches = query_atlas(self.atlas, "我要做定时任务调度", top=3)
        scheduled = next((m for m in matches if m.slot.name == "定时任务与调度"), None)
        self.assertIsNotNone(scheduled)
        self.assertEqual(scheduled.candidates, [])


if __name__ == "__main__":
    unittest.main()
