from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field, model_validator

from system1_doom.state import WorldState

PRIMITIVE_ACTION_IDS: Tuple[str, ...] = (
    "move_forward",
    "move_backward",
    "strafe_left",
    "strafe_right",
    "turn_left",
    "turn_right",
    "shoot",
    "use",
    "switch_weapon_1",
    "switch_weapon_2",
    "switch_weapon_3",
    "strafe_left_shoot",
    "strafe_right_shoot",
)
STRAFE_FIRE_PRIMITIVES: Tuple[str, ...] = ("strafe_left_shoot", "strafe_right_shoot")

MAX_ALLOWED_MACRO_DURATION: int = 16


class PreconditionSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_ammo: int = 0
    max_ammo: int = 9999
    min_health: float = 0.0
    max_health: float = 200.0
    requires_visible_enemy: bool = False
    requires_visible_pickup: bool = False
    min_wall_distance_front: float = 0.0
    max_wall_distance_front: float = 99999.0
    excluded_weapons: Tuple[str, ...] = ()

    def is_satisfied(self, state: WorldState) -> bool:
        obs = state.observation
        if obs.ammo < self.min_ammo or obs.ammo > self.max_ammo:
            return False
        if obs.health < self.min_health or obs.health > self.max_health:
            return False
        if self.requires_visible_enemy and len(obs.visible_enemies) == 0:
            return False
        if self.requires_visible_pickup and len(obs.visible_pickups) == 0:
            return False
        if obs.wall_distance_front < self.min_wall_distance_front:
            return False
        if obs.wall_distance_front > self.max_wall_distance_front:
            return False
        if self.excluded_weapons and obs.current_weapon in self.excluded_weapons:
            return False
        return True

    def failing_condition(self, state: WorldState) -> Optional[str]:
        """Name of the first precondition `state` fails, in the order `is_satisfied` checks them; None if all pass."""
        obs = state.observation
        if obs.ammo < self.min_ammo:
            return "min_ammo"
        if obs.ammo > self.max_ammo:
            return "max_ammo"
        if obs.health < self.min_health:
            return "min_health"
        if obs.health > self.max_health:
            return "max_health"
        if self.requires_visible_enemy and len(obs.visible_enemies) == 0:
            return "requires_visible_enemy"
        if self.requires_visible_pickup and len(obs.visible_pickups) == 0:
            return "requires_visible_pickup"
        if obs.wall_distance_front < self.min_wall_distance_front:
            return "min_wall_distance_front"
        if obs.wall_distance_front > self.max_wall_distance_front:
            return "max_wall_distance_front"
        if self.excluded_weapons and obs.current_weapon in self.excluded_weapons:
            return "excluded_weapons"
        return None


