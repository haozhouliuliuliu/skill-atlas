"""在**真实抓取数据**上做的回归测试。

这一组测试的存在意义
--------------------
README 里那些数字（日榜 91% 是垃圾、54 个能力位首选分别是什么）来自一次真实抓取。
光把它们写在文档里，读者只能相信；所以这里提交了一份**裁减后的真实数据**：

* 榜单记录（day/week/month）**完整保留** —— 只有 240 KB，且决定了垃圾统计
* 定向检索结果裁减到**每个能力位排序前 25 的候选** —— 首选必然在其中

于是这一段话就变成了可执行的断言：

    「用这份数据重跑流水线，54 个能力位的首选与排序分必须**逐个一致**。」

它也顺便成了最强的回归测试：任何改动只要影响了打分或相关性排序，
都会在这里以真实数据的形式暴露出来，而不是只在合成样本上。
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from skill_atlas import build_atlas, store  # noqa: E402
from skill_atlas.snapshot import take  # noqa: E402

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "real_crawl"
REFERENCE = FIXTURE / "reference_tops.json"


class TestRealCrawl(unittest.TestCase):
    """用真实数据验证「重跑得到同样的结论」。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not REFERENCE.exists():
            raise AssertionError(
                f"缺少真实数据 fixture：{FIXTURE}\n"
                "这是仓库的一部分，不应缺失；若被删除，请重新生成。"
            )
        cls.reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
        cls.atlas = build_atlas(
            store.load_rankings(FIXTURE), store.load_enrichment(FIXTURE)
        )
        cls.snapshot = take(cls.atlas, per_slot=cls.reference["keep_per_slot"])

    # -- 质量过滤 ------------------------------------------------------
    def test_junk_count_reproduces(self) -> None:
        """榜单里的垃圾仓库数量必须与完整抓取时一致。"""
        self.assertEqual(len(self.atlas.junk), self.reference["junk_full"])

    def test_junk_reasons_are_physical_where_possible(self) -> None:
        """判据优先级：能报物理理由的就不报语言理由。"""
        reasons = [reason for _repo, reason in self.atlas.junk]
        self.assertTrue(reasons)
        readme_only = sum(1 for r in reasons if "仅README" in r)
        self.assertGreater(readme_only, 0, "真实数据里应有大量只有 README 的仓库")

    # -- 能力位结论 ----------------------------------------------------
    def test_every_reference_slot_has_candidates(self) -> None:
        missing = [
            slot for slot in self.reference["tops"] if slot not in self.snapshot.slots
        ]
        self.assertEqual(missing, [], "参考结论里的能力位不应变成空缺")

    def test_top_picks_match_the_reference(self) -> None:
        """核心断言：54 个能力位的首选逐个一致。"""
        mismatches = []
        for slot, expected in self.reference["tops"].items():
            entries = self.snapshot.slots.get(slot, [])
            actual = entries[0].full_name if entries else None
            if actual != expected["top"]:
                mismatches.append(f"{slot}: 期望 {expected['top']}，实际 {actual}")
        self.assertEqual(mismatches, [], "\n".join(mismatches))

    def test_rank_scores_match_the_reference(self) -> None:
        """排序分也要一致 —— 否则排序对了只是巧合。"""
        mismatches = []
        for slot, expected in self.reference["tops"].items():
            entries = self.snapshot.slots.get(slot, [])
            if not entries:
                continue
            entry = entries[0]
            if (entry.rank_score, entry.quality, entry.relevance) != (
                expected["rank_score"],
                expected["quality"],
                expected["relevance"],
            ):
                mismatches.append(
                    f"{slot}: 期望 ({expected['rank_score']}, {expected['quality']}, "
                    f"{expected['relevance']})，实际 "
                    f"({entry.rank_score}, {entry.quality}, {entry.relevance})"
                )
        self.assertEqual(mismatches, [], "\n".join(mismatches))

    def test_slot_count_matches(self) -> None:
        self.assertEqual(len(self.snapshot.slots), len(self.reference["tops"]))

    # -- 抽查几个有说服力的结论 ----------------------------------------
    def test_known_top_picks(self) -> None:
        """把几个最可辨认的结论写死，便于人工扫一眼就知道对不对。"""
        expected = {
            "Agent 编排与 Harness": "langgenius/dify",
            "本地推理引擎": "ollama/ollama",
            "浏览器自动化与反检测": "microsoft/playwright",
            "逆向工程与调试": "NationalSecurityAgency/ghidra",
            "日志与监控": "grafana/grafana",
            "定时任务与调度": "apache/airflow",
            "语音识别与合成": "ggml-org/whisper.cpp",
            "文档解析与 RAG 切分": "docling-project/docling",
        }
        for slot, repo in expected.items():
            with self.subTest(slot=slot):
                entries = self.snapshot.slots.get(slot, [])
                self.assertTrue(entries, f"{slot} 没有候选")
                self.assertEqual(entries[0].full_name, repo)

    def test_manual_exclusion_holds_on_real_data(self) -> None:
        """apache/ranger 在真实数据里存在，且必须被剔除。"""
        appeared = any(
            entry.full_name == "apache/ranger"
            for entry in self.snapshot.slots.get("磁盘与文件管理", [])
        )
        self.assertFalse(appeared, "人工剔除在真实数据上失效了")

    def test_activity_penalty_is_visible(self) -> None:
        """Tampermonkey 558 天未推送，应当排在活跃的 XIU2/UserScript 之后。"""
        entries = self.snapshot.slots.get("浏览器与插件", [])
        names = [e.full_name for e in entries]
        if "Tampermonkey/tampermonkey" not in names or "XIU2/UserScript" not in names:
            self.skipTest("这两个仓库不在本次 fixture 的前 25 名内")
        self.assertLess(
            names.index("XIU2/UserScript"), names.index("Tampermonkey/tampermonkey")
        )


if __name__ == "__main__":
    unittest.main()
