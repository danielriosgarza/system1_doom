"""Real time: the rule tree playing while the game goes on, as a player at the keyboard would.

In `play` (game.py) the game waits for every decision: the state is read, every question is answered, and only then
are the decision's 8 tics played. Here the game does not wait. It runs at 35 tics a second, and a decision made from
the state at tic t can only start once its answers are in, `lag` tics later; meanwhile the keys of the decision before
stay as they were.

    tics      0 ....... 8 ....... 16 ...... 24
    observe   s0        s8        s16                 a decision every 8 tics, as in play() ...
    plays     idle|a0   ...  |a8  ...  |a16 ...       ... each started `lag` tics after the state it read

A decision is asked from the state at most every 8 tics (as in play) and never before the last one is answered, so
with a lag under 8 tics every action plays its 8 tics in full, `lag` tics late; with a longer lag the decisions are
`lag` tics apart, and the tics between the end of one action and the start of the next follow `fill`:

    hold    keep pressing the action's last code (what a held key does)
    idle    release every key
    steady  keep walking, sidestepping and firing, but stop turning (a turn held on overshoots the aim)

Three ways to live with the lag, chosen with `cadence` and `predict`:

    pipeline    (the default) ask every 8 tics, while the last action is still playing. The state then does not show
                the rest of that action: an aim read at tic 8 is turned for again by the action started at tic 0+lag,
                so a lag near 8 tics turns twice for one angle, and the aim swings from side to side.
    sequential  ask once the last action has played its 8 tics, so every state shows the whole of the last action;
                a decision then takes 8 + lag tics, and the lag is spent in `fill`.
    predict     (with pipeline) before asking, shift every angle in the state by the turn the keys already chosen
                will make before the answer is in (an efference copy: the turn is known, so it need not be seen).
    track       (with pipeline) the tree picks what to aim at and what to do once aimed; a reflex turns toward it
                every tic from the engine's positions, which need no question. An action that went through the aim
                skill presses its turn while the focus is more than 3 degrees off (the skill's narrowest band) and
                its `then` code otherwise, through its 8 tics and the fill after them.

The state's counters (decisions so far, under fire, stall streak, fruitless firing) and the outcome of each stretch
are kept per 8 tics of game time, whatever the lag, so the state reads as it did in training; the history names the
keys pressed in those 8 tics, which can be the end of one action and the start of the next.

Two clocks:

- `lag=N`: the game is held while the tree is walked, then N tics are played before the answer is used. The same
  answers give the same game, and `lag=0` is `play()` exactly. `lag=(lo, hi)` draws each decision's lag from lo to hi
  tics, a reaction time that varies from one decision to the next; the draw depends on the seed and the decision's
  number only, so a replay draws the same.
- `lag=None`: the wall clock. The walk runs on its own thread while the game plays tic by tic, held to 35 tics a
  second; an answer is used at the first tic after it arrives. If the game itself falls behind the clock (reading the
  state takes a few milliseconds), the missing tics are played at once with the keys as they are.
"""

from __future__ import annotations

import json
import math
import random
import re
import statistics
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from system1_doom.evidence import enemy_line, landmark_line, shown_enemies, shown_landmarks

from .codes import TICS, buttons, segments
from .game import Game
from .tree import RuleTree
from .walk import Decision, Jev, decide

TIC_RATE = 35  # Doom's tics a second
IDLE = "0000"
FILLS = ("hold", "idle", "steady")
CADENCES = ("pipeline", "sequential")
EXPECTED_LAG = 6  # tics, on the wall clock, until a few answers have been timed


# Doom turns 320 angle units a tic for the first 5 tics a turn key is held, then 640 (measured on deadly_corridor).
SLOW_TURN, FAST_TURN, SLOW_TICS = 360 * 320 / 65536, 360 * 640 / 65536, 5
ANGLE = re.compile(r"(\d+(?:\.\d+)?) deg (left|right)|straight ahead")
TURNED_CHANNELS = ("threats", "pickups", "landmarks")
DEADBAND = 3.0  # degrees off the focus a tracked action still turns at


def turned(codes: Sequence[str], held: int = 0) -> float:
    """Degrees the view turns over these tics (left positive), `held` tics of turning already behind the first."""
    total = 0.0
    for code in codes:
        if code[2] == "0":
            held = 0
            continue
        held += 1
        total += (SLOW_TURN if held <= SLOW_TICS else FAST_TURN) * (1 if code[2] == "L" else -1)
    return total


