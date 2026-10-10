"""按项目需求检索适配的能力位。

匹配方式
--------
1. 中文按 **2-gram** 切分 —— 对中文无需同义词表也能工作，
   例如「日志监控」会切出 {日志, 志监, 监控}，与「日志与监控」高度重合。
2. 英文按 token 切分。
3. 叠加人工同义词表，覆盖命名较"黑话"的能力位
   （比如「系统1决策模型」这种名字，用户不会这么说话）。

之所以不用向量检索：这里要的是**可解释**。用户能看到"命中了『日志』『监控』"
比拿到一个 0.83 的相似度更有用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .index import Atlas
from .slots import Slot, all_slots

#: 命名较黑话的能力位，补一层用户可能说的白话
SYNONYMS: dict[str, str] = {
    "Agent 编排与 Harness": "智能体框架 多智能体 工作流编排 让ai自己干活 agent框架",
    "Agent Skill 规范与范例": "技能封装 提示词库 让ai按规范产出 skill模板",
    "Agent 记忆与检索": "长期记忆 记住上下文 向量记忆",
    "模型接入与聚合": "多模型 模型网关 便宜调模型 api中转",
    "本地推理引擎": "本地跑模型 离线推理 显卡推理",
    "系统1决策模型": "快速判断 分类决策 小模型分流",
    "代码理解与检索": "读懂代码 代码搜索",
    "浏览器自动化与反检测": "自动上网 抓网页 爬虫 模拟点击",
    "Agent 可观测与调试界面": "看ai在干嘛 调试 追踪 可视化监控",
    "内容生产流水线": "自动出内容 批量做视频 图文流水线",
    "语音识别与合成": "语音转文字 文字转语音 配音 声音克隆",
    "文档解析与 RAG 切分": "解析pdf 切分文档 喂给模型 知识库问答",
    "Agent 评测与回归": "评测 效果测试 回归 打分",
    "Office 文档生成与解析": (
        "word excel ppt office pdf 办公文档 文档整理 整理文档 读写文档 解析文档 "
        "生成报告 生成表格 文件整理 文档转换 批量处理文档 docx xlsx pptx"
    ),
    "排版与出版": "排版 公式 latex 出版 论文 书籍",
    "财务与票据": "记账 发票 账单 理财 报销 对账",
    "邮件与日历": "收发邮件 日程 日历 邮箱",
    "PDF 深度处理": "pdf 解析pdf 拆分合并 提取文字 表格提取 扫描件 pdf转换 合并pdf",
    "知识库与本体": "知识图谱 本体 第二大脑 个人知识库",
    "笔记与编辑器": "obsidian 笔记软件 双链",
    "任务与项目管理": "待办 看板 项目管理",
    "双向链接与图谱分析": "知识图谱可视化 双向链接分析",
    "桌面全文检索": "本地搜索 快速找文件 everything",
    "磁盘与文件管理": "文件管理器 磁盘占用 清理空间",
    "系统清理与优化": "清理垃圾 精简系统 提速",
    "截图与录屏": "截图 录屏 屏幕录制",
    "文件格式转换": "格式转换 转码 批量转换",
    "本地音乐与媒体库": "音乐播放 媒体库",
    "剪贴板与快捷启动": "剪贴板 快速启动器",
    "图像编辑": "修图 图片处理 ps替代",
    "矢量与 Logo 设计": "矢量图 画logo svg设计",
    "视频编辑与生成": "剪视频 生成视频 视频剪辑",
    "CAD 与 3D": "建模 三维 cad 3d打印",
    "动画与可视化": "动画 图表 数据可视化",
    "UI 组件与材质": "前端组件 设计系统 ui库",
    "浏览器与插件": "浏览器扩展 油猴脚本 插件",
    "表格与表单": "数据表格 表单 校验",
    "数据库与数据分析": "数据库 数据分析 olap 查询引擎",
    "网络代理与穿透": "内网穿透 代理 组网 出国",
    "NAS 与媒体管理": "nas 家庭影音 自建媒体库",
    "容器与部署": "docker 部署 上线 容器编排",
    "通知与消息": "推送通知 消息提醒 telegram 机器人",
    "测试与质量": "单元测试 端到端测试 测试框架",
    "认证与权限": "登录鉴权 权限 单点登录 oauth",
    "定时任务与调度": "定时任务 计划任务 任务队列 调度",
    "日志与监控": "日志 监控 告警 指标",
    "对象存储与文件同步": "文件同步 对象存储 网盘自建",
    "逆向工程与调试": "逆向 反编译 调试二进制",
    "渗透与漏洞": "渗透测试 漏洞扫描 安全",
    "移动端与设备定制": "刷机 root 车机 安卓定制",
    "游戏移植与 Mod": "游戏移植 mod 模拟器 开源重制",
    "机器人与嵌入式": "机器人 单片机 固件 硬件",
    "串口与设备通信": "串口 单片机通信 设备协议",
    "教程与清单": "教程 学习路线 面试题 清单",
}

#: 这些 2-gram 太泛，会把一切匹配到一切
STOP_GRAMS: frozenset[str] = frozenset({
    "我要", "要做", "做一", "一个", "做个", "帮我", "想要", "需要", "用来", "可以",
    "怎么", "如何", "什么", "哪些", "我的", "系统", "工具", "项目", "功能", "实现",
    "管理", "处理", "支持", "能够", "自动", "应用", "平台",
})


def cjk_grams(text: str) -> set[str]:
    """中文 2-gram（跳过停用词）。"""
    out: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) == 1:
            out.add(run)
            continue
        for i in range(len(run) - 1):
            gram = run[i : i + 2]
            if gram not in STOP_GRAMS:
                out.add(gram)
    return out


def latin_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#.]+", text.lower()) if len(t) > 1}


@dataclass
class Match:
    """一个被匹配到的能力位。"""

    slot: Slot
    score: float
    cjk_hits: list[str]
    latin_hits: list[str]
    candidates: list[str]  # 仓库名，已按排序分排好

    def hit_summary(self) -> str:
        parts = ["、".join(self.cjk_hits)]
        if self.latin_hits:
            parts.append(" ".join(self.latin_hits))
        return " ".join(p for p in parts if p) or "—"


def _slot_keywords(slot: Slot) -> tuple[set[str], set[str]]:
    text = f"{slot.name} {slot.domain} {SYNONYMS.get(slot.name, '')}"
    return cjk_grams(text), latin_tokens(text)


def match_slots(
    text: str,
    *,
    top: int = 4,
    index: dict[str, list[str]] | None = None,
) -> list[Match]:
    """把一段项目描述匹配到能力位。"""
    index = index or {}
    query_cjk = cjk_grams(text)
    query_latin = latin_tokens(text)

    matches: list[Match] = []
    for slot in all_slots():
        key_cjk, key_latin = _slot_keywords(slot)
        cjk_hits = query_cjk & key_cjk
        latin_hits = query_latin & key_latin
        if not cjk_hits and not latin_hits:
            continue
        # 中文与英文等权；命中能力位专有名（长词）再加分
        score = 2.0 * len(cjk_hits) + 2.0 * len(latin_hits)
        score += 1.5 * len(query_cjk & cjk_grams(slot.name))
        if slot.core:
            score += 0.3
        matches.append(
            Match(
                slot=slot,
                score=round(score, 1),
                cjk_hits=sorted(cjk_hits)[:8],
                latin_hits=sorted(latin_hits)[:5],
                candidates=index.get(slot.name, []),
            )
        )

    matches.sort(key=lambda m: (-m.score, m.slot.name))
    return matches[:top]


def query_atlas(atlas: Atlas, text: str, *, top: int = 4) -> list[Match]:
    """基于已构建的索引做匹配。"""
    index = {slot: [c.full_name for c in recs] for slot, recs in atlas.by_slot.items()}
    return match_slots(text, top=top, index=index)
