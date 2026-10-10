"""仓库数据模型的测试。"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from skill_atlas import Repo  # noqa: E402

SAMPLE_API_ITEM = {
    "full_name": "storytold/photocraft",
    "html_url": "https://github.com/storytold/photocraft",
    "description": "An open-source, clean-room reimplementation of Adobe Photoshop in pure Rust",
    "language": "Rust",
    "stargazers_count": 39102,
    "forks_count": 4100,
    "open_issues_count": 42,
    "size": 12345,
    "license": {"spdx_id": "Apache-2.0"},
    "created_at": "2026-09-11T10:00:00Z",
    "pushed_at": "2026-10-10T10:00:00Z",
    "archived": False,
    "topics": ["photoshop", "rust"],
    "homepage": "https://example.com",
}


class TestFromSearchItem(unittest.TestCase):
    def test_parses_all_fields(self) -> None:
        repo = Repo.from_search_item(SAMPLE_API_ITEM)
        self.assertEqual(repo.full_name, "storytold/photocraft")
        self.assertEqual(repo.stars, 39102)
        self.assertEqual(repo.forks, 4100)
        self.assertEqual(repo.license, "Apache-2.0")
        self.assertEqual(repo.topics, ["photoshop", "rust"])
        self.assertEqual(repo.created_date(), "2026-09-11")

    def test_tolerates_missing_fields(self) -> None:
        repo = Repo.from_search_item({"full_name": "a/b"})
        self.assertEqual(repo.stars, 0)
        self.assertIsNone(repo.license)
        self.assertEqual(repo.topics, [])
        self.assertFalse(repo.archived)

    def test_null_license_object(self) -> None:
        repo = Repo.from_search_item({"full_name": "a/b", "license": None})
        self.assertIsNone(repo.license)

    def test_round_trip(self) -> None:
        repo = Repo.from_search_item(SAMPLE_API_ITEM)
        again = Repo.from_dict(repo.to_dict())
        self.assertEqual(repo, again)


class TestDerivedHelpers(unittest.TestCase):
    def test_owner_and_name(self) -> None:
        repo = Repo(full_name="langchain-ai/langchain")
        self.assertEqual(repo.owner(), "langchain-ai")
        self.assertEqual(repo.name(), "langchain")

    def test_safe_name_is_filename_friendly(self) -> None:
        self.assertEqual(Repo(full_name="a/b").safe_name(), "a--b")

    def test_days_since_push(self) -> None:
        now = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)
        repo = Repo(full_name="a/b", pushed_at="2026-10-03T00:00:00Z")
        self.assertEqual(repo.days_since_push(now), 7)

    def test_days_since_push_handles_garbage(self) -> None:
        self.assertEqual(Repo(full_name="a/b", pushed_at="").days_since_push(), 9999)
        self.assertEqual(
            Repo(full_name="a/b", pushed_at="not-a-date").days_since_push(), 9999
        )

    def test_search_text_is_lowercased_and_complete(self) -> None:
        repo = Repo(
            full_name="A/B",
            description="Some Tool",
            language="Rust",
            topics=["Charts"],
        )
        text = repo.search_text()
        for token in ("a/b", "some tool", "rust", "charts"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
