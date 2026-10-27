"""Ask a decider the questions Jev answered in the shipped rule-tree recordings, and score both against the text.

    python -m system1_doom.ruletree.agreement OUT.json --decider laya
    python -m system1_doom.ruletree.agreement OUT.json --decider laya --model typed-decisions --max-len 0
    python -m system1_doom.ruletree.agreement OUT.json --decider kev

A recording keeps every question of every walk as it was sent: the state text, then the `[focus]` line once a focus
was picked, the question and its options, and Jev's answer. Each question goes to the decider named with the same
text and options (the decider's own request fields, such as Laya's window, are added as in play), and its pick is set
beside Jev's.

Some questions have an answer the state text settles (`settled`), so both models are scored against it rather than
against each other: at the root, whether the threats list names an enemy; in the aim skill, which band the focus
angle is in (an angle on a band's edge is left out, since "between 3 and 7" and "between 7 and 12" both hold); under
r1, whether the focus is more than 400 away and whether the outgoing channel names five or more fruitless decisions;
and the goal focus, the GreenArmor. "Which enemy is the biggest danger" is a judgement, so it is compared only.
`chance` is what a uniform pick would score on the same questions.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

from system1_doom.d1_client import D1UltraClient, decider_of

from .walk import FOCUS_HEAD, Jev

EPISODES = "web/public/episodes/rules-*"
FAR = 400  # r2: "more than 400 units away"
FRUITLESS = 5  # r11: "the last 5 or more decisions in which I fired hit nothing"

Question = Tuple[int, str, str, str, str, Dict[str, str], Dict[str, Any], int]


def questions(decisions: Path) -> Iterator[Question]:
    """Every question of a recording as it was sent: (decision, kind, node, text, question, options, Jev's answer, the
    step's index in the decision's walk)."""
    for line in decisions.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        text = row["state_text"].split(FOCUS_HEAD, 1)[0]
        for i, step in enumerate(row["steps"]):
            if step["kind"] == "focus":
                text = text.split(FOCUS_HEAD, 1)[0]
                if step.get("answer"):
                    yield row["decision"], "focus", step["node"], text, step["question"], step["options"], step["answer"], i
                if step.get("focus_line"):
                    text += FOCUS_HEAD + step["focus_line"]
            elif step["kind"] == "rule" and step.get("answer"):
                yield row["decision"], "rule", step["node"], text, step["question"], step["options"], step["answer"], i


def _channel(text: str, name: str) -> str:
    head = f"[{name}]\n"
    return text.split(head, 1)[1].split("\n\n", 1)[0] if head in text else ""


def settled(kind: str, node: str, text: str, options: Dict[str, str]) -> Optional[Set[str]]:
    """The options the state text makes right, for the questions of general-11 it settles; None for the others."""
    focus = text.split(FOCUS_HEAD, 1)[1] if FOCUS_HEAD in text else ""
    if kind == "rule" and node == "root" and set(options) == {"r1", "r3", "none"}:
        return {"r3"} if "no enem" in _channel(text, "threats").lower() else {"r1"}
    if kind == "rule" and node == "aim" and set(options) == {"r4", "r5", "r6", "r7", "r8", "r9", "none"}:
        m = re.search(r"(\d+) deg (right|left)", focus)
        if not m or int(m.group(1)) in (3, 7, 12):
            return None
        deg, side = int(m.group(1)), m.group(2)
        if deg < 3:
            return {"none"}
        band = 0 if deg < 7 else 1 if deg < 12 else 2
        return {(("r4", "r5", "r6") if side == "right" else ("r7", "r8", "r9"))[band]}
    if kind == "rule" and node == "r1" and set(options) == {"r2", "r11", "none"}:
        far = re.search(r"at distance (\d+)", focus)
        fruitless = re.search(r"the last (\d+) decisions in which you fired hit nothing", _channel(text, "outgoing"))
        right = {"r2"} if far and int(far.group(1)) > FAR else set()
        if fruitless and int(fruitless.group(1)) >= FRUITLESS:
            right.add("r11")
        return right or {"none"}
    if kind == "focus" and node == "r3":
        return {k for k, v in options.items() if v.startswith("GreenArmor")} or None
    return None


def compare(client: D1UltraClient, episodes: Sequence[Path]) -> Dict[str, Any]:
    """Ask the client every question of the recordings; each answer beside Jev's, and the scores."""
    ask = Jev(client, budget=30.0)
    rows: List[Dict[str, Any]] = []
    t0 = time.monotonic()
    for ep in episodes:
        for decision, kind, node, text, question, options, jev, step in questions(Path(ep) / "decisions.jsonl"):
            a = ask.ask(kind, node, text, "", question, options)
            right = settled(kind, node, text, options)
            rows.append({
                "episode": Path(ep).name, "decision": decision, "step": step, "kind": kind, "node": node, "options": options,
                "right": sorted(right) if right is not None else None, "jev": jev["pick"], "pick": a.pick,
                "probabilities": a.probabilities, "miss": a.miss, "error": a.error, "latency_ms": a.latency_ms,
            })
    by: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        c = by[f"{r['kind']}:{r['node']}"]
        c["questions"] += 1
        c["missed"] += r["miss"] is not None
        c["agree"] += r["pick"] == r["jev"]
        if r["right"] is not None:
            c["settled"] += 1
            c["jev_right"] += r["jev"] in r["right"]
            c["right"] += r["pick"] in r["right"]
            c["chance"] += len(r["right"]) / len(r["options"])
    total: Counter = Counter()
    for c in by.values():
        total.update(c)
    lat = sorted(r["latency_ms"] for r in rows if r["miss"] is None and r["latency_ms"])

    def scores(c: Counter) -> Dict[str, Any]:
        s = c["settled"]
        return {"questions": c["questions"], "missed": c["missed"], "agree_with_jev": c["agree"], "settled": s,
                "jev_right": c["jev_right"], "right": c["right"], "chance": round(c["chance"] / s, 3) if s else None}

    return {
        "decider": client.decider.name, "model": client.model, "request": dict(client.decider.request),
        "answered_by": client.models_answered(), "median_latency_ms": lat[len(lat) // 2] if lat else None,
        "seconds": round(time.monotonic() - t0, 1), "all": scores(total),
        "by_question": {k: scores(v) for k, v in sorted(by.items())}, "rows": rows,
    }


def summary_lines(result: Dict[str, Any]) -> List[str]:
    lines = [f"{result['decider']} ({result['model']}, {result['request'] or 'no request fields'}), "
             f"median {result['median_latency_ms']} ms a question"]
    for name, s in [*result["by_question"].items(), ("all", result["all"])]:
        line = f"{name:12s} {s['questions']:4d} asked, {s['agree_with_jev']:4d} as Jev"
        if s["settled"]:
            line += (f"; settled by the text {s['settled']:4d}: Jev right {s['jev_right'] / s['settled']:4.0%}, "
                     f"{result['decider']} right {s['right'] / s['settled']:4.0%}, chance {s['chance']:4.0%}")
        lines.append(line)
    return lines


def main(argv: Optional[Sequence[str]] = None, client: Optional[D1UltraClient] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m system1_doom.ruletree.agreement", description=__doc__.split("\n")[0])
    ap.add_argument("out", help="the JSON file for every answer and the scores")
    ap.add_argument("--decider", choices=("jev", "laya", "kev"), default="laya")
    ap.add_argument("--model", help="the decider's model, when it differs from its default")
    ap.add_argument("--endpoint", help="the decider's System One URL, when it differs from the default")
    ap.add_argument("--max-len", type=int, help="Laya's window in tokens; 0 sends none (the checkpoint's own, 512)")
    ap.add_argument("--episodes", nargs="*", help=f"recording folders (default: {EPISODES})")
    args = ap.parse_args(argv)
    if client is None:
        decider = decider_of(args.decider)
        if args.max_len is not None:
            decider = decider.model_copy(update={"request": {"max_len": args.max_len} if args.max_len else {}})
        client = D1UltraClient(decider=decider, model=args.model, endpoint_url=args.endpoint, max_workers=2)
    episodes = [Path(p) for p in (args.episodes or sorted(glob.glob(EPISODES)))]
    try:
        result = compare(client, episodes)
    finally:
        client.shutdown()
    Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("\n".join(summary_lines(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
