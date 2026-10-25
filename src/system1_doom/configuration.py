"""The configuration: everything that shapes what each d1-ultra instance sees, as versioned data.

The configuration is what System 2 will own (design spec, section 8): each sense's scope, concern and
reason vocabulary, the central instance's scope, the exploration level, the active strategy, the admitted
macros, and the bounds every instance works inside. This module is data only: pydantic models, their
validation, the default configuration from the design's tables, and loading and saving. Nothing here
decides anything. In this version only an admitted macro changes the configuration during play: the
controller queues the new version and applies it at the next tick boundary, the hook System 2 will use.

The design's numbers live in `Bounds`, not scattered as literals: the 0.5 at which a sense speaks (d1's
own yes), the 5 s per-call budget, the pool of 6 calls in flight, the 7-channel scope, the channel caps,
the 2,000-tick history ring, the 8-decision return with discount 0.9, the 3 consecutive central misses,
and the 8 frames a decision lasts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Literal, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from system1_doom.actions import ActionSpec

ExplorationLevel = Literal["exploit", "explore"]

SENSE_NAMES: Tuple[str, ...] = ("survival", "combat", "navigation", "resource", "goal")
CENTRAL_NAME = "central"

# Every channel of evidence an instance can be shown, in the fixed order a scope is rendered in.
CHANNELS: Tuple[str, ...] = (
    "vitals",
    "threats",
    "incoming",
    "outgoing",
    "pickups",
    "geometry",
    "position",
    "progress",
    "history",
    "frame",
    "menu",
    "projections",
    "values",
    "novelty",
    "archive",
    "exploration",
    "messages",
    "relevance",
)
# Only the central instance may be shown these: what the senses said, their record, and the level.
CENTRAL_ONLY_CHANNELS: Tuple[str, ...] = ("messages", "relevance", "exploration")
# A sense must never hear the others or see their record.
SENSE_FORBIDDEN_CHANNELS: Tuple[str, ...] = ("messages", "relevance")


class Bounds(BaseModel):
    """The hand-written limits every instance works inside. Bounds, never weights."""

    model_config = ConfigDict(frozen=True)

    call_budget_sec: float = Field(default=5.0, gt=0.0, le=60.0, description="Per-call budget for one d1-ultra call")
    yes_at: float = Field(
        default=0.5, description="d1's own yes: a sense speaks, and the admit instance admits, at this probability or more"
    )
    max_scope_channels: int = Field(default=7, ge=1, le=len(CHANNELS))
    max_enemies: int = Field(default=6, ge=1, description="Enemies rendered in the threats channel")
    max_pickups: int = Field(default=6, ge=1, description="Pickups rendered in the pickups channel")
    max_history_steps: int = Field(default=6, ge=1, description="Primitives rendered in the history channel")
    max_summaries: int = Field(default=3, ge=1, description="Decision summaries rendered in the history channel")
    system1_pool: int = Field(default=6, ge=1, description="Calls in flight for System 1: five senses and the central")
    system2_pool: int = Field(default=2, ge=1, description="Calls in flight for System 2, on its own pool")
    trials_in_flight: int = Field(default=1, ge=1)
    cooling_decisions: int = Field(default=60, ge=0, description="Decisions an instance rests after a change to it")
    history_ring: int = Field(default=2000, ge=1, description="Ticks kept in memory; every tick is persisted")
    history_test_sample: int = Field(default=24, ge=1)
    system2_calls_per_cycle: int = Field(default=40, ge=1)
    central_miss_limit: int = Field(default=3, ge=1, description="Consecutive central misses that end the episode")
    decision_frames: int = Field(default=8, ge=1, description="Game frames one decision lasts, and a missed tick idles")
    return_steps: int = Field(default=8, ge=1, description="n of the n-step return a decision is judged by")
    return_gamma: float = Field(default=0.9, gt=0.0, le=1.0, description="Discount of that return")
    probability_tolerance: float = Field(
        default=0.02, ge=0.0, description="A distribution summing further than this from 1 is malformed"
    )
    thin_record: int = Field(default=5, ge=1, description="Below this many ticks a relevance mean is shown with its count")
    stall_units: float = Field(default=4.0, ge=0.0, description="A decision that moved less than this is a stall")


class SenseConfig(BaseModel):
    """One sense: the channels it is shown, the concern its instructions name, and its finite reasons."""

    model_config = ConfigDict(frozen=True)

    scope: Tuple[str, ...]
    concern: str = Field(min_length=3, max_length=200)
    reasons: Tuple[str, ...] = Field(min_length=1)


class CentralConfig(BaseModel):
    """The central instance: its scope and the concern its instructions name."""

    model_config = ConfigDict(frozen=True)

    scope: Tuple[str, ...]
    concern: str = Field(min_length=3, max_length=200)


def _check_scope(owner: str, scope: Tuple[str, ...], bounds: Bounds, sense: bool) -> None:
    unknown = [c for c in scope if c not in CHANNELS]
    if unknown:
        raise ValueError(f"{owner}: unknown channel(s) {unknown}; the channels are {list(CHANNELS)}")
    if len(set(scope)) != len(scope):
        raise ValueError(f"{owner}: a channel appears twice in {list(scope)}")
    if "menu" not in scope:
        raise ValueError(f"{owner}: every scope must contain 'menu', the finite set its choice is over")
    if len(scope) > bounds.max_scope_channels:
        raise ValueError(f"{owner}: {len(scope)} channels, more than the bound of {bounds.max_scope_channels}")
    if sense:
        central_only = [c for c in scope if c in CENTRAL_ONLY_CHANNELS]
        if central_only:
            raise ValueError(f"{owner}: {central_only} are the central instance's channels only")


class Configuration(BaseModel):
    """Everything System 2 can change, versioned. Version 1 is the design's initial configuration."""

    model_config = ConfigDict(frozen=True)

    version: int = Field(default=1, ge=1)
    senses: Dict[str, SenseConfig]
    central: CentralConfig
    exploration_level: ExplorationLevel = "exploit"
    active_strategy: str = "strat_tactical_combat"
    admitted_macros: Tuple[ActionSpec, ...] = ()
    bounds: Bounds = Field(default_factory=Bounds)

    @model_validator(mode="after")
    def _validate(self) -> "Configuration":
        if tuple(self.senses) != SENSE_NAMES:
            raise ValueError(f"senses must be exactly {list(SENSE_NAMES)}, in that order; got {list(self.senses)}")
        for name, sense in self.senses.items():
            _check_scope(f"sense {name}", sense.scope, self.bounds, sense=True)
            if len(set(sense.reasons)) != len(sense.reasons):
                raise ValueError(f"sense {name}: a reason appears twice")
            for reason in sense.reasons:
                if not reason.replace("_", "").isalnum() or reason != reason.lower():
                    raise ValueError(f"sense {name}: reason {reason!r} must be a lowercase snake_case id")
        _check_scope("central", self.central.scope, self.bounds, sense=False)
        if any(not m.is_macro for m in self.admitted_macros):
            raise ValueError("only macro-actions can be admitted into the menu")
        return self

    def sense_names(self) -> Tuple[str, ...]:
        return tuple(self.senses)

    def with_changes(self, **changes: object) -> "Configuration":
        """A new configuration with `changes` applied and the version bumped, validated as a whole."""
        data = self.model_dump()
        data.update(changes)
        data["version"] = self.version + 1
        return Configuration.model_validate(data)

    def replace(self, **changes: object) -> "Configuration":
        """The same version with `changes` applied: for setting up the initial configuration before play."""
        return Configuration.model_validate({**self.model_dump(), **changes})

    def with_bounds(self, **changes: object) -> "Configuration":
        """The same version with some bounds replaced (used before play starts, e.g. by --call-budget)."""
        bounds = Bounds.model_validate({**self.bounds.model_dump(), **changes})
        return self.replace(bounds=bounds.model_dump())

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Configuration":
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


