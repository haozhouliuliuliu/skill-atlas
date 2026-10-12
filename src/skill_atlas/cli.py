"""命令行入口。

    skill-atlas fetch     抓新建榜（日/周/月）
    skill-atlas enrich    按能力位定向检索成熟项目
    skill-atlas build     生成 Obsidian 库
    skill-atlas query     反查「我要做 X」该用哪些能力位
    skill-atlas inspect   给单个仓库做质量体检
    skill-atlas slots     列出全部能力位

能力位的名称与检索式由使用者自行维护，因此可能是任意语言 —— 本工具不翻译它们。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from . import __version__, store
from .api import GitHubError, SearchClient, resolve_token
from .console import ensure_safe_output
from .index import WINDOW_ORDER, Atlas, RankingResult, build_atlas
from .models import Repo
from .quality import low_value_reason
from .query import query_atlas
from .scoring import quality_score, relevance
from .slots import SLOT_EXCLUDE, SLOT_PIN, all_slots, slot_by_name
from .snapshot import archive, diff, find_baseline, load, snapshot_path, take
from .vault import render_vault, slot_index


def _load_atlas(data_dir: pathlib.Path) -> Atlas:
    rankings = store.load_rankings(data_dir)
    enrichment = store.load_enrichment(data_dir)
    if not rankings and not enrichment:
        raise SystemExit(
            f"no data under {data_dir}/raw — run `skill-atlas fetch` and "
            "`skill-atlas enrich` first"
        )
    return build_atlas(rankings, enrichment)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_fetch(args) -> int:
    client = SearchClient(token=resolve_token())
    print(f"auth: {'token' if client.token else 'anonymous'}   pace: {client.pace}s")
    for window in args.window:
        if window not in WINDOW_ORDER:
            print(f"  unknown window: {window}")
            continue
        days = {"day": 1, "week": 7, "month": 30}[window]
        try:
            repos, meta = client.created_ranking(days, per_page=args.per_page)
        except GitHubError as exc:
            print(f"  {window}: FAILED {exc}")
            continue
        result = RankingResult(
            window=window,
            repos=repos,
            since=meta["since"],
            total_count=meta["total_count"],
        )
        path = store.save_ranking(args.data, result)
        junk = sum(1 for repo in repos if low_value_reason(repo))
        rate = round(100 * junk / len(repos)) if repos else 0
        print(
            f"  {window:<5} fetched={len(repos):>3}  low-value={junk:>3} ({rate:>3}%)  "
            f"total={result.total_count:>9}  -> {path.name}"
        )
    return 0


def cmd_enrich(args) -> int:
    client = SearchClient(token=resolve_token())
    existing = store.load_enrichment(args.data)
    print(f"auth: {'token' if client.token else 'anonymous'}   pace: {client.pace}s")
    print(f"resume: {len(existing)}/{len(all_slots())} slots already cached")

    targets = all_slots()
    if args.only:
        wanted = set(args.only)
        targets = tuple(s for s in targets if s.name in wanted)
        missing = wanted - {s.name for s in targets}
        if missing:
            print(f"  unknown slot(s): {', '.join(sorted(missing))}")

    done = 0
    for slot in targets:
        if slot.name in existing and not args.force:
            continue
        try:
            repos = client.slot_candidates(slot, min_stars=args.min_stars,
                                           per_page=args.per_page)
        except GitHubError as exc:
            print(f"  {slot.name:<26} FAILED {exc}")
            continue
        kept = [r for r in repos if not low_value_reason(r)]
        existing[slot.name] = kept
        store.save_enrichment(args.data, existing)  # incremental
        done += 1
        print(f"  {slot.name:<26} raw={len(repos):>3} kept={len(kept):>3}")
    print(f"done. saved {done} slot(s); {len(existing)} total cached")
    return 0


def cmd_build(args) -> int:
    atlas = _load_atlas(args.data)
    stats = render_vault(atlas, args.vault, per_slot=args.per_slot)
    store.save_slot_index(args.data, slot_index(atlas))
    # build 会推进基线：这次的排名成为下次 diff 的比较对象。
    snap = take(atlas, per_slot=args.per_slot)
    archived = archive(args.data, snap)
    print(f"vault -> {args.vault}")
    for key in ("candidates", "junk", "slots", "repos", "logs", "gaps"):
        print(f"  {key:<11} {stats[key]}")
    print(f"  snapshot    {archived}  (下次 diff 的比较基线)")
    return 0


def cmd_update(args) -> int:
    """每日循环：抓取 → 补全 → 报告变化。

    刻意**不**默认建库：`diff` 要在基线还是上一次的状态时才有意义。
    先看变化、确认之后再 `build`，这是「先看后动」的落点。
    加 ``--build`` 可以一步到底。
    """
    print("=" * 74)
    print("1/3  fetch    抓新建榜（日/周/月）")
    print("=" * 74)
    if cmd_fetch(argparse.Namespace(data=args.data, window=list(WINDOW_ORDER),
                                    per_page=args.per_page)) != 0:
        return 1

    print("\n" + "=" * 74)
    print("2/3  enrich   按能力位检索成熟项目（可断点续跑）")
    print("=" * 74)
    if cmd_enrich(argparse.Namespace(data=args.data, only=None,
                                     min_stars=args.min_stars,
                                     per_page=args.per_page, force=False)) != 0:
        return 1

    print("\n" + "=" * 74)
    print("3/3  diff     与上次基线比较")
    print("=" * 74)
    cmd_diff(argparse.Namespace(data=args.data, baseline=None,
                                per_slot=args.per_slot, json=False, quiet=False))

    if args.build:
        print("\n" + "=" * 74)
        print("build         渲染库并推进基线")
        print("=" * 74)
        cmd_build(argparse.Namespace(data=args.data, vault=args.vault,
                                     per_slot=args.per_slot))
    else:
        print("\n确认变化后运行 `skill-atlas build` 渲染库并推进基线。")
    return 0


def cmd_diff(args) -> int:
    atlas = _load_atlas(args.data)
    current = take(atlas, per_slot=args.per_slot)

    baseline_path = args.baseline or snapshot_path(args.data)
    if not pathlib.Path(baseline_path).exists():
        print(f"没有基线快照：{baseline_path}")
        print("先运行 `skill-atlas build` 建立基线，之后再抓取并用 diff 查看变化。")
        return 0

    baseline = load(baseline_path)
    report = diff(baseline, current)

    if args.json:
        import json as _json

        payload = {
            "baseline": {"path": str(baseline_path), "generated_at": baseline.generated_at},
            "current": {"generated_at": current.generated_at},
            "top_changes": [
                {
                    "slot": d.slot,
                    "direction": d.direction,
                    "score_delta": d.score_delta,
                    "old": d.old_top.full_name if d.old_top else None,
                    "new": d.new_top.full_name if d.new_top else None,
                }
                for d in report.top_changes
            ],
            "entered": {d.slot: [e.full_name for e in d.entered] for d in report.deltas if d.entered},
            "dropped": {d.slot: [e.full_name for e in d.dropped] for d in report.deltas if d.dropped},
            "gaps_opened": report.gaps_opened,
            "gaps_closed": report.gaps_closed,
        }
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"基线 {baseline.generated_at}  ->  当前 {current.generated_at}")
    print("=" * 74)
    if report.is_empty:
        print("没有任何变化。")
        return 0

    if report.upgrades:
        print(f"\n🔼 出现更好的首选（{len(report.upgrades)} 个）—— 这是值得替换的信号")
        for d in report.upgrades:
            print(f"  [{d.slot}]  +{d.score_delta} 分")
            print(f"      换下  {d.old_top.full_name if d.old_top else '—'} ")
            print(f"      换上  {d.new_top.full_name if d.new_top else '—'} "
                  f"(排序分 {d.new_top.rank_score if d.new_top else 0})")

    churn = [d for d in report.top_changes if d.direction == "churn"]
    if churn:
        print(f"\n↔️  首位变更但分数持平（{len(churn)} 个）—— 多为噪声")
        for d in churn:
            print(f"  [{d.slot}] {d.old_top.full_name} -> {d.new_top.full_name}")

    if report.downgrades:
        print(f"\n🔽 首位变弱（{len(report.downgrades)} 个）—— 值得确认原因")
        for d in report.downgrades:
            print(f"  [{d.slot}]  {d.score_delta} 分")
            print(f"      原  {d.old_top.full_name if d.old_top else '—'}")
            print(f"      现  {d.new_top.full_name if d.new_top else '—（空缺）'}")

    if report.gaps_closed:
        print(f"\n✅ 新填上的空缺（{len(report.gaps_closed)} 个）: {', '.join(report.gaps_closed)}")
    if report.gaps_opened:
        print(f"\n⚠️ 新出现的空缺（{len(report.gaps_opened)} 个）: {', '.join(report.gaps_opened)}")

    entered = [d for d in report.deltas if d.entered]
    if entered and not args.quiet:
        print(f"\n进入候选列表的新项目（前 10 个能力位）")
        for d in entered[:10]:
            names = ", ".join(e.full_name for e in d.entered[:4])
            more = f" 等 {len(d.entered)} 个" if len(d.entered) > 4 else ""
            print(f"  [{d.slot}] {names}{more}")

    dropped = [d for d in report.deltas if d.dropped]
    if dropped and not args.quiet:
        print(f"\n掉出候选列表（前 10 个能力位）")
        for d in dropped[:10]:
            names = ", ".join(e.full_name for e in d.dropped[:4])
            more = f" 等 {len(d.dropped)} 个" if len(d.dropped) > 4 else ""
            print(f"  [{d.slot}] {names}{more}")

    print(f"\n共 {len(report.deltas)} 个能力位有变化。"
          f"确认无误后运行 `skill-atlas build` 推进基线。")
    return 0


def cmd_query(args) -> int:
    atlas = _load_atlas(args.data)
    matches = query_atlas(atlas, args.text, top=args.top)
    print(f"需求：{args.text}")
    print("=" * 74)
    if not matches:
        print("没有匹配到任何能力位。建议换更具体的词，或先看 01-能力位总表.md。")
        return 0
    for rank, match in enumerate(matches, 1):
        star = "，核心" if match.slot.core else ""
        print(f"\n[{rank}] {match.slot.name}　（领域：{match.slot.domain}{star}）")
        print(f"    匹配度 {match.score}　命中词：{match.hit_summary()}")
        print(f"    候选 {len(match.candidates)} 个")
        if not match.candidates:
            print("    ⚠️ 无现成候选（机会区）")
            continue
        for i, name in enumerate(match.candidates[: args.per_slot]):
            candidate = atlas.candidates.get(name)
            if not candidate:
                continue
            mark = "首选" if i == 0 else "    "
            repo = candidate.repo
            print(
                f"      {mark} [{candidate.score:>3}分] {name:<44} "
                f"★{repo.stars} fork{repo.forks} {(repo.description or '')[:56]}"
            )
    print("\n说明：匹配基于关键词，仅供参考；最终取舍看候选表里的可验证指标。")
    return 0


def cmd_inspect(args) -> int:
    client = SearchClient(token=resolve_token())
    try:
        repo = client.get_repo(args.repo)
    except GitHubError as exc:
        print(f"FAILED: {exc}")
        return 1
    reason = low_value_reason(repo)
    print(f"# {repo.full_name}")
    print(f"  stars={repo.stars} forks={repo.forks} issues={repo.open_issues} "
          f"size={repo.size_kb}KB lang={repo.language} license={repo.license}")
    print(f"  created={repo.created_date()} pushed={repo.pushed_date()} "
          f"archived={repo.archived}  days_since_push={repo.days_since_push()}")
    print(f"  quality_score = {quality_score(repo)} / 100")
    print(f"  verdict: {'LOW VALUE — ' + reason if reason else 'OK'}")
    for slot in all_slots():
        if not slot.query:
            continue
        level, why = relevance(repo, slot.query)
        if level >= 2:
            print(f"  relevant to [{slot.name}] via {why}")
    return 0


def cmd_slots(args) -> int:
    slots = all_slots()
    print(f"{len(slots)} capability slots")
    for slot in slots:
        kind = "staple" if slot.is_staple else "rule  "
        core = "core" if slot.core else "    "
        print(f"  [{kind}] [{core}] {slot.domain:<8} {slot.name}")
    if SLOT_PIN:
        print("\nmanual pins:")
        for name, repo in SLOT_PIN.items():
            print(f"  {name} -> {repo}")
    if SLOT_EXCLUDE:
        print("\nmanual exclusions:")
        for name, entries in SLOT_EXCLUDE.items():
            for repo, why in entries.items():
                print(f"  {name}: {repo} ({why})")
    return 0


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-atlas",
        description="Turn GitHub search results into a replaceable capability-slot index.",
    )
    parser.add_argument("--version", action="version", version=f"skill-atlas {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="fetch the new-repo rankings")
    p_fetch.add_argument("--data", type=pathlib.Path, default=store.DEFAULT_DATA_DIR)
    p_fetch.add_argument("--window", nargs="+", default=list(WINDOW_ORDER))
    p_fetch.add_argument("--per-page", type=int, default=100)
    p_fetch.set_defaults(func=cmd_fetch)

    p_enrich = sub.add_parser("enrich", help="run the per-slot queries")
    p_enrich.add_argument("--data", type=pathlib.Path, default=store.DEFAULT_DATA_DIR)
    p_enrich.add_argument("--only", nargs="+", default=None)
    p_enrich.add_argument("--min-stars", type=int, default=200)
    p_enrich.add_argument("--per-page", type=int, default=100)
    p_enrich.add_argument("--force", action="store_true")
    p_enrich.set_defaults(func=cmd_enrich)

    p_build = sub.add_parser("build", help="render the Obsidian vault")
    p_build.add_argument("--data", type=pathlib.Path, default=store.DEFAULT_DATA_DIR)
    p_build.add_argument("--vault", type=pathlib.Path, default=pathlib.Path("vault"))
    p_build.add_argument("--per-slot", type=int, default=10)
    p_build.set_defaults(func=cmd_build)

    p_query = sub.add_parser("query", help="find slots for a project idea")
    p_query.add_argument("text")
    p_query.add_argument("--data", type=pathlib.Path, default=store.DEFAULT_DATA_DIR)
    p_query.add_argument("--top", type=int, default=4)
    p_query.add_argument("--per-slot", type=int, default=3)
    p_query.set_defaults(func=cmd_query)

    p_diff = sub.add_parser(
        "diff",
        help="compare the current ranking against the last built snapshot",
        description=(
            "按能力位比较「当前抓取结果」与「上次 build 时的快照」，"
            "突出显示出现了更好首选的能力位。diff 不会推进基线 —— "
            "确认变化后运行 build 才会。"
        ),
    )
    p_diff.add_argument("--data", type=pathlib.Path, default=store.DEFAULT_DATA_DIR)
    p_diff.add_argument("--baseline", type=pathlib.Path, default=None,
                        help="指定比较基线（默认 data/build/snapshot.json）")
    p_diff.add_argument("--per-slot", type=int, default=10)
    p_diff.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_diff.add_argument("--quiet", action="store_true", help="只报告首位变更与空缺")
    p_diff.set_defaults(func=cmd_diff)

    p_update = sub.add_parser(
        "update",
        help="the daily loop: fetch + enrich + diff",
        description=(
            "每日循环：抓取新建榜 → 按能力位补全成熟项目 → 与上次基线比较差异。"
            "默认不建库，因为 diff 需要基线停留在上一次；加 --build 可一步到底。"
        ),
    )
    p_update.add_argument("--data", type=pathlib.Path, default=store.DEFAULT_DATA_DIR)
    p_update.add_argument("--vault", type=pathlib.Path, default=pathlib.Path("vault"))
    p_update.add_argument("--per-page", type=int, default=100)
    p_update.add_argument("--min-stars", type=int, default=200)
    p_update.add_argument("--per-slot", type=int, default=10)
    p_update.add_argument("--build", action="store_true",
                          help="diff 之后立刻建库并推进基线")
    p_update.set_defaults(func=cmd_update)

    p_inspect = sub.add_parser("inspect", help="quality-check one repository")
    p_inspect.add_argument("repo", help="owner/name")
    p_inspect.set_defaults(func=cmd_inspect)

    p_slots = sub.add_parser("slots", help="list all capability slots")
    p_slots.set_defaults(func=cmd_slots)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_safe_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
