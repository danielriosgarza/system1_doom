"""The soft loop: play the training seeds; take the first failure to the rule writer; check, gate and commit its
proposal; play again. When every training seed clears, play the held-out seeds and stop.

Each failure gets up to three proposals. A proposal that fails its check, or the gate, goes back to the writer with
the report. Every step is a line of the run's `build.jsonl`: each pass (which seeds failed, how and where), each
proposal (the writer, its seconds, the rule), each check, each gate and each commit.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from pydantic import ValidationError

from .check import ProposalError, check, commit
from .gate import gate
from .tree import Proposal, tree_lines
from .writers import Writer, parse

PROMPT = Path(__file__).resolve().parent / "prompts" / "rule-writer.md"
ATTEMPTS = 3


def instructions() -> str:
    return PROMPT.read_text(encoding="utf-8")


def prompt_for(run: Any, game: str, history: List[Tuple[Dict[str, Any], str]]) -> str:
    dossier = run.dossier(game)
    parts = [instructions(), "\n---\n\n# The failure\n",
             f"The dossier below is also at {dossier}; its frames are the frame-NNN.jpg files in that folder, and you may "
             f"open them. The current rule tree is in {run.tree_dir / 'tree.json'}. Answer with the JSON only.\n",
             dossier.read_text(encoding="utf-8")]
    if history:
        parts.append("\n# Your earlier attempts on this failure, and what the program said\n")
        for i, (proposal, verdict) in enumerate(history, 1):
            parts.append(f"## attempt {i}\n```json\n{json.dumps(proposal, indent=1)}\n```\n{verdict}\n")
        parts.append("Write a new proposal that addresses what the program said.")
    return "\n".join(parts)


def attempt(run: Any, writer: Writer, train: Sequence[int], failure: Dict[str, Any], n: int, attempts: int = ATTEMPTS) -> bool:
    """Up to `attempts` proposals for one failure; True if a rule was committed."""
    game = failure["game"]
    history: List[Tuple[Dict[str, Any], str]] = []
    folder = run.proposals_dir()
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
            proposal = Proposal.model_validate(raw)
            result = check(run, tree, proposal, name=name)
        except (ProposalError, ValidationError, ValueError) as exc:
            run.log(step="check", name=name, error=str(exc)[-1500:])
            history.append((raw, f"The program could not check this proposal: {str(exc)[-1500:]}"))
            continue
        report = result.report
        verdict = report.summary()
        (folder / f"{name}.check.json").write_text(report.model_dump_json(by_alias=True, indent=1), encoding="utf-8")
        run.log(step="check", name=name, rule=report.rule, attach_to=report.attach_to, passed=report.passed,
                sees=report.sees["pass"], unchanged=report.unchanged["pass"], avoids=report.avoids["pass"],
                old_tree=report.avoids["old_tree"], new_tree=report.avoids["new_tree"])
        if not report.passed:
            history.append((raw, verdict))
            continue
        g = gate(run, tree, result.tree, train, label=f"{name}-")
        (folder / f"{name}.gate.txt").write_text(g.summary(report.rule), encoding="utf-8")
        run.log(step="gate", name=name, current=g.current, with_rule=g.with_rule, of=g.of, passed=g.passed)
        if not g.passed:
            history.append((raw, verdict + f"\n\ngate: FAIL. Played on every training seed, the current tree cleared {g.current} "
                            f"and the tree with your rule {g.with_rule} of {g.of}:\n" + g.summary(report.rule)))
            continue
        run.save(commit(result))
        run.log(step="commit", name=name, rule=report.rule, tree=tree_lines(run.tree()))
        return True
    return False


def run_loop(run: Any, writer: Writer, train: Sequence[int], held: Sequence[int], rounds: int = 12,
             attempts: int = ATTEMPTS) -> Dict[str, Any]:
    """Rounds of the loop until every training seed clears (then the held-out seeds are played) or `rounds` run out."""
    train, held = list(train), list(held)
    result: Dict[str, Any] = {"rounds": 0, "train": None, "held": None}
    for r in range(1, rounds + 1):
        results = run.play_many(train)
        failures = [x for x in results if x["event"] != "cleared"]
        cleared = len(results) - len(failures)
        run.log(step="pass", round=r, cleared=cleared, of=len(train),
                games=[{k: x.get(k) for k in ("seed", "game", "event", "decisions", "max_x", "health")} for x in results])
        result.update(rounds=r, train=f"{cleared}/{len(train)}")
        if not failures:
            held_results = run.play_many(held) if held else []
            n_held = sum(x["event"] == "cleared" for x in held_results)
            run.log(step="held-out", cleared=n_held, of=len(held),
                    games=[{k: x.get(k) for k in ("seed", "game", "event", "decisions", "max_x", "health")} for x in held_results])
            result["held"] = f"{n_held}/{len(held)}"
            break
        failure = next((x for x in failures if x["event"] != "crashed"), None)
        if failure is None:
            run.log(step="stop", reason="every seed that did not clear crashed")
            break
        attempt(run, writer, train, failure, r, attempts)
    run.log(step="done", tree=tree_lines(run.tree()), **result)
    return result
