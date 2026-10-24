from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, wait
import math
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from system1_doom.actions import ActionSpec
from system1_doom.d1_client import ChoiceQuestion, D1Response, D1UltraClient, NoulQuestion, QuestionSpec
from system1_doom.simulator import ProjectedOutcome
from system1_doom.state import WorldState


def _softmax(utilities: Dict[str, float], temperature: float = 0.35) -> Dict[str, float]:
    if not utilities:
        return {}
    temp = max(0.05, temperature)
    max_u = max(utilities.values())
    exps = {k: math.exp((v - max_u) / temp) for k, v in utilities.items()}
    total = sum(exps.values()) or 1.0
    return {k: v / total for k, v in exps.items()}


def _distribution_confidence(probs: Dict[str, float]) -> Tuple[float, float]:
    """Return (confidence, uncertainty) in [0, 1] using normalized Shannon entropy."""
    n = len(probs)
    if n <= 1:
        return 1.0, 0.0
    entropy = -sum(p * math.log(max(p, 1e-12)) for p in probs.values() if p > 0)
    max_entropy = math.log(n)
    uncertainty = min(1.0, max(0.0, entropy / max_entropy))
    return 1.0 - uncertainty, uncertainty


class DecisionInput(BaseModel):
    """Standard Decision Module Input (Spec Section 6)."""

    model_config = ConfigDict(frozen=True)

    world_state: WorldState
    available_actions: Tuple[ActionSpec, ...]
    local_memory: Dict[str, Any] = Field(default_factory=dict)
    projected_outcomes: Dict[str, ProjectedOutcome] = Field(default_factory=dict)
    time_budget_sec: float = Field(default=0.02, gt=0.0)
    learned_utilities: Dict[str, float] = Field(default_factory=dict)
    learned_trust: Dict[str, float] = Field(default_factory=dict)


class DecisionOutput(BaseModel):
    """Standard Decision Module Output (Spec Section 6)."""

    model_config = ConfigDict(frozen=True)

    module_name: str
    ranked_actions: Tuple[str, ...]
    action_probabilities: Dict[str, float]
    utility_estimates: Dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    projected_outcomes: Dict[str, ProjectedOutcome] = Field(default_factory=dict)
    request_additional_simulation: bool = False
    request_action_expansion: bool = False
    expansion_problem_description: Optional[str] = None
    local_memory_update: Dict[str, Any] = Field(default_factory=dict)
    used_d1_ultra: bool = False
    d1_action_probabilities: Dict[str, float] = Field(default_factory=dict)
    # Decision anatomy for traces: the heuristic and learned utilities behind `utility_estimates`,
    # the trust that blended them, and the weight d1-ultra would get against the local distribution.
    heuristic_utilities: Dict[str, float] = Field(default_factory=dict)
    learned_utilities: Dict[str, float] = Field(default_factory=dict)
    trust: Dict[str, float] = Field(default_factory=dict)
    d1_weight: float = 0.0


