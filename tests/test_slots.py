"""能力位定义的完整性测试。"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from skill_atlas import Repo, SLOT_EXCLUDE, UNASSIGNED, all_slots, assign_slot  # noqa: E402

#: 能力位总数。改动能力位定义时这个数字要同步更新 —— 这是刻意的摩擦，
#: 因为漏改一处会让「覆盖率」这个指标悄悄失真。
EXPECTED_SLOT_COUNT = 54


class TestSlotDefinitions(unittest.TestCase):
    def test_slot_count(self) -> None:
        self.assertEqual(len(all_slots()), EXPECTED_SLOT_COUNT)

    def test_names_are_unique(self) -> None:
        names = [s.name for s in all_slots()]
        self.assertEqual(len(names), len(set(names)))

    def test_every_slot_has_a_search_query(self) -> None:
        """每个能力位都要有检索式，否则它会永远空缺。"""
        missing = [s.name for s in all_slots() if not s.query.strip()]
        self.assertEqual(missing, [])

    def test_every_slot_has_a_domain(self) -> None:
        self.assertTrue(all(s.domain for s in all_slots()))

    def test_patterns_are_valid_regex(self) -> None:
        import re

        for slot in all_slots():
            for pattern in slot.patterns:
                with self.subTest(slot=slot.name, pattern=pattern):
                    re.compile(pattern)

    def test_staple_slots_have_no_patterns(self) -> None:
        """标准能力位占位只靠检索式，不参与榜单自动归位。"""
        staples = [s for s in all_slots() if s.is_staple]
        self.assertEqual(len(staples), 12)
        self.assertTrue(all(not s.patterns for s in staples))


class TestAssignSlot(unittest.TestCase):
    def test_named_project_goes_to_expected_slot(self) -> None:
        repo = Repo(
            full_name="langchain-ai/langchain",
            description="The agent engineering platform.",
            language="Python",
            topics=["agent", "llm"],
        )
        self.assertEqual(assign_slot(repo).name, "Agent 编排与 Harness")

    def test_specific_slot_wins_over_generic_one(self) -> None:
        """回归：`on your own` 曾把 laya（系统1决策模型）抢进「本地推理引擎」。

        修法是把更具体的「系统1决策模型」排到「本地推理引擎」前面。
        """
        repo = Repo(
            full_name="NandhaKishorM/laya",
            description=(
                "Non-autoregressive System 1 decision engine. Typed choice, score "
                "and yes/no decisions over any text in a single forward pass, "
                "runs on your own hardware."
            ),
            language="Python",
        )
        self.assertEqual(assign_slot(repo).name, "系统1决策模型")

    def test_unmatched_repo_is_unassigned(self) -> None:
        repo = Repo(full_name="someone/whatever", description="nothing special")
        self.assertEqual(assign_slot(repo).name, UNASSIGNED.name)

    def test_browser_slot_requires_extension_wording(self) -> None:
        """回归：裸词 `browser` 曾把 PS5 漏洞链归进「浏览器与插件」。"""
        exploit = Repo(
            full_name="ntfargo/Relapse-Exploit",
            description="Exploit chain for PS5 7.00 - 13.60",
            topics=["browser", "exploit"],
        )
        self.assertNotEqual(assign_slot(exploit).name, "浏览器与插件")

        userscript = Repo(
            full_name="XIU2/UserScript",
            description="自用的一些油猴脚本",
            language="JavaScript",
        )
        self.assertEqual(assign_slot(userscript).name, "浏览器与插件")


class TestManualCalibration(unittest.TestCase):
    def test_known_collisions_are_registered(self) -> None:
        """同名撞车造成的人工剔除必须有记录，否则日后无人知道为什么少了它。"""
        self.assertIn("apache/ranger", SLOT_EXCLUDE.get("磁盘与文件管理", {}))
        self.assertTrue(SLOT_EXCLUDE["磁盘与文件管理"]["apache/ranger"])

    def test_exclusion_reasons_are_non_empty(self) -> None:
        for slot, entries in SLOT_EXCLUDE.items():
            for name, reason in entries.items():
                with self.subTest(slot=slot, repo=name):
                    self.assertTrue(reason.strip())


if __name__ == "__main__":
    unittest.main()
