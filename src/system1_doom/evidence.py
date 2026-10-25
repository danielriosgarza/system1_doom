"""Evidence channels: what an instance is shown, rendered as plain text.

Design spec, section 3. A channel renders one named piece of evidence; a scope is the set of channels
an instance is shown, and nothing else reaches it. Every channel reads one `EvidenceInputs`, built once
per tick from the world state, the legal menu with its descriptions, the simulator's projections, the
value networks' predictions and trust counts, the novelty counts, the relevance records, the messages,
the exploration level and the active strategy.

Rendering is deterministic: the same inputs and scope give the same text, byte for byte, so a stored
tick re-rendered from its stored inputs reproduces exactly what an instance saw at the time. A scope
renders only its channels, in the fixed order of `CHANNELS`, each under a short header line. `frame`
attaches the screen as the call's image and renders a one-line note. `projections` is labelled as a
rough projection and `values` as learned from past play. Nothing here ranks or scores an action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from system1_doom.configuration import CHANNELS, SENSE_NAMES, Bounds, ExplorationLevel, reason_words
from system1_doom.relevance import RelevanceCounts, render_relevance
from system1_doom.tracing import EnemyTrace, LandmarkTrace, PickupTrace, StateTrace, state_trace

if TYPE_CHECKING:
    from system1_doom.actions import ActionSpec
    from system1_doom.archive import StrategyEntry
    from system1_doom.simulator import ProjectedOutcome
    from system1_doom.state import WorldState


class MenuItem(BaseModel):
    """One legal action as the menu shows it."""

    model_config = ConfigDict(frozen=True)

    id: str
    description: str


class ProjectionLine(BaseModel):
    """The bounded simulator's numbers for one legal action."""

    model_config = ConfigDict(frozen=True)

    expected_value: float
    damage_taken: float
    damage_dealt: float
    survival: float
    progress: float
    resource: float


class ValueLine(BaseModel):
    """The value networks' predicted returns for one legal action, and how often it was tried here."""

    model_config = ConfigDict(frozen=True)

    predictions: Dict[str, float]
    tried: int


class StrategyLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    action_sequence: Tuple[str, ...]
    observed_reward: float
    success_rate: float
    usage_count: int


class EvidenceCounters(BaseModel):
    """Counters the controller keeps across decisions, shown in incoming, position and progress."""

    model_config = ConfigDict(frozen=True)

    decisions: int = 0
    under_fire_streak: int = 0
    stall_streak: int = 0
    sectors_discovered: int = 0


class ChannelCaps(BaseModel):
    """How much a channel may list, copied from the bounds so a stored tick re-renders on its own."""

    model_config = ConfigDict(frozen=True)

    enemies: int = 6
    pickups: int = 6
    landmarks: int = 8
    history_steps: int = 6
    summaries: int = 3
    thin_record: int = 5

    @classmethod
    def from_bounds(cls, bounds: Bounds) -> "ChannelCaps":
        return cls(
            enemies=bounds.max_enemies,
            pickups=bounds.max_pickups,
            landmarks=bounds.max_landmarks,
            history_steps=bounds.max_history_steps,
            summaries=bounds.max_summaries,
            thin_record=bounds.thin_record,
        )


class Message(BaseModel):
    """What a sense that spoke sends the central instance."""

    model_config = ConfigDict(frozen=True)

    sense: str
    action: str
    reason: str
    strength: float
    target: Optional[str] = Field(default=None, description="The enemy or pickup the sense chose for the motor, if it chooses one")
    target_kind: Optional[str] = Field(default=None, description="enemy or pickup")
    target_line: Optional[str] = Field(default=None, description="The chosen target in the words the sense saw it in")


