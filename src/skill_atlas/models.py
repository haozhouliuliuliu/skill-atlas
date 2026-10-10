"""仓库数据模型。

刻意只保留**可验证**的字段：不做任何语义猜测，所有排序依据都能在
GitHub 页面上被人工复核。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

#: 从 GitHub search API 响应里保留的字段
SEARCH_FIELDS = (
    "full_name",
    "html_url",
    "description",
    "language",
    "stargazers_count",
    "forks_count",
    "open_issues_count",
    "created_at",
    "pushed_at",
    "archived",
    "homepage",
    "size",
)


@dataclass
class Repo:
    """一个 GitHub 仓库。"""

    full_name: str
    url: str = ""
    description: str = ""
    language: str | None = None
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    size_kb: int = 0
    license: str | None = None
    created_at: str = ""
    pushed_at: str = ""
    archived: bool = False
    topics: list[str] = field(default_factory=list)
    homepage: str | None = None

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------
    @classmethod
    def from_search_item(cls, item: dict) -> "Repo":
        """从 GitHub search API 的单条结果构造。

        也兼容本项目 :meth:`to_dict` 的输出 —— 后者把许可证存成纯字符串，
        而 GitHub API 返回的是 ``{"spdx_id": ...}`` 字典。两种都要认，
        否则“抓取 → 落盘 → 再读回”这条链路会在许可证字段上崩掉。
        """
        raw_license = item.get("license")
        if isinstance(raw_license, dict):
            license_id: str | None = raw_license.get("spdx_id")
        else:
            license_id = raw_license or None
        return cls(
            full_name=item.get("full_name") or "",
            url=item.get("html_url") or "",
            description=item.get("description") or "",
            language=item.get("language"),
            stars=item.get("stargazers_count") or 0,
            forks=item.get("forks_count") or 0,
            open_issues=item.get("open_issues_count") or 0,
            size_kb=item.get("size") or 0,
            license=license_id,
            created_at=item.get("created_at") or "",
            pushed_at=item.get("pushed_at") or "",
            archived=bool(item.get("archived")),
            topics=list(item.get("topics") or []),
            homepage=item.get("homepage") or None,
        )

    def to_dict(self) -> dict:
        return {
            "full_name": self.full_name,
            "html_url": self.url,
            "description": self.description,
            "language": self.language,
            "stargazers_count": self.stars,
            "forks_count": self.forks,
            "open_issues_count": self.open_issues,
            "size": self.size_kb,
            "license": self.license,
            "created_at": self.created_at,
            "pushed_at": self.pushed_at,
            "archived": self.archived,
            "topics": self.topics,
            "homepage": self.homepage,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Repo":
        """接受本项目的 to_dict 输出，也兼容 GitHub API 原始格式。"""
        return cls.from_search_item(data)

    # ------------------------------------------------------------------
    # 派生属性
    # ------------------------------------------------------------------
    def owner(self) -> str:
        return self.full_name.split("/", 1)[0]

    def name(self) -> str:
        parts = self.full_name.split("/", 1)
        return parts[1] if len(parts) > 1 else self.full_name

    def safe_name(self) -> str:
        """适合当文件名的形式。"""
        return self.full_name.replace("/", "--")

    def days_since_push(self, now: dt.datetime | None = None) -> int:
        """距最近一次推送的天数；无法解析时返回一个很大的数。"""
        if not self.pushed_at:
            return 9999
        try:
            pushed = dt.datetime.fromisoformat(self.pushed_at.replace("Z", "+00:00"))
        except ValueError:
            return 9999
        now = now or dt.datetime.now(dt.timezone.utc)
        if pushed.tzinfo is None:
            pushed = pushed.replace(tzinfo=dt.timezone.utc)
        return max(0, (now - pushed).days)

    def search_text(self) -> str:
        """用于关键词匹配的小写文本（名字 + 描述 + 语言 + topics）。"""
        return " ".join(
            [
                self.full_name,
                self.description or "",
                self.language or "",
                " ".join(self.topics),
            ]
        ).lower()

    def name_text(self) -> str:
        return self.full_name.lower()

    def topics_text(self) -> str:
        return " ".join(self.topics).lower()

    def description_text(self) -> str:
        return (self.description or "").lower()

    def created_date(self) -> str:
        return self.created_at[:10]

    def pushed_date(self) -> str:
        return self.pushed_at[:10]
