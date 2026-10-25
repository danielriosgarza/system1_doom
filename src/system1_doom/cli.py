"""Play ViZDoom with every decision made by d1-ultra instances.

    python -m system1_doom.cli --scenario basic.cfg --ticks 15
    python -m system1_doom.cli --scenario deadly_corridor.cfg --episodes 3 --visible

Play needs LIQUID_API_KEY (in the environment or a .env file): five senses and a central instance
decide every tick, so without the key there is nothing that could decide.

System 2 is on unless `--no-system2`: every 20 decisions and at each episode end it may change the
configuration (one trial at a time), saving it to the run folder's `configuration.json`, which
`--configuration` loads; its records go to `reflections.jsonl` in the log folder.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

from system1_doom.controller import NO_KEY_MESSAGE, ControllerConfig, DoomDecisionController
from system1_doom.d1_client import TransportFn, load_api_key
from system1_doom.train import (
    INSTALL_HINT,
    RunStore,
    default_run_dir,
    format_row,
    learn_from_episode,
    load_learner,
    load_play_learner,
)
from system1_doom.vizdoom_env import ViZDoomBridge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Play ViZDoom with d1-ultra making every decision")
    parser.add_argument("--scenario", default="deadly_corridor.cfg", help="ViZDoom scenario config filename")
    parser.add_argument(
        "--ticks",
        type=int,
        default=None,
        help="Decision cap: of the one episode played without --episodes (default 15), or per episode with it (default 500)",
    )
    parser.add_argument("--episodes", type=int, default=0, help="Play complete episodes and report how many were cleared")
    parser.add_argument("--call-budget", type=float, default=None, help="Per-call budget in seconds for each d1-ultra call (default 5)")
    level = parser.add_mutually_exclusive_group()
    level.add_argument("--explore", dest="level", action="store_const", const="explore", help="Start at the explore level")
    level.add_argument("--exploit", dest="level", action="store_const", const="exploit", help="Start at the exploit level (default)")
    parser.add_argument("--seed", type=int, default=None, help="ViZDoom seed, and System 1's seed for draws under explore")
    parser.add_argument("--configuration", default=None, help="A configuration.json to start from (default: the design's)")
    parser.add_argument("--disable-slow-llm", action="store_true", help="Disable the slow macro-proposal worker")
    parser.add_argument("--no-system2", action="store_true", help="Switch System 2 off: the configuration stays as it starts")
    parser.add_argument("--visible", action="store_true", help="Show live 640x480 ViZDoom window on your display")
    parser.add_argument("--no-dashboard", action="store_true", help="Hide the side window of the six instances")
    parser.add_argument(
        "--step-delay-ms",
        type=int,
        default=None,
        help="Pause in ms after each game step. Defaults to 120ms when --visible is set. Use 0 for a headless-speed run.",
    )
    parser.add_argument("--save-gif", default=None, help="Path to save split-screen HUD animated GIF (e.g. logs/run.gif)")
    parser.add_argument("--save-mp4", default=None, help="Path to save split-screen HUD MP4 video (e.g. logs/run.mp4)")
    parser.add_argument("--log-dir", default="logs", help="Directory for traces, history and frames")
    parser.add_argument("--run-dir", default=None, help="Run folder with trained networks and the ledger (default: runs/<scenario name>)")
    parser.add_argument("--no-learned", action="store_true", help="Do not load value networks (the values channel says so)")
    parser.add_argument("--learn", action="store_true", help="Keep training the value networks between episodes (requires --episodes)")
    return parser


def _episode_summary(index: int, result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "episode": index,
        "cleared": result["cleared"],
        "finished": result["finished"],
        "finished_reason": result["finished_reason"],
        "ticks": result["ticks"],
        "reward": result["reward"],
        "health": result["health"],
        "armor": result["armor"],
        "kills": result["kills"],
        "cost": result["cost"],
        "misses": result["misses"],
        "configuration_version": result["configuration_end"].version,
        "system2": result["system2"],
        "mean_tick_ms": round(sum(t.timing_ms.get("total", 0.0) for t in result["traces"]) / max(1, result["ticks"]), 1),
        "actions_executed": result["actions"],
    }


def main(argv: Optional[Sequence[str]] = None, transport: Optional[TransportFn] = None) -> int:
    """`transport` answers d1-ultra calls in tests; real play needs LIQUID_API_KEY."""
    args = build_parser().parse_args(argv)
    api_key = load_api_key()
    if not api_key:
        if transport is None:
            print(NO_KEY_MESSAGE, file=sys.stderr)
            return 2
        api_key = "test-transport"

    store = RunStore(args.run_dir or default_run_dir(args.scenario))
    learner = None
    if args.learn or (not args.no_learned and (store.best.is_file() or store.checkpoint.is_file())):
        try:
            learner = load_learner(store) if args.learn else load_play_learner(store)
        except ImportError:
            if args.learn:
                print(INSTALL_HINT, file=sys.stderr)
                return 2
            print("PyTorch is not installed; playing without value networks.", file=sys.stderr)
        except ValueError as exc:
            if args.learn:
                print(f"{exc}\nRetrain with `python -m system1_doom.train --fresh`.", file=sys.stderr)
                return 2
            print(f"{exc}\nPlaying without value networks.", file=sys.stderr)

    # Each reflex step advances 2 Doom tics. 120ms is about half speed, slow enough to follow aim and shots.
    delay_ms = args.step_delay_ms if args.step_delay_ms is not None else (120 if args.visible else 0)
    env = ViZDoomBridge(scenario=args.scenario, window_visible=args.visible, step_delay_ms=delay_ms, seed=args.seed)
    cfg = ControllerConfig(
        call_budget_sec=args.call_budget,
        seed=args.seed or 0,
        configuration_path=args.configuration,
        exploration_level=args.level,
        enable_slow_llm=not args.disable_slow_llm,
        log_dir=args.log_dir,
        relevance_path=str(store.relevance),
        enable_system2=not args.no_system2,
        configuration_out=str(store.configuration),
        system2_state_path=str(store.system2),
        show_dashboard=args.visible and not args.no_dashboard,
        record_experience=args.learn,
        record_frames=bool(args.save_gif or args.save_mp4),
    )
    try:
        ctrl = DoomDecisionController(env=env, config=cfg, learner=learner, transport=transport, api_key=api_key)
    except Exception:
        env.close()
        raise
    ctrl.restore_macros(store.load_macros())
    learned_info = (
        {
            "model_file": str(store.checkpoint if args.learn or not store.best.is_file() else store.best),
            "episodes_trained": learner.episodes,
            "learning_now": args.learn,
        }
        if learner is not None
        else None
    )
    try:
        episodes = max(1, args.episodes)
        max_ticks = args.ticks if args.ticks is not None else (500 if args.episodes > 0 else 15)
        results: List[Dict[str, Any]] = []
        for episode_index in range(episodes):
            if episode_index > 0:
                env.restart_episode()
            t0 = time.perf_counter()
            result = ctrl.run_episode(max_ticks=max_ticks)
            if args.learn and learner is not None:
                row = learn_from_episode(ctrl, learner, store, result, args.scenario, time.perf_counter() - t0)
                print(format_row(row), file=sys.stderr, flush=True)
            results.append(_episode_summary(episode_index + 1, result))
        ctrl.wait_system2(120.0)  # the end-of-episode cycle's calls belong in the summary
        saved_gif = str(ctrl.recorder.save_gif(args.save_gif)) if args.save_gif else None
        saved_mp4 = str(ctrl.recorder.save_mp4(args.save_mp4)) if args.save_mp4 else None
        counters = ctrl.counters()
        summary = {
            "scenario": args.scenario,
            "decider": "d1-ultra",
            "configuration_version": ctrl.configuration.version,
            "exploration_level": ctrl.configuration.exploration_level,
            "call_budget_sec": ctrl.configuration.bounds.call_budget_sec,
            "episodes": len(results),
            "episodes_cleared": sum(1 for item in results if item["cleared"]),
            "value_networks": learned_info,
            "results": results,
            "instances": {
                name: {
                    "calls": c.calls,
                    "answered": c.answered,
                    "misses": c.misses,
                    "retries": c.retries,
                    "mean_latency_ms": round(c.mean_latency_ms, 1),
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "cost": round(c.cost, 9),
                }
                for name, c in counters.items()
            },
            "ticks_log": str(ctrl.logger.ticks_path),
            "history_log": str(ctrl.history.path),
            "relevance": str(store.relevance),
            "proposals_log": str(ctrl.logger.proposals_path),
            "reflections_log": str(ctrl.logger.reflections_path) if ctrl.system2 is not None else None,
            "configuration": str(store.configuration) if ctrl.system2 is not None else None,
            "saved_gif": saved_gif,
            "saved_mp4": saved_mp4,
        }
        print(json.dumps(summary, indent=2))
    finally:
        ctrl.close()
    return 1 if any(r["finished_reason"] == "connection_lost" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
