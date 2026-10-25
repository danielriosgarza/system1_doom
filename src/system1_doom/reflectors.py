"""System 2's reflectors: d1-ultra instances over the history, each with a finite menu of configuration changes.

Design spec, section 8. A reflector is one call, like a sense: its scope is a history channel and
`h_outcomes` (`history_channels.py`), and it answers three finite questions: `speak` (noul), `change`
(a choice over the configuration changes it may propose) and `reason` (a choice over its own short
vocabulary). Its instructions name the reflector, its concern and that it sees only the evidence given;
they never say how to weigh anything.

| Reflector | Scope | `change` criteria |
| --- | --- | --- |
| auditor of each sense (5) | `h_sense:<name>`, `h_outcomes` | `widen:<name>:<channel>` per channel it could add, `narrow:<name>:<channel>` per channel it could drop (never `menu`), `keep` |
| central auditor | `h_central`, `h_outcomes` | `widen:central:<channel>`, `narrow:central:<channel>`, `keep` |
| menu reflector | `h_actions`, `h_outcomes` | `macro:<sense>` (a new macro for that sense's problem), `retire:<macro id>` per admitted macro, `keep` |
| strategy reflector | `h_strategy`, `h_outcomes` | `strategy:<id>` per archived strategy that is not active, `keep` |
| exploration reflector | `h_exploration`, `h_outcomes` | `level:exploit`, `level:explore` |

This module is data and pure functions: the nine specs, each one's finite change menu for a
configuration, the bounds that remove a change from it before the call (`blocked_by`: cooling, the
scope-size bound, the one-trial bound, built-in actions, `menu` never narrowed, a configuration that
would not validate), what a change does to a configuration (`apply_change`), and the diff between two
configurations. Nothing here ranks or chooses a change: the bounds filter the finite set, and d1 decides.
A reflector that is silent, missed, or chose no change (`keep`, or the level already set) sends nothing.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from system1_doom.actions import BUILTIN_IDS
from system1_doom.configuration import (
    CENTRAL_NAME,
    CENTRAL_ONLY_CHANNELS,
    CHANNELS,
    SENSE_NAMES,
    Configuration,
    reason_words,
)
from system1_doom.d1_client import ChoiceQuestion, NoulQuestion, QuestionSpec
from system1_doom.instance import InstanceResult, InstanceSpec, preamble

ChangeKind = Literal["keep", "widen", "narrow", "macro", "retire", "strategy", "level"]
ReflectorKind = Literal["sense_auditor", "central_auditor", "menu", "strategy", "exploration"]

KEEP = "keep"
# The cooling key of System 2 as a whole: a menu, strategy or level change cools every change after it.
SYSTEM2_KEY = "system2"
COOLING_KEYS: Tuple[str, ...] = SENSE_NAMES + (CENTRAL_NAME, SYSTEM2_KEY)
SCOPE_KINDS: Tuple[str, ...] = ("widen", "narrow")

AUDITOR_REASONS: Tuple[str, ...] = ("missing_evidence", "needless_evidence", "poor_payoff", "doing_well", "too_little_data")
MENU_REASONS: Tuple[str, ...] = ("no_fitting_action", "macro_failing", "macro_unused", "menu_serves", "too_little_data")
STRATEGY_REASONS: Tuple[str, ...] = ("strategy_failing", "better_strategy_archived", "strategy_working", "too_little_data")
EXPLORATION_REASONS: Tuple[str, ...] = ("stuck_or_repeating", "progress_stalled", "progress_steady", "too_little_data")


class ReflectorSpec(BaseModel):
    """One reflector: data, like a sense's configuration."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="The instance name its calls are counted under, e.g. survival_auditor")
    title: str = Field(description="How its instructions name it, e.g. 'survival auditor'")
    kind: ReflectorKind
    target: Optional[str] = Field(default=None, description="The sense or the central an auditor audits")
    scope: Tuple[str, ...]
    concern: str
    reasons: Tuple[str, ...]

    def instance_spec(self) -> InstanceSpec:
        return InstanceSpec(
            name=self.name, kind="reflector", scope=self.scope, concern=self.concern, reasons=self.reasons, title=self.title
        )


def _sense_auditor(sense: str) -> ReflectorSpec:
    return ReflectorSpec(
        name=f"{sense}_auditor",
        title=f"{sense} auditor",
        kind="sense_auditor",
        target=sense,
        scope=(f"h_sense:{sense}", "h_outcomes"),
        concern=f"whether the {sense} sense is shown the evidence it needs, and only that",
        reasons=AUDITOR_REASONS,
    )


