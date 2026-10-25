"""The controller: it renders evidence, keeps the bounds and presses the keys; d1-ultra decides.

Every tick (design spec, sections 1, 5 and 7):

1. a pending configuration is applied at the tick boundary (System 2's changes and reverts, and an
   admitted macro, are queued with `request_configuration`), and System 2 is told which one took effect;
2. the frozen world state is acquired and the legal menu built from the preconditions;
3. the evidence is computed: the simulator's projections, the value networks' predictions and tries,
   the novelty counts and the relevance records, into one `EvidenceInputs`;
4. System 1 decides: five senses in parallel, then the central, then the pick;
5. the pick's fixed primitives are executed, or, when the central missed, no key is held for the
   decision's frames;
6. the executed decision is kept for the value networks, the tick is stored whole in the history (with
   the screen d1 saw, kept in memory beside the ring record), System 2 is told, the trace is logged, and
   the recorder and dashboard are fed.

Three consecutive central misses end the episode as `connection_lost`. At the end of an episode the
relevance ledger is updated from the episode's ticks and saved, the configuration is saved (as it is at
every change that takes effect, when the run has a `configuration.json`), and System 2 is told.

System 2 (`system2.py`, on when `ControllerConfig.enable_system2`) runs on its own thread with
`slow_client`; it never blocks a tick. Nothing here ranks, scores or picks an action or a change, and
nothing stands in for a missed answer.
"""

from __future__ import annotations

import base64
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from system1_doom.actions import BUILTIN_IDS, ActionSpec, ActionVocabulary
from system1_doom.admission import AdmissionDecisionResult, ProposalAdmissionPipeline
from system1_doom.archive import StrategyArchive, StrategyEntry
from system1_doom.configuration import SENSE_NAMES, Configuration, ExplorationLevel, default_configuration
from system1_doom.d1_client import D1UltraClient, Decider, DeciderName, InstanceCounters, TransportFn, decider_of, load_api_key
from system1_doom.evidence import ChannelCaps, EvidenceCounters, StrategyLine, ValueLine, build_inputs
from system1_doom.features import encode_action, encode_actions, encode_state
from system1_doom.history import HISTORY_FILE, HistoryStore, make_record
from system1_doom.llm_worker import ExpansionRequest, SlowLLMWorker
from system1_doom.logger import DecisionLogger, ProposalTrace, TickTrace
from system1_doom.relevance import RelevanceDecision, RelevanceLedger, load_ledger, save_ledger, update_ledger
from system1_doom.simulator import BoundedSimulator, ProjectionLimits
from system1_doom.reflection import System2EpisodeSummary
from system1_doom.state import WorldState
from system1_doom.system1 import System1
from system1_doom.system2 import Record, System2
from system1_doom.tracing import (
    SlowPathRequestTrace,
    outcome_trace,
    projection_chain,
    projection_summary,
    pruned_actions,
    state_trace,
)
from system1_doom.visualizer import EpisodeRecorder, LiveDecisionDashboard, render_decision_dashboard
from system1_doom.vizdoom_env import ViZDoomBridge

if TYPE_CHECKING:
    from system1_doom.learning import Learner

BUILTIN_ACTION_IDS = BUILTIN_IDS
FinishedReason = Literal["episode_end", "max_ticks", "stopped", "connection_lost"]
MOVEMENT_PRIMITIVES = ("move_", "strafe_")


def no_key_message(decider: Union[str, Decider] = "d1-ultra") -> str:
    """Why play stops without the decider's key: nothing else could decide."""
    d = decider_of(decider)
    return (
        f"{d.key_env} is not set. {d.name} makes every decision of this agent, so play needs the key "
        "(in the environment or a .env file)."
    )


NO_KEY_MESSAGE = no_key_message("d1-ultra")


class MissingAPIKey(RuntimeError):
    """Play was asked for without the decider's key: there is nothing else that could decide."""