class EvidenceInputs(BaseModel):
    """Everything any channel renders from, for one tick. Stored whole in the history."""

    model_config = ConfigDict(frozen=True)

    tick: int
    context: str
    state: StateTrace
    counters: EvidenceCounters = Field(default_factory=EvidenceCounters)
    recent_primitives: Tuple[str, ...] = ()
    recent_summaries: Tuple[str, ...] = ()
    frame_ref: Optional[str] = Field(default=None, description="The screen this decision was made on, when there is one")
    menu: Tuple[MenuItem, ...]
    projections: Dict[str, ProjectionLine] = Field(default_factory=dict)
    values: Optional[Dict[str, ValueLine]] = Field(default=None, description="None when no value networks are loaded")
    novelty: Dict[str, int] = Field(default_factory=dict)
    archive: Tuple[StrategyLine, ...] = ()
    active_strategy: str = ""
    exploration_level: ExplorationLevel = "exploit"
    relevance: Dict[str, RelevanceCounts] = Field(default_factory=dict)
    messages: Tuple[Message, ...] = ()
    caps: ChannelCaps = Field(default_factory=ChannelCaps)

    def menu_ids(self) -> List[str]:
        return [item.id for item in self.menu]


class RenderedEvidence(BaseModel):
    """A scope's text, and the image reference when `frame` is in scope and there is a frame."""

    model_config = ConfigDict(frozen=True)

    scope: Tuple[str, ...]
    text: str
    image_ref: Optional[str] = None


# ---------------------------------------------------------------------------------------------------
# Small deterministic phrases.


def _num(value: float, places: int = 0) -> str:
    text = f"{value:.{places}f}"
    return "0" if places == 0 and text == "-0" else text


def _signed(value: float) -> str:
    text = f"{value:+.2f}"
    return "+0.00" if text == "-0.00" else text


def _angle(offset: float) -> str:
    """Offsets are positive to the left of the crosshair."""
    magnitude = _num(abs(offset))
    if magnitude == "0":
        return "straight ahead"
    return f"{magnitude} deg {'left' if offset > 0 else 'right'}"


def _under_crosshair(e: EnemyTrace, screen_width: int) -> bool:
    centre = screen_width / 2.0
    return e.screen_x - e.width / 2.0 <= centre <= e.screen_x + e.width / 2.0


def _nearest(items: Sequence, key_id: Callable) -> List:
    return sorted(items, key=lambda x: (x.distance, key_id(x)))


# ---------------------------------------------------------------------------------------------------
# One renderer per channel. Each returns the body lines under the channel's header.


def _vitals(inp: EvidenceInputs) -> List[str]:
    s = inp.state
    return [f"health {_num(s.health)}, armor {_num(s.armor)}, ammo {s.ammo}, weapon {s.weapon}"]


def enemy_line(e: EnemyTrace, screen_width: int) -> str:
    """One visible enemy in words: the threats channel's line, and the enemy target's criterion."""
    notes = []
    if _under_crosshair(e, screen_width):
        notes.append("under the crosshair")
    if e.is_attacking:
        notes.append("attacking")
    n = e.attacks_without_hit
    if n:
        notes.append(f"your last {n} attacks on it hit nothing" if n > 1 else "your last attack on it hit nothing")
    extra = f", {', '.join(notes)}" if notes else ""
    return f"{e.name} at distance {_num(e.distance)}, {_angle(e.angle_offset)}, size {e.width}x{e.height} px{extra}"


def shown_enemies(inp: "EvidenceInputs") -> List[EnemyTrace]:
    """The enemies the threats channel lists, nearest first, within the cap."""
    return _nearest(inp.state.enemies, lambda e: e.id)[: inp.caps.enemies]


def _threats(inp: EvidenceInputs) -> List[str]:
    enemies = _nearest(inp.state.enemies, lambda e: e.id)
    if not enemies:
        return ["no enemy visible"]
    shown = shown_enemies(inp)
    head = (
        f"{len(enemies)} enem{'y' if len(enemies) == 1 else 'ies'} visible, nearest first"
        + (f" (nearest {len(shown)} shown)" if len(shown) < len(enemies) else "")
        + ":"
    )
    return [head] + [f"- {enemy_line(e, inp.state.screen_width)}" for e in shown]


def _incoming(inp: EvidenceInputs) -> List[str]:
    unseen = "; the attacker is not in view" if inp.state.recent_incoming_damage > 0 and not inp.state.enemies else ""
    return [
        f"damage taken since the last decision {_num(inp.state.recent_incoming_damage)}{unseen}; "
        f"consecutive decisions under fire {inp.counters.under_fire_streak}"
    ]


def _outgoing(inp: EvidenceInputs) -> List[str]:
    s = inp.state
    return [
        f"damage dealt since the last decision {_num(s.recent_outgoing_damage)}, "
        f"hits {s.recent_hits}, kills {s.recent_kills}"
    ]