REFLECTORS: Tuple[ReflectorSpec, ...] = tuple(_sense_auditor(s) for s in SENSE_NAMES) + (
    ReflectorSpec(
        name="central_auditor",
        title="central auditor",
        kind="central_auditor",
        target=CENTRAL_NAME,
        scope=("h_central", "h_outcomes"),
        concern="whether the central action chooser is shown the evidence it needs, and only that",
        reasons=AUDITOR_REASONS,
    ),
    ReflectorSpec(
        name="menu_reflector",
        title="menu reflector",
        kind="menu",
        scope=("h_actions", "h_outcomes"),
        concern="whether the legal menu of actions serves the agent, and whose problem a new macro-action would solve",
        reasons=MENU_REASONS,
    ),
    ReflectorSpec(
        name="strategy_reflector",
        title="strategy reflector",
        kind="strategy",
        scope=("h_strategy", "h_outcomes"),
        concern="whether the active strategy serves the agent",
        reasons=STRATEGY_REASONS,
    ),
    ReflectorSpec(
        name="exploration_reflector",
        title="exploration reflector",
        kind="exploration",
        scope=("h_exploration", "h_outcomes"),
        concern="whether the agent should exploit what it knows or explore less-tried actions",
        reasons=EXPLORATION_REASONS,
    ),
)
REFLECTOR_NAMES: Tuple[str, ...] = tuple(r.name for r in REFLECTORS)


class ChangeOption(BaseModel):
    """One configuration change a reflector may propose: an id, what it touches, and how it reads."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: ChangeKind
    target: Optional[str] = Field(default=None, description="widen/narrow: the instance; macro: the sense; retire: the macro; strategy: its id; level: the level")
    channel: Optional[str] = None
    description: str

    @property
    def is_scope_change(self) -> bool:
        return self.kind in SCOPE_KINDS

    @property
    def instance(self) -> Optional[str]:
        """The instance a scope change changes (a sense or the central); None for every other change."""
        return self.target if self.is_scope_change else None

    @property
    def cooling_key(self) -> Optional[str]:
        """Who cools after this change: the changed instance, or System 2 as a whole; None for keep."""
        if self.kind == "keep":
            return None
        return self.target if self.is_scope_change else SYSTEM2_KEY


def _who(instance: str) -> str:
    return "the central action chooser" if instance == CENTRAL_NAME else f"the {instance} sense"


def change_option(change_id: str, configuration: Configuration) -> ChangeOption:
    """The option a change id names, with its description; ValueError for an id no reflector offers."""
    parts = change_id.split(":")
    head = parts[0]
    if change_id == KEEP:
        return ChangeOption(id=KEEP, kind="keep", description="keep the configuration as it is")
    if head in SCOPE_KINDS and len(parts) == 3:
        instance, channel = parts[1], parts[2]
        if instance not in SENSE_NAMES + (CENTRAL_NAME,) or channel not in CHANNELS:
            raise ValueError(f"unknown scope change {change_id!r}")
        text = (
            f"show {_who(instance)} the {channel} channel as well"
            if head == "widen"
            else f"stop showing {_who(instance)} the {channel} channel"
        )
        return ChangeOption(id=change_id, kind=head, target=instance, channel=channel, description=text)  # type: ignore[arg-type]
    if head == "macro" and len(parts) == 2 and parts[1] in SENSE_NAMES:
        sense = parts[1]
        concern = configuration.senses[sense].concern
        return ChangeOption(
            id=change_id, kind="macro", target=sense,
            description=f"ask the slow path for a new macro-action for the {sense} sense's problem ({concern})",
        )
    if head == "retire" and len(parts) == 2:
        return ChangeOption(id=change_id, kind="retire", target=parts[1], description=f"retire the admitted macro {parts[1]} from the menu")
    if head == "strategy" and len(parts) == 2:
        return ChangeOption(id=change_id, kind="strategy", target=parts[1], description=f"make {parts[1]} the active strategy")
    if head == "level" and len(parts) == 2 and parts[1] in ("exploit", "explore"):
        meaning = {
            "exploit": "the action the chooser gives the highest probability is executed",
            "explore": "the executed action is drawn from the chooser's probabilities",
        }[parts[1]]
        return ChangeOption(id=change_id, kind="level", target=parts[1], description=f"set the exploration level to {parts[1]}: {meaning}")
    raise ValueError(f"unknown change {change_id!r}")


def scope_of(configuration: Configuration, instance: str) -> Tuple[str, ...]:
    return tuple(configuration.central.scope if instance == CENTRAL_NAME else configuration.senses[instance].scope)


def addable(configuration: Configuration, instance: str) -> Tuple[str, ...]:
    """The channels an instance could be shown besides its scope: every channel, less its scope, less the
    central-only channels for a sense. The scope-size bound is applied by `blocked_by`, not here."""
    scope = scope_of(configuration, instance)
    forbidden = () if instance == CENTRAL_NAME else CENTRAL_ONLY_CHANNELS
    return tuple(c for c in CHANNELS if c not in scope and c not in forbidden)


def droppable(configuration: Configuration, instance: str) -> Tuple[str, ...]:
    """The channels an instance's scope could lose: every channel of its scope but `menu`."""
    return tuple(c for c in scope_of(configuration, instance) if c != "menu")


