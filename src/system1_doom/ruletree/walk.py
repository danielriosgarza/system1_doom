"""The walk: one decision of the rule tree, made by Jev's answers.

At a node with children Jev is asked "Which of these is true right now?" with each child's condition and "None of
these is true right now." as the options, and the walk moves into the child it picks. A node with a focus first has
Jev pick one listed item of some channels, which the state then shows as a `[focus]` channel. A node whose action
calls a skill goes on walking in the skill; the caller's `then` completes the skill's partial action. The deepest
node reached gives the action. The root's action is a random code.

A failed call is a miss: the walk stops at the node it has reached, and that node's action is played (a skill call
plays its `then`). Nothing stands in for a missing answer.

Answers are kept: a game asks afresh and records what Jev answered; a check reads every recorded answer first, so
that a replayed state gets the answer it got in play and an old and a new tree are compared on equal terms.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from system1_doom.d1_client import ChoiceQuestion, D1UltraClient

from .codes import COMBOS, RANDOM, THEN, complete
from .tree import ROOT, Focus, RuleNode, RuleTree, SkillCall

NODE_QUESTION = "Which of these is true right now?"
NONE = "none"
NONE_TEXT = "None of these is true right now."
FOCUS_HEAD = "\n\n[focus]\n"
DEFAULT_BUDGET = 10.0


class Answer(BaseModel):
    """Jev's answer to one choice question, or a miss."""

    probabilities: Dict[str, float] = Field(default_factory=dict)
    pick: Optional[str] = None
    miss: Optional[str] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    cost: float = 0.0
    cached: bool = False


class Step(BaseModel):
    """One step of a walk: a question at a node (`rule` or `focus`), or a skill entered."""

    kind: Literal["rule", "focus", "skill"]
    node: str = Field(description="The node asked at; for a skill, the rule that called it")
    skill: Optional[str] = None
    question: Optional[str] = None
    options: Dict[str, str] = Field(default_factory=dict)
    answer: Optional[Answer] = None
    pick: Optional[str] = Field(default=None, description="rule: the child picked, or none; focus: the item picked")
    focus_line: Optional[str] = None


class Decision(BaseModel):
    """One decision: the action played, the node that gave it, and every step of the walk."""

    action: str
    node: str
    steps: List[Step]
    missed: bool = False

    @property
    def route(self) -> str:
        return route(self.steps, self.node)

    @property
    def cost(self) -> float:
        return sum(s.answer.cost for s in self.steps if s.answer and not s.answer.cached)

    @property
    def calls(self) -> int:
        return sum(1 for s in self.steps if s.answer and not s.answer.cached)


def route(steps: List[Step], node: str) -> str:
    """Every rule the walk went into and every skill it entered: what a cornerstone expects to reach."""
    ids = [s.pick if s.kind == "rule" else s.skill for s in steps if (s.kind == "rule" and s.pick not in (None, NONE)) or s.kind == "skill"]
    return "/".join(ids) or node


def random_code(seed: int, step: int) -> str:
    """The root's random walk: a code drawn from the seed and the decision number, so a replay draws the same."""
    return random.Random(f"{seed}:{step}").choice(COMBOS)


def items(text: str, channel: str) -> List[str]:
    """The listed items of one channel of the state, word for word as Jev reads them."""
    head = f"[{channel}]\n"
    if head not in text:
        return []
    block = text.split(head, 1)[1].split("\n\n", 1)[0]
    return [line[2:] for line in block.splitlines() if line.startswith("- ")]


class AnswerBook:
    """Jev's recorded answers, one JSON file per game (a shard) in one folder."""

    def __init__(self, folder: Optional[Path] = None, shard: Optional[str] = None, read: bool = True) -> None:
        self.folder = Path(folder) if folder is not None else None
        self.shard = shard
        self.answers: Dict[str, Dict[str, float]] = {}
        self.lock = threading.Lock()
        if read and self.folder is not None and self.folder.is_dir():
            for p in sorted(self.folder.glob("*.json")):
                self.answers.update(json.loads(p.read_text(encoding="utf-8")))

    def get(self, key: str) -> Optional[Dict[str, float]]:
        with self.lock:
            return self.answers.get(key)

    def put(self, key: str, probabilities: Dict[str, float]) -> None:
        with self.lock:
            self.answers[key] = probabilities

    def save(self) -> None:
        if self.folder is None or self.shard is None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        with self.lock:
            (self.folder / self.shard).write_text(json.dumps(self.answers), encoding="utf-8")


