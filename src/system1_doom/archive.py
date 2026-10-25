"""The strategy archive: a bounded store of strategies, kept as evidence.

The archive holds a handful of named strategies (a context signature, a short action sequence, and a
record: observed reward, success rate, uses, failure modes). It decides nothing. The active strategy is
part of the configuration (System 2 will change it); the archive's entries and records are rendered in
the `archive` evidence channel, which the goal sense sees.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field


class StrategyEntry(BaseModel):
    """Strategy Archive Entry (Spec Section 11)."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    context_signature: str
    action_sequence: Tuple[str, ...]
    observed_reward: float = 0.0
    success_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    failure_modes: Tuple[str, ...] = ()
    usage_count: int = 0
    novelty_signature: str = "default"


DEFAULT_STRATEGIES: Tuple[StrategyEntry, ...] = (
    StrategyEntry(
        strategy_id="strat_tactical_combat",
        context_signature="hp:healthy|ammo:stocked|enemies:1:mid|dmg:clear|pickup:no_pickup",
        action_sequence=("peek_and_fire", "circle_strafe_left", "shoot"),
        observed_reward=5.0,
        success_rate=0.75,
        failure_modes=(),
        usage_count=1,
        novelty_signature="combat_orbit",
    ),
    StrategyEntry(
        strategy_id="strat_evasive_survival",
        context_signature="hp:critical|ammo:stocked|enemies:2:melee|dmg:under_fire|pickup:pickup_visible",
        action_sequence=("retreat_to_cover", "strafe_left", "approach_pickup"),
        observed_reward=4.0,
        success_rate=0.70,
        failure_modes=(),
        usage_count=1,
        novelty_signature="evade_recover",
    ),
    StrategyEntry(
        strategy_id="strat_corridor_advance",
        context_signature="hp:healthy|ammo:stocked|enemies:0:none|dmg:clear|pickup:pickup_visible",
        action_sequence=("move_forward", "approach_pickup", "use"),
        observed_reward=3.5,
        success_rate=0.80,
        failure_modes=(),
        usage_count=1,
        novelty_signature="advance_loot",
    ),
)


class StrategyArchive:
    """Bounded archive of distinct strategies (Spec Section 11): a store and evidence, never a chooser."""

    def __init__(
        self,
        max_entries: int = 12,
        initial_entries: Tuple[StrategyEntry, ...] = DEFAULT_STRATEGIES,
        active_strategy: Optional[str] = None,
    ) -> None:
        self.max_entries = max(2, max_entries)
        self._entries: Dict[str, StrategyEntry] = {}
        for entry in initial_entries[: self.max_entries]:
            self._entries[entry.strategy_id] = entry
        self._active_id: str = next(iter(self._entries.keys()))
        if active_strategy is not None:
            self.set_active(active_strategy)

    def entries(self) -> List[StrategyEntry]:
        return list(self._entries.values())

    def active_strategy(self) -> StrategyEntry:
        return self._entries[self._active_id]

    def get(self, strategy_id: str) -> Optional[StrategyEntry]:
        return self._entries.get(strategy_id)

    def set_active(self, strategy_id: str) -> None:
        """Make `strategy_id` the active strategy, as the configuration says; unknown ids are refused."""
        if strategy_id not in self._entries:
            raise KeyError(f"no strategy {strategy_id!r} in the archive; it holds {list(self._entries)}")
        self._active_id = strategy_id

    def admit_strategy(self, entry: StrategyEntry) -> None:
        """Store a strategy; when the archive is full, the oldest entry that is not active makes room."""
        if entry.strategy_id not in self._entries and len(self._entries) >= self.max_entries:
            oldest = next((sid for sid in self._entries if sid != self._active_id), None)
            if oldest is not None:
                del self._entries[oldest]
        self._entries[entry.strategy_id] = entry

    def record_outcome(
        self,
        strategy_id: str,
        reward: float,
        success: bool,
        failure_mode: Optional[str] = None,
    ) -> None:
        cur = self._entries.get(strategy_id)
        if cur is None:
            return
        n = cur.usage_count + 1
        alpha = 0.3
        new_reward = (1 - alpha) * cur.observed_reward + alpha * reward
        new_sr = (1 - alpha) * cur.success_rate + alpha * (1.0 if success else 0.0)
        modes = list(cur.failure_modes)
        if failure_mode and failure_mode not in modes:
            modes.append(failure_mode)
            modes = modes[-5:]
        self._entries[strategy_id] = cur.model_copy(
            update={
                "observed_reward": round(new_reward, 4),
                "success_rate": round(min(1.0, max(0.0, new_sr)), 4),
                "failure_modes": tuple(modes),
                "usage_count": n,
            }
        )
