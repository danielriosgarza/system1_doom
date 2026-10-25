"""The relevance ledger: each sense's track record per context, kept as counts and shown as evidence.

Design spec, section 6. What is learned is shown to the central instance; nothing learned is ever
multiplied into a decision. For every tick where a sense spoke, at the end of the episode:

- followed: the central executed the sense's action; paid off: the n-step return of the decision
  (the learner's return, n 8, discount 0.9, of the per-decision game reward) was positive;
- overruled: the central executed another action, and whether that chosen action paid off;
- calibration: the sense's mean strength on ticks that paid off, and on ticks that did not.

A tick whose central call missed executed no action, so it is neither followed nor overruled and is
left out of the ledger (its idle burst's reward still counts in the returns of the decisions before it).

Update and rendering are pure functions; the ledger is a pydantic model saved as `relevance.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from system1_doom.features import n_step_returns

LEDGER_VERSION = 1


class RelevanceCounts(BaseModel):
    """One sense's record in one context: plain counts and the sums behind two means."""

    model_config = ConfigDict(frozen=True)

    spoke: int = 0
    followed: int = 0
    followed_paid: int = 0
    overruled: int = 0
    overruled_paid: int = 0
    strength_paid_sum: float = 0.0
    strength_paid_n: int = 0
    strength_unpaid_sum: float = 0.0
    strength_unpaid_n: int = 0


class SpokenMessage(BaseModel):
    """What the ledger needs of a message: who spoke, for which action, how strongly."""

    model_config = ConfigDict(frozen=True)

    sense: str
    action: str
    strength: float


class RelevanceDecision(BaseModel):
    """One tick as the ledger sees it. `executed_action` is None when the central call missed."""

    model_config = ConfigDict(frozen=True)

    context: str
    executed_action: Optional[str]
    reward: float
    spoken: Tuple[SpokenMessage, ...] = ()


class RelevanceLedger(BaseModel):
    """`relevance.json`: records keyed `<sense>|<context signature>`, grown episode by episode."""

    model_config = ConfigDict(frozen=True)

    version: int = LEDGER_VERSION
    episodes: int = 0
    return_steps: int = 8
    return_gamma: float = 0.9
    entries: Dict[str, RelevanceCounts] = Field(default_factory=dict, description='Keyed "<sense>|<context signature>"')

    def record(self, sense: str, context: str) -> Optional[RelevanceCounts]:
        return self.entries.get(f"{sense}|{context}")

    def snapshot(self, context: str, senses: Sequence[str]) -> Dict[str, RelevanceCounts]:
        """The records of `senses` in `context`; a sense with no record here is absent."""
        out: Dict[str, RelevanceCounts] = {}
        for sense in senses:
            rec = self.record(sense, context)
            if rec is not None:
                out[sense] = rec
        return out


def decision_returns(rewards: Sequence[float], steps: int, gamma: float) -> List[float]:
    """The n-step discounted return of every decision of one episode, truncated at its end."""
    if not rewards:
        return []
    return [float(v) for v in n_step_returns(np.asarray(rewards, dtype=np.float32), gamma, steps)]


def update_ledger(
    ledger: RelevanceLedger, episode: Sequence[RelevanceDecision], steps: int, gamma: float
) -> RelevanceLedger:
    """A new ledger with one episode's decisions added. Pure: `ledger` is not changed."""
    returns = decision_returns([d.reward for d in episode], steps, gamma)
    entries: Dict[str, Dict[str, float]] = {k: v.model_dump() for k, v in ledger.entries.items()}
    for decision, ret in zip(episode, returns):
        if decision.executed_action is None:
            continue
        paid = ret > 0.0
        for msg in decision.spoken:
            key = f"{msg.sense}|{decision.context}"
            rec = entries.setdefault(key, RelevanceCounts().model_dump())
            rec["spoke"] += 1
            if msg.action == decision.executed_action:
                rec["followed"] += 1
                rec["followed_paid"] += 1 if paid else 0
            else:
                rec["overruled"] += 1
                rec["overruled_paid"] += 1 if paid else 0
            if paid:
                rec["strength_paid_sum"] += msg.strength
                rec["strength_paid_n"] += 1
            else:
                rec["strength_unpaid_sum"] += msg.strength
                rec["strength_unpaid_n"] += 1
    return RelevanceLedger(
        version=LEDGER_VERSION,
        episodes=ledger.episodes + 1,
        return_steps=steps,
        return_gamma=gamma,
        entries={k: RelevanceCounts.model_validate(v) for k, v in sorted(entries.items())},
    )


def _mean_phrase(total: float, n: int, thin: int) -> str:
    if n == 0:
        return "n/a"
    mean = f"{total / n:.2f}"
    return mean if n >= thin else f"{mean} over {n} tick{'' if n == 1 else 's'}"


def render_record(sense: str, counts: Optional[RelevanceCounts], thin: int = 5) -> str:
    """One sense's line in the `relevance` channel, in the words of the design (section 6)."""
    if counts is None or counts.spoke == 0:
        return f"{sense} here: no record here."
    return (
        f"{sense} here: spoke {counts.spoke}, followed {counts.followed}, "
        f"paid off {counts.followed_paid} of {counts.followed}; "
        f"overruled {counts.overruled}, the chosen action paid off {counts.overruled_paid} of {counts.overruled}; "
        f"mean strength {_mean_phrase(counts.strength_paid_sum, counts.strength_paid_n, thin)} when it paid off, "
        f"{_mean_phrase(counts.strength_unpaid_sum, counts.strength_unpaid_n, thin)} when not."
    )


def render_relevance(snapshot: Dict[str, RelevanceCounts], senses: Sequence[str], thin: int = 5) -> List[str]:
    """Every sense's line, in sense order, from a snapshot of one context."""
    return [render_record(sense, snapshot.get(sense), thin) for sense in senses]


def save_ledger(ledger: RelevanceLedger, path: Union[str, Path]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def load_ledger(path: Union[str, Path]) -> RelevanceLedger:
    """The ledger at `path`, or an empty one when there is no file yet."""
    path = Path(path)
    if not path.is_file():
        return RelevanceLedger()
    return RelevanceLedger.model_validate(json.loads(path.read_text(encoding="utf-8")))
