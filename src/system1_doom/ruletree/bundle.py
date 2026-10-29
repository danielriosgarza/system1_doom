"""A rule-tree recording: one episode played by a tree, written as a folder the website reads.

    episode.json      RuleTreeEpisodeMeta: the tree, the seed, the decider (Jev, or a local model: Laya, Kev) and the
                      model asked, how the episode ended, the decider's calls, cost and misses
    decisions.jsonl   one RuleTreeDecision per decision: the state text the decider was sent, every step of the walk with
                      its question, options, probabilities and pick, the action played and what followed
    tree.json         the tree as played, with cornerstones/ (the screen each rule was written from)
    build.jsonl       the soft loop's record of how the tree was written, when the tree has one
    frames/00042.jpg  the screen at decision 42 (320x240 JPEG; Jev is sent it, Laya and Kev read text only)
    frames/end.jpg    the screen after the last action

The episode is played from the start to its end (cleared, died or timed out), with fresh answers. A stall does not
stop it, as it stops a game of the soft loop; the decision where the soft loop would have stopped is in the result.

A real-time recording (`record_realtime_episode`) is the same folder for a game the game did not wait in
(`realtime.py`): episode.json names how it was played (`realtime`), and each decision also says when its state was
read and its action began, what the helper aimed at, and the keys pressed until the next action began.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import shutil
import time
from typing import Any, Callable, Dict, List, Literal, Optional

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from system1_doom.d1_client import D1UltraClient
from system1_doom.logger import TRACE_SCHEMA_VERSION

from .codes import TICS, describe, describe_code, segments
from .game import SCENARIO, Game, outcome, play
from .tree import ROOT, RuleTree, load_tree, save_tree
from .walk import DEFAULT_BUDGET, AnswerBook, Jev, action_of

SOLUTION = "rule-tree"
FRAME_DIR = "frames"
END_FRAME = "frames/end.jpg"
DECISIONS_FILE = "decisions.jsonl"
BUILD_FILE = "build.jsonl"


def _package_version() -> str:
    try:
        return importlib.metadata.version("system1-doom")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


class RecordedAnswer(BaseModel):
    """Jev's answer to one question of a walk, or a miss."""

    model_config = ConfigDict(frozen=True)

    probabilities: Dict[str, float] = Field(default_factory=dict, description="Jev's probability for each option, by option key")
    pick: Optional[str] = Field(default=None, description="The option with the highest probability; None on a miss")
    miss: Optional[str] = Field(default=None, description="Why the call failed (timeout, http_error, malformed, off_menu, ...)")
    error: Optional[str] = None
    latency_ms: float = 0.0
    cost: float = 0.0
    cached: bool = Field(default=False, description="Asked earlier in this game with the same text, screen and options: no call")