class DecisionModule(ABC):
    """Abstract base class for all 5 Doom decision modules."""

    name: str
    question_prompt: str

    def __init__(self, d1_client: Optional[D1UltraClient] = None) -> None:
        self.d1_client = d1_client

    @abstractmethod
    def compute_local_utilities(self, inp: DecisionInput) -> Dict[str, float]:
        """Compute fast bounded utility estimates over available_actions."""

    @abstractmethod
    def check_expansion_needed(self, inp: DecisionInput, uncertainty: float) -> Tuple[bool, Optional[str]]:
        """Determine whether this module requests asynchronous action expansion."""

    def build_d1_questions(self, inp: DecisionInput) -> Dict[str, QuestionSpec]:
        criteria: Dict[str, str] = {}
        for act in inp.available_actions:
            proj = inp.projected_outcomes.get(act.id)
            proj_note = (
                f" [proj: E[val]={proj.expected_value:+.2f}, dmg_in={proj.expected_damage_taken:.1f}, "
                f"dmg_out={proj.expected_damage_dealt:.1f}, res={proj.expected_resource_gain:.1f}]"
                if proj is not None
                else ""
            )
            criteria[act.id] = f"{act.description}{proj_note}"

        return {
            f"{self.name}_action": ChoiceQuestion(
                instructions=self.question_prompt,
                criteria=criteria,
            ),
            f"{self.name}_expand": NoulQuestion(
                instructions=(
                    f"For module '{self.name}' ({self.question_prompt}), are the current candidate actions "
                    f"insufficient for this state such that a new macro-action should be proposed?"
                )
            ),
        }

    def build_output(self, inp: DecisionInput, d1_response: Optional[D1Response] = None) -> DecisionOutput:
        local_utils = self.compute_local_utilities(inp)
        heuristic_utils = dict(local_utils)
        if inp.learned_utilities:
            local_utils = {
                aid: (1.0 - inp.learned_trust.get(aid, 0.0)) * u
                + inp.learned_trust.get(aid, 0.0) * inp.learned_utilities.get(aid, u)
                for aid, u in local_utils.items()
            }
        local_probs = _softmax(local_utils)
        used_d1 = False

        choice_key = f"{self.name}_action"
        expand_key = f"{self.name}_expand"
        blended_probs = dict(local_probs)
        d1_probs: Dict[str, float] = {}
        ranked_local = sorted(local_utils, key=local_utils.get, reverse=True)
        utility_gap = (
            local_utils[ranked_local[0]] - local_utils[ranked_local[1]] if len(ranked_local) >= 2 else 1.0
        )
        # A large local gap means the geometry already picks the action (aim, shoot, or advance).
        d1_weight = 0.25 if utility_gap >= 0.45 else 0.75

        if d1_response is not None and choice_key in d1_response.raw_answers:
            try:
                c_ans = d1_response.choice(choice_key)
                d1_probs = {
                    act.id: float(c_ans.probabilities.get(act.id, 0.0)) for act in inp.available_actions
                }
                raw_blend = {
                    act.id: d1_weight * float(c_ans.probabilities.get(act.id, 0.0))
                    + (1.0 - d1_weight) * local_probs.get(act.id, 0.0)
                    for act in inp.available_actions
                }
                tot = sum(raw_blend.values()) or 1.0
                blended_probs = {k: v / tot for k, v in raw_blend.items()}
                used_d1 = True
            except Exception:
                used_d1 = False
                d1_probs = {}

        ranked = tuple(sorted(blended_probs.keys(), key=lambda k: blended_probs[k], reverse=True))
        conf, unc = _distribution_confidence(blended_probs)

        req_expand, expand_desc = self.check_expansion_needed(inp, unc)
        if d1_response is not None and expand_key in d1_response.raw_answers:
            try:
                if d1_response.noul(expand_key).noul > 0.78 and not req_expand:
                    req_expand = True
                    expand_desc = (
                        f"d1-ultra signaled high action-expansion need for {self.name} in context "
                        f"{inp.world_state.context_signature()}."
                    )
            except Exception:
                pass

        req_sim = bool(unc > 0.72 and len(inp.projected_outcomes) < len(inp.available_actions))
        mem_update = dict(inp.local_memory)
        mem_update["last_top_action"] = ranked[0] if ranked else None
        mem_update["last_confidence"] = round(conf, 4)

        return DecisionOutput(
            module_name=self.name,
            ranked_actions=ranked,
            action_probabilities=blended_probs,
            utility_estimates=local_utils,
            confidence=conf,
            uncertainty=unc,
            projected_outcomes=inp.projected_outcomes,
            request_additional_simulation=req_sim,
            request_action_expansion=req_expand,
            expansion_problem_description=expand_desc,
            local_memory_update=mem_update,
            used_d1_ultra=used_d1,
            d1_action_probabilities=d1_probs,
            heuristic_utilities=heuristic_utils,
            learned_utilities={aid: v for aid, v in inp.learned_utilities.items() if aid in local_utils},
            trust={aid: inp.learned_trust.get(aid, 0.0) for aid in local_utils} if inp.learned_utilities else {},
            d1_weight=d1_weight,
        )

    def evaluate(self, inp: DecisionInput, use_d1_sync: bool = False) -> DecisionOutput:
        d1_resp: Optional[D1Response] = None
        if self.d1_client is not None and self.d1_client.enabled:
            ctx_key = f"mod:{self.name}:{inp.world_state.context_signature()}"
            if use_d1_sync and inp.time_budget_sec >= 0.25:
                questions = self.build_d1_questions(inp)
                images = [f"data:image/jpeg;base64,{inp.world_state.observation.frame_jpeg_b64}"] if inp.world_state.observation.frame_jpeg_b64 else None
                d1_resp = self.d1_client.decide(
                    state=inp.world_state.to_d1_state_text(),
                    questions=questions,
                    images=images,
                    timeout=inp.time_budget_sec,
                )
            else:
                d1_resp = self.d1_client.get_cached(ctx_key)

        return self.build_output(inp, d1_response=d1_resp)


