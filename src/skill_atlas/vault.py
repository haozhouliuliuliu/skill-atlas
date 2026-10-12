"""把能力位索引渲染成 Obsidian 友好的 markdown 库。"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

from .index import WINDOW_LABELS, WINDOW_ORDER, Atlas, Candidate
from .scoring import REL_BONUS, activity_score
from .slots import SLOT_EXCLUDE, Slot, all_slots

#: 常见项目类型 -> 需要的能力位。检索入口的起点。
BLUEPRINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("做一个 Agent 应用", (
        "Agent 编排与 Harness", "Agent Skill 规范与范例", "Agent 记忆与检索",
        "模型接入与聚合", "浏览器自动化与反检测",
    )),
    ("做文档自动化流程", (
        "Office 文档生成与解析", "文件格式转换",
        "浏览器自动化与反检测", "定时任务与调度",
    )),
    ("搭个人知识库", (
        "知识库与本体", "笔记与编辑器", "桌面全文检索", "双向链接与图谱分析",
    )),
    ("做桌面效率工具", (
        "UI 组件与材质", "磁盘与文件管理", "文件格式转换", "剪贴板与快捷启动",
    )),
    ("做内容生产（视频/图文）", (
        "内容生产流水线", "视频编辑与生成", "图像编辑",
        "矢量与 Logo 设计", "语音识别与合成",
    )),
    ("做本地 AI 推理", (
        "本地推理引擎", "系统1决策模型", "模型接入与聚合", "日志与监控",
    )),
    ("做数据/后端服务", (
        "数据库与数据分析", "容器与部署", "认证与权限", "日志与监控", "测试与质量",
    )),
    ("做网络工具", ("网络代理与穿透", "NAS 与媒体管理", "通知与消息")),
    ("做逆向/安全研究", ("逆向工程与调试", "渗透与漏洞", "移动端与设备定制")),
)

_CANDIDATE_HEADER = (
    "| 首选 | 排序分 | 质量分 | 相关 | ★ | Fork | Lic | 语言 | 来源 | Repo | 一句话 |\n"
    "|:--:|---:|---:|:--:|---:|---:|---|---|---|---|---|"
)


def _clean(text: str | None, limit: int) -> str:
    text = (text or "").replace("|", "/").replace("\n", " ").strip()
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def _candidate_row(candidate: Candidate, slot_name: str, first: bool) -> str:
    repo = candidate.repo
    return (
        f"| {'✅' if first else ''} | {candidate.rank_score(slot_name)} "
        f"| {candidate.score} | {candidate.relevance_why(slot_name)} "
        f"| {repo.stars} | {repo.forks} | {repo.license or '—'} "
        f"| {repo.language or '—'} | {candidate.source_label} "
        f"| [[{repo.safe_name()}|{repo.full_name}]] "
        f"| {_clean(repo.description, 80)} |"
    )


def _scrambled(atlas: Atlas, slot: Slot) -> list[Candidate]:
    """本该落到这个能力位、却被更靠前的能力位抢先命中的候选。

    用来区分「真·空缺」与「假·空缺（归属需要人工裁决）」。
    """
    out: list[Candidate] = []
    for candidate in atlas.candidates.values():
        if slot.name in candidate.slots:
            continue
        text = candidate.repo.search_text()
        if any(re.search(p, text) for p in slot.patterns):
            out.append(candidate)
    out.sort(key=lambda c: (-c.score, c.full_name))
    return out


# ---------------------------------------------------------------------------
# 各类笔记
# ---------------------------------------------------------------------------
def _slot_note(slot: Slot, total: int, shown: list[Candidate], atlas: Atlas) -> str:
    note = ""
    if total > len(shown):
        note = f"（共 {total} 个候选，此处展示前 {len(shown)}）"

    lines = [
        f"# {slot.name}",
        "",
        f"**领域**：{slot.domain}　**候选数**：{total}　"
        f"**核心能力位**：{'是' if slot.core else '否'}",
        "",
        "> 定位说明：这是项目里一个「会被替换的位置」。同位候选按排序分排列，",
        "> 发现更好的就替换首选，并把变更记到下面的替换记录。",
        "> 「来源」列：榜单 = 来自近期新建榜；检索 = 按本能力位关键词定向检索补全。",
        f"> 「相关」列取值与加成：{', '.join(f'{k} {v:+d}' for k, v in REL_BONUS.items() if k != '—')}",
        "",
        f"**检索式**：`{slot.query}`",
        "",
    ]

    if shown:
        lines += [f"## 候选（排序分 = 质量分 + 相关性加成）{note}", "", _CANDIDATE_HEADER]
        lines += [
            _candidate_row(c, slot.name, i == 0) for i, c in enumerate(shown)
        ]
        lines += [
            "",
            "## 替换记录",
            "",
            "| 日期 | 换下 | 换上 | 理由 |",
            "|---|---|---|---|",
            "",
        ]
        exclusions = SLOT_EXCLUDE.get(slot.name)
        if exclusions:
            lines += ["## 人工剔除", "", "| Repo | 剔除原因 |", "|---|---|"]
            lines += [f"| {name} | {why} |" for name, why in exclusions.items()]
            lines.append("")
    else:
        scrambled = _scrambled(atlas, slot)
        if scrambled:
            lines += [
                "## ⚠️ 假·空缺（有候选，但被判给了更靠前的能力位）",
                "",
                "下面这些条目命中了本能力位的关键词，却因为分类优先级被归到了别处。",
                "**需要人工裁决**：把它们留在原位，还是改判到本能力位？",
                "",
                "| 质量分 | Repo | 当前被归到 |",
                "|---:|---|---|",
            ]
            for candidate in scrambled[:20]:
                other = "、".join(f"[[{s}]]" for s in candidate.slots) or "—"
                lines.append(
                    f"| {candidate.score} "
                    f"| [[{candidate.repo.safe_name()}|{candidate.full_name}]] | {other} |"
                )
            lines.append("")
        else:
            lines += [
                "## ⚠️ 真·空缺（无任何候选）",
                "",
                "**榜单与定向检索都没有**找到落到这个位置的项目，且没有被其他能力位抢走。",
                "",
                "1. 这个位置确实没有现成轮子 —— 属于你的**机会区**，需要自己写；",
                "2. 检索关键词没命中 —— 需要补关键词后重新运行 `skill-atlas enrich`。",
                "",
            ]
        lines += ["## 候选（待补充）", "", "| 首选 | 质量分 | Repo | 备注 |",
                  "|:--:|---:|---|---|", ""]
    return "\n".join(lines)


def _index_note(atlas: Atlas, stats, generated_at: str, note_count: int) -> str:
    lines = [
        "# 能力位总表",
        "",
        f"生成时间：{generated_at}　|　条目笔记：{note_count}　|　能力位：{len(stats)}",
        "",
        "用法：先看「项目蓝图」确定需要哪些能力位，再回到这里点进去挑候选。",
        "",
        "**✅ = 已有首选　⚠️ = 空缺**",
        "",
        "| 领域 | 能力位 | 候选数 | 首选 | 排序分 | 状态 |",
        "|---|---|---:|---|---:|:--:|",
    ]
    gaps: list[str] = []
    for slot, total, shown in stats:
        star = "⭐" if slot.core else ""
        if shown:
            top = shown[0]
            lines.append(
                f"| {slot.domain} | [[{slot.name}]]{star} | {total} "
                f"| [[{top.repo.safe_name()}|{top.full_name}]] "
                f"| {top.rank_score(slot.name)} | ✅ |"
            )
        else:
            gaps.append(slot.name)
            lines.append(f"| {slot.domain} | [[{slot.name}]]{star} | 0 | — | — | ⚠️ |")

    lines += [
        "",
        "## 覆盖情况",
        "",
        f"- 能力位总数：{len(stats)}　有候选：{len(stats) - len(gaps)}",
        f"- 空缺：{len(gaps)} 个 —— {', '.join(gaps) if gaps else '无'}",
        "",
        "空缺说明这个位置没有现成轮子（机会区），或者检索关键词需要调整。",
        "",
    ]
    return "\n".join(lines)


def _blueprint_note() -> str:
    lines = [
        "# 项目蓝图：从「我要做什么」到「用哪些能力位」",
        "",
        "这是检索入口。说出你要做的项目，按下面的组合去 [[01-能力位总表]] 逐个取首选。",
        "",
        "也可以用命令行直接查：",
        "",
        "```bash",
        'skill-atlas query "我要做一个能自动整理 Word 和 PDF 的 agent"',
        "```",
        "",
    ]
    for name, slots in BLUEPRINTS:
        lines.append(f"## {name}")
        lines.append("")
        lines += [f"- [[{s}]]" for s in slots]
        lines.append("")
    return "\n".join(lines)


def _repo_note(candidate: Candidate) -> str:
    repo = candidate.repo
    hits = candidate.windows or "—"
    best = candidate.best_rank
    rank_line = f"{hits}（最高第 {best} 名）" if best else "未上榜（来自定向检索）"
    slot_names = list(candidate.slots)
    slot_tags = [re.sub(r"[\s/]+", "-", s).lower() for s in slot_names]
    domain = next((s for s in all_slots() if s.name in candidate.slots), None)
    domain_name = domain.domain if domain else "待归位"
    # 注意：这里必须先算出 domain_tag 再插进 f-string。
    # 早期版本把 re.sub(r"[\s/]+", ...) 直接写在 f-string 表达式里，
    # 那要求 Python 3.12+（PEP 701 才允许表达式含反斜杠），
    # 而 pyproject.toml 声明支持 3.10 —— 结果 3.10/3.11 直接 SyntaxError。
    domain_tag = re.sub(r"[\s/]+", "-", domain_name).lower()

    front = [
        "---",
        f"repo: {repo.full_name}",
        f"url: {repo.url}",
        f"stars: {repo.stars}",
        f"forks: {repo.forks}",
        f"language: {repo.language or 'null'}",
        f"license: {repo.license or 'null'}",
        f"size_kb: {repo.size_kb}",
        f"created: {repo.created_date()}",
        f"pushed: {repo.pushed_date()}",
        f"数据来源: [{candidate.source_label}]",
        f"领域: {domain_name}",
        "能力位:",
    ]
    front += [f"  - {s}" for s in slot_names] or ["  - 待归位"]
    front += [
        f"质量分: {candidate.score}",
        f"命中榜单: [{hits}]",
        f"最高排名: {best if best else 'null'}",
        "tags:",
        "  - skill-atlas",
        f"  - domain/{domain_tag}",
    ]
    for tag in dict.fromkeys(slot_tags):
        front.append(f"  - slot/{tag}")
    front += [
        "---",
        "",
        f"# {repo.full_name}",
        "",
        f"> {repo.description or '(无描述)'}",
        "",
        "## 可验证指标",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| ★ Stars | {repo.stars} |",
        f"| Fork | {repo.forks} |",
        f"| Open Issues | {repo.open_issues} |",
        f"| 语言 | {repo.language or '—'} |",
        f"| 许可证 | {repo.license or '—'} |",
        f"| 体积 | {repo.size_kb} KB |",
        f"| 创建 | {repo.created_date()} |",
        f"| 最近推送 | {repo.pushed_date()} |",
        f"| 已归档 | {'是' if repo.archived else '否'} |",
        f"| 活跃度系数 | {activity_score(repo):.2f} |",
        f"| 数据来源 | {candidate.source_label} |",
        f"| 命中榜单 | {rank_line} |",
        f"| **质量分** | **{candidate.score} / 100** |",
        "",
        "## 归位",
        "",
    ]
    if slot_names:
        for name in slot_names:
            level, why = candidate.slots[name]
            slot = next((s for s in all_slots() if s.name == name), None)
            core = "（核心）" if slot and slot.core else ""
            front.append(f"- 能力位：[[{name}]]{core}　相关性 {why}")
    else:
        front.append("- 未归位")
    front += [
        "",
        "## 我的评估（待填）",
        "",
        "- 能否直接用：",
        "- 适配我的场景需要改什么：",
        "- 与同位其他候选相比的优势：",
        "",
    ]
    return "\n".join(front)


def _log_note(window: str, atlas: Atlas, stamp: str) -> str:
    result = atlas.rankings.get(window)
    if not result:
        return ""
    junk_names = {repo.full_name for repo, _ in atlas.junk}
    bad = [repo for repo in result.repos if repo.full_name in junk_names]
    good = [repo for repo in result.repos if repo.full_name not in junk_names]
    rate = round(100 * len(bad) / len(result.repos)) if result.repos else 0

    lines = [
        f"# 检索日志 {stamp} · {WINDOW_LABELS.get(window, window)}榜",
        "",
        f"- 口径：`created:>{result.since}`，按 star 降序取前 100",
        f"- 该条件下仓库总数：{result.total_count}",
        f"- 抓取：{len(result.repos)} 条　通过质量过滤：{len(good)} 条　剔除：{len(bad)} 条",
        f"- 剔除率：{rate}%",
        "",
        "## 通过过滤的条目",
        "",
        "| 排名 | ★ | Fork | 质量分 | Repo | 能力位 |",
        "|---:|---:|---:|---:|---|---|",
    ]
    for rank, repo in enumerate(result.repos, 1):
        candidate = atlas.candidates.get(repo.full_name)
        if candidate is None:
            continue
        slot_cell = "、".join(f"[[{s}]]" for s in candidate.slots) or "—"
        lines.append(
            f"| {rank} | {repo.stars} | {repo.forks} | {candidate.score} "
            f"| [[{repo.safe_name()}|{repo.full_name}]] | {slot_cell} |"
        )
    lines += [
        "",
        "## 被剔除（仅列前 15）",
        "",
        "| 排名 | ★ | 体积 | Repo | 理由 |",
        "|---:|---:|---:|---|---|",
    ]
    reasons = {repo.full_name: why for repo, why in atlas.junk}
    shown = 0
    for rank, repo in enumerate(result.repos, 1):
        if repo.full_name not in reasons:
            continue
        if shown >= 15:
            break
        shown += 1
        lines.append(
            f"| {rank} | {repo.stars} | {repo.size_kb}KB | {repo.full_name} "
            f"| {reasons[repo.full_name]} |"
        )
    lines.append("")
    return "\n".join(lines)


def _vault_readme(atlas: Atlas, stats, note_count: int, per_slot: int) -> str:
    gaps = [slot.name for slot, total, _ in stats if total == 0]
    return f"""# Skill Atlas · 我的能力位索引

