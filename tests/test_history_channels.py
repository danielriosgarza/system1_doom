"""History channels: golden text on a synthetic history, the three windows, paid off per episode, determinism."""

import pytest

from system1_doom.archive import DEFAULT_STRATEGIES
from system1_doom.configuration import CHANNELS, CENTRAL_ONLY_CHANNELS
from system1_doom.evidence import StrategyLine
from system1_doom.history_channels import (
    HISTORY_CHANNELS,
    ChangeLogEntry,
    System2Status,
    HistoryTestSummary,
    TrialStatus,
    VerdictSummary,
    history_inputs,
    record_returns,
    render_history_channel,
    render_history_scope,
    window_indices,
)
from system1_doom.reflectors import REFLECTORS, Proposal, apply_change, change_option
from system1_doom.relevance import decision_returns
from tests.system2_fixtures import CONFIG, episode, make_record

SMALL = CONFIG.with_bounds(window_recent=4, window_long=10, window_episodes=2)
ARCHIVE = tuple(
    StrategyLine(
        strategy_id=e.strategy_id, action_sequence=tuple(e.action_sequence), observed_reward=e.observed_reward,
        success_rate=e.success_rate, usage_count=e.usage_count,
    )
    for e in DEFAULT_STRATEGIES
)


def labelled_history():
    """Three episodes with known rewards, messages, misses and outcomes (ten ticks)."""
    ring = [make_record("e1", t, r, spoken={"survival": ("strafe_left", 0.8)} if t % 2 else {}) for t, r in enumerate([1.0, -1.0, 2.0, -3.0])]
    ring += [
        make_record("e2", 0, -2.0, spoken={"survival": ("shoot", 0.9), "combat": ("shoot", 0.7)}, kills=1, damage=4, displacement=10, new_cells=1),
        make_record("e2", 1, 3.0, spoken={"survival": ("strafe_left", 0.6)}, executed="strafe_left", stalled=True, novelty={"shoot": 3, "strafe_left": 0}),
        make_record("e2", 2, -1.0, executed=None),
        make_record("e2", 3, 0.5, spoken={"combat": ("shoot", 0.95)}, tie=True, damage=6, died=True),
    ]
    ring += [
        make_record("e3", 0, -4.0, spoken={"survival": ("approach_pickup", 0.7)}, executed="approach_pickup", sense_missed=("goal",), displacement=20),
        make_record("e3", 1, 2.0, spoken={"survival": ("shoot", 0.55), "resource": ("approach_pickup", 0.8)}, pick_kind="drawn"),
    ]
    return ring


STATUS = System2Status(
    decisions=10,
    cooling_left={"survival": 12},
    change_log=(ChangeLogEntry(version=2, change="widen:survival:pickups", by="system 2", cycle_id="c0002", decision=4, status="trial"),),
    trial=TrialStatus(cycle_id="c0002", change="widen:survival:pickups", version=2, observed=6, of=60),
    tests=(
        HistoryTestSummary(cycle_id="c0001", change="widen:survival:pickups", status="waiting", note="fewer than 24 stored ticks"),
        HistoryTestSummary(cycle_id="c0002", change="widen:survival:pickups", status="passed", old_composite=0.3333, new_composite=0.6667, noise_agreement=1.0),
    ),
    verdicts=(VerdictSummary(cycle_id="c0000", change="level:explore", version=1, verdict="revert", by="the trial judge"),),
)


@pytest.fixture(scope="module")
def inputs():
    return history_inputs(labelled_history(), SMALL, archive=ARCHIVE, status=STATUS)


