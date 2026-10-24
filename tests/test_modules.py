import pytest

from system1_doom.actions import ActionVocabulary
from system1_doom.d1_client import D1UltraClient, load_api_key
from system1_doom.modules import (
    BatchModuleEvaluator,
    CombatModule,
    DecisionInput,
    GoalModule,
    NavigationModule,
    ResourceModule,
    SurvivalModule,
)
from system1_doom.simulator import BoundedSimulator
from tests.test_state_and_actions import make_sample_world_state


def test_all_five_modules_satisfy_contract_without_network():
    vocab = ActionVocabulary.default()
    sim = BoundedSimulator()
    state = make_sample_world_state(health=25.0, ammo=8, enemies=2, pickups=1)
    actions = tuple(vocab.available_actions(state))
    projections = sim.project_candidates(state, list(actions))

    inp = DecisionInput(
        world_state=state,
        available_actions=actions,
        local_memory={"consecutive_stalls": 0},
        projected_outcomes=projections,
        time_budget_sec=0.02,
    )

    disabled_d1 = D1UltraClient(enabled=False)
    modules = [
        SurvivalModule(d1_client=disabled_d1),
        CombatModule(d1_client=disabled_d1),
        NavigationModule(d1_client=disabled_d1),
        ResourceModule(d1_client=disabled_d1),
        GoalModule(d1_client=disabled_d1),
    ]

    outputs = {}
    for mod in modules:
        out = mod.evaluate(inp)
        outputs[mod.name] = out
        assert len(out.ranked_actions) == len(actions)
        assert set(out.action_probabilities.keys()) == {a.id for a in actions}
        assert sum(out.action_probabilities.values()) == pytest.approx(1.0, abs=1e-4)
        assert 0.0 <= out.confidence <= 1.0
        assert 0.0 <= out.uncertainty <= 1.0
        assert out.used_d1_ultra is False

    # With low health (25) and 2 enemies, Survival should prefer evasive/retreat actions over standing still
    assert outputs["survival"].ranked_actions[0] in (
        "weave_fire",
        "retreat_to_cover",
        "circle_strafe_left",
        "circle_strafe_right",
        "strafe_left",
        "strafe_right",
        "move_backward",
    )
    # Combat should prefer shooting or combat macros
    assert outputs["combat"].ranked_actions[0] in (
        "weave_fire",
        "strafe_left_shoot",
        "strafe_right_shoot",
        "shoot",
        "peek_and_fire",
        "circle_strafe_left",
        "circle_strafe_right",
    )
    # Resource should prefer approaching the visible pickup
    assert outputs["resource"].ranked_actions[0] == "approach_pickup"


def test_module_emits_action_expansion_request_on_repeated_failure():
    vocab = ActionVocabulary.default()
    state = make_sample_world_state(health=20.0, ammo=4, enemies=3, pickups=0)
    actions = tuple(vocab.available_actions(state))
    inp = DecisionInput(
        world_state=state,
        available_actions=actions,
        local_memory={"consecutive_damage_ticks": 5, "repeated_failures": 4},
        projected_outcomes={},
        time_budget_sec=0.02,
    )
    combat = CombatModule(d1_client=D1UltraClient(enabled=False))
    out = combat.evaluate(inp)
    assert out.request_action_expansion is True
    assert out.expansion_problem_description is not None
    assert len(out.expansion_problem_description) > 10


def test_live_d1_ultra_batch_module_evaluation():
    api_key = load_api_key()
    assert api_key
    client = D1UltraClient(api_key=api_key)
    vocab = ActionVocabulary.default()
    sim = BoundedSimulator()
    state = make_sample_world_state(health=30.0, ammo=10, enemies=2, pickups=1)
    actions = tuple(vocab.available_actions(state))
    projections = sim.project_candidates(state, list(actions))

    evaluator = BatchModuleEvaluator(d1_client=client)
    outputs = evaluator.evaluate_all(
        world_state=state,
        available_actions=actions,
        module_memories={},
        projected_outcomes=projections,
        time_budget_sec=10.0,
        execution_mode="sync_d1",
    )

    assert set(outputs.keys()) == {"survival", "combat", "navigation", "resource", "goal"}
    for name, out in outputs.items():
        assert out.used_d1_ultra is True
        assert sum(out.action_probabilities.values()) == pytest.approx(1.0, abs=1e-4)
        assert out.ranked_actions[0] in {a.id for a in actions}
