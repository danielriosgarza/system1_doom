"""The rule tree: nodes, their conditions and actions, focus questions, skills, and the frames rules came from.

A node is a rule: a condition Jev judges from the state, and an action. Its children are its exceptions. The root
has no condition; its action is the random walk. A node may have a `focus`: when the walk enters it, Jev first picks
one item from some channels of the state, and the rules below speak of "the focus". An action is a code (see
`codes.py`) or a call to a skill, `{"skill": "aim", "then": "0001"}`: a second tree without a condition at its top,
whose rules may give part of a decision that the caller's `then` completes.

A tree is a folder that can be played without anything else: `tree.json`, and `cornerstones/` with the screen of
each frame a rule was written from. A cornerstone keeps the seed and the actions that led to its frame, so a check
can replay the game from it.
"""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .codes import COMBOS, RANDOM, THEN, ActionError, describe, segments

ROOT = "root"
# The channels of the state the game renders, in order (see `game.py`); a focus picks from some of them.
CHANNELS = ("vitals", "threats", "incoming", "outgoing", "pickups", "landmarks", "geometry", "position", "progress", "history")
SHIPPED = Path(__file__).resolve().parent / "trees"
# The tree that plays when none is named: over two benchmark runs it cleared 156 of 162 games to codex-11's 155, in
# fewer decisions (§15 of docs/DOCUMENTATION.md).
DEFAULT_TREE = "general-11"


class Focus(BaseModel):
    """Before its children are asked, the node has Jev pick one listed item of these channels."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    from_channels: List[str] = Field(alias="from")
    question: str


class SkillCall(BaseModel):
    """Go on walking in a skill; its rules' partial actions are completed by `then`."""

    model_config = ConfigDict(frozen=True)

    skill: str
    then: str


Action = Union[SkillCall, str]


class Cornerstone(BaseModel):
    """A frame a rule was written from, kept so that later rules can be checked against it.

    `prefix` is every action played before the frame; with the seed it replays the game to the frame. `expect` is
    the route the walk took there (the rules and skills it went through). `standing` is (alive, goal reached,
    health, furthest point) at `horizon`, the decision the rule's own check compared at.
    """

    seed: int
    prefix: List[str]
    state_text: str
    frame: str = Field(description="The screen at the frame: a JPEG file under the tree's folder")
    expect: str
    event_at: int
    horizon: int
    standing: Tuple[int, int, float, float]

    @property
    def decision(self) -> int:
        return len(self.prefix)


class RuleNode(BaseModel):
    id: str
    parent: Optional[str]
    condition: Optional[str]
    action: Action
    focus: Optional[Focus] = None
    children: List[str] = Field(default_factory=list)
    cornerstones: List[Cornerstone] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict, description="Who wrote the rule, from which failure, and why")


class RuleTree(BaseModel):
    name: str
    writer: str = Field(description="Who wrote the rules: claude, codex, a person, ...")
    nodes: Dict[str, RuleNode]

    _home: Optional[Path] = PrivateAttr(default=None)
    _pending: Dict[str, str] = PrivateAttr(default_factory=dict)

    @property
    def skills(self) -> List[str]:
        return [nid for nid, n in self.nodes.items() if n.parent is None and nid != ROOT]

    def top(self, nid: str) -> str:
        """The root, or the skill, a node belongs to."""
        while self.nodes[nid].parent is not None:
            nid = self.nodes[nid].parent
        return nid

    def frame_b64(self, cornerstone: Cornerstone) -> str:
        """A cornerstone's screen as base64 JPEG."""
        if cornerstone.frame in self._pending:
            return self._pending[cornerstone.frame]
        if self._home is None:
            raise FileNotFoundError(f"{cornerstone.frame}: the tree has no folder")
        return base64.b64encode((self._home / cornerstone.frame).read_bytes()).decode("ascii")

    def add_cornerstone(self, nid: str, cornerstone: Cornerstone, frame_b64: str) -> None:
        """Keep a frame at a node; its screen is written with the tree."""
        n = len(self.nodes[nid].cornerstones)
        name = f"cornerstones/{nid}-{n}.jpg"
        cornerstone = cornerstone.model_copy(update={"frame": name})
        self.nodes[nid].cornerstones.append(cornerstone)
        self._pending[name] = frame_b64

    def clone(self) -> "RuleTree":
        new = self.model_copy(deep=True)
        new._home = self._home
        new._pending = dict(self._pending)
        return new


def shipped_trees() -> List[str]:
    return sorted(p.name for p in SHIPPED.iterdir() if (p / "tree.json").is_file()) if SHIPPED.is_dir() else []


def tree_folder(where: Union[str, Path]) -> Path:
    """A tree's folder: a path to a folder or its tree.json, or the name of a shipped tree."""
    p = Path(where)
    if p.name == "tree.json":
        p = p.parent
    if (p / "tree.json").is_file():
        return p
    if (SHIPPED / str(where) / "tree.json").is_file():
        return SHIPPED / str(where)
    raise FileNotFoundError(f"no tree at {where!r}; the shipped trees are {shipped_trees()}")


def load_tree(where: Union[str, Path]) -> RuleTree:
    folder = tree_folder(where)
    tree = RuleTree.model_validate_json((folder / "tree.json").read_text(encoding="utf-8"))
    tree._home = folder
    return tree