def test_the_three_windows_as_the_history_holds_them(inputs):
    recent, long, episodes = inputs.windows
    assert (recent.label, recent.decisions, recent.episode_ids, recent.first, recent.last) == ("last 4 decisions", 4, ("e2", "e3"), "e2:2", "e3:1")
    assert (long.decisions, long.episode_ids, long.first) == (10, ("e1", "e2", "e3"), "e1:0")
    assert (episodes.label, episodes.decisions, episodes.episode_ids, episodes.first) == ("last 2 episodes", 6, ("e2", "e3"), "e2:0")
    # The design's windows: 20 and 100 decisions and 3 episodes; fewer when the history holds fewer.
    windows = [w for w, _ in window_indices(labelled_history(), CONFIG.bounds)]
    assert [(w.label, w.decisions) for w in windows] == [("last 20 decisions", 10), ("last 100 decisions", 10), ("last 3 episodes", 10)]
    assert [w.held() for w in windows] == ["last 20 decisions (only 10 held)", "last 100 decisions (only 10 held)", "last 3 episodes (10 decisions)"]


def test_paid_off_is_the_n_step_return_computed_per_episode(inputs):
    records = labelled_history()
    expected = decision_returns([1.0, -1.0, 2.0, -3.0], 8, 0.9) + decision_returns([-2.0, 3.0, -1.0, 0.5], 8, 0.9) + decision_returns([-4.0, 2.0], 8, 0.9)
    assert record_returns(records, 8, 0.9) == pytest.approx(expected)
    assert inputs.returns == pytest.approx(expected)
    # The first decision of e2 pays off only by its own episode's future, never e1's.
    assert inputs.paid(4) and not inputs.paid(3)


def test_h_outcomes_golden(inputs):
    assert render_history_channel(inputs, "h_outcomes") == (
        "[h_outcomes]\n"
        "what play produced, per window:\n"
        "- last 4 decisions: decisions 4, reward -2.5, kills 0, deaths 1, damage taken 6, stalls 0, missed ticks 1\n"
        "- last 10 decisions: decisions 10, reward -2.5, kills 1, deaths 1, damage taken 10, stalls 1, missed ticks 1\n"
        "- last 2 episodes (6 decisions): decisions 6, reward -1.5, kills 1, deaths 1, damage taken 10, stalls 1, missed ticks 1"
    )


def test_h_sense_golden(inputs):
    assert render_history_channel(inputs, "h_sense:survival") == (
        "[h_sense:survival]\n"
        "the survival sense (concern: staying alive in the next few seconds), on decisions the central did not miss; "
        "paid off: the decision's 8-step return (discount 0.9) was positive:\n"
        "- last 4 decisions: spoke 2, followed 2, paid off 1 of 2; overruled 0, the chosen action paid off 0 of 0; "
        "mean strength 0.55 over 1 tick when it paid off, 0.70 over 1 tick when not; missed 0 of 4 calls\n"
        "- last 10 decisions: spoke 6, followed 4, paid off 3 of 4; overruled 2, the chosen action paid off 0 of 2; "
        "mean strength 0.68 over 3 ticks when it paid off, 0.77 over 3 ticks when not; missed 0 of 10 calls\n"
        "- last 2 episodes (6 decisions): spoke 4, followed 4, paid off 3 of 4; overruled 0, the chosen action paid off 0 of 0; "
        "mean strength 0.68 over 3 ticks when it paid off, 0.70 over 1 tick when not; missed 0 of 6 calls\n"
        "scope now (5 of 7 channels): vitals, threats, incoming, projections, menu\n"
        "could add: outgoing, pickups, geometry, position, progress, history, frame, values, novelty, archive\n"
        "could drop: vitals, threats, incoming, projections"
    )
    goal = render_history_channel(inputs, "h_sense:goal")
    assert "- last 4 decisions: spoke 0, followed 0, paid off 0 of 0;" in goal and goal.count("missed 1 of") == 3