class WalkStep(BaseModel):
    """One step of a decision's walk down the tree."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["rule", "focus", "skill"] = Field(
        description="rule: Jev chose one of a node's children, or none; focus: Jev picked one listed item; skill: the "
        "walk went on in a skill"
    )
    node: str = Field(description="The node asked at; for a skill, the rule that called it")
    skill: Optional[str] = None
    question: Optional[str] = None
    options: Dict[str, str] = Field(default_factory=dict, description="Option key to its text: a child's id to its condition, "
                                    "`none` to 'None of these is true right now.', or `i0`, `i1`, ... to a listed item")
    answer: Optional[RecordedAnswer] = Field(default=None, description="None for a skill, and for a focus with one item or none")
    pick: Optional[str] = Field(default=None, description="rule: the child picked, or none; focus: the item picked")
    focus_line: Optional[str] = Field(default=None, description="focus: the line the later questions read under [focus]")


class ActionSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(description="Four letters: walk (F, 0, B), sidestep (L, 0, R), turn (L, 0, R), fire (1, 0)")
    tics: int
    words: str


class RuleTreeDecision(BaseModel):
    """One line of `decisions.jsonl`: what Jev was shown, how the walk went, the action played and what followed."""

    model_config = ConfigDict(frozen=True)

    decision: int = Field(description="0 for the first decision")
    state_text: str = Field(
        description="The state as the decision's first question read it. After a focus step, the later questions read "
        "it with '\\n\\n[focus]\\n' and that step's focus_line appended."
    )
    frame: str = Field(description="The screen Jev was sent with every question of the decision, a path in the bundle")
    steps: List[WalkStep]
    node: str = Field(description="The node the walk reached, whose action was played")
    route: str = Field(description="Every rule the walk went into and every skill it entered, joined by '/'")
    action: str
    action_words: str
    segments: List[ActionSegment]
    missed: bool = Field(description="A call failed, so the walk stopped at the node it had reached")
    calls: int
    cost: float
    latency_ms: float = Field(description="The decision's calls, one after another, in milliseconds")
    health_before: float
    health_after: float
    armor: Optional[float] = Field(default=None, description="After the action; None when it ended the episode")
    kills: Optional[float] = None
    x: Optional[int] = None
    y: Optional[int] = None
    angle: Optional[int] = None
    reward: float
    max_x: int = Field(description="The furthest point reached along the corridor so far")
    observed_tic: Optional[int] = Field(default=None, description="Real time: the tic the state was read at")
    start_tic: Optional[int] = Field(default=None, description="Real time: the tic the action began at, once the answers were in")
    walk_ms: Optional[float] = Field(default=None, description="Real time: how long the walk took, in milliseconds")
    target: Optional[str] = Field(default=None, description="Real time: what the helper aimed at, as the focus named it")
    after: Optional[str] = Field(default=None, description="Real time: the code the rule plays once its focus is dead")
    pressed: List[ActionSegment] = Field(default_factory=list, description="Real time: the keys pressed from this "
                                         "action's start to the next one's (the helper's turns and taps included)")
    events: List[str] = Field(description="died, timed out, or stalled (less than 48 units further in 24 decisions)")
    finished: bool
    died: bool
    cleared: bool


class RuleTreeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Literal["cleared", "died", "timed out"]
    cleared: bool
    died: bool
    decisions: int
    health: float
    kills: float
    reward: float
    max_x: int
    stalled_at: Optional[int] = Field(default=None, description="The first decision marked stalled, where a game of the "
                                      "soft loop would have stopped; None when there was none")


class RuleTreeFrames(BaseModel):
    model_config = ConfigDict(frozen=True)

    dir: str = FRAME_DIR
    pattern: str = "{decision:05d}.jpg"
    width: int = 320
    height: int = 240
    end_frame: Optional[str] = None


class RealtimeSettings(BaseModel):
    """How a real-time recording was played (`realtime.play_realtime`)."""

    model_config = ConfigDict(frozen=True)

    clock: Literal["wall", "fixed"] = Field(description="wall: the game ran at 35 tics a second while the walk ran; fixed: "
                                            "the game was held for the walk, then `lag` tics were played")
    lag: Optional[List[int]] = Field(default=None, description="fixed: the lag in tics, low and high")
    track: Optional[str] = Field(default=None, description="screen: the fair helper aimed; engine: the helper read the engine")
    aim: Optional[str] = None
    fire: Optional[str] = None
    reflex: Optional[int] = Field(default=None, description="Tics the helper sees late")
    tics: int = Field(description="Game tics played")
    late_tics: int = Field(default=0, description="Tics the game fell behind the clock and played at once")
    lag_median: float = Field(description="Median tics from a state to its action")
    walk_ms_median: float = Field(description="Median time of a walk, in milliseconds")


class RuleTreeEpisodeMeta(BaseModel):
    """`episode.json` of a rule-tree recording."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = TRACE_SCHEMA_VERSION
    solution: Literal["rule-tree"] = SOLUTION
    name: str
    title: str
    scenario: str
    seed: int
    decider: Literal["jev", "laya", "kev"] = Field(
        default="jev", description="Who answered every question: Jev, or a model on this machine (Laya, Kev)"
    )
    model: Optional[str] = Field(
        default=None, description="The model asked, as the requests named it (a Laya checkpoint, kev-latest); none in "
                                  "recordings made before it was kept"
    )
    models: Dict[str, int] = Field(description="Answers per model, as the responses named it")
    tree: str
    tree_writer: str
    rules: int = Field(description="The tree's nodes, without the root and the tops of its skills")
    decision_tics: int = Field(default=TICS, description="How long one decision holds its keys, in tics (35 a second)")
    call_budget_sec: float
    result: RuleTreeResult
    calls: int
    cost: float
    misses: int = Field(description="Calls that failed; each stopped its walk where it was")
    decision_count: int
    seconds: float = Field(description="Wall-clock time of the episode, Jev's calls included")
    frames: RuleTreeFrames
    files: List[str]
    package_version: str = Field(default_factory=_package_version)
    recorded_at: str
    realtime: Optional[RealtimeSettings] = Field(default=None, description="Played without holding the game for the "
                                                 "answers; None for a recording that held it")


