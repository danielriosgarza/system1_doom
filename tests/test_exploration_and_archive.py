import pytest

from system1_doom.archive import StrategyArchive, StrategyEntry
from system1_doom.exploration import ExplorationController
from tests.test_state_and_actions import make_sample_world_state


def test_exploration_pressure_increases_on_stall_and_decreases_in_high_risk():
    ctrl = ExplorationController()

    # Healthy state, stalled progress, high uncertainty -> high exploration pressure & higher temperature
    state_stalled = make_sample_world_state(health=90.0, ammo=20, enemies=0, pickups=0)
    exp_stalled = ctrl.update_and_decide(
        state=state_stalled,
        progress_delta=0.0,
        failed_step=True,
        mean_module_uncertainty=0.80,
        active_strategy_id="strat_nav",
        near_term_winning_sequence=False,
    )
    assert exp_stalled.performance_plateau_signal is False  # only 1 stall so far
    for _ in range(4):
        exp_stalled = ctrl.update_and_decide(
            state=state_stalled,
            progress_delta=0.0,
            failed_step=True,
            mean_module_uncertainty=0.85,
            active_strategy_id="strat_nav",
            near_term_winning_sequence=False,
        )
    assert exp_stalled.performance_plateau_signal is True
    assert exp_stalled.exploration_pressure > 0.55

    # High-risk state (low health + enemies + near-term winning sequence) -> low exploration pressure & lower temperature
    state_risk = make_sample_world_state(health=18.0, ammo=10, enemies=2, pickups=0)
    exp_risk = ctrl.update_and_decide(
        state=state_risk,
        progress_delta=5.0,
        failed_step=False,
        mean_module_uncertainty=0.20,
        active_strategy_id="strat_combat",
        near_term_winning_sequence=True,
    )
    assert exp_risk.exploration_pressure < exp_stalled.exploration_pressure
    assert exp_risk.temperature < exp_stalled.temperature


def test_strategy_archive_bounded_capacity_and_explicit_strategy_decision():
    archive = StrategyArchive(max_entries=4)
    state = make_sample_world_state(health=70.0, ammo=12, enemies=1, pickups=0)

    # Default strategies are pre-populated
    assert len(archive.entries()) >= 2
    initial_active = archive.active_strategy()
    assert initial_active is not None

    # Record repeated failures on current strategy -> controller should switch or request new proposal
    for _ in range(4):
        archive.record_outcome(initial_active.strategy_id, reward=-5.0, success=False, failure_mode="took_heavy_damage")

    decision = archive.decide_strategy_action(
        state=state,
        exploration_pressure=0.75,
        recent_failures=4,
    )
    assert decision.choice in (
        "switch_to_archived_strategy",
        "explore_variation",
        "request_new_strategy_proposal",
    )

    # Registering new strategies enforces bounded archive size
    for i in range(6):
        archive.admit_strategy(
            StrategyEntry(
                strategy_id=f"custom_strat_{i}",
                context_signature=state.context_signature(),
                action_sequence=("strafe_left", "shoot", "strafe_right"),
                observed_reward=float(i),
                success_rate=0.6,
                failure_modes=(),
                usage_count=1,
                novelty_signature=f"nov_{i}",
            )
        )
    assert len(archive.entries()) <= 4
