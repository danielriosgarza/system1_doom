"""The reflectors: nine instances over the history, their finite change menus, and the bounds that filter them."""

import pytest

from system1_doom.actions import ActionVocabulary
from system1_doom.configuration import CENTRAL_ONLY_CHANNELS, CHANNELS, SENSE_NAMES, default_configuration
from system1_doom.d1_client import D1UltraClient
from system1_doom.instance import run_system2_instance
from system1_doom.reflectors import (
    REFLECTOR_NAMES,
    REFLECTORS,
    SYSTEM2_KEY,
    BoundsState,
    apply_change,
    blocked_by,
    change_menu,
    change_option,
    config_diff,
    filter_changes,
    proposal_of,
    reflector_questions,
)
from tests.fake_d1 import FakeD1, instance_name, reflector_answer

CONFIG = default_configuration()
ARCHIVE = ("strat_tactical_combat", "strat_evasive_survival", "strat_corridor_advance")
SPECS = {spec.name: spec for spec in REFLECTORS}
MACRO = ActionVocabulary.default().get("weave_fire").model_copy(update={"id": "zigzag_fire"})


def ids(options):
    return [o.id for o in options]


def test_nine_reflectors_each_over_its_history_channel_and_the_outcomes():
    assert REFLECTOR_NAMES == (
        "survival_auditor", "combat_auditor", "navigation_auditor", "resource_auditor", "goal_auditor",
        "central_auditor", "menu_reflector", "strategy_reflector", "exploration_reflector",
    )
    assert [s.scope for s in REFLECTORS] == [(f"h_sense:{n}", "h_outcomes") for n in SENSE_NAMES] + [
        ("h_central", "h_outcomes"), ("h_actions", "h_outcomes"), ("h_strategy", "h_outcomes"), ("h_exploration", "h_outcomes"),
    ]
    for spec in REFLECTORS:
        assert spec.reasons and len(set(spec.reasons)) == len(spec.reasons)


def test_the_questions_name_the_reflector_and_never_say_how_to_weigh():
    spec = SPECS["survival_auditor"]
    options = change_menu(spec, CONFIG)
    questions = reflector_questions(spec, options)
    assert list(questions) == ["speak", "change", "reason"]
    assert questions["speak"].type == "noul" and questions["change"].type == "choice" and questions["reason"].type == "choice"
    assert questions["change"].criteria == {o.id: o.description for o in options}
    assert list(questions["reason"].criteria) == list(spec.reasons)
    for q in questions.values():
        assert q.instructions.startswith(
            "You are the survival auditor of a Doom agent's slow system; your concern is whether the survival sense is "
            "shown the evidence it needs, and only that. You see only the evidence given."
        )
        for word in ("weigh", "score", "prefer", "threshold", "rank"):
            assert word not in q.instructions.lower()
    # The fake tells a reflector apart from the payload alone.
    payload = D1UltraClient(api_key="k").payload("state", questions)
    assert instance_name(payload) == "survival_auditor"


def test_a_sense_auditor_offers_one_channel_at_a_time_and_never_menu():
    options = ids(change_menu(SPECS["survival_auditor"], CONFIG))
    scope = CONFIG.senses["survival"].scope
    widen = [f"widen:survival:{c}" for c in CHANNELS if c not in scope and c not in CENTRAL_ONLY_CHANNELS]
    narrow = [f"narrow:survival:{c}" for c in scope if c != "menu"]
    assert options == widen + narrow + ["keep"]
    assert "narrow:survival:menu" not in options and not any(o.endswith((":messages", ":relevance", ":exploration")) for o in options)
    central = ids(change_menu(SPECS["central_auditor"], CONFIG))
    assert "narrow:central:menu" not in central and "widen:central:novelty" in central and "narrow:central:messages" in central


def test_the_menu_strategy_and_exploration_menus():
    with_macro = CONFIG.with_changes(admitted_macros=(MACRO,))
    assert ids(change_menu(SPECS["menu_reflector"], with_macro)) == [f"macro:{s}" for s in SENSE_NAMES] + ["retire:zigzag_fire", "keep"]
    assert ids(change_menu(SPECS["strategy_reflector"], CONFIG, ARCHIVE)) == ["strategy:strat_evasive_survival", "strategy:strat_corridor_advance", "keep"]
    assert ids(change_menu(SPECS["exploration_reflector"], CONFIG)) == ["level:exploit", "level:explore"]
    assert change_option("macro:navigation", CONFIG).description.endswith("(moving through the level)")