一个用来回答「**我要做 X，有什么现成轮子可以直接用**」的知识库。

## 它解决什么问题

做项目时最贵的一步不是写代码，而是**不知道该用什么**。这个库把 GitHub 上的候选项目
按「能力位」组织好，每个位置都有多个备选、按可验证指标排序。你只需要说出项目目标，
就能顺着一张蓝图把需要的能力位逐个取下来。

## 目录

| 目录 | 作用 |
|---|---|
| `01-能力位总表.md` | **主入口**。所有能力位一览，标出空缺 |
| `02-项目蓝图.md` | 「我要做 X」→ 需要哪几个能力位 |
| `10-能力位/` | 每个能力位一个笔记：候选排序表 + 空缺说明 + 替换记录 + 人工剔除记录 |
| `20-项目条目/` | 每个仓库一个笔记：可验证指标 + 你的评估栏 |
| `30-检索日志/` | 每次抓榜的产出与剔除情况 |
| `_atlas_manifest.json` | 本工具生成过哪些文件的清单，用于安全清理过期产物 |

原始抓取数据不放在库里 —— 它在 `data/` 目录，是这份产物的来源而不是产物本身。

## 三个设计决定

**1. 分类单位是「能力位」，不是「主题标签」**
主题标签（比如"AI"）无法回答"该用哪个"。能力位是一个**会被替换的具体位置**
（比如"桌面全文检索"）。同一个位置上放多个候选，才能谈择优与替换。