def recording_game() -> Game:
    """The game as a recording plays it: the same game, keeping the screen after the last action."""
    return Game(keep_screen=True)


def _write_jpeg(screen: np.ndarray, path: Path) -> None:
    arr = np.asarray(screen, dtype=np.uint8)
    if arr.ndim == 3 and arr.shape[0] in (1, 3, 4) and arr.shape[2] not in (1, 3, 4):
        arr = np.transpose(arr, (1, 2, 0))
    image = Image.fromarray(arr)
    if image.size != (320, 240):
        image = image.resize((320, 240), Image.Resampling.BILINEAR)
    image.save(path, format="JPEG", quality=75)


def action_words(action: str) -> str:
    """The action in words for the site. The state's history channel says "for 1 tics", as Jev has always read it;
    the site says "for 1 tic"."""
    return describe(action).replace(" for 1 tics", " for 1 tic")


def rule_count(tree: RuleTree) -> int:
    return sum(1 for nid in tree.nodes if nid != ROOT and nid not in tree.skills)


def _decision(rec: Dict[str, Any]) -> RuleTreeDecision:
    steps = [WalkStep.model_validate(s) for s in rec["steps"]]
    called = [s.answer for s in steps if s.answer is not None and not s.answer.cached]
    return RuleTreeDecision(
        decision=rec["i"],
        state_text=rec["text"],
        frame=f"{FRAME_DIR}/{rec['i']:05d}.jpg",
        steps=steps,
        node=rec["node"],
        route=rec["route"],
        action=rec["code"],
        action_words=action_words(rec["code"]),
        segments=[ActionSegment(code=c, tics=t, words=describe_code(c)) for c, t in segments(rec["code"])],
        missed=rec["missed"],
        calls=len(called),
        cost=round(sum(a.cost for a in called), 9),
        latency_ms=round(sum(a.latency_ms for a in called), 1),
        health_before=rec["health_before"],
        health_after=rec["health_after"],
        armor=rec.get("armor"),
        kills=rec.get("kills"),
        x=rec.get("x"),
        y=rec.get("y"),
        angle=rec.get("angle"),
        reward=rec["reward"],
        max_x=rec["max_x"],
        events=rec["events"],
        finished=rec["finished"],
        died=rec["died"],
        cleared=rec["cleared"],
    )


def default_title(tree: RuleTree, seed: int) -> str:
    return f"deadly corridor, rule tree {tree.name}, seed {seed}"


