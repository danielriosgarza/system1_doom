"""Action codes: what one decision of the rule tree presses.

A code has four letters, one per axis: walk (`F` forward, `0`, `B` backward), sidestep (`L`, `0`, `R`), turn
(`L`, `0`, `R`) and fire (`1`, `0`). `F0R1` walks forward while turning right and firing; `0000` stands still.
There are 54 codes. A decision lasts 8 tics (about a quarter of a second): a code alone is held for all 8, and a
sequence `CODE:TICS+CODE:TICS` divides them (`00R0:3+0001:5` turns right for 3 tics, then fires for 5).

Inside a skill, a rule may give only the start of a decision (`00R0:3`); the rule that called the skill names a
code, its `then`, that fills the tics left.
"""

from __future__ import annotations

from typing import List, Tuple, Union

TICS = 8

AXES = (
    ("walk", {"F": "walk forward", "0": "no walking", "B": "walk backward"}),
    ("strafe", {"L": "sidestep left", "0": "no sidestep", "R": "sidestep right"}),
    ("turn", {"L": "turn left", "0": "no turning", "R": "turn right"}),
    ("fire", {"1": "fire", "0": "no firing"}),
)
COMBOS = tuple("".join((w, s, t, f)) for w in "F0B" for s in "L0R" for t in "L0R" for f in "10")

# The actions that are not codes: the root's random walk, and a skill's own default, the caller's `then`.
RANDOM = "random"
THEN = "then"


class ActionError(ValueError):
    """An action that is not a code, a sequence adding up to one decision, or (inside a skill) less."""


def segments(action: str, partial: bool = False) -> List[Tuple[str, int]]:
    """The (code, tics) parts of an action. Outside a skill they add up to 8 tics; with `partial` (inside a
    skill) they may add up to less, and the caller's `then` does the rest."""
    if ":" not in action:
        if action not in COMBOS:
            raise ActionError(f"{action!r} is not one of the 54 codes")
        return [(action, TICS)]
    try:
        segs = [(code, int(tics)) for code, tics in (part.split(":") for part in action.split("+"))]
    except ValueError:
        raise ActionError(f"{action!r} is not CODE:TICS+CODE:TICS...") from None
    for code, tics in segs:
        if code not in COMBOS:
            raise ActionError(f"{code!r} in {action!r} is not one of the 54 codes")
        if tics < 1:
            raise ActionError(f"{action!r} holds {code} for {tics} tics")
    total = sum(t for _, t in segs)
    if total > TICS or (total < TICS and not partial):
        raise ActionError(f"{action!r} adds up to {total} tics; a decision is {TICS}" + ("" if partial else " outside a skill"))
    return segs


def complete(action: str, then: str) -> str:
    """A skill's action finished with the caller's `then` code for the tics left."""
    if action == THEN:
        return then
    left = TICS - sum(t for _, t in segments(action, partial=True))
    return action if left == 0 else f"{action}+{then}:{left}"


def buttons(code: str) -> List[int]:
    """ViZDoom's buttons for one code, in the order of deadly_corridor.cfg: MOVE_LEFT, MOVE_RIGHT, ATTACK,
    MOVE_FORWARD, MOVE_BACKWARD, TURN_LEFT, TURN_RIGHT."""
    w, s, t, f = code
    return [int(x) for x in (s == "L", s == "R", f == "1", w == "F", w == "B", t == "L", t == "R")]


def fires(action: str) -> bool:
    """Whether any part of a full action fires."""
    return any(code[3] == "1" for code, _ in segments(action))


def describe_code(code: str) -> str:
    """One code in words: "walk forward + fire"; `0000` is "stand still"."""
    parts = [AXES[i][1][v] for i, v in enumerate(code) if v != "0"]
    return " + ".join(parts) if parts else "stand still"


def describe(action: Union[str, dict]) -> str:
    """An action in words, as the site and the rule writer read it."""
    if isinstance(action, dict):
        return f"use skill {action['skill']}, then {describe_code(action['then'])}"
    if action == THEN:
        return "the caller's action"
    if action == RANDOM:
        return "a random code"
    segs = segments(action, partial=True)
    if len(segs) == 1 and segs[0][1] == TICS:
        return describe_code(segs[0][0])
    text = ", then ".join(f"{describe_code(c)} for {t} tics" for c, t in segs)
    return text if sum(t for _, t in segs) == TICS else text + ", then the caller's action"