def test_h_central_golden(inputs):
    assert render_history_channel(inputs, "h_central") == (
        "[h_central]\n"
        "the central action chooser (concern: choosing the one action the agent executes now); "
        "paid off: the decision's 8-step return (discount 0.9) was positive:\n"
        "- last 4 decisions: 4 decisions, 1 missed; followed the strongest message on 2 of 3 decisions with a message; "
        "picks that paid off 2 of 3; ties 1\n"
        "- last 10 decisions: 10 decisions, 1 missed; followed the strongest message on 4 of 7 decisions with a message; "
        "picks that paid off 4 of 9; ties 1\n"
        "- last 2 episodes (6 decisions): 6 decisions, 1 missed; followed the strongest message on 4 of 5 decisions with a message; "
        "picks that paid off 4 of 5; ties 1\n"
        "scope now (5 of 7 channels): messages, relevance, exploration, vitals, menu; novelty is added while the level is explore and there is room\n"
        "could add: threats, incoming, outgoing, pickups, geometry, position, progress, history, frame, projections, values, novelty, archive\n"
        "could drop: messages, relevance, exploration, vitals"
    )


def test_h_actions_golden_and_admitted_macros(inputs):
    assert render_history_channel(inputs, "h_actions") == (
        "[h_actions]\n"
        "each action executed, per window: times executed and mean 8-step return (discount 0.9):\n"
        "- last 4 decisions: shoot 2 (mean +1.25), approach_pickup 1 (mean -2.20)\n"
        "- last 10 decisions: shoot 7 (mean -0.43), strafe_left 1 (mean +2.50), approach_pickup 1 (mean -2.20)\n"
        "- last 2 episodes (6 decisions): shoot 3 (mean +0.92), strafe_left 1 (mean +2.50), approach_pickup 1 (mean -2.20)\n"
        "on the menu but never executed in these windows: none\n"
        "admitted macros: none"
    )
    from system1_doom.actions import ActionVocabulary

    macro = ActionVocabulary.default().get("weave_fire").model_copy(update={"id": "zigzag_fire"})
    with_macro = history_inputs(labelled_history()[:2], SMALL.with_changes(admitted_macros=(macro,)))
    text = render_history_channel(with_macro, "h_actions")
    assert "on the menu but never executed in these windows: strafe_left, approach_pickup" in text
    assert "admitted macros, over these windows:\n- zigzag_fire: " in text and "legal on 0 decisions, never executed" in text


def test_h_strategy_h_exploration_golden(inputs):
    strategy = render_history_channel(inputs, "h_strategy")
    assert strategy.startswith("[h_strategy]\nstrategies (active: strat_tactical_combat):\n- strat_tactical_combat (active): peek_and_fire")
    assert strategy.endswith(
        "decisions under each strategy, per window (count, mean 8-step return):\n"
        "- last 4 decisions: strat_tactical_combat 4 (mean -0.06)\n"
        "- last 10 decisions: strat_tactical_combat 10 (mean -0.33)\n"
        "- last 2 episodes (6 decisions): strat_tactical_combat 6 (mean +0.42)"
    )
    assert render_history_channel(inputs, "h_exploration") == (
        "[h_exploration]\n"
        "level now: exploit (the action the chooser gives the highest probability is executed)\n"
        "per window: decisions that took a less-tried action (taken fewer times in that situation than the menu's average so far), "
        "picks drawn under explore, and the progress trend (reward, displacement and new cells per decision):\n"
        "- last 4 decisions: less-tried 1 of 4 (0.25); drawn 1; reward per decision -0.62; displacement per decision 5.0; new cells per decision 0.00\n"
        "- last 10 decisions: less-tried 2 of 10 (0.20); drawn 1; reward per decision -0.25; displacement per decision 3.0; new cells per decision 0.10\n"
        "- last 2 episodes (6 decisions): less-tried 2 of 6 (0.33); drawn 1; reward per decision -0.25; displacement per decision 5.0; new cells per decision 0.17"
    )