def save_tree(tree: RuleTree, folder: Union[str, Path]) -> Path:
    """Write `tree.json` and every cornerstone's screen into `folder`."""
    folder = Path(folder)
    (folder / "cornerstones").mkdir(parents=True, exist_ok=True)
    for node in tree.nodes.values():
        for c in node.cornerstones:
            target = folder / c.frame
            if c.frame in tree._pending:
                target.write_bytes(base64.b64decode(tree._pending[c.frame]))
            elif tree._home is not None and (tree._home / c.frame).resolve() != target.resolve():
                shutil.copyfile(tree._home / c.frame, target)
    (folder / "tree.json").write_text(json.dumps(tree.model_dump(mode="json", by_alias=True), indent=1) + "\n", encoding="utf-8")
    tree._home = folder
    tree._pending.clear()
    return folder


# --------------------------------------------------------------------------- proposals


class ProposedRule(BaseModel):
    """One rule of a proposal. `under` is "frame" (an exception to the node the proposal attaches to) or, in a
    group, the index of an earlier member."""

    model_config = ConfigDict(extra="forbid")

    condition: str
    action: Action
    under: Union[str, int] = "frame"
    focus: Optional[Focus] = None


class Proposal(BaseModel):
    """What a rule writer proposes for one failure: one rule, or a group that forms one skill, written from the
    frame `frame` of the game `trace`. `under` may name a node on that frame's walk to attach higher."""

    model_config = ConfigDict(extra="ignore")

    trace: str
    frame: int
    under: Optional[str] = None
    why: str = ""
    condition: Optional[str] = None
    action: Optional[Action] = None
    focus: Optional[Focus] = None
    group: Optional[List[ProposedRule]] = None

    def members(self) -> List[ProposedRule]:
        if self.group:
            return list(self.group)
        if self.condition is None or self.action is None:
            raise ValueError("a proposal needs a condition and an action, or a group")
        return [ProposedRule(condition=self.condition, action=self.action, under="frame", focus=self.focus)]


def check_action(tree: RuleTree, action: Action, in_skill: bool) -> None:
    """Refuse an action the walk could not play: unknown codes, a partial action outside a skill, a call to a
    skill the tree does not have."""
    if isinstance(action, SkillCall):
        if action.then not in COMBOS:
            raise ActionError(f"then {action.then!r} is not one of the 54 codes")
        if action.skill not in tree.skills:
            raise ActionError(f"no skill {action.skill!r}; the skills are {tree.skills}")
    elif action == THEN:
        if not in_skill:
            raise ActionError("only a rule inside a skill can do the caller's action")
    elif action == RANDOM:
        raise ActionError("a rule cannot choose the random walk")
    else:
        segments(action, partial=in_skill)


def next_id(tree: RuleTree) -> str:
    rid = f"r{len(tree.nodes)}"
    while rid in tree.nodes:
        rid = f"r{int(rid[1:]) + 1}"
    return rid


def with_rule(tree: RuleTree, proposal: Proposal, attach_to: str, writer: str = "") -> Tuple[RuleTree, List[str]]:
    """A copy of the tree with the proposal's rules added as exceptions to `attach_to` (or to earlier members of
    its group), and the new ids."""
    new = tree.clone()
    ids: List[str] = []
    for m in proposal.members():
        parent = attach_to if m.under == "frame" else ids[int(m.under)]
        if parent not in new.nodes:
            raise ValueError(f"no node {parent!r} to attach to")
        check_action(new, m.action, in_skill=new.top(parent) != ROOT)
        if m.focus is not None:
            unknown = [c for c in m.focus.from_channels if c not in CHANNELS]
            if unknown or not m.focus.from_channels:
                raise ValueError(f"a focus picks from the channels {list(CHANNELS)}, not {unknown or 'none'}")
        rid = next_id(new)
        provenance = {"trace": proposal.trace, "frame": proposal.frame, "why": proposal.why}
        if writer:
            provenance["writer"] = writer
        new.nodes[rid] = RuleNode(id=rid, parent=parent, condition=m.condition, action=m.action, focus=m.focus, provenance=provenance)
        new.nodes[parent].children.append(rid)
        ids.append(rid)
    return new, ids


def tree_lines(tree: RuleTree) -> List[str]:
    """The tree as indented lines: the root's tree first, then each skill."""
    lines: List[str] = []

    def does(action: Action) -> str:
        if action == RANDOM:
            return "random walk"
        if isinstance(action, SkillCall):
            return describe(action.model_dump())
        return describe(action) + ("" if action == THEN else f" ({action})")

    def walk(nid: str, depth: int) -> None:
        n = tree.nodes[nid]
        label = "default" if n.parent is None else f"if {n.condition!r}"
        focus = f" [focus: {n.focus.question!r} among {', '.join(n.focus.from_channels)}]" if n.focus else ""
        lines.append("  " * depth + f"{nid}: {label}{focus} -> {does(n.action)}")
        for c in n.children:
            walk(c, depth + 1)

    walk(ROOT, 0)
    for skill in tree.skills:
        lines.append(f"skill {skill}:")
        walk(skill, 1)
    return lines
