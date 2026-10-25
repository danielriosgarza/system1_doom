"""System 1: one tick of decision, made entirely by d1-ultra instances.

Design spec, sections 4, 5 and 7. A tick runs the five senses in parallel, turns the senses that spoke
into messages, then runs the central instance on its own scope (the messages, each sense's relevance,
the exploration level, its world channels, the legal menu). The central's answer becomes the action:

- `top` under the `exploit` level: the action d1 gave the highest probability;
- `drawn` under the `explore` level: one action drawn from d1's own distribution with System 1's
  seeded generator, the uniform number logged so the draw can be replayed;
- `missed` when the central call missed: no action, the motor holds no keys for the decision.

Where the top probabilities tie, the first in menu order is taken and the tie is logged. There is no
temperature, no bonus and no stand-in: nothing here ranks or scores an action, and a missed central is
recorded as missed.

The motor's targets are the senses' answers too: the enemy the aim locks onto is the combat sense's
`target` answer and the pickup a pickup-seeking action walks to is the resource sense's (whichever sense
the configuration gives each target). A sense that missed, or was not asked because its scope showed no
candidate, leaves its target empty, and the motor then has nothing to aim at. While the level is `explore` the central is also shown `novelty`, when its scope has
room within the bound.
"""

from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from system1_doom.configuration import CENTRAL_NAME, Configuration, ExplorationLevel
from system1_doom.d1_client import D1UltraClient, Usage
from system1_doom.evidence import EvidenceInputs, Message
from system1_doom.instance import InstanceResult, central_spec, run_instance, sense_spec, target_criteria
from system1_doom.senses import messages_of, run_senses

PickKind = Literal["top", "drawn", "missed"]


class Pick(BaseModel):
    """How the central's answer became the executed action."""

    model_config = ConfigDict(frozen=True)

    kind: PickKind
    action: Optional[str] = Field(default=None, description="The action to execute; None when the central missed")
    probability: Optional[float] = Field(default=None, description="d1's probability of that action")
    draw: Optional[float] = Field(default=None, description="The uniform number in [0, 1) drawn under explore")
    tie: bool = Field(default=False, description="The top probability was shared; the first in menu order was taken")
    tied: Tuple[str, ...] = Field(default=(), description="The actions sharing the top probability, in menu order")


def central_scope(config: Configuration) -> Tuple[str, ...]:
    """The central's scope this tick: its configured scope, plus `novelty` while exploring if there is room."""
    scope = tuple(config.central.scope)
    if (
        config.exploration_level == "explore"
        and "novelty" not in scope
        and len(scope) < config.bounds.max_scope_channels
    ):
        scope = scope + ("novelty",)
    return scope


def pick_action(
    central: InstanceResult, menu_ids: Sequence[str], level: ExplorationLevel, rng: random.Random
) -> Pick:
    """Turn the central's answer into the action: `top`, `drawn` from d1's distribution, or `missed`."""
    if central.missed or not central.action_probabilities:
        return Pick(kind="missed")
    probs = [float(central.action_probabilities.get(a, 0.0)) for a in menu_ids]
    best = max(probs)
    tied = tuple(a for a, p in zip(menu_ids, probs) if p == best)
    if level == "exploit":
        return Pick(kind="top", action=tied[0], probability=best, tie=len(tied) > 1, tied=tied if len(tied) > 1 else ())
    draw = rng.random()
    # Walk d1's own distribution in menu order; scaling the uniform number by the total keeps the
    # answer exactly as returned (it is within the tolerance of 1, never renormalised in the record).
    threshold = draw * sum(probs)
    cumulative = 0.0
    chosen: Optional[int] = None
    for index, p in enumerate(probs):
        cumulative += p
        if p > 0.0 and cumulative > threshold:
            chosen = index
            break
    if chosen is None:  # float rounding at the very top of the range: the last action d1 gave weight to
        chosen = max(i for i, p in enumerate(probs) if p > 0.0)
    return Pick(kind="drawn", action=menu_ids[chosen], probability=probs[chosen], draw=draw)


def total_usage(results: Sequence[InstanceResult]) -> Usage:
    return Usage(
        input_tokens=sum(r.usage.input_tokens for r in results),
        output_tokens=sum(r.usage.output_tokens for r in results),
        cost=round(sum(r.usage.cost for r in results), 12),
    )


