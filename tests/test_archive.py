"""The strategy archive is a bounded store and evidence; it decides nothing."""

import pytest

from system1_doom.archive import DEFAULT_STRATEGIES, StrategyArchive, StrategyEntry
from tests.test_state_and_actions import make_sample_world_state


def _entry(i: int) -> StrategyEntry:
    return StrategyEntry(
        strategy_id=f"custom_strat_{i}",
        context_signature=make_sample_world_state().context_signature(),
        action_sequence=("strafe_left", "shoot", "strafe_right"),
        observed_reward=float(i),
        success_rate=0.6,
    )


def test_the_archive_holds_no_decision():
    archive = StrategyArchive()
    assert not hasattr(archive, "decide_strategy_action") and not hasattr(archive, "d1_client")
    assert [e.strategy_id for e in archive.entries()] == [e.strategy_id for e in DEFAULT_STRATEGIES]


def test_the_active_strategy_follows_the_configuration():
    archive = StrategyArchive(active_strategy="strat_corridor_advance")
    assert archive.active_strategy().strategy_id == "strat_corridor_advance"
    archive.set_active("strat_evasive_survival")
    assert archive.active_strategy().strategy_id == "strat_evasive_survival"
    with pytest.raises(KeyError):
        archive.set_active("strat_unknown")


def test_a_full_archive_makes_room_by_age_never_by_score():
    archive = StrategyArchive(max_entries=4, active_strategy="strat_tactical_combat")
    for i in range(3):
        archive.admit_strategy(_entry(i))
    ids = [e.strategy_id for e in archive.entries()]
    # The oldest entries that are not active leave first, whatever their record.
    assert len(ids) == 4 and ids[0] == "strat_tactical_combat"
    assert ids[1:] == ["custom_strat_0", "custom_strat_1", "custom_strat_2"]


def test_outcomes_update_the_record_shown_as_evidence():
    archive = StrategyArchive()
    before = archive.active_strategy()
    archive.record_outcome(before.strategy_id, reward=-5.0, success=False, failure_mode="took_heavy_damage")
    after = archive.active_strategy()
    assert after.usage_count == before.usage_count + 1 and after.observed_reward < before.observed_reward
    assert after.failure_modes == ("took_heavy_damage",)
