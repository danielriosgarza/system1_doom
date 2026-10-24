from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from system1_doom.actions import DEFAULT_MACROS, DEFAULT_PRIMITIVES, ActionSpec, ActionVocabulary
from system1_doom.admission import AdmissionDecisionResult, ProposalAdmissionPipeline
from system1_doom.arbiter import ArbiterDecision, FinalArbiter
from system1_doom.archive import StrategyArchive
from system1_doom.d1_client import D1UltraClient, load_api_key
from system1_doom.exploration import ExplorationController
from system1_doom.features import encode_action, encode_actions, encode_state
from system1_doom.llm_worker import ExpansionRequest, SlowLLMWorker
from system1_doom.logger import DecisionLogger, ProposalTrace, TickTrace
from system1_doom.modules import BatchModuleEvaluator, DecisionModule, DecisionOutput
from system1_doom.simulator import BoundedSimulator, ProjectedOutcome, ProjectionLimits
from system1_doom.state import WorldState
from system1_doom.tracing import (
    SlowPathRequestTrace,
    arbiter_trace,
    critical_arbiter_trace,
    module_trace,
    outcome_trace,
    projection_chain,
    projection_summary,
    pruned_actions,
    state_trace,
    steering_trace,
)
from system1_doom.visualizer import EpisodeRecorder
from system1_doom.visualizer import LiveDecisionDashboard, render_decision_dashboard
from system1_doom.vizdoom_env import ViZDoomBridge

if TYPE_CHECKING:
    from system1_doom.learning import Learner

BUILTIN_ACTION_IDS = frozenset(a.id for a in DEFAULT_PRIMITIVES + DEFAULT_MACROS)
MODULE_MEMORY_COUNTERS = ("consecutive_damage_ticks", "repeated_failures", "consecutive_stalls", "plateau_ticks")


class ControllerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution_mode: Literal["async_cached", "sync_d1"] = "async_cached"
    enable_d1_ultra: bool = True
    enable_slow_llm: bool = True
    use_codex_cli: bool = True
    tick_budget_sec: float = 0.035
    reduced_budget_threshold_sec: float = 0.012
    critical_budget_threshold_sec: float = 0.004
    log_dir: str = "logs"
    deterministic_arbiter: bool = False
    show_dashboard: bool = False
    exploration_floor: float = Field(default=0.0, ge=0.0, le=1.0)
    record_experience: bool = False
    record_frames: bool = False


