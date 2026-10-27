"""The rule tree's command line.

  python -m system1_doom.ruletree show   --tree general-11
  python -m system1_doom.ruletree eval   RUN --tree general-11 --seeds 9-19,40-59
  python -m system1_doom.ruletree eval   RUN --tree general-11 --seeds 9-19 --decider laya
  python -m system1_doom.ruletree play   RUN --tree general-11 --seed 9
  python -m system1_doom.ruletree loop   RUN --tree general-9 --writer codex --train 9-19 --held 20-39
  python -m system1_doom.ruletree check  RUN PROPOSAL.json
  python -m system1_doom.ruletree gate   RUN PROPOSAL.json --seeds 9-19
  python -m system1_doom.ruletree commit RUN PROPOSAL.json
  python -m system1_doom.ruletree finish RUN OUT

RUN is a folder (see `run.py`); it starts from `--tree` (a shipped tree's name or a tree folder) the first time;
`play` and `eval` start it from general-11 when no tree is named.
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
from .run import Run
from .tree import DEFAULT_TREE, Proposal, load_tree, shipped_trees, tree_lines
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
    kwargs = {"workers": args.workers}
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
            if args.command not in ("play", "eval"):
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