class SurvivalModule(DecisionModule):
    name = "survival"
    question_prompt = "Which available action best reduces near-term probability of death?"

    def compute_local_utilities(self, inp: DecisionInput) -> Dict[str, float]:
        obs = inp.world_state.observation
        low_hp_pressure = max(0.2, (100.0 - obs.health) / 60.0)
        utilities: Dict[str, float] = {}
        for act in inp.available_actions:
            proj = inp.projected_outcomes.get(act.id)
            u = 0.0
            if proj is not None:
                u += proj.survival_probability * 1.2 - (proj.expected_damage_taken * 0.22 * low_hp_pressure)
            if act.id in ("retreat_to_cover", "circle_strafe_left", "circle_strafe_right", "weave_fire"):
                u += 0.65 * low_hp_pressure
            elif act.id in ("strafe_left", "strafe_right", "move_backward"):
                u += 0.45 * low_hp_pressure
            elif act.id == "approach_pickup" and any(p.category in ("health", "armor") for p in obs.visible_pickups):
                u += 0.55 * low_hp_pressure
            elif act.id == "move_forward" and obs.visible_enemies:
                u -= 0.40 * low_hp_pressure
            utilities[act.id] = u
        return utilities

    def check_expansion_needed(self, inp: DecisionInput, uncertainty: float) -> Tuple[bool, Optional[str]]:
        obs = inp.world_state.observation
        dmg_streak = int(inp.local_memory.get("consecutive_damage_ticks", 0))
        if (obs.health < 35.0 and obs.recent_incoming_damage >= 15.0) or dmg_streak >= 4:
            return (
                True,
                f"Existing evasion macros failed to prevent heavy incoming damage (health={obs.health:.0f}, "
                f"recent_dmg={obs.recent_incoming_damage:.0f}, enemies={len(obs.visible_enemies)}).",
            )
        return False, None


class CombatModule(DecisionModule):
    name = "combat"
    question_prompt = "Which available combat action best improves the current fight?"

    def compute_local_utilities(self, inp: DecisionInput) -> Dict[str, float]:
        obs = inp.world_state.observation
        utilities: Dict[str, float] = {}
        nearest_angle = min((abs(e.angle_offset) for e in obs.visible_enemies), default=90.0)
        signed_angle = min(obs.visible_enemies, key=lambda e: abs(e.angle_offset)).angle_offset if obs.visible_enemies else 0.0

        for act in inp.available_actions:
            proj = inp.projected_outcomes.get(act.id)
            u = 0.0
            if proj is not None:
                u += proj.expected_damage_dealt * 0.05 - proj.expected_damage_taken * 0.04
            if obs.visible_enemies:
                aimed = nearest_angle <= 12.0
                if act.id == "shoot" and aimed:
                    u += 2.4
                elif act.id == "weave_fire":
                    u += 2.2
                elif act.id == "peek_and_fire" and aimed:
                    u += 1.6
                elif act.id in ("turn_left", "strafe_left") and signed_angle > 8.0:
                    u += 2.1
                elif act.id in ("turn_right", "strafe_right") and signed_angle < -8.0:
                    u += 2.1
                elif act.id in ("circle_strafe_left", "circle_strafe_right", "peek_and_fire", "shoot"):
                    u += 0.35
            else:
                if act.id == "move_forward":
                    u += 0.2
            utilities[act.id] = u
        return utilities

    def check_expansion_needed(self, inp: DecisionInput, uncertainty: float) -> Tuple[bool, Optional[str]]:
        failures = int(inp.local_memory.get("repeated_failures", 0))
        dmg_ticks = int(inp.local_memory.get("consecutive_damage_ticks", 0))
        if failures >= 3 or (dmg_ticks >= 4 and len(inp.world_state.observation.visible_enemies) >= 2):
            return (
                True,
                f"Existing combat macros repeatedly fail against this enemy configuration "
                f"(enemies={len(inp.world_state.observation.visible_enemies)}, failures={failures}).",
            )
        return False, None


