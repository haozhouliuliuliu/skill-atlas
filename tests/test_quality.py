"""质量过滤的回归测试。

这些用例不是凭空写的，每一条都对应真实数据里踩过的坑。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from skill_atlas import Repo, is_low_value, low_value_reason  # noqa: E402
from skill_atlas.quality import README_ONLY_KB  # noqa: E402


class TestLowValueDetection(unittest.TestCase):
    """识别"只有一个 README"的 SEO 引流仓库。"""

    def test_readme_only_repo_is_rejected(self) -> None:
        # 真实样本 KindStatesman/KMS-Pico：614 star、0 fork、2KB、无语言
        # 它同时命中话术判据，但**报告的是物理理由** —— 理由应当是可当场复核的那个。
        repo = Repo(
            full_name="KindStatesman/KMS-Pico",
            description=(
                "Kms Pico Free optimizes your professional desktop environment by "
                "providing a tailored utility configuration."
            ),
            stars=614,
            forks=0,
            size_kb=2,
        )
        self.assertTrue(is_low_value(repo))
        self.assertIn("仅README", low_value_reason(repo) or "")

    def test_template_prose_is_caught_when_size_and_engagement_are_fine(self) -> None:
        """体积正常、也有 fork 和许可证，但满口模板话术 —— 由语言判据兜住。"""
        repo = Repo(
            full_name="someone/Total-Commander",
            description=(
                "Total Commander is an advanced utility that optimizes your "
                "professional desktop software utility configuration."
            ),
            stars=504,
            forks=5,
            size_kb=400,
            license="MIT",
        )
        self.assertTrue(is_low_value(repo))
        self.assertEqual(low_value_reason(repo), "模板话术")

    def test_reason_precedence_is_physical_first(self) -> None:
        """判据优先级：仅README > 社区行为全空 > 模板话术。

        理由应当总是**可当场复核**的那一个。下面三条样本都同时命中多条判据，
        返回值必须按优先级给出。
        """
        readme_only = Repo(
            full_name="a/b",
            description="optimizes your professional desktop environment",
            stars=500, size_kb=2,
        )
        self.assertIn("仅README", low_value_reason(readme_only) or "")

        no_engagement = Repo(
            full_name="c/d",
            description="optimizes your professional desktop environment",
            stars=500, size_kb=500,
        )
        self.assertEqual(low_value_reason(no_engagement), "0fork/0issue/无证/无语言")

        prose_only = Repo(
            full_name="e/f",
            description="optimizes your professional desktop environment",
            stars=500, size_kb=500, forks=5, license="MIT",
        )
        self.assertEqual(low_value_reason(prose_only), "模板话术")

    def test_size_is_reported_before_prose(self) -> None:
        """物理事实优先于语言判断 —— 检查顺序即证据强度顺序。"""
        repo = Repo(
            full_name="someone/x",
            description="optimizes your professional desktop environment",
            stars=500,
            size_kb=2,
        )
        self.assertIn("仅README", low_value_reason(repo) or "")

    def test_tiny_repo_rejected_even_without_template_phrases(self) -> None:
        """话术漏判时，体积判据必须兜住。"""
        repo = Repo(
            full_name="someone/Discord-Server-Raider",
            description="An AI-driven solution designed to streamline server management.",
            stars=605,
            forks=0,
            size_kb=2,
        )
        self.assertTrue(is_low_value(repo))
        self.assertIn("仅README", low_value_reason(repo) or "")

    def test_real_project_passes(self) -> None:
        # 真实样本 fayazara/robot-heads：119 star、18 fork、907KB、MIT
        repo = Repo(
            full_name="fayazara/robot-heads",
            description="Animated 3D robot heads for React.",
            language="TypeScript",
            stars=119,
            forks=18,
            open_issues=1,
            size_kb=907,
            license="MIT",
        )
        self.assertFalse(is_low_value(repo))
        self.assertIsNone(low_value_reason(repo))

    def test_size_threshold_boundary(self) -> None:
        """阈值边界：等于阈值算"只有 README"，超过则通过。"""
        base = dict(
            full_name="x/y",
            description="a real tool",
            language="Go",
            stars=500,
            forks=20,
            open_issues=2,
            license="MIT",
        )
        self.assertTrue(is_low_value(Repo(size_kb=README_ONLY_KB, **base)))
        self.assertFalse(is_low_value(Repo(size_kb=README_ONLY_KB + 1, **base)))

    def test_zero_engagement_repo_rejected(self) -> None:
        """0 fork / 0 issue / 无许可证 / 无语言 —— 四项全空。"""
        repo = Repo(
            full_name="nobody/tool",
            description="A tool.",
            size_kb=500,
            stars=900,
        )
        self.assertTrue(is_low_value(repo))
        self.assertIn("0fork", low_value_reason(repo) or "")


if __name__ == "__main__":
    unittest.main()