def held_turning(codes: Sequence[str]) -> int:
    """How many of the last tics in a row a turn key was held."""
    n = 0
    for code in reversed(codes):
        if code[2] == "0":
            break
        n += 1
    return n


def shifted(text: str, turn: float) -> str:
    """The state as it will read once the view has turned `turn` degrees (left positive): every angle of the threats,
    pickups and landmarks, which are offsets from the facing, less the turn. Distances and the rest stay as read."""
    if abs(turn) < 0.5:
        return text

    def one(m: "re.Match[str]") -> str:
        offset = 0.0 if m.group(0) == "straight ahead" else float(m.group(1)) * (1 if m.group(2) == "left" else -1)
        new = offset - turn
        magnitude = f"{abs(new):.0f}"
        return "straight ahead" if magnitude == "0" else f"{magnitude} deg {'left' if new > 0 else 'right'}"

    out = []
    for block in text.split("\n\n"):
        head = block.split("\n", 1)[0]
        if head.strip("[]") in TURNED_CHANNELS:
            block = ANGLE.sub(one, block)
        out.append(block)
    return "\n\n".join(out)


def target_of(inputs: Any, d: Decision) -> Optional[Tuple[str, Any]]:
    """What a decision's last focus picked, as the engine knows it: an enemy's object id, or a remembered pickup's
    position. None when the walk picked no focus."""
    picks = [s.pick for s in d.steps if s.kind == "focus" and s.pick]
    if not picks or inputs is None or "aim" not in d.route.split("/"):
        return None
    for e in shown_enemies(inputs):
        if enemy_line(e, inputs.state.screen_width) == picks[-1]:
            return ("enemy", int(e.id.rsplit("_", 1)[1]))
    for m in shown_landmarks(inputs):
        if landmark_line(m, inputs.state.tick) == picks[-1]:
            return ("point", (m.x, m.y))
    return None


def tracking(then: str, bearing: Optional[float]) -> str:
    """A tracked action's code this tic: turn toward the focus while it is more than DEADBAND off, else `then`."""
    if bearing is None or abs(bearing) <= DEADBAND:
        return then
    return "00" + ("L" if bearing > 0 else "R") + "0"


def per_tic(action: str) -> List[str]:
    """The code pressed at each of an action's 8 tics."""
    return [code for code, tics in segments(action) for _ in range(tics)]


def run_length(codes: Sequence[str]) -> str:
    """Tics pressed, as an action: one code, or `CODE:TICS+CODE:TICS` when the keys changed."""
    runs: List[List[Any]] = []
    for c in codes:
        if runs and runs[-1][0] == c:
            runs[-1][1] += 1
        else:
            runs.append([c, 1])
    if len(runs) == 1 and runs[0][1] == TICS:
        return runs[0][0]
    return "+".join(f"{c}:{n}" for c, n in runs)


def filled(code: str, fill: str) -> str:
    """The code pressed after an action's 8 tics, until the next action starts."""
    if fill == "hold":
        return code
    if fill == "idle":
        return IDLE
    if fill == "steady":
        return code[:2] + "0" + code[3]
    raise ValueError(f"fill is one of {FILLS}, not {fill!r}")


@dataclass
class Pending:
    """A decision being made: the state it reads and when its answer is (or will be) in."""

    i: int
    observed: int  # the tic of the state it reads
    inputs: Any = None  # what the state was rendered from
    decision: Optional[Decision] = None
    future: Optional[Future] = None
    ready_at: Optional[int] = None  # with a fixed lag, the tic its answer is used
    seconds: float = 0.0


@dataclass
class Plan:
    """The action being played and the tic it started at."""

    codes: List[str]
    start: int
    record: Dict[str, Any] = field(default_factory=dict)
    target: Optional[Tuple[str, Any]] = None  # with track: what the focus picked


