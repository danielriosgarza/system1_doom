"""The soft loop in real time: rules written for a player as quick as Laya, from games in which the game did not wait.

Every game is played by `realtime.play_realtime` at a fixed lag (Laya's 7 tics by default), with the fair helper
aiming (`track="screen"`): the decider answers while the game is held, then the lag is played before its answer is
used, so a slow decider (Kev) plays as Laya would in real time. New rules ask questions Laya was never trained on, so
Kev answers them here, and its games become Laya's training data afterwards (`teach.py`).

A round plays the training seeds with the run's tree. The first failure not yet tried goes to the rule writer, with a
real-time dossier (`<run>/games/<game>/dossier.md`) and the real-time instructions (`prompts/rule-writer-realtime.md`).
A proposal is checked for `sees` only (at its frame, the walk through the new tree passes through it); the paused
check's replays from the middle of a game would need the helper's and the pending action's state. It is then gated:
the training seeds are played with the new tree, against the round's games with the current one. It is committed when
it clears more seeds, or as many with the failure's own game getting at least `PROGRESS` units further. Every step is a
line of `<run>/build.jsonl`, as in `loop.py`.
"""

from __future__ import annotations

import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import ValidationError

from .codes import describe
from .dossier import WINDOW, walk_line
from .gate import GateReport
from .realtime import REFLEX, play_realtime, summary
from .tree import ROOT, Proposal, RuleTree, tree_lines, with_rule
from .walk import decide
from .writers import Writer, parse

PROMPT = Path(__file__).resolve().parent / "prompts" / "rule-writer-realtime.md"
ATTEMPTS = 3
PROGRESS = 48  # units further along the corridor that count, at an equal number cleared
SETTINGS = {"lag": 7, "track": "screen", "reflex": REFLEX, "fill": "hold"}


