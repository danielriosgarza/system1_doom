from __future__ import annotations

import math
import random
from typing import Dict, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from system1_doom.actions import ActionSpec
from system1_doom.archive import StrategyEntry
from system1_doom.d1_client import ChoiceQuestion, D1Response, D1UltraClient
from system1_doom.exploration import ExplorationController, ExplorationState
from system1_doom.modules import DecisionOutput
from system1_doom.simulator import ProjectedOutcome
from system1_doom.state import WorldState


class ArbiterDecision(BaseModel):
    """Finite arbitration decision over currently valid actions (Spec Section 9)."""

    model_config = ConfigDict(frozen=True)

    selected_action_id: str
    arbiter_distribution: Dict[str, float]
    action_scores: Dict[str, float]
    component_breakdown: Dict[str, Dict[str, float]]
    confidence: float = Field(ge=0.0, le=1.0)
    temperature_used: float
    used_d1_ultra: bool = False
    d1_distribution: Dict[str, float] = Field(default_factory=dict)
    module_weights: Dict[str, float] = Field(default_factory=dict)
    explored: bool = False


class FinalArbiter:
    """
    Combines world state, module proposals, module confidence/uncertainty,
    projected outcomes, and exploration state into one finite decision over valid actions.
    """

    def __init__(self, d1_client: Optional[D1UltraClient] = None, rng_seed: int = 42) -> None:
        self.d1_client = d1_client
        self._rng = random.Random(rng_seed)

    def _module_context_weights(
        self,
        state: WorldState,
        module_outputs: Dict[str, DecisionOutput],
        learned_gate_weights: Optional[Dict[str, float]] = None,
        learned_share: float = 0.0,
    ) -> Dict[str, float]:
        heuristic = self._heuristic_module_weights(state, module_outputs)
        if not learned_gate_weights or learned_share <= 0.0:
            return heuristic
        blended = {
            name: (1.0 - learned_share) * w + learned_share * learned_gate_weights.get(name, w)
            for name, w in heuristic.items()
        }
        tot = sum(blended.values()) or 1.0
        return {k: v / tot for k, v in blended.items()}

    def _heuristic_module_weights(self, state: WorldState, module_outputs: Dict[str, DecisionOutput]) -> Dict[str, float]:
        obs = state.observation
        fighting = len(obs.visible_enemies) > 0 and obs.ammo > 0
        base_weights = {
            "survival": 0.55 if fighting else (1.4 if obs.health <= 40.0 else 0.8),
            "combat": 2.2 if fighting else 0.35,
            "navigation": 0.45 if fighting else 1.7,
            "resource": 0.7 if fighting else (1.3 if obs.visible_pickups else 0.6),
            "goal": 1.2 if fighting else 1.3,
        }
        weighted: Dict[str, float] = {}
        for name, out in module_outputs.items():
            w = base_weights.get(name, 1.0) * (0.4 + 0.6 * out.confidence)
            weighted[name] = w
        tot = sum(weighted.values()) or 1.0
        return {k: v / tot for k, v in weighted.items()}

    def _build_d1_arbiter_question(
        self,
        available_actions: Tuple[ActionSpec, ...],
        module_outputs: Dict[str, DecisionOutput],
        projected_outcomes: Dict[str, ProjectedOutcome],
    ) -> ChoiceQuestion:
        criteria: Dict[str, str] = {}
        for act in available_actions:
            mod_votes = ", ".join(
                f"{m}:{out.action_probabilities.get(act.id, 0.0):.2f}(c={out.confidence:.2f})"
                for m, out in sorted(module_outputs.items())
            )
            proj = projected_outcomes.get(act.id)
            proj_summary = (
                f"E[val]={proj.expected_value:+.2f}, dmg_in={proj.expected_damage_taken:.1f}, "
                f"dmg_out={proj.expected_damage_dealt:.1f}, surv={proj.survival_probability:.2f}"
                if proj is not None
                else "no_proj"
            )
            criteria[act.id] = f"{act.description} | votes=[{mod_votes}] | proj=[{proj_summary}]"

        return ChoiceQuestion(
            instructions=(
                "Act as the Final Arbiter for the Doom controller. Given the world state, module probability "
                "proposals, module confidences, and short-horizon projections, select the best valid action."
            ),
            criteria=criteria,
        )

    def arbitrate(
        self,
        world_state: WorldState,
        available_actions: Tuple[ActionSpec, ...],
        module_outputs: Dict[str, DecisionOutput],
        projected_outcomes: Dict[str, ProjectedOutcome],
        exploration_state: ExplorationState,
        exploration_controller: ExplorationController,
        active_strategy: Optional[StrategyEntry] = None,
        execution_mode: Literal["async_cached", "sync_d1"] = "async_cached",
        deterministic: bool = False,
        time_budget_sec: float = 0.5,
        learned_gate_weights: Optional[Dict[str, float]] = None,
        learned_share: float = 0.0,
        exploration_floor: float = 0.0,
    ) -> ArbiterDecision:
        mod_weights = self._module_context_weights(world_state, module_outputs, learned_gate_weights, learned_share)
        ctx_sig = world_state.context_signature()

        # Query or retrieve cached d1-ultra arbiter decision
        d1_probs: Dict[str, float] = {}
        used_d1 = False
        if self.d1_client is not None and self.d1_client.enabled:
            arb_q = {"arbiter_choice": self._build_d1_arbiter_question(available_actions, module_outputs, projected_outcomes)}
            arb_ctx_key = f"arbiter:{ctx_sig}"
            images = (
                [f"data:image/jpeg;base64,{world_state.observation.frame_jpeg_b64}"]
                if world_state.observation.frame_jpeg_b64
                else None
            )
            d1_resp: Optional[D1Response] = None
            if execution_mode == "sync_d1":
                d1_resp = self.d1_client.decide(
                    state=world_state.to_d1_state_text(),
                    questions=arb_q,
                    images=images,
                    timeout=max(0.4, time_budget_sec),
                )
            else:
                d1_resp = self.d1_client.get_cached(arb_ctx_key, fallback_to_latest=False)
                self.d1_client.submit_async(
                    context_key=arb_ctx_key,
                    state=world_state.to_d1_state_text(),
                    questions=arb_q,
                    images=images,
                )
            if d1_resp is not None and "arbiter_choice" in d1_resp.raw_answers:
                try:
                    d1_probs = dict(d1_resp.choice("arbiter_choice").probabilities)
                    used_d1 = True
                except Exception:
                    used_d1 = False

        action_scores: Dict[str, float] = {}
        breakdown: Dict[str, Dict[str, float]] = {}

        for act in available_actions:
            # 1. Expected value from confidence-weighted module proposals + projection + strategy alignment
            mod_ev = sum(
                mod_weights.get(m_name, 0.2) * out.action_probabilities.get(act.id, 0.0)
                for m_name, out in module_outputs.items()
            )
            proj = projected_outcomes.get(act.id)
            proj_ev = 0.20 * proj.expected_value if proj is not None else 0.0
            strat_bonus = (
                0.15
                if (active_strategy is not None and act.id in active_strategy.action_sequence)
                else 0.0
            )
            d1_bonus = 0.30 * float(d1_probs.get(act.id, 0.0)) if used_d1 else 0.0
            expected_value = mod_ev + proj_ev + strat_bonus + d1_bonus

            # 2. Exploration bonus (rewards higher-variance / under-sampled options under exploration pressure)
            mod_disagreement = 0.0
            if module_outputs:
                probs_for_act = [out.action_probabilities.get(act.id, 0.0) for out in module_outputs.values()]
                mean_p = sum(probs_for_act) / len(probs_for_act)
                mod_disagreement = math.sqrt(sum((p - mean_p) ** 2 for p in probs_for_act) / len(probs_for_act))
            exploration_bonus = exploration_state.exploration_pressure * (0.35 * mod_disagreement + (0.12 if act.is_macro else 0.0))

            # 3. Novelty bonus
            novelty_raw = exploration_controller.action_novelty(ctx_sig, act.id)
            novelty_bonus = 0.25 * exploration_state.exploration_pressure * novelty_raw

            # 4. Risk penalty
            risk_penalty = 0.0
            if proj is not None:
                hp_vulnerability = 1.8 if world_state.observation.health <= 35.0 else 0.8
                risk_penalty = 0.04 * proj.expected_damage_taken * hp_vulnerability

            # 5. Execution cost
            exec_cost = act.execution_cost

            total_score = expected_value + exploration_bonus + novelty_bonus - risk_penalty - exec_cost
            action_scores[act.id] = total_score
            breakdown[act.id] = {
                "expected_value": round(expected_value, 4),
                "exploration_bonus": round(exploration_bonus, 4),
                "novelty_bonus": round(novelty_bonus, 4),
                "risk_penalty": round(risk_penalty, 4),
                "execution_cost": round(exec_cost, 4),
                "d1_arbiter_prob": round(float(d1_probs.get(act.id, 0.0)), 4),
                "total_score": round(total_score, 4),
            }

        # Convert scores into probability distribution controlled by exploration_state.temperature
        temp = max(0.08, exploration_state.temperature)
        max_s = max(action_scores.values())
        exps = {k: math.exp((s - max_s) / temp) for k, s in action_scores.items()}
        sum_exps = sum(exps.values()) or 1.0
        dist = {k: v / sum_exps for k, v in exps.items()}

        ranked_ids = sorted(action_scores, key=action_scores.get, reverse=True)
        score_margin = action_scores[ranked_ids[0]] - (action_scores[ranked_ids[1]] if len(ranked_ids) > 1 else 0.0)
        # A module that is nearly certain and far ahead of its own alternatives can commit
        # the arbiter. This is how an admitted macro gets reused once a module adopts it.
        committed_id: Optional[str] = None
        for out in module_outputs.values():
            if not out.utility_estimates:
                continue
            top = max(out.utility_estimates, key=out.utility_estimates.get)
            others = [value for key, value in out.utility_estimates.items() if key != top]
            runner_up = max(others) if others else 0.0
            if (
                top in action_scores
                and out.utility_estimates[top] >= 5.0
                and out.utility_estimates[top] - runner_up >= 4.0
                and out.action_probabilities.get(top, 0.0) >= 0.9
            ):
                committed_id = top
                break
        # Otherwise sample only when the modules disagree and exploration pressure is actually high.
        explored = False
        if committed_id is not None:
            selected_id = committed_id
        elif exploration_floor > 0.0 and self._rng.random() < exploration_floor:
            explore_temp = max(0.5, temp)
            explore_exps = {k: math.exp((s - max_s) / explore_temp) for k, s in action_scores.items()}
            keys = list(explore_exps.keys())
            selected_id = self._rng.choices(keys, weights=[explore_exps[k] for k in keys], k=1)[0]
            explored = True
        elif deterministic or score_margin >= 0.08 or exploration_state.exploration_pressure < 0.45:
            selected_id = ranked_ids[0]
        else:
            keys = list(dist.keys())
            weights = [dist[k] for k in keys]
            selected_id = self._rng.choices(keys, weights=weights, k=1)[0]

        exploration_controller.record_action_execution(ctx_sig, selected_id)

        return ArbiterDecision(
            selected_action_id=selected_id,
            arbiter_distribution=dist,
            action_scores=action_scores,
            component_breakdown=breakdown,
            confidence=max(dist.values()),
            temperature_used=temp,
            used_d1_ultra=used_d1,
            d1_distribution={k: float(v) for k, v in d1_probs.items()},
            module_weights={k: round(v, 4) for k, v in mod_weights.items()},
            explored=explored,
        )