def change_menu(spec: ReflectorSpec, configuration: Configuration, archive_ids: Sequence[str] = ()) -> List[ChangeOption]:
    """The reflector's finite set of changes for this configuration, before the bounds filter it."""
    ids: List[str] = []
    if spec.kind in ("sense_auditor", "central_auditor"):
        assert spec.target is not None
        ids += [f"widen:{spec.target}:{c}" for c in addable(configuration, spec.target)]
        ids += [f"narrow:{spec.target}:{c}" for c in droppable(configuration, spec.target)]
        ids.append(KEEP)
    elif spec.kind == "menu":
        ids += [f"macro:{s}" for s in SENSE_NAMES]
        ids += [f"retire:{m.id}" for m in configuration.admitted_macros if m.id not in BUILTIN_IDS]
        ids.append(KEEP)
    elif spec.kind == "strategy":
        ids += [f"strategy:{sid}" for sid in archive_ids if sid != configuration.active_strategy]
        ids.append(KEEP)
    else:
        ids += ["level:exploit", "level:explore"]
    return [change_option(i, configuration) for i in ids]


def is_no_change(option: ChangeOption, configuration: Configuration) -> bool:
    """`keep`, the level already set, or the strategy already active: choosing it changes nothing."""
    if option.kind == "keep":
        return True
    if option.kind == "level":
        return option.target == configuration.exploration_level
    if option.kind == "strategy":
        return option.target == configuration.active_strategy
    return False


class BoundsState(BaseModel):
    """What the bounds read besides the configuration: decisions, cooling, the trial, the slow path, the archive."""

    model_config = ConfigDict(frozen=True)

    decisions: int = 0
    cooling: Dict[str, int] = Field(default_factory=dict, description="Cooling key -> the decision count at which it ends")
    trials: int = Field(default=0, description="Trials in flight, and changes queued or asked for that will become one")
    slow_path_available: bool = True
    archive_ids: Tuple[str, ...] = ()

    def cooling_left(self, key: str) -> int:
        return max(0, self.cooling.get(key, 0) - self.decisions)


def apply_change(configuration: Configuration, option: ChangeOption) -> Configuration:
    """The configuration with `option` applied and the version bumped (`with_changes`, validated whole).

    `keep` and `macro:<sense>` change no configuration: a macro enters only when the admit instance says yes.
    """
    if option.is_scope_change:
        assert option.target is not None and option.channel is not None
        scope = scope_of(configuration, option.target)
        if option.kind == "widen":
            # The new channel joins before `menu`, which the design's scopes list last; render order is fixed anyway.
            new_scope = tuple(c for c in scope if c != "menu") + (option.channel, "menu")
        else:
            new_scope = tuple(c for c in scope if c != option.channel)
        if option.target == CENTRAL_NAME:
            return configuration.with_changes(central={**configuration.central.model_dump(), "scope": new_scope})
        senses = {name: sense.model_dump() for name, sense in configuration.senses.items()}
        senses[option.target]["scope"] = new_scope
        return configuration.with_changes(senses=senses)
    if option.kind == "retire":
        return configuration.with_changes(
            admitted_macros=[m.model_dump() for m in configuration.admitted_macros if m.id != option.target]
        )
    if option.kind == "strategy":
        return configuration.with_changes(active_strategy=option.target)
    if option.kind == "level":
        return configuration.with_changes(exploration_level=option.target)
    raise ValueError(f"{option.id} changes no configuration")


def blocked_by(option: ChangeOption, configuration: Configuration, state: BoundsState) -> Optional[str]:
    """The bound that keeps `option` off the criteria, or None when it may be offered. Never a preference."""
    if is_no_change(option, configuration):
        return None
    bounds = configuration.bounds
    if state.trials >= bounds.trials_in_flight:
        return f"one trial in flight: {state.trials} already"
    whole = state.cooling_left(SYSTEM2_KEY)
    if whole:
        return f"cooling: System 2 as a whole rests {whole} more decisions"
    key = option.cooling_key
    if key is not None and key != SYSTEM2_KEY and state.cooling_left(key):
        return f"cooling: {key} rests {state.cooling_left(key)} more decisions"
    if option.is_scope_change:
        assert option.target is not None and option.channel is not None
        scope = scope_of(configuration, option.target)
        if option.kind == "widen":
            if len(scope) >= bounds.max_scope_channels:
                return f"scope size: {option.target} already has {len(scope)} channels, the bound"
            if option.channel not in addable(configuration, option.target):
                return f"{option.channel} cannot be added to {option.target}'s scope"
        else:
            if option.channel == "menu":
                return "menu is never narrowed"
            if option.channel not in scope:
                return f"{option.channel} is not in {option.target}'s scope"
    elif option.kind == "retire":
        if option.target in BUILTIN_IDS:
            return f"{option.target} is a built-in action; built-in actions are never retired"
        if option.target not in {m.id for m in configuration.admitted_macros}:
            return f"{option.target} is not an admitted macro"
    elif option.kind == "macro":
        if not state.slow_path_available:
            return "the slow path is off or already busy"
        return None
    elif option.kind == "strategy" and option.target not in state.archive_ids:
        return f"{option.target} is not in the archive"
    try:
        apply_change(configuration, option)
    except (ValidationError, ValueError) as exc:
        return f"the configuration would not validate: {str(exc).splitlines()[0][:160]}"
    return None


