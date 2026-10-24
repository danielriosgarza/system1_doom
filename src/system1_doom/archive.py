from __future__ import annotations

from typing import Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from system1_doom.d1_client import ChoiceQuestion, D1UltraClient
from system1_doom.state import WorldState


StrategyControlAction = Literal[
    "continue_current_strategy",
    "switch_to_archived_strategy",
    "explore_variation",
    "request_new_strategy_proposal",
]


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


class StrategyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    choice: StrategyControlAction
    selected_strategy_id: str
    probabilities: Dict[str, float]
    confidence: float
    used_d1_ultra: bool = False


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
    """
    Bounded archive of distinct strategies / macro-action patterns (Spec Section 11).
    Prevents permanent collapse into one local optimum.
    """

    def __init__(
        self,
        max_entries: int = 12,
        initial_entries: Tuple[StrategyEntry, ...] = DEFAULT_STRATEGIES,
        d1_client: Optional[D1UltraClient] = None,
    ) -> None:
        self.max_entries = max(2, max_entries)
        self.d1_client = d1_client
        self._entries: Dict[str, StrategyEntry] = {}
        for entry in initial_entries[: self.max_entries]:
            self._entries[entry.strategy_id] = entry
        self._active_id: str = next(iter(self._entries.keys()))

    def entries(self) -> List[StrategyEntry]:
        return list(self._entries.values())

    def active_strategy(self) -> StrategyEntry:
        return self._entries[self._active_id]

    def get(self, strategy_id: str) -> Optional[StrategyEntry]:
        return self._entries.get(strategy_id)

    def admit_strategy(self, entry: StrategyEntry) -> None:
        if entry.strategy_id not in self._entries and len(self._entries) >= self.max_entries:
            # Evict lowest-scoring non-active entry to respect bounded capacity
            candidates = [e for e in self._entries.values() if e.strategy_id != self._active_id]
            if candidates:
                worst = min(candidates, key=lambda e: e.observed_reward + e.success_rate * 5.0)
                del self._entries[worst.strategy_id]
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

    def decide_strategy_action(
        self,
        state: WorldState,
        exploration_pressure: float,
        recent_failures: int,
        use_d1_sync: bool = False,
    ) -> StrategyDecision:
        active = self.active_strategy()
        used_d1 = False

        # Bounded utility scores over the 4 finite strategy meta-choices
        scores: Dict[StrategyControlAction, float] = {
            "continue_current_strategy": active.success_rate * 1.2 - 0.35 * recent_failures,
            "switch_to_archived_strategy": 0.4 + 0.25 * recent_failures + 0.3 * exploration_pressure,
            "explore_variation": 0.3 + 0.7 * exploration_pressure,
            "request_new_strategy_proposal": 0.2 + (0.9 if recent_failures >= 3 else 0.0) + 0.4 * exploration_pressure,
        }

        if use_d1_sync and self.d1_client is not None and self.d1_client.enabled:
            resp = self.d1_client.decide(
                state=(
                    f"{state.to_d1_state_text()}\nActive strategy: {active.strategy_id} "
                    f"(sr={active.success_rate:.2f}, reward={active.observed_reward:.2f}, failures={recent_failures})"
                ),
                questions={
                    "strategy_choice": ChoiceQuestion(
                        instructions="How should the controller manage its high-level strategy archive on this tick?",
                        criteria={
                            "continue_current_strategy": "Keep executing the current strategy because it fits the context",
                            "switch_to_archived_strategy": "Switch to a better-matching strategy from the archive",
                            "explore_variation": "Increase variation around the active strategy",
                            "request_new_strategy_proposal": "Request the slow LLM worker to synthesize a new strategy/macro",
                        },
                    )
                },
                timeout=1.5,
            )
            if resp is not None and "strategy_choice" in resp.raw_answers:
                c_ans = resp.choice("strategy_choice")
                for k in scores:
                    scores[k] = 0.65 * float(c_ans.probabilities.get(k, 0.0)) + 0.35 * max(0.0, scores[k])
                used_d1 = True

        # Convert to valid distribution
        shifted = {k: max(0.01, v) for k, v in scores.items()}
        tot = sum(shifted.values())
        probs = {k: v / tot for k, v in shifted.items()}
        best_choice: StrategyControlAction = max(probs.keys(), key=lambda k: probs[k])  # type: ignore[assignment]

        if best_choice == "switch_to_archived_strategy" and len(self._entries) > 1:
            alternatives = [e for e in self._entries.values() if e.strategy_id != self._active_id]
            best_alt = max(alternatives, key=lambda e: e.success_rate + 0.1 * e.observed_reward)
            self._active_id = best_alt.strategy_id

        return StrategyDecision(
            choice=best_choice,
            selected_strategy_id=self._active_id,
            probabilities=probs,
            confidence=max(probs.values()),
            used_d1_ultra=used_d1,
        )