class Targets(BaseModel):
    """What the senses chose for the motor's assistance this tick; None where no sense chose."""

    model_config = ConfigDict(frozen=True)

    enemy: Optional[str] = Field(default=None, description="The visible enemy the aim locks onto")
    pickup: Optional[str] = Field(default=None, description="The remembered pickup a pickup-seeking action walks to")
    chosen_by: Dict[str, str] = Field(default_factory=dict, description="Target kind -> the sense whose answer it is")


ONLY_CANDIDATE = "only candidate"


def targets_of(config: Configuration, senses: Dict[str, InstanceResult], inputs: EvidenceInputs) -> Targets:
    """Each target kind's answer, from the sense the configuration gives it; empty when that sense missed.

    A lone candidate (one enemy in view, one pickup remembered) is the target without a question, since a
    choice needs two options; it is recorded as chosen by `only candidate`.
    """
    chosen: Dict[str, str] = {}
    by: Dict[str, str] = {}
    for name, sense in config.senses.items():
        if sense.target is None:
            continue
        candidates = target_criteria(sense_spec(name, sense), inputs)
        result = senses.get(name)
        if len(candidates) == 1:
            chosen[sense.target], by[sense.target] = next(iter(candidates)), ONLY_CANDIDATE
        elif result is not None and not result.missed and result.target is not None:
            chosen[sense.target], by[sense.target] = result.target, name
    return Targets(enemy=chosen.get("enemy"), pickup=chosen.get("pickup"), chosen_by=by)


class System1Result(BaseModel):
    """One tick of System 1: the evidence inputs, the six instance results, the messages and the pick."""

    model_config = ConfigDict(frozen=True)

    inputs: EvidenceInputs = Field(description="What every channel rendered from, the messages included")
    senses: Dict[str, InstanceResult]
    central: InstanceResult
    messages: Tuple[Message, ...]
    pick: Pick
    targets: Targets = Field(default_factory=Targets, description="The senses' targets for the motor")
    exploration_level: ExplorationLevel
    senses_ms: float = 0.0
    central_ms: float = 0.0
    wall_ms: float = 0.0

    @property
    def instances(self) -> Dict[str, InstanceResult]:
        """The five senses in sense order, then the central."""
        return {**self.senses, CENTRAL_NAME: self.central}

    @property
    def missed(self) -> bool:
        return self.pick.kind == "missed"

    def usage(self) -> Usage:
        return total_usage(list(self.instances.values()))

    def misses(self) -> List[str]:
        return [name for name, r in self.instances.items() if r.missed]


class System1:
    """Runs a tick: five senses in parallel, then the central, then the pick. Seeded for explore draws."""

    def __init__(self, client: D1UltraClient, *, pool_size: int = 6, seed: int = 0) -> None:
        self.client = client
        self.seed = seed
        self.rng = random.Random(seed)
        self._pool = ThreadPoolExecutor(max_workers=max(1, pool_size), thread_name_prefix="system1")

    def tick(self, config: Configuration, inputs: EvidenceInputs, *, frame_b64: Optional[str] = None) -> System1Result:
        bounds = config.bounds
        started = time.monotonic()
        senses = run_senses(self.client, config, inputs, self._pool, frame_b64=frame_b64)
        senses_done = time.monotonic()
        messages = messages_of(senses)
        central_inputs = inputs.model_copy(update={"messages": messages, "exploration_level": config.exploration_level})
        spec = central_spec(config.central, central_scope(config))
        central = run_instance(
            self.client,
            spec,
            central_inputs,
            frame_b64=frame_b64,
            budget=bounds.call_budget_sec,
            yes_at=bounds.yes_at,
            tolerance=bounds.probability_tolerance,
        )
        finished = time.monotonic()
        pick = pick_action(central, central_inputs.menu_ids(), config.exploration_level, self.rng)
        return System1Result(
            inputs=central_inputs,
            senses=senses,
            central=central,
            messages=messages,
            pick=pick,
            targets=targets_of(config, senses, inputs),
            exploration_level=config.exploration_level,
            senses_ms=round((senses_done - started) * 1000.0, 3),
            central_ms=round((finished - senses_done) * 1000.0, 3),
            wall_ms=round((finished - started) * 1000.0, 3),
        )

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
