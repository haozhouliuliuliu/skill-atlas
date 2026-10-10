"""快照与差分 —— 「同位置择优替换」的检测机制。

为什么需要它
------------
抓取、打分、渲染都做完之后，工作流仍然缺一环。用户的诉求是：

    通过每日检索，看会不会发现更好的，然后就能把相同定位的替换掉。

工具原本能生成某一个时刻的库，却**没有任何机制告诉你"某个能力位出现了更好的候选"**。
没有差分，"每日检索"就只能靠人肉翻 54 个笔记 —— 那等于没有。

设计取舍
--------
* 快照只存**必要的比较信息**（排序分、质量分、相关性），不存完整仓库元数据。
  完整数据留在 raw 里，快照是用来做 diff 的，不是第二份真相。
* 差分把「首位变更」与「列表增删」分开报告。前者是可执行的替换信号；
  后者大多是噪声（一个能力位下有几十个候选，边界抖动很正常）。
* 首位变更还要看**方向**：新首选排序分更高才算 "upgrade"，
  否则只是 churn，甚至是退化。
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from dataclasses import asdict, dataclass, field

from .index import Atlas

SNAPSHOT_VERSION = 1


@dataclass
class Entry:
    """快照里的一个候选。"""

    full_name: str
    rank_score: int
    quality: int
    relevance: str

    @classmethod
    def from_candidate(cls, candidate, slot_name: str) -> "Entry":
        return cls(
            full_name=candidate.full_name,
            rank_score=candidate.rank_score(slot_name),
            quality=candidate.score,
            relevance=candidate.relevance_why(slot_name),
        )


@dataclass
class Snapshot:
    """某个时刻的能力位排名。"""

    generated_at: str
    per_slot: int
    slots: dict[str, list[Entry]] = field(default_factory=dict)
    total_candidates: int = 0
    junk: int = 0
    version: int = SNAPSHOT_VERSION

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "generated_at": self.generated_at,
            "per_slot": self.per_slot,
            "total_candidates": self.total_candidates,
            "junk": self.junk,
            "slots": {
                name: [asdict(entry) for entry in entries]
                for name, entries in self.slots.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Snapshot":
        return cls(
            generated_at=payload.get("generated_at", ""),
            per_slot=payload.get("per_slot", 0),
            total_candidates=payload.get("total_candidates", 0),
            junk=payload.get("junk", 0),
            version=payload.get("version", 0),
            slots={
                name: [Entry(**entry) for entry in entries]
                for name, entries in payload.get("slots", {}).items()
            },
        )


def take(atlas: Atlas, *, per_slot: int = 10, generated_at: str | None = None) -> Snapshot:
    """从索引里取一份快照。"""
    slots: dict[str, list[Entry]] = {}
    for slot_name, recs in atlas.by_slot.items():
        if not recs:
            continue
        slots[slot_name] = [
            Entry.from_candidate(candidate, slot_name) for candidate in recs[:per_slot]
        ]
    return Snapshot(
        generated_at=generated_at or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        per_slot=per_slot,
        slots=slots,
        total_candidates=len(atlas.candidates),
        junk=len(atlas.junk),
    )


def save(path: pathlib.Path | str, snapshot: Snapshot) -> pathlib.Path:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return path


def load(path: pathlib.Path | str) -> Snapshot:
    return Snapshot.from_dict(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# 差分
# ---------------------------------------------------------------------------
@dataclass
class SlotDelta:
    """一个能力位在两份快照之间的变化。"""

    slot: str
    old_top: Entry | None = None
    new_top: Entry | None = None
    entered: list[Entry] = field(default_factory=list)
    dropped: list[Entry] = field(default_factory=list)

    @property
    def top_changed(self) -> bool:
        old = self.old_top.full_name if self.old_top else None
        new = self.new_top.full_name if self.new_top else None
        return old != new

    @property
    def direction(self) -> str:
        """首位变更的性质。

        * ``upgrade``   新首选的排序分更高 —— 这才是"发现了更好的"
        * ``downgrade`` 新首选更弱 —— 值得警惕（可能是原首选被剔除或仓库消失）
        * ``churn``     分数持平，只是换了个人
        * ``filled``    原本空缺，现在有候选了
        * ``emptied``   原本有候选，现在空了
        * ````          没有变更

        ``filled`` 刻意不归入 ``upgrade``：空缺被填上是**另一类事件**
        （"这个位置原来没有轮子，现在有了"），混进升级报告会让人以为
        是同一个候选被换掉了。
        """
        if not self.top_changed:
            return ""
        if self.old_top is None:
            return "filled"
        if self.new_top is None:
            return "emptied"
        if self.new_top.rank_score > self.old_top.rank_score:
            return "upgrade"
        if self.new_top.rank_score < self.old_top.rank_score:
            return "downgrade"
        return "churn"

    @property
    def score_delta(self) -> int:
        old = self.old_top.rank_score if self.old_top else 0
        new = self.new_top.rank_score if self.new_top else 0
        return new - old

    @property
    def is_actionable(self) -> bool:
        """值得动作的变化：换上了更强的候选，或者填上了一个空缺。"""
        return self.direction in ("upgrade", "filled")


@dataclass
class DiffReport:
    old_at: str
    new_at: str
    deltas: list[SlotDelta] = field(default_factory=list)

    @property
    def top_changes(self) -> list[SlotDelta]:
        return [d for d in self.deltas if d.top_changed]

    @property
    def upgrades(self) -> list[SlotDelta]:
        return [d for d in self.deltas if d.direction == "upgrade"]

    @property
    def downgrades(self) -> list[SlotDelta]:
        return [d for d in self.deltas if d.direction == "downgrade"]

    @property
    def gaps_opened(self) -> list[str]:
        return [d.slot for d in self.deltas if d.direction == "emptied"]

    @property
    def gaps_closed(self) -> list[str]:
        return [d.slot for d in self.deltas if d.direction == "filled"]

    @property
    def slots_with_new_entries(self) -> list[SlotDelta]:
        return [d for d in self.deltas if d.entered]

    @property
    def is_empty(self) -> bool:
        return not any(d.top_changed or d.entered or d.dropped for d in self.deltas)


def diff(old: Snapshot, new: Snapshot) -> DiffReport:
    """比较两份快照。"""
    report = DiffReport(old_at=old.generated_at, new_at=new.generated_at)
    for slot in dict.fromkeys([*old.slots, *new.slots]):
        old_entries = old.slots.get(slot, [])
        new_entries = new.slots.get(slot, [])
        old_names = {e.full_name for e in old_entries}
        new_names = {e.full_name for e in new_entries}
        delta = SlotDelta(
            slot=slot,
            old_top=old_entries[0] if old_entries else None,
            new_top=new_entries[0] if new_entries else None,
            entered=[e for e in new_entries if e.full_name not in old_names],
            dropped=[e for e in old_entries if e.full_name not in new_names],
        )
        if delta.top_changed or delta.entered or delta.dropped:
            report.deltas.append(delta)
    report.deltas.sort(
        key=lambda d: (
            not d.is_actionable,
            not d.top_changed,
            -abs(d.score_delta),
            d.slot,
        )
    )
    return report


# ---------------------------------------------------------------------------
# 基线的存放约定
# ---------------------------------------------------------------------------
def snapshot_path(data_dir: pathlib.Path | str) -> pathlib.Path:
    return pathlib.Path(data_dir) / "build" / "snapshot.json"


def history_dir(data_dir: pathlib.Path | str) -> pathlib.Path:
    return pathlib.Path(data_dir) / "build" / "snapshot-history"


def archive(data_dir: pathlib.Path | str, snapshot: Snapshot) -> pathlib.Path:
    """把快照存成当前状态，并按日期留一份历史。"""
    current = save(snapshot_path(data_dir), snapshot)
    stamp = (snapshot.generated_at or "unknown")[:10]
    save(history_dir(data_dir) / f"{stamp}.json", snapshot)
    return current


def find_baseline(data_dir: pathlib.Path | str, *, before: str) -> pathlib.Path | None:
    """找出 ``before`` 之前最近的一份历史快照。"""
    directory = history_dir(data_dir)
    if not directory.exists():
        return None
    candidates = sorted(
        (p for p in directory.glob("*.json") if p.stem < before), reverse=True
    )
    return candidates[0] if candidates else None