**2. 质量靠可验证指标，不靠描述话术**
每个条目按 stars / forks / 活跃度 / 许可证 / 体积 算 0-100 分。
实测发现：SEO 垃圾仓库只有 README（体积 ≤8KB）、0 fork、0 issue、无许可证，
与真实项目在体积分布上呈**双峰**（≤8KB 有 115 个，9-50KB 仅 3 个），判据非常干净。

**3. 空缺能力位显式登记**
空缺 = 这个位置没有现成轮子 = 你的机会区，或者检索口径要换。
空缺分两种：**真·空缺**（没有任何候选）与**假·空缺**（有候选但被判给别处，待裁决）。

## 日常维护流程

```bash
skill-atlas update            # 抓取 + 补全 + 报告与上次基线的差异
skill-atlas build             # 确认变化后渲染这个库并推进基线
skill-atlas query "我要做 X"   # 反查该用哪些能力位
```

`update` 刻意不自动建库：只有基线还停在上一次，`diff` 才有意义。

如果某个能力位出现排序分更高的候选，在 `10-能力位/<位名>.md` 里把 ✅ 换到新候选，
并在「替换记录」写下日期与理由；若判定某条是错误命中，写进 `SLOT_EXCLUDE`。

> 本库由 skill-atlas 生成，它用 `_atlas_manifest.json` 记录自己写过哪些文件，
> 下次渲染时会清掉不再生成的那些（**不会**碰你的其它笔记）。