class NavigationModule(DecisionModule):
    name = "navigation"
    question_prompt = "Which movement action best improves positional progress?"

    def compute_local_utilities(self, inp: DecisionInput) -> Dict[str, float]:
        obs = inp.world_state.observation
        utilities: Dict[str, float] = {}
        for act in inp.available_actions:
            proj = inp.projected_outcomes.get(act.id)
            u = proj.expected_positional_progress * 0.45 if proj is not None else 0.0
            if act.id == "move_forward" and obs.wall_distance_front > 64.0:
                u += 0.75
            elif act.id == "approach_pickup":
                u += 0.55
            elif act.id == "use" and obs.wall_distance_front <= 64.0:
                u += 0.80
            elif act.id == "turn_left" and obs.wall_distance_front <= 64.0 and obs.wall_distance_left > obs.wall_distance_right:
                u += 0.70
            elif act.id == "turn_right" and obs.wall_distance_front <= 64.0 and obs.wall_distance_right >= obs.wall_distance_left:
                u += 0.70
            utilities[act.id] = u
        return utilities

    def check_expansion_needed(self, inp: DecisionInput, uncertainty: float) -> Tuple[bool, Optional[str]]:
        stalls = int(inp.local_memory.get("consecutive_stalls", 0))
        if stalls >= 4:
            return (
                True,
                f"Current navigation actions cannot reliably cross this obstacle (stalls={stalls}, "
                f"wall_front={inp.world_state.observation.wall_distance_front:.0f}).",
            )
        return False, None


class ResourceModule(DecisionModule):
    name = "resource"
    question_prompt = "Which action best improves resource state without unacceptable risk?"

    def compute_local_utilities(self, inp: DecisionInput) -> Dict[str, float]:
        obs = inp.world_state.observation
        utilities: Dict[str, float] = {}
        need_hp = obs.health < 75.0
        need_ammo = obs.ammo < 15

        for act in inp.available_actions:
            proj = inp.projected_outcomes.get(act.id)
            u = 0.0
            if proj is not None:
                u += proj.expected_resource_gain * 0.12 - proj.expected_damage_taken * 0.05
            if act.id == "approach_pickup" and obs.visible_pickups:
                u += 1.15 if (need_hp or need_ammo) else 0.75
            elif act.id == "move_forward" and obs.visible_pickups:
                u += 0.55
            elif "shoot" in act.primitive_expansion and not obs.visible_enemies:
                u -= 0.65  # Penalize wasting ammo when no enemies are visible
            utilities[act.id] = u
        return utilities

    def check_expansion_needed(self, inp: DecisionInput, uncertainty: float) -> Tuple[bool, Optional[str]]:
        obs = inp.world_state.observation
        if obs.ammo <= 2 and obs.health <= 35.0 and obs.visible_pickups:
            return (
                True,
                "Low ammo and low health while pickups are guarded by enemies; need an evasive pickup acquisition macro.",
            )
        return False, None


class GoalModule(DecisionModule):
    name = "goal"
    question_prompt = "Which action or projected state most increases probability of eventual level success?"

    def compute_local_utilities(self, inp: DecisionInput) -> Dict[str, float]:
        obs = inp.world_state.observation
        utilities: Dict[str, float] = {}
        for act in inp.available_actions:
            proj = inp.projected_outcomes.get(act.id)
            u = proj.expected_value * 0.5 if proj is not None else 0.0
            if obs.visible_enemies:
                if act.id in ("circle_strafe_left", "circle_strafe_right", "peek_and_fire", "shoot", "weave_fire"):
                    u += 0.60
            else:
                if act.id in ("move_forward", "approach_pickup"):
                    u += 0.70
            utilities[act.id] = u
        return utilities

    def check_expansion_needed(self, inp: DecisionInput, uncertainty: float) -> Tuple[bool, Optional[str]]:
        if int(inp.local_memory.get("plateau_ticks", 0)) >= 6:
            return (
                True,
                "Episode progress has plateaued; need a combined advance-and-clear tactical macro-action.",
            )
        return False, None