def test_the_bounds_filter_cooling_trial_scope_size_builtins_and_menu():
    free = BoundsState(decisions=100, archive_ids=ARCHIVE)
    widen = change_option("widen:survival:pickups", CONFIG)
    assert blocked_by(widen, CONFIG, free) is None
    # Cooling: the changed instance rests 60 decisions; System 2 as a whole after a menu, strategy or level change.
    cooling = free.model_copy(update={"cooling": {"survival": 130}})
    assert blocked_by(widen, CONFIG, cooling) == "cooling: survival rests 30 more decisions"
    assert blocked_by(change_option("widen:combat:pickups", CONFIG), CONFIG, cooling) is None
    whole = free.model_copy(update={"cooling": {SYSTEM2_KEY: 110}})
    assert blocked_by(widen, CONFIG, whole).startswith("cooling: System 2 as a whole")
    assert blocked_by(change_option("level:explore", CONFIG), CONFIG, whole).startswith("cooling")
    # One trial in flight.
    assert blocked_by(widen, CONFIG, free.model_copy(update={"trials": 1})) == "one trial in flight: 1 already"
    # The scope-size bound: combat has 6 channels, so one more fills it and the next is refused.
    full = apply_change(CONFIG, change_option("widen:combat:pickups", CONFIG))
    assert blocked_by(change_option("widen:combat:geometry", full), full, free).startswith("scope size")
    assert blocked_by(change_option("narrow:combat:pickups", full), full, free) is None
    # Built-in actions are never retired; menu is never narrowed; a sense never sees the central's channels.
    assert "built-in" in blocked_by(change_option("retire:weave_fire", CONFIG), CONFIG, free)
    assert blocked_by(change_option("narrow:survival:menu", CONFIG), CONFIG, free) == "menu is never narrowed"
    assert "cannot be added" in blocked_by(change_option("widen:survival:messages", CONFIG), CONFIG, free)
    assert blocked_by(change_option("macro:combat", CONFIG), CONFIG, free.model_copy(update={"slow_path_available": False})) is not None
    # No change is never blocked: keep, and the level already set.
    for no_change in ("keep", "level:exploit"):
        assert blocked_by(change_option(no_change, CONFIG), CONFIG, free.model_copy(update={"trials": 1})) is None
    allowed, blocked = filter_changes(change_menu(SPECS["combat_auditor"], full), full, free)
    assert all(o.kind != "widen" for o in allowed) and all(r.startswith("scope size") for k, r in blocked.items())


def test_a_change_applied_bumps_the_version_and_the_diff_says_what_changed():
    widened = apply_change(CONFIG, change_option("widen:survival:pickups", CONFIG))
    assert widened.version == 2 and widened.senses["survival"].scope == ("vitals", "threats", "incoming", "projections", "pickups", "menu")
    assert config_diff(CONFIG, widened).changes == ("survival scope: + pickups",)
    narrowed = apply_change(widened, change_option("narrow:central:vitals", widened))
    assert narrowed.version == 3 and "vitals" not in narrowed.central.scope
    assert config_diff(widened, narrowed).model_dump() == {"old_version": 2, "new_version": 3, "changes": ("central scope: - vitals",)}
    level = apply_change(CONFIG, change_option("level:explore", CONFIG))
    assert config_diff(CONFIG, level).changes == ("exploration level: exploit -> explore",)
    with_macro = CONFIG.with_changes(admitted_macros=(MACRO,))
    retired = apply_change(with_macro, change_option("retire:zigzag_fire", with_macro))
    assert retired.admitted_macros == () and config_diff(with_macro, retired).changes == ("admitted macros: - zigzag_fire",)
    with pytest.raises(ValueError):
        apply_change(CONFIG, change_option("macro:combat", CONFIG))


def test_a_reflector_is_one_call_and_sends_a_proposal_only_when_it_speaks_for_a_change():
    spec = SPECS["survival_auditor"]
    options = change_menu(spec, CONFIG)

    def policy(name, payload):
        return reflector_answer(payload, 0.9, "widen:survival:pickups", "poor_payoff")

    fake = FakeD1(system2_policy=policy)
    client = D1UltraClient(api_key="k", transport=fake)
    result = run_system2_instance(client, spec.instance_spec(), "[h_outcomes]\nx", reflector_questions(spec, options))
    assert result.kind == "reflector" and result.spoke and result.strength == 0.9 and result.change == "widen:survival:pickups"
    assert result.reason == "poor_payoff" and set(result.answers) == {"speak", "change", "reason"}
    assert result.scope == ("h_sense:survival", "h_outcomes") and result.evidence == "[h_outcomes]\nx"
    proposal = proposal_of(spec, result, options, CONFIG)
    assert proposal is not None and (proposal.change, proposal.reason, proposal.strength) == ("widen:survival:pickups", "poor_payoff", 0.9)
    assert proposal_of(spec, result.model_copy(update={"spoke": False}), options, CONFIG) is None
    assert proposal_of(spec, result.model_copy(update={"change": "keep"}), options, CONFIG) is None
    assert proposal_of(spec, result.model_copy(update={"missed": True}), options, CONFIG) is None
    exploration = SPECS["exploration_reflector"]
    level = run_system2_instance(client, exploration.instance_spec(), "x", reflector_questions(exploration, change_menu(exploration, CONFIG)))
    assert proposal_of(exploration, level.model_copy(update={"spoke": True, "change": "level:exploit"}), change_menu(exploration, CONFIG), CONFIG) is None


def test_a_change_outside_the_criteria_is_a_miss_and_nothing_stands_in():
    spec = SPECS["menu_reflector"]
    options = change_menu(spec, CONFIG)
    fake = FakeD1().fail("menu_reflector", [0], "off_menu").fail("menu_reflector", [1], "malformed")
    client = D1UltraClient(api_key="k", transport=fake)
    off = run_system2_instance(client, spec.instance_spec(), "x", reflector_questions(spec, options))
    bad = run_system2_instance(client, spec.instance_spec(), "x", reflector_questions(spec, options))
    assert off.missed and off.miss_reason == "off_menu" and off.change is None and off.raw_answer["choice"] == "teleport_hack"
    assert bad.missed and bad.miss_reason == "malformed"
    assert client.counters()["menu_reflector"].misses == {"off_menu": 1, "malformed": 1}
