"""The relevance ledger: counts and calibration from a synthetic history, rendering, save and restore."""

import pytest

from system1_doom.relevance import (
    RelevanceCounts,
    RelevanceDecision,
    RelevanceLedger,
    SpokenMessage,
    decision_returns,
    load_ledger,
    render_record,
    render_relevance,
    save_ledger,
    update_ledger,
)


def _d(context, executed, reward, *spoken):
    return RelevanceDecision(
        context=context, executed_action=executed, reward=reward,
        spoken=tuple(SpokenMessage(sense=s, action=a, strength=p) for s, a, p in spoken),
    )


def test_returns_are_the_learners_n_step_discounted_returns():
    assert decision_returns([1.0, 0.0, 2.0], steps=2, gamma=0.5) == pytest.approx([1.0, 1.0, 2.0])
    assert decision_returns([], 8, 0.9) == []
    assert decision_returns([0.0] * 8 + [10.0], 8, 0.9)[0] == pytest.approx(0.0)
    assert decision_returns([0.0] * 7 + [10.0], 8, 0.9)[0] == pytest.approx(10.0 * 0.9**7)


def test_counts_and_calibration_from_a_synthetic_history():
    # steps=1: a decision pays off when its own reward is positive.
    episode = [
        _d("ctx", "shoot", 5.0, ("combat", "shoot", 0.9), ("survival", "retreat", 0.6)),  # combat followed+paid; survival overruled, chosen paid
        _d("ctx", "retreat", -1.0, ("combat", "shoot", 0.7), ("survival", "retreat", 0.8)),  # combat overruled, not paid; survival followed, not paid
        _d("ctx", None, 3.0, ("combat", "shoot", 0.95)),  # a missed central: left out
        _d("other", "shoot", 1.0, ("combat", "shoot", 0.5)),
    ]
    ledger = update_ledger(RelevanceLedger(), episode, steps=1, gamma=0.9)
    combat = ledger.record("combat", "ctx")
    assert (combat.spoke, combat.followed, combat.followed_paid, combat.overruled, combat.overruled_paid) == (2, 1, 1, 1, 0)
    assert combat.strength_paid_sum == pytest.approx(0.9) and combat.strength_paid_n == 1
    assert combat.strength_unpaid_sum == pytest.approx(0.7) and combat.strength_unpaid_n == 1
    survival = ledger.record("survival", "ctx")
    assert (survival.followed, survival.followed_paid, survival.overruled, survival.overruled_paid) == (1, 0, 1, 1)
    assert ledger.record("combat", "other").followed_paid == 1 and ledger.record("goal", "ctx") is None
    assert ledger.episodes == 1 and (ledger.return_steps, ledger.return_gamma) == (1, 0.9)


def test_the_update_is_pure_and_grows_across_episodes():
    empty = RelevanceLedger()
    one = update_ledger(empty, [_d("c", "a", 1.0, ("goal", "a", 0.6))], 8, 0.9)
    two = update_ledger(one, [_d("c", "b", 1.0, ("goal", "a", 0.6))], 8, 0.9)
    assert empty.entries == {} and one.record("goal", "c").spoke == 1
    assert two.record("goal", "c").spoke == 2 and two.record("goal", "c").overruled == 1 and two.episodes == 2


def test_the_reward_after_a_decision_counts_toward_its_return():
    # The first decision earns nothing itself, but the next one (a missed central's idle) does.
    ledger = update_ledger(RelevanceLedger(), [_d("c", "a", 0.0, ("combat", "a", 0.9)), _d("c", None, 4.0)], 8, 0.9)
    assert ledger.record("combat", "c").followed_paid == 1


def test_rendering_in_the_words_of_the_design():
    counts = RelevanceCounts(
        spoke=14, followed=9, followed_paid=7, overruled=5, overruled_paid=2,
        strength_paid_sum=0.81 * 9, strength_paid_n=9, strength_unpaid_sum=0.64 * 5, strength_unpaid_n=5,
    )
    assert render_record("survival", counts) == (
        "survival here: spoke 14, followed 9, paid off 7 of 9; overruled 5, the chosen action paid off 2 of 5; "
        "mean strength 0.81 when it paid off, 0.64 when not."
    )
    assert render_record("goal", None) == "goal here: no record here."
    thin = RelevanceCounts(spoke=1, followed=1, followed_paid=1, strength_paid_sum=0.9, strength_paid_n=1)
    assert render_record("combat", thin).endswith("mean strength 0.90 over 1 tick when it paid off, n/a when not.")
    lines = render_relevance({"combat": thin}, ("survival", "combat"))
    assert lines[0] == "survival here: no record here." and lines[1].startswith("combat here: spoke 1")


def test_save_and_restore(tmp_path):
    ledger = update_ledger(RelevanceLedger(), [_d("c", "a", 1.0, ("goal", "a", 0.6))], 8, 0.9)
    path = tmp_path / "runs" / "basic" / "relevance.json"
    assert load_ledger(path) == RelevanceLedger()
    save_ledger(ledger, path)
    assert load_ledger(path) == ledger
    assert ledger.snapshot("c", ("survival", "goal")) == {"goal": ledger.record("goal", "c")}