def play_rt(run: Any, seed: int, tree: RuleTree, label: str = "", settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One real-time game with fresh answers, kept in `<run>/games/<name>.json` (and its dossier when it failed)."""
    settings = {**SETTINGS, **(settings or {})}
    name = run.new_name(seed, label)
    jev = run.jev(read=False, shard=f"{name}.json")
    game = run._borrow()
    try:
        record = play_realtime(game, tree, jev, seed, keep_text=True, keep_frames=True, **settings)
    except Exception:
        run._discard(game)
        raise
    run._idle.put(game)
    jev.book.save()
    data = {"name": name, "seed": seed, "tree": tree.name, "realtime": settings, **record}
    (run.folder / "games" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    out = summary(record)
    if out["event"] != "cleared":
        write_rt_dossier(run.folder / "games" / name, name, data, tree)
    return {"game": name, **out}


def play_rt_jobs(run: Any, jobs: Sequence[Tuple[int, RuleTree, str]], settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Play (seed, tree, label) jobs in parallel; their summaries, in the order given."""

    def one(job: Tuple[int, RuleTree, str]) -> Dict[str, Any]:
        seed, tree, label = job
        try:
            return play_rt(run, seed, tree, label, settings)
        except Exception as exc:  # noqa: BLE001 - a crashed game is reported with the others, not raised
            return {"seed": seed, "event": "crashed", "error": f"{type(exc).__name__}: {exc}"[:500]}

    with ThreadPoolExecutor(run.workers) as pool:
        return list(pool.map(one, jobs))


def _window_at(windows: List[Dict[str, Any]], tic: int) -> Optional[Dict[str, Any]]:
    """The last 8 tics of game time ended at or before `tic`."""
    done = [w for w in windows if w["tic"] <= tic]
    return done[-1] if done else None


def write_rt_dossier(folder: Path, name: str, game: Dict[str, Any], tree: RuleTree) -> Path:
    """The rule writer's dossier for a real-time game: the tree, the last decisions (when each state was read and its
    action started, what the helper aimed at, health and position, where the enemies really were, the screen), what
    was pressed between them, and the state text of each."""
    folder.mkdir(parents=True, exist_ok=True)
    decisions, windows = game["decisions"], game["windows"]
    last = windows[-1]
    happened = ", ".join(last["events"]) or ("cleared" if last.get("cleared") else "none")
    s = game["realtime"]
    lines = [f"# {name}: seed {game['seed']}, tic {game['tics']} (decision {len(decisions) - 1}): {happened}", "",
             f"Played in real time: every action started {s['lag']} tics after the state it was decided from; the helper "
             f"aimed ({s['track']}, {s['reflex']} tics late).", "",
             "## The rule tree that played", "", "```", *tree_lines(tree), "```", "",
             f"## The last {WINDOW} decisions", ""]
    shown = decisions[-WINDOW:]
    for k, d in enumerate(shown):
        i = d["i"]
        then = shown[k + 1]["start"] if k + 1 < len(shown) else game["tics"]
        w0, w1 = _window_at(windows, d["observed"]), _window_at(windows, then)
        h0 = w0["health_after"] if w0 else 100
        h1 = w1["health_after"] if w1 else h0
        pressed = [w["code"] for w in windows if d["start"] < w["tic"] <= then + 8][:4]
        frame = None
        if d.get("frame"):
            frame = folder / f"frame-{i:03d}.jpg"
            frame.write_bytes(base64.b64decode(d["frame"]))
        enemies = "; ".join(
            f"{e['name']}#{e['id']} {e['dist']}u {e['bearing']:+d}deg {e['side']}{' on screen' if e['on_screen'] else ''}"
            for e in d.get("truth", []) if e["dist"] < 1200
        ) or "none within 1200"
        target = f"; the helper aimed at {d['target'][0]} {d['target'][1]}" if d.get("target") else ""
        after = f", then {describe(d['after'])} once it was dead" if d.get("after") else ""
        lines += [f"## decision {i}: {describe(d['code'])} ({d['code']}), by {d['node']}",
                  f"state read at tic {d['observed']}, action from tic {d['start']} to tic {then}{target}{after}",
                  f"health {h0:.0f} -> {h1:.0f}, x {w0.get('x') if w0 else 0} -> {w1.get('x') if w1 else None}, "
                  f"furthest {w1['max_x'] if w1 else 0}",
                  f"keys pressed, 8 tics at a time: {' | '.join(pressed) or 'none'}",
                  f"path {d['route']}; walk: {walk_line(d['steps'])}",
                  f"engine truth (not shown to System 1): {enemies}"]
        if frame is not None:
            lines.append(f"frame: {frame}")
        lines.append("")
    lines += ["## The state System 1 read at each of these decisions", ""]
    for d in shown:
        if d.get("text"):
            lines += [f"### decision {d['i']}", "```", d["text"], "```", ""]
    out = folder / "dossier.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def rt_sees(run: Any, tree: RuleTree, proposal: Proposal, name: str) -> Tuple[RuleTree, List[str], str, Dict[str, Any]]:
    """The new tree, its new ids, where they attach, and the `sees` check at the proposal's frame."""
    path = run.folder / "games" / f"{proposal.trace}.json"
    if not path.is_file():
        raise ValueError(f"no game {proposal.trace!r} in this run")
    game = json.loads(path.read_text(encoding="utf-8"))
    by_i = {d["i"]: d for d in game.get("decisions", [])}
    d = by_i.get(proposal.frame)
    if d is None or "text" not in d:
        raise ValueError(f"game {proposal.trace} has decisions 0 to {len(by_i) - 1}; frame {proposal.frame} is not one of them")
    jev = run.jev(read=True, shard=f"{name}.json")
    deciding = decide(tree, jev, d["text"], d.get("frame", ""), game["seed"], proposal.frame)
    on_path = [ROOT] + deciding.route.split("/")
    attach_to = proposal.under if proposal.under in on_path else deciding.node
    new, ids = with_rule(tree, proposal, attach_to, writer=getattr(run, "writer_name", ""))
    walked = decide(new, jev, d["text"], d.get("frame", ""), game["seed"], proposal.frame)
    jev.book.save()
    passed = any(i in walked.route.split("/") or i == walked.node for i in ids)
    return new, ids, attach_to, {"pass": passed, "walk": walk_line([s.model_dump(exclude_none=True) for s in walked.steps])}


def rt_gate(run: Any, current: List[Dict[str, Any]], candidate: RuleTree, seeds: Sequence[int], failure_seed: int,
            label: str, settings: Optional[Dict[str, Any]] = None) -> GateReport:
    """The new tree on every training seed, against the round's games with the current tree."""
    results = play_rt_jobs(run, [(s, candidate, label) for s in seeds], settings)
    rows = [{"seed": s, "current": c, "with_rule": w} for s, c, w in zip(seeds, current, results)]
    n_current = sum(r["current"]["event"] == "cleared" for r in rows)
    n_with = sum(r["with_rule"]["event"] == "cleared" for r in rows)
    mine = next(r for r in rows if r["seed"] == failure_seed)
    further = (mine["with_rule"]["event"] == "cleared" and mine["current"]["event"] != "cleared") or \
        (mine["with_rule"].get("max_x") or 0) >= (mine["current"].get("max_x") or 0) + PROGRESS
    passed = n_with > n_current or (n_with == n_current and further)
    return GateReport(current=n_current, with_rule=n_with, of=len(seeds), passed=passed, rows=rows)


def prompt_for(run: Any, game: str, history: List[Tuple[Dict[str, Any], str]]) -> str:
    dossier = run.dossier(game)
    parts = [PROMPT.read_text(encoding="utf-8"), "\n---\n\n# The failure\n",
             f"The dossier below is also at {dossier}; its frames are the frame-NNN.jpg files in that folder, and you may "
             f"open them. The current rule tree is in {run.tree_dir / 'tree.json'}. Answer with the JSON only.\n",
             dossier.read_text(encoding="utf-8")]
    if history:
        parts.append("\n# Your earlier attempts on this failure, and what the program said\n")
        for i, (proposal, verdict) in enumerate(history, 1):
            parts.append(f"## attempt {i}\n```json\n{json.dumps(proposal, indent=1)}\n```\n{verdict}\n")
        parts.append("Write a new proposal that addresses what the program said.")
    return "\n".join(parts)


def rt_attempt(run: Any, writer: Writer, train: Sequence[int], current: List[Dict[str, Any]], failure: Dict[str, Any],
               n: int, attempts: int = ATTEMPTS, settings: Optional[Dict[str, Any]] = None) -> bool:
    """Up to `attempts` proposals for one failure; True if a rule was committed."""
    game = failure["game"]
    history: List[Tuple[Dict[str, Any], str]] = []
    folder = run.proposals_dir()
    run.writer_name = writer.name
    for k in range(1, attempts + 1):
        name = f"f{n:02d}-{game}-a{k}"
        prompt = prompt_for(run, game, history)
        (folder / f"{name}.prompt.md").write_text(prompt, encoding="utf-8")
        t0 = time.monotonic()
        answer = writer.write(prompt, name, folder)
        seconds = round(time.monotonic() - t0)
        try:
            raw = parse(answer)
        except ValueError as exc:
            run.log(step="proposal", name=name, writer=writer.name, seconds=seconds, error=str(exc))
            history.append(({"unparsed": answer[:2000]}, f"The program could not read a JSON object from your answer ({exc})."))
            continue
        if "needs_representation" in raw:
            run.log(step="needs_representation", name=name, writer=writer.name, seconds=seconds, proposal=raw)
            return False
        raw["trace"] = game
        run.log(step="proposal", name=name, writer=writer.name, seconds=seconds, proposal=raw)
        (folder / f"{name}.json").write_text(json.dumps(raw, indent=1), encoding="utf-8")
        tree = run.tree()
        try:
            new, ids, attach_to, sees = rt_sees(run, tree, Proposal.model_validate(raw), name)
        except (ValidationError, ValueError) as exc:
            run.log(step="check", name=name, error=str(exc)[-1500:])
            history.append((raw, f"The program could not check this proposal: {str(exc)[-1500:]}"))
            continue
        rule = "+".join(ids)
        verdict = (f"check: {'PASS' if sees['pass'] else 'FAIL'} (your rule became {rule}, attached under {attach_to})\n"
                   f"sees: {'pass' if sees['pass'] else 'FAIL'}; the walk at your frame: {sees['walk']}")
        run.log(step="check", name=name, rule=rule, attach_to=attach_to, passed=sees["pass"], sees=sees["pass"])
        if not sees["pass"]:
            history.append((raw, verdict))
            continue
        g = rt_gate(run, current, new, train, failure["seed"], f"{name}-", settings)
        (folder / f"{name}.gate.txt").write_text(g.summary(rule), encoding="utf-8")
        run.log(step="gate", name=name, current=g.current, with_rule=g.with_rule, of=g.of, passed=g.passed)
        if not g.passed:
            history.append((raw, verdict + f"\n\ngate: FAIL. Played in real time on every training seed, the current tree "
                            f"cleared {g.current} and the tree with your rule {g.with_rule} of {g.of} (it must clear more, or "
                            f"as many with this game getting at least {PROGRESS} units further):\n" + g.summary(rule)))
            continue
        run.save(new)
        run.log(step="commit", name=name, rule=rule, tree=tree_lines(run.tree()))
        return True
    return False


def run_rt_loop(run: Any, writer: Writer, train: Sequence[int], held: Sequence[int], rounds: int = 8,
                attempts: int = ATTEMPTS, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Rounds until every training seed clears (then the held-out seeds are played), `rounds` run out, or every
    failure has been tried."""
    train, held = list(train), list(held)
    result: Dict[str, Any] = {"rounds": 0, "train": None, "held": None}
    tried: set = set()
    for r in range(1, rounds + 1):
        tree = run.tree()
        results = play_rt_jobs(run, [(s, tree, "") for s in train], settings)
        failures = [x for x in results if x["event"] != "cleared"]
        cleared = len(results) - len(failures)
        run.log(step="pass", round=r, realtime=True, cleared=cleared, of=len(train),
                games=[{k: x.get(k) for k in ("seed", "game", "event", "decisions", "max_x", "health")} for x in results])
        result.update(rounds=r, train=f"{cleared}/{len(train)}")
        if not failures:
            break
        failure = next((x for x in failures if x["event"] != "crashed" and x["seed"] not in tried), None)
        if failure is None:
            run.log(step="stop", reason="every failure has been tried")
            break
        if not rt_attempt(run, writer, train, results, failure, r, attempts, settings):
            tried.add(failure["seed"])
    if held:
        held_results = play_rt_jobs(run, [(s, run.tree(), "held-") for s in held], settings)
        n_held = sum(x["event"] == "cleared" for x in held_results)
        run.log(step="held-out", realtime=True, cleared=n_held, of=len(held),
                games=[{k: x.get(k) for k in ("seed", "game", "event", "decisions", "max_x", "health")} for x in held_results])
        result["held"] = f"{n_held}/{len(held)}"
    run.log(step="done", tree=tree_lines(run.tree()), **result)
    return result
