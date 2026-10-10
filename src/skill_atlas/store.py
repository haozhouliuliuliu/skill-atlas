"""原始抓取结果的落盘与读取。

落盘格式刻意保持朴素 JSON，方便人工检查与 diff —— 这个项目的数据是论点的一部分，
不应该藏在数据库里。
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

from .index import WINDOW_ORDER, RankingResult
from .models import Repo

DEFAULT_DATA_DIR = pathlib.Path("data")


def raw_dir(data_dir: pathlib.Path | str) -> pathlib.Path:
    path = pathlib.Path(data_dir) / "raw"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: pathlib.Path, payload: dict) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return path


def save_ranking(data_dir: pathlib.Path | str, result: RankingResult) -> pathlib.Path:
    payload = {
        "window": result.window,
        "since": result.since,
        "total_count": result.total_count,
        "fetched_at": result.fetched_at or dt.datetime.now().isoformat(),
        "repos": [repo.to_dict() for repo in result.repos],
    }
    return _write_json(raw_dir(data_dir) / f"{result.window}.json", payload)


def load_ranking(data_dir: pathlib.Path | str, window: str) -> RankingResult | None:
    path = raw_dir(data_dir) / f"{window}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RankingResult(
        window=payload.get("window", window),
        since=payload.get("since", ""),
        total_count=payload.get("total_count", 0),
        fetched_at=payload.get("fetched_at", ""),
        repos=[Repo.from_dict(item) for item in payload.get("repos", [])],
    )


def load_rankings(data_dir: pathlib.Path | str) -> dict[str, RankingResult]:
    out: dict[str, RankingResult] = {}
    for window in WINDOW_ORDER:
        result = load_ranking(data_dir, window)
        if result and result.repos:
            out[window] = result
    return out


def save_enrichment(
    data_dir: pathlib.Path | str, slots: dict[str, list[Repo]]
) -> pathlib.Path:
    payload = {
        "fetched_at": dt.datetime.now().isoformat(),
        "slots": {
            name: [repo.to_dict() for repo in repos] for name, repos in slots.items()
        },
    }
    return _write_json(raw_dir(data_dir) / "enriched.json", payload)


def load_enrichment(data_dir: pathlib.Path | str) -> dict[str, list[Repo]]:
    path = raw_dir(data_dir) / "enriched.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: [Repo.from_dict(item) for item in repos]
        for name, repos in payload.get("slots", {}).items()
    }


def save_slot_index(data_dir: pathlib.Path | str, index: dict[str, list[str]]) -> pathlib.Path:
    """导出机器可读的能力位排名（排序的唯一真相）。"""
    return _write_json(pathlib.Path(data_dir) / "build" / "slot_index.json", index)