def _pickups(inp: EvidenceInputs) -> List[str]:
    pickups: List[PickupTrace] = _nearest(inp.state.pickups, lambda p: p.id)
    if not pickups:
        return ["no pickup visible"]
    shown = pickups[: inp.caps.pickups]
    head = (
        f"{len(pickups)} pickup{'' if len(pickups) == 1 else 's'} visible, nearest first"
        + (f" (nearest {len(shown)} shown)" if len(shown) < len(pickups) else "")
        + ":"
    )
    return [head] + [f"- {p.name} ({p.category}) at distance {_num(p.distance)}, {_angle(p.angle_offset)}" for p in shown]


def _bearing(bearing: float) -> str:
    """Where a remembered point lies from the facing: `straight ahead`, `30 deg left`, `150 deg right, behind you`."""
    words = _angle(bearing)
    return f"{words}, behind you" if abs(bearing) > 90.0 else words


def _reward_link(m: LandmarkTrace) -> str:
    if m.reward_agreement is None or m.reward_moves < 3:
        return "no reward link yet"
    a = m.reward_agreement
    over = f"(agreement {a:+.2f} over {m.reward_moves} moves)"
    if a >= 0.5:
        return f"reward rose as you got closer {over}"
    if a <= -0.5:
        return f"reward rose as you got farther from it {over}"
    return f"no clear link between its distance and reward {over}"


def landmark_line(m: LandmarkTrace, tick: int) -> str:
    """One remembered pickup in words: the landmarks channel's line, and the pickup target's criterion."""
    if m.in_view:
        seen = "in view"
    else:
        ago = max(0, tick - m.last_seen_tick)
        seen = f"out of view, last seen {ago} decision{'' if ago == 1 else 's'} ago"
    where = f"{_num(m.distance)} away, {_bearing(m.bearing)}, {seen}"
    n = m.approaches_nowhere
    if n:
        # Once walking at it gets no closer, how reward moved with its distance says nothing about reaching it.
        return f"{m.name} ({m.category}): cannot be walked to from here, {n} walk{'' if n == 1 else 's'} at it got no closer; {where}"
    return f"{m.name} ({m.category}): {where}; {_reward_link(m)}"


def shown_landmarks(inp: "EvidenceInputs") -> List[LandmarkTrace]:
    """The remembered pickups the landmarks channel lists, nearest first, within the cap."""
    return _nearest(inp.state.landmarks, lambda m: m.id)[: inp.caps.landmarks]


def _landmarks(inp: EvidenceInputs) -> List[str]:
    landmarks = _nearest(inp.state.landmarks, lambda m: m.id)
    if not landmarks:
        return ["no pickup remembered: none seen yet this episode, or every one seen was picked up"]
    shown = shown_landmarks(inp)
    head = (
        f"{len(landmarks)} pickup{'' if len(landmarks) == 1 else 's'} seen this episode and not picked up, "
        "where each lies now from your position and facing, nearest first"
        + (f" (nearest {len(shown)} shown)" if len(shown) < len(landmarks) else "")
        + ":"
    )
    return [head] + [f"- {landmark_line(m, inp.state.tick)}" for m in shown]


def _geometry(inp: EvidenceInputs) -> List[str]:
    w = inp.state.walls
    moving = "still" if inp.state.movement == "stationary" else "moving"
    return [f"wall distance ahead {_num(w.front)}, left {_num(w.left)}, right {_num(w.right)}; {moving}"]


def _position(inp: EvidenceInputs) -> List[str]:
    p = inp.state.position
    n = inp.counters.sectors_discovered
    return [f"x {_num(p.x)}, y {_num(p.y)}, facing {_num(p.angle)} deg; {n} sector{'' if n == 1 else 's'} discovered this episode"]


def _progress(inp: EvidenceInputs) -> List[str]:
    progress = inp.state.episode_progress
    displacement = progress.get("last_displacement")
    moved = f"{_num(displacement)} units" if displacement is not None else "none yet"
    last = progress.get("last_reward")
    earned = f"{last:+.1f}" if last is not None else "none yet"
    return [
        f"decisions so far {inp.counters.decisions}, reward so far {_num(progress.get('reward_so_far', 0.0), 1)}, "
        f"reward from the last decision {earned}, kills {_num(progress.get('kills', 0.0))}, "
        f"last displacement {moved}, stall streak {inp.counters.stall_streak}"
    ]