def record_episode(
    tree: RuleTree,
    seed: int,
    out: Path,
    client: D1UltraClient,
    name: Optional[str] = None,
    title: Optional[str] = None,
    budget: float = DEFAULT_BUDGET,
    game_factory: Callable[[], Game] = recording_game,
) -> RuleTreeEpisodeMeta:
    """Play one seeded episode with the tree, every decision the client's decider's, and write it as a recording in
    `out`."""
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; choose another --out or remove it first")
    jev = Jev(client, AnswerBook(), budget)
    game = game_factory()
    t0 = time.monotonic()
    try:
        trace = play(game, tree, jev, seed, stop_on_event=False)
        last_screen = getattr(game, "last_screen", None)
    finally:
        game.close()
    seconds = round(time.monotonic() - t0, 1)

    (out / FRAME_DIR).mkdir(parents=True, exist_ok=True)
    decisions = [_decision(rec) for rec in trace]
    for rec, d in zip(trace, decisions):
        (out / d.frame).write_bytes(base64.b64decode(rec["frame"]))
    end_frame = None
    if last_screen is not None:
        _write_jpeg(last_screen, out / END_FRAME)
        end_frame = END_FRAME
    (out / DECISIONS_FILE).write_text("".join(d.model_dump_json() + "\n" for d in decisions), encoding="utf-8")
    home = tree._home
    save_tree(tree.clone(), out)  # a clone: saving moves a tree's home to the folder it is saved in
    files = [DECISIONS_FILE, "tree.json"]
    if home is not None and (home / BUILD_FILE).is_file():
        shutil.copyfile(home / BUILD_FILE, out / BUILD_FILE)
        files.append(BUILD_FILE)

    last = trace[-1]
    stalls = [rec["i"] for rec in trace if "stalled" in rec["events"]]
    meta = RuleTreeEpisodeMeta(
        name=name or out.name,
        title=title or default_title(tree, seed),
        scenario=SCENARIO,
        seed=seed,
        decider=client.decider.name,
        model=client.model,
        models=client.models_answered(),
        tree=tree.name,
        tree_writer=tree.writer,
        rules=rule_count(tree),
        call_budget_sec=budget,
        result=RuleTreeResult(
            outcome=outcome(trace),
            cleared=bool(last["cleared"]),
            died=bool(last["died"]),
            decisions=len(trace),
            health=last["health_after"],
            kills=next((rec["kills"] for rec in reversed(trace) if rec.get("kills") is not None), 0.0),
            reward=round(sum(rec["reward"] for rec in trace), 1),
            max_x=last["max_x"],
            stalled_at=stalls[0] if stalls else None,
        ),
        calls=sum(d.calls for d in decisions),
        cost=round(sum(d.cost for d in decisions), 9),
        misses=sum(1 for d in decisions for s in d.steps if s.answer is not None and s.answer.miss),
        decision_count=len(decisions),
        seconds=seconds,
        frames=RuleTreeFrames(end_frame=end_frame),
        files=files,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    (out / "episode.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return meta


def _tics(windows: List[Dict[str, Any]]) -> List[str]:
    """The code pressed at every tic of a real-time game, from its stretches of 8 tics."""
    return [c for w in windows for c, n in segments(w["code"], partial=True) for _ in range(n)]


def _window_at(windows: List[Dict[str, Any]], tic: int) -> Optional[Dict[str, Any]]:
    done = [w for w in windows if w["tic"] <= tic]
    return done[-1] if done else None


def _runs(codes: List[str]) -> List[ActionSegment]:
    out: List[List[Any]] = []
    for c in codes:
        if out and out[-1][0] == c:
            out[-1][1] += 1
        else:
            out.append([c, 1])
    return [ActionSegment(code=c, tics=n, words=describe_code(c)) for c, n in out]


def _realtime_decisions(record: Dict[str, Any]) -> List[RuleTreeDecision]:
    """The decisions of a real-time game, each with what followed until the next one's state was read."""
    windows, decs = record["windows"], record["decisions"]
    tics, last = _tics(windows), windows[-1]
    out = []
    for k, d in enumerate(decs):
        final = k == len(decs) - 1
        until = record["tics"] if final else decs[k + 1]["observed"]
        w0, w1 = _window_at(windows, d["observed"]), (last if final else _window_at(windows, until))
        h0 = w0["health_after"] if w0 else 100.0
        h1 = w1["health_after"] if w1 else h0
        between = [w for w in windows if d["observed"] < w["tic"] <= until or (final and w is last)]
        next_start = record["tics"] if final else decs[k + 1]["start"]
        later = w1 or {}
        rec = {
            **d, "text": d["text"], "health_before": h0, "health_after": h1, "armor": later.get("armor"),
            "kills": later.get("kills"), "x": later.get("x"), "y": later.get("y"), "angle": later.get("angle"),
            "reward": round(sum(w["reward"] for w in between), 1), "max_x": (w1 or {"max_x": 0})["max_x"],
            "events": sorted({e for w in between for e in w["events"]}), "finished": bool(final and last["finished"]),
            "died": bool(final and last.get("died")), "cleared": bool(final and last.get("cleared")),
        }
        target = None
        if d.get("target"):
            picks = [s.get("focus_line") or s.get("pick") for s in d["steps"] if s["kind"] == "focus" and s.get("pick")]
            target = picks[-1] if picks else f"{d['target'][0]} {d['target'][1]}"
        base = _decision(rec)
        out.append(base.model_copy(update={
            "observed_tic": d["observed"], "start_tic": d["start"], "walk_ms": round(1000 * d["seconds"], 1),
            "target": target, "after": d.get("after"), "pressed": _runs(tics[d["start"]:next_start]),
        }))
    return out


def record_realtime_episode(
    tree: RuleTree,
    seed: int,
    out: Path,
    client: D1UltraClient,
    settings: Dict[str, Any],
    name: Optional[str] = None,
    title: Optional[str] = None,
    budget: float = DEFAULT_BUDGET,
    game_factory: Callable[[], Game] = recording_game,
) -> RuleTreeEpisodeMeta:
    """Play one seeded episode in real time (`settings` as `realtime.play_realtime` takes them; `lag` None is the wall
    clock) and write it as a recording in `out`."""
    from .realtime import play_realtime  # realtime imports this package's game; imported here to keep bundle light

    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; choose another --out or remove it first")
    jev = Jev(client, AnswerBook(), budget)
    game = game_factory()
    t0 = time.monotonic()
    try:
        record = play_realtime(game, tree, jev, seed, keep_text=True, keep_frames=True, stop_on_event=False, **settings)
        last_screen = getattr(game, "last_screen", None)
    finally:
        game.close()
    seconds = round(time.monotonic() - t0, 1)

    (out / FRAME_DIR).mkdir(parents=True, exist_ok=True)
    decisions = _realtime_decisions(record)
    for d, raw in zip(decisions, record["decisions"]):
        (out / d.frame).write_bytes(base64.b64decode(raw["frame"]))
    end_frame = None
    if last_screen is not None:
        _write_jpeg(last_screen, out / END_FRAME)
        end_frame = END_FRAME
    (out / DECISIONS_FILE).write_text("".join(d.model_dump_json() + "\n" for d in decisions), encoding="utf-8")
    home = tree._home
    save_tree(tree.clone(), out)
    files = [DECISIONS_FILE, "tree.json"]
    if home is not None and (home / BUILD_FILE).is_file():
        shutil.copyfile(home / BUILD_FILE, out / BUILD_FILE)
        files.append(BUILD_FILE)

    last = record["windows"][-1]
    stalls = [d.decision for d in decisions if "stalled" in d.events]
    lag = settings.get("lag")
    lags = sorted(d["lag"] for d in record["decisions"])
    walks = sorted(1000 * d["seconds"] for d in record["decisions"])
    events = last["events"]
    meta = RuleTreeEpisodeMeta(
        name=name or out.name,
        title=title or f"deadly corridor in real time, rule tree {tree.name}, seed {seed}",
        scenario=SCENARIO,
        seed=seed,
        decider=client.decider.name,
        model=client.model,
        models=client.models_answered(),
        tree=tree.name,
        tree_writer=tree.writer,
        rules=rule_count(tree),
        call_budget_sec=budget,
        result=RuleTreeResult(
            outcome=events[0] if events and events[0] in ("died", "timed out") else ("cleared" if last.get("cleared") else "died"),
            cleared=bool(last.get("cleared")),
            died=bool(last.get("died")),
            decisions=len(decisions),
            health=last["health_after"],
            kills=next((w["kills"] for w in reversed(record["windows"]) if w.get("kills") is not None), 0.0),
            reward=round(sum(w["reward"] for w in record["windows"]), 1),
            max_x=last["max_x"],
            stalled_at=stalls[0] if stalls else None,
        ),
        calls=sum(d.calls for d in decisions),
        cost=round(sum(d.cost for d in decisions), 9),
        misses=sum(1 for d in decisions for s in d.steps if s.answer is not None and s.answer.miss),
        decision_count=len(decisions),
        seconds=seconds,
        frames=RuleTreeFrames(end_frame=end_frame),
        files=files,
        recorded_at=datetime.now(timezone.utc).isoformat(),
        realtime=RealtimeSettings(
            clock="wall" if lag is None else "fixed",
            lag=None if lag is None else ([lag, lag] if isinstance(lag, int) else list(lag)),
            track=settings.get("track"), aim=settings.get("aim"), fire=settings.get("fire"), reflex=settings.get("reflex"),
            tics=record["tics"], late_tics=record["late_tics"],
            lag_median=float(lags[len(lags) // 2]) if lags else 0.0,
            walk_ms_median=round(walks[len(walks) // 2], 1) if walks else 0.0,
        ),
    )
    (out / "episode.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return meta


def check_recording(bundle: Path, raw: Optional[Dict[str, Any]] = None) -> List[str]:
    """Validate a rule-tree recording: every decision has a walk, the action played is the action of the node the walk
    reached, and every file and frame exists. Returns the problems (empty when it is valid)."""
    problems: List[str] = []
    try:
        raw = raw if raw is not None else json.loads((bundle / "episode.json").read_text(encoding="utf-8"))
        meta = RuleTreeEpisodeMeta.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a reported problem
        return [f"episode.json: {exc}"]
    try:
        tree = load_tree(bundle)
    except Exception as exc:  # noqa: BLE001
        return problems + [f"tree.json: {exc}"]
    decisions: List[RuleTreeDecision] = []
    for i, line in enumerate((bundle / DECISIONS_FILE).read_text(encoding="utf-8").splitlines()):
        try:
            decisions.append(RuleTreeDecision.model_validate_json(line))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{DECISIONS_FILE} line {i + 1}: {exc}")
    if len(decisions) != meta.decision_count:
        problems.append(f"{DECISIONS_FILE} has {len(decisions)} decisions, episode.json says {meta.decision_count}")
    for n, d in enumerate(decisions):
        where = f"decision {d.decision}"
        if d.decision != n:
            problems.append(f"{where}: expected decision {n}")
        if d.node not in tree.nodes:
            problems.append(f"{where}: reached {d.node}, which is not in tree.json")
            continue
        if not d.steps and tree.nodes[ROOT].children:
            problems.append(f"{where}: no walk")
        asked = [s for s in d.steps if s.kind == "rule"]
        if not d.missed and asked and asked[-1].pick is None:
            problems.append(f"{where}: the last question has no pick, but nothing missed")
        then = next((tree.nodes[s.node].action.then for s in reversed(d.steps) if s.kind == "skill"), None)  # type: ignore[union-attr]
        try:
            expected = action_of(tree.nodes[d.node], then, meta.seed, d.decision)
        except ValueError as exc:
            problems.append(f"{where}: {exc}")
            continue
        if d.action != expected:
            problems.append(f"{where}: played {d.action}, but {d.node} gives {expected}")
        if not (bundle / d.frame).is_file():
            problems.append(f"{where}: missing frame {d.frame}")
    if meta.frames.end_frame is not None and not (bundle / meta.frames.end_frame).is_file():
        problems.append(f"missing frame {meta.frames.end_frame}")
    for file_name in meta.files:
        path = bundle / file_name
        if not path.is_file():
            problems.append(f"episode.json lists {file_name}, which is missing")
        elif file_name == BUILD_FILE:
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    problems.append(f"{BUILD_FILE} line {i + 1}: {exc}")
                    continue
                if not isinstance(row, dict) or "step" not in row:
                    problems.append(f"{BUILD_FILE} line {i + 1}: not a step of the soft loop")
    for nid, node in tree.nodes.items():
        for c in node.cornerstones:
            if not (bundle / c.frame).is_file():
                problems.append(f"tree.json: {nid}'s cornerstone frame {c.frame} is missing")
    if decisions:
        last = decisions[-1]
        if not last.finished:
            problems.append("the last decision did not end the episode")
        if last.cleared != meta.result.cleared or last.died != meta.result.died:
            problems.append("episode.json's result does not match the last decision")
    calls = sum(d.calls for d in decisions)
    if calls != meta.calls:
        problems.append(f"episode.json counts {meta.calls} calls, the decisions {calls}")
    return problems