class DoomDecisionController:
    """
    Main Doom Decision Controller orchestrating:
    - Fast path: state acquisition -> bounded projections -> 5 parallel modules -> exploration -> final arbiter -> execution
    - Slow path: asynchronous LLM macro-action proposals (`codex exec`) -> deterministic + d1-ultra admission gate
    """

    def __init__(
        self,
        env: ViZDoomBridge,
        config: ControllerConfig = ControllerConfig(),
        api_key: Optional[str] = None,
        custom_llm_generator: Optional[Callable[[ExpansionRequest], str]] = None,
        learner: Optional["Learner"] = None,
    ) -> None:
        self.env = env
        self.config = config
        self.learner = learner
        self.exploration_floor = config.exploration_floor

        resolved_key = api_key if api_key is not None else load_api_key()
        self.d1_client = D1UltraClient(
            api_key=resolved_key,
            enabled=config.enable_d1_ultra and bool(resolved_key),
        )
        self.vocabulary = ActionVocabulary.default()
        self.simulator = BoundedSimulator(limits=ProjectionLimits())
        self.archive = StrategyArchive(d1_client=self.d1_client)
        self.exploration = ExplorationController(d1_client=self.d1_client)
        self.module_evaluator = BatchModuleEvaluator(d1_client=self.d1_client)
        self.arbiter = FinalArbiter(d1_client=self.d1_client)
        self.admission_pipeline = ProposalAdmissionPipeline(
            vocabulary=self.vocabulary,
            archive=self.archive,
            simulator=self.simulator,
            d1_client=self.d1_client,
        )
        self.llm_worker = SlowLLMWorker(
            admission_pipeline=self.admission_pipeline,
            use_codex_cli=config.use_codex_cli,
            custom_generator=custom_llm_generator,
            enabled=config.enable_slow_llm,
        )
        self.logger = DecisionLogger(log_dir=config.log_dir)

        self._module_memories: Dict[str, Dict[str, Any]] = {
            name: {"consecutive_damage_ticks": 0, "repeated_failures": 0, "consecutive_stalls": 0, "plateau_ticks": 0}
            for name in ("survival", "combat", "navigation", "resource", "goal")
        }
        self._cached_reactive_action_id: str = "move_forward"
        self._last_pending_request_context: str = ""
        self.recorder = EpisodeRecorder()
        self._dashboard: Optional[LiveDecisionDashboard] = None
        self._dashboard_failed = False

    def replace_module(self, name: str, module: DecisionModule) -> None:
        """Allow any of the 5 decision modules to be replaced independently (Spec Section 16 & 20)."""
        if name not in self.module_evaluator.modules:
            raise ValueError(f"Unknown module slot '{name}'. Expected one of {list(self.module_evaluator.modules.keys())}.")
        self.module_evaluator.modules[name] = module

    def admitted_macros(self) -> List[ActionSpec]:
        """Macro-actions admitted at runtime (not part of the built-in vocabulary)."""
        return [a for a in self.vocabulary.all_actions() if a.id not in BUILTIN_ACTION_IDS]

    def restore_macros(self, specs: List[ActionSpec]) -> None:
        for spec in specs:
            if spec.id not in BUILTIN_ACTION_IDS:
                self.vocabulary.register_admitted_macro(spec)

    def _drain_slow_llm_proposals(self) -> None:
        self._log_proposals(self.llm_worker.drain_completed_results())

    def _log_proposals(self, results: List[AdmissionDecisionResult], tick: Optional[int] = None) -> None:
        for res in results:
            self.logger.log_proposal(
                ProposalTrace(
                    timestamp=DecisionLogger.now_iso(),
                    request_context=self._last_pending_request_context,
                    raw_proposal=res.raw_proposal,
                    parsed_proposal=res.parsed_proposal.model_dump() if res.parsed_proposal else None,
                    validation_result="valid" if res.admitted else res.rejection_reason,
                    admission_decision=res.admitted,
                    admitted_action_id=res.admitted_action_id,
                    d1_admission_probability=res.d1_admission_probability,
                    tick=tick,
                    source=res.source,
                    source_module=res.source_module,
                    stage_results=list(res.stage_results),
                    sandbox_summary=projection_summary(res.sandbox_outcome) if res.sandbox_outcome else None,
                    admitted_strategy_id=res.admitted_strategy_id,
                )
            )

    def _select_budget_mode(self, budget_sec: float) -> Literal["full", "reduced", "critical"]:
        if budget_sec <= self.config.critical_budget_threshold_sec:
            return "critical"
        if budget_sec <= self.config.reduced_budget_threshold_sec:
            return "reduced"
        return "full"

    def step(self, budget_override_sec: Optional[float] = None) -> TickTrace:
        tick_start = time.perf_counter()
        timing_ms: Dict[str, float] = {}
        budget_sec = budget_override_sec if budget_override_sec is not None else self.config.tick_budget_sec
        budget_mode = self._select_budget_mode(budget_sec)

        # 1. Drain any completed proposals from the asynchronous slow LLM worker
        drained = self.llm_worker.drain_completed_results()

        # 2. Acquire immutable WorldState S_t
        strat_refs = tuple(e.strategy_id for e in self.archive.entries())
        world_state: WorldState = self.env.acquire_world_state(strategy_refs=strat_refs)
        self._log_proposals(drained, tick=world_state.observation.tick)
        supported = tuple(
            action for action in self.vocabulary.available_actions(world_state) if self.env.action_supported(action)
        )
        available_actions = supported or tuple(self.vocabulary.available_actions(world_state))
        avail_ids = [a.id for a in available_actions]
        pruned = pruned_actions(self.vocabulary.all_actions(), avail_ids, world_state, self.env.action_supported)
        memories_in = {
            name: {key: int(memory.get(key, 0)) for key in MODULE_MEMORY_COUNTERS}
            for name, memory in self._module_memories.items()
        }
        slow_request: Optional[SlowPathRequestTrace] = None
        arb_decision: Optional[ArbiterDecision] = None

        # 3. Execute according to budget degradation policy (Spec Section 14)
        projections: Dict[str, ProjectedOutcome] = {}
        module_outputs: Dict[str, DecisionOutput] = {}
        d1_arb_dist: Dict[str, float] = {}
        module_weights: Dict[str, float] = {}
        explored = False

        context = world_state.context_signature()
        state_vec = encode_state(world_state) if self.learner is not None else None
        learned_utilities: Optional[Dict[str, Dict[str, float]]] = None
        learned_trust: Dict[str, float] = {}
        gate_weights: Optional[Dict[str, float]] = None
        gate_share = 0.0
        if self.learner is not None and budget_mode != "critical":
            predictions = self.learner.module_utilities(state_vec, encode_actions(available_actions))
            learned_utilities = {
                name: {aid: float(v) for aid, v in zip(avail_ids, values)} for name, values in predictions.items()
            }
            learned_trust = self.learner.action_trust(context, avail_ids)
            gate_weights = self.learner.gate_weights(state_vec)
            gate_share = self.learner.gate_trust(context)

        if budget_mode == "critical":
            # Critical budget -> cached/reactive decision without running projections
            selected_id = (
                self._cached_reactive_action_id
                if self._cached_reactive_action_id in avail_ids
                else avail_ids[0]
            )
            uniform_p = 1.0 / len(avail_ids)
            arb_dist = {aid: (1.0 if aid == selected_id else 0.0) for aid in avail_ids}
            for m_name in self.module_evaluator.modules:
                module_outputs[m_name] = DecisionOutput(
                    module_name=m_name,
                    ranked_actions=tuple(avail_ids),
                    action_probabilities={aid: uniform_p for aid in avail_ids},
                    utility_estimates={aid: 0.0 for aid in avail_ids},
                    confidence=0.5,
                    uncertainty=0.5,
                    used_d1_ultra=False,
                )
            used_d1 = False
        else:
            if budget_mode == "full":
                stage_start = time.perf_counter()
                projections = self.simulator.project_candidates(world_state, list(available_actions))
                timing_ms["projection"] = (time.perf_counter() - stage_start) * 1000.0

            stage_start = time.perf_counter()
            module_outputs = self.module_evaluator.evaluate_all(
                world_state=world_state,
                available_actions=available_actions,
                module_memories=self._module_memories,
                projected_outcomes=projections,
                time_budget_sec=budget_sec * 0.65,
                execution_mode=self.config.execution_mode,
                learned_utilities=learned_utilities,
                learned_trust=learned_trust,
            )
            timing_ms["modules"] = (time.perf_counter() - stage_start) * 1000.0

            # Check if any module requested asynchronous action expansion
            for m_name, m_out in module_outputs.items():
                self._module_memories[m_name] = dict(m_out.local_memory_update)
                if m_out.request_action_expansion and not self.llm_worker.is_busy():
                    desc = m_out.expansion_problem_description or f"Module {m_name} requested new macro-action."
                    self._last_pending_request_context = f"{m_name}:{world_state.context_signature()}:{desc}"
                    enqueued = self.llm_worker.enqueue_request(
                        ExpansionRequest(
                            source_module=m_name,
                            problem_description=desc,
                            world_state=world_state,
                            existing_action_ids=tuple(a.id for a in self.vocabulary.all_actions()),
                        )
                    )
                    if enqueued:
                        slow_request = SlowPathRequestTrace(module=m_name, description=desc)

            stage_start = time.perf_counter()
            arb_decision = self.arbiter.arbitrate(
                world_state=world_state,
                available_actions=available_actions,
                module_outputs=module_outputs,
                projected_outcomes=projections,
                exploration_state=self.exploration.current_state,
                exploration_controller=self.exploration,
                active_strategy=self.archive.active_strategy(),
                execution_mode=self.config.execution_mode,
                deterministic=self.config.deterministic_arbiter,
                time_budget_sec=budget_sec * 0.35,
                learned_gate_weights=gate_weights,
                learned_share=gate_share,
                exploration_floor=self.exploration_floor,
            )
            timing_ms["arbiter"] = (time.perf_counter() - stage_start) * 1000.0
            selected_id = arb_decision.selected_action_id
            arb_dist = arb_decision.arbiter_distribution
            d1_arb_dist = dict(arb_decision.d1_distribution)
            module_weights = dict(arb_decision.module_weights)
            explored = arb_decision.explored
            self._cached_reactive_action_id = selected_id
            used_d1 = arb_decision.used_d1_ultra or any(m.used_d1_ultra for m in module_outputs.values())

        timing_ms["decision"] = (time.perf_counter() - tick_start) * 1000.0

        # 4. Execute selected bounded action in ViZDoom
        selected_spec: ActionSpec = self.vocabulary.get(selected_id) or available_actions[0]
        stage_start = time.perf_counter()
        exec_res = self.env.execute_action(selected_spec)
        timing_ms["motor"] = (time.perf_counter() - stage_start) * 1000.0

        if self.learner is not None and self.config.record_experience:
            top_actions = (
                {}
                if budget_mode == "critical"
                else {name: (out.ranked_actions[0] if out.ranked_actions else None) for name, out in module_outputs.items()}
            )
            self.learner.record_step(
                state_vec, encode_action(selected_spec), exec_res, top_actions, selected_spec.id, context
            )

        # 5. Update empirical simulator cache, strategy archive, and exploration state
        failed_step = exec_res.damage_taken > 8.0 or exec_res.health_after <= 0.0
        self.simulator.record_empirical_outcome(
            context_signature=world_state.context_signature(),
            action_id=selected_spec.id,
            reward_delta=exec_res.reward,
            damage_taken=world_state.observation.recent_incoming_damage,
        )
        active_strat = self.archive.active_strategy()
        self.archive.record_outcome(
            strategy_id=active_strat.strategy_id,
            reward=exec_res.reward,
            success=not failed_step,
            failure_mode="negative_reward_or_damage" if failed_step else None,
        )
        self.logger.record_macro_performance(selected_spec.id, exec_res.reward)

        mean_unc = (
            sum(m.uncertainty for m in module_outputs.values()) / len(module_outputs)
            if module_outputs
            else 0.5
        )
        exp_state = self.exploration.update_and_decide(
            state=world_state,
            progress_delta=exec_res.kills_delta * 8.0 + max(0.0, exec_res.reward),
            failed_step=failed_step,
            mean_module_uncertainty=mean_unc,
            active_strategy_id=active_strat.strategy_id,
            near_term_winning_sequence=exec_res.kills_delta > 0.0 or exec_res.armor >= 100.0,
            use_d1_sync=(self.config.execution_mode == "sync_d1" and budget_mode == "full"),
        )
        strategy_decision = self.archive.decide_strategy_action(
            state=world_state,
            exploration_pressure=exp_state.exploration_pressure,
            recent_failures=exp_state.recent_failures,
            use_d1_sync=False,
        )

        # Update module failure/damage counters for next tick
        for m_mem in self._module_memories.values():
            if world_state.observation.recent_incoming_damage > 0:
                m_mem["consecutive_damage_ticks"] = int(m_mem.get("consecutive_damage_ticks", 0)) + 1
            else:
                m_mem["consecutive_damage_ticks"] = 0
            if failed_step:
                m_mem["repeated_failures"] = int(m_mem.get("repeated_failures", 0)) + 1
            else:
                m_mem["repeated_failures"] = 0
        nav_mem = self._module_memories["navigation"]
        tried_to_move = any(p.startswith("move_") for p in selected_spec.primitive_expansion)
        if tried_to_move and exec_res.displacement < 4.0:
            nav_mem["consecutive_stalls"] = int(nav_mem.get("consecutive_stalls", 0)) + 1
        else:
            nav_mem["consecutive_stalls"] = 0

        # 6. Log full TickTrace (Spec Section 17)
        trace = TickTrace(
            timestamp=DecisionLogger.now_iso(),
            tick=world_state.observation.tick,
            state_hash=world_state.state_hash(),
            context_signature=world_state.context_signature(),
            budget_mode=budget_mode,
            available_actions=avail_ids,
            module_outputs={
                m_name: module_trace(m_out, memories_in.get(m_name, {})) for m_name, m_out in module_outputs.items()
            },
            projection_results_used={aid: projection_summary(p) for aid, p in projections.items()},
            arbiter_distribution={k: round(v, 6) for k, v in arb_dist.items()},
            selected_action=selected_spec.id,
            primitive_steps_executed=exec_res.primitive_steps_executed,
            exploration_state=exp_state.model_dump(),
            active_strategy=self.archive.active_strategy().strategy_id,
            reward_outcome=round(exec_res.reward, 4),
            used_d1_ultra=used_d1,
            d1_arbiter_distribution={k: round(float(v), 6) for k, v in d1_arb_dist.items()},
            learning=(
                {
                    "network_share": round(learned_trust.get(selected_spec.id, 0.0), 4),
                    "gate_share": round(gate_share, 4),
                    "module_weights": module_weights,
                    "explored": explored,
                    "exploration_floor": round(self.exploration_floor, 4),
                }
                if self.learner is not None
                else {}
            ),
            state=state_trace(world_state),
            pruned_actions=pruned,
            arbiter=(
                arbiter_trace(
                    arb_decision,
                    gate_weights=gate_weights,
                    gate_share=gate_share,
                    exploration_floor=self.exploration_floor,
                    deterministic=self.config.deterministic_arbiter,
                )
                if arb_decision is not None
                else critical_arbiter_trace(self.exploration_floor, self.config.deterministic_arbiter)
            ),
            projection_chain=(
                projection_chain(projections[selected_spec.id], selected_spec) if selected_spec.id in projections else None
            ),
            steering=steering_trace(strategy_decision, self.archive.entries()),
            outcome=outcome_trace(exec_res),
            slow_path_request=slow_request,
            budget_sec=budget_sec,
            timing_ms={k: round(v, 3) for k, v in timing_ms.items()},
        )
        self.logger.log_tick(trace)
        if self.config.record_frames:
            self.recorder.add_step(
                raw_frames=exec_res.frames_captured[-1:],
                trace=trace,
                health=exec_res.health_after,
                armor=exec_res.armor,
                ammo=world_state.observation.ammo,
            )
        self._publish_dashboard(trace, health=exec_res.health_after, armor=exec_res.armor, ammo=world_state.observation.ammo)
        return trace

    def _publish_dashboard(self, trace: TickTrace, health: float, armor: float, ammo: int) -> None:
        if not self.config.show_dashboard or self._dashboard_failed:
            return
        try:
            if self._dashboard is None:
                self._dashboard = LiveDecisionDashboard()
            image = render_decision_dashboard(
                trace,
                proposals=self.logger.proposal_traces[-4:],
                health=health,
                armor=armor,
                ammo=ammo,
                d1_enabled=self.d1_client.enabled,
                codex_enabled=self.config.enable_slow_llm,
                codex_busy=self.llm_worker.is_busy(),
                pending_request=self._last_pending_request_context,
                execution_mode=self.config.execution_mode,
            )
            self._dashboard.update(image)
        except Exception:
            self._dashboard_failed = True

    def run_ticks(self, num_ticks: int) -> List[TickTrace]:
        return [self.step() for _ in range(num_ticks)]

    def run_episode(self, max_ticks: int = 500) -> Dict[str, Any]:
        """Play until the episode ends or `max_ticks` control decisions have been made."""
        previous_restart = self.env.auto_restart
        self.env.auto_restart = False
        traces: List[TickTrace] = []
        try:
            if self.env.is_episode_finished():
                self.env.restart_episode()
            if self.learner is not None:
                self.learner.discard_episode()
            for _ in range(max_ticks):
                if self.env.is_episode_finished():
                    break
                traces.append(self.step())
            transitions = 0
            if self.learner is not None and self.config.record_experience:
                transitions = self.learner.end_episode()
            status = self.env.episode_status()
            status.update(
                {
                    "ticks": float(len(traces)),
                    "finished": 1.0 if self.env.is_episode_finished() else 0.0,
                    "cleared": 1.0 if self.env.level_cleared() else 0.0,
                }
            )
            return {
                "health": max(0.0, status["health"]),
                "armor": status["armor"],
                "kills": status["kills"],
                "reward": round(status["reward"], 2),
                "ticks": len(traces),
                "finished": bool(status["finished"]),
                "cleared": bool(status["cleared"]),
                "died": bool(self.env.game.is_player_dead()),
                "transitions": transitions,
                "explored_steps": sum(1 for trace in traces if trace.learning.get("explored")),
                "network_share": (
                    sum(trace.learning.get("network_share", 0.0) for trace in traces) / len(traces) if traces else 0.0
                ),
                "actions": [trace.selected_action for trace in traces],
                "traces": traces,
            }
        finally:
            self.env.auto_restart = previous_restart

    def close(self) -> None:
        if self._dashboard is not None:
            self._dashboard.close()
        self._drain_slow_llm_proposals()
        self.module_evaluator.shutdown()
        self.llm_worker.shutdown(wait=False)
        self.d1_client.shutdown(wait=False)
        self.env.close()
