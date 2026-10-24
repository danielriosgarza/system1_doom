from __future__ import annotations

import argparse
import json
import sys
import time
from system1_doom.controller import ControllerConfig, DoomDecisionController
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Liquid AI d1-ultra Doom Decision Controller")
    parser.add_argument("--scenario", default="deadly_corridor.cfg", help="ViZDoom scenario config filename")
    parser.add_argument(
        "--ticks",
        type=int,
        default=None,
        help="Control ticks to run, or the per-episode cap when --episodes is set",
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=0,
        help="Play complete episodes and report how many were cleared (use with --disable-d1 for a fast local run)",
    )
    parser.add_argument(
        "--mode",
        choices=["async_cached", "sync_d1"],
        default="sync_d1",
        help="Execution mode for Liquid AI d1-ultra",
    )
    parser.add_argument("--disable-d1", action="store_true", help="Run without calling Liquid AI d1-ultra API")
    parser.add_argument("--disable-slow-llm", action="store_true", help="Disable slow LLM worker")
    parser.add_argument("--visible", action="store_true", help="Show live 640x480 ViZDoom window on your display")
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Hide the side window of d1-ultra decisions and Codex recommendations",
    )
    parser.add_argument(
        "--step-delay-ms",
        type=int,
        default=None,
        help="Pause in ms after each game step. Defaults to 120ms when --visible is set, which is a bit slower than real time. Use 0 for a headless-speed run.",
    )
    parser.add_argument("--save-gif", default=None, help="Path to save split-screen HUD animated GIF (e.g. logs/run.gif)")
    parser.add_argument("--save-mp4", default=None, help="Path to save split-screen HUD MP4 video (e.g. logs/run.mp4)")
    parser.add_argument("--log-dir", default="logs", help="Directory for JSONL decision traces")
    parser.add_argument("--run-dir", default=None, help="Run folder with trained models (default: runs/<scenario name>)")
    parser.add_argument("--no-learned", action="store_true", help="Ignore trained models and play on heuristics only")
    parser.add_argument("--learn", action="store_true", help="Keep training between episodes (requires --episodes)")
    args = parser.parse_args()

    store = RunStore(args.run_dir or default_run_dir(args.scenario))
    learner = None
    if args.learn or (not args.no_learned and (store.best.is_file() or store.checkpoint.is_file())):
        try:
            learner = load_learner(store) if args.learn else load_play_learner(store)
        except ImportError:
            if args.learn:
                print(INSTALL_HINT, file=sys.stderr)
                raise SystemExit(2)
            print("PyTorch is not installed; playing on heuristics only.", file=sys.stderr)
        except ValueError as exc:
            if args.learn:
                print(f"{exc}\nRetrain with `python -m system1_doom.train --fresh`.", file=sys.stderr)
                raise SystemExit(2)
            print(f"{exc}\nPlaying on heuristics only.", file=sys.stderr)

    # Each reflex step advances 2 Doom tics. 120ms is about half speed, slow enough to follow aim and shots.
    delay_ms = args.step_delay_ms if args.step_delay_ms is not None else (120 if args.visible else 0)

    env = ViZDoomBridge(
        scenario=args.scenario,
        window_visible=args.visible,
        include_jpeg_frame=not args.disable_d1,
        step_delay_ms=delay_ms,
    )
    cfg = ControllerConfig(
        execution_mode=args.mode,
        enable_d1_ultra=not args.disable_d1,
        enable_slow_llm=not args.disable_slow_llm,
        tick_budget_sec=5.0 if args.mode == "sync_d1" else 0.04,
        log_dir=args.log_dir,
        show_dashboard=args.visible and not args.no_dashboard,
        exploration_floor=0.05 if args.learn else 0.0,
        record_experience=args.learn,
        record_frames=bool(args.save_gif or args.save_mp4),
    )
    ctrl = DoomDecisionController(env=env, config=cfg, learner=learner)
    ctrl.restore_macros(store.load_macros())
    learned_info = (
        {
            "model_file": str(store.checkpoint if args.learn or not store.best.is_file() else store.best),
            "episodes_trained": learner.episodes,
            "network_share": round(learner.network_share, 4),
            "learning_now": args.learn,
        }
        if learner is not None
        else None
    )
    try:
        saved_gif = None
        saved_mp4 = None
        if args.episodes > 0:
            max_ticks = args.ticks if args.ticks is not None else 500
            episode_results = []
            for episode_index in range(args.episodes):
                if episode_index > 0:
                    env.restart_episode()
                t0 = time.perf_counter()
                result = ctrl.run_episode(max_ticks=max_ticks)
                if args.learn and learner is not None:
                    row = learn_from_episode(ctrl, learner, store, result, args.scenario, time.perf_counter() - t0)
                    print(format_row(row), file=sys.stderr, flush=True)
                episode_results.append(
                    {
                        "episode": episode_index + 1,
                        "cleared": result["cleared"],
                        "finished": result["finished"],
                        "ticks": result["ticks"],
                        "reward": result["reward"],
                        "health": result["health"],
                        "armor": result["armor"],
                        "kills": result["kills"],
                        "actions_selected": result["actions"],
                    }
                )
            if args.save_gif:
                saved_gif = str(ctrl.recorder.save_gif(args.save_gif))
            if args.save_mp4:
                saved_mp4 = str(ctrl.recorder.save_mp4(args.save_mp4))
            summary = {
                "scenario": args.scenario,
                "mode": args.mode,
                "episodes": args.episodes,
                "episodes_cleared": sum(1 for item in episode_results if item["cleared"]),
                "learned_model": learned_info,
                "results": episode_results,
                "d1_ultra_calls": ctrl.d1_client.call_count,
                "d1_ultra_errors": ctrl.d1_client.error_count,
                "ticks_log": str(ctrl.logger.ticks_path),
                "proposals_log": str(ctrl.logger.proposals_path),
                "saved_gif": saved_gif,
                "saved_mp4": saved_mp4,
            }
        else:
            tick_count = args.ticks if args.ticks is not None else 15
            traces = ctrl.run_ticks(tick_count)
            saved_gif = str(ctrl.recorder.save_gif(args.save_gif)) if args.save_gif else None
            saved_mp4 = str(ctrl.recorder.save_mp4(args.save_mp4)) if args.save_mp4 else None
            summary = {
                "scenario": args.scenario,
                "mode": args.mode,
                "ticks_completed": len(traces),
                "learned_model": learned_info,
                "d1_ultra_calls": ctrl.d1_client.call_count,
                "d1_ultra_errors": ctrl.d1_client.error_count,
                "total_reward": round(sum(t.reward_outcome for t in traces), 2),
                "actions_selected": [t.selected_action for t in traces],
                "active_strategy_end": traces[-1].active_strategy if traces else None,
                "ticks_log": str(ctrl.logger.ticks_path),
                "proposals_log": str(ctrl.logger.proposals_path),
                "saved_gif": saved_gif,
                "saved_mp4": saved_mp4,
            }
        print(json.dumps(summary, indent=2))
    finally:
        ctrl.close()
        env.close()


if __name__ == "__main__":
    main()
