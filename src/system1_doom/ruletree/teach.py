"""Training data for a decision model of one's own, from rule-tree games: every question asked, as it was sent, with
the answer of the model that played (the teacher) or the answer the state text settles.

    python -m system1_doom.ruletree.teach OUT.jsonl RUN [RUN ...] --seeds 400-424 --labels teacher

Each line is one question in the `{state, questions, gold | expected}` form `laya-train` reads: `gold` holds the
teacher's probabilities, `expected` the one option the text makes right (two that both hold share the mass, as
`gold`). With `--labels text` only the questions `agreement.settled` decides are written; with `text+teacher` the text's
answer is used where it settles one and the teacher's elsewhere. A question asked again with the same text and options
is written once. A missed answer is left out. Games played in real time (`realtime --keep-text`, in `RUN/realtime/`)
are read as well: their decisions are the trace, each with the state text it was decided from, so a teacher held to
Laya's lag gives answers to the states Laya meets in real time.

Laya fine-tuned this way on 3,212 of Jev's answers (seeds 400-424) is in §15 of docs/DOCUMENTATION.md.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from .agreement import settled
from .walk import FOCUS_HEAD

LABELS = ("teacher", "text", "text+teacher")


def game_questions(trace: Sequence[Dict[str, Any]]) -> Iterator[Tuple[str, str, str, str, Dict[str, str], Dict[str, Any]]]:
    """Every answered question of a game as it was sent: (kind, node, text, question, options, answer)."""
    for rec in trace:
        text = rec["text"].split(FOCUS_HEAD, 1)[0]
        for step in rec["steps"]:
            answer = step.get("answer")
            answered = bool(answer) and not answer.get("miss")
            if step["kind"] == "focus":
                text = text.split(FOCUS_HEAD, 1)[0]
                if answered:
                    yield "focus", step["node"], text, step["question"], step["options"], answer
                if step.get("focus_line"):
                    text += FOCUS_HEAD + step["focus_line"]
            elif step["kind"] == "rule" and answered:
                yield "rule", step["node"], text, step["question"], step["options"], answer


def row(kind: str, node: str, text: str, question: str, options: Dict[str, str], answer: Dict[str, Any],
        labels: str) -> Optional[Tuple[Dict[str, Any], str]]:
    """One training line and where its label came from (`text` or `teacher`), or None when it has no label."""
    q = {"q": {"type": "choice", "instructions": question, "criteria": dict(options)}}
    right = settled(kind, node, text, options) if labels != "teacher" else None
    if right is not None and len(right) == 1:
        return {"state": text, "questions": q, "expected": {"q": next(iter(right))}}, "text"
    if right is not None:
        probs = {k: (1.0 / len(right) if k in right else 0.0) for k in options}
        return {"state": text, "questions": q, "gold": {"q": {"probabilities": probs}}}, "text"
    if labels != "text" and answer.get("probabilities"):
        return {"state": text, "questions": q, "gold": {"q": {"probabilities": dict(answer["probabilities"])}}}, "teacher"
    return None


def build(runs: Sequence[Path], seeds: Sequence[int], labels: str = "teacher") -> Tuple[List[Dict[str, Any]], Counter]:
    """The training lines of every game of the runs played on the seeds, and a count by question and label source."""
    wanted, lines, counts, seen = set(seeds), [], Counter(), set()
    for run in runs:
        for path in sorted(Path(run, "games").glob("*.json")) + sorted(Path(run, "realtime").glob("*.json")):
            game = json.loads(path.read_text(encoding="utf-8"))
            trace = game.get("trace") or [d for d in game.get("decisions", []) if "text" in d]
            if game.get("seed") not in wanted or not trace:
                continue
            for kind, node, text, question, options, answer in game_questions(trace):
                key = (text, question, tuple(sorted(options.items())))
                if key in seen:
                    continue
                seen.add(key)
                made = row(kind, node, text, question, options, answer, labels)
                if made is not None:
                    lines.append(made[0])
                    counts[f"{kind}:{node}:{made[1]}"] += 1
    return lines, counts


def main(argv: Optional[Sequence[str]] = None) -> int:
    from .__main__ import parse_seeds

    ap = argparse.ArgumentParser(prog="python -m system1_doom.ruletree.teach", description=__doc__.split("\n")[0])
    ap.add_argument("out", help="the JSONL file laya-train reads")
    ap.add_argument("runs", nargs="+", help="run folders whose games to read")
    ap.add_argument("--seeds", required=True, help="the seeds whose games to read, e.g. 400-424")
    ap.add_argument("--labels", choices=LABELS, default="teacher")
    args = ap.parse_args(argv)
    lines, counts = build([Path(r) for r in args.runs], parse_seeds(args.seeds), args.labels)
    Path(args.out).write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    print(f"{len(lines)} questions: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