def _history(inp: EvidenceInputs) -> List[str]:
    steps = list(inp.recent_primitives)[-inp.caps.history_steps :]
    summaries = list(inp.recent_summaries)[-inp.caps.summaries :]
    lines = [
        f"last {len(steps)} primitives executed, oldest first: {', '.join(steps)}" if steps else "no primitive executed yet"
    ]
    if summaries:
        lines.append(f"last {len(summaries)} decisions, oldest first:")
        lines.extend(f"- {summary}" for summary in summaries)
    else:
        lines.append("no decision made yet")
    return lines


def _frame(inp: EvidenceInputs) -> List[str]:
    if inp.frame_ref is None:
        return ["no screen image at this decision"]
    return [f"the screen at this decision is attached as the image ({inp.state.screen_width}x{inp.state.screen_height})"]


def _menu(inp: EvidenceInputs) -> List[str]:
    return ["the legal actions now:"] + [f"- {item.id}: {item.description}" for item in inp.menu]


def _projections(inp: EvidenceInputs) -> List[str]:
    lines = ["a rough projection from a hand-written simulator, not the game; per legal action:"]
    for aid in inp.menu_ids():
        p = inp.projections.get(aid)
        if p is None:
            lines.append(f"- {aid}: not projected")
            continue
        lines.append(
            f"- {aid}: expected value {_signed(p.expected_value)}, damage in {_num(p.damage_taken, 1)}, "
            f"damage out {_num(p.damage_dealt, 1)}, survival {_num(p.survival, 2)}, progress {_num(p.progress, 2)}"
        )
    return lines


def _values(inp: EvidenceInputs) -> List[str]:
    if inp.values is None:
        return ["no value networks are loaded"]
    lines = [
        "learned from past play: each value network's predicted return (standardised) and how often the action "
        "was tried in this situation in training; per legal action:"
    ]
    for aid in inp.menu_ids():
        v = inp.values.get(aid)
        if v is None:
            lines.append(f"- {aid}: no prediction")
            continue
        preds = ", ".join(f"{name} {_signed(value)}" for name, value in v.predictions.items())
        lines.append(f"- {aid}: {preds}; tried {v.tried} here")
    return lines


def _novelty(inp: EvidenceInputs) -> List[str]:
    lines = ["how often each legal action has been taken in this situation so far:"]
    lines.extend(f"- {aid}: {inp.novelty.get(aid, 0)}" for aid in inp.menu_ids())
    return lines


def _archive(inp: EvidenceInputs) -> List[str]:
    if not inp.archive:
        return ["no strategy archived"]
    lines = [f"strategies (active: {inp.active_strategy}):"]
    for s in inp.archive:
        active = " (active)" if s.strategy_id == inp.active_strategy else ""
        lines.append(
            f"- {s.strategy_id}{active}: {', '.join(s.action_sequence)}; reward {_num(s.observed_reward, 2)}, "
            f"success {_num(s.success_rate, 2)}, used {s.usage_count} times"
        )
    return lines


def _exploration(inp: EvidenceInputs) -> List[str]:
    if inp.exploration_level == "explore":
        return [
            "level explore: the executed action is drawn from your probabilities; prefer a less-tried action "
            "when the messages do not demand otherwise."
        ]
    return ["level exploit: the action you give the highest probability is executed."]


def _messages(inp: EvidenceInputs) -> List[str]:
    if not inp.messages:
        return ["no sense spoke this tick."]
    return [f"{m.sense} says {m.action}, strength {_num(m.strength, 2)}, reason {reason_words(m.reason)}{_target_words(m)}." for m in inp.messages]


def _target_words(m: Message) -> str:
    if m.target is None:
        return ""
    return f", {'aim at' if m.target_kind == 'enemy' else 'walk to'} {m.target_line or m.target}"


def _relevance(inp: EvidenceInputs) -> List[str]:
    return [f"each sense's record in this situation ({inp.context}):"] + render_relevance(
        inp.relevance, SENSE_NAMES, inp.caps.thin_record
    )


