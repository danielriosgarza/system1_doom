"""The check every proposed rule must pass before it is gated, and the commit that adds it.

1. sees: at its frame, the walk through the new tree passes through the new rule (or one of its group).
2. unchanged: the frames earlier rules were written from still take the same route, or replaying their game from
   there to their own horizon with the new tree ends no worse than the rule's own check did.
3. avoids: the game is replayed to the frame and played on to 24 decisions past the failure, once with the old tree
   and once with the new one; the new one must end better (see `better`).

The proposal becomes an exception to the node that decides at its frame under the current tree, or to the node it
names as `under` if that node is on the frame's walk. Answers Jev gave in play are reused, so a replayed state gets
the answer it got then.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from .codes import ActionError
from .dossier import walk_line
from .game import play
from .tree import ROOT, Cornerstone, Proposal, RuleTree, with_rule
from .walk import decide

AVOID_MARGIN = 24  # decisions played past the original event

Standing = Tuple[int, int, float, float]


class ProposalError(ValueError):
    """A proposal the check cannot test: unknown game or frame, or a rule the tree cannot hold."""


def standing(trace: Sequence[Dict[str, Any]], i: int) -> Standing:
    """What the goal needs, at decision i: alive, the goal reached, health, furthest point reached."""
    r = trace[min(i, len(trace) - 1)]
    dead = any(x["died"] for x in trace[: i + 1])
    cleared = not dead and len(trace) <= i + 1 and trace[-1]["finished"] and "timed out" not in trace[-1]["events"]
    return (0 if dead else 1, int(cleared), 0.0 if dead else float(r["health_after"]), float(r["max_x"]))


def better(new: Sequence[float], old: Sequence[float]) -> bool:
    """Alive beats dead, and the goal reached beats not reached; otherwise no worse on health and furthest point,
    and better on one of them. Dead is never better than dead: dying a few units further on does not avoid the
    death."""
    new, old = tuple(new), tuple(old)
    if new[:2] != old[:2]:
        return new[:2] > old[:2]
    if new[0] == 0:
        return False
    return all(n >= o for n, o in zip(new[2:], old[2:])) and new[2:] != old[2:]


class CheckReport(BaseModel):
    rule: str
    ids: List[str]
    attach_to: str
    frame: int
    event_at: int
    event: List[str]
    sees: Dict[str, Any]
    unchanged: Dict[str, Any]
    avoids: Dict[str, Any]
    passed: bool = Field(alias="pass")
    jev_calls: int = 0

    model_config = {"populate_by_name": True}

    def summary(self) -> str:
        """The report in the few lines the rule writer needs."""
        a = self.avoids
        return "\n".join([
            f"check: {'PASS' if self.passed else 'FAIL'} (your rule became {self.rule}, attached under {self.attach_to})",
            f"sees: {'pass' if self.sees['pass'] else 'FAIL'}; the walk at your frame: {self.sees['walk']}",
            f"unchanged: {'pass' if self.unchanged['pass'] else 'FAIL'}; earlier frames that now take another route: "
            f"{self.unchanged['changed'] or 'none'}",
            f"avoids: {'pass' if a['pass'] else 'FAIL'}; standing at decision {a['horizon']} as (alive, goal reached, health, "
            f"furthest point): old tree {a['old_tree']}, new tree {a['new_tree']}; first unwanted event with your rule: "
            f"{a['first_event_after']}",
            f"the new tree's decisions from your frame (decision:action:node): {a['actions'][:1500]}",
        ])


@dataclass
class CheckResult:
    """The report, and what a commit needs: the new tree, where the frame is kept, the frames that moved
    ((node, index) -> the route the frame takes now)."""

    report: CheckReport
    tree: RuleTree
    store_at: Optional[str]
    cornerstone: Optional[Cornerstone]
    frame_b64: str
    moved: Dict[Tuple[str, int], str] = field(default_factory=dict)


def check(run: Any, tree: RuleTree, proposal: Proposal, name: str = "check") -> CheckResult:
    """Check a proposal against the game it was written from (a game of `run`), with the run's recorded answers."""
    try:
        game = run.game_record(proposal.trace)
    except FileNotFoundError as exc:
        raise ProposalError(str(exc)) from None
    seed, trace, k = game["seed"], game["trace"], proposal.frame
    if not 0 <= k < len(trace) or "text" not in trace[k]:
        raise ProposalError(f"game {proposal.trace} has decisions 0 to {len(trace) - 1}; frame {k} is not one of them")
    f = len(trace) - 1
    jev = run.jev(read=True, shard=f"{name}.json")
    text, frame = trace[k]["text"], trace[k]["frame"]

    deciding = decide(tree, jev, text, frame, seed, k)
    on_path = [ROOT] + deciding.route.split("/")
    attach_to = proposal.under if proposal.under in on_path else deciding.node
    try:
        new, ids = with_rule(tree, proposal, attach_to)
    except (ActionError, ValueError) as exc:
        raise ProposalError(str(exc)) from None
    rid = "+".join(ids)

    # 1. Jev sees it.
    seen = decide(new, jev, text, frame, seed, k)
    went = seen.route.split("/")
    store_at = next((i for i in reversed(went) if i in ids), None)
    sees = {"pass": store_at is not None, "reached": seen.node, "route": seen.route,
            "walk": walk_line([s.model_dump(exclude_none=True) for s in seen.steps])}

    # 2. Nothing older gets worse.
    corners = [(nid, n, c) for nid, node in tree.nodes.items() for n, c in enumerate(node.cornerstones)]
    with ThreadPoolExecutor(8) as pool:
        got = list(pool.map(lambda x: decide(new, jev, x[2].state_text, tree.frame_b64(x[2]), x[2].seed, x[2].decision), corners))
    changed, moved = [], {}
    for (nid, n, c), d in zip(corners, got):
        if d.route == c.expect:
            continue
        replay = play(run.game(), new, jev, c.seed, prefix=c.prefix, stop_after=c.horizon, keep_frames=False, stop_on_event=False)
        now = standing(replay, c.horizon)
        worse = better(c.standing, now)
        changed.append({"rule": nid, "expected": c.expect, "now_reaches": d.route, "standing_then": list(c.standing),
                        "standing_now": list(now), "worse": worse})
        moved[(nid, n)] = d.route
    unchanged = {"pass": not any(x["worse"] for x in changed), "cornerstones": len(corners), "changed": changed}

    # 3. It avoids the event.
    horizon = f + AVOID_MARGIN
    prefix = [r["code"] for r in trace[:k]]
    before = play(run.game(), tree, jev, seed, prefix=prefix, stop_after=horizon, keep_frames=False, stop_on_event=False)
    after = play(run.game(), new, jev, seed, prefix=prefix, stop_after=horizon, keep_frames=False, stop_on_event=False)
    first = next((r for r in after[k:] if r["events"]), None)
    old_s, new_s = standing(before, horizon), standing(after, horizon)
    avoids = {"pass": better(new_s, old_s), "horizon": horizon, "old_tree": list(old_s), "new_tree": list(new_s),
              "first_event_after": None if first is None else {"i": first["i"], "events": first["events"]},
              "actions": " ".join(f"{r['i']}:{r['code']}:{r['node']}" for r in after[k:])}
    jev.book.save()

    report = CheckReport(rule=rid, ids=ids, attach_to=attach_to, frame=k, event_at=f, event=trace[f]["events"], sees=sees,
                         unchanged=unchanged, avoids=avoids, passed=sees["pass"] and unchanged["pass"] and avoids["pass"],
                         jev_calls=jev.calls)
    cornerstone = None
    if store_at is not None:
        cornerstone = Cornerstone(seed=seed, prefix=prefix, state_text=text, frame="", expect=seen.route, event_at=f,
                                  horizon=horizon, standing=new_s)
    return CheckResult(report=report, tree=new, store_at=store_at, cornerstone=cornerstone, frame_b64=frame, moved=moved)


def commit(result: CheckResult) -> RuleTree:
    """The tree with the checked rule: its frame kept at the rule the walk reached, and every earlier frame that
    moved without harm now expecting the route it takes."""
    if not result.report.passed or result.store_at is None or result.cornerstone is None:
        raise ValueError("only a rule that passed its check is committed")
    tree = result.tree.clone()
    tree.add_cornerstone(result.store_at, result.cornerstone, result.frame_b64)
    for (nid, n), now in result.moved.items():
        tree.nodes[nid].cornerstones[n] = tree.nodes[nid].cornerstones[n].model_copy(update={"expect": now})
    return tree
