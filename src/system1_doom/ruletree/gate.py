"""The gate: a rule that passed its check on one game, against every training seed.

The current tree and the tree with the rule each play every seed once, side by side, with fresh answers. The rule
is kept only if its tree clears at least as many seeds. Passing on one game does not prove a rule is good
everywhere: in the soft loop a back-off rule passed its check with a large margin and still cleared fewer seeds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from pydantic import BaseModel, Field

from .tree import RuleTree


class GateReport(BaseModel):
    model_config = {"populate_by_name": True}

    current: int
    with_rule: int
    of: int
    passed: bool = Field(alias="pass")
    rows: List[Dict[str, Any]]

    def summary(self, ids: str = "the rule") -> str:
        lines = []
        for row in self.rows:
            a, b = row["current"], row["with_rule"]
            lines.append(f"seed {row['seed']}: current {a['event']} (x {a.get('max_x')}, health {a.get('health')}), "
                         f"with {ids} {b['event']} (x {b.get('max_x')}, health {b.get('health')}, {b.get('game')})")
        lines.append(f"cleared: current {self.current} of {self.of}, with {ids} {self.with_rule} of {self.of}: "
                     f"{'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)


def gate(run: Any, current: RuleTree, candidate: RuleTree, seeds: Sequence[int], label: str = "gate-") -> GateReport:
    """Play every seed with both trees (the candidate's games are named with `label`)."""
    seeds = list(seeds)
    results = run.play_jobs([(s, t, lab) for s in seeds for t, lab in ((current, ""), (candidate, label))])
    rows = [{"seed": s, "current": results[2 * i], "with_rule": results[2 * i + 1]} for i, s in enumerate(seeds)]
    n_current = sum(r["current"]["event"] == "cleared" for r in rows)
    n_with = sum(r["with_rule"]["event"] == "cleared" for r in rows)
    return GateReport(current=n_current, with_rule=n_with, of=len(seeds), passed=n_with >= n_current, rows=rows)
