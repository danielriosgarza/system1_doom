"""Record episodes as self-contained bundles for the web app, and check or describe the bundle format.

    python -m system1_doom.export --scenario deadly_corridor.cfg --episodes 1 --seed 7
    python -m system1_doom.export --scenario deadly_corridor.cfg --seed 7 --model best --out web/public/episodes/x
    python -m system1_doom.export --check web/public/episodes/x
    python -m system1_doom.export --index web/public/episodes
    python -m system1_doom.export --schema web/schema/bundle.schema.json

A bundle is one folder per episode:

    episode.json      what was played, with which brains, and how it ended (EpisodeMeta)
    ticks.jsonl       one TickTrace per control tick
    proposals.jsonl   one ProposalTrace per slow-path proposal, final state
    frames/00042.jpg  the 320x240 screen the controller saw when it decided tick 42
    frames/end.jpg    the screen after the last action
    metrics.jsonl, evaluation.json, macros.json   copied from the run folder when present
                      (MetricsRow per line, EvaluationSummary, a list of ActionSpec)
    trust.json        the loaded checkpoint's experience counts, when a model was loaded (TrustFile)
"""

from __future__ import annotations

import argparse
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
from system1_doom.controller import BUILTIN_ACTION_IDS, ControllerConfig, DoomDecisionController
from system1_doom.features import encode_action
from system1_doom.logger import TRACE_SCHEMA_VERSION, ProposalTrace, TickTrace
from system1_doom.state import WorldState
from system1_doom.train import RunStore, default_run_dir
from system1_doom.vizdoom_env import ViZDoomBridge

if TYPE_CHECKING:
    from system1_doom.learning import Learner

Model = Literal["heuristics", "best", "latest"]

FRAME_QUALITY = 80
COPIED_RUN_FILES = ("metrics.jsonl", "evaluation.json", "macros.json")
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


class BrainsInfo(BaseModel):
    """Which deciders were switched on for this episode."""

    model_config = ConfigDict(frozen=True)

    heuristics: bool = True
    learned_networks: bool
    d1_ultra: bool
    slow_path: Literal["off", "templates", "codex"]


class PlayConfigInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution_mode: str
    tick_budget_sec: float
    deterministic_arbiter: bool
    exploration_floor: float
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
    transitions: int = 0
    explored_steps: int = 0
    network_share: float = 0.0
    actions: List[str] = Field(default_factory=list)


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
    model: Model
    checkpoint: Optional[CheckpointInfo] = None
    brains: BrainsInfo
    config: PlayConfigInfo
    result: EpisodeResult
    first_tick: int
    last_tick: int
    tick_count: int
    buttons: List[str]
    frames: FramesInfo
    actions: Dict[str, ActionInfo]
    modules: Dict[str, str]
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
    network_share: float
    exploration_floor: float
    explored_steps: int = 0
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
    """`evaluation.json`: `train.evaluate`, the same seeded episodes played greedily by each brain."""

    model_config = ConfigDict(frozen=True)

    scenario: str
    episodes: int
    trained_episodes: int = 0
    heuristics: EvaluationScores
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
    model_config = ConfigDict(frozen=True)

    name: str
    title: str
    scenario: str
    model: Model
    seed: int
    cleared: bool
    died: bool
    reward: float
    ticks: int


def _jpeg(screen_buffer: np.ndarray, path: Path) -> None:
    arr = np.asarray(screen_buffer, dtype=np.uint8)
    if arr.ndim == 3 and arr.shape[0] in (1, 3, 4) and arr.shape[2] not in (1, 3, 4):
        arr = np.transpose(arr, (1, 2, 0))
    image = Image.fromarray(arr)
    if image.size != (320, 240):
        image = image.resize((320, 240), Image.Resampling.BILINEAR)
    image.save(path, format="JPEG", quality=FRAME_QUALITY)


