"""The website's Local models screen: for each shipped rule-tree recording, every question Jev answered with each local
model's answer to it, from saved agreement runs (`agreement.py`).

    python -m system1_doom.ruletree.site_models web/public/episodes kev-27b=runs/agreement-kev.json laya=runs/agreement-laya.json ...

Writes `<recording>/models.json`: the model ids in the order given, and one entry per question (its decision, its step
in the walk, kind and node) with each model's pick and the probability it gave the pick. An agreement run's rows follow
`agreement.questions` in order, so a run saved before rows named their step is matched by its position.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .agreement import questions


def site_answers(episode: Path, runs: Sequence[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """The models.json of one recording folder from (model id, agreement result) pairs."""
    asked = list(questions(episode / "decisions.jsonl"))
    entries: List[Dict[str, Any]] = [
        {"decision": q[0], "step": q[7], "kind": q[1], "node": q[2], "picks": {}} for q in asked
    ]
    for model, result in runs:
        rows = [r for r in result["rows"] if r["episode"] == episode.name]
        if len(rows) != len(asked):
            raise ValueError(f"{model}: {len(rows)} answers for {episode.name}, which asked {len(asked)} questions")
        for entry, row in zip(entries, rows):
            if (row["decision"], row["kind"], row["node"]) != (entry["decision"], entry["kind"], entry["node"]):
                raise ValueError(f"{model}: answer for decision {row['decision']} {row['kind']}:{row['node']} out of order")
            if row.get("pick") is not None:
                entry["picks"][model] = [row["pick"], round(row["probabilities"][row["pick"]], 4)]
    return {"models": [m for m, _ in runs], "answers": entries}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m system1_doom.ruletree.site_models", description=__doc__.split("\n")[0])
    ap.add_argument("episodes", help="the folder of the shipped recordings")
    ap.add_argument("runs", nargs="+", help="model=agreement.json, in the order the page shows them")
    args = ap.parse_args(argv)
    runs = []
    for spec in args.runs:
        model, _, path = spec.partition("=")
        runs.append((model, json.loads(Path(path).read_text(encoding="utf-8"))))
    names = sorted({r["episode"] for _, result in runs for r in result["rows"]})
    for name in names:
        out = Path(args.episodes) / name / "models.json"
        out.write_text(json.dumps(site_answers(out.parent, runs), separators=(",", ":")) + "\n", encoding="utf-8")
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
