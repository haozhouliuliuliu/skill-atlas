"""检索入口（query）与库渲染（vault）的测试。"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from tests import cleanup, make_temp_dir  # noqa: E402

from skill_atlas.index import RankingResult, build_atlas  # noqa: E402
from skill_atlas.models import Repo  # noqa: E402
from skill_atlas.query import cjk_grams, latin_tokens, match_slots, query_atlas  # noqa: E402
from skill_atlas.vault import render_vault, slot_index  # noqa: E402


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


class TestTokenisation(unittest.TestCase):
    def test_cjk_grams_skip_stopwords(self) -> None:
        grams = cjk_grams("我要做一个日志监控")
        self.assertIn("日志", grams)
        self.assertIn("监控", grams)
        self.assertNotIn("我要", grams)

    def test_latin_tokens_drop_single_chars(self) -> None:
        self.assertEqual(latin_tokens("a b c word pdf"), {"word", "pdf"})


class TestMatching(unittest.TestCase):
    def test_chinese_query_finds_the_right_slot(self) -> None:
        matches = match_slots("想给项目加日志监控和定时任务", top=3)
        names = [m.slot.name for m in matches]
        self.assertIn("日志与监控", names)
        self.assertIn("定时任务与调度", names)

    def test_english_query_matches_via_names(self) -> None:
        repo_obj = repo("obsidian-community/obsidian")
        atlas = build_atlas({}, {"笔记与编辑器": [repo_obj]})
        matches = query_atlas(atlas, "obsidian 笔记", top=3)
        self.assertTrue(matches)
        self.assertEqual(matches[0].slot.name, "笔记与编辑器")
        self.assertEqual(matches[0].candidates, ["obsidian-community/obsidian"])

    def test_office_query_hits_office_slot_first(self) -> None:
        """回归：整理 Word/PDF 曾经匹配不到「Office 文档生成与解析」。"""
        matches = match_slots("我要做一个能自动整理 Word 和 PDF 的 agent", top=4)
        self.assertEqual(matches[0].slot.name, "Office 文档生成与解析")

    def test_no_match_returns_empty(self) -> None:
        self.assertEqual(match_slots("qqqq zzzz", top=3), [])

    def test_hit_summary_is_readable(self) -> None:
        match = match_slots("日志监控", top=1)[0]
        self.assertTrue(match.hit_summary())


class TestVaultRendering(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_temp_dir()

    def tearDown(self) -> None:
        cleanup(self.tmp)

    def _atlas(self):
        ranked = repo("langchain-ai/langchain", description="The agent engineering platform.")
        searched = repo("ollama/ollama", description="run local models")
        return build_atlas(
            {"week": RankingResult(window="week", repos=[ranked], since="s", total_count=1)},
            {"本地推理引擎": [searched]},
        )

    def test_creates_expected_layout(self) -> None:
        atlas = self._atlas()
        stats = render_vault(atlas, self.tmp, per_slot=5, generated_at="2026-01-01 00:00")
        for name in ("README.md", "01-能力位总表.md", "02-项目蓝图.md"):
            self.assertTrue((self.tmp / name).exists(), name)
        self.assertEqual(len(list((self.tmp / "10-能力位").glob("*.md"))), 54)
        self.assertEqual(len(list((self.tmp / "30-检索日志").glob("*.md"))), 1)
        self.assertEqual(stats["slots"], 54)
        self.assertEqual(stats["logs"], 1)

    def test_repo_note_has_frontmatter(self) -> None:
        atlas = self._atlas()
        render_vault(atlas, self.tmp, per_slot=5)
        note = (self.tmp / "20-项目条目" / "ollama--ollama.md").read_text(encoding="utf-8")
        self.assertTrue(note.startswith("---"))
        self.assertIn("repo: ollama/ollama", note)
        self.assertIn("能力位:", note)
        self.assertIn("- 本地推理引擎", note)

    def test_slot_note_records_exclusions(self) -> None:
        atlas = build_atlas(
            {}, {"磁盘与文件管理": [repo("yazi-rs/yazi", description="a file manager")]}
        )
        render_vault(atlas, self.tmp, per_slot=5)
        note = (self.tmp / "10-能力位" / "磁盘与文件管理.md").read_text(encoding="utf-8")
        self.assertIn("人工剔除", note)
        self.assertIn("apache/ranger", note)

    def test_empty_slot_is_marked(self) -> None:
        """没有任何候选的能力位必须显式标出空缺，而不是静默消失。"""
        atlas = build_atlas({}, {})
        stats = render_vault(atlas, self.tmp, per_slot=5)
        self.assertEqual(stats["gaps"], 54)
        index_note = (self.tmp / "01-能力位总表.md").read_text(encoding="utf-8")
        self.assertIn("⚠️", index_note)

    def test_slot_index_is_machine_readable(self) -> None:
        atlas = self._atlas()
        index = slot_index(atlas)
        self.assertIn("本地推理引擎", index)
        self.assertEqual(index["本地推理引擎"][0], "ollama/ollama")

    # -- 过期产物的清理 ------------------------------------------------
    def test_manifest_is_written(self) -> None:
        render_vault(self._atlas(), self.tmp, per_slot=5)
        manifest = self.tmp / "_atlas_manifest.json"
        self.assertTrue(manifest.exists())
        files = json.loads(manifest.read_text(encoding="utf-8"))["files"]
        self.assertIn("01-能力位总表.md", files)
        self.assertTrue(any(f.startswith("10-能力位/") for f in files))

    def test_stale_generated_notes_are_removed(self) -> None:
        """回归：渲染器不清扫输出目录，旧条目会残留成死条目。

        在 Obsidian 库里，一条指向已不再是候选的笔记比缺一条更糟 ——
        它会让人以为那个候选还在。
        """
        stale = self.tmp / "20-项目条目" / "old--gone.md"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("stale", encoding="utf-8")
        (self.tmp / "_atlas_manifest.json").write_text(
            json.dumps({"files": ["20-项目条目/old--gone.md"]}), encoding="utf-8"
        )

        stats = render_vault(self._atlas(), self.tmp, per_slot=5)
        self.assertFalse(stale.exists(), "过期笔记应当被清掉")
        self.assertEqual(stats["removed"], 1)

    def test_files_outside_the_manifest_are_never_touched(self) -> None:
        """库目录可能被指向用户自己的 Obsidian 仓库，不能误删无关笔记。"""
        mine = self.tmp / "我的笔记" / "读书笔记.md"
        mine.parent.mkdir(parents=True, exist_ok=True)
        mine.write_text("不要删我", encoding="utf-8")

        render_vault(self._atlas(), self.tmp, per_slot=5)

        self.assertTrue(mine.exists())
        self.assertEqual(mine.read_text(encoding="utf-8"), "不要删我")


if __name__ == "__main__":
    unittest.main()