class RecordingBridge(ViZDoomBridge):
    """A ViZDoom bridge that saves the screen each world state was built from, named by its tick.

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
        state = self.game.get_state()
        if state is not None and state.screen_buffer is not None:
            _jpeg(state.screen_buffer, self.frames_dir / f"{world_state.observation.tick:05d}.jpg")
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
        for a in ctrl.vocabulary.all_actions()
    }


def _load_model(store: RunStore, model: Model) -> Tuple[Optional["Learner"], Optional[Path]]:
    if model == "heuristics":
        return None, None
    from system1_doom.learning import Learner

    path = store.best if model == "best" else store.checkpoint
    if not path.is_file():
        raise FileNotFoundError(f"No {path.name} in {store.root}; train first or use --model heuristics.")
    return Learner.load(path), path


def _prepare_out_dir(out: Path) -> None:
    if out.exists():
        if any(out.iterdir()) and not (out / "episode.json").is_file():
            raise FileExistsError(f"{out} exists and is not a bundle; refusing to overwrite it.")
        shutil.rmtree(out)
    (out / "frames").mkdir(parents=True)


@dataclass
class Player:
    """Everything that plays episodes, built once: the run folder, the brain, the bridge and the controller."""

    scenario: str
    model: Model
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
    model: Model,
    store: RunStore,
    learner: Optional["Learner"],
    model_path: Optional[Path],
    max_ticks: int = 500,
    d1: bool = False,
    slow_path: bool = True,
    codex: bool = False,
    deterministic: bool = False,
) -> Player:
    """The bridge and controller a bundle is played with, writing its frames and logs into `out`."""
    env = RecordingBridge(
        frames_dir=out / "frames",
        scenario=scenario,
        window_visible=False,
        include_jpeg_frame=d1,
        seed=seed,
    )
    cfg = ControllerConfig(
        execution_mode="async_cached",
        enable_d1_ultra=d1,
        enable_slow_llm=slow_path,
        use_codex_cli=codex,
        tick_budget_sec=0.04,
        log_dir=str(out),
        deterministic_arbiter=deterministic,
        exploration_floor=0.0,
        record_frames=True,
    )
    ctrl = DoomDecisionController(env=env, config=cfg, learner=learner)
    keeper = LastFrameKeeper()
    ctrl.recorder = keeper  # type: ignore[assignment]
    ctrl.restore_macros(store.load_macros())
    return Player(scenario, model, max_ticks, slow_path, store, learner, model_path, env, cfg, ctrl, keeper)


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
    files = ["episode.json", "ticks.jsonl", "proposals.jsonl"]
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


def default_title(scenario: str, model: Model, seed: int) -> str:
    stem = Path(scenario).stem
    return f"{stem.replace('_', ' ')}, {'heuristics only' if model == 'heuristics' else model + ' checkpoint'}, seed {seed}"


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
) -> EpisodeMeta:
    """`episode.json` for an episode played by `player`; the action catalog is the vocabulary as it is now."""
    ctrl, cfg = player.ctrl, player.cfg
    return EpisodeMeta(
        name=name,
        title=title,
        scenario=player.scenario,
        seed=seed,
        model=player.model,
        checkpoint=checkpoint,
        brains=BrainsInfo(
            learned_networks=player.learner is not None,
            d1_ultra=ctrl.d1_client.enabled,
            slow_path="off" if not player.slow_path else ("codex" if ctrl.llm_worker.use_codex_cli else "templates"),
        ),
        config=PlayConfigInfo(
            execution_mode=cfg.execution_mode,
            tick_budget_sec=cfg.tick_budget_sec,
            deterministic_arbiter=cfg.deterministic_arbiter,
            exploration_floor=cfg.exploration_floor,
            max_ticks=player.max_ticks,
        ),
        result=EpisodeResult(**result),
        first_tick=traces[0].tick if traces else 0,
        last_tick=traces[-1].tick if traces else 0,
        tick_count=len(traces),
        buttons=list(player.env.button_names),
        frames=FramesInfo(end_frame=end_frame),
        actions=_action_catalog(ctrl),
        modules={n: m.question_prompt for n, m in ctrl.module_evaluator.modules.items()},
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
    """Write the final proposals, the end frame and `episode.json` for an episode just played into `out`."""
    # record_macro_performance appends a fresh copy of a proposal each time its macro runs; keep the final ones.
    (out / "proposals.jsonl").write_text(
        "".join(p.model_dump_json() + "\n" for p in player.ctrl.logger.proposal_traces), encoding="utf-8"
    )
    end_frame = None
    if player.keeper.last is not None:
        _jpeg(player.keeper.last, out / "frames" / "end.jpg")
        end_frame = "frames/end.jpg"
    meta = episode_meta(player, name, title, seed, result, traces, files, checkpoint, end_frame)
    (out / "episode.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return meta


def record_bundle(
    scenario: str,
    seed: int,
    out: Path,
    model: Model = "heuristics",
    run_dir: Optional[Path] = None,
    max_ticks: int = 500,
    d1: bool = False,
    slow_path: bool = True,
    codex: bool = False,
    deterministic: bool = False,
    name: Optional[str] = None,
    title: Optional[str] = None,
) -> EpisodeMeta:
    """Play one seeded episode and write it as a bundle in `out`."""
    store = RunStore(run_dir or default_run_dir(scenario))
    learner, model_path = _load_model(store, model)
    _prepare_out_dir(out)
    player = build_player(
        scenario, seed, out, model, store, learner, model_path, max_ticks, d1, slow_path, codex, deterministic
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
        title or default_title(scenario, model, seed),
        seed,
        result,
        traces,
        files,
        checkpoint,
    )


def check_bundle(bundle: Path) -> List[str]:
    """Validate a bundle against the trace models; returns a list of problems (empty when it is valid)."""
    problems: List[str] = []
    try:
        meta = EpisodeMeta.model_validate_json((bundle / "episode.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - every failure becomes a reported problem
        return [f"episode.json: {exc}"]
    if meta.schema_version != TRACE_SCHEMA_VERSION:
        problems.append(f"episode.json: schema_version {meta.schema_version}, expected {TRACE_SCHEMA_VERSION}")
    ticks: List[TickTrace] = []
    for i, line in enumerate((bundle / "ticks.jsonl").read_text(encoding="utf-8").splitlines()):
        try:
            ticks.append(TickTrace.model_validate_json(line))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"ticks.jsonl line {i + 1}: {exc}")
    if len(ticks) != meta.tick_count:
        problems.append(f"ticks.jsonl has {len(ticks)} ticks, episode.json says {meta.tick_count}")
    for tick in ticks:
        frame = bundle / meta.frames.dir / f"{tick.tick:05d}.jpg"
        if not frame.is_file():
            problems.append(f"missing frame {frame.relative_to(bundle)}")
        if tick.state is None or tick.arbiter is None or tick.outcome is None:
            problems.append(f"tick {tick.tick}: missing state, arbiter or outcome detail")
    proposals_path = bundle / "proposals.jsonl"
    if proposals_path.is_file():
        for i, line in enumerate(proposals_path.read_text(encoding="utf-8").splitlines()):
            try:
                ProposalTrace.model_validate_json(line)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"proposals.jsonl line {i + 1}: {exc}")
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
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{file_name}: {exc}")
    return problems


def index_entry(name: str, meta: EpisodeMeta) -> BundleIndexEntry:
    """The line `index.json` gives the bundle named `name`."""
    return BundleIndexEntry(
        name=name,
        title=meta.title,
        scenario=meta.scenario,
        model=meta.model,
        seed=meta.seed,
        cleared=meta.result.cleared,
        died=meta.result.died,
        reward=meta.result.reward,
        ticks=meta.tick_count,
    )


def write_index(episodes_dir: Path) -> List[BundleIndexEntry]:
    """Write `index.json` listing every bundle under `episodes_dir`, heuristics first."""
    entries = []
    for meta_path in sorted(episodes_dir.glob("*/episode.json")):
        meta = EpisodeMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
        entries.append(index_entry(meta_path.parent.name, meta))
    order = {"heuristics": 0, "best": 1, "latest": 2}
    entries.sort(key=lambda e: (e.scenario, order[e.model], e.seed))
    (episodes_dir / "index.json").write_text(
        json.dumps({"schema_version": TRACE_SCHEMA_VERSION, "episodes": [e.model_dump() for e in entries]}, indent=2),
        encoding="utf-8",
    )
    return entries


def bundle_json_schema() -> Dict[str, Any]:
    """One JSON Schema document whose $defs hold every record a bundle contains."""
    models = (EpisodeMeta, TickTrace, ProposalTrace, BundleIndexEntry, MetricsRow, EvaluationSummary, TrustFile, ActionSpec)
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
    parser = argparse.ArgumentParser(description="Record controller episodes as bundles for the web app")
    parser.add_argument("--scenario", default="deadly_corridor.cfg", help="ViZDoom scenario config filename")
    parser.add_argument("--episodes", type=int, default=1, help="Episodes to record, seeds seed, seed+1, ...")
    parser.add_argument("--seed", type=int, default=7, help="Seed of the first episode")
    parser.add_argument("--model", choices=["heuristics", "best", "latest"], default="heuristics")
    parser.add_argument("--run-dir", default=None, help="Run folder with trained models (default: runs/<scenario name>)")
    parser.add_argument("--out", default=None, help="Bundle folder (default: bundles/<scenario>-<model>-<seed>)")
    parser.add_argument("--name", default=None, help="Bundle name shown in the app (default: the folder name)")
    parser.add_argument("--title", default=None, help="Episode title shown in the app")
    parser.add_argument("--max-ticks", type=int, default=500, help="Decision cap per episode")
    parser.add_argument("--d1", action="store_true", help="Use Liquid AI d1-ultra (needs LIQUID_API_KEY)")
    parser.add_argument("--codex", action="store_true", help="Let the slow path call the Codex CLI instead of templates")
    parser.add_argument("--no-slow-path", action="store_true", help="Switch the slow path off entirely")
    parser.add_argument("--deterministic", action="store_true", help="Always take the arbiter's top-scored action")
    parser.add_argument("--check", metavar="BUNDLE", default=None, help="Validate a bundle and exit")
    parser.add_argument("--index", metavar="DIR", default=None, help="Write DIR/index.json listing its bundles and exit")
    parser.add_argument("--schema", metavar="OUT.json", default=None, help="Write the bundle JSON Schema and exit")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
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

    stem = Path(args.scenario).stem
    for i in range(args.episodes):
        seed = args.seed + i
        default_out = Path("bundles") / f"{stem}-{args.model}-{seed}"
        if args.out is None:
            out = default_out
        else:
            out = Path(args.out) if args.episodes == 1 else Path(args.out) / default_out.name
        try:
            meta = record_bundle(
                scenario=args.scenario,
                seed=seed,
                out=out,
                model=args.model,
                run_dir=Path(args.run_dir) if args.run_dir else None,
                max_ticks=args.max_ticks,
                d1=args.d1,
                slow_path=not args.no_slow_path,
                codex=args.codex,
                deterministic=args.deterministic,
                name=args.name if args.episodes == 1 else None,
                title=args.title if args.episodes == 1 else None,
            )
        except (FileNotFoundError, FileExistsError) as exc:
            print(exc, file=sys.stderr)
            return 2
        status = "cleared" if meta.result.cleared else ("died" if meta.result.died else "survived")
        print(f"{out}: {meta.tick_count} ticks, reward {meta.result.reward:.1f}, {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
