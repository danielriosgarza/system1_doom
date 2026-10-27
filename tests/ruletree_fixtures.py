"""Shared pieces for the rule-tree tests: the general starting tree, a state text, a screen, a scripted Jev."""

from __future__ import annotations

import base64
import io
from typing import Any, Callable, Dict, Optional

from PIL import Image

from system1_doom.d1_client import D1UltraClient
from system1_doom.ruletree.tree import RuleNode, RuleTree, SkillCall, Focus
from tests.fake_d1 import FakeD1, choice

AIM_BANDS = [
    ("r4", "between 3 and 7 degrees to the right", "00R0:3"),
    ("r5", "between 7 and 12 degrees to the right", "00R0:5"),
    ("r6", "more than 12 degrees to the right", "00R0:7"),
    ("r7", "between 3 and 7 degrees to the left", "00L0:3"),
    ("r8", "between 7 and 12 degrees to the left", "00L0:5"),
    ("r9", "more than 12 degrees to the left", "00L0:7"),
]


def general_tree() -> RuleTree:
    """The 9-rule general tree the soft loop starts from."""
    nodes = {
        "root": RuleNode(id="root", parent=None, condition=None, action="random", children=["r1", "r3"]),
        "r1": RuleNode(id="r1", parent="root", condition="The threats list shows at least one enemy.",
                       action=SkillCall(skill="aim", then="0001"), children=["r2"],
                       focus=Focus(from_channels=["threats"], question="Which of these enemies is the biggest danger to me right now?")),
        "r2": RuleNode(id="r2", parent="r1", condition="The focus channel says the enemy is more than 400 units away.",
                       action=SkillCall(skill="aim", then="F001")),
        "r3": RuleNode(id="r3", parent="root", condition="The threats list says no enemy is visible.",
                       action=SkillCall(skill="aim", then="F000"),
                       focus=Focus(from_channels=["landmarks"], question="Which of these is the goal I am trying to reach?")),
        "aim": RuleNode(id="aim", parent=None, condition=None, action="then", children=[r for r, _, _ in AIM_BANDS]),
    }
    for rid, band, action in AIM_BANDS:
        nodes[rid] = RuleNode(id=rid, parent="aim", condition=f"The focus channel says it is {band}.", action=action)
    return RuleTree(name="general-9", writer="claude", nodes=nodes)


STATE = (
    "[goal]\nReach the green armor at the far end of the corridor alive.\n\n"
    "[vitals]\nhealth 100, armor 0\n\n"
    "[threats]\n- ShotgunGuy at distance 300, 10 deg right, 8 px wide\n- Zombieman at distance 520, 4 deg left, 3 px wide\n\n"
    "[landmarks]\n- the green armor, far ahead\n\n"
    "[outgoing]\nno shots fired"
)
ONE_THREAT = STATE.replace("- Zombieman at distance 520, 4 deg left, 3 px wide\n", "")


def screen_b64(color=(40, 40, 40)) -> str:
    out = io.BytesIO()
    Image.new("RGB", (320, 240), color).save(out, format="JPEG")
    return base64.b64encode(out.getvalue()).decode("ascii")


Script = Callable[[str, Dict[str, str], str], str]


def scripted(answer: Script, p: float = 0.8) -> Callable[[str, Dict[str, Any]], Dict[str, Any]]:
    """A FakeD1 policy for the rule tree: `answer(kind, options, state)` names the option to pick."""

    def policy(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        question = payload["questions"][name]
        options = question["criteria"]
        return {name: choice(list(options), answer(name, options, payload["state"]), p)}

    return policy


def by_text(*wanted: str) -> Script:
    """Pick the first option whose text contains one of `wanted`, else `none` (or the first option)."""

    def answer(kind: str, options: Dict[str, str], state: str) -> str:
        for w in wanted:
            for key, text in options.items():
                if w in text:
                    return key
        return "none" if "none" in options else next(iter(options))

    return answer


def jev_client(fake: FakeD1, budget: Optional[float] = None) -> D1UltraClient:
    return D1UltraClient(api_key="typesafe_test_key", decider="jev", transport=fake, default_timeout=budget or 2.0)


class CorridorGame:
    """A stand-in for Deadly Corridor, deterministic: walking forward gains 50 units a decision; an enemy comes into
    view at 100 units (150 on odd seeds) and kills the agent on its third decision in view unless the agent stands
    and fires (`0001`), which kills it. Reaching 400 units clears the level."""

    def __init__(self) -> None:
        self.max_x = [0.0]

    def close(self) -> None:
        pass

    def reset(self, seed: int) -> None:
        self.seed, self.x, self.health, self.seen, self.enemy = seed, 0.0, 100.0, 0, True
        self.max_x = [0.0]
        self.done = self.dead = False

    def in_view(self) -> bool:
        return self.enemy and self.x >= (150 if self.seed % 2 else 100)

    def observe(self):
        threats = "- Imp at distance 200, 0 deg ahead, size 10x20 px" if self.in_view() else "no enemy visible"
        text = f"[goal]\nReach the end alive.\n\n[vitals]\nhealth {self.health:.0f}\n\n[threats]\n{threats}\n\n[position]\nx {self.x:.0f}"
        return text, SCREEN

    def truth(self):
        return [{"name": "Imp", "id": 1, "dist": 200, "bearing": 0, "side": "ahead", "on_screen": self.in_view()}] if self.enemy else []

    def step(self, code: str):
        from system1_doom.ruletree.codes import segments

        h0 = self.health
        for seg, tics in segments(code):
            if seg == "0001" and self.in_view():
                self.enemy = False
            if seg[0] == "F":
                self.x += 50 * tics / 8
        if self.in_view():
            self.seen += 1
            if self.seen >= 3:
                self.health, self.dead, self.done = 0.0, True, True
        if self.x >= 400:
            self.done = True
        self.max_x.append(max(self.max_x[-1], self.x))
        return {"code": code, "health_before": h0, "health_after": self.health, "died": self.dead, "finished": self.done,
                "x": round(self.x), "reward": 0.0}

    def events(self, rec):
        if rec["died"]:
            return ["died"]
        if len(self.max_x) > 24 and self.max_x[-1] - self.max_x[-25] < 48:
            return ["stalled"]
        return []

    def cleared(self) -> bool:
        return self.done and not self.dead


SCREEN = screen_b64()


def walk_on_tree() -> RuleTree:
    """A tree with no rules whose root walks forward."""
    return RuleTree(name="walk-on", writer="test", nodes={"root": RuleNode(id="root", parent=None, condition=None, action="F000")})


def sees_imp(kind: str, options: Dict[str, str], state: str) -> str:
    """Jev for the corridor: a condition about an enemy in view holds when the threats list has one."""
    in_view = "- Imp" in state
    for key, text in options.items():
        if in_view and text == "An enemy is in view.":
            return key
    return "none" if "none" in options else next(iter(options))
