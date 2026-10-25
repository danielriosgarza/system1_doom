"""Record episodes played by d1-ultra or Jev as self-contained bundles, and check or describe the bundle format.

    python -m system1_doom.export --scenario deadly_corridor.cfg --episodes 1 --seed 7
    python -m system1_doom.export --scenario deadly_corridor.cfg --seed 7 --networks best --out bundles/x
    python -m system1_doom.export --scenario basic.cfg --episodes 2 --no-system2
    python -m system1_doom.export --check bundles/x
    python -m system1_doom.export --index bundles
    python -m system1_doom.export --schema bundle.schema.json

Recording needs the decider's key (LIQUID_API_KEY for d1-ultra, TYPESAFE_API_KEY for `--decider jev`):
every decision is made by its instances. A bundle is one folder per episode (schema version 2):

    episode.json      what was played, the decider, the configuration at start and end, the cost,
                      the misses and how it ended (EpisodeMeta)
    ticks.jsonl       one TickTrace per tick: the six instances with their verbatim evidence and answers
    history.jsonl     one TickRecord per tick: the tick stored whole, re-renderable under any scope
    relevance.json    the relevance ledger after the episode (RelevanceLedger)
    proposals.jsonl   one ProposalTrace per slow-path proposal, final state
    reflections.jsonl System 2's records while the episode was played: a ReflectionTrace per cycle, a
                      TrialVerdictTrace per verdict (it names the cycle that made the change, which may
                      be in an earlier episode), a System2Note per moment between; empty when none
    frames/00042.jpg  the 320x240 JPEG d1-ultra was shown at tick 42
    frames/end.jpg    the screen after the last action
    metrics.jsonl, evaluation.json, macros.json   copied from the run folder when present
                      (MetricsRow per line, EvaluationSummary, a list of ActionSpec)
    trust.json        the loaded checkpoint's experience counts, when value networks were loaded (TrustFile)

System 2 is on unless `--no-system2`: it reads the run folder's history as the episodes are played, may
change the configuration between ticks (each change a trial, `configuration_start` and `configuration_end`
show where the episode began and ended), and saves `configuration.json` and `system2.json` in the run
folder. Recording starts from that saved configuration when it exists (or `--configuration PATH`, or the
design's version 1 with `--fresh-configuration`), and each next episode of `--episodes N` from the one the
episode before saved. `episode.json` counts its cycles, history tests and trials (`system2`).

An episode that ended with `connection_lost` (three central misses in a row) is written so it can be
inspected, but it is not shippable: export exits 1, `--check` reports it and `--index` leaves it out.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic.json_schema import models_json_schema

from system1_doom.actions import ActionSpec
from system1_doom.configuration import CENTRAL_NAME, SENSE_NAMES, Configuration, ExplorationLevel
from system1_doom.controller import (
    BUILTIN_ACTION_IDS,
    ControllerConfig,
    DoomDecisionController,
    EpisodeCost,
    EpisodeMisses,
    FinishedReason,
    no_key_message,
)
from system1_doom.d1_client import DeciderName, InstanceCounters, TransportFn, load_api_key
from system1_doom.features import encode_action
from system1_doom.history import HISTORY_FILE, TickRecord
from system1_doom.history_test import HistoryTestResult
from system1_doom.instance import InstanceResult
from system1_doom.logger import TRACE_SCHEMA_VERSION, ProposalTrace, TickTrace
from system1_doom.reflection import (
    REFLECTIONS_FILE,
    ReflectionTrace,
    System2EpisodeSummary,
    System2Note,
    TrialVerdictTrace,
    load_reflections,
    summarize,
)
from system1_doom.relevance import RelevanceLedger, save_ledger
from system1_doom.state import WorldState
from system1_doom.train import (
    ConfigurationFileError,
    RunStore,
    add_configuration_flags,
    add_decider_flag,
    default_run_dir,
    starting_configuration,
)
from system1_doom.vizdoom_env import ViZDoomBridge

if TYPE_CHECKING:
    from system1_doom.learning import Learner

# Which value networks serve the `values` evidence channel: none, the best or the latest checkpoint.
Networks = Literal["none", "best", "latest"]
DECIDER = "d1-ultra"
RELEVANCE_FILE = "relevance.json"
NOT_SHIPPABLE = "connection_lost"

FRAME_QUALITY = 80
COPIED_RUN_FILES = ("metrics.jsonl", "evaluation.json", "macros.json")
# How long finishing a bundle waits for System 2's cycle or verdict in flight, so its record lands in this bundle.
SYSTEM2_WAIT_SEC = 120.0
# `macros.json` is `RunStore.save_macros`: the macros admitted during training, as action specs.
MacroList = TypeAdapter(List[ActionSpec])


def _package_version() -> str:
    try:
        return importlib.metadata.version("system1-doom")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


class ActionInfo(BaseModel):
    """One vocabulary entry as the bundle describes it."""

    model_config = ConfigDict(frozen=True)

    description: str
    is_macro: bool
    builtin: bool
    primitives: List[str]
    preconditions: Dict[str, Any]
    maximum_duration: int
    termination_condition: str
    execution_cost: float
    encoding: List[float]


class CheckpointInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    episodes: int
    transitions_seen: int
    network_share: float
    best_score: Optional[float] = None


class PlayConfigInfo(BaseModel):
    """How the episode was played; the configuration itself is recorded whole beside it."""

    model_config = ConfigDict(frozen=True)

    call_budget_sec: float
    seed: int = Field(description="System 1's generator seed, for draws under the explore level")
    max_ticks: int


class EpisodeResult(BaseModel):
    """`DoomDecisionController.run_episode` summary without the traces."""

    model_config = ConfigDict(frozen=True)

    health: float
    armor: float
    kills: float
    reward: float
    ticks: int
    finished: bool
    cleared: bool
    died: bool
    finished_reason: Optional[FinishedReason] = Field(
        default=None, description="episode_end, max_ticks, stopped, or connection_lost (not shippable); None while in progress"
    )
    transitions: int = 0
    actions: List[str] = Field(default_factory=list, description="The executed action per tick; 'missed' where the central missed")


class FramesInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    dir: str = "frames"
    pattern: str = "{tick:05d}.jpg"
    width: int = 320
    height: int = 240
    end_frame: Optional[str] = None


class EpisodeMeta(BaseModel):
    """`episode.json`: what a bundle contains and how it was recorded."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = TRACE_SCHEMA_VERSION
    name: str
    title: str
    scenario: str
    seed: int
    decider: DeciderName = Field(default=DECIDER, description="The decision model every decision was made by: d1-ultra, or jev")
    value_networks: Networks = Field(description="Which value networks served the values evidence channel")
    checkpoint: Optional[CheckpointInfo] = None
    slow_path: Literal["off", "templates", "codex"]
    config: PlayConfigInfo
    configuration_start: Configuration
    configuration_end: Configuration
    result: EpisodeResult
    cost: EpisodeCost
    misses: EpisodeMisses
    instances: Dict[str, InstanceCounters] = Field(default_factory=dict, description="Call counters per instance over the episode")
    system2: Optional[System2EpisodeSummary] = Field(
        default=None, description="What System 2 did while the episode was played, counted from reflections.jsonl; None in older bundles"
    )
    first_tick: int
    last_tick: int
    tick_count: int
    buttons: List[str]
    frames: FramesInfo
    actions: Dict[str, ActionInfo]
    files: List[str]
    package_version: str = Field(default_factory=_package_version)
    recorded_at: str


