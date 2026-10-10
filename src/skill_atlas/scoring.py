"""打分与排序。

只用可验证指标，且每个公式都附上"为什么这么设"以及踩过的坑。
"""

from __future__ import annotations

import math
import re

from .models import Repo

# ---------------------------------------------------------------------------
# 活跃度
# ---------------------------------------------------------------------------
def activity_score(repo: Repo) -> float:
    """最近推送时间的阶梯计分（0-1）。"""
    days = repo.days_since_push()
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.8
    if days <= 90:
        return 0.5
    if days <= 365:
        return 0.2
    return 0.05


# ---------------------------------------------------------------------------
# 质量分
# ---------------------------------------------------------------------------
def quality_score(repo: Repo) -> int:
    """可验证质量分 0-100。

    构成：

    * 采用度 55 = stars 30 + forks 25，均为对数刻度
    * 工程完备 30 = 许可证 10 + 代码量 10 + issue 活跃 10
    * 活跃度 15

    .. warning::

       **修正记录。** 早期版本把对数分母设成 ``stars/4.5``、``forks/2.0``，
       于是 3 万星和 18 万星都拿满分。后果是 697 星的 ``bas3line/ascii``
       得 86 分，压过了 11.3 万星 / 2.26 万 fork 的 ``d3/d3``（84 分）。
       分母放大到 5.5 / 4.6 后不再过早饱和。
    """
    s = 0.0
    s += 30 * min(1.0, math.log10(1 + repo.stars) / 5.5)
    s += 25 * min(1.0, math.log10(1 + repo.forks) / 4.6)
    s += 10 if repo.license else 0
    s += 10 * min(1.0, repo.size_kb / 1000.0)
    s += 10 if repo.open_issues >= 10 else (6 if repo.open_issues >= 1 else 0)
    s += 15 * activity_score(repo)
    return int(round(s))


# ---------------------------------------------------------------------------
# 相关性
# ---------------------------------------------------------------------------
def query_words(terms: str) -> list[str]:
    """把检索式拆成纯关键词（去掉 ``OR``、``stars:`` 限定符与引号）。"""
    words: list[str] = []
    for part in re.split(r"\s+OR\s+", terms, flags=re.I):
        part = part.strip().strip('"').lower()
        if not part or part.startswith("stars:"):
            continue
        # 形如 `gsap stars:>200` 的残尾要去掉
        part = re.sub(r"\s*stars:\S+\s*$", "", part).strip()
        if part:
            words.append(part)
    return words


def term_hit(text: str, word: str) -> bool:
    """关键词命中判定。

    英文单词必须**按词边界**匹配。否则检索词 ``zep`` 会命中
    ``zephyrproject/zephyr``、``dify`` 会命中 ``modify``/``codify``，
    把大量无关仓库带进候选池。含空格的短语按整体子串匹配。
    """
    if not word:
        return False
    if re.search(r"[a-z]", word):
        if " " in word:
            return word in text
        return (
            re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None
        )
    return word in text


#: 相关性等级 -> (排序加成, 展示名)
REL_BONUS: dict[str, int] = {
    "人工": 100,
    "名字": 20,
    "榜单": 20,
    "topics": 0,
    "描述": -15,
    "—": -100,
}


def relevance(repo: Repo, terms: str) -> tuple[int, str]:
    """相关性 0-3，附带判定依据。

    依据是**关键词命中的位置**，因为命中位置强烈反映项目的主业：

    * 3 = 出现在仓库名里，如 ``langchain-ai/langchain``
    * 2 = 出现在 topics 里
    * 1 = 只出现在描述里
    * 0 = 完全没命中

    .. note::

       为什么不能直接信 GitHub 的排序：``sort=stars`` 会把「topics 蹭到
       关键词」的大项目排到前面 —— 查 ``langchain`` 时
       ``microsoft/markitdown`` 排第一。
    """
    words = query_words(terms)
    if not words:
        return 3, "榜单"
    if any(term_hit(repo.name_text(), w) for w in words):
        return 3, "名字"
    if any(term_hit(repo.topics_text(), w) for w in words):
        return 2, "topics"
    if any(term_hit(repo.description_text(), w) for w in words):
        return 1, "描述"
    return 0, "—"


def rank_score(score: int, rel_why: str) -> int:
    """排序分 = 质量分 + 相关性加成。

    .. note::

       **为什么不用硬分层。** 先按相关性分层、层内再按质量分，会出现断崖：
       30,731 星的 ``Bilibili-Evolved``（topics 命中）排到了 3,068 星的
       ``webextension-polyfill``（名字命中）后面。

       **为什么"名字"要给 +20。** topics 太容易被蹭到 ——
       ``freeCodeCamp`` 的 topics 里**真的**有 ``d3``（课程教 D3）。
       若不加权，它 100 分的质量分会压过 ``d3/d3`` 本身（84 分）。
       加 20 分等于要求「topics 命中者质量分必须高出 20 分才能反超」。
    """
    return score + REL_BONUS.get(rel_why, 0)