def play_realtime(
    game: Game,
    tree: RuleTree,
    jev: Jev,
    seed: int,
    lag: Union[None, int, Tuple[int, int]] = None,
    fill: str = "hold",
    cadence: str = "pipeline",
    predict: bool = False,
    track: bool = False,
    tic_rate: float = TIC_RATE,
    keep_text: bool = False,
    stop_on_event: bool = True,
    max_tics: Optional[int] = None,
) -> Dict[str, Any]:
    """One game in real time (`lag=None`, the wall clock) or with a fixed lag of `lag` tics; its record: every
    decision (when its state was read, when its action started, what the walk did) and every 8 tics of game time
    (`windows`, each with the outcome and events of a decision of `play`)."""
    if fill not in FILLS:
        raise ValueError(f"fill is one of {FILLS}, not {fill!r}")
    lo, hi = (lag, lag) if lag is None or isinstance(lag, int) else lag
    if lag is not None and not 0 <= lo <= hi:
        raise ValueError(f"a lag is 0 tics or more, and a range runs from low to high, not {lag!r}")
    if cadence not in CADENCES:
        raise ValueError(f"cadence is one of {CADENCES}, not {cadence!r}")
    if (predict or track) and cadence != "pipeline":
        raise ValueError("predict and track are ways to ask while the last action plays: they go with pipeline")
    game.reset(seed)
    pool = ThreadPoolExecutor(1, thread_name_prefix="walk") if lag is None else None
    decisions: List[Dict[str, Any]] = []
    windows: List[Dict[str, Any]] = []
    t, next_ask, late = 0, 0, 0
    plan: Optional[Plan] = None
    pending: Optional[Pending] = None
    pressed: List[str] = []
    texts: Dict[int, str] = {}
    predicted: Dict[int, float] = {}
    pressed_all: List[str] = []  # every tic's keys, for the turn held so far
    before = game.begin()
    clock0 = time.perf_counter()

    def answered() -> bool:
        if pending is None:
            return False
        if pending.future is not None:
            return pending.future.done()
        return pending.ready_at is not None and t >= pending.ready_at

    def adopt() -> None:
        nonlocal plan, pending, next_ask
        assert pending is not None
        if pending.future is not None:
            pending.decision, pending.seconds = pending.future.result()
        d = pending.decision
        assert d is not None
        if plan is not None:
            played = t - plan.start
            plan.record.update(played=played, cut=max(0, TICS - played), filled=max(0, played - TICS))
        rec = {"i": pending.i, "observed": pending.observed, "start": t, "lag": t - pending.observed,
               "seconds": round(pending.seconds, 4),
               "code": d.action, "node": d.node, "route": d.route, "missed": d.missed,
               "steps": [s.model_dump(exclude_none=True) for s in d.steps]}
        if keep_text:
            rec["text"] = texts[pending.i]
        if pending.i in predicted:
            rec["predicted_turn"] = predicted[pending.i]
        target = target_of(pending.inputs, d) if track else None
        if target is not None:
            rec["target"] = [target[0], target[1]]
        decisions.append(rec)
        plan = Plan(per_tic(d.action), t, rec, target)
        pending = None
        if cadence == "sequential":
            next_ask = t + TICS

    def walk(text: str, frame: str, i: int) -> Tuple[Decision, float]:
        t0 = time.perf_counter()
        return decide(tree, jev, text, frame, seed, i), time.perf_counter() - t0

    def coming(n: int) -> List[str]:
        """The keys of the next `n` tics if no new action starts: the rest of the one playing, then the fill."""
        if plan is None:
            return [IDLE] * n
        done = t - plan.start
        rest = plan.codes[done:] if done < TICS else []
        return (rest + [filled(plan.codes[-1], fill)] * n)[:n]

    def ask() -> None:
        nonlocal pending, next_ask
        text, frame = game.observe()
        i = len(decisions)
        if predict:
            recent = [d["lag"] for d in decisions[-5:]]
            expect = (lo + hi) // 2 if lag is not None else (int(statistics.median(recent)) if recent else EXPECTED_LAG)
            turn = turned(coming(expect), held_turning(pressed_all))
            text = shifted(text, turn)
            predicted[i] = round(turn, 2)
        if keep_text:
            texts[i] = text
        pending = Pending(i=i, observed=t, inputs=game.last_inputs if track else None)
        if pool is not None:
            pending.future = pool.submit(walk, text, frame, i)
        else:
            pending.decision, pending.seconds = walk(text, frame, i)
            pending.ready_at = t + (lo if lo == hi else random.Random(f"{seed}:{i}:lag").randint(lo, hi))
        next_ask = t + TICS if cadence == "pipeline" else 1 << 30

    try:
        while True:
            if len(pressed) == TICS:
                rec = game.end(run_length(pressed), before)
                rec.update(w=len(windows), tic=t, max_x=round(game.max_x[-1]))
                rec["events"] = game.events(rec)
                rec["cleared"] = rec["finished"] and not rec["events"]
                windows.append(rec)
                if rec["finished"] or (stop_on_event and rec["events"]) or (max_tics is not None and t >= max_tics):
                    break
                pressed, before = [], game.begin()
            while True:
                if answered():
                    adopt()
                elif pending is None and t >= next_ask:
                    ask()
                else:
                    break
            if plan is None:
                code = IDLE
            elif plan.target is not None:
                code = tracking(plan.codes[-1], game.bearing(plan.target))
            elif t - plan.start < TICS:
                code = plan.codes[t - plan.start]
            else:
                code = filled(plan.codes[-1], fill)
            n = 1
            if pool is not None:
                # Tics the game is behind the clock are played now, with the keys as they are.
                due = int((time.perf_counter() - clock0) * tic_rate)
                n = max(1, min(due - t, TICS - len(pressed)))
                late += n - 1
            game.press(buttons(code), n)
            pressed += [code] * n
            pressed_all.extend([code] * n)
            t += n
            if game.g.is_episode_finished():
                rec = game.end(run_length(pressed), before)
                rec.update(w=len(windows), tic=t, max_x=round(game.max_x[-1]))
                rec["events"] = game.events(rec)
                rec["cleared"] = rec["finished"] and not rec["events"]
                windows.append(rec)
                break
            if pool is not None:
                wait = clock0 + t / tic_rate - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
    if plan is not None and "played" not in plan.record:
        played = t - plan.start
        plan.record.update(played=played, cut=0, filled=max(0, played - TICS))
    return {"seed": seed, "lag": lag, "fill": fill, "cadence": cadence, "predict": predict, "track": track, "tics": t, "late_tics": late,
            "seconds": round(time.perf_counter() - clock0, 2), "decisions": decisions, "windows": windows}