class Jev:
    """Asks Jev one choice question at a time through the package's client, and keeps the answers in a book."""

    def __init__(self, client: D1UltraClient, book: Optional[AnswerBook] = None, budget: float = DEFAULT_BUDGET) -> None:
        self.client = client
        self.book = book if book is not None else AnswerBook()
        self.budget = budget
        self.calls = 0
        self._count = threading.Lock()

    def key(self, kind: str, text: str, frame_b64: str, question: str, options: Dict[str, str]) -> str:
        return hashlib.sha256(json.dumps([self.client.model, kind, text, frame_b64, question, sorted(options.items())]).encode()).hexdigest()

    def ask(self, kind: str, node: str, text: str, frame_b64: str, question: str, options: Dict[str, str]) -> Answer:
        key = self.key(kind, text, frame_b64, question, options)
        known = self.book.get(key)
        if known is not None:
            return Answer(probabilities=known, pick=max(known, key=known.get), cached=True)
        with self._count:
            self.calls += 1
        result = self.client.call(
            f"{kind}:{node}",
            text,
            {kind: ChoiceQuestion(instructions=question, criteria=options)},
            images=[f"data:image/jpeg;base64,{frame_b64}"],
            budget=self.budget,
        )
        timing = {"latency_ms": result.latency_ms, "cost": result.usage.cost}
        if not result.answered:
            return Answer(miss=result.miss_reason, error=result.error, **timing)
        try:
            probs = dict(result.response.choice(kind).probabilities)
        except (KeyError, ValidationError) as exc:
            self.client.note_miss(f"{kind}:{node}", "malformed")
            return Answer(miss="malformed", error=f"{type(exc).__name__}: {exc}"[:300], **timing)
        if not probs or any(p < 0 for p in probs.values()) or sum(probs.values()) > 1.01:
            self.client.note_miss(f"{kind}:{node}", "malformed")
            return Answer(probabilities=probs, miss="malformed", error="probabilities out of range", **timing)
        pick = max(probs, key=probs.get)
        if pick not in options:
            self.client.note_miss(f"{kind}:{node}", "off_menu")
            return Answer(probabilities=probs, miss="off_menu", error=f"picked {pick!r}", **timing)
        self.book.put(key, probs)
        return Answer(probabilities=probs, pick=pick, **timing)


def with_focus(text: str, frame_b64: str, node: RuleNode, focus: Focus, jev: Jev) -> Step:
    """Jev picks the focus among the items of the node's channels; the step carries the `[focus]` line to show."""
    options = [(ch, it) for ch in focus.from_channels for it in items(text, ch)]
    step = Step(kind="focus", node=node.id, question=focus.question, options={f"i{k}": it for k, (_, it) in enumerate(options)})
    if len(options) > 1:
        step.answer = jev.ask("focus", node.id, text, frame_b64, focus.question, step.options)
        if step.answer.miss:
            return step
        chosen = options[int(step.answer.pick[1:])]
    else:
        chosen = options[0] if options else None
    step.pick = chosen[1] if chosen else None
    step.focus_line = f"{chosen[1]} (from the {chosen[0]} list)" if chosen else "nothing"
    return step


def decide(tree: RuleTree, jev: Jev, state_text: str, frame_b64: str, seed: int, step: int) -> Decision:
    """Walk the tree with Jev's answers; the deepest node reached gives the action."""
    node, steps, then = tree.nodes[ROOT], [], None
    text = state_text.split(FOCUS_HEAD, 1)[0]
    missed = False
    while True:
        if node.focus is not None:
            text = text.split(FOCUS_HEAD, 1)[0]
            s = with_focus(text, frame_b64, node, node.focus, jev)
            steps.append(s)
            if s.answer is not None and s.answer.miss:
                missed = True
                break
            text += FOCUS_HEAD + s.focus_line
        if node.children:
            options = {c: tree.nodes[c].condition for c in node.children}
            options[NONE] = NONE_TEXT
            s = Step(kind="rule", node=node.id, question=NODE_QUESTION, options=options)
            s.answer = jev.ask("rule", node.id, text, frame_b64, NODE_QUESTION, options)
            steps.append(s)
            if s.answer.miss:
                missed = True
                break
            s.pick = s.answer.pick
            if s.pick != NONE:
                node = tree.nodes[s.pick]
                continue
        if isinstance(node.action, SkillCall):
            then = node.action.then
            steps.append(Step(kind="skill", node=node.id, skill=node.action.skill))
            node = tree.nodes[node.action.skill]
            continue
        break
    return Decision(action=action_of(node, then, seed, step), node=node.id, steps=steps, missed=missed)


def action_of(node: RuleNode, then: Optional[str], seed: int, step: int) -> str:
    """The code the node reached plays: a skill call stopped by a miss plays its `then`."""
    action = node.action
    if isinstance(action, SkillCall):
        return action.then
    if action == RANDOM:
        return random_code(seed, step)
    if then is not None:
        return complete(action, then)
    if action == THEN:
        raise ValueError(f"{node.id} does the caller's action, but nothing called it")
    return action
