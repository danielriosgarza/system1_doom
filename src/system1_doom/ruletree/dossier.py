"""The dossier: what the rule writer is given for one failure.

The tree that played, then the last 12 decisions before the unwanted event: the action, the rule that gave it and
the walk that led there, health and position, where the enemies really were (for the writer's diagnosis; Jev never
sees it), and the screen; then the state Jev read at each of those decisions, word for word.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List

from .codes import describe
from .tree import RuleTree, tree_lines

WINDOW = 12  # decisions shown before the event


def walk_line(steps: List[Dict[str, Any]]) -> str:
    """A walk in one line: `at root picked r1 (0.93); focus at r1 picked 'Zombieman ...' (0.81); skill aim; ...`."""
    parts = []
    for s in steps:
        answer = s.get("answer") or {}
        p = answer.get("probabilities", {}).get(answer.get("pick"))
        prob = f" ({p:.2f})" if p is not None else ""
        if s["kind"] == "skill":
            parts.append(f"skill {s['skill']}")
        elif answer.get("miss"):
            parts.append(f"at {s['node']} the {s['kind']} question missed ({answer['miss']})")
        elif s["kind"] == "focus":
            parts.append(f"focus at {s['node']} picked {s.get('pick')!r}{prob}")
        else:
            parts.append(f"at {s['node']} picked {s.get('pick')}{prob}")
    return "; ".join(parts) or "none (replayed)"


def write_dossier(folder: Path, name: str, seed: int, trace: List[Dict[str, Any]], tree: RuleTree) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    f = len(trace) - 1
    last = trace[f]
    happened = ", ".join(last["events"]) or ("cleared" if last.get("cleared") else "none")
    lines = [f"# {name}: seed {seed}, decision {f}: {happened}", "",
             "## The rule tree that played", "", "```", *tree_lines(tree), "```", "",
             f"## The last {WINDOW} decisions", ""]
    shown = trace[max(0, f - WINDOW + 1):]
    for rec in shown:
        i = rec["i"]
        frame = None
        if rec.get("frame"):
            frame = folder / f"frame-{i:03d}.jpg"
            frame.write_bytes(base64.b64decode(rec["frame"]))
        enemies = "; ".join(
            f"{e['name']}#{e['id']} {e['dist']}u {e['bearing']:+d}deg {e['side']}{' on screen' if e['on_screen'] else ''}"
            for e in rec.get("truth", []) if e["dist"] < 1200
        ) or "none within 1200"
        lines += [f"## decision {i}: {describe(rec['code'])} ({rec['code']}), by {rec['node']}",
                  f"health {rec['health_before']:.0f} -> {rec['health_after']:.0f}, x {rec.get('x')}, furthest {rec['max_x']}, "
                  f"events {', '.join(rec['events']) or 'none'}",
                  f"path {rec.get('route', rec['node'])}; walk: {walk_line(rec.get('steps', []))}",
                  f"engine truth (not shown to Jev): {enemies}"]
        if frame is not None:
            lines.append(f"frame: {frame}")
        lines.append("")
    lines += ["## The state Jev read at each of these decisions", ""]
    for rec in shown:
        if rec.get("text"):
            lines += [f"### decision {rec['i']}", "```", rec["text"], "```", ""]
    out = folder / "dossier.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