# The design's tables (spec sections 3 and 4): initial scopes, concerns and reason vocabularies.
DEFAULT_SENSES: Dict[str, SenseConfig] = {
    "survival": SenseConfig(
        scope=("vitals", "threats", "incoming", "projections", "menu"),
        concern="staying alive in the next few seconds",
        reasons=("health_critical", "under_fire", "enemy_too_close", "recovering", "no_threat"),
    ),
    "combat": SenseConfig(
        scope=("threats", "outgoing", "vitals", "frame", "projections", "menu"),
        concern="winning the current fight",
        reasons=("target_aimed", "target_off_centre", "several_enemies", "low_ammo", "no_target"),
    ),
    "navigation": SenseConfig(
        scope=("geometry", "position", "progress", "projections", "menu"),
        concern="moving through the level",
        reasons=("path_clear", "wall_ahead", "stalled", "door_or_switch_ahead", "unexplored_side"),
    ),
    "resource": SenseConfig(
        scope=("pickups", "vitals", "menu"),
        concern="health, armor and ammo",
        reasons=("health_pickup_near", "ammo_pickup_near", "pickup_guarded", "nothing_needed", "nothing_visible"),
    ),
    "goal": SenseConfig(
        scope=("progress", "archive", "history", "values", "menu"),
        concern="finishing the level",
        reasons=("making_progress", "plateau", "strategy_fits", "strategy_failing", "nearly_done"),
    ),
}
DEFAULT_CENTRAL = CentralConfig(
    scope=("messages", "relevance", "exploration", "vitals", "menu"),
    concern="choosing the one action the agent executes now",
)


def default_configuration(**overrides: object) -> Configuration:
    """The initial configuration of the design (version 1), with optional top-level overrides."""
    data: Dict[str, object] = {
        "version": 1,
        "senses": {k: v.model_dump() for k, v in DEFAULT_SENSES.items()},
        "central": DEFAULT_CENTRAL.model_dump(),
    }
    data.update(overrides)
    return Configuration.model_validate(data)


def reason_words(reason_id: str) -> str:
    """How a reason id reads in a message: `under_fire` -> `under fire`."""
    return reason_id.replace("_", " ")
