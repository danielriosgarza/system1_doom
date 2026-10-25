"""Typed detail records for decision traces.

A tick trace carries the frozen state, why actions were pruned, the simulator's projection of the
executed action, and what the executed action changed; the six instance results and the pick come
from `instance.py` and `system1.py`. Everything here is a reading of values play already computed;
nothing in this module feeds back into control.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field
from system1_doom.features import MODULE_NAMES, module_rewards

if TYPE_CHECKING:
    from system1_doom.actions import ActionSpec
    from system1_doom.simulator import ProjectedOutcome
    from system1_doom.state import WorldState
    from system1_doom.vizdoom_env import ExecutionStepResult

UNSUPPORTED_BY_SCENARIO = "unsupported_by_scenario"


def _r(value: float) -> float:
    return round(float(value), 4)


class PositionTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0


class WallTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    front: float = 0.0
    left: float = 0.0
    right: float = 0.0


class EnemyTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    distance: float
    angle_offset: float
    screen_x: int
    screen_y: int
    width: int
    height: int
    is_attacking: bool = False
    attacks_without_hit: int = 0


class PickupTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    category: str
    distance: float
    angle_offset: float
    screen_x: int
    screen_y: int
    width: int = 12
    height: int = 12


class LandmarkTrace(BaseModel):
    """A pickup remembered from earlier in the episode: where it lies from this tick's pose, and its record."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    category: str
    x: float = 0.0
    y: float = 0.0
    distance: float
    bearing: float = Field(description="Degrees from the facing, positive to the left")
    in_view: bool = False
    last_seen_tick: int = 0
    reward_agreement: Optional[float] = Field(default=None, description="How reward went with getting closer, -1 to 1")
    reward_moves: int = 0
    approaches_nowhere: int = 0


class StateTrace(BaseModel):
    """The frozen world state of a tick, from which every evidence channel was rendered."""

    model_config = ConfigDict(frozen=True)

    tick: int
    episode_tick: int = 0
    health: float
    armor: float
    ammo: int
    weapon: str
    movement: str
    position: PositionTrace
    walls: WallTrace
    enemies: List[EnemyTrace] = Field(default_factory=list)
    pickups: List[PickupTrace] = Field(default_factory=list)
    landmarks: List[LandmarkTrace] = Field(default_factory=list)
    recent_incoming_damage: float = 0.0
    recent_outgoing_damage: float = 0.0
    recent_hits: int = 0
    recent_kills: int = 0
    recent_actions: List[str] = Field(default_factory=list)
    episode_progress: Dict[str, float] = Field(default_factory=dict)
    screen_width: int = 320
    screen_height: int = 240


class ProjectionStepTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    primitive: str
    health: float
    damage_taken: float
    damage_dealt: float
    x: float
    y: float
    angle: float


class ProjectionChainTrace(BaseModel):
    """The bounded simulator's rollout of the selected action, primitive by primitive (first branch)."""

    model_config = ConfigDict(frozen=True)

    action_id: str
    steps: List[ProjectionStepTrace] = Field(default_factory=list)
    branch_values: List[float] = Field(default_factory=list)
    expected_value: float = 0.0
    empirical_samples: int = 0
    depth_reached: int = 0


class OutcomeTrace(BaseModel):
    """What the executed action (or the idle of a missed tick) changed, and the per-network rewards it becomes."""

    model_config = ConfigDict(frozen=True)

    reward: float = 0.0
    damage_taken: float = 0.0
    hits_delta: float = 0.0
    kills_delta: float = 0.0
    health_gain: float = 0.0
    armor_gain: float = 0.0
    ammo_gain: float = 0.0
    new_cells: int = 0
    displacement: float = 0.0
    died: bool = False
    health_after: float = 0.0
    armor_after: float = 0.0
    episode_finished: bool = False
    module_rewards: Dict[str, float] = Field(default_factory=dict)


class SlowPathRequestTrace(BaseModel):
    """An expansion request handed to the slow worker during this tick."""

    model_config = ConfigDict(frozen=True)

    module: str
    description: str


