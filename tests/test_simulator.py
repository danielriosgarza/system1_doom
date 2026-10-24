import pytest
from system1_doom.actions import ActionVocabulary
from system1_doom.simulator import BoundedSimulator, ProjectionLimits
from tests.test_state_and_actions import make_sample_world_state


def test_simulator_enforces_explicit_bounds():
    vocab = ActionVocabulary.default()
    state = make_sample_world_state(health=50.0, ammo=10, enemies=2, pickups=1)
    candidates = vocab.available_actions(state)
    assert len(candidates) > 4

    limits = ProjectionLimits(
        max_candidate_count=4,
        max_simulation_depth=3,
        max_wall_clock_budget_sec=0.05,
        max_branching_factor=2,
    )
    sim = BoundedSimulator(limits=limits)
    results = sim.project_candidates(state, candidates)

    assert len(results) <= limits.max_candidate_count
    for action_id, outcome in results.items():
        assert outcome.action_id == action_id
        assert 1 <= outcome.depth_reached <= limits.max_simulation_depth
        assert len(outcome.projected_states) <= limits.max_simulation_depth
        assert len(outcome.branch_values) <= limits.max_branching_factor


def test_simulator_distinguishes_combat_retreat_and_pickup_outcomes():
    vocab = ActionVocabulary.default()
    state = make_sample_world_state(health=35.0, ammo=10, enemies=1, pickups=1)
    sim = BoundedSimulator()

    retreat = vocab.get("retreat_to_cover")
    shoot = vocab.get("shoot")
    pickup = vocab.get("approach_pickup")
    assert retreat and shoot and pickup

    outcomes = sim.project_candidates(state, [retreat, shoot, pickup])
    assert outcomes["retreat_to_cover"].expected_damage_taken < outcomes["shoot"].expected_damage_taken
    assert outcomes["shoot"].expected_damage_dealt > outcomes["retreat_to_cover"].expected_damage_dealt
    assert outcomes["approach_pickup"].expected_resource_gain > outcomes["retreat_to_cover"].expected_resource_gain


def test_simulator_caches_empirical_transitions():
    vocab = ActionVocabulary.default()
    state = make_sample_world_state(health=60.0, ammo=10, enemies=1, pickups=0)
    sim = BoundedSimulator()
    sim.record_empirical_outcome(state.context_signature(), "circle_strafe_left", reward_delta=12.5, damage_taken=0.0)

    macro = vocab.get("circle_strafe_left")
    assert macro is not None
    outcome = sim.project_action(state, macro)
    assert outcome.empirical_samples == 1
    assert outcome.expected_value > 0.0
