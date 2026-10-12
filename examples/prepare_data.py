#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把示例数据写成一个可用的 data 目录，让 CLI 也能完全离线跑通。

    python examples/prepare_data.py --out data
    PYTHONPATH=src python -m skill_atlas.cli build --data data --vault vault
    PYTHONPATH=src python -m skill_atlas.cli query "我要加日志监控" --data data

这样演示就不必依赖网络与 GitHub 凭证。
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from skill_atlas import store  # noqa: E402
from skill_atlas.console import ensure_safe_output  # noqa: E402

from examples import sample_data  # noqa: E402


def main() -> int:
    ensure_safe_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data"))
    parser.add_argument("--force", action="store_true",
                        help="覆盖已存在的目录")
    args = parser.parse_args()

    if args.out.exists():
        if not args.force:
            print(f"{args.out} 已存在。加 --force 覆盖，或换一个 --out。")
            return 1
        shutil.rmtree(args.out)

    store.save_enrichment(args.out, sample_data.enrichment())
    for _window, result in sample_data.rankings().items():
        store.save_ranking(args.out, result)

    written = sorted(p.relative_to(args.out).as_posix()
                     for p in args.out.rglob("*.json"))
    print(f"示例数据已写入 {args.out}/raw/")
    for name in written:
        print(f"  {name}")
    print("\n接着可以：")
    print(f"  PYTHONPATH=src python -m skill_atlas.cli build --data {args.out} "
          f"--vault vault")
    print(f'  PYTHONPATH=src python -m skill_atlas.cli query "我要加日志监控" '
          f"--data {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
