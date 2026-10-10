"""能力位（slot）定义。

设计要点
--------
分类单位不是"主题标签"，而是**会被替换的具体位置**。
"AI" 这样的标签回答不了"我该用哪个"；"桌面全文检索"才能。
同一个位置上放多个候选、按可验证指标排序，于是"发现更好的就换掉"才有落点。

每个能力位同时携带两份配置：

* ``patterns`` —— 关键词规则，用于把**榜单**里的仓库自动归位
* ``query``    —— 检索式，用于按这个能力位去**全量检索**成熟项目

两者放在一起，是为了避免它们各自漂移（早期版本它们分散在两个文件里，
改了一个忘了另一个，直接导致该能力位抓到一批无关的 TTS 论文）。

``patterns`` 为空的能力位是**标准能力位占位**：无论榜单里有没有，
它都要在库里占一格，用来暴露缺口。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Repo


@dataclass(frozen=True)
class Slot:
    """一个会被替换的能力位。"""

    domain: str
    name: str
    patterns: tuple[str, ...] = ()
    core: bool = False
    query: str = ""

    @property
    def is_staple(self) -> bool:
        """标准能力位占位（没有关键词规则，只靠检索式）。"""
        return not self.patterns


# ---------------------------------------------------------------------------
# 全部能力位。顺序即归位优先级：先匹配先归位，所以具体的要排在泛化的前面。
# ---------------------------------------------------------------------------
SLOTS: tuple[Slot, ...] = (
    # ---------------------------- AI 工程 ----------------------------
    Slot("AI工程", "Agent Skill 规范与范例", (
        r"agent skill", r"skills?\b", r"skill for", r"prompt.*skill", r"技能",
    ), True, '"agent skills" OR "claude skills" OR "skill library" OR "prompt library"'),
    Slot("AI工程", "Agent 编排与 Harness", (
        r"agent harness", r"agent-native", r"multi-agent", r"\bagents?\b",
        r"agentic", r"autonomous", r"ai coworker", r"agent preset",
    ), True, "langchain OR autogen OR crewai OR dify"),
    Slot("AI工程", "Agent 记忆与检索", (
        r"memory", r"memo", r"recall", r"remember",
    ), True, '"agent memory" OR mem0 OR "long-term memory" OR zep'),
    Slot("AI工程", "模型接入与聚合", (
        r"our-free-model", r"free model", r"frontier models", r"model.*place",
        r"openai.*compatible", r"api.*gateway", r"多账号.*网关", r"magpie",
    ), True, 'litellm OR "llm gateway" OR openrouter OR "one-api"'),
    # 注意：本能力的检索式**不能**用 "non-autoregressive" ——
    # 该词在 TTS 领域是标准术语，会把 SoundStorm / Matcha-TTS 这类语音论文灌进来
    # （实测 12 条污染）。必须按这个新兴集群的自有名字检索。
    Slot("AI工程", "系统1决策模型", (
        r"\bjev\b", r"\blaya\b", r"\bkev\b", r"decision (engine|model)",
        r"system 1", r"non-autoregressive", r"typed (choice|decision)",
        r"calibrated probabilit", r"recursive self-improvement",
    ), True, 'jev OR laya OR "decision engine" OR "system one"'),
    Slot("AI工程", "本地推理引擎", (
        r"inference engine", r"\bmlx\b", r"core ?ml", r"quantiz", r"\bvram\b",
        r"local.*(model|inference)", r"consumer hardware", r"neural engine",
        r"\bmoe\b", r"on your own",
    ), True, '"llama.cpp" OR ollama OR vllm OR "inference engine"'),
    Slot("AI工程", "代码理解与检索", (
        r"code search", r"find code", r"jevgrep", r"coding agent", r"code agent",
        r"\bcompiler\b", r"\btsc\b", r"pair program", r"autocomplete",
    ), True, '"code search" OR "ast-grep" OR "code understanding" OR "semantic grep"'),
    Slot("AI工程", "浏览器自动化与反检测", (
        r"playwright", r"puppeteer", r"selenium", r"undetected", r"anti-bot",
        r"web agent", r"scrap", r"crawl", r"\bspider\b", r"browser automation",
    ), True, 'playwright OR "browser automation" OR "stealth browser" OR "anti-detect"'),
    Slot("AI工程", "Agent 可观测与调试界面", (
        r"diagram", r"dashboard", r"observe|observab", r"debug", r"panel",
        r"robot head", r"notch", r"status", r"visual-geometric",
    ), False, 'langfuse OR "llm observability" OR "llm tracing" OR "agent monitoring"'),
    Slot("AI工程", "内容生产流水线", (
        r"reelmimic", r"short film", r"carousel", r"日报", r"热点", r"opuscar",
        r"genjustsu", r"video replacement", r"storyboard", r"single-file canvas",
    ), False, '"video automation" OR remotion OR "content pipeline" OR "faceless video"'),
    Slot("AI工程", "语音识别与合成", (), True,
         'whisper OR "text to speech" OR "voice cloning" OR "speech recognition"'),
    Slot("AI工程", "文档解析与 RAG 切分", (), True,
         'unstructured OR llamaindex OR docling OR "document parsing"'),
    Slot("AI工程", "Agent 评测与回归", (), True,
         '"llm evaluation" OR promptfoo OR "agent benchmark" OR "eval framework"'),

    # ---------------------------- 文档办公 ----------------------------
    Slot("文档办公", "Office 文档生成与解析", (
        r"\bword\b", r"\bexcel\b", r"spreadsheet", r"powerpoint", r"slide",
        r"\bpdf\b", r"docx", r"xlsx", r"\boffice\b",
    ), True, 'openpyxl OR python-docx OR "office documents" OR libreoffice'),
    Slot("文档办公", "排版与出版", (
        r"typeset", r"layout", r"排版", r"publish", r"印刷",
    ), False, 'typst OR latex OR pandoc OR "typesetting"'),
    Slot("文档办公", "财务与票据", (
        r"invoice", r"ledger", r"finance", r"financial", r"发票", r"账",
    ), False, 'firefly-iii OR "personal finance" OR invoicing OR ledger'),
    Slot("文档办公", "邮件与日历", (), True,
         '"email client" OR mailspring OR caldav OR imap'),
    Slot("文档办公", "PDF 深度处理", (), True,
         'pdfplumber OR pymupdf OR "pdf parsing" OR "pdf toolkit"'),

    # ---------------------------- 知识管理 ----------------------------
    Slot("知识管理", "知识库与本体", (
        r"ontology", r"knowledge (base|graph|work|management)", r"second brain",
        r"\bpkm\b", r"知识库", r"本体", r"open-glean",
    ), True, 'ontology OR "knowledge graph" OR "second brain" OR khoj'),
    Slot("知识管理", "笔记与编辑器", (
        r"obsidian", r"note-?taking", r"zettelkasten", r"markdown editor",
        r"笔记", r"双链",
    ), True, 'obsidian OR logseq OR "note taking" OR "markdown editor"'),
    Slot("知识管理", "任务与项目管理", (
        r"project management", r"task", r"kanban", r"scheduling", r"workspace",
    ), False, 'kanban OR "project management" OR "task management" OR plane'),
    Slot("知识管理", "双向链接与图谱分析", (), True,
         '"graph visualization" OR "backlinks" OR "knowledge graph" OR "graph analysis"'),

    # ---------------------------- 系统桌面 ----------------------------
    Slot("系统桌面", "桌面全文检索", (
        r"file search", r"fsearch", r"finder", r"fuzzy", r"indexed content",
        r"treemap", r"文件检索", r"检索",
    ), True, 'ripgrep OR "file search" OR fzf OR "everything search"'),
    # 注意：不要用裸词 "ranger" —— 会与 Hadoop 的 apache/ranger（权限管理）撞名
    Slot("系统桌面", "磁盘与文件管理", (
        r"\bdisk\b", r"archive", r"file browser", r"backup", r"launcher",
        r"download\w*", r"网盘", r"下载",
    ), True, '"file manager" OR yazi OR "disk usage" OR superfile'),
    Slot("系统桌面", "系统清理与优化", (
        r"debloat", r"optimi[sz]", r"cleaner|cleanup|clean up", r"booster",
        r"uninstall", r"shader compilation", r"清理", r"优化",
    ), False, 'bleachbit OR "system cleaner" OR debloat OR "system optimizer"'),
    Slot("系统桌面", "截图与录屏", (
        r"screenshot", r"screen record", r"截图", r"录屏", r"screen capture",
    ), False, 'flameshot OR sharex OR "screen recorder" OR obs-studio'),
    Slot("系统桌面", "文件格式转换", (
        r"convert", r"conversion", r"transcod", r"格式转换", r"转换",
    ), True, 'pandoc OR ffmpeg OR imagemagick OR "file converter"'),
    Slot("系统桌面", "本地音乐与媒体库", (
        r"music search", r"playlist", r"playback", r"spotify", r"groovebox",
        r"\bdaw\b", r"music production", r"audio workstation", r"sound design",
    ), False, 'navidrome OR beets OR "music player" OR "media library"'),
    Slot("系统桌面", "剪贴板与快捷启动", (), True,
         '"clipboard manager" OR "app launcher" OR alfred OR raycast'),

    # ---------------------------- 创意设计 ----------------------------
    Slot("创意设计", "图像编辑", (
        r"photoshop", r"lightroom", r"image edit", r"photo", r"图像", r"修图",
    ), True, 'gimp OR krita OR darktable OR "image editor"'),
    Slot("创意设计", "矢量与 Logo 设计", (
        r"illustrator", r"vector", r"logo", r"svg", r"矢量", r"品牌",
    ), True, 'inkscape OR penpot OR "svg editor" OR "vector graphics"'),
    Slot("创意设计", "视频编辑与生成", (
        r"video", r"film", r"premiere", r"motion", r"cut", r"视频", r"剪辑", r"动画",
    ), True, 'kdenlive OR shotcut OR "video editor" OR "video generation"'),
    Slot("创意设计", "CAD 与 3D", (
        r"\bcad\b", r"autocad", r"sketchup", r"revit", r"3d (model|asset|print)",
        r"floorplan", r"drafting",
    ), False, 'freecad OR blender OR openscad OR "3d modeling"'),

    # ---------------------------- Web 前端 ----------------------------
    Slot("Web前端", "动画与可视化", (
        r"animat", r"\bcanvas\b", r"\bascii\b", r"visuali", r"\bcharts?\b", r"\bgraphs?\b",
    ), False, 'd3 OR "animation library" OR "chart library" OR gsap'),
    Slot("Web前端", "UI 组件与材质", (
        r"component library", r"ui component", r"components for", r"\bwebgpu\b",
        r"liquid glass", r"design system", r"\breact\b", r"\bvue\b", r"\bsvelte\b",
        r"tailwind", r"前端", r"组件",
    ), True, 'shadcn OR radix OR "component library" OR "design system"'),
    Slot("Web前端", "浏览器与插件", (
        r"browser extension", r"webextension", r"userscript", r"tampermonkey",
        r"chrome extension", r"油猴", r"扩展程序", r"浏览器插件", r"插件",
    ), False, '"browser extension" OR webextension OR tampermonkey OR "userscript"'),
    Slot("Web前端", "表格与表单", (), True,
         '"data grid" OR "form builder" OR "table library" OR "form validation"'),

    # ------------------------ 数据基础设施 ------------------------
    Slot("数据基础设施", "数据库与数据分析", (
        r"\bdatabase\b", r"duckdb", r"sqlite", r"sql\b", r"postgres",
        r"data (engine|pipeline|workspace)", r"etl", r"olap", r"ontology.*data",
    ), True, 'duckdb OR clickhouse OR "analytics engine" OR "olap"'),
    Slot("数据基础设施", "网络代理与穿透", (
        r"proxy", r"tunnel", r"\bcdn\b", r"cloudflare", r"relay", r"代理", r"网关", r"穿透",
    ), True, 'frp OR tailscale OR "reverse proxy" OR clash'),
    Slot("数据基础设施", "NAS 与媒体管理", (
        r"\bnas\b", r"strm", r"media (server|library|management)", r"影视",
        r"jellyfin", r"emby",
    ), False, 'jellyfin OR immich OR "media server" OR "self-hosted media"'),
    Slot("数据基础设施", "容器与部署", (
        r"kubernetes", r"\bk8s\b", r"docker", r"deployment", r"terraform",
        r"\bci/?cd\b", r"容器", r"部署",
    ), False, 'coolify OR "docker compose" OR kubernetes OR "deployment platform"'),
    Slot("数据基础设施", "通知与消息", (
        r"telegram", r"slack", r"notif", r"webhook", r"message", r"推送",
    ), False, 'gotify OR apprise OR n8n OR "notification service"'),
    Slot("数据基础设施", "测试与质量", (
        r"\btest\b", r"testing", r"benchmark", r"\bqa\b", r"linter", r"测试",
    ), False, 'pytest OR vitest OR "e2e testing" OR "test framework"'),
    Slot("数据基础设施", "认证与权限", (
        r"auth", r"\bsso\b", r"\boauth\b", r"permission", r"rbac", r"鉴权", r"授权",
    ), False, 'casbin OR keycloak OR oauth2 OR "authorization library"'),
    Slot("数据基础设施", "定时任务与调度", (), True,
         'cron OR airflow OR "task scheduler" OR "job queue"'),
    Slot("数据基础设施", "日志与监控", (), True,
         'prometheus OR grafana OR loki OR "log aggregation"'),
    Slot("数据基础设施", "对象存储与文件同步", (), True,
         'syncthing OR rclone OR minio OR "file sync"'),

    # ---------------------------- 安全逆向 ----------------------------
    Slot("安全逆向", "逆向工程与调试", (
        r"reverse engineer", r"decompil", r"\bapk\b", r"disassembl", r"逆向",
        r"破解", r"forensic",
    ), True, 'ghidra OR frida OR "reverse engineering" OR decompiler'),
    Slot("安全逆向", "渗透与漏洞", (
        r"pentest", r"exploit", r"vulnerab", r"\bcve\b", r"jailbreak",
        r"hardening", r"渗透", r"漏洞",
    ), False, 'nuclei OR metasploit OR "penetration testing" OR "security scanner"'),
    Slot("安全逆向", "移动端与设备定制", (
        r"\bios\b", r"android", r"carplay", r"head unit", r"root", r"adb",
        r"mfi", r"mobile",
    ), False, 'magisk OR "custom rom" OR "android rooting" OR carplay'),

    # ---------------------------- 游戏硬件 ----------------------------
    Slot("游戏硬件", "游戏移植与 Mod", (
        r"\bgame\b", r"gta", r"bloodborne", r"\bps[45]\b", r"emulator",
        r"\bmod\b", r"minecraft", r"quest",
    ), False, '"source port" OR "game mod" OR ryujinx OR "game engine reimplementation"'),
    Slot("游戏硬件", "机器人与嵌入式", (
        r"\brobot", r"firmware", r"embedded", r"\bgadget\b", r"\bmcu\b",
        r"\bdriver\b", r"硬件",
    ), False, 'ros2 OR esphome OR "robot framework" OR firmware'),
    Slot("游戏硬件", "串口与设备通信", (), True,
         '"serial port" OR esp32 OR "embedded rust" OR "device communication"'),

    # ---------------------------- 学习资源 ----------------------------
    Slot("学习资源", "教程与清单", (
        r"awesome", r"roadmap", r"tutorial", r"learning", r"course",
        r"interview", r"cheat ?sheet", r"handbook", r"guide", r"curated",
        r"教程", r"学习", r"指南", r"面试", r"清单",
    ), True, 'awesome OR roadmap OR "interview questions" OR handbook'),
)

# ---------------------------------------------------------------------------
# 人工校准层 —— 「同位置择优替换」的落点，也是自动化出错时的兜底。
# ---------------------------------------------------------------------------
#: 直接指定某能力位的首选（人工判断优先于算法）
SLOT_PIN: dict[str, str] = {}

#: 剔除已知的错误命中，并记录原因（会写进能力位笔记，便于日后复查）
SLOT_EXCLUDE: dict[str, dict[str, str]] = {
    "磁盘与文件管理": {
        "apache/ranger": "Hadoop 权限管理项目，与终端文件管理器 ranger 同名撞车",
    },
    "Office 文档生成与解析": {
        "storytold/pdfcraft": "Acrobat 的 Rust 重写，属于 PDF 而非通用 Office 套件",
    },
}


def all_slots() -> tuple[Slot, ...]:
    """全部能力位（含标准能力位占位）。"""
    return SLOTS


def slot_by_name(name: str) -> Slot | None:
    for slot in SLOTS:
        if slot.name == name:
            return slot
    return None


def _compiled(slot: Slot) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in slot.patterns]


_COMPILED: dict[str, list[re.Pattern[str]]] = {
    s.name: _compiled(s) for s in SLOTS if s.patterns
}


def assign_slot(repo: Repo) -> Slot:
    """按关键词规则把仓库归位。先匹配先归位。"""
    text = repo.search_text()
    for slot in SLOTS:
        for pattern in _COMPILED.get(slot.name, ()):
            if pattern.search(text):
                return slot
    return UNASSIGNED


#: 未能归位的仓库
UNASSIGNED = Slot("待归位", "待归位")
