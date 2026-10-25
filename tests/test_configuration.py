"""The configuration: the design's defaults, its validation, versioning and serialisation."""

import pytest
from pydantic import ValidationError

from system1_doom.actions import ActionVocabulary
from system1_doom.configuration import (
    CHANNELS,
    SENSE_NAMES,
    Bounds,
    Configuration,
    default_configuration,
)


def test_the_default_is_the_designs_tables():
    configuration = default_configuration()
    assert configuration.version == 1 and configuration.exploration_level == "exploit"
    assert tuple(configuration.senses) == SENSE_NAMES
    assert {n: s.scope for n, s in configuration.senses.items()} == {
        "survival": ("vitals", "threats", "incoming", "projections", "menu"),
        "combat": ("threats", "outgoing", "vitals", "frame", "projections", "menu"),
        "navigation": ("landmarks", "geometry", "position", "progress", "menu"),
        "resource": ("landmarks", "vitals", "menu"),
        "goal": ("landmarks", "progress", "history", "archive", "values", "menu"),
    }
    assert {n: s.target for n, s in configuration.senses.items()} == {
        "survival": None, "combat": "enemy", "navigation": None, "resource": "pickup", "goal": None,
    }
    assert configuration.central.scope == ("messages", "relevance", "exploration", "vitals", "menu")
    assert configuration.senses["survival"].reasons == (
        "health_critical", "under_fire", "enemy_too_close", "recovering", "no_threat",
    )
    assert configuration.senses["combat"].concern == "winning the current fight"
    assert len(CHANNELS) == 19


def test_the_bounds_hold_the_designs_numbers():
    b = Bounds()
    assert (b.call_budget_sec, b.yes_at, b.system1_pool, b.system2_pool, b.max_scope_channels) == (5.0, 0.5, 6, 2, 7)
    assert (b.max_enemies, b.max_pickups, b.max_landmarks, b.max_history_steps, b.max_summaries) == (6, 6, 8, 6, 3)
    assert (b.cooling_decisions, b.history_ring, b.history_test_sample, b.system2_calls_per_cycle) == (60, 2000, 24, 40)
    assert (b.central_miss_limit, b.decision_frames, b.return_steps, b.return_gamma) == (3, 8, 8, 0.9)


def _with_scope(sense: str, scope):
    data = default_configuration().model_dump()
    data["senses"][sense]["scope"] = scope
    return data


@pytest.mark.parametrize(
    "sense, scope, words",
    [
        ("survival", ("vitals", "threats"), "must contain 'menu'"),
        ("survival", ("vitals", "messages", "menu"), "central instance's channels only"),
        ("combat", ("threats", "relevance", "menu"), "central instance's channels only"),
        ("goal", ("exploration", "menu"), "central instance's channels only"),
        ("resource", ("pickups", "telepathy", "menu"), "unknown channel"),
        ("navigation", ("geometry", "position", "progress", "projections", "values", "novelty", "history", "menu"), "bound of 7"),
        ("navigation", ("geometry", "geometry", "menu"), "appears twice"),
    ],
)
def test_validation_refuses_a_scope_outside_the_bounds(sense, scope, words):
    with pytest.raises(ValidationError, match=words):
        Configuration.model_validate(_with_scope(sense, scope))


def test_the_central_may_hear_messages_but_needs_the_menu_and_the_bound():
    data = default_configuration().model_dump()
    data["central"]["scope"] = ("messages", "relevance", "exploration")
    with pytest.raises(ValidationError, match="must contain 'menu'"):
        Configuration.model_validate(data)
    data["central"]["scope"] = ("messages", "relevance", "exploration", "vitals", "threats", "novelty", "menu")
    assert Configuration.model_validate(data).central.scope[-1] == "menu"


def test_the_senses_must_be_the_five():
    data = default_configuration().model_dump()
    del data["senses"]["goal"]
    with pytest.raises(ValidationError, match="senses must be exactly"):
        Configuration.model_validate(data)


def test_a_change_bumps_the_version_and_the_file_round_trips(tmp_path):
    configuration = default_configuration()
    explore = configuration.with_changes(exploration_level="explore")
    assert explore.version == 2 and explore.exploration_level == "explore" and configuration.version == 1
    macro = ActionVocabulary.default().get("weave_fire")
    with pytest.raises(ValidationError):
        configuration.with_changes(admitted_macros=(ActionVocabulary.default().get("shoot"),))
    assert configuration.with_changes(admitted_macros=(macro,)).admitted_macros == (macro,)
    budget = configuration.with_bounds(call_budget_sec=2.0)
    assert budget.version == 1 and budget.bounds.call_budget_sec == 2.0
    path = tmp_path / "configuration.json"
    explore.save(path)
    assert Configuration.load(path) == explore


def test_each_motor_target_is_chosen_by_one_sense_at_most():
    data = default_configuration().model_dump()
    data["senses"]["survival"]["target"] = "enemy"
    with pytest.raises(ValidationError, match="one sense at most"):
        Configuration.model_validate(data)
    data["senses"]["survival"]["target"] = None
    data["senses"]["combat"]["target"] = None
    assert Configuration.model_validate(data).senses["combat"].target is None


def test_a_file_saved_before_senses_chose_targets_gives_combat_and_resource_theirs():
    data = default_configuration().model_dump()
    for sense in data["senses"].values():
        del sense["target"]
    loaded = Configuration.model_validate(data)
    assert {n: s.target for n, s in loaded.senses.items() if s.target} == {"combat": "enemy", "resource": "pickup"}
