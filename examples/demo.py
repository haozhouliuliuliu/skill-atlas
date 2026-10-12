#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线演示：不联网、不需要 token，跑完整条流水线并打印结果。

    python examples/demo.py              # 渲染到 examples/out/ 并打印摘要
    python examples/demo.py --keep-out   # 保留上次输出（默认会先清空）

它演示了四件事：
  1. SEO 引流仓库被质量过滤器挡掉
  2. 榜单条目按关键词自动归位到能力位
  3. 成熟项目被相关性判定为「名字命中」并排到前面
  4. 没有候选的能力位被显式报告为空缺，而不是静默消失
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from skill_atlas import build_atlas, query_atlas, render_vault  # noqa: E402
from skill_atlas.console import ensure_safe_output  # noqa: E402
from skill_atlas.quality import low_value_reason  # noqa: E402

from examples import sample_data  # noqa: E402

LINE = "─" * 74


def main() -> int:
    # 输出里有中文；在非 UTF-8 的控制台/管道上必须降级而不是崩掉。
    ensure_safe_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path,
                        default=PROJECT_ROOT / "examples" / "out")
    parser.add_argument("--keep-out", action="store_true",
                        help="不清理上次的输出目录")
    parser.add_argument("--per-slot", type=int, default=5)
    args = parser.parse_args()

    rankings = sample_data.rankings()
    enrichment = sample_data.enrichment()
    atlas = build_atlas(rankings, enrichment)

    print(LINE)
    print("1. 质量过滤：SEO 引流仓库")
    print(LINE)
    if atlas.junk:
        for repo, reason in atlas.junk:
            print(f"  {repo.full_name}")
            print(f"      ★{repo.stars}  fork{repo.forks}  {repo.size_kb}KB  "
                  f"语言={repo.language or '无'}  许可证={repo.license or '无'}")
            print(f"      -> 排除理由: {reason}")
    else:
        print("  （样本里没有垃圾仓库）")
    print(f"  候选池保留 {len(atlas.candidates)} 个仓库\n")

    print(LINE)
    print("2 & 3. 能力位排序（按排序分 = 质量分 + 相关性加成）")
    print(LINE)
    for slot_name in ("本地推理引擎", "浏览器与插件", "磁盘与文件管理", "语音识别与合成"):
        recs = atlas.by_slot.get(slot_name, [])
        print(f"\n  [{slot_name}]  候选 {len(recs)} 个")
        for i, candidate in enumerate(recs[: args.per_slot]):
            mark = "首选" if i == 0 else "    "
            print(f"    {mark} 排序分 {candidate.rank_score(slot_name):>3} "
                  f"(质量 {candidate.score:>3})  相关={candidate.relevance_why(slot_name):<6} "
                  f"{candidate.full_name}")

    print(f"\n  [磁盘与文件管理] 的人工剔除:")
    from skill_atlas import SLOT_EXCLUDE

    for name, why in SLOT_EXCLUDE.get("磁盘与文件管理", {}).items():
        print(f"    ✂ {name} —— {why}")

    print("\n" + LINE)
    print("4. 空缺报告")
    print(LINE)
    stats = list(atlas.slot_stats(atlas.cap(args.per_slot)))
    empty = [slot.name for slot, total, _ in stats if total == 0]
    print(f"  {len(empty)} / {len(stats)} 个能力位没有候选")
    print(f"  其中包含样本里刻意留空的: 笔记与编辑器 = "
          f"{'空缺' if '笔记与编辑器' in empty else '有候选'}")
    print(f"\n  没有检索结果的能力位会被如实标成空缺，而不是静默消失 ——")
    print(f"  空白本身就是信息：那个位置没有现成轮子。")

    print("\n" + LINE)
    print("5. 渲染 Obsidian 库")
    print(LINE)
    out = args.out
    if out.exists() and not args.keep_out:
        shutil.rmtree(out)
    counts = render_vault(atlas, out, per_slot=args.per_slot)
    for key, value in counts.items():
        print(f"  {key:<11} {value}")
    print(f"\n  输出目录: {out}")
    print(f"  用 Obsidian 打开这个目录即可（或直接看 01-能力位总表.md）")

    print("\n" + LINE)
    print("6. 检索入口：从「我要做什么」反查能力位")
    print(LINE)
    for question in ("我想给项目加日志监控和定时任务", "做一个文件管理器"):
        matches = query_atlas(atlas, question, top=2)
        print(f"\n  需求: {question}")
        for rank, match in enumerate(matches, 1):
            print(f"    [{rank}] {match.slot.name}  匹配度 {match.score}  "
                  f"命中词: {match.hit_summary()}")
            if not match.candidates:
                print("          （本样本中该能力位没有候选 —— 机会区）")
                continue
            for name in match.candidates[:2]:
                candidate = atlas.candidates[name]
                print(f"          {candidate.full_name}  (质量 {candidate.score})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