def test_h_config_h_tests_and_messages_golden(inputs):
    assert render_history_channel(inputs, "h_config") == (
        "[h_config]\n"
        "configuration version 1\n"
        "changes (latest last, the last 1 of 1):\n"
        "- version 2: widen:survival:pickups by system 2, cycle c0002; trial\n"
        "trial in flight: widen:survival:pickups (version 2), observed 6 of 60 decisions\n"
        "change pending: none\n"
        "cooling: survival 12 decisions left; combat ready; navigation ready; resource ready; goal ready; central ready; "
        "System 2 as a whole (menu, strategy, level) ready"
    )
    assert render_history_channel(inputs, "h_tests") == (
        "[h_tests]\n"
        "recent history tests (latest last):\n"
        "- cycle c0001, widen:survival:pickups: waiting, fewer than 24 stored ticks\n"
        "- cycle c0002, widen:survival:pickups: composite 0.33 old, 0.67 new; passed; noise agreement 1.00\n"
        "recent trial verdicts (latest last):\n"
        "- level:explore (version 1): revert, by the trial judge"
    )
    option = change_option("widen:survival:pickups", SMALL)
    proposal = Proposal(reflector="survival_auditor", title="survival auditor", change=option.id, description=option.description, reason="poor_payoff", strength=0.9)
    with_messages = inputs.model_copy(update={"proposals": (proposal,)})
    assert render_history_channel(with_messages, "messages") == (
        "[messages]\n"
        "the reflectors' proposals this cycle:\n"
        "- survival auditor proposes widen:survival:pickups (show the survival sense the pickups channel as well), "
        "strength 0.90, reason poor payoff."
    )


def test_a_scope_renders_only_its_channels_in_order_and_deterministically(inputs):
    for spec in REFLECTORS:
        text = render_history_scope(inputs, spec.scope)
        headers = [line for line in text.splitlines() if line.startswith("[")]
        assert headers == [f"[{c}]" for c in HISTORY_CHANNELS if c in spec.scope], spec.name
        assert text == render_history_scope(history_inputs(labelled_history(), SMALL, archive=ARCHIVE, status=STATUS), spec.scope)
    with pytest.raises(ValueError):
        render_history_scope(inputs, ("h_telepathy",))


def test_what_a_sense_could_add_and_drop_follows_the_bounds():
    full = apply_change(CONFIG, change_option("widen:combat:pickups", CONFIG))
    text = render_history_channel(history_inputs(labelled_history(), full), "h_sense:combat")
    assert "scope now (7 of 7 channels)" in text and "could add: nothing while the scope holds 7 channels, the bound" in text
    survival = render_history_channel(history_inputs([], CONFIG), "h_sense:survival")
    added = survival.split("could add: ")[1].split("\n")[0].split(", ")
    assert set(added) == set(CHANNELS) - set(CONFIG.senses["survival"].scope) - set(CENTRAL_ONLY_CHANNELS)
    assert "menu" not in survival.split("could drop: ")[1]
    assert "- no decision is stored yet" in survival


def test_an_empty_history_says_so():
    empty = history_inputs([], CONFIG)
    for channel in ("h_outcomes", "h_actions"):
        assert render_history_channel(empty, channel).endswith("no decision is stored yet")
    assert render_history_channel(empty, "h_tests") == "[h_tests]\nno history test yet\nno trial judged yet"
    assert render_history_channel(empty, "h_config").splitlines()[2:4] == ["no change made yet", "trial in flight: none"]


def test_windows_cover_the_last_episodes_across_a_long_ring():
    ring = episode("a", [1.0] * 30) + episode("b", [1.0] * 30) + episode("c", [-1.0] * 30) + episode("d", [1.0] * 30)
    inp = history_inputs(ring, CONFIG)
    recent, long, episodes = inp.windows
    assert recent.episode_ids == ("d",) and long.episode_ids == ("a", "b", "c", "d") and long.first == "a:20"
    assert episodes.episode_ids == ("b", "c", "d") and episodes.decisions == 90
    assert len(inp.records) == 100, "the inputs hold only what some window covers"