def outcome_of(record: Dict[str, Any]) -> str:
    """How a real-time game ended: cleared, died, stalled, timed out, or (cut short) none."""
    last = record["windows"][-1]
    if last["events"]:
        return last["events"][0]
    return "cleared" if last.get("cleared") else "none"


def summary(record: Dict[str, Any]) -> Dict[str, Any]:
    """One line of a real-time evaluation."""
    decisions, last = record["decisions"], record["windows"][-1]
    asked = [s for d in decisions for s in d["steps"] if "answer" in s and not s["answer"].get("cached")]
    lags = [d["lag"] for d in decisions]
    return {
        "seed": record["seed"], "event": outcome_of(record), "windows": len(record["windows"]), "decisions": len(decisions),
        "max_x": last["max_x"], "health": last["health_after"], "kills": max((w.get("kills", 0) for w in record["windows"]), default=0),
        "calls": len(asked), "misses": sum(1 for s in asked if s["answer"].get("miss")),
        "lag_median": statistics.median(lags) if lags else None, "lag_max": max(lags) if lags else None,
        "walk_ms_median": round(1000 * statistics.median(d["seconds"] for d in decisions), 1) if decisions else None,
        "cut": sum(d.get("cut", 0) for d in decisions), "filled": sum(d.get("filled", 0) for d in decisions),
        "late_tics": record["late_tics"], "seconds": record["seconds"],
    }


def evaluate(run: Any, seeds: Sequence[int], lag: Union[None, int, Tuple[int, int]], fill: str = "hold", label: str = "",
             tree: Optional[RuleTree] = None, cadence: str = "pipeline", predict: bool = False,
             track: bool = False) -> List[Dict[str, Any]]:
    """Play every seed once in real time with fresh answers; each game is kept in `<run>/realtime/<label>s<seed>.json`.
    On the wall clock the games are played one after another, so that no other game's questions wait on the model in
    front of them; with a fixed lag, `run.workers` at a time."""
    tree = tree if tree is not None else run.tree()
    out = run.folder / "realtime"
    out.mkdir(parents=True, exist_ok=True)

    def one(seed: int) -> Dict[str, Any]:
        jev = run.jev(read=False)
        game = run._borrow()
        try:
            record = play_realtime(game, tree, jev, seed, lag=lag, fill=fill, cadence=cadence, predict=predict,
                                   track=track)
        except Exception as exc:  # noqa: BLE001 - a crashed game is reported with the others, not raised
            run._discard(game)
            return {"seed": seed, "event": "crashed", "error": f"{type(exc).__name__}: {exc}"[:500]}
        run._idle.put(game)
        (out / f"{label}s{seed}.json").write_text(json.dumps({"tree": tree.name, **record}), encoding="utf-8")
        return summary(record)

    if lag is None:
        return [one(s) for s in seeds]
    with ThreadPoolExecutor(run.workers) as pool:
        return list(pool.map(one, seeds))


def lag_tics(seconds: float, tic_rate: float = TIC_RATE) -> int:
    """A walk's time in tics: the first tic after it is done."""
    return math.ceil(seconds * tic_rate)