class ActionSpec(BaseModel):
    """Finite, bounded executable action specification (primitive or macro-action)."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=64)
    description: str = "Bounded executable Doom action"
    is_macro: bool = False
    parameters: Dict[str, Any] = Field(default_factory=dict)
    preconditions: PreconditionSpec = Field(default_factory=PreconditionSpec)
    maximum_duration: int = Field(ge=1, le=MAX_ALLOWED_MACRO_DURATION)
    termination_condition: str = Field(min_length=1, max_length=128)
    primitive_expansion: Tuple[str, ...]

    @model_validator(mode="after")
    def _validate_finite_executable_procedure(self) -> "ActionSpec":
        if len(self.primitive_expansion) == 0:
            raise ValueError(f"Action '{self.id}' has an empty primitive_expansion.")
        if len(self.primitive_expansion) > self.maximum_duration:
            raise ValueError(
                f"Action '{self.id}' primitive_expansion length ({len(self.primitive_expansion)}) "
                f"exceeds maximum_duration ({self.maximum_duration})."
            )
        for prim in self.primitive_expansion:
            if prim not in PRIMITIVE_ACTION_IDS:
                raise ValueError(
                    f"Action '{self.id}' references unknown or illegal primitive '{prim}'. "
                    f"Allowed primitives: {PRIMITIVE_ACTION_IDS}"
                )
        if not self.is_macro and (len(self.primitive_expansion) != 1 or self.primitive_expansion[0] != self.id):
            raise ValueError(f"Primitive action '{self.id}' must expand to ({self.id!r},).")
        return self

    @property
    def execution_cost(self) -> float:
        """Normalized execution cost based on sequence length and ammo consumption."""
        shots = sum(1 for p in self.primitive_expansion if p.endswith("shoot"))
        return 0.02 * len(self.primitive_expansion) + 0.02 * shots


DEFAULT_PRIMITIVES: Tuple[ActionSpec, ...] = (
    ActionSpec(
        id="move_forward",
        description="Advance forward toward the corridor goal or next room",
        is_macro=False,
        parameters={"step_size": 1},
        preconditions=PreconditionSpec(min_wall_distance_front=16.0),
        maximum_duration=8,
        termination_condition="single_tick_completed",
        primitive_expansion=("move_forward",),
    ),
    ActionSpec(
        id="move_backward",
        description="Retreat backward away from point-blank threats when critically injured",
        is_macro=False,
        parameters={"step_size": 1},
        preconditions=PreconditionSpec(max_health=45.0, requires_visible_enemy=True),
        maximum_duration=8,
        termination_condition="single_tick_completed",
        primitive_expansion=("move_backward",),
    ),
    ActionSpec(
        id="strafe_left",
        description="Sidestep left perpendicular to heading to dodge projectiles or reposition",
        is_macro=False,
        parameters={"step_size": 1},
        preconditions=PreconditionSpec(),
        maximum_duration=8,
        termination_condition="single_tick_completed",
        primitive_expansion=("strafe_left",),
    ),
    ActionSpec(
        id="strafe_right",
        description="Sidestep right perpendicular to heading to dodge projectiles or reposition",
        is_macro=False,
        parameters={"step_size": 1},
        preconditions=PreconditionSpec(),
        maximum_duration=8,
        termination_condition="single_tick_completed",
        primitive_expansion=("strafe_right",),
    ),
    ActionSpec(
        id="turn_left",
        description="Rotate view left to aim at left-side targets or scan room",
        is_macro=False,
        parameters={"degrees": 15},
        preconditions=PreconditionSpec(),
        maximum_duration=8,
        termination_condition="single_tick_completed",
        primitive_expansion=("turn_left",),
    ),
    ActionSpec(
        id="turn_right",
        description="Rotate view right to aim at right-side targets or scan room",
        is_macro=False,
        parameters={"degrees": 15},
        preconditions=PreconditionSpec(),
        maximum_duration=8,
        termination_condition="single_tick_completed",
        primitive_expansion=("turn_right",),
    ),
    ActionSpec(
        id="shoot",
        description="Aim and fire current weapon at visible enemy target",
        is_macro=False,
        parameters={"shots": 1},
        preconditions=PreconditionSpec(min_ammo=1, requires_visible_enemy=True),
        maximum_duration=8,
        termination_condition="weapon_fired_or_no_ammo",
        primitive_expansion=("shoot",),
    ),
    ActionSpec(
        id="use",
        description="Interact with doors, switches, or lifts directly ahead within reach",
        is_macro=False,
        parameters={},
        preconditions=PreconditionSpec(max_wall_distance_front=64.0),
        maximum_duration=8,
        termination_condition="single_tick_completed",
        primitive_expansion=("use",),
    ),
    ActionSpec(
        id="switch_weapon_1",
        description="Switch to slot 1 melee weapon when out of ammo",
        is_macro=False,
        parameters={"slot": 1},
        preconditions=PreconditionSpec(max_ammo=0, excluded_weapons=("fist_chainsaw",)),
        maximum_duration=8,
        termination_condition="weapon_switched",
        primitive_expansion=("switch_weapon_1",),
    ),
    ActionSpec(
        id="switch_weapon_2",
        description="Switch to slot 2 pistol",
        is_macro=False,
        parameters={"slot": 2},
        preconditions=PreconditionSpec(min_ammo=1, excluded_weapons=("pistol", "shotgun", "chaingun")),
        maximum_duration=8,
        termination_condition="weapon_switched",
        primitive_expansion=("switch_weapon_2",),
    ),
    ActionSpec(
        id="switch_weapon_3",
        description="Switch to slot 3 shotgun",
        is_macro=False,
        parameters={"slot": 3},
        preconditions=PreconditionSpec(min_ammo=1, excluded_weapons=("shotgun", "pistol", "chaingun")),
        maximum_duration=8,
        termination_condition="weapon_switched",
        primitive_expansion=("switch_weapon_3",),
    ),
    ActionSpec(
        id="strafe_left_shoot",
        description="Strafe left while tracking the target, firing whenever it is centred",
        is_macro=False,
        parameters={"shots": 1},
        preconditions=PreconditionSpec(min_ammo=1, requires_visible_enemy=True),
        maximum_duration=8,
        termination_condition="single_tick_completed",
        primitive_expansion=("strafe_left_shoot",),
    ),
    ActionSpec(
        id="strafe_right_shoot",
        description="Strafe right while tracking the target, firing whenever it is centred",
        is_macro=False,
        parameters={"shots": 1},
        preconditions=PreconditionSpec(min_ammo=1, requires_visible_enemy=True),
        maximum_duration=8,
        termination_condition="single_tick_completed",
        primitive_expansion=("strafe_right_shoot",),
    ),
)

DEFAULT_MACROS: Tuple[ActionSpec, ...] = (
    ActionSpec(
        id="circle_strafe_left",
        description="Turn left toward left-side enemy, fire, strafe left to evade fire, and fire a second shot",
        is_macro=True,
        parameters={"target": "left_or_nearest_enemy", "duration": 4},
        preconditions=PreconditionSpec(min_ammo=1, requires_visible_enemy=True),
        maximum_duration=8,
        termination_condition="enemy_eliminated_or_duration_elapsed",
        primitive_expansion=("turn_left", "shoot", "strafe_left", "shoot"),
    ),
    ActionSpec(
        id="circle_strafe_right",
        description="Turn right toward right-side enemy, fire, strafe right to evade fire, and fire a second shot",
        is_macro=True,
        parameters={"target": "right_or_nearest_enemy", "duration": 4},
        preconditions=PreconditionSpec(min_ammo=1, requires_visible_enemy=True),
        maximum_duration=8,
        termination_condition="enemy_eliminated_or_duration_elapsed",
        primitive_expansion=("turn_right", "shoot", "strafe_right", "shoot"),
    ),
    ActionSpec(
        id="retreat_to_cover",
        description="Backpedal while sidestepping away from heavy incoming damage when health is low",
        is_macro=True,
        parameters={"direction": "backward_left", "duration": 3},
        preconditions=PreconditionSpec(max_health=45.0, requires_visible_enemy=True),
        maximum_duration=8,
        termination_condition="damage_stopped_or_duration_elapsed",
        primitive_expansion=("move_backward", "strafe_left", "move_backward"),
    ),
    ActionSpec(
        id="approach_pickup",
        description="Sprint forward down the corridor toward visible armor, health, weapon, or goal pickup",
        is_macro=True,
        parameters={"pickup_id": "nearest_pickup", "duration": 4},
        preconditions=PreconditionSpec(requires_visible_pickup=True, min_wall_distance_front=24.0),
        maximum_duration=8,
        termination_condition="pickup_collected_or_enemy_encountered",
        primitive_expansion=("move_forward", "move_forward", "move_forward", "move_forward"),
    ),
    ActionSpec(
        id="peek_and_fire",
        description="Engage visible enemy with an aimed double burst while weaving left and right",
        is_macro=True,
        parameters={"direction": "left_right", "burst_length": 4},
        preconditions=PreconditionSpec(min_ammo=1, requires_visible_enemy=True),
        maximum_duration=8,
        termination_condition="enemy_eliminated_or_no_ammo",
        primitive_expansion=("strafe_left", "shoot", "strafe_right", "shoot"),
    ),
    ActionSpec(
        id="weave_fire",
        description="Keep strafing left then right while tracking the target and firing whenever it is centred",
        is_macro=True,
        parameters={"target": "locked_enemy", "duration": 4},
        preconditions=PreconditionSpec(min_ammo=1, requires_visible_enemy=True),
        maximum_duration=8,
        termination_condition="enemy_eliminated_or_duration_elapsed",
        primitive_expansion=("strafe_left_shoot", "strafe_left_shoot", "strafe_right_shoot", "strafe_right_shoot"),
    ),
)


BUILTIN_IDS = frozenset(a.id for a in DEFAULT_PRIMITIVES + DEFAULT_MACROS)


class ActionVocabulary:
    """Thread-safe finite vocabulary of primitive actions and admitted macro-actions."""

    def __init__(self, actions: Tuple[ActionSpec, ...] = DEFAULT_PRIMITIVES + DEFAULT_MACROS) -> None:
        self._actions: Dict[str, ActionSpec] = {a.id: a for a in actions}

    @classmethod
    def default(cls) -> "ActionVocabulary":
        return cls(DEFAULT_PRIMITIVES + DEFAULT_MACROS)

    def get(self, action_id: str) -> Optional[ActionSpec]:
        return self._actions.get(action_id)

    def all_actions(self) -> List[ActionSpec]:
        return list(self._actions.values())

    def available_actions(self, state: WorldState) -> List[ActionSpec]:
        avail = [a for a in self._actions.values() if a.preconditions.is_satisfied(state)]
        if not avail:
            avail = [self._actions["turn_left"], self._actions["turn_right"], self._actions["move_forward"]]
        return avail

    def register_admitted_macro(self, spec: ActionSpec) -> None:
        if not spec.is_macro:
            raise ValueError("Only macro-actions can be dynamically admitted into the vocabulary.")
        self._actions[spec.id] = spec

    def retire_macro(self, action_id: str) -> None:
        """Remove an admitted macro; built-in actions cannot be retired."""
        if action_id in BUILTIN_IDS:
            raise ValueError(f"'{action_id}' is a built-in action and cannot be retired.")
        self._actions.pop(action_id, None)
