import pytest
from pydantic import ValidationError

from system1_doom.actions import (
    DEFAULT_MACROS,
    DEFAULT_PRIMITIVES,
    PRIMITIVE_ACTION_IDS,
    ActionSpec,
    ActionVocabulary,
    PreconditionSpec,
)
from system1_doom.state import (
    ControllerMemory,
    EnemyObservation,
    Observation,
    PickupObservation,
    Pose3D,
    WorldState,
)


def make_sample_world_state(health: float = 80.0, ammo: int = 12, enemies: int = 1, pickups: int = 1) -> WorldState:
    enemy_list = tuple(
        EnemyObservation(
            enemy_id=f"imp_{i}",
            name="DoomImp",
            distance=180.0 + i * 30.0,
            angle_offset=-10.0 + i * 20.0,
            screen_x=140,
            screen_y=120,
            width=32,
            height=64,
        )
        for i in range(enemies)
    )
    pickup_list = tuple(
        PickupObservation(
            pickup_id=f"medikit_{i}",
            name="Medikit",
            category="health",
            distance=150.0,
            angle_offset=5.0,
            screen_x=165,
            screen_y=140,
        )
        for i in range(pickups)
    )
    obs = Observation(
        tick=10,
        health=health,
        armor=25.0,
        ammo=ammo,
        current_weapon="shotgun",
        visible_enemies=enemy_list,
        visible_pickups=pickup_list,
        recent_incoming_damage=10.0,
        recent_outgoing_damage=20.0,
        recent_kills=0,
        movement_state="moving_forward",
        recent_actions=("move_forward", "shoot"),
        position=Pose3D(x=120.0, y=64.0, z=0.0, angle=45.0),
        episode_progress={"tick": 10.0, "distance_to_goal": 850.0, "reward_so_far": 15.0},
    )
    mem = ControllerMemory(
        short_action_history=("move_forward", "turn_left", "shoot"),
        recent_state_summaries=("tick=8 hp=90", "tick=9 hp=80"),
        discovered_locations=("corridor_start", "pillar_left"),
        strategy_archive_refs=("strat_default_combat",),
    )
    return WorldState(observation=obs, memory=mem)


def test_world_state_is_immutable():
    ws = make_sample_world_state()
    with pytest.raises(ValidationError):
        ws.observation = ws.observation  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ws.observation.health = 100.0  # type: ignore[misc]


def test_world_state_hash_and_text_summary():
    ws1 = make_sample_world_state(health=75.0, ammo=10)
    ws2 = make_sample_world_state(health=75.0, ammo=10)
    ws3 = make_sample_world_state(health=25.0, ammo=10)

    assert ws1.state_hash() == ws2.state_hash()
    assert ws1.state_hash() != ws3.state_hash()
    summary = ws1.to_d1_state_text()
    assert "health=75.0" in summary
    assert "DoomImp" in summary
    assert ws1.context_signature() != ws3.context_signature()


def test_action_spec_rejects_unbounded_or_invalid_primitives():
    # Empty primitive expansion is invalid
    with pytest.raises(ValidationError):
        ActionSpec(
            id="bad_empty",
            is_macro=True,
            parameters={},
            preconditions=PreconditionSpec(),
            maximum_duration=5,
            termination_condition="tick_limit_reached",
            primitive_expansion=(),
        )

    # Unknown primitive in expansion is invalid
    with pytest.raises(ValidationError):
        ActionSpec(
            id="bad_primitive",
            is_macro=True,
            parameters={},
            preconditions=PreconditionSpec(),
            maximum_duration=5,
            termination_condition="tick_limit_reached",
            primitive_expansion=("teleport_hack",),
        )

    # Expansion exceeding maximum_duration or excessive cap is invalid
    with pytest.raises(ValidationError):
        ActionSpec(
            id="bad_duration",
            is_macro=True,
            parameters={},
            preconditions=PreconditionSpec(),
            maximum_duration=2,
            termination_condition="tick_limit_reached",
            primitive_expansion=("move_forward", "move_forward", "shoot"),
        )


def test_default_primitives_and_macros_are_valid_and_filter_by_preconditions():
    vocab = ActionVocabulary.default()
    for p_id in PRIMITIVE_ACTION_IDS:
        assert vocab.get(p_id) is not None
    assert len(DEFAULT_PRIMITIVES) >= 9
    assert len(DEFAULT_MACROS) >= 4

    # Normal state with ammo and pickups: shoot, peek_and_fire, approach_pickup available
    ws_full = make_sample_world_state(health=80.0, ammo=10, enemies=1, pickups=1)
    avail_ids = {a.id for a in vocab.available_actions(ws_full)}
    assert "shoot" in avail_ids
    assert "peek_and_fire" in avail_ids
    assert "approach_pickup" in avail_ids

    # Zero ammo state: shoot and peek_and_fire filtered out by preconditions
    ws_no_ammo = make_sample_world_state(health=80.0, ammo=0, enemies=1, pickups=0)
    avail_no_ammo = {a.id for a in vocab.available_actions(ws_no_ammo)}
    assert "shoot" not in avail_no_ammo
    assert "peek_and_fire" not in avail_no_ammo
    assert "approach_pickup" not in avail_no_ammo
    assert "move_forward" in avail_no_ammo
    assert "strafe_left" in avail_no_ammo
