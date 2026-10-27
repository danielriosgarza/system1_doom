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

Asking ahead (`Jev(ahead=True)`, for a model that answers each question of a request on its own, such as Kev or Laya):
before a rule question, every question the walk may ask next about the same text (`upcoming`: the node's own, its
children's focus questions while the text has no focus, and the questions of the children and skills reached without a
focus) goes in one request, and the walk takes the answers it reaches from there. A model that reads the state once per
request answers the extra questions almost for free; the walk and its picks are the same.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field, ValidationError

from system1_doom.d1_client import ChoiceQuestion, D1UltraClient

from .codes import COMBOS, RANDOM, THEN, complete
from .tree import ROOT, Focus, RuleNode, RuleTree, SkillCall

NODE_QUESTION = "Which of these is true right now?"
NONE = "none"
NONE_TEXT = "None of these is true right now."
FOCUS_HEAD = "\n\n[focus]\n"
DEFAULT_BUDGET = 10.0
AHEAD = 6  # questions asked together at most


class Answer(BaseModel):
    """Jev's answer to one choice question, or a miss."""

    probabilities: Dict[str, float] = Field(default_factory=dict)
    pick: Optional[str] = None
    miss: Optional[str] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    cost: float = 0.0
    cached: bool = False
    batch: Optional[int] = Field(default=None, description="Questions in the request it came from, when more than one; "
                                                           "latency and cost are its share")


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
    """Asks Jev one choice question at a time through the package's client, and keeps the answers in a book. With
    `ahead`, the questions `upcoming` names go in one request before a rule question, and are answered from there."""

    def __init__(self, client: D1UltraClient, book: Optional[AnswerBook] = None, budget: float = DEFAULT_BUDGET,
                 ahead: bool = False) -> None:
        self.client = client
        self.book = book if book is not None else AnswerBook()
        self.budget = budget
        self.ahead = ahead
        self.calls = 0
        self._count = threading.Lock()
        self._early: Dict[str, Answer] = {}

    def key(self, kind: str, text: str, frame_b64: str, question: str, options: Dict[str, str]) -> str:
        return hashlib.sha256(json.dumps([self.client.model, kind, text, frame_b64, question, sorted(options.items())]).encode()).hexdigest()

    def ask(self, kind: str, node: str, text: str, frame_b64: str, question: str, options: Dict[str, str]) -> Answer:
        key = self.key(kind, text, frame_b64, question, options)
        known = self.book.get(key)
        if known is not None:
            return Answer(probabilities=known, pick=max(known, key=known.get), cached=True)
        with self._count:
            early = self._early.pop(key, None)
        if early is not None:
            self.book.put(key, early.probabilities)
            return early
        with self._count:
            self.calls += 1
        result = self.client.call(
            f"{kind}:{node}",
            text,
            {kind: ChoiceQuestion(instructions=question, criteria=options)},
            images=[f"data:image/jpeg;base64,{frame_b64}"],
            budget=self.budget,
        )
        answer = self._read(result, kind, f"{kind}:{node}", options, {"latency_ms": result.latency_ms, "cost": result.usage.cost})
        if answer.miss is None:
            self.book.put(key, answer.probabilities)
        return answer

    def ask_together(self, text: str, frame_b64: str, questions: Sequence[Tuple[str, str, str, Dict[str, str]]]) -> None:
        """Ask (kind, node, question, options) about one text in one request, and keep each answer for `ask`; nothing
        when fewer than two are not known yet. A miss keeps nothing: `ask` then asks on its own."""
        todo: Dict[str, Tuple[str, str, str, Dict[str, str]]] = {}
        for kind, node, question, options in questions:
            key = self.key(kind, text, frame_b64, question, options)
            with self._count:
                early = key in self._early
            if not early and self.book.get(key) is None:
                todo.setdefault(key, (kind, node, question, options))
        if len(todo) < 2:
            return
        names = [kind if i == 0 else f"{kind}.{i}" for i, (kind, *_rest) in enumerate(todo.values())]
        with self._count:
            self.calls += 1
        first_kind, first_node = next(iter(todo.values()))[:2]
        result = self.client.call(
            f"ahead:{first_kind}:{first_node}",
            text,
            {name: ChoiceQuestion(instructions=q[2], criteria=q[3]) for name, q in zip(names, todo.values())},
            images=[f"data:image/jpeg;base64,{frame_b64}"],
            budget=self.budget,
        )
        n = len(todo)
        share = {"latency_ms": round(result.latency_ms / n, 3), "cost": result.usage.cost / n, "batch": n}
        for name, (key, (kind, node, _question, options)) in zip(names, todo.items()):
            answer = self._read(result, name, f"{kind}:{node}", options, share)
            if answer.miss is None:
                with self._count:
                    self._early[key] = answer

    def _read(self, result: Any, name: str, instance: str, options: Dict[str, str], timing: Dict[str, Any]) -> Answer:
        """The answer to question `name` of a call, or the miss it is: none, malformed or off the menu."""
        if not result.answered:
            return Answer(miss=result.miss_reason, error=result.error, **timing)
        try:
            probs = dict(result.response.choice(name).probabilities)
        except (KeyError, ValidationError) as exc:
            self.client.note_miss(instance, "malformed")
            return Answer(miss="malformed", error=f"{type(exc).__name__}: {exc}"[:300], **timing)
        if not probs or any(p < 0 for p in probs.values()) or sum(probs.values()) > 1.01:
            self.client.note_miss(instance, "malformed")
            return Answer(probabilities=probs, miss="malformed", error="probabilities out of range", **timing)
        pick = max(probs, key=probs.get)
        if pick not in options:
            self.client.note_miss(instance, "off_menu")
            return Answer(probabilities=probs, miss="off_menu", error=f"picked {pick!r}", **timing)
        return Answer(probabilities=probs, pick=pick, **timing)


def focus_items(text: str, focus: Focus) -> List[Tuple[str, str]]:
    """(channel, item) for every item a focus picks among, in the order of its options i0, i1, ..."""
    return [(ch, it) for ch in focus.from_channels for it in items(text, ch)]


def upcoming(tree: RuleTree, node: RuleNode, text: str) -> List[Tuple[str, str, str, Dict[str, str]]]:
    """The questions about `text` the walk may ask from `node` on, before its focus changes the text: (kind, node,
    question, options), the node's own rule question first, at most AHEAD."""
    out: List[Tuple[str, str, str, Dict[str, str]]] = []
    queue, seen = [node], set()
    while queue and len(out) < AHEAD:
        n = queue.pop(0)
        if n.id in seen:
            continue
        seen.add(n.id)
        if n.children:
            options = {c: tree.nodes[c].condition for c in n.children}
            options[NONE] = NONE_TEXT
            out.append(("rule", n.id, NODE_QUESTION, options))
            for c in n.children:
                child = tree.nodes[c]
                if child.focus is None:
                    queue.append(child)
                elif FOCUS_HEAD not in text:
                    picks = focus_items(text, child.focus)
                    if len(picks) > 1:
                        out.append(("focus", child.id, child.focus.question, {f"i{k}": it for k, (_, it) in enumerate(picks)}))
        if isinstance(n.action, SkillCall):
            queue.append(tree.nodes[n.action.skill])
    return out[:AHEAD]


def with_focus(text: str, frame_b64: str, node: RuleNode, focus: Focus, jev: Jev) -> Step:
    """Jev picks the focus among the items of the node's channels; the step carries the `[focus]` line to show."""
    options = focus_items(text, focus)
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
            if jev.ahead:
                jev.ask_together(text, frame_b64, upcoming(tree, node, text))
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