class MetricsRow(BaseModel):
    """One line of `metrics.jsonl`: a training episode as `train.learn_from_episode` recorded it."""

    model_config = ConfigDict(frozen=True)

    episode: int
    scenario: str
    reward: float
    kills: float
    health: float
    armor: float
    ticks: int
    cleared: bool
    finished: bool
    died: bool
    transitions: int
    replay_size: int
    network_share: float = 0.0
    exploration_floor: Optional[float] = Field(default=None, description="Rows written before d1-ultra decided")
    explored_steps: Optional[int] = Field(default=None, description="Rows written before d1-ultra decided")
    finished_reason: Optional[str] = None
    missed_ticks: int = 0
    cost_usd: float = 0.0
    losses: Dict[str, float] = Field(default_factory=dict, description="Mean loss per network over the episode's gradient steps")
    macros: int = 0
    episode_sec: float = 0.0
    train_sec: float = 0.0
    d1_calls: int = 0
    timestamp: str = ""


class EvaluationScores(BaseModel):
    """One brain's means over the evaluation episodes; cleared and survived are rates."""

    model_config = ConfigDict(frozen=True)

    reward: float
    cleared: float
    survived: float
    kills: float
    health: float
    ticks: float


class EvaluationSummary(BaseModel):
    """`evaluation.json`: `train.evaluate`, the same seeded episodes played by d1-ultra with no, the latest
    and the best value networks as evidence (`heuristics` is a file written before d1-ultra decided)."""

    model_config = ConfigDict(frozen=True)

    scenario: str
    episodes: int
    trained_episodes: int = 0
    none: Optional[EvaluationScores] = None
    heuristics: Optional[EvaluationScores] = None
    latest: Optional[EvaluationScores] = None
    best: Optional[EvaluationScores] = None