def state_trace(world_state: "WorldState") -> StateTrace:
    obs = world_state.observation
    return StateTrace(
        tick=obs.tick,
        episode_tick=int(obs.episode_progress.get("episode_tick", 0.0)),
        health=obs.health,
        armor=obs.armor,
        ammo=obs.ammo,
        weapon=obs.current_weapon,
        movement=obs.movement_state,
        position=PositionTrace(x=_r(obs.position.x), y=_r(obs.position.y), angle=_r(obs.position.angle)),
        walls=WallTrace(front=obs.wall_distance_front, left=obs.wall_distance_left, right=obs.wall_distance_right),
        enemies=[
            EnemyTrace(
                id=e.enemy_id,
                name=e.name,
                distance=e.distance,
                angle_offset=e.angle_offset,
                screen_x=e.screen_x,
                screen_y=e.screen_y,
                width=e.width,
                height=e.height,
                is_attacking=e.is_attacking,
                attacks_without_hit=e.attacks_without_hit,
            )
            for e in obs.visible_enemies
        ],
        pickups=[
            PickupTrace(
                id=p.pickup_id,
                name=p.name,
                category=p.category,
                distance=p.distance,
                angle_offset=p.angle_offset,
                screen_x=p.screen_x,
                screen_y=p.screen_y,
                width=p.width,
                height=p.height,
            )
            for p in obs.visible_pickups
        ],
        landmarks=[
            LandmarkTrace(
                id=m.landmark_id,
                name=m.name,
                category=m.category,
                x=m.x,
                y=m.y,
                distance=m.distance,
                bearing=m.bearing,
                in_view=m.in_view,
                last_seen_tick=m.last_seen_tick,
                reward_agreement=m.reward_agreement,
                reward_moves=m.reward_moves,
                approaches_nowhere=m.approaches_nowhere,
            )
            for m in obs.landmarks
        ],
        recent_incoming_damage=_r(obs.recent_incoming_damage),
        recent_outgoing_damage=_r(obs.recent_outgoing_damage),
        recent_hits=obs.recent_hits,
        recent_kills=obs.recent_kills,
        recent_actions=list(obs.recent_actions),
        episode_progress={k: _r(v) for k, v in obs.episode_progress.items()},
        screen_width=obs.screen_width,
        screen_height=obs.screen_height,
    )


def pruned_actions(
    vocabulary: Sequence["ActionSpec"],
    available_ids: Sequence[str],
    world_state: "WorldState",
    supported: Callable[["ActionSpec"], bool],
) -> Dict[str, str]:
    """Every vocabulary action left off this tick's menu, with the first precondition it failed."""
    keep = set(available_ids)
    pruned: Dict[str, str] = {}
    for action in vocabulary:
        if action.id in keep:
            continue
        pruned[action.id] = action.preconditions.failing_condition(world_state) or (
            UNSUPPORTED_BY_SCENARIO if not supported(action) else "not_offered"
        )
    return pruned


def projection_chain(outcome: "ProjectedOutcome", action: "ActionSpec") -> ProjectionChainTrace:
    steps = [
        ProjectionStepTrace(
            primitive=action.primitive_expansion[i] if i < len(action.primitive_expansion) else "",
            health=_r(state.observation.health),
            damage_taken=_r(state.observation.recent_incoming_damage),
            damage_dealt=_r(state.observation.recent_outgoing_damage),
            x=_r(state.observation.position.x),
            y=_r(state.observation.position.y),
            angle=_r(state.observation.position.angle),
        )
        for i, state in enumerate(outcome.projected_states)
    ]
    return ProjectionChainTrace(
        action_id=outcome.action_id,
        steps=steps,
        branch_values=[_r(v) for v in outcome.branch_values],
        expected_value=_r(outcome.expected_value),
        empirical_samples=outcome.empirical_samples,
        depth_reached=outcome.depth_reached,
    )


def projection_summary(outcome: "ProjectedOutcome") -> Dict[str, float]:
    return {
        "expected_value": round(outcome.expected_value, 4),
        "expected_damage_taken": round(outcome.expected_damage_taken, 4),
        "expected_damage_dealt": round(outcome.expected_damage_dealt, 4),
        "survival_probability": round(outcome.survival_probability, 4),
        "expected_resource_gain": round(outcome.expected_resource_gain, 4),
        "expected_positional_progress": round(outcome.expected_positional_progress, 4),
        "empirical_samples": float(outcome.empirical_samples),
        "depth_reached": float(outcome.depth_reached),
    }


def outcome_trace(result: "ExecutionStepResult") -> OutcomeTrace:
    rewards = module_rewards(result)
    return OutcomeTrace(
        reward=_r(result.reward),
        damage_taken=_r(result.damage_taken),
        hits_delta=_r(result.hits_delta),
        kills_delta=_r(result.kills_delta),
        health_gain=_r(result.health_gain),
        armor_gain=_r(result.armor_gain),
        ammo_gain=_r(result.ammo_gain),
        new_cells=int(result.new_cells),
        displacement=_r(result.displacement),
        died=bool(result.died),
        health_after=_r(result.health_after),
        armor_after=_r(result.armor),
        episode_finished=bool(result.episode_finished),
        module_rewards={name: _r(v) for name, v in zip(MODULE_NAMES, rewards)},
    )