RENDERERS: Dict[str, Callable[[EvidenceInputs], List[str]]] = {
    "vitals": _vitals,
    "threats": _threats,
    "incoming": _incoming,
    "outgoing": _outgoing,
    "pickups": _pickups,
    "landmarks": _landmarks,
    "geometry": _geometry,
    "position": _position,
    "progress": _progress,
    "history": _history,
    "frame": _frame,
    "menu": _menu,
    "projections": _projections,
    "values": _values,
    "novelty": _novelty,
    "archive": _archive,
    "exploration": _exploration,
    "messages": _messages,
    "relevance": _relevance,
}
assert tuple(RENDERERS) == CHANNELS, "one renderer per channel, in channel order"


def render_channel(inputs: EvidenceInputs, channel: str) -> str:
    """One channel: its header line and its body."""
    return "\n".join([f"[{channel}]"] + RENDERERS[channel](inputs))


def render_scope(inputs: EvidenceInputs, scope: Sequence[str]) -> RenderedEvidence:
    """The text an instance with this scope is shown: its channels only, in channel order."""
    unknown = [c for c in scope if c not in RENDERERS]
    if unknown:
        raise ValueError(f"unknown channel(s) {unknown}")
    ordered = tuple(c for c in CHANNELS if c in scope)
    text = "\n\n".join(render_channel(inputs, c) for c in ordered)
    image_ref = inputs.frame_ref if "frame" in ordered else None
    return RenderedEvidence(scope=ordered, text=text, image_ref=image_ref)


# ---------------------------------------------------------------------------------------------------
# Building the inputs from what the controller holds.


def projection_line(outcome: "ProjectedOutcome") -> ProjectionLine:
    return ProjectionLine(
        expected_value=round(outcome.expected_value, 4),
        damage_taken=round(outcome.expected_damage_taken, 4),
        damage_dealt=round(outcome.expected_damage_dealt, 4),
        survival=round(outcome.survival_probability, 4),
        progress=round(outcome.expected_positional_progress, 4),
        resource=round(outcome.expected_resource_gain, 4),
    )


def build_inputs(
    world_state: "WorldState",
    menu: Sequence["ActionSpec"],
    *,
    projections: Optional[Mapping[str, "ProjectedOutcome"]] = None,
    values: Optional[Mapping[str, ValueLine]] = None,
    novelty: Optional[Mapping[str, int]] = None,
    archive: Sequence["StrategyEntry"] = (),
    active_strategy: str = "",
    exploration_level: ExplorationLevel = "exploit",
    relevance: Optional[Mapping[str, RelevanceCounts]] = None,
    counters: Optional[EvidenceCounters] = None,
    frame_ref: Optional[str] = None,
    caps: Optional[ChannelCaps] = None,
) -> EvidenceInputs:
    """The one `EvidenceInputs` of a tick. Messages are added after the senses have answered."""
    caps = caps or ChannelCaps()
    menu_ids = [a.id for a in menu]
    return EvidenceInputs(
        tick=world_state.observation.tick,
        context=world_state.context_signature(),
        state=state_trace(world_state),
        counters=counters or EvidenceCounters(),
        recent_primitives=tuple(world_state.observation.recent_actions[-caps.history_steps :]),
        recent_summaries=tuple(world_state.memory.recent_state_summaries[-caps.summaries :]),
        frame_ref=frame_ref,
        menu=tuple(MenuItem(id=a.id, description=a.description) for a in menu),
        projections={aid: projection_line(p) for aid, p in (projections or {}).items() if aid in menu_ids},
        values=None if values is None else {aid: v for aid, v in values.items() if aid in menu_ids},
        novelty={aid: int((novelty or {}).get(aid, 0)) for aid in menu_ids},
        archive=tuple(
            StrategyLine(
                strategy_id=e.strategy_id,
                action_sequence=tuple(e.action_sequence),
                observed_reward=e.observed_reward,
                success_rate=e.success_rate,
                usage_count=e.usage_count,
            )
            for e in archive
        ),
        active_strategy=active_strategy,
        exploration_level=exploration_level,
        relevance=dict(relevance or {}),
        caps=caps,
    )