## 当前状态

- 条目笔记：{note_count}　候选池：{len(atlas.candidates)}
- 能力位：{len(stats)}　其中空缺 {len(gaps)} 个
- 每个能力位最多展示 {per_slot} 个候选
- 榜单剔除：{len(atlas.junk)} 条被判为不可复用

## 已知局限

- 抓取口径偏向「新建」和「高星」，**中小型但极合用的项目**容易漏。
- 能力位归属由关键词规则判定，存在同名撞车等误判，需要人工校准。
- 相关性只按「关键词命中位置」判断，**不理解语义**。它能正确排序 `dify`，
  但说不清 `dify` 和 `langgraph` 哪个更适合你。
- 质量分衡量的是「项目是否健康」，**不等于「是否适合你的场景」**。
"""


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
#: 记录本工具生成过哪些文件，用于安全地清理过期产物。
MANIFEST_NAME = "_atlas_manifest.json"


def _load_manifest(out_dir: pathlib.Path) -> set[str]:
    path = out_dir / MANIFEST_NAME
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return set()
    files = payload.get("files")
    return set(files) if isinstance(files, list) else set()


def _save_manifest(out_dir: pathlib.Path, files: set[str]) -> None:
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps({"files": sorted(files)}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def _prune(out_dir: pathlib.Path, previous: set[str], current: set[str]) -> list[str]:
    """删掉「上次由我们生成、这次不再生成」的文件。

    只碰清单里的路径。库目录可能被指向用户自己的 Obsidian 仓库，
    直接清空目录会删掉与本事无关的笔记 —— 这是不可接受的。
    """
    removed: list[str] = []
    for rel in sorted(previous - current):
        target = out_dir / rel
        try:
            if target.is_file():
                target.unlink()
                removed.append(rel)
        except OSError:
            continue
    # 顺手清掉因此变空的目录（不递归删除非空目录）
    for directory in sorted(
        (p for p in out_dir.rglob("*") if p.is_dir()), reverse=True
    ):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            continue
    return removed


def render_vault(
    atlas: Atlas,
    out_dir: pathlib.Path,
    *,
    per_slot: int = 10,
    generated_at: str | None = None,
) -> dict[str, int]:
    """把索引渲染成 markdown 库，返回各类文件数量。

    会清理由**上一次渲染**产生、而这次不再产生的文件（通过 ``_atlas_manifest.json``
    记录）。用户的其它文件不受影响。
    """
    out_dir = pathlib.Path(out_dir)
    slot_dir = out_dir / "10-能力位"
    repo_dir = out_dir / "20-项目条目"
    log_dir = out_dir / "30-检索日志"
    previous = _load_manifest(out_dir)
    written: set[str] = set()

    def write(path: pathlib.Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.add(path.relative_to(out_dir).as_posix())

    for directory in (slot_dir, repo_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=True)

    stamp = (generated_at or dt.datetime.now().strftime("%Y-%m-%d %H:%M"))[:10]
    pretty_time = generated_at or dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    # 注意：文件名只能取日期部分。早期版本把 "YYYY-MM-DD HH:MM" 整个用作文件名，
    # 冒号在 Windows 上是非法字符，导致日志文件静默写不出来。

    capped = atlas.cap(per_slot)
    stats = list(atlas.slot_stats(capped))
    note_repos = atlas.note_repos(capped)

    for slot, total, shown in stats:
        write(slot_dir / f"{slot.name}.md", _slot_note(slot, total, shown, atlas))
    for candidate in note_repos:
        write(repo_dir / f"{candidate.repo.safe_name()}.md", _repo_note(candidate))

    write(out_dir / "README.md", _vault_readme(atlas, stats, len(note_repos), per_slot))
    write(out_dir / "01-能力位总表.md",
          _index_note(atlas, stats, pretty_time, len(note_repos)))
    write(out_dir / "02-项目蓝图.md", _blueprint_note())

    for window in WINDOW_ORDER:
        text = _log_note(window, atlas, stamp)
        if text:
            write(log_dir / f"{stamp}-{window}.md", text)

    removed = _prune(out_dir, previous, written)
    _save_manifest(out_dir, written)

    return {
        "slots": len(stats),
        "repos": len(note_repos),
        "logs": sum(1 for p in written if p.startswith("30-检索日志/")),
        "candidates": len(atlas.candidates),
        "junk": len(atlas.junk),
        "gaps": sum(1 for _slot, total, _shown in stats if total == 0),
        "removed": len(removed),
    }


def slot_index(atlas: Atlas) -> dict[str, list[str]]:
    """能力位 -> 排好序的仓库名列表（机器可读，供 query 复用）。"""
    return {slot: [c.full_name for c in recs] for slot, recs in atlas.by_slot.items()}