def filter_changes(
    options: Sequence[ChangeOption], configuration: Configuration, state: BoundsState
) -> Tuple[List[ChangeOption], Dict[str, str]]:
    """The options the bounds allow, in the given order, and each blocked option with its bound."""
    allowed: List[ChangeOption] = []
    blocked: Dict[str, str] = {}
    for option in options:
        reason = blocked_by(option, configuration, state)
        if reason is None:
            allowed.append(option)
        else:
            blocked[option.id] = reason
    return allowed, blocked


def offers_a_change(options: Sequence[ChangeOption], configuration: Configuration) -> bool:
    return any(not is_no_change(o, configuration) for o in options)


def reflector_questions(spec: ReflectorSpec, criteria: Sequence[ChangeOption]) -> Dict[str, QuestionSpec]:
    """The reflector's three finite questions; the change criteria are exactly the options the bounds allow."""
    pre = preamble(spec.instance_spec())
    return {
        "speak": NoulQuestion(instructions=f"{pre} Must the slow system's central hear a proposal from you now?"),
        "change": ChoiceQuestion(
            instructions=f"{pre} Which configuration change do you propose?",
            criteria={o.id: o.description for o in criteria},
        ),
        "reason": ChoiceQuestion(
            instructions=f"{pre} Which reason best describes why?",
            criteria={r: reason_words(r) for r in spec.reasons},
        ),
    }


class Proposal(BaseModel):
    """What a reflector that spoke sends System 2's central: who, which change, why, how strongly."""

    model_config = ConfigDict(frozen=True)

    reflector: str
    title: str
    change: str
    description: str
    reason: str
    strength: float


def proposal_of(
    spec: ReflectorSpec, result: InstanceResult, options: Sequence[ChangeOption], configuration: Configuration
) -> Optional[Proposal]:
    """The proposal a reflector sends, or None when it was silent, missed, or chose no change."""
    if result.missed or not result.spoke or result.change is None or result.reason is None or result.strength is None:
        return None
    by_id = {o.id: o for o in options}
    option = by_id.get(result.change)
    if option is None or is_no_change(option, configuration):
        return None
    return Proposal(
        reflector=spec.name, title=spec.title, change=option.id, description=option.description,
        reason=result.reason, strength=result.strength,
    )


class ConfigDiff(BaseModel):
    """What changed between two configurations, in words, with the versions."""

    model_config = ConfigDict(frozen=True)

    old_version: int
    new_version: int
    changes: Tuple[str, ...] = ()


def config_diff(old: Configuration, new: Configuration) -> ConfigDiff:
    changes: List[str] = []

    def scope_change(name: str, before: Sequence[str], after: Sequence[str]) -> None:
        added = [c for c in after if c not in before]
        dropped = [c for c in before if c not in after]
        if added or dropped:
            parts = [f"+ {c}" for c in added] + [f"- {c}" for c in dropped]
            changes.append(f"{name} scope: {', '.join(parts)}")

    for name in SENSE_NAMES:
        scope_change(name, old.senses[name].scope, new.senses[name].scope)
    scope_change(CENTRAL_NAME, old.central.scope, new.central.scope)
    if old.exploration_level != new.exploration_level:
        changes.append(f"exploration level: {old.exploration_level} -> {new.exploration_level}")
    if old.active_strategy != new.active_strategy:
        changes.append(f"active strategy: {old.active_strategy} -> {new.active_strategy}")
    before = [m.id for m in old.admitted_macros]
    after = [m.id for m in new.admitted_macros]
    for macro in after:
        if macro not in before:
            changes.append(f"admitted macros: + {macro}")
    for macro in before:
        if macro not in after:
            changes.append(f"admitted macros: - {macro}")
    return ConfigDiff(old_version=old.version, new_version=new.version, changes=tuple(changes))