class TrustFile(BaseModel):
    """`trust.json`: how often each action was executed in each context during training (trust = n / (n + trust_count))."""

    model_config = ConfigDict(frozen=True)

    trust_count: float
    episodes: int
    network_share: float
    action_counts: Dict[str, int] = Field(description='Keyed "<context signature>|<action id>"')
    context_counts: Dict[str, int]


class BundleIndexEntry(BaseModel):
    """One line of `index.json`: what the app's picker and recording cards say before the bundle is opened."""

    model_config = ConfigDict(frozen=True)

    name: str
    title: str
    scenario: str
    value_networks: Networks
    seed: int
    cleared: bool
    died: bool
    reward: float
    ticks: int
    kills: float = 0.0
    configuration_start: int = Field(default=1, description="The configuration version the episode started from")
    configuration_end: int = Field(default=1, description="The configuration version it ended at")
    decider: DeciderName = Field(default=DECIDER, description="The decision model every decision was made by: d1-ultra, or jev")


def _jpeg(screen_buffer: np.ndarray, path: Path) -> None:
    arr = np.asarray(screen_buffer, dtype=np.uint8)
    if arr.ndim == 3 and arr.shape[0] in (1, 3, 4) and arr.shape[2] not in (1, 3, 4):
        arr = np.transpose(arr, (1, 2, 0))
    image = Image.fromarray(arr)
    if image.size != (320, 240):
        image = image.resize((320, 240), Image.Resampling.BILINEAR)
    image.save(path, format="JPEG", quality=FRAME_QUALITY)


class RecordingBridge(ViZDoomBridge):
    """A ViZDoom bridge that saves the JPEG each world state carries (the image d1-ultra is shown), by tick.

    Saving at acquisition, not after the motor burst, keeps the frame aligned with the enemy and
    pickup boxes in the trace's state snapshot.
    """

    def __init__(self, frames_dir: Path, **kwargs: Any) -> None:
        self.frames_dir = frames_dir
        super().__init__(**kwargs)

    @property
    def frames_dir(self) -> Path:
        return self._frames_dir

    @frames_dir.setter
    def frames_dir(self, path: Path) -> None:
        """Where the next frames go; `serve` points it at each episode's folder in turn."""
        path.mkdir(parents=True, exist_ok=True)
        self._frames_dir = path

    def acquire_world_state(self, strategy_refs: Tuple[str, ...] = ()) -> WorldState:
        world_state = super().acquire_world_state(strategy_refs=strategy_refs)
        frame = world_state.observation.frame_jpeg_b64
        if frame:
            (self.frames_dir / f"{world_state.observation.tick:05d}.jpg").write_bytes(base64.b64decode(frame))
        return world_state


class LastFrameKeeper:
    """Stands in for the controller's HUD recorder and keeps only the most recent post-action screen."""

    def __init__(self) -> None:
        self.last: Optional[np.ndarray] = None

    def add_step(self, raw_frames: Sequence[np.ndarray], trace: TickTrace, health: float = 100.0, armor: float = 0.0, ammo: int = 50) -> None:
        if raw_frames:
            self.last = raw_frames[-1]


def _action_catalog(ctrl: DoomDecisionController) -> Dict[str, ActionInfo]:
    return {
        a.id: ActionInfo(
            description=a.description,
            is_macro=a.is_macro,
            builtin=a.id in BUILTIN_ACTION_IDS,
            primitives=list(a.primitive_expansion),
            preconditions=a.preconditions.model_dump(mode="json"),
            maximum_duration=a.maximum_duration,
            termination_condition=a.termination_condition,
            execution_cost=round(a.execution_cost, 4),
            encoding=[round(float(v), 4) for v in encode_action(a)],
        )
        for a in ctrl.known_actions()
    }


def load_networks(store: RunStore, networks: Networks) -> Tuple[Optional["Learner"], Optional[Path]]:
    """The value networks for the values channel: none, or the best or latest checkpoint of the run."""
    if networks == "none":
        return None, None
    from system1_doom.learning import Learner

    path = store.best if networks == "best" else store.checkpoint
    if not path.is_file():
        raise FileNotFoundError(f"No {path.name} in {store.root}; train first or use --networks none.")
    return Learner.load(path), path


def _prepare_out_dir(out: Path) -> None:
    if out.exists():
        if any(out.iterdir()) and not (out / "episode.json").is_file():
            raise FileExistsError(f"{out} exists and is not a bundle; refusing to overwrite it.")
        shutil.rmtree(out)
    (out / "frames").mkdir(parents=True)


@dataclass
class Player:
    """Everything that plays episodes, built once: the run folder, the networks, the bridge and the controller."""

    scenario: str
    networks: Networks
    max_ticks: int
    slow_path: bool
    store: RunStore
    learner: Optional["Learner"]
    model_path: Optional[Path]
    env: RecordingBridge
    cfg: ControllerConfig
    ctrl: DoomDecisionController
    keeper: LastFrameKeeper


