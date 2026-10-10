"""离线示例数据，供 ``examples/demo.py`` 与端到端测试共用。

指标取自真实抓取结果，因此离线算出来的质量分与线上一致 —— 演示不是"示意"，
是同一套代码在同一类数据上的真实输出。

数据刻意覆盖了几种典型情况：

* 一个只有 README 的 SEO 引流仓库（演示质量过滤）
* 榜单条目按关键词自动归位
* 检索条目按关键词命中位置判定相关性
* 一个长期未推送的仓库（演示活跃度惩罚）
* 一个已登记人工剔除的仓库（演示校准层）
* 一个没有任何候选的能力位（演示空缺报告）
"""

from __future__ import annotations

import datetime as dt

from skill_atlas.index import RankingResult
from skill_atlas.models import Repo


def _pushed(days_ago: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo(
    full_name: str,
    description: str,
    *,
    stars: int,
    forks: int,
    size_kb: int,
    license: str | None,
    language: str | None,
    open_issues: int = 0,
    pushed_days_ago: int = 1,
    topics: tuple[str, ...] = (),
) -> Repo:
    return Repo(
        full_name=full_name,
        url=f"https://github.com/{full_name}",
        description=description,
        language=language,
        stars=stars,
        forks=forks,
        open_issues=open_issues,
        size_kb=size_kb,
        license=license,
        created_at="2024-01-01T00:00:00Z",
        pushed_at=_pushed(pushed_days_ago),
        topics=list(topics),
    )


def rankings() -> dict[str, RankingResult]:
    """两份「新建榜」，含一条 SEO 垃圾仓库。"""
    day = [
        # 只有 README：2KB、0 fork、无语言、无许可证 -> 必须被过滤
        _repo(
            "KindStatesman/KMS-Pico",
            "Kms Pico Free optimizes your professional desktop environment by "
            "providing a tailored utility configuration.",
            stars=614,
            forks=0,
            size_kb=2,
            license=None,
            language=None,
        ),
        _repo(
            "storytold/wordcraft",
            "An open-source, clean-room reimplementation of Microsoft Word in pure Rust",
            stars=2560,
            forks=745,
            size_kb=30000,
            license="Apache-2.0",
            language="Rust",
            open_issues=25,
            topics=("word", "rust"),
        ),
        _repo(
            "d3/d3",
            "Bring data to life with SVG, Canvas and HTML.",
            stars=113725,
            forks=22639,
            size_kb=59348,
            license="ISC",
            language="Shell",
            open_issues=120,
            pushed_days_ago=134,
            topics=("charts", "d3", "visualization"),
        ),
    ]
    week = [
        _repo(
            "NandhaKishorM/laya",
            "Non-autoregressive System 1 decision engine. Typed choice, score and "
            "yes/no decisions over any text in a single forward pass.",
            stars=32094,
            forks=2850,
            size_kb=13137,
            license="Apache-2.0",
            language="Python",
            open_issues=8,
            topics=("decision-engine", "laya"),
        )
    ]
    return {
        "day": RankingResult(window="day", repos=day, since="2026-10-09T00:00:00Z",
                             total_count=391358),
        "week": RankingResult(window="week", repos=week, since="2026-10-03T00:00:00Z",
                              total_count=3247462),
    }


def enrichment() -> dict[str, list[Repo]]:
    """四个能力位的检索结果，外加一个刻意留空的能力位。"""
    return {
        "本地推理引擎": [
            _repo("ollama/ollama",
                  "Get up and running with large language models locally.",
                  stars=182604, forks=18185, size_kb=95538, license="MIT",
                  language="Go", open_issues=1500, topics=("llama", "llm")),
            _repo("ggml-org/llama.cpp",
                  "LLM inference in C/C++ with minimal dependencies.",
                  stars=130720, forks=11000, size_kb=200000, license="MIT",
                  language="C++", open_issues=400),
            _repo("vllm-project/vllm",
                  "A high-throughput and memory-efficient inference engine.",
                  stars=93506, forks=10000, size_kb=80000, license="Apache-2.0",
                  language="Python", open_issues=900),
        ],
        "日志与监控": [
            _repo("grafana/grafana",
                  "The open and composable observability and data visualization platform.",
                  stars=77221, forks=14838, size_kb=300000, license="AGPL-3.0",
                  language="TypeScript", open_issues=3000),
            _repo("prometheus/prometheus",
                  "The Prometheus monitoring system and time series database.",
                  stars=66459, forks=10905, size_kb=150000, license="Apache-2.0",
                  language="Go", open_issues=800),
        ],
        "浏览器与插件": [
            _repo("XIU2/UserScript",
                  "自用的一些乱七八糟 油猴脚本",
                  stars=10087, forks=704, size_kb=2000, license="GPL-3.0",
                  language="JavaScript", open_issues=40, topics=("userscript",)),
            # 558 天未推送：活跃度惩罚的真实案例
            _repo("Tampermonkey/tampermonkey",
                  "Tampermonkey is the most popular userscript manager.",
                  stars=5785, forks=576, size_kb=3714, license="GPL-3.0",
                  language="JavaScript", open_issues=600, pushed_days_ago=558,
                  topics=("userscript", "browser-extension")),
        ],
        "磁盘与文件管理": [
            _repo("sxyazi/yazi",
                  "Blazing fast terminal file manager written in Rust.",
                  stars=42731, forks=1200, size_kb=20000, license="MIT",
                  language="Rust", open_issues=300),
            # 已登记人工剔除：与终端文件管理器 ranger 同名撞车
            _repo("apache/ranger",
                  "a file manager for data platforms, with fine-grained authorisation.",
                  stars=900, forks=600, size_kb=90000, license="Apache-2.0",
                  language="Java", open_issues=100),
        ],
        "语音识别与合成": [
            _repo("ggml-org/whisper.cpp",
                  "Port of OpenAI's Whisper model in C/C++ for speech recognition.",
                  stars=42000, forks=4600, size_kb=9000, license="MIT",
                  language="C++", open_issues=400),
        ],
        # 「笔记与编辑器」刻意缺席，用来演示空缺报告
    }