class ControllerConfig(BaseModel):
    """How a controller plays. The configuration (scopes, level, strategy, macros, bounds) is separate data."""

    model_config = ConfigDict(frozen=True)

    decider: DeciderName = Field(default="d1-ultra", description="The decision model every instance is a call to: d1-ultra, or jev")
    call_budget_sec: Optional[float] = Field(default=None, gt=0.0, description="Per-call budget; None keeps the configuration's")
    seed: int = Field(default=0, description="Seeds System 1's generator for draws under the explore level")
    configuration: Optional[Configuration] = Field(default=None, description="The initial configuration")
    configuration_path: Optional[str] = Field(default=None, description="A configuration.json to start from")
    exploration_level: Optional[ExplorationLevel] = Field(default=None, description="Overrides the initial level")
    enable_slow_llm: bool = True
    use_codex_cli: bool = True
    log_dir: str = "logs"
    relevance_path: Optional[str] = Field(default=None, description="runs/<scenario>/relevance.json, restored and saved")
    enable_system2: bool = Field(default=False, description="Run System 2 (the entry points turn it on unless --no-system2)")
    configuration_out: Optional[str] = Field(
        default=None, description="runs/<scenario>/configuration.json, saved at every change that takes effect and at episode end"
    )
    system2_state_path: Optional[str] = Field(default=None, description="runs/<scenario>/system2.json, System 2's state, restored and saved")
    record_experience: bool = False
    record_frames: bool = False
    show_dashboard: bool = False


def initial_configuration(config: ControllerConfig) -> Configuration:
    """The configuration a controller starts with: given, loaded, or the design's, then the overrides."""
    if config.configuration is not None:
        configuration = config.configuration
    elif config.configuration_path:
        configuration = Configuration.load(config.configuration_path)
    else:
        configuration = default_configuration()
    if config.exploration_level is not None:
        configuration = configuration.replace(exploration_level=config.exploration_level)
    if config.call_budget_sec is not None:
        configuration = configuration.with_bounds(call_budget_sec=config.call_budget_sec)
    return configuration


class EpisodeCost(BaseModel):
    """What an episode's d1-ultra calls cost, as the responses' usage blocks report it."""

    model_config = ConfigDict(frozen=True)

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0


class EpisodeMisses(BaseModel):
    """An episode's misses: in total, the ticks whose central missed, and per instance and reason."""

    model_config = ConfigDict(frozen=True)

    total: int = 0
    missed_ticks: int = 0
    by_instance: Dict[str, Dict[str, int]] = Field(default_factory=dict)


def instance_deltas(after: Dict[str, InstanceCounters], before: Dict[str, InstanceCounters]) -> Dict[str, InstanceCounters]:
    """Each instance's counters over a stretch of play: `after` minus `before`."""
    out: Dict[str, InstanceCounters] = {}
    for name, now in after.items():
        then = before.get(name, InstanceCounters())
        misses = {r: n - then.misses.get(r, 0) for r, n in now.misses.items() if n - then.misses.get(r, 0)}
        delta = InstanceCounters(
            calls=now.calls - then.calls,
            answered=now.answered - then.answered,
            misses=misses,
            retries=now.retries - then.retries,
            latency_ms_total=round(now.latency_ms_total - then.latency_ms_total, 3),
            input_tokens=now.input_tokens - then.input_tokens,
            output_tokens=now.output_tokens - then.output_tokens,
            cost=round(now.cost - then.cost, 9),
        )
        if delta.calls or delta.misses:
            out[name] = delta
    return out


def episode_cost(deltas: Dict[str, InstanceCounters]) -> EpisodeCost:
    return EpisodeCost(
        calls=sum(c.calls for c in deltas.values()),
        input_tokens=sum(c.input_tokens for c in deltas.values()),
        output_tokens=sum(c.output_tokens for c in deltas.values()),
        usd=round(sum(c.cost for c in deltas.values()), 9),
    )