def build_player(
    scenario: str,
    seed: int,
    out: Path,
    networks: Networks,
    store: RunStore,
    learner: Optional["Learner"],
    model_path: Optional[Path],
    max_ticks: int = 500,
    slow_path: bool = True,
    codex: bool = False,
    call_budget_sec: Optional[float] = None,
    exploration_level: Optional[ExplorationLevel] = None,
    transport: Optional[TransportFn] = None,
    api_key: Optional[str] = None,
    system2: bool = True,
    configuration_path: Optional[Path] = None,
    fresh_configuration: bool = False,
    decider: DeciderName = DECIDER,
) -> Player:
    """The bridge and controller a bundle is played with, writing its frames and logs into `out`.

    It starts from `configuration_path` when given, else (unless `fresh_configuration`, which also forgets
    the saved configuration and System 2's state) from the run folder's saved `configuration.json` when it
    exists, else from the design's version 1, and says which on stderr.
    """
    if fresh_configuration:
        store.forget_configuration()
    start = starting_configuration(store, configuration_path, fresh_configuration)
    print(start.line, file=sys.stderr, flush=True)
    env = RecordingBridge(frames_dir=out / "frames", scenario=scenario, window_visible=False, seed=seed)
    cfg = ControllerConfig(
        decider=decider,
        call_budget_sec=call_budget_sec,
        seed=seed,
        configuration_path=str(start.path) if start.path else None,
        exploration_level=exploration_level,
        enable_slow_llm=slow_path,
        use_codex_cli=codex,
        log_dir=str(out),
        relevance_path=str(store.relevance),
        enable_system2=system2,
        configuration_out=str(store.configuration),
        system2_state_path=str(store.system2),
        record_frames=True,
    )
    try:
        ctrl = DoomDecisionController(env=env, config=cfg, learner=learner, transport=transport, api_key=api_key)
    except Exception:
        env.close()
        raise
    keeper = LastFrameKeeper()
    ctrl.recorder = keeper  # type: ignore[assignment]
    if not start.saved:
        ctrl.restore_macros(store.load_macros())
    return Player(scenario, networks, max_ticks, slow_path, store, learner, model_path, env, cfg, ctrl, keeper)


def play_episode(
    player: Player, seed: int, on_tick: Optional[Callable[[TickTrace], Optional[bool]]] = None
) -> Tuple[Dict[str, Any], List[TickTrace]]:
    """Play one seeded episode; returns `run_episode`'s summary without the traces, and the traces."""
    player.env.restart_episode(seed=seed)
    result = player.ctrl.run_episode(max_ticks=player.max_ticks, on_tick=on_tick)
    traces: List[TickTrace] = result.pop("traces")
    return result, traces


def copy_run_files(player: Player, out: Path) -> Tuple[List[str], Optional[CheckpointInfo]]:
    """Copy the run folder's files and write `trust.json`; returns the bundle's file list and the checkpoint."""
    files = ["episode.json", "ticks.jsonl", HISTORY_FILE, RELEVANCE_FILE, "proposals.jsonl", REFLECTIONS_FILE]
    if player.store.root.is_dir():
        for file_name in COPIED_RUN_FILES:
            source = player.store.root / file_name
            if source.is_file():
                shutil.copyfile(source, out / file_name)
                files.append(file_name)
    checkpoint = None
    learner = player.learner
    if learner is not None and player.model_path is not None:
        checkpoint = CheckpointInfo(
            file=player.model_path.name,
            episodes=learner.episodes,
            transitions_seen=learner.transitions_seen,
            network_share=round(learner.network_share, 4),
            best_score=round(learner.best_score, 2) if np.isfinite(learner.best_score) else None,
        )
        trust = {
            "trust_count": learner.config.trust_count,
            "episodes": learner.episodes,
            "network_share": round(learner.network_share, 4),
            "action_counts": learner.action_counts,
            "context_counts": learner.context_counts,
        }
        (out / "trust.json").write_text(json.dumps(trust), encoding="utf-8")
        files.append("trust.json")
    return files, checkpoint


def default_title(scenario: str, networks: Networks, seed: int, decider: DeciderName = DECIDER) -> str:
    stem = Path(scenario).stem
    evidence = "no value networks" if networks == "none" else f"{networks} value networks"
    return f"{stem.replace('_', ' ')}, {decider} with {evidence}, seed {seed}"


