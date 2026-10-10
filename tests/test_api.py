"""GitHub 客户端（api）的测试。

``api.py`` 是唯一一个既**不含可离线验证的纯逻辑**、又**带网络副作用**的模块，
所以这里把 HTTP 层打桩，只测它自己的逻辑：URL 构造、响应解析、
限流退避、错误包装、凭证解析。
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from skill_atlas.api import (  # noqa: E402
    GitHubError,
    RateLimited,
    SearchClient,
    resolve_token,
)

SEARCH_ITEM = {
    "full_name": "ollama/ollama",
    "html_url": "https://github.com/ollama/ollama",
    "description": "run models locally",
    "language": "Go",
    "stargazers_count": 182604,
    "forks_count": 18185,
    "open_issues_count": 1500,
    "size": 95538,
    "license": {"spdx_id": "MIT"},
    "created_at": "2023-06-26T00:00:00Z",
    "pushed_at": "2026-10-10T00:00:00Z",
    "archived": False,
    "topics": ["llm"],
}


class FakeResponse:
    """最小可用的 urlopen 返回值。"""

    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.github.com/x", code=code, msg="boom", hdrs=None, fp=None
    )


class TestUrlConstruction(unittest.TestCase):
    def setUp(self) -> None:
        self.client = SearchClient()
        self.captured: list[str] = []

    def _patch(self, payload: object):
        def fake_urlopen(request, timeout=None):
            self.captured.append(request.full_url)
            return FakeResponse(payload)

        return mock.patch("urllib.request.urlopen", side_effect=fake_urlopen)

    def test_search_repos_requests_the_right_url(self) -> None:
        with self._patch({"items": [SEARCH_ITEM]}), mock.patch("time.sleep"):
            repos = self.client.search_repos('ollama OR "inference engine"', per_page=50)
        self.assertEqual(len(repos), 1)
        url = self.captured[0]
        self.assertIn("/search/repositories?", url)
        self.assertIn("per_page=50", url)
        self.assertIn("sort=stars", url)
        self.assertIn("q=ollama+OR+%22inference+engine%22", url)

    def test_sort_can_be_disabled(self) -> None:
        with self._patch({"items": []}), mock.patch("time.sleep"):
            self.client.search_repos("x", sort=None)
        self.assertNotIn("sort=", self.captured[0])

    def test_search_parses_items_into_repos(self) -> None:
        with self._patch({"items": [SEARCH_ITEM]}), mock.patch("time.sleep"):
            repo = self.client.search_repos("x")[0]
        self.assertEqual(repo.full_name, "ollama/ollama")
        self.assertEqual(repo.stars, 182604)
        self.assertEqual(repo.license, "MIT")
        self.assertEqual(repo.topics, ["llm"])

    def test_search_raw_returns_total_count(self) -> None:
        with self._patch({"items": [SEARCH_ITEM], "total_count": 391358}), \
                mock.patch("time.sleep"):
            repos, total = self.client.search_raw("created:>2026-10-09")
        self.assertEqual(len(repos), 1)
        self.assertEqual(total, 391358)

    def test_slot_candidates_appends_a_star_floor(self) -> None:
        from skill_atlas.slots import slot_by_name

        slot = slot_by_name("本地推理引擎")
        with self._patch({"items": []}), mock.patch("time.sleep"):
            self.client.slot_candidates(slot, min_stars=500)
        self.assertIn("stars%3A%3E500", self.captured[0])

    def test_slot_without_query_skips_the_request(self) -> None:
        from skill_atlas.slots import Slot

        with self._patch({"items": []}), mock.patch("time.sleep"):
            result = self.client.slot_candidates(Slot("d", "s", (), True, ""))
        self.assertEqual(result, [])
        self.assertEqual(self.captured, [], "没有检索式就不应该发请求")


class TestHeaders(unittest.TestCase):
    def test_token_is_only_sent_when_present(self) -> None:
        self.assertNotIn("Authorization", SearchClient()._headers())
        headers = SearchClient(token="ghp_secret")._headers()
        self.assertEqual(headers["Authorization"], "Bearer ghp_secret")

    def test_user_agent_is_always_set(self) -> None:
        self.assertTrue(SearchClient()._headers()["User-Agent"])


class TestErrorHandling(unittest.TestCase):
    def setUp(self) -> None:
        self.client = SearchClient()

    def test_403_is_retried_then_reported(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=http_error(403)), \
                mock.patch("skill_atlas.api.time.sleep") as slept:
            with self.assertRaises(GitHubError):
                self.client.search_repos("x")
        # 三次尝试之间有两次 60 秒退避（第三次直接抛错，不再等待）
        backoffs = [c.args[0] for c in slept.call_args_list if c.args[0] == 60]
        self.assertEqual(len(backoffs), 2)

    def test_403_that_succeeds_on_retry_is_not_an_error(self) -> None:
        responses = [http_error(403), FakeResponse({"items": [SEARCH_ITEM]})]

        def fake_urlopen(request, timeout=None):
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
                mock.patch("skill_atlas.api.time.sleep"):
            repos = self.client.search_repos("x")
        self.assertEqual(len(repos), 1)

    def test_404_is_not_retried(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=http_error(404)) as called, \
                mock.patch("skill_atlas.api.time.sleep"):
            with self.assertRaises(GitHubError):
                self.client.search_repos("x")
        self.assertEqual(called.call_count, 1, "4xx 非限流错误不应重试")

    def test_network_error_is_retried_then_reported(self) -> None:
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("down")) as called, \
                mock.patch("skill_atlas.api.time.sleep"):
            with self.assertRaises(GitHubError):
                self.client.search_repos("x")
        self.assertEqual(called.call_count, 3)

    def test_rate_limited_is_a_github_error(self) -> None:
        self.assertTrue(issubclass(RateLimited, GitHubError))


class TestPacing(unittest.TestCase):
    def test_authenticated_clients_go_faster(self) -> None:
        anonymous = SearchClient()
        authenticated = SearchClient(token="t")
        self.assertLess(authenticated.pace, anonymous.pace)

    def test_pace_is_respected_between_calls(self) -> None:
        client = SearchClient(token="t")
        client.pace_authenticated = 5.0
        payload = {"items": []}
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(payload)), \
                mock.patch("skill_atlas.api.time.sleep") as slept:
            client.search_repos("a")
            client.search_repos("b")
        # 第一次不需要等待，第二次需要
        waits = [c.args[0] for c in slept.call_args_list]
        self.assertEqual(len(waits), 1)
        self.assertLessEqual(waits[0], 5.0)


class TestResolveToken(unittest.TestCase):
    def test_prefers_environment_variable(self) -> None:
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "from-env"}, clear=False):
            self.assertEqual(resolve_token(), "from-env")

    def test_falls_back_to_gh_token_variable(self) -> None:
        env = {"GH_TOKEN": "from-gh"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(resolve_token(), "from-gh")

    def test_ignores_blank_values(self) -> None:
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "   "}, clear=True), \
                mock.patch("shutil.which", return_value=None):
            self.assertIsNone(resolve_token())

    def test_uses_gh_cli_when_available(self) -> None:
        completed = mock.Mock(returncode=0, stdout="ghp_from_cli\n")
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("shutil.which", return_value="/usr/bin/gh"), \
                mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(resolve_token(), "ghp_from_cli")

    def test_returns_none_when_gh_is_not_logged_in(self) -> None:
        completed = mock.Mock(returncode=1, stdout="")
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("shutil.which", return_value="/usr/bin/gh"), \
                mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(resolve_token())


if __name__ == "__main__":
    unittest.main()
