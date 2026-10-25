"""Train the value networks on episodes d1-ultra plays, resuming across runs.

    python -m system1_doom.train --scenario deadly_corridor.cfg --episodes 50
    python -m system1_doom.train --scenario deadly_corridor.cfg --evaluate 5

d1-ultra makes every decision (it needs LIQUID_API_KEY); the five value networks learn between
episodes from what it played, and serve the `values` evidence channel. Training is therefore a d1
cost too: about six calls per decision. The run folder also keeps the relevance ledger
(`relevance.json`), which every episode updates, and, with System 2 on (the default; `--no-system2`
switches it off), the configuration as System 2 changed it (`configuration.json`, saved at every change
and episode end), System 2's state (`system2.json`) and its records (`reflections.jsonl`).

Every entry point that plays starts from the run folder's `configuration.json` when it exists, so System
2's work carries across runs (and `system2.json` restores, its fingerprint matching); `--configuration
PATH` names another file, and `--fresh-configuration` starts from the design's version 1, forgetting the
saved configuration and System 2's state (`--fresh` implies it). `starting_configuration` decides which,
and each run says so in one line on stderr. Evaluation plays under that configuration with System 2 off,
so its episodes stay identical.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

from system1_doom.actions import ActionSpec
from system1_doom.charts import render_learning_curves, rolling_mean
from system1_doom.configuration import Configuration
from system1_doom.controller import NO_KEY_MESSAGE, ControllerConfig, DoomDecisionController
from system1_doom.d1_client import TransportFn, load_api_key
from system1_doom.vizdoom_env import ViZDoomBridge

if TYPE_CHECKING:
    from system1_doom.learning import Learner

INSTALL_HINT = (
    "Learning needs PyTorch and matplotlib. Install them with:\n"
    "  uv pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
    "  uv pip install matplotlib"
)
BEST_WINDOW = 20


class RunStore:
    """Files of one run: value networks, experience, admitted macros, the relevance ledger, the configuration,
    System 2's state, metrics, and charts."""

    def __init__(self, run_dir: Union[str, Path]) -> None:
        self.root = Path(run_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.checkpoint = self.root / "checkpoint.pt"
        self.best = self.root / "best.pt"
        self.replay = self.root / "replay.npz"
        self.macros = self.root / "macros.json"
        self.metrics = self.root / "metrics.jsonl"
        self.curves = self.root / "learning_curves.png"
        self.relevance = self.root / "relevance.json"
        self.configuration = self.root / "configuration.json"
        self.system2 = self.root / "system2.json"

    def reset(self) -> None:
        for path in (
            self.checkpoint, self.best, self.replay, self.macros, self.metrics, self.curves, self.relevance,
            self.configuration, self.system2,
        ):
            path.unlink(missing_ok=True)
        for name in ("ticks.jsonl", "proposals.jsonl", "history.jsonl", "reflections.jsonl"):
            (self.root / name).unlink(missing_ok=True)

    def load_metrics(self) -> List[Dict[str, Any]]:
        if not self.metrics.is_file():
            return []
        rows = []
        for line in self.metrics.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def append_metrics(self, row: Dict[str, Any]) -> None:
        with self.metrics.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def load_macros(self) -> List[ActionSpec]:
        if not self.macros.is_file():
            return []
        # ActionSpec validation re-checks primitives and bounds, so a hand-edited file cannot smuggle in an illegal action.
        return [ActionSpec.model_validate(item) for item in json.loads(self.macros.read_text(encoding="utf-8"))]

    def save_macros(self, specs: Sequence[ActionSpec]) -> None:
        self.macros.write_text(json.dumps([s.model_dump(mode="json") for s in specs], indent=2), encoding="utf-8")

    def forget_configuration(self) -> None:
        """`--fresh-configuration`: the saved configuration and System 2's state go, so both start over."""
        for path in (self.configuration, self.system2):
            path.unlink(missing_ok=True)


def default_run_dir(scenario: str) -> Path:
    return Path("runs") / Path(scenario).stem


class ConfigurationFileError(ValueError):
    """The configuration a run would start from does not exist or does not load."""


class StartingConfiguration:
    """The configuration a run starts from: a file and its version, or the design's version 1 (`path` None)."""

    def __init__(self, path: Optional[Path], version: int, saved: bool) -> None:
        self.path = path
        self.version = version
        # The run folder's own configuration.json: it already holds every macro admitted and retired, so the
        # run folder's macros.json is not merged into it (that would change it, and System 2 would start fresh).
        self.saved = saved

    @property
    def line(self) -> str:
        if self.path is None:
            return "configuration: the design's version 1"
        return f"configuration: {self.path} (version {self.version})"


def starting_configuration(store: RunStore, path: Optional[Union[str, Path]] = None, fresh: bool = False) -> StartingConfiguration:
    """Which configuration a run starts from: `path` when given; else, unless `fresh`, the run folder's saved
    `configuration.json` when it exists (System 2's `system2.json` then restores, its fingerprint matching);
    else the design's version 1. Reads only; `RunStore.forget_configuration` is the caller's, for runs that save."""
    chosen = Path(path) if path is not None else (store.configuration if not fresh and store.configuration.is_file() else None)
    if chosen is None:
        return StartingConfiguration(None, 1, False)
    if not chosen.is_file():
        raise ConfigurationFileError(f"{chosen}: no such configuration file")
    try:
        version = Configuration.load(chosen).version
    except Exception as exc:  # noqa: BLE001 - any failure to load is reported with its remedy
        raise ConfigurationFileError(
            f"{chosen} does not load as a configuration ({str(exc).splitlines()[0][:200]}); "
            "start from the design's version 1 with --fresh-configuration"
        ) from exc
    return StartingConfiguration(chosen, version, chosen.resolve() == store.configuration.resolve())


def add_configuration_flags(parser: argparse.ArgumentParser) -> None:
    """`--configuration PATH` and `--fresh-configuration`, shared by every entry point that plays."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--configuration", default=None, metavar="PATH",
        help="A configuration.json to start from (default: the run folder's configuration.json when it exists, else the design's version 1)",
    )
    group.add_argument(
        "--fresh-configuration", action="store_true",
        help="Start from the design's version 1: the run folder's saved configuration and System 2 state are forgotten",
    )


def load_learner(store: RunStore, overrides: Optional[Dict[str, Any]] = None, fresh: bool = False) -> "Learner":
    """Resume from the run folder, or start new networks. `overrides` only holds explicitly given settings."""
    from system1_doom.learning import Learner, LearnerConfig

    if fresh or not store.checkpoint.is_file():
        return Learner(LearnerConfig(**(overrides or {})))
    learner = Learner.load(store.checkpoint, overrides=overrides)
    if store.replay.is_file():
        learner.replay.load(store.replay)
    return learner


def load_play_learner(store: RunStore) -> Optional["Learner"]:
    """The strongest saved networks for watching or evaluation: best.pt if present, else the latest checkpoint."""
    from system1_doom.learning import Learner

    for path in (store.best, store.checkpoint):
        if path.is_file():
            return Learner.load(path)
    return None


def save_progress(store: RunStore, learner: "Learner", ctrl: DoomDecisionController) -> None:
    learner.save(store.checkpoint)
    learner.replay.save(store.replay)
    store.save_macros(ctrl.admitted_macros())


def learn_from_episode(
    ctrl: DoomDecisionController,
    learner: "Learner",
    store: RunStore,
    result: Dict[str, Any],
    scenario: str,
    episode_sec: float,
    train_steps: Optional[int] = None,
) -> Dict[str, Any]:
    """Train after an episode, record its metrics row, and persist the run."""
    t0 = time.perf_counter()
    losses = learner.train(train_steps)
    train_sec = time.perf_counter() - t0

    row = {
        "episode": learner.episodes,
        "scenario": scenario,
        "reward": float(result["reward"]),
        "kills": float(result["kills"]),
        "health": float(result["health"]),
        "armor": float(result["armor"]),
        "ticks": int(result["ticks"]),
        "cleared": bool(result["cleared"]),
        "finished": bool(result["finished"]),
        "died": bool(result.get("died", False)),
        "transitions": int(result.get("transitions", 0)),
        "replay_size": learner.replay.size,
        "network_share": round(learner.network_share, 4),
        "finished_reason": str(result.get("finished_reason", "")),
        "missed_ticks": int(result.get("misses", {}).get("missed_ticks", 0)),
        "cost_usd": round(float(result.get("cost", {}).get("usd", 0.0)), 6),
        "losses": losses,
        "macros": len(ctrl.admitted_macros()),
        "episode_sec": round(episode_sec, 2),
        "train_sec": round(train_sec, 2),
        "d1_calls": int(result.get("cost", {}).get("calls", 0)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    store.append_metrics(row)

    rewards = [r["reward"] for r in store.load_metrics()]
    rolling = float(rolling_mean(rewards, BEST_WINDOW)[-1]) if len(rewards) >= 5 else None
    improved = rolling is not None and rolling > learner.best_score
    if improved:
        learner.best_score = rolling
    save_progress(store, learner, ctrl)
    if improved:
        shutil.copyfile(store.checkpoint, store.best)
    row["best"] = improved
    return row


def format_row(row: Dict[str, Any]) -> str:
    status = "clear" if row["cleared"] else ("dead " if row["died"] else "alive")
    losses = row.get("losses") or {}
    module_losses = [v for k, v in losses.items() if k != "gate"]
    loss_txt = f"{sum(module_losses) / len(module_losses):6.3f}" if module_losses else "     -"
    return (
        f"ep {row['episode']:5d}  reward {row['reward']:9.1f}  kills {row['kills']:3.0f}  hp {row['health']:4.0f}  "
        f"{status}  missed {row.get('missed_ticks', 0):3d}  calls {row.get('d1_calls', 0):5d}  ${row.get('cost_usd', 0.0):.4f}  "
        f"loss {loss_txt}  ticks {row['ticks']:4d}  {row['episode_sec'] + row['train_sec']:5.1f}s"
        f"{'  * best' if row.get('best') else ''}"
    )


def summarize(rows: List[Dict[str, Any]], new_rows: int, store: RunStore) -> str:
    if not rows:
        return "No episodes recorded."
    k = max(1, min(len(rows) // 2, max(10, len(rows) // 10)))
    first, last = rows[:k], rows[-k:]

    def mean(items: List[Dict[str, Any]], key: str) -> float:
        return sum(float(r[key]) for r in items) / len(items)

    lines = [
        f"Run folder {store.root}: {len(rows)} episodes total, {new_rows} this session.",
        f"  Mean reward   first {k}: {mean(first, 'reward'):9.1f}   last {k}: {mean(last, 'reward'):9.1f}",
        f"  Success rate  first {k}: {100 * mean(first, 'cleared'):8.0f}%   last {k}: {100 * mean(last, 'cleared'):8.0f}%",
        f"  Replay {rows[-1]['replay_size']} transitions, {rows[-1]['macros']} admitted macros, "
        f"d1-ultra cost this run ${sum(float(r.get('cost_usd', 0.0)) for r in rows):.4f}.",
        f"  Charts: {store.curves}",
    ]
    return "\n".join(lines)


EVAL_SEED_BASE = 10_000


def evaluate(
    scenario: str,
    store: RunStore,
    episodes: int,
    max_ticks: int,
    transport: Optional[TransportFn] = None,
    api_key: Optional[str] = None,
    start: Optional[StartingConfiguration] = None,
) -> Dict[str, Dict[str, float]]:
    """Play identical seeded episodes with d1-ultra deciding, with no, the latest and the best value networks as evidence.

    Every contender plays under the same configuration (`start`, by default the run folder's saved one) with
    System 2 off and nothing saved, so the episodes differ only by the networks.
    """
    from system1_doom.learning import Learner

    start = start or starting_configuration(store)

    contenders: List[Any] = [("none", None)]
    for label, path in (("latest", store.checkpoint), ("best", store.best)):
        if path.is_file():
            contenders.append((label, Learner.load(path)))
    trained_episodes = max((model.episodes for _, model in contenders if model is not None), default=0)
    report: Dict[str, Dict[str, float]] = {}
    for label, model in contenders:
        env = ViZDoomBridge(scenario=scenario, window_visible=False)
        cfg = ControllerConfig(
            seed=EVAL_SEED_BASE, enable_slow_llm=False, log_dir=str(store.root / "eval" / label),
            configuration_path=str(start.path) if start.path else None,
        )
        ctrl = DoomDecisionController(env=env, config=cfg, learner=model, transport=transport, api_key=api_key)
        if not start.saved:
            ctrl.restore_macros(store.load_macros())
        results = []
        try:
            for i in range(episodes):
                env.restart_episode(seed=EVAL_SEED_BASE + i)
                results.append(ctrl.run_episode(max_ticks=max_ticks))
        finally:
            ctrl.close()
        n = max(1, len(results))
        report[label] = {
            "reward": round(sum(r["reward"] for r in results) / n, 2),
            "cleared": round(sum(1 for r in results if r["cleared"]) / n, 4),
            "survived": round(sum(1 for r in results if not r["died"]) / n, 4),
            "kills": round(sum(r["kills"] for r in results) / n, 2),
            "health": round(sum(r["health"] for r in results) / n, 2),
            "ticks": round(sum(r["ticks"] for r in results) / n, 1),
        }
    (store.root / "evaluation.json").write_text(
        json.dumps({"scenario": scenario, "episodes": episodes, "trained_episodes": trained_episodes, **report}, indent=2),
        encoding="utf-8",
    )
    return report


def format_evaluation(report: Dict[str, Dict[str, float]], scenario: str, episodes: int) -> str:
    lines = [
        f"Evaluation on {scenario}: {episodes} identical seeded episodes each, d1-ultra deciding, no learning.",
        f"  {'networks':12s}{'reward':>9s}{'cleared':>9s}{'survived':>10s}{'kills':>7s}{'health':>8s}{'ticks':>7s}",
    ]
    for label, m in report.items():
        lines.append(
            f"  {label:12s}{m['reward']:9.1f}{100 * m['cleared']:8.0f}%{100 * m['survived']:9.0f}%"
            f"{m['kills']:7.1f}{m['health']:8.1f}{m['ticks']:7.0f}"
        )
    if len(report) == 1:
        lines.append("  No checkpoint in this run folder yet; train first to compare.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train the value networks on episodes d1-ultra plays")
    parser.add_argument("--scenario", default="deadly_corridor.cfg", help="ViZDoom scenario config filename")
    parser.add_argument("--episodes", type=int, default=50, help="Episodes to play in this session")
    parser.add_argument("--max-ticks", type=int, default=500, help="Decision cap per episode")
    parser.add_argument("--run-dir", default=None, help="Run folder (default: runs/<scenario name>)")
    parser.add_argument(
        "--fresh", action="store_true", help="Delete the run folder's models, history, configuration and System 2 state first"
    )
    parser.add_argument("--train-steps", type=int, default=None, help="Gradient steps after each episode (default 200)")
    parser.add_argument(
        "--trust-count",
        type=float,
        default=None,
        help="Tries of an action in a situation at which the reported network share reaches 50%% (default 25)",
    )
    parser.add_argument("--chart-every", type=int, default=5, help="Redraw learning curves every N episodes")
    parser.add_argument("--seed", type=int, default=None, help="ViZDoom, network and System 1 draw seed")
    parser.add_argument("--call-budget", type=float, default=None, help="Per-call budget in seconds for each d1-ultra call (default 5)")
    level = parser.add_mutually_exclusive_group()
    level.add_argument("--explore", dest="level", action="store_const", const="explore", help="Play at the explore level")
    level.add_argument("--exploit", dest="level", action="store_const", const="exploit", help="Play at the exploit level (default)")
    parser.add_argument("--codex", action="store_true", help="Let the slow Codex worker propose new macros")
    parser.add_argument("--no-system2", action="store_true", help="Switch System 2 off: the configuration stays as it starts")
    add_configuration_flags(parser)
    parser.add_argument(
        "--evaluate",
        type=int,
        default=0,
        metavar="N",
        help="Skip training; play N identical seeded episodes with no, the latest and the best networks as evidence",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None, transport: Optional[TransportFn] = None) -> int:
    """`transport` answers d1-ultra calls in tests; real play needs LIQUID_API_KEY."""
    args = build_parser().parse_args(argv)
    try:
        from system1_doom.learning import CheckpointMismatch
        import matplotlib  # noqa: F401
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 2
    api_key = load_api_key()
    if not api_key:
        if transport is None:
            print(NO_KEY_MESSAGE, file=sys.stderr)
            return 2
        api_key = "test-transport"

    store = RunStore(args.run_dir or default_run_dir(args.scenario))
    fresh_configuration = args.fresh_configuration or args.fresh
    if args.evaluate > 0:
        try:
            start = starting_configuration(store, args.configuration, fresh_configuration)
        except ConfigurationFileError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(start.line, file=sys.stderr, flush=True)
        try:
            report = evaluate(args.scenario, store, args.evaluate, args.max_ticks, transport=transport, api_key=api_key, start=start)
        except CheckpointMismatch as exc:
            print(f"{exc}\nRetrain with --fresh.", file=sys.stderr)
            return 2
        print(format_evaluation(report, args.scenario, args.evaluate), flush=True)
        return 0
    if args.fresh:
        store.reset()
    elif fresh_configuration:
        store.forget_configuration()
    try:
        start = starting_configuration(store, args.configuration, fresh_configuration)
    except ConfigurationFileError as exc:
        print(exc, file=sys.stderr)
        return 2

    overrides: Dict[str, Any] = {}
    if args.train_steps is not None:
        overrides["train_steps"] = args.train_steps
    if args.trust_count is not None:
        overrides["trust_count"] = args.trust_count
    if args.seed is not None:
        overrides["seed"] = args.seed
    try:
        learner = load_learner(store, overrides, fresh=args.fresh)
    except CheckpointMismatch as exc:
        print(f"{exc}\nStart over with --fresh, or point --run-dir at a new folder.", file=sys.stderr)
        return 2

    env = ViZDoomBridge(scenario=args.scenario, window_visible=False, seed=args.seed)
    cfg = ControllerConfig(
        call_budget_sec=args.call_budget,
        seed=args.seed or 0,
        configuration_path=str(start.path) if start.path else None,
        exploration_level=args.level,
        enable_slow_llm=args.codex,
        log_dir=str(store.root),
        relevance_path=str(store.relevance),
        enable_system2=not args.no_system2,
        configuration_out=str(store.configuration),
        system2_state_path=str(store.system2),
        record_experience=True,
    )
    try:
        ctrl = DoomDecisionController(env=env, config=cfg, learner=learner, transport=transport, api_key=api_key)
    except Exception:
        env.close()
        raise
    if not start.saved:
        ctrl.restore_macros(store.load_macros())
    print(start.line, file=sys.stderr, flush=True)

    resumed = learner.episodes
    print(
        f"Training the value networks on {args.scenario} in {store.root}, d1-ultra deciding "
        f"({'resuming after episode ' + str(resumed) if resumed else 'fresh start'})",
        flush=True,
    )
    played = 0
    try:
        for i in range(args.episodes):
            if i > 0:
                env.restart_episode()
            t0 = time.perf_counter()
            result = ctrl.run_episode(max_ticks=args.max_ticks)
            row = learn_from_episode(ctrl, learner, store, result, args.scenario, time.perf_counter() - t0)
            played += 1
            print(format_row(row), flush=True)
            if played % max(1, args.chart_every) == 0:
                render_learning_curves(store.load_metrics(), store.curves, title=f"{Path(args.scenario).stem} training")
    except KeyboardInterrupt:
        learner.discard_episode()
        save_progress(store, learner, ctrl)
        print("\nInterrupted. Progress saved; run the same command to resume.", flush=True)
    finally:
        rows = store.load_metrics()
        render_learning_curves(rows, store.curves, title=f"{Path(args.scenario).stem} training")
        print(summarize(rows, played, store), flush=True)
        ctrl.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