def episode_meta(
    player: Player,
    name: str,
    title: str,
    seed: int,
    result: Dict[str, Any],
    traces: Sequence[TickTrace],
    files: List[str],
    checkpoint: Optional[CheckpointInfo],
    end_frame: Optional[str] = None,
    system2: Optional[System2EpisodeSummary] = None,
) -> EpisodeMeta:
    """`episode.json` for an episode played by `player`; the action catalog is the vocabulary as it is now."""
    ctrl = player.ctrl
    start = result.get("configuration_start", ctrl.configuration)
    end = result.get("configuration_end", ctrl.configuration)
    by_instance = {name: InstanceCounters.model_validate(c) for name, c in result.get("instances", {}).items()}
    return EpisodeMeta(
        name=name,
        title=title,
        decider=player.cfg.decider,
        scenario=player.scenario,
        seed=seed,
        value_networks=player.networks,
        checkpoint=checkpoint,
        slow_path="off" if not player.slow_path else ("codex" if ctrl.llm_worker.use_codex_cli else "templates"),
        config=PlayConfigInfo(call_budget_sec=start.bounds.call_budget_sec, seed=player.cfg.seed, max_ticks=player.max_ticks),
        configuration_start=start,
        configuration_end=end,
        result=EpisodeResult(**{k: v for k, v in result.items() if k in EpisodeResult.model_fields}),
        cost=EpisodeCost(**result.get("cost", {})),
        misses=EpisodeMisses(**result.get("misses", {})),
        instances=by_instance,
        system2=system2 if system2 is not None else System2EpisodeSummary(enabled=player.cfg.enable_system2),
        first_tick=traces[0].tick if traces else 0,
        last_tick=traces[-1].tick if traces else 0,
        tick_count=len(traces),
        buttons=list(player.env.button_names),
        frames=FramesInfo(end_frame=end_frame),
        actions=_action_catalog(ctrl),
        files=files,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )


