"""Typed detail records for decision traces.

Each tick trace carries enough of the controller's working to replay the decision from it:
the frozen state, why actions were pruned, each module's utilities, the arbiter's score
arithmetic and pick rule, the projection of the chosen action, the strategy decision, and
what the executed action changed. Everything here is a reading of values the fast path
already computes; nothing in this module feeds back into control.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from system1_doom.features import MODULE_NAMES, module_rewards

if TYPE_CHECKING:
    from system1_doom.actions import ActionSpec
    from system1_doom.arbiter import ArbiterDecision
    from system1_doom.archive import StrategyDecision, StrategyEntry
    from system1_doom.modules import DecisionOutput
    from system1_doom.simulator import ProjectedOutcome
    from system1_doom.state import WorldState
    from system1_doom.vizdoom_env import ExecutionStepResult

UNSUPPORTED_BY_SCENARIO = "unsupported_by_scenario"


def _r(value: float) -> float:
    return round(float(value), 4)


class ModuleTrace(TypedDict, total=False):
    """One module's entry in `TickTrace.module_outputs`. Plain dict at runtime; typed for the schema."""

    top_action: Optional[str]
    confidence: float
    uncertainty: float
    request_action_expansion: bool
    expansion_problem: Optional[str]
    used_d1_ultra: bool
    probabilities: Dict[str, float]
    d1_top_action: Optional[str]
    d1_probabilities: Dict[str, float]
    utility_heuristic: Dict[str, float]
    utility_learned: Dict[str, float]
    trust: Dict[str, float]
    utility_blended: Dict[str, float]
    d1_weight: float
    request_additional_simulation: bool
    memory: Dict[str, int]


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


class StateTrace(BaseModel):
    """The frozen world state every module saw this tick."""

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
    recent_incoming_damage: float = 0.0
    recent_outgoing_damage: float = 0.0
    recent_kills: int = 0
    recent_actions: List[str] = Field(default_factory=list)
    episode_progress: Dict[str, float] = Field(default_factory=dict)
    screen_width: int = 320
    screen_height: int = 240


class ArbiterTrace(BaseModel):
    """The arbiter's arithmetic: one score per action, the weights behind it, and how the pick was made."""

    model_config = ConfigDict(frozen=True)

    action_scores: Dict[str, float] = Field(default_factory=dict)
    component_breakdown: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    module_weights: Dict[str, float] = Field(default_factory=dict)
    module_weights_heuristic: Dict[str, float] = Field(default_factory=dict)
    module_weights_gate: Optional[Dict[str, float]] = None
    gate_share: float = 0.0
    temperature: float = 0.0
    exploration_pressure: float = 0.0
    exploration_floor: float = 0.0
    deterministic: bool = False
    pick_rule: Literal["committed", "explored", "greedy", "sampled", "critical_cached"] = "greedy"
    score_margin: float = 0.0
    committed_by: Optional[str] = None
    confidence: float = 0.0


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


class StrategyEntryTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    context_signature: str
    action_sequence: List[str]
    observed_reward: float
    success_rate: float
    usage_count: int
    failure_modes: List[str] = Field(default_factory=list)
    novelty_signature: str = "default"


class SteeringTrace(BaseModel):
    """The four-way strategy meta-decision made after the action ran, and the archive it chose from."""

    model_config = ConfigDict(frozen=True)

    choice: str
    probabilities: Dict[str, float] = Field(default_factory=dict)
    scores: Dict[str, float] = Field(default_factory=dict)
    confidence: float = 0.0
    active_before: Optional[str] = None
    active_after: str
    entries: List[StrategyEntryTrace] = Field(default_factory=list)


class OutcomeTrace(BaseModel):
    """What the executed action changed in the game, and the per-module rewards it becomes."""

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
    """An expansion request this tick handed to the slow worker."""

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
        recent_incoming_damage=_r(obs.recent_incoming_damage),
        recent_outgoing_damage=_r(obs.recent_outgoing_damage),
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


def module_trace(out: "DecisionOutput", memory: Dict[str, int]) -> ModuleTrace:
    return ModuleTrace(
        top_action=out.ranked_actions[0] if out.ranked_actions else None,
        confidence=round(out.confidence, 4),
        uncertainty=round(out.uncertainty, 4),
        request_action_expansion=out.request_action_expansion,
        expansion_problem=out.expansion_problem_description,
        used_d1_ultra=out.used_d1_ultra,
        probabilities={k: round(v, 6) for k, v in out.action_probabilities.items()},
        d1_top_action=(
            max(out.d1_action_probabilities, key=out.d1_action_probabilities.get) if out.d1_action_probabilities else None
        ),
        d1_probabilities={k: round(v, 6) for k, v in out.d1_action_probabilities.items()},
        utility_heuristic={k: _r(v) for k, v in out.heuristic_utilities.items()},
        utility_learned={k: _r(v) for k, v in out.learned_utilities.items()},
        trust={k: _r(v) for k, v in out.trust.items()},
        utility_blended={k: _r(v) for k, v in out.utility_estimates.items()},
        d1_weight=out.d1_weight,
        request_additional_simulation=out.request_additional_simulation,
        memory={k: int(v) for k, v in memory.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
    )


def arbiter_trace(
    decision: "ArbiterDecision",
    gate_weights: Optional[Dict[str, float]],
    gate_share: float,
    exploration_floor: float,
    deterministic: bool,
) -> ArbiterTrace:
    return ArbiterTrace(
        action_scores={k: _r(v) for k, v in decision.action_scores.items()},
        component_breakdown=dict(decision.component_breakdown),
        module_weights=dict(decision.module_weights),
        module_weights_heuristic=dict(decision.heuristic_weights),
        module_weights_gate={k: _r(v) for k, v in gate_weights.items()} if gate_weights else None,
        gate_share=_r(gate_share),
        temperature=_r(decision.temperature_used),
        exploration_pressure=_r(decision.exploration_pressure_used),
        exploration_floor=_r(exploration_floor),
        deterministic=deterministic,
        pick_rule=decision.pick_rule,
        score_margin=_r(decision.score_margin),
        committed_by=decision.committed_by,
        confidence=_r(decision.confidence),
    )


def critical_arbiter_trace(exploration_floor: float, deterministic: bool) -> ArbiterTrace:
    return ArbiterTrace(
        pick_rule="critical_cached", exploration_floor=_r(exploration_floor), deterministic=deterministic, confidence=1.0
    )


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


def steering_trace(decision: "StrategyDecision", entries: Sequence["StrategyEntry"]) -> SteeringTrace:
    return SteeringTrace(
        choice=decision.choice,
        probabilities={k: _r(v) for k, v in decision.probabilities.items()},
        scores=dict(decision.scores),
        confidence=_r(decision.confidence),
        active_before=decision.previous_strategy_id,
        active_after=decision.selected_strategy_id,
        entries=[
            StrategyEntryTrace(
                strategy_id=e.strategy_id,
                context_signature=e.context_signature,
                action_sequence=list(e.action_sequence),
                observed_reward=e.observed_reward,
                success_rate=e.success_rate,
                usage_count=e.usage_count,
                failure_modes=list(e.failure_modes),
                novelty_signature=e.novelty_signature,
            )
            for e in entries
        ],
    )


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
