"""The history: every tick stored whole, a bounded ring in memory and every tick on disk.

Design spec, sections 6, 7 and 9. A `TickRecord` keeps everything a tick produced: the evidence inputs
every channel rendered from (the messages included), the six instance results with their verbatim
evidence and full answers, the pick, the executed action and its primitives, the reward that followed,
what the action changed (damage, kills, death, displacement) and whether it stalled. The store keeps the
last `history_ring` ticks in memory (2,000 by default) and appends every tick to `history.jsonl` in the
log directory, which is copied into bundles.

Because rendering is deterministic, a stored tick re-rendered under an instance's own scope reproduces
the text that instance saw, byte for byte; `rerender` renders a stored tick under any scope, which is
what System 2's history test uses. The test also attaches the screen the instance saw when `frame` is in
the new scope: the store keeps each ring record's frame in memory beside it (`frame`), because the log
folder's `frames/<tick>.jpg` is rewritten by the next episode with the same tick numbers. The relevance
ledger is updated from the records of an episode.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from system1_doom.evidence import EvidenceInputs, Message, RenderedEvidence, render_scope
from system1_doom.instance import InstanceResult
from system1_doom.relevance import RelevanceDecision, SpokenMessage
from system1_doom.system1 import Pick, System1Result
from system1_doom.tracing import OutcomeTrace

HISTORY_FILE = "history.jsonl"


class TickRecord(BaseModel):
    """One tick, whole."""

    model_config = ConfigDict(frozen=True)

    episode_id: str
    tick: int
    configuration_version: int
    exploration_level: str
    active_strategy: str
    inputs: EvidenceInputs = Field(description="What every channel rendered from at this tick, the messages included")
    instances: Dict[str, InstanceResult] = Field(description="The five senses in sense order, then the central")
    messages: Tuple[Message, ...] = ()
    pick: Pick
    executed_action: Optional[str] = Field(default=None, description="None when the central missed and the tick idled")
    primitives: Tuple[str, ...] = ()
    reward: float = 0.0
    done: bool = False
    outcome: Optional[OutcomeTrace] = Field(default=None, description="What the action (or the idle) changed; None in older records")
    stalled: bool = Field(default=False, description="The action tried to move and moved less than the stall bound")

    @property
    def context(self) -> str:
        return self.inputs.context

    @property
    def key(self) -> str:
        """`<episode id>:<tick>`, unique in a history."""
        return f"{self.episode_id}:{self.tick}"

    def relevance_decision(self) -> RelevanceDecision:
        """This tick as the relevance ledger sees it."""
        return RelevanceDecision(
            context=self.inputs.context,
            executed_action=self.executed_action,
            reward=self.reward,
            spoken=tuple(SpokenMessage(sense=m.sense, action=m.action, strength=m.strength) for m in self.messages),
        )


def make_record(
    result: System1Result,
    *,
    episode_id: str,
    configuration_version: int,
    active_strategy: str,
    executed_action: Optional[str],
    primitives: Sequence[str],
    reward: float,
    done: bool,
    outcome: Optional[OutcomeTrace] = None,
    stalled: bool = False,
) -> TickRecord:
    """The record of a tick System 1 decided and the motor executed (or idled through)."""
    return TickRecord(
        episode_id=episode_id,
        tick=result.inputs.tick,
        configuration_version=configuration_version,
        exploration_level=result.exploration_level,
        active_strategy=active_strategy,
        inputs=result.inputs,
        instances=result.instances,
        messages=result.messages,
        pick=result.pick,
        executed_action=executed_action,
        primitives=tuple(primitives),
        reward=float(reward),
        done=bool(done),
        outcome=outcome,
        stalled=bool(stalled),
    )


def rerender(record: TickRecord, scope: Sequence[str]) -> RenderedEvidence:
    """A stored tick rendered under any scope, from its stored inputs."""
    return render_scope(record.inputs, scope)


def rerender_instance(record: TickRecord, instance: str, scope: Optional[Sequence[str]] = None) -> RenderedEvidence:
    """What `instance` would have seen at this tick under `scope` (its own scope at the time by default)."""
    result = record.instances[instance]
    return rerender(record, result.scope if scope is None else scope)


class HistoryStore:
    """The last `ring` ticks in memory; every tick appended to `history.jsonl` when a path is given.

    Each ring record's frame (the base64 JPEG every instance with `frame` in scope was shown) is kept in
    memory beside it and dropped with it, so the history test can attach the very screen of a tick from an
    earlier episode, whose `frames/<tick>.jpg` in the log folder a later episode may have rewritten.
    """

    def __init__(self, path: Optional[Union[str, Path]] = None, ring: int = 2000) -> None:
        self.path = Path(path) if path is not None else None
        self.ring = max(1, ring)
        self._records: Deque[TickRecord] = deque(maxlen=self.ring)
        self._frames: Dict[str, str] = {}
        self._lock = threading.Lock()
        self.appended = 0
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: TickRecord, frame_b64: Optional[str] = None) -> None:
        with self._lock:
            if len(self._records) == self.ring:
                self._frames.pop(self._records[0].key, None)
            self._records.append(record)
            if frame_b64:
                self._frames[record.key] = frame_b64
            self.appended += 1
            if self.path is not None:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(record.model_dump_json() + "\n")

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def frame(self, record: TickRecord) -> Optional[str]:
        """The base64 JPEG the instances were shown at this ring record, or None (no screen, or out of the ring)."""
        with self._lock:
            return self._frames.get(record.key)

    def records(self, episode_id: Optional[str] = None) -> List[TickRecord]:
        with self._lock:
            return [r for r in self._records if episode_id is None or r.episode_id == episode_id]

    def get(self, tick: int, episode_id: Optional[str] = None) -> Optional[TickRecord]:
        with self._lock:
            for record in reversed(self._records):
                if record.tick == tick and (episode_id is None or record.episode_id == episode_id):
                    return record
        return None

    def rerender(self, tick: int, instance: str, scope: Optional[Sequence[str]] = None, episode_id: Optional[str] = None) -> RenderedEvidence:
        """Re-render a stored tick's instance under `scope` (its own scope by default)."""
        record = self.get(tick, episode_id)
        if record is None:
            raise KeyError(f"tick {tick} is not in the history ring")
        return rerender_instance(record, instance, scope)


def load_history(path: Union[str, Path]) -> List[TickRecord]:
    """Every record of a `history.jsonl`, in order."""
    out: List[TickRecord] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                out.append(TickRecord.model_validate(json.loads(line)))
    return out


def relevance_decisions(records: Iterable[TickRecord]) -> List[RelevanceDecision]:
    return [r.relevance_decision() for r in records]