def finish_bundle(
    player: Player,
    out: Path,
    name: str,
    title: str,
    seed: int,
    result: Dict[str, Any],
    traces: Sequence[TickTrace],
    files: List[str],
    checkpoint: Optional[CheckpointInfo],
) -> EpisodeMeta:
    """Write the final proposals, the ledger, System 2's records, the end frame and `episode.json` for an episode just played into `out`."""
    # System 2's end-of-episode cycle (or a verdict) still in flight belongs to this episode: let it finish first.
    player.ctrl.wait_system2(SYSTEM2_WAIT_SEC)
    # record_macro_performance appends a fresh copy of a proposal each time its macro runs; keep the final ones.
    (out / "proposals.jsonl").write_text(
        "".join(p.model_dump_json() + "\n" for p in player.ctrl.logger.proposal_traces), encoding="utf-8"
    )
    save_ledger(player.ctrl.ledger, out / RELEVANCE_FILE)
    if not (out / HISTORY_FILE).is_file():
        (out / HISTORY_FILE).write_text("", encoding="utf-8")
    if not (out / REFLECTIONS_FILE).is_file():
        (out / REFLECTIONS_FILE).write_text("", encoding="utf-8")
    system2 = summarize(load_reflections((out / REFLECTIONS_FILE).read_text(encoding="utf-8")), enabled=player.cfg.enable_system2)
    end_frame = None
    if player.keeper.last is not None:
        _jpeg(player.keeper.last, out / "frames" / "end.jpg")
        end_frame = "frames/end.jpg"
    meta = episode_meta(player, name, title, seed, result, traces, files, checkpoint, end_frame, system2)
    (out / "episode.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return meta


def record_bundle(
    scenario: str,
    seed: int,
    out: Path,
    networks: Networks = "none",
    run_dir: Optional[Path] = None,
    max_ticks: int = 500,
    slow_path: bool = True,
    codex: bool = False,
    name: Optional[str] = None,
    title: Optional[str] = None,
    call_budget_sec: Optional[float] = None,
    exploration_level: Optional[ExplorationLevel] = None,
    transport: Optional[TransportFn] = None,
    api_key: Optional[str] = None,
    system2: bool = True,
    configuration_path: Optional[Path] = None,
    fresh_configuration: bool = False,
    decider: DeciderName = DECIDER,
) -> EpisodeMeta:
    """Play one seeded episode with the decider deciding and write it as a bundle in `out`."""
    store = RunStore(run_dir or default_run_dir(scenario))
    learner, model_path = load_networks(store, networks)
    _prepare_out_dir(out)
    player = build_player(
        scenario, seed, out, networks, store, learner, model_path, max_ticks, slow_path, codex,
        call_budget_sec, exploration_level, transport, api_key, system2, configuration_path, fresh_configuration,
        decider=decider,
    )
    try:
        result, traces = play_episode(player, seed)
    finally:
        player.ctrl.close()
    files, checkpoint = copy_run_files(player, out)
    return finish_bundle(
        player,
        out,
        name or out.name,
        title or default_title(scenario, networks, seed, decider),
        seed,
        result,
        traces,
        files,
        checkpoint,
    )


def _check_tick(tick: TickTrace, bundle: Path, meta: EpisodeMeta) -> List[str]:
    problems: List[str] = []
    expected = list(SENSE_NAMES) + [CENTRAL_NAME]
    if list(tick.instances) != expected:
        problems.append(f"tick {tick.tick}: instances {list(tick.instances)}, expected {expected}")
    for name, result in tick.instances.items():
        if not result.evidence:
            problems.append(f"tick {tick.tick}: {name} has no evidence text")
        if result.image_ref is not None and not (bundle / result.image_ref).is_file():
            problems.append(f"tick {tick.tick}: {name}'s image {result.image_ref} is missing")
    if tick.pick.kind == "missed":
        if tick.executed_action is not None:
            problems.append(f"tick {tick.tick}: the central missed but {tick.executed_action} was executed")
    elif tick.executed_action != tick.pick.action or tick.executed_action not in tick.available_actions:
        problems.append(f"tick {tick.tick}: executed {tick.executed_action}, but the pick was {tick.pick.action}")
    low, high = meta.configuration_start.version, meta.configuration_end.version
    if not low <= tick.configuration_version <= high:
        problems.append(f"tick {tick.tick}: configuration version {tick.configuration_version} outside {low}..{high}")
    frame = bundle / meta.frames.dir / f"{tick.tick:05d}.jpg"
    if not frame.is_file():
        problems.append(f"missing frame {frame.relative_to(bundle)}")
    return problems


def _check_reflections(path: Path, meta: EpisodeMeta) -> List[str]:
    """Every line of reflections.jsonl is one of System 2's records, and episode.json counts them right."""
    problems: List[str] = []
    records = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            records.extend(load_reflections(line))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{REFLECTIONS_FILE} line {i + 1}: {exc}")
    low, high = meta.configuration_start.version, meta.configuration_end.version
    for record in records:
        if isinstance(record, ReflectionTrace):
            made = len(record.reflectors) + (record.central is not None) + (record.history_test.calls if record.history_test else 0)
            if record.calls != made:
                problems.append(f"{REFLECTIONS_FILE}: {record.cycle_id} counts {record.calls} calls; its reflectors, central and test made {made}")
            if record.calls > meta.configuration_start.bounds.system2_calls_per_cycle:
                problems.append(f"{REFLECTIONS_FILE}: {record.cycle_id} made {record.calls} calls, over the bound")
            if not low <= record.configuration_version <= high:
                problems.append(f"{REFLECTIONS_FILE}: {record.cycle_id} ran at configuration version {record.configuration_version}, outside {low}..{high}")
    if meta.system2 is not None and not problems:
        counted = summarize(records, enabled=meta.system2.enabled)
        if counted != meta.system2:
            problems.append(f"episode.json system2 {meta.system2.model_dump()} does not match {REFLECTIONS_FILE} {counted.model_dump()}")
    return problems


def check_bundle(bundle: Path) -> List[str]:
    """Validate a bundle against the trace models; returns a list of problems (empty when it is valid)."""
    problems: List[str] = []
    try:
        raw = json.loads((bundle / "episode.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - every failure becomes a reported problem
        return [f"episode.json: {exc}"]
    if isinstance(raw, dict) and raw.get("schema_version") != TRACE_SCHEMA_VERSION:
        return [f"episode.json: schema_version {raw.get('schema_version')}, expected {TRACE_SCHEMA_VERSION}"]
    try:
        meta = EpisodeMeta.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        return [f"episode.json: {exc}"]
    if meta.result.finished_reason == NOT_SHIPPABLE:
        problems.append("episode.json: the episode ended with connection_lost (three central misses in a row); not shippable")
    ticks: List[TickTrace] = []
    for i, line in enumerate((bundle / "ticks.jsonl").read_text(encoding="utf-8").splitlines()):
        try:
            ticks.append(TickTrace.model_validate_json(line))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"ticks.jsonl line {i + 1}: {exc}")
    if len(ticks) != meta.tick_count:
        problems.append(f"ticks.jsonl has {len(ticks)} ticks, episode.json says {meta.tick_count}")
    for tick in ticks:
        problems.extend(_check_tick(tick, bundle, meta))
    proposals_path = bundle / "proposals.jsonl"
    if proposals_path.is_file():
        for i, line in enumerate(proposals_path.read_text(encoding="utf-8").splitlines()):
            try:
                ProposalTrace.model_validate_json(line)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"proposals.jsonl line {i + 1}: {exc}")
    for required in (HISTORY_FILE, RELEVANCE_FILE):
        if required not in meta.files:
            problems.append(f"episode.json does not list {required}")
    if meta.system2 is not None and REFLECTIONS_FILE not in meta.files:
        problems.append(f"episode.json counts System 2's records but does not list {REFLECTIONS_FILE}")
    for file_name in meta.files:
        path = bundle / file_name
        if not path.is_file():
            problems.append(f"episode.json lists {file_name}, which is missing")
            continue
        try:
            if file_name == "metrics.jsonl":
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        MetricsRow.model_validate_json(line)
            elif file_name == "evaluation.json":
                EvaluationSummary.model_validate_json(path.read_text(encoding="utf-8"))
            elif file_name == "trust.json":
                TrustFile.model_validate_json(path.read_text(encoding="utf-8"))
            elif file_name == "macros.json":
                MacroList.validate_json(path.read_text(encoding="utf-8"))
            elif file_name == RELEVANCE_FILE:
                RelevanceLedger.model_validate_json(path.read_text(encoding="utf-8"))
            elif file_name == HISTORY_FILE:
                records = [TickRecord.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if len(records) != meta.tick_count:
                    problems.append(f"{HISTORY_FILE} has {len(records)} ticks, episode.json says {meta.tick_count}")
            elif file_name == REFLECTIONS_FILE:
                problems.extend(_check_reflections(path, meta))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{file_name}: {exc}")
    return problems


def index_entry(name: str, meta: EpisodeMeta) -> BundleIndexEntry:
    """The line `index.json` gives the bundle named `name`."""
    return BundleIndexEntry(
        name=name,
        title=meta.title,
        scenario=meta.scenario,
        value_networks=meta.value_networks,
        seed=meta.seed,
        cleared=meta.result.cleared,
        died=meta.result.died,
        reward=meta.result.reward,
        ticks=meta.tick_count,
        kills=meta.result.kills,
        configuration_start=meta.configuration_start.version,
        configuration_end=meta.configuration_end.version,
        decider=meta.decider,
    )


def write_index(episodes_dir: Path) -> List[BundleIndexEntry]:
    """Write `index.json` listing every shippable schema-2 bundle under `episodes_dir`, by scenario,
    networks, seed and the configuration version it started from. Bundles of another schema version, and episodes that lost the connection, are left out."""
    entries = []
    for meta_path in sorted(episodes_dir.glob("*/episode.json")):
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != TRACE_SCHEMA_VERSION:
            continue
        meta = EpisodeMeta.model_validate(raw)
        if meta.result.finished_reason == NOT_SHIPPABLE:
            continue
        entries.append(index_entry(meta_path.parent.name, meta))
    order = {"none": 0, "best": 1, "latest": 2}
    entries.sort(key=lambda e: (e.scenario, order[e.value_networks], e.seed, e.configuration_start, e.name))
    (episodes_dir / "index.json").write_text(
        json.dumps({"schema_version": TRACE_SCHEMA_VERSION, "episodes": [e.model_dump() for e in entries]}, indent=2),
        encoding="utf-8",
    )
    return entries


def bundle_json_schema() -> Dict[str, Any]:
    """One JSON Schema document whose $defs hold every record a bundle contains, and the models inside them
    the web app reads by name (its TypeScript types are generated from this document)."""
    models = (
        EpisodeMeta,
        TickTrace,
        TickRecord,
        RelevanceLedger,
        ProposalTrace,
        BundleIndexEntry,
        MetricsRow,
        EvaluationSummary,
        TrustFile,
        ActionSpec,
        ReflectionTrace,
        TrialVerdictTrace,
        System2Note,
        Configuration,
        InstanceResult,
        HistoryTestResult,
        System2EpisodeSummary,
    )
    _, schema = models_json_schema(
        [(m, "serialization") for m in models],
        title="system1_doom episode bundle",
    )
    schema["description"] = (
        f"Generated by `python -m system1_doom.export --schema` from the pydantic models "
        f"(schema_version {TRACE_SCHEMA_VERSION}). Do not edit by hand."
    )
    return schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record episodes played by d1-ultra as bundles for the web app")
    parser.add_argument("--scenario", default="deadly_corridor.cfg", help="ViZDoom scenario config filename")
    parser.add_argument("--episodes", type=int, default=1, help="Episodes to record, seeds seed, seed+1, ...")
    parser.add_argument("--seed", type=int, default=7, help="Seed of the first episode (also System 1's draw seed)")
    parser.add_argument(
        "--networks", choices=["none", "best", "latest"], default="none", help="Value networks for the values evidence channel"
    )
    parser.add_argument("--run-dir", default=None, help="Run folder with trained networks (default: runs/<scenario name>)")
    parser.add_argument("--out", default=None, help="Bundle folder (default: bundles/<scenario>-<networks>-<seed>)")
    parser.add_argument("--name", default=None, help="Bundle name shown in the app (default: the folder name)")
    parser.add_argument("--title", default=None, help="Episode title shown in the app")
    parser.add_argument("--max-ticks", type=int, default=500, help="Decision cap per episode")
    parser.add_argument("--call-budget", type=float, default=None, help="Per-call budget in seconds for each d1-ultra call (default 5)")
    level = parser.add_mutually_exclusive_group()
    level.add_argument("--explore", dest="level", action="store_const", const="explore", help="Start at the explore level")
    level.add_argument("--exploit", dest="level", action="store_const", const="exploit", help="Start at the exploit level (default)")
    parser.add_argument("--codex", action="store_true", help="Let the slow path call the Codex CLI instead of templates")
    parser.add_argument("--no-slow-path", action="store_true", help="Switch the slow path off entirely")
    parser.add_argument("--no-system2", action="store_true", help="Switch System 2 off: the configuration stays as it starts")
    add_configuration_flags(parser)
    add_decider_flag(parser)
    parser.add_argument("--check", metavar="BUNDLE", default=None, help="Validate a bundle and exit")
    parser.add_argument("--index", metavar="DIR", default=None, help="Write DIR/index.json listing its bundles and exit")
    parser.add_argument("--schema", metavar="OUT.json", default=None, help="Write the bundle JSON Schema and exit")
    return parser


def main(argv: Optional[Sequence[str]] = None, transport: Optional[TransportFn] = None) -> int:
    """`transport` answers the decider's calls in tests; real recordings need the decider's key."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.schema:
        out = Path(args.schema)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bundle_json_schema(), indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out}")
        return 0
    if args.check:
        problems = check_bundle(Path(args.check))
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{args.check}: {'valid' if not problems else f'{len(problems)} problem(s)'}")
        return 1 if problems else 0
    if args.index:
        entries = write_index(Path(args.index))
        print(f"Indexed {len(entries)} bundle(s) in {Path(args.index) / 'index.json'}")
        return 0
    api_key = load_api_key(args.decider)
    if not api_key:
        if transport is None:
            print(no_key_message(args.decider), file=sys.stderr)
            return 2
        api_key = "test-transport"

    stem = Path(args.scenario).stem
    status_code = 0
    for i in range(args.episodes):
        seed = args.seed + i
        default_out = Path("bundles") / f"{stem}-{args.networks}-{seed}"
        if args.out is None:
            out = default_out
        else:
            out = Path(args.out) if args.episodes == 1 else Path(args.out) / default_out.name
        try:
            meta = record_bundle(
                scenario=args.scenario,
                seed=seed,
                out=out,
                networks=args.networks,
                run_dir=Path(args.run_dir) if args.run_dir else None,
                max_ticks=args.max_ticks,
                slow_path=not args.no_slow_path,
                codex=args.codex,
                name=args.name if args.episodes == 1 else None,
                title=args.title if args.episodes == 1 else None,
                call_budget_sec=args.call_budget,
                exploration_level=args.level,
                transport=transport,
                api_key=api_key,
                system2=not args.no_system2,
                # Each episode is its own controller: the first starts as asked, each next one from the
                # configuration the one before saved in the run folder, as serve's episodes carry on.
                configuration_path=Path(args.configuration) if args.configuration and i == 0 else None,
                fresh_configuration=args.fresh_configuration and i == 0,
                decider=args.decider,
            )
        except (FileNotFoundError, FileExistsError, ConfigurationFileError) as exc:
            print(exc, file=sys.stderr)
            return 2
        status = "cleared" if meta.result.cleared else ("died" if meta.result.died else "survived")
        system2 = meta.system2
        reflections = (
            f", System 2: {system2.cycles} cycles, {system2.tests} tests, {system2.trials_started} trials, {system2.calls} calls, ${system2.usd:.4f}"
            if system2 is not None and system2.enabled
            else ""
        )
        print(
            f"{out}: {meta.tick_count} ticks, reward {meta.result.reward:.1f}, {status}, "
            f"{meta.cost.calls} calls, ${meta.cost.usd:.4f}, {meta.misses.missed_ticks} missed ticks, "
            f"configuration version {meta.configuration_start.version} -> {meta.configuration_end.version}{reflections}"
        )
        if meta.result.finished_reason == NOT_SHIPPABLE:
            print(f"{out}: the connection to {args.decider} was lost (three central misses in a row); not shippable.", file=sys.stderr)
            status_code = 1
    return status_code


if __name__ == "__main__":
    raise SystemExit(main())
