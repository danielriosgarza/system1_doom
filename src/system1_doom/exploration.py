from __future__ import annotations

from typing import Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

from system1_doom.d1_client import D1UltraClient, ScoreQuestion
from system1_doom.state import WorldState


class ExplorationState(BaseModel):
    """Explicit state-dependent exploration parameters (Spec Section 10)."""

    model_config = ConfigDict(frozen=True)

    recent_progress: float = 0.0
    recent_failures: int = 0
    state_visitation_novelty: float = Field(default=1.0, ge=0.0, le=1.0)
    strategy_usage_frequency: Dict[str, int] = Field(default_factory=dict)
    uncertainty_estimates: float = Field(default=0.3, ge=0.0, le=1.0)
    performance_plateau_signal: bool = False
    exploration_pressure: float = Field(default=0.25, ge=0.0, le=1.0)
    temperature: float = Field(default=0.35, gt=0.0)
    # The four quarter-terms of the pressure and the three dampers (1.0 when not applied), for traces.
    terms: Dict[str, float] = Field(default_factory=dict)


class ExplorationController:
    """
    Maintains visitation counts, failure/stall streaks, and outputs bounded exploration
    decisions (exploration_pressure and sampler temperature).
    """

    def __init__(self, d1_client: Optional[D1UltraClient] = None) -> None:
        self.d1_client = d1_client
        self._context_visits: Dict[str, int] = {}
        self._strategy_usage: Dict[str, int] = {}
        self._recent_progress_ema: float = 0.0
        self._recent_failures: int = 0
        self._stall_streak: int = 0
        self._current_state = ExplorationState()

    @property
    def current_state(self) -> ExplorationState:
        return self._current_state

    def action_novelty(self, context_signature: str, action_id: str) -> float:
        key = f"{context_signature}::{action_id}"
        visits = self._context_visits.get(key, 0)
        return 1.0 / (1.0 + visits)

    def record_action_execution(self, context_signature: str, action_id: str) -> None:
        key = f"{context_signature}::{action_id}"
        self._context_visits[key] = self._context_visits.get(key, 0) + 1

    def update_and_decide(
        self,
        state: WorldState,
        progress_delta: float,
        failed_step: bool,
        mean_module_uncertainty: float,
        active_strategy_id: str,
        near_term_winning_sequence: bool = False,
        use_d1_sync: bool = False,
    ) -> ExplorationState:
        ctx = state.context_signature()
        ctx_count = self._context_visits.get(ctx, 0) + 1
        self._context_visits[ctx] = ctx_count
        novelty = 1.0 / (1.0 + 0.5 * (ctx_count - 1))

        self._strategy_usage[active_strategy_id] = self._strategy_usage.get(active_strategy_id, 0) + 1
        self._recent_progress_ema = 0.7 * self._recent_progress_ema + 0.3 * progress_delta

        if failed_step:
            self._recent_failures = min(20, self._recent_failures + 1)
        else:
            self._recent_failures = max(0, self._recent_failures - 1)

        if progress_delta <= 0.05:
            self._stall_streak += 1
        else:
            self._stall_streak = 0

        plateau = self._stall_streak >= 3 or self._recent_failures >= 3

        # High-risk detection: low health or heavy incoming fire
        obs = state.observation
        high_risk = obs.health <= 30.0 or (obs.recent_incoming_damage >= 15.0 and len(obs.visible_enemies) > 0)

        # Base exploration pressure from Spec Section 10
        terms: Dict[str, float] = {
            "uncertainty": 0.25 * mean_module_uncertainty,
            "failures": 0.25 * min(1.0, self._recent_failures / 4.0),
            "plateau": 0.25 * (1.0 if plateau else 0.0),
            "novelty": 0.25 * novelty,
        }
        pressure = terms["uncertainty"] + terms["failures"] + terms["plateau"] + terms["novelty"]

        # Decrease pressure when strategy is producing reliable progress, in high-risk state, or winning sequence found
        terms["progress_damper"] = 0.55 if self._recent_progress_ema > 1.0 else 1.0
        terms["risk_damper"] = 0.35 if high_risk else 1.0
        terms["winning_damper"] = 0.25 if near_term_winning_sequence else 1.0
        if self._recent_progress_ema > 1.0:
            pressure *= 0.55
        if high_risk:
            pressure *= 0.35
        if near_term_winning_sequence:
            pressure *= 0.25

        if use_d1_sync and self.d1_client is not None and self.d1_client.enabled:
            resp = self.d1_client.decide(
                state=f"{state.to_d1_state_text()}\nExploration telemetry: failures={self._recent_failures}, plateau={plateau}, novelty={novelty:.2f}",
                questions={
                    "explore_level": ScoreQuestion(
                        instructions="What level of exploration vs greedy exploitation should the Doom controller use right now?",
                        criteria=[
                            "Exploit strictly: high-risk survival situation or winning strategy already working",
                            "Balanced exploration: moderate uncertainty or unfamiliar room",
                            "High exploration: stalled progress or repeated strategy failure in safe/moderate state",
                        ],
                    )
                },
                timeout=1.5,
            )
            if resp is not None and "explore_level" in resp.raw_answers:
                d1_pressure = min(1.0, max(0.0, resp.score("explore_level").score / 2.0))
                pressure = 0.5 * pressure + 0.5 * d1_pressure
                terms["d1_pressure"] = d1_pressure

        pressure = min(1.0, max(0.02, pressure))
        # Map exploration_pressure in [0, 1] to sampler temperature in [0.10, 1.10]
        temperature = 0.10 + 1.00 * pressure

        self._current_state = ExplorationState(
            recent_progress=round(self._recent_progress_ema, 4),
            recent_failures=self._recent_failures,
            state_visitation_novelty=round(novelty, 4),
            strategy_usage_frequency=dict(self._strategy_usage),
            uncertainty_estimates=round(mean_module_uncertainty, 4),
            performance_plateau_signal=plateau,
            exploration_pressure=round(pressure, 4),
            temperature=round(temperature, 4),
            terms={k: round(v, 4) for k, v in terms.items()},
        )
        return self._current_state
