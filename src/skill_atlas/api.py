"""GitHub Search API 客户端（只用标准库）。

关于凭证
--------
匿名访问的限额很紧（search 10 次/分钟、core 60 次/小时）。
如果本机装过 ``gh`` 并已登录，会自动复用它的 token；也支持 ``GITHUB_TOKEN``
环境变量。两者都没有时仍可运行，只是要放慢节奏。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .models import Repo
from .slots import Slot

DEFAULT_API = "https://api.github.com"
DEFAULT_UA = "skill-atlas/0.1 (+https://github.com/haozhouliuliuliu/skill-atlas)"

#: 检索式里统一附加的最小星标门槛，过滤掉噪声项目
MIN_STARS = 200


class GitHubError(RuntimeError):
    """API 调用失败。"""


class RateLimited(GitHubError):
    """触发了 GitHub 的速率限制。"""


def resolve_token() -> str | None:
    """依次尝试：环境变量 ``GITHUB_TOKEN`` / ``GH_TOKEN`` / ``gh auth token``。"""
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    if shutil.which("gh"):
        try:
            proc = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return None


@dataclass
class SearchClient:
    """一个极简的 GitHub 仓库检索客户端。"""

    token: str | None = None
    api: str = DEFAULT_API
    user_agent: str = DEFAULT_UA
    timeout: int = 45
    #: 两次请求之间的间隔（秒）。已登录时 GitHub 允许 30 次/分钟。
    pace_anonymous: float = 7.0
    pace_authenticated: float = 2.5
    _last_call: float = 0.0

    @property
    def pace(self) -> float:
        return self.pace_authenticated if self.token else self.pace_anonymous

    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/vnd.github+json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _sleep_for_pace(self) -> None:
        wait = self.pace - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def _get(self, url: str, *, retries: int = 3) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            self._sleep_for_pace()
            request = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    self._last_call = time.monotonic()
                    return json.load(resp)
            except urllib.error.HTTPError as exc:
                self._last_call = time.monotonic()
                if exc.code in (403, 429) and attempt < retries:
                    time.sleep(60)
                    last_error = RateLimited(f"HTTP {exc.code}")
                    continue
                raise GitHubError(f"HTTP {exc.code} for {url}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._last_call = time.monotonic()
                last_error = exc
                if attempt < retries:
                    time.sleep(5)
                    continue
        raise GitHubError(f"request failed: {last_error}")

    # ------------------------------------------------------------------
    def search_repos(
        self,
        query: str,
        *,
        sort: str | None = "stars",
        per_page: int = 100,
    ) -> list[Repo]:
        """执行一次仓库检索。"""
        params = {"q": query, "per_page": str(per_page)}
        if sort:
            params["sort"] = sort
            params["order"] = "desc"
        url = f"{self.api}/search/repositories?{urllib.parse.urlencode(params)}"
        data = self._get(url)
        return [Repo.from_search_item(item) for item in data.get("items", [])]

    def search_raw(self, query: str, *, sort: str | None = "stars",
                   per_page: int = 100) -> tuple[list[Repo], int]:
        """同 :meth:`search_repos`，但同时返回该条件下的仓库总数。"""
        params = {"q": query, "per_page": str(per_page)}
        if sort:
            params["sort"] = sort
            params["order"] = "desc"
        url = f"{self.api}/search/repositories?{urllib.parse.urlencode(params)}"
        data = self._get(url)
        repos = [Repo.from_search_item(item) for item in data.get("items", [])]
        return repos, int(data.get("total_count") or 0)

    def rate_limit(self) -> dict:
        """查看当前限额余额。"""
        return self._get(f"{self.api}/rate_limit")

    def get_repo(self, full_name: str) -> Repo:
        """取单个仓库的元数据。"""
        data = self._get(f"{self.api}/repos/{full_name}")
        return Repo.from_search_item(data)

    # ------------------------------------------------------------------
    def created_ranking(self, days: int, *, per_page: int = 100) -> tuple[list[Repo], dict]:
        """「新建榜」：``created:>N天前`` + 星标降序。"""
        now = dt.datetime.now(dt.timezone.utc)
        since = (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = f"created:>{since}"
        repos, total = self.search_raw(query, per_page=per_page)
        meta = {"days": days, "since": since, "query": query, "total_count": total}
        return repos, meta

    def slot_candidates(self, slot: Slot, *, min_stars: int = MIN_STARS,
                        per_page: int = 100) -> list[Repo]:
        """按能力位的检索式去全量检索成熟项目。"""
        if not slot.query:
            return []
        return self.search_repos(f"{slot.query} stars:>{min_stars}", per_page=per_page)