class BatchModuleEvaluator:
    """
    Runs the 5 independent decision modules over the same immutable WorldState snapshot.
    Supports:
    - 'sync_d1': batches all 5 module questions into a single d1-ultra call
    - 'async_cached': reads cached d1-ultra response immediately, triggers non-blocking refresh,
      and runs modules in parallel worker threads within strict tick budget
    """

    def __init__(self, d1_client: Optional[D1UltraClient] = None) -> None:
        self.d1_client = d1_client
        self.modules: Dict[str, DecisionModule] = {
            "survival": SurvivalModule(d1_client=d1_client),
            "combat": CombatModule(d1_client=d1_client),
            "navigation": NavigationModule(d1_client=d1_client),
            "resource": ResourceModule(d1_client=d1_client),
            "goal": GoalModule(d1_client=d1_client),
        }
        self._pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="doom-mod")

    def evaluate_all(
        self,
        world_state: WorldState,
        available_actions: Tuple[ActionSpec, ...],
        module_memories: Dict[str, Dict[str, Any]],
        projected_outcomes: Dict[str, ProjectedOutcome],
        time_budget_sec: float = 0.025,
        execution_mode: Literal["async_cached", "sync_d1"] = "async_cached",
        learned_utilities: Optional[Dict[str, Dict[str, float]]] = None,
        learned_trust: Optional[Dict[str, float]] = None,
    ) -> Dict[str, DecisionOutput]:
        learned = learned_utilities or {}
        inputs: Dict[str, DecisionInput] = {
            name: DecisionInput(
                world_state=world_state,
                available_actions=available_actions,
                local_memory=module_memories.get(name, {}),
                projected_outcomes=projected_outcomes,
                time_budget_sec=time_budget_sec,
                learned_utilities=learned.get(name, {}),
                learned_trust=dict(learned_trust or {}) if name in learned else {},
            )
            for name in self.modules
        }

        combined_questions: Dict[str, QuestionSpec] = {}
        for name, mod in self.modules.items():
            combined_questions.update(mod.build_d1_questions(inputs[name]))

        images = (
            [f"data:image/jpeg;base64,{world_state.observation.frame_jpeg_b64}"]
            if world_state.observation.frame_jpeg_b64
            else None
        )
        batch_ctx_key = f"batch_mods:{world_state.context_signature()}"
        d1_resp: Optional[D1Response] = None

        if self.d1_client is not None and self.d1_client.enabled:
            if execution_mode == "sync_d1":
                d1_resp = self.d1_client.decide(
                    state=world_state.to_d1_state_text(),
                    questions=combined_questions,
                    images=images,
                    timeout=max(0.5, time_budget_sec),
                )
            else:
                d1_resp = self.d1_client.get_cached(batch_ctx_key, fallback_to_latest=False)
                self.d1_client.submit_async(
                    context_key=batch_ctx_key,
                    state=world_state.to_d1_state_text(),
                    questions=combined_questions,
                    images=images,
                )

        # Evaluate all 5 modules in parallel worker threads within time_budget_sec
        futures = {
            name: self._pool.submit(mod.build_output, inputs[name], d1_resp)
            for name, mod in self.modules.items()
        }
        done, not_done = wait(futures.values(), timeout=max(0.005, time_budget_sec))

        results: Dict[str, DecisionOutput] = {}
        for name, fut in futures.items():
            if fut in done and not fut.cancelled():
                try:
                    results[name] = fut.result(timeout=0.001)
                except Exception:
                    results[name] = self.modules[name].build_output(inputs[name], None)
            else:
                fut.cancel()
                # Graceful degradation if a module worker missed the tick deadline
                results[name] = self.modules[name].build_output(inputs[name], None)

        return results

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