class DoomDecisionController:
    """Plays ViZDoom with every decision made by d1-ultra instances (System 1)."""

    def __init__(
        self,
        env: ViZDoomBridge,
        config: ControllerConfig = ControllerConfig(),
        api_key: Optional[str] = None,
        transport: Optional[TransportFn] = None,
        custom_llm_generator: Optional[Callable[[ExpansionRequest], str]] = None,
        learner: Optional["Learner"] = None,
    ) -> None:
        decider = decider_of(config.decider)
        key = api_key if api_key is not None else load_api_key(decider)
        if not key:
            raise MissingAPIKey(no_key_message(decider))
        self.decider = decider
        self.env = env
        self.config = config
        self.learner = learner
        self.configuration = initial_configuration(config)
        self.system2: Optional[System2] = None
        self._pending_configuration: Optional[Configuration] = None
        self._config_lock = threading.Lock()
        bounds = self.configuration.bounds

        # System 1's calls and System 2's (the admit instance, later the reflectors) have pools of their own.
        self.d1_client = D1UltraClient(
            api_key=key, decider=decider, default_timeout=bounds.call_budget_sec, max_workers=bounds.system1_pool, transport=transport
        )
        self.slow_client = D1UltraClient(
            api_key=key, decider=decider, default_timeout=bounds.call_budget_sec, max_workers=bounds.system2_pool, transport=transport
        )
        self.system1 = System1(self.d1_client, pool_size=bounds.system1_pool, seed=config.seed)
        self.vocabulary = ActionVocabulary.default()
        self.simulator = BoundedSimulator(limits=ProjectionLimits())
        self.archive = StrategyArchive(active_strategy=self.configuration.active_strategy)
        self.admission_pipeline = ProposalAdmissionPipeline(
            vocabulary=self.vocabulary,
            simulator=self.simulator,
            d1_client=self.slow_client,
            call_budget_sec=bounds.call_budget_sec,
            yes_at=bounds.yes_at,
        )
        self.llm_worker = SlowLLMWorker(
            admission_pipeline=self.admission_pipeline,
            use_codex_cli=config.use_codex_cli,
            custom_generator=custom_llm_generator,
            enabled=config.enable_slow_llm,
        )
        self.logger = DecisionLogger(log_dir=config.log_dir)
        self.history = HistoryStore(self.logger.log_dir / HISTORY_FILE, ring=bounds.history_ring)
        self.ledger: RelevanceLedger = load_ledger(config.relevance_path) if config.relevance_path else RelevanceLedger()
        self._sync_menu_and_strategy(self.configuration)

        self.recorder = EpisodeRecorder()
        self._dashboard: Optional[LiveDecisionDashboard] = None
        self._dashboard_failed = False
        self._novelty: Dict[str, int] = {}
        self._pending_strategies: Dict[str, StrategyEntry] = {}
        self._slow_request: Optional[SlowPathRequestTrace] = None
        self._last_request_context = ""
        self._last_world_state: Optional[WorldState] = None
        self.ticks_played = 0
        self._begin_episode()
        if config.enable_system2:
            self.system2 = System2(self, seed=config.seed, state_path=config.system2_state_path)

    # ------------------------------------------------------------------------------------------------
    # The configuration: applied whole, only at a tick boundary.

    def request_configuration(self, configuration: Configuration) -> None:
        """Queue a configuration; it takes effect at the start of the next tick, never mid-tick."""
        with self._config_lock:
            self._pending_configuration = configuration

    def _queue_change(self, **changes: Any) -> None:
        with self._config_lock:
            base = self._pending_configuration or self.configuration
            self._pending_configuration = base.with_changes(**changes)

    def next_configuration(self) -> Configuration:
        """The configuration the next tick will play under: the one queued, else the one in play."""
        with self._config_lock:
            return self._pending_configuration or self.configuration

    def _apply_pending_configuration(self) -> bool:
        with self._config_lock:
            pending, self._pending_configuration = self._pending_configuration, None
        if pending is None:
            return False
        old = self.configuration
        self._sync_menu_and_strategy(pending)
        self.configuration = pending
        self.d1_client.default_timeout = pending.bounds.call_budget_sec
        self.admission_pipeline.call_budget_sec = pending.bounds.call_budget_sec
        self._save_configuration()
        if self.system2 is not None:
            self.system2.on_configuration_applied(old, pending)
        return True

    def _save_configuration(self) -> None:
        if self.config.configuration_out:
            path = Path(self.config.configuration_out)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.configuration.save(path)

    def _sync_menu_and_strategy(self, configuration: Configuration) -> None:
        wanted = {spec.id: spec for spec in configuration.admitted_macros}
        for action in self.vocabulary.all_actions():
            if action.id not in BUILTIN_IDS and action.id not in wanted:
                self.vocabulary.retire_macro(action.id)
        for spec in wanted.values():
            self.vocabulary.register_admitted_macro(spec)
            strategy = getattr(self, "_pending_strategies", {}).pop(spec.id, None)
            if strategy is not None:
                self.archive.admit_strategy(strategy)
        if self.archive.get(configuration.active_strategy) is not None:
            self.archive.set_active(configuration.active_strategy)

    def archive_lines(self) -> List[StrategyLine]:
        """The strategy archive as the evidence shows it (System 2's strategy reflector reads it)."""
        return [
            StrategyLine(
                strategy_id=e.strategy_id, action_sequence=tuple(e.action_sequence), observed_reward=e.observed_reward,
                success_rate=e.success_rate, usage_count=e.usage_count,
            )
            for e in self.archive.entries()
        ]

    def slow_path_available(self) -> bool:
        """Whether the slow worker could take a macro request now (on, and not busy)."""
        return self.llm_worker.enabled and not self.llm_worker.is_busy()

    # ------------------------------------------------------------------------------------------------
    # System 2's records, for the recorder and the live page.

    def add_reflection_listener(self, listener: Callable[[Record], None]) -> None:
        """Call `listener` with each of System 2's records (cycles, verdicts, notes) as it is logged."""
        if self.system2 is not None:
            self.system2.add_listener(listener)

    def remove_reflection_listener(self, listener: Callable[[Record], None]) -> None:
        if self.system2 is not None:
            self.system2.remove_listener(listener)

    def wait_system2(self, timeout: Optional[float] = None) -> bool:
        """Wait until System 2 has done what it was told so far (a cycle or a verdict in flight). True when idle."""
        return True if self.system2 is None else self.system2.wait_idle(timeout)

    def admitted_macros(self) -> List[ActionSpec]:
        """Macro-actions admitted into the menu (the configuration's admitted macros)."""
        return list(self.configuration.admitted_macros)

    def known_actions(self) -> List[ActionSpec]:
        """Every action in the vocabulary, and any admitted macro waiting for the next tick boundary."""
        actions = {a.id: a for a in self.vocabulary.all_actions()}
        with self._config_lock:
            pending = self._pending_configuration
        for spec in pending.admitted_macros if pending is not None else ():
            actions.setdefault(spec.id, spec)
        return list(actions.values())

    def restore_macros(self, specs: Sequence[ActionSpec]) -> None:
        """Admit macros saved by an earlier run: part of the initial configuration before play, else a change."""
        keep = tuple(s for s in specs if s.id not in BUILTIN_IDS and s.is_macro)
        if not keep:
            return
        merged = tuple({**{m.id: m for m in self.configuration.admitted_macros}, **{m.id: m for m in keep}}.values())
        if self.ticks_played == 0:
            self.configuration = self.configuration.replace(admitted_macros=[m.model_dump() for m in merged])
            self._sync_menu_and_strategy(self.configuration)
        else:
            self._queue_change(admitted_macros=[m.model_dump() for m in merged])

    def use_log_dir(self, log_dir: Path) -> None:
        """Write traces, the history and frames into `log_dir` from now on (serve does this per episode)."""
        self.logger = DecisionLogger(log_dir=log_dir)
        self.history.path = self.logger.log_dir / HISTORY_FILE

    # ------------------------------------------------------------------------------------------------
    # The slow path: wired and testable; nothing triggers a proposal during play in this version.

    def request_expansion(self, source: str, description: str) -> bool:
        """Ask the slow worker for a new macro-action, from the latest world state. False when busy or off."""
        state = self._last_world_state or self.env.acquire_world_state()
        enqueued = self.llm_worker.enqueue_request(
            ExpansionRequest(
                source_module=source,
                problem_description=description,
                world_state=state,
                existing_action_ids=tuple(a.id for a in self.vocabulary.all_actions()),
            )
        )
        if enqueued:
            self._last_request_context = f"{source}:{state.context_signature()}:{description}"
            self._slow_request = SlowPathRequestTrace(module=source, description=description)
        return enqueued

    def drain_slow_path(self) -> None:
        """Log the slow path's finished proposals now, as `close` does, rather than at the next tick."""
        self._handle_proposals(self.llm_worker.drain_completed_results())

    def _handle_proposals(self, results: List[AdmissionDecisionResult], tick: Optional[int] = None) -> None:
        for res in results:
            self.logger.log_proposal(
                ProposalTrace(
                    timestamp=DecisionLogger.now_iso(),
                    request_context=self._last_request_context,
                    raw_proposal=res.raw_proposal,
                    parsed_proposal=res.parsed_proposal.model_dump() if res.parsed_proposal else None,
                    validation_result="valid" if res.admitted else res.rejection_reason,
                    admission_decision=res.admitted,
                    admitted_action_id=res.admitted_action_id,
                    d1_admission_probability=res.d1_admission_probability,
                    admit_instance=res.admit_instance,
                    tick=tick,
                    source=res.source,
                    source_module=res.source_module,
                    stage_results=list(res.stage_results),
                    sandbox_summary=projection_summary(res.sandbox_outcome) if res.sandbox_outcome else None,
                    admitted_strategy_id=res.admitted_strategy_id,
                )
            )
            if self.system2 is not None:
                self.system2.on_proposal(res)
            if res.admitted and res.admitted_action is not None:
                if res.admitted_strategy is not None:
                    self._pending_strategies[res.admitted_action.id] = res.admitted_strategy
                with self._config_lock:
                    base = self._pending_configuration or self.configuration
                macros = {m.id: m for m in base.admitted_macros}
                macros[res.admitted_action.id] = res.admitted_action
                self._queue_change(admitted_macros=[m.model_dump() for m in macros.values()])

    # ------------------------------------------------------------------------------------------------
    # One tick.

    def _begin_episode(self) -> None:
        self.episode_id = uuid.uuid4().hex[:12]
        self._decisions = 0
        self._under_fire_streak = 0
        self._stall_streak = 0
        self._central_misses_in_a_row = 0
        self.connection_lost = False
        self._episode_decisions: List[RelevanceDecision] = []
        self._missed_ticks = 0

    def _menu(self, world_state: WorldState) -> Tuple[ActionSpec, ...]:
        supported = tuple(a for a in self.vocabulary.available_actions(world_state) if self.env.action_supported(a))
        return supported or tuple(self.vocabulary.available_actions(world_state))

    def _values(self, world_state: WorldState, menu: Sequence[ActionSpec], context: str) -> Optional[Dict[str, ValueLine]]:
        if self.learner is None:
            return None
        predictions = self.learner.predict_returns(encode_state(world_state), encode_actions(menu))
        tried = self.learner.tried_counts(context, [a.id for a in menu])
        return {
            a.id: ValueLine(predictions={name: round(float(values[i]), 4) for name, values in predictions.items()}, tried=tried[a.id])
            for i, a in enumerate(menu)
        }

    def _frame_ref(self, tick: int, frame_b64: Optional[str]) -> Optional[str]:
        """Keep the screen d1 saw as `frames/<tick>.jpg` in the log folder; its reference goes in the evidence.

        The file is always rewritten: tick numbers restart with each episode, and a log folder that holds
        several episodes keeps the latest episode's screens rather than an earlier episode's. The history
        test needs an earlier episode's screen too, so the history keeps each ring record's frame in memory
        (`HistoryStore.frame`); the files and the bundle layout are unchanged.
        """
        if not frame_b64:
            return None
        ref = f"frames/{tick:05d}.jpg"
        path = self.logger.log_dir / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(frame_b64))
        return ref

    def step(self) -> TickTrace:
        tick_start = time.perf_counter()
        timing_ms: Dict[str, float] = {}

        # 1. A pending configuration takes effect here, at the tick boundary, and nowhere else.
        if self.system2 is not None:
            self.system2.begin()
        changed = self._apply_pending_configuration()
        configuration = self.configuration
        bounds = configuration.bounds
        drained = self.llm_worker.drain_completed_results()

        # 2. The frozen world state and the legal menu.
        stage = time.perf_counter()
        world_state = self.env.acquire_world_state(strategy_refs=tuple(e.strategy_id for e in self.archive.entries()))
        self._last_world_state = world_state
        obs = world_state.observation
        self._handle_proposals(drained, tick=obs.tick)
        menu = self._menu(world_state)
        menu_by_id = {a.id: a for a in menu}
        avail_ids = list(menu_by_id)
        pruned = pruned_actions(self.vocabulary.all_actions(), avail_ids, world_state, self.env.action_supported)
        context = world_state.context_signature()
        self._under_fire_streak = self._under_fire_streak + 1 if obs.recent_incoming_damage > 0 else 0
        timing_ms["acquire"] = (time.perf_counter() - stage) * 1000.0

        # 3. The evidence: one EvidenceInputs for every channel of every instance this tick.
        stage = time.perf_counter()
        projections = self.simulator.project_candidates(world_state, list(menu))
        values = self._values(world_state, menu, context)
        inputs = build_inputs(
            world_state,
            menu,
            projections=projections,
            values=values,
            novelty={aid: self._novelty.get(f"{context}|{aid}", 0) for aid in avail_ids},
            archive=self.archive.entries(),
            active_strategy=configuration.active_strategy,
            exploration_level=configuration.exploration_level,
            relevance=self.ledger.snapshot(context, SENSE_NAMES),
            counters=EvidenceCounters(
                decisions=self._decisions,
                under_fire_streak=self._under_fire_streak,
                stall_streak=self._stall_streak,
                sectors_discovered=int(getattr(self.env, "episode_cells_discovered", 0)),
            ),
            frame_ref=self._frame_ref(obs.tick, obs.frame_jpeg_b64),
            caps=ChannelCaps.from_bounds(bounds),
        )
        timing_ms["evidence"] = (time.perf_counter() - stage) * 1000.0

        # 4. System 1: five senses in parallel, the central, the pick.
        result = self.system1.tick(configuration, inputs, frame_b64=obs.frame_jpeg_b64)
        timing_ms["senses"] = result.senses_ms
        timing_ms["central"] = result.central_ms
        timing_ms["decision"] = (time.perf_counter() - tick_start) * 1000.0

        # 5. Act: the pick's fixed primitives, or no keys for the decision's frames when the central missed.
        stage = time.perf_counter()
        executed: Optional[ActionSpec] = menu_by_id[result.pick.action] if result.pick.action is not None else None
        if executed is not None:
            exec_res = self.env.execute_action(executed)
        else:
            exec_res = self.env.execute_idle(bounds.decision_frames)
        timing_ms["motor"] = (time.perf_counter() - stage) * 1000.0

        # 6. The value networks learn from what d1 played; a missed tick executed nothing to learn from.
        if self.learner is not None and self.config.record_experience and executed is not None:
            self.learner.record_step(encode_state(world_state), encode_action(executed), exec_res, executed.id, context)

        # Counters behind the evidence of the next tick.
        self._decisions += 1
        if executed is not None:
            key = f"{context}|{executed.id}"
            self._novelty[key] = self._novelty.get(key, 0) + 1
            self.simulator.record_empirical_outcome(
                context_signature=context,
                action_id=executed.id,
                reward_delta=exec_res.reward,
                damage_taken=obs.recent_incoming_damage,
            )
            failed_step = exec_res.damage_taken > 8.0 or exec_res.health_after <= 0.0
            self.archive.record_outcome(
                strategy_id=configuration.active_strategy,
                reward=exec_res.reward,
                success=not failed_step,
                failure_mode="negative_reward_or_damage" if failed_step else None,
            )
            self.logger.record_macro_performance(executed.id, exec_res.reward)
            tried_to_move = any(p.startswith(MOVEMENT_PRIMITIVES) for p in executed.primitive_expansion)
            stalled = tried_to_move and exec_res.displacement < bounds.stall_units
            self._stall_streak = self._stall_streak + 1 if stalled else 0
            self._central_misses_in_a_row = 0
        else:
            stalled = False
            self._stall_streak = 0
            self._missed_ticks += 1
            self._central_misses_in_a_row += 1
            if self._central_misses_in_a_row >= bounds.central_miss_limit:
                self.connection_lost = True

        # 7. The history keeps the tick whole, with the screen d1 saw; then System 2 is told.
        outcome = outcome_trace(exec_res)
        record = make_record(
            result,
            episode_id=self.episode_id,
            configuration_version=configuration.version,
            active_strategy=configuration.active_strategy,
            executed_action=executed.id if executed is not None else None,
            primitives=exec_res.primitive_steps_executed,
            reward=exec_res.reward,
            done=exec_res.episode_finished,
            outcome=outcome,
            stalled=stalled,
        )
        self.history.append(record, frame_b64=obs.frame_jpeg_b64)
        self._episode_decisions.append(record.relevance_decision())
        if self.system2 is not None:
            self.system2.on_tick(record)

        # 8. The trace.
        timing_ms["total"] = (time.perf_counter() - tick_start) * 1000.0
        trace = TickTrace(
            timestamp=DecisionLogger.now_iso(),
            tick=obs.tick,
            episode_id=self.episode_id,
            configuration_version=configuration.version,
            configuration_changed=changed,
            state_hash=world_state.state_hash(),
            context_signature=context,
            state=state_trace(world_state),
            available_actions=avail_ids,
            pruned_actions=pruned,
            instances=result.instances,
            messages=list(result.messages),
            pick=result.pick,
            executed_action=executed.id if executed is not None else None,
            primitive_steps_executed=list(exec_res.primitive_steps_executed),
            outcome=outcome,
            reward_outcome=round(exec_res.reward, 4),
            missed=executed is None,
            exploration_level=configuration.exploration_level,
            active_strategy=configuration.active_strategy,
            projection_results_used={aid: projection_summary(p) for aid, p in projections.items()},
            projection_chain=(
                projection_chain(projections[executed.id], executed) if executed is not None and executed.id in projections else None
            ),
            slow_path_request=self._slow_request,
            timing_ms={k: round(v, 3) for k, v in timing_ms.items()},
            usage=result.usage(),
        )
        self._slow_request = None
        self.logger.log_tick(trace)
        self.ticks_played += 1

        # 9. The recorder and the dashboard.
        if self.config.record_frames:
            self.recorder.add_step(
                raw_frames=exec_res.frames_captured[-1:],
                trace=trace,
                health=exec_res.health_after,
                armor=exec_res.armor,
                ammo=obs.ammo,
            )
        self._publish_dashboard(trace, health=exec_res.health_after, armor=exec_res.armor, ammo=obs.ammo)
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
                codex_enabled=self.config.enable_slow_llm,
                codex_busy=self.llm_worker.is_busy(),
                pending_request=self._last_request_context,
            )
            self._dashboard.update(image)
        except Exception:
            self._dashboard_failed = True

    # ------------------------------------------------------------------------------------------------
    # Episodes.

    def counters(self) -> Dict[str, InstanceCounters]:
        """Every instance's call counters, System 1's and the slow path's."""
        merged = dict(self.d1_client.counters())
        for name, c in self.slow_client.counters().items():
            if name in merged:
                c = InstanceCounters(
                    calls=merged[name].calls + c.calls,
                    answered=merged[name].answered + c.answered,
                    misses={r: merged[name].misses.get(r, 0) + c.misses.get(r, 0) for r in {*merged[name].misses, *c.misses}},
                    retries=merged[name].retries + c.retries,
                    latency_ms_total=merged[name].latency_ms_total + c.latency_ms_total,
                    input_tokens=merged[name].input_tokens + c.input_tokens,
                    output_tokens=merged[name].output_tokens + c.output_tokens,
                    cost=merged[name].cost + c.cost,
                )
            merged[name] = c
        return merged

    def models_answered(self) -> Dict[str, int]:
        """Answers per model name as the responses reported it, System 1's and the slow path's together."""
        merged = dict(self.d1_client.models_answered())
        for model, n in self.slow_client.models_answered().items():
            merged[model] = merged.get(model, 0) + n
        return merged

    def run_ticks(self, num_ticks: int) -> List[TickTrace]:
        return [self.step() for _ in range(num_ticks)]

    def run_episode(
        self, max_ticks: int = 500, on_tick: Optional[Callable[[TickTrace], Optional[bool]]] = None
    ) -> Dict[str, Any]:
        """Play until the episode ends, `max_ticks` decisions are made, `on_tick` says stop, or the connection is lost.

        `on_tick(trace)` runs after each tick's trace is kept; returning True ends the episode there.
        The relevance ledger is updated from the episode's ticks (and saved when it has a path), the
        configuration is saved, and System 2 is told the episode ended (its end-of-episode cycle runs on
        its own thread, so its calls are not in this episode's cost; `wait_system2` waits for it).
        """
        previous_restart = self.env.auto_restart
        self.env.auto_restart = False
        traces: List[TickTrace] = []
        counters_before = self.counters()
        system2_since = len(self.system2.records) if self.system2 is not None else 0
        configuration_start = self.configuration
        reason: FinishedReason = "max_ticks"
        try:
            if self.env.is_episode_finished():
                self.env.restart_episode()
            if self.learner is not None:
                self.learner.discard_episode()
            self._begin_episode()
            for _ in range(max_ticks):
                if self.env.is_episode_finished():
                    reason = "episode_end"
                    break
                traces.append(self.step())
                if self.connection_lost:
                    reason = "connection_lost"
                    break
                if on_tick is not None and on_tick(traces[-1]):
                    reason = "stopped"
                    break
            else:
                if self.env.is_episode_finished():
                    reason = "episode_end"
            transitions = 0
            if self.learner is not None and self.config.record_experience:
                transitions = self.learner.end_episode()
            self._update_ledger()
            deltas = instance_deltas(self.counters(), counters_before)
            status = self.env.episode_status()
            self._save_configuration()
            system2 = self.system2.summary(system2_since) if self.system2 is not None else System2EpisodeSummary(enabled=False)
            if self.system2 is not None and traces:
                self.system2.on_episode_end(self.episode_id)
            return {
                "health": max(0.0, status["health"]),
                "armor": status["armor"],
                "kills": status["kills"],
                "reward": round(status["reward"], 2),
                "ticks": len(traces),
                "finished": self.env.is_episode_finished(),
                "cleared": self.env.level_cleared(),
                "died": bool(self.env.game.is_player_dead()),
                "finished_reason": reason,
                "transitions": transitions,
                "cost": episode_cost(deltas).model_dump(),
                "misses": EpisodeMisses(
                    total=sum(sum(c.misses.values()) for c in deltas.values()),
                    missed_ticks=sum(1 for t in traces if t.missed),
                    by_instance={name: dict(c.misses) for name, c in deltas.items() if c.misses},
                ).model_dump(),
                "instances": {name: c.model_dump() for name, c in deltas.items()},
                "actions": [t.executed_action or "missed" for t in traces],
                "configuration_start": configuration_start,
                "configuration_end": self.configuration,
                "system2": system2.model_dump(),
                "traces": traces,
            }
        finally:
            self.env.auto_restart = previous_restart

    def _update_ledger(self) -> None:
        if not self._episode_decisions:
            return
        bounds = self.configuration.bounds
        self.ledger = update_ledger(self.ledger, self._episode_decisions, bounds.return_steps, bounds.return_gamma)
        if self.config.relevance_path:
            save_ledger(self.ledger, self.config.relevance_path)
        self._episode_decisions = []

    def close(self) -> None:
        if self._dashboard is not None:
            self._dashboard.close()
        if self.system2 is not None:
            self.system2.shutdown()
        self.drain_slow_path()
        self.llm_worker.shutdown(wait=False)
        self.system1.shutdown()
        self.d1_client.shutdown(wait=False)
        self.slow_client.shutdown(wait=False)
        self.env.close()
