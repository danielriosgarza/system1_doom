"""The rule tree's command line.

  python -m system1_doom.ruletree show   --tree general-11
  python -m system1_doom.ruletree eval   RUN --tree general-11 --seeds 9-19,40-59
  python -m system1_doom.ruletree eval   RUN --tree general-11 --seeds 9-19 --decider laya
  python -m system1_doom.ruletree play   RUN --tree general-11 --seed 9
  python -m system1_doom.ruletree realtime RUN --seeds 9-19 --decider laya --model ruletree-kev-v1 --lag wall
  python -m system1_doom.ruletree loop   RUN --tree general-9 --writer codex --train 9-19 --held 20-39
  python -m system1_doom.ruletree rtloop RUN --tree realtime-5 --writer codex --decider kev --ahead --lag 7
  python -m system1_doom.ruletree check  RUN PROPOSAL.json
  python -m system1_doom.ruletree gate   RUN PROPOSAL.json --seeds 9-19
  python -m system1_doom.ruletree commit RUN PROPOSAL.json
  python -m system1_doom.ruletree finish RUN OUT

RUN is a folder (see `run.py`); it starts from `--tree` (a shipped tree's name or a tree folder) the first time;
`play` and `eval` start it from general-11 when no tree is named.
`realtime` plays the seeds without holding the game for the answers (realtime.py): `--lag wall` on the wall clock,
one game at a time, or `--lag N` with every action started N tics after the state it was decided from (`--lag 7-52`:
a lag drawn from 7 to 52 tics for each decision).
`check` tests a proposal against a game of the run; `gate` checks it, then plays the seeds with and without it;
`commit` checks it and, if it passed, adds it to the run's tree. `finish` copies the run's tree and record into a
tree folder of its own. Jev is reached with TYPESAFE_API_KEY from the environment or `.env`; without it every
command but `show` and `finish` stops with exit code 2. `--decider laya` asks Laya instead, the open-weight model
served on this machine by `laya-serve` (at `--endpoint`, http://127.0.0.1:8000/v1/systemone by default), which
needs no key unless the server was started with LAYA_API_KEY; Laya reads the state text and not the screen.
`--decider kev` asks Kev the same way, served on this machine by `python -m kev.serve` (http://127.0.0.1:8008 by
default; KEV_API_KEY only if the server has one).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from system1_doom.d1_client import D1UltraClient, decider_of, load_api_key

from .check import ProposalError, check, commit
from .gate import gate
from .loop import ATTEMPTS, run_loop
from .realtime import AIMS, CADENCES, FILLS, REFLEX, TRACKS, evaluate
from .rtloop import run_rt_loop
from .run import Run
from .tree import DEFAULT_TREE, Proposal, load_tree, shipped_trees, tree_lines
from .walk import DEFAULT_BUDGET
from .writers import writer_named


def parse_seeds(spec: str) -> List[int]:
    """`9-19`, `9,12,15` or `9-19,40-59`."""
    seeds: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = map(int, part.split("-"))
            seeds += range(lo, hi + 1)
        elif part:
            seeds.append(int(part))
    return seeds


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m system1_doom.ruletree", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show", help="print a tree")
    show.add_argument("--tree", default=DEFAULT_TREE,
                      help=f"a tree folder, or a shipped tree: {', '.join(shipped_trees())} (default {DEFAULT_TREE})")
    for name, help_ in (("play", "play one seed"), ("eval", "play seeds once each, in parallel")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("run")
        p.add_argument("--tree", help=f"the tree to start the run from, the first time (default {DEFAULT_TREE})")
        if name == "play":
            p.add_argument("--seed", type=int, required=True)
        else:
            p.add_argument("--seeds", required=True)
    rt = sub.add_parser("realtime", help="play seeds while the game goes on during each decision")
    rt.add_argument("run")
    rt.add_argument("--tree", help=f"the tree to start the run from, the first time (default {DEFAULT_TREE})")
    rt.add_argument("--seeds", required=True)
    rt.add_argument("--lag", default="wall", help="wall (the wall clock, one game at a time), a number of tics, or a range "
                                                  "LO-HI drawn afresh for each decision")
    rt.add_argument("--fill", choices=FILLS, default="hold", help="the keys between the end of one action and the start "
                                                                   "of the next, when a decision takes over 8 tics")
    rt.add_argument("--cadence", choices=CADENCES, default="pipeline", help="ask every 8 tics while the last action plays "
                    "(pipeline), or once it has played (sequential)")
    rt.add_argument("--predict", action="store_true", help="shift the state's angles by the turn still to come before "
                                                           "the answer is in (with pipeline)")
    rt.add_argument("--track", nargs="?", const="screen", choices=TRACKS,
                    help="a helper turns toward the focus every tic, the tree choosing what to aim at and what to do "
                         "(with pipeline): screen (the default) sees only what the player sees, `--reflex` tics late; "
                         "engine reads every enemy's position from the engine, on screen or not (not a fair player)")
    rt.add_argument("--keep-text", action="store_true", help="keep each decision's state text in its game, for training "
                                                             "data (teach.py reads RUN/realtime/ too)")
    rt.add_argument("--aim", choices=AIMS, default="band", help="with --track screen, turn until the focus is within 3 "
                    "degrees (band, the default) or until the crosshair is on its label (box)")
    rt.add_argument("--reflex", type=int, default=REFLEX, help=f"tics the screen helper sees late (default {REFLEX})")
    rt.add_argument("--label", default="", help="a prefix for the games' files, to keep several settings in one run")
    rtl = sub.add_parser("rtloop", help="run the soft loop on real-time games (rtloop.py)")
    rtl.add_argument("run")
    rtl.add_argument("--tree", help="the tree to start the run from, the first time")
    rtl.add_argument("--writer", choices=("codex", "claude", "file"), default="codex")
    rtl.add_argument("--writer-cmd", help="the writer's command, when it differs from the default ({out}: its answer file)")
    rtl.add_argument("--train", default="9-19")
    rtl.add_argument("--held", default="20-39")
    rtl.add_argument("--rounds", type=int, default=8)
    rtl.add_argument("--attempts", type=int, default=ATTEMPTS)
    rtl.add_argument("--lag", type=int, default=7, help="tics from a state to its action (default 7, Laya's)")
    rtl.add_argument("--reflex", type=int, default=REFLEX, help=f"tics the helper sees late (default {REFLEX})")
    rtl.add_argument("--aim", choices=AIMS, default="box", help="how the helper aims (default box)")
    rtl.add_argument("--margin", type=int, default=1, help="more training seeds a rule must clear to pass the gate "
                     "(default 1, which also passes as many with the failed game further on)")
    rtl.add_argument("--monitor", default="", help="seeds never trained on, played after each commit")
    loop = sub.add_parser("loop", help="run the soft loop")
    loop.add_argument("run")
    loop.add_argument("--tree", help="the tree to start the run from, the first time")
    loop.add_argument("--writer", choices=("codex", "claude", "file"), default="codex")
    loop.add_argument("--writer-cmd", help="the writer's command, when it differs from the default ({out}: its answer file)")
    loop.add_argument("--train", default="9-19")
    loop.add_argument("--held", default="20-39")
    loop.add_argument("--rounds", type=int, default=12)
    loop.add_argument("--attempts", type=int, default=ATTEMPTS)
    for name, help_ in (("check", "check a proposal"), ("gate", "check a proposal, then gate it"), ("commit", "check a proposal and add it")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("run")
        p.add_argument("proposal")
        if name == "gate":
            p.add_argument("--seeds", default="9-19")
    finish = sub.add_parser("finish", help="copy a run's tree and record into a tree folder")
    finish.add_argument("run")
    finish.add_argument("out")
    for p in sub.choices.values():
        if p.prog.split()[-1] != "show":
            p.add_argument("--workers", type=int, default=6, help="games played at once")
            p.add_argument("--decider", choices=("jev", "laya", "kev"), default="jev",
                           help="the decision model that answers every question: jev (TypeSafe; the default), or laya or "
                                "kev (open weights, served on this machine)")
            p.add_argument("--model", help="the decider's model (default: jev-latest for Jev, the english checkpoint for Laya, "
                                           "kev-latest for Kev)")
            p.add_argument("--endpoint", help="the decider's System One URL, when it differs from the default")
            p.add_argument("--budget", type=float, default=DEFAULT_BUDGET,
                           help=f"seconds a question may take before it is a miss (default {DEFAULT_BUDGET:g})")
            p.add_argument("--ahead", action="store_true",
                           help="ask the questions the walk may ask next about the same state in one request (for a model "
                                "that answers each question on its own, such as Kev or Laya)")
    return ap


def _summary_line(r: dict) -> str:
    return (f"seed {r['seed']}: {r['event']} at decision {r.get('decisions')}, furthest {r.get('max_x')}, health {r.get('health')}, "
            f"{r.get('jev_calls')} calls, {r.get('game')}")


def main(argv: Optional[Sequence[str]] = None, client: Optional[D1UltraClient] = None,
         game_factory: Optional[Callable[[], Any]] = None, out=None) -> int:
    args = _parser().parse_args(argv)
    out = out or sys.stdout

    def say(line: str) -> None:
        print(line, file=out, flush=True)

    if args.command == "show":
        say("\n".join(tree_lines(load_tree(args.tree))))
        return 0

    decider = decider_of(args.decider)
    if client is None and args.command not in ("finish",) and decider.key_required and not load_api_key(decider):
        say(f"{decider.key_env} is not set. {decider.name.capitalize()} makes every decision of the rule tree, so play "
            "needs the key (in the environment or a .env file).")
        return 2
    kwargs = {"workers": args.workers, "budget": args.budget, "ahead": args.ahead}
    if client is not None:
        kwargs["client"] = client
    elif args.model or args.endpoint or decider.name != "jev":
        kwargs["client"] = D1UltraClient(decider=decider, model=args.model, endpoint_url=args.endpoint,
                                         max_workers=max(6, 2 * args.workers))
    if game_factory is not None:
        kwargs["game_factory"] = game_factory
    run = Run(args.run, **kwargs)
    try:
        if args.command == "finish":
            say(str(run.finish(args.out)))
            return 0
        if getattr(args, "tree", None):
            run.start(args.tree)
        elif not (run.tree_dir / "tree.json").is_file():
            if args.command not in ("play", "eval", "realtime", "rtloop"):
                say(f"{args.run} has no tree yet: start it with --tree")
                return 2
            say(f"starting {args.run} from {DEFAULT_TREE}")
            run.start(DEFAULT_TREE)

        if args.command in ("play", "eval"):
            seeds = [args.seed] if args.command == "play" else parse_seeds(args.seeds)
            results = run.play_many(seeds)
            for r in results:
                say(_summary_line(r))
            cleared = sum(r["event"] == "cleared" for r in results)
            run.log(step=args.command, tree=run.tree().name, models=run.client.models_answered(), cleared=cleared, of=len(results),
                    games=results)
            say(f"cleared {cleared} of {len(results)}")
            return 0

        if args.command == "realtime":
            lag = None if args.lag == "wall" else tuple(map(int, args.lag.split("-"))) if "-" in args.lag else int(args.lag)
            results = evaluate(run, parse_seeds(args.seeds), lag, args.fill, args.label, cadence=args.cadence,
                               predict=args.predict, track=args.track, reflex=args.reflex, keep_text=args.keep_text,
                               aim=args.aim)
            for r in results:
                say(json.dumps(r))
            cleared = sum(r["event"] == "cleared" for r in results)
            run.log(step="realtime", tree=run.tree().name, lag=args.lag, fill=args.fill, cadence=args.cadence,
                    predict=args.predict, track=args.track, label=args.label,
                    models=run.client.models_answered(), cleared=cleared, of=len(results), games=results)
            say(f"cleared {cleared} of {len(results)}")
            return 0

        if args.command == "rtloop":
            settings = {"lag": args.lag, "track": "screen", "reflex": args.reflex, "fill": "hold", "aim": args.aim}
            result = run_rt_loop(run, writer_named(args.writer, args.writer_cmd), parse_seeds(args.train), parse_seeds(args.held),
                                 args.rounds, args.attempts, settings, args.margin, parse_seeds(args.monitor))
            say(json.dumps(result))
            return 0

        if args.command == "loop":
            result = run_loop(run, writer_named(args.writer, args.writer_cmd), parse_seeds(args.train), parse_seeds(args.held),
                              args.rounds, args.attempts)
            say(json.dumps(result))
            return 0

        raw = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
        name = Path(args.proposal).stem
        tree = run.tree()
        try:
            result = check(run, tree, Proposal.model_validate(raw), name=name)
        except (ProposalError, ValueError) as exc:
            say(f"the proposal cannot be checked: {exc}")
            return 2
        say(result.report.summary())
        run.log(step="check", name=name, proposal=raw, rule=result.report.rule, passed=result.report.passed)
        if args.command == "check" or not result.report.passed:
            return 0 if result.report.passed else 1
        if args.command == "gate":
            g = gate(run, tree, result.tree, parse_seeds(args.seeds), label=f"{name}-")
            say(g.summary(result.report.rule))
            run.log(step="gate", name=name, current=g.current, with_rule=g.with_rule, of=g.of, passed=g.passed)
            return 0 if g.passed else 1
        run.save(commit(result))
        run.log(step="commit", name=name, rule=result.report.rule, tree=tree_lines(run.tree()))
        say(f"committed {result.report.rule}")
        return 0
    finally:
        run.close()


if __name__ == "__main__":
    sys.exit(main())
