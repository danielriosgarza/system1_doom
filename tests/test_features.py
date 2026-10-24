import numpy as np

from system1_doom.actions import ActionSpec, ActionVocabulary
from system1_doom.features import ACTION_DIM, STATE_DIM, encode_action, encode_actions, encode_state
from system1_doom.state import EnemyObservation, Observation, PickupObservation, WorldState


def _combat_state() -> WorldState:
    return WorldState(
        observation=Observation(
            health=40.0,
            armor=100.0,
            ammo=30,
            visible_enemies=(
                EnemyObservation(enemy_id="z1", name="Zombieman", distance=300.0, angle_offset=-6.0),
                EnemyObservation(enemy_id="s1", name="ShotgunGuy", distance=120.0, angle_offset=30.0),
            ),
            visible_pickups=(PickupObservation(pickup_id="m1", name="Medikit", category="health", distance=200.0),),
            recent_incoming_damage=12.0,
            recent_actions=("strafe_left+shoot", "turn_left", "move_forward"),
            episode_progress={"episode_tick": 12.0},
        )
    )


def test_state_encoding_has_fixed_size_and_bounded_values():
    for state in (WorldState(observation=Observation()), _combat_state()):
        vec = encode_state(state)
        assert vec.shape == (STATE_DIM,)
        assert vec.dtype == np.float32
        assert np.all(np.isfinite(vec))
        assert vec.min() >= -1.0 and vec.max() <= 3.0


def test_state_encoding_reflects_threats_and_pickups():
    calm = encode_state(WorldState(observation=Observation()))
    combat = encode_state(_combat_state())
    assert not np.allclose(calm, combat)
    # Nearest enemy is the ShotgunGuy at 120 units: inside melee range and not aimed.
    assert combat[10] == 1.0
    assert combat[8] == 0.0
    # Nearest pickup is health.
    assert combat[14] == 1.0


def test_action_encoding_describes_primitive_composition():
    vocab = ActionVocabulary.default()
    actions = vocab.all_actions()
    mat = encode_actions(actions)
    assert mat.shape == (len(actions), ACTION_DIM)
    for action, row in zip(actions, mat):
        plan = action.primitive_expansion
        if not any(p.startswith("switch_weapon") or p.endswith("_shoot") for p in plan):
            assert row[:8].sum() == np.float32(1.0)
    assert not np.allclose(encode_action(vocab.get("shoot")), encode_action(vocab.get("move_forward")))


def test_strafe_fire_counts_as_both_strafing_and_shooting():
    vec = encode_action(ActionVocabulary.default().get("weave_fire"))
    assert vec[2] == np.float32(0.5) and vec[3] == np.float32(0.5)  # strafe left / right
    assert vec[6] == np.float32(1.0)  # every step fires


def test_new_macro_gets_an_encoding_without_retraining():
    macro = ActionSpec(
        id="zigzag_fire",
        description="Zigzag and fire",
        is_macro=True,
        maximum_duration=4,
        termination_condition="sequence_completed",
        primitive_expansion=("strafe_left", "shoot", "strafe_right", "shoot"),
    )
    vec = encode_action(macro)
    assert vec.shape == (ACTION_DIM,)
    assert vec[6] == np.float32(0.5)  # half of the plan is shooting
    assert vec[10] == 1.0  # macro flag
