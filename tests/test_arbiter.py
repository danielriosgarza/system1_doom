import pytest

from system1_doom.actions import ActionVocabulary
from system1_doom.arbiter import FinalArbiter
from system1_doom.archive import StrategyArchive
from system1_doom.d1_client import D1UltraClient, load_api_key
from system1_doom.exploration import ExplorationController
from system1_doom.modules import BatchModuleEvaluator
from system1_doom.simulator import BoundedSimulator
from tests.test_state_and_actions import make_sample_world_state


def test_arbiter_combines_modules_projections_and_exploration_without_network():
    vocab = ActionVocabulary.default()
    sim = BoundedSimulator()
    exp_ctrl = ExplorationController()
    archive = StrategyArchive()
    disabled_d1 = D1UltraClient(enabled=False)
    evaluator = BatchModuleEvaluator(d1_client=disabled_d1)
    arbiter = FinalArbiter(d1_client=disabled_d1)

    state = make_sample_world_state(health=22.0, ammo=10, enemies=2, pickups=1)
    actions = tuple(vocab.available_actions(state))
    projections = sim.project_candidates(state, list(actions))
    mod_outputs = evaluator.evaluate_all(
        world_state=state,
        available_actions=actions,
        module_memories={},
        projected_outcomes=projections,
        execution_mode="async_cached",
    )
    exp_state = exp_ctrl.update_and_decide(
        state=state,
        progress_delta=1.0,
        failed_step=False,
        mean_module_uncertainty=0.25,
        active_strategy_id=archive.active_strategy().strategy_id,
    )

    decision = arbiter.arbitrate(
        world_state=state,
        available_actions=actions,
        module_outputs=mod_outputs,
        projected_outcomes=projections,
        exploration_state=exp_state,
        exploration_controller=exp_ctrl,
        active_strategy=archive.active_strategy(),
        execution_mode="async_cached",
        deterministic=True,
    )

    assert decision.selected_action_id in {a.id for a in actions}
    assert sum(decision.arbiter_distribution.values()) == pytest.approx(1.0, abs=1e-4)
    assert set(decision.component_breakdown[decision.selected_action_id].keys()) >= {
        "expected_value",
        "exploration_bonus",
        "novelty_bonus",
        "risk_penalty",
        "execution_cost",
    }


def test_live_d1_ultra_arbiter_decision():
    api_key = load_api_key()
    assert api_key
    client = D1UltraClient(api_key=api_key)
    vocab = ActionVocabulary.default()
    sim = BoundedSimulator()
    exp_ctrl = ExplorationController(d1_client=client)
    archive = StrategyArchive(d1_client=client)
    evaluator = BatchModuleEvaluator(d1_client=client)
    arbiter = FinalArbiter(d1_client=client)

    state = make_sample_world_state(health=28.0, ammo=8, enemies=2, pickups=1)
    actions = tuple(vocab.available_actions(state))
    projections = sim.project_candidates(state, list(actions))
    mod_outputs = evaluator.evaluate_all(
        world_state=state,
        available_actions=actions,
        module_memories={},
        projected_outcomes=projections,
        execution_mode="async_cached",
    )
    exp_state = exp_ctrl.current_state

    decision = arbiter.arbitrate(
        world_state=state,
        available_actions=actions,
        module_outputs=mod_outputs,
        projected_outcomes=projections,
        exploration_state=exp_state,
        exploration_controller=exp_ctrl,
        active_strategy=archive.active_strategy(),
        execution_mode="sync_d1",
        deterministic=True,
    )

    assert decision.used_d1_ultra is True
    assert decision.selected_action_id in {a.id for a in actions}
    assert sum(decision.arbiter_distribution.values()) == pytest.approx(1.0, abs=1e-4)
