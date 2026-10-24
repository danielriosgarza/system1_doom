"""Train the controller's learned modules over many episodes, resuming across runs.

    python -m system1_doom.train --scenario deadly_corridor.cfg --episodes 200
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
from system1_doom.controller import ControllerConfig, DoomDecisionController
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
    """Files of one training run: models, experience, admitted macros, metrics, and charts."""

    def __init__(self, run_dir: Union[str, Path]) -> None:
        self.root = Path(run_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.checkpoint = self.root / "checkpoint.pt"
        self.best = self.root / "best.pt"
        self.replay = self.root / "replay.npz"
        self.macros = self.root / "macros.json"
        self.metrics = self.root / "metrics.jsonl"
        self.curves = self.root / "learning_curves.png"

    def reset(self) -> None:
        for path in (self.checkpoint, self.best, self.replay, self.macros, self.metrics, self.curves):
            path.unlink(missing_ok=True)
        for name in ("ticks.jsonl", "proposals.jsonl"):
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


def default_run_dir(scenario: str) -> Path:
    return Path("runs") / Path(scenario).stem


def exploration_schedule(episode_index: int, start: float, end: float, decay_episodes: int) -> float:
    if decay_episodes <= 0:
        return end
    frac = min(1.0, max(0.0, episode_index / decay_episodes))
    return start + (end - start) * frac


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
    """The strongest saved model for watching or evaluation: best.pt if present, else the latest checkpoint."""
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
        "network_share": round(float(result.get("network_share", 0.0)), 4),
        "exploration_floor": round(ctrl.exploration_floor, 4),
        "explored_steps": int(result.get("explored_steps", 0)),
        "losses": losses,
        "macros": len(ctrl.admitted_macros()),
        "episode_sec": round(episode_sec, 2),
        "train_sec": round(train_sec, 2),
        "d1_calls": ctrl.d1_client.call_count,
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
        f"{status}  net {100 * row['network_share']:3.0f}%  explore {row['exploration_floor']:.2f}  "
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
        f"  Network share now {100 * rows[-1]['network_share']:.0f}%, replay {rows[-1]['replay_size']} transitions, "
        f"{rows[-1]['macros']} admitted macros.",
        f"  Charts: {store.curves}",
    ]
    return "\n".join(lines)


EVAL_SEED_BASE = 10_000


def evaluate(scenario: str, store: RunStore, episodes: int, max_ticks: int) -> Dict[str, Dict[str, float]]:
    """Play identical seeded episodes greedily, with and without the trained networks."""
    from system1_doom.learning import Learner

    contenders: List[Any] = [("heuristics", None)]
    for label, path in (("latest", store.checkpoint), ("best", store.best)):
        if path.is_file():
            contenders.append((label, Learner.load(path)))
    trained_episodes = max((model.episodes for _, model in contenders if model is not None), default=0)
    report: Dict[str, Dict[str, float]] = {}
    for label, model in contenders:
        env = ViZDoomBridge(scenario=scenario, window_visible=False, include_jpeg_frame=False)
        cfg = ControllerConfig(
            execution_mode="async_cached",
            enable_d1_ultra=False,
            enable_slow_llm=False,
            tick_budget_sec=0.04,
            log_dir=str(store.root / "eval"),
            deterministic_arbiter=True,
        )
        ctrl = DoomDecisionController(env=env, config=cfg, learner=model)
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
        f"Evaluation on {scenario}: {episodes} identical seeded episodes each, no exploration, no learning.",
        f"  {'':12s}{'reward':>9s}{'cleared':>9s}{'survived':>10s}{'kills':>7s}{'health':>8s}{'ticks':>7s}",
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
    parser = argparse.ArgumentParser(description="Train the Doom controller's learned decision modules")
    parser.add_argument("--scenario", default="deadly_corridor.cfg", help="ViZDoom scenario config filename")
    parser.add_argument("--episodes", type=int, default=100, help="Episodes to play in this session")
    parser.add_argument("--max-ticks", type=int, default=500, help="Decision cap per episode")
    parser.add_argument("--run-dir", default=None, help="Run folder (default: runs/<scenario name>)")
    parser.add_argument("--fresh", action="store_true", help="Delete the run folder's models and history first")
    parser.add_argument("--train-steps", type=int, default=None, help="Gradient steps after each episode (default 200)")
    parser.add_argument(
        "--trust-count",
        type=float,
        default=None,
        help="Tries of an action in a situation before its network gets 50%% weight (default 25)",
    )
    parser.add_argument("--explore-start", type=float, default=0.6)
    parser.add_argument("--explore-end", type=float, default=0.05)
    parser.add_argument("--explore-decay", type=int, default=100, help="Episodes to decay exploration over")
    parser.add_argument("--chart-every", type=int, default=5, help="Redraw learning curves every N episodes")
    parser.add_argument("--seed", type=int, default=None, help="ViZDoom and network seed")
    parser.add_argument("--d1", action="store_true", help="Use Liquid AI d1-ultra (async cached) while training")
    parser.add_argument("--codex", action="store_true", help="Let the slow Codex worker propose new macros")
    parser.add_argument(
        "--evaluate",
        type=int,
        default=0,
        metavar="N",
        help="Skip training; compare trained networks against heuristics on N identical seeded episodes",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from system1_doom.learning import CheckpointMismatch
        import matplotlib  # noqa: F401
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 2

    store = RunStore(args.run_dir or default_run_dir(args.scenario))
    if args.evaluate > 0:
        try:
            report = evaluate(args.scenario, store, args.evaluate, args.max_ticks)
        except CheckpointMismatch as exc:
            print(f"{exc}\nRetrain with --fresh.", file=sys.stderr)
            return 2
        print(format_evaluation(report, args.scenario, args.evaluate), flush=True)
        return 0
    if args.fresh:
        store.reset()

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

    env = ViZDoomBridge(
        scenario=args.scenario,
        window_visible=False,
        include_jpeg_frame=args.d1,
        seed=args.seed,
    )
    cfg = ControllerConfig(
        execution_mode="async_cached",
        enable_d1_ultra=args.d1,
        enable_slow_llm=args.codex,
        tick_budget_sec=0.04,
        log_dir=str(store.root),
        record_experience=True,
    )
    ctrl = DoomDecisionController(env=env, config=cfg, learner=learner)
    ctrl.restore_macros(store.load_macros())

    resumed = learner.episodes
    print(
        f"Training on {args.scenario} in {store.root} "
        f"({'resuming after episode ' + str(resumed) if resumed else 'fresh start'}, "
        f"network share {100 * learner.network_share:.0f}%)",
        flush=True,
    )
    played = 0
    try:
        for i in range(args.episodes):
            if i > 0:
                env.restart_episode()
            ctrl.exploration_floor = exploration_schedule(
                learner.episodes, args.explore_start, args.explore_end, args.explore_decay
            )
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
