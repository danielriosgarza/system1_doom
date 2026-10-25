"""The history test: the metrics, the margin rule, the stratified sample, waiting under 24 ticks, the noise
estimate, the call bound, misses and frames, on a labelled synthetic history with the fake d1-ultra."""

import random
from concurrent.futures import ThreadPoolExecutor

import pytest

from system1_doom.d1_client import D1UltraClient
from system1_doom.history_test import (
    Answer,
    Metrics,
    agrees,
    metrics,
    run_history_test,
    sample_ticks,
    strata_of,
    verdict,
)
from system1_doom.reflectors import apply_change, change_option
from tests.fake_d1 import FakeD1, default_policy, survival_until_pickups
from tests.system2_fixtures import CONFIG, make_record

WIDEN = change_option("widen:survival:pickups", CONFIG)
WIDER = apply_change(CONFIG, WIDEN)


def silent(action="shoot"):
    return Answer(spoke=False, action=action)


def spoke(action):
    return Answer(spoke=True, action=action)


def test_the_sense_metrics_as_defined_on_labelled_ticks():
    executed = "shoot"
    rows = [
        # bad ticks: an alarm is speaking for another action than the one executed
        ("bad", spoke("strafe_left"), executed),  # alarm
        ("bad", spoke("shoot"), executed),  # spoke for the executed action: no alarm
        ("bad", silent(), executed),  # silent: no alarm
        ("bad", Answer(spoke=False, missed=True), executed),  # a miss is silence
        # good ticks: agreement is silence or the executed action
        ("good", silent(), executed),
        ("good", spoke("shoot"), executed),
        ("good", spoke("approach_pickup"), executed),
        # the rest: quiet is silence
        ("rest", silent(), executed),
        ("rest", spoke("shoot"), executed),
    ]
    m = metrics("sense", rows)
    assert m.quality == {"alarm_recall": 0.25, "good_agreement": pytest.approx(2 / 3, abs=1e-6), "quiet": 0.5}
    assert m.composite == pytest.approx((0.25 + 2 / 3 + 0.5) / 3, abs=1e-6) and m.missed == 1


def test_the_central_metrics_and_an_empty_stratum():
    rows = [
        ("good", Answer(spoke=True, action="shoot"), "shoot"),
        ("good", Answer(spoke=True, action="strafe_left"), "shoot"),
        ("bad", Answer(spoke=True, action="strafe_left"), "shoot"),
        ("bad", Answer(spoke=False, missed=True), "shoot"),  # a missed central disagrees with nothing
        ("rest", Answer(spoke=True, action="strafe_left"), "shoot"),  # the central has no metric on the rest
    ]
    m = metrics("central", rows)
    assert m.quality == {"disagreement_on_bad": 0.5, "agreement_on_good": 0.5} and m.composite == 0.5
    only_good = metrics("sense", [("good", silent(), "shoot")])
    assert only_good.quality == {"alarm_recall": None, "good_agreement": 1.0, "quiet": None} and only_good.composite == 1.0


def _m(alarm, agreement, quiet):
    quality = {"alarm_recall": alarm, "good_agreement": agreement, "quiet": quiet}
    return Metrics(quality=quality, composite=round((alarm + agreement + quiet) / 3, 6))


def test_the_margin_rule_on_both_sides():
    old = _m(0.30, 0.60, 0.60)  # composite 0.50
    assert verdict(old, _m(0.45, 0.60, 0.60), 0.05, 0.10) == (True, 0.05, 0.0)  # exactly the margin passes
    passed, gain, _ = verdict(old, _m(0.44, 0.60, 0.60), 0.05, 0.10)
    assert not passed and gain == pytest.approx(0.046667, abs=1e-6)  # under the margin fails
    assert verdict(old, _m(0.90, 0.50, 0.60), 0.05, 0.10)[0]  # a metric 0.10 worse is allowed
    passed, gain, worst = verdict(old, _m(0.90, 0.49, 0.60), 0.05, 0.10)
    assert not passed and gain > 0.05 and worst == pytest.approx(0.11)  # 0.11 worse fails however much the composite gains


def test_strata_are_the_bottom_and_top_quarters_by_rank():
    returns = [5.0, -1.0, 0.0, 2.0, -3.0, 1.0, 4.0, -2.0]
    assert strata_of(returns, 0.25) == ["good", "rest", "rest", "rest", "bad", "rest", "good", "bad"]


def test_the_stratified_sample_and_the_context_cap_with_a_seed():
    n = 60
    returns = [float(i % 20) for i in range(n)]
    contexts = [f"ctx_{i % 7}" for i in range(n)]
    labels = strata_of(returns, 0.25)
    first = sample_ticks(contexts, labels, 24, 4, 4, random.Random(5))
    again = sample_ticks(contexts, labels, 24, 4, 4, random.Random(5))
    other = sample_ticks(contexts, labels, 24, 4, 4, random.Random(6))
    assert first == again and first.indices != other.indices
    assert len(first.indices) == len(set(first.indices)) == 24
    assert [first.strata.count(s) for s in ("bad", "good", "rest")] == [8, 8, 8]
    assert all(labels[i] == s for i, s in zip(first.indices, first.strata))
    picked_contexts = [contexts[i] for i in first.indices]
    assert max(picked_contexts.count(c) for c in set(picked_contexts)) <= 4 and first.notes == ()
    assert len(first.noise) == 4 and set(first.noise) <= set(first.indices)


def test_the_cap_is_relaxed_only_when_a_stratum_cannot_fill_and_the_shortfall_goes_to_the_rest():
    returns = [float(i) for i in range(30)]
    two_contexts = ["a" if i % 2 else "b" for i in range(30)]
    sample = sample_ticks(two_contexts, strata_of(returns, 0.25), 24, 4, 4, random.Random(1))
    # 30 ticks: the quarters hold 7 each, so 1 more comes from the rest of each; two contexts cannot respect a cap of 4.
    assert sample.targets == {"bad": 7, "good": 7, "rest": 10} and sample.pool_sizes == {"bad": 7, "good": 7, "rest": 16}
    assert any("holds 7 ticks; 1 more are drawn from the rest" in note for note in sample.notes)
    relaxed = [note for note in sample.notes if "context cap of 4 was relaxed" in note]
    assert relaxed and len(sample.indices) == 24
    # Relaxed only where the cap would leave a stratum short: 8 per context fill at most 2 x 4 of the 24.
    counts = [two_contexts[i] for i in sample.indices]
    assert counts.count("a") + counts.count("b") == 24 and len(relaxed) <= 2
    capped = sample_ticks(two_contexts, strata_of(returns, 0.25), 8, 0, 4, random.Random(1))
    assert not any("relaxed" in note for note in capped.notes)


def _history(n_per_episode=12, episodes=3, survival_speaks=True, **kwargs):
    records = []
    for e in range(episodes):
        for t in range(n_per_episode):
            reward = float((t * 7 + e * 3) % 11) - 5.0
            spoken = {"survival": ("shoot", 0.9)} if survival_speaks else {}
            records.append(make_record(f"e{e}", t, reward, spoken=spoken, context=f"ctx_{t % 5}", **kwargs))
    return records


def _client(fake):
    return D1UltraClient(api_key="k", transport=fake, max_workers=2)


def test_a_scope_change_that_quiets_a_sense_on_its_followed_but_unpaid_messages_passes():
    fake = FakeD1(survival_until_pickups)
    client = _client(fake)
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = run_history_test(client, _history(), "survival", WIDEN.id, CONFIG, WIDER, seed=3, executor=pool)
    assert result.status == "passed" and result.kind == "sense" and result.passed
    assert result.old_scope == CONFIG.senses["survival"].scope and result.new_scope == WIDER.senses["survival"].scope
    assert result.old.quality == {"alarm_recall": 0.0, "good_agreement": 1.0, "quiet": 0.0}
    assert result.new.quality == {"alarm_recall": 0.0, "good_agreement": 1.0, "quiet": 1.0}
    assert result.composite_gain == pytest.approx(1 / 3, abs=1e-6) and result.worst_drop == 0.0
    # 24 re-runs under the new scope and 4 noise re-asks under the old: 28 calls, all on the fake.
    assert result.calls == 28 == fake.count("survival") and len(result.ticks) == 24 and result.noise_ticks == 4
    news = fake.payloads("survival")
    assert sum(1 for p in news if "[pickups]" in p["state"]) == 24 and sum(1 for p in news if "[pickups]" not in p["state"]) == 4
    # The old answers come from the stored ticks: what the instance said under its scope at the time.
    assert all(t.old.spoke and t.old.action == "shoot" for t in result.ticks)
    assert result.noise_agreement == 1.0, "the fake re-asked under the old scope says what the tick stored"
    assert result.usage.input_tokens > 0 and result.new.mean_evidence_chars > result.old.mean_evidence_chars
    assert {t.key for t in result.ticks} <= {r.key for r in _history()} and result.limits.startswith("Hindsight labels")


def test_a_change_that_does_not_clear_the_margin_fails():
    narrow = change_option("narrow:survival:threats", CONFIG)
    result = run_history_test(_client(FakeD1(survival_until_pickups)), _history(), "survival", narrow.id, CONFIG, apply_change(CONFIG, narrow), seed=3)
    assert result.status == "failed" and result.composite_gain == 0.0 and result.reason.startswith("failed")


def test_no_test_under_24_ticks_and_no_call():
    fake = FakeD1(survival_until_pickups)
    result = run_history_test(_client(fake), _history(n_per_episode=7, episodes=3)[:-1] + [], "survival", WIDEN.id, CONFIG, WIDER, seed=1)
    assert result.status == "waiting" and result.candidates == 20 and "fewer than 24" in result.reason
    assert result.calls == 0 and fake.count("survival") == 0
    # Only the last 3 episodes count, and only ticks answered under the current scope with an executed action.
    old = _history(n_per_episode=30, episodes=1)
    recent = _history(n_per_episode=7, episodes=3)
    recent = [r.model_copy(update={"episode_id": f"r{r.episode_id}"}) for r in recent]
    result = run_history_test(_client(fake), old + recent, "survival", WIDEN.id, CONFIG, WIDER, seed=1)
    assert result.status == "waiting" and result.window_ticks == 21
    missed = [make_record("m", t, 1.0, executed=None) for t in range(30)]
    assert run_history_test(_client(fake), missed, "survival", WIDEN.id, CONFIG, WIDER, seed=1).candidates == 0
    other_scope = [make_record("w", t, 1.0, config=WIDER) for t in range(30)]
    assert run_history_test(_client(fake), other_scope, "survival", WIDEN.id, CONFIG, WIDER, seed=1).candidates == 0


def test_the_noise_estimate_compares_the_re_asked_old_scope_with_the_stored_answers():
    # The stored ticks say survival spoke for strafe_left; the fake re-asked under the old scope speaks for shoot.
    records = _history(survival_speaks=False)
    records = [r.model_copy(update={"instances": {**r.instances, "survival": r.instances["survival"].model_copy(update={"spoke": True, "action": "strafe_left"})}}) for r in records]
    fake = FakeD1(survival_until_pickups)
    result = run_history_test(_client(fake), records, "survival", WIDEN.id, CONFIG, WIDER, seed=2)
    assert result.noise_ticks == 4 and result.noise_agreement == 0.0
    noisy = [t for t in result.ticks if t.noise is not None]
    assert len(noisy) == 4 and all(not agrees("sense", t.noise, t.old) for t in noisy)
    assert agrees("sense", silent("shoot"), silent("strafe_left")) and agrees("central", spoke("shoot"), spoke("shoot"))


def test_a_missed_call_in_the_re_run_counts_as_silent_and_is_counted():
    fake = FakeD1(survival_until_pickups).fail("survival", range(0, 6), "raise")
    result = run_history_test(_client(fake), _history(), "survival", WIDEN.id, CONFIG, WIDER, seed=3)
    assert result.new_missed + result.noise_missed == 6 and result.calls == 28
    missed = [t for t in result.ticks if t.new is not None and t.new.missed]
    assert missed and all(not t.new.spoke and t.new.action is None for t in missed)
    assert result.new.missed == result.new_missed


def test_the_frame_the_instance_saw_is_attached_when_frame_joins_the_scope():
    frame_change = change_option("widen:survival:frame", CONFIG)
    records = _history(frame_ref="frames/00042.jpg")
    frames = {r.key: f"ZnJhbWUt{r.tick:02d}" for r in records[:-3]}  # the last three ticks' screens are no longer held
    fake = FakeD1(default_policy)
    result = run_history_test(
        _client(fake), records, "survival", frame_change.id, CONFIG, apply_change(CONFIG, frame_change), seed=4,
        frame_of=lambda record: frames.get(record.key),
    )
    payloads = [p for p in fake.payloads("survival") if "[frame]" in p["state"]]
    assert len(payloads) == 24
    with_image = [p for p in payloads if "images" in p]
    assert all(p["images"][0].startswith("data:image/jpeg;base64,ZnJhbWUt") for p in with_image)
    held = [t for t in result.ticks if t.key in frames]
    assert len(with_image) == len(held) and all(t.new.image for t in held)
    missing = [n for n in result.notes if "no longer held" in n]
    assert len(missing) == 24 - len(held) > 0


def test_the_central_is_tested_on_agreement_and_disagreement():
    narrow = change_option("narrow:central:vitals", CONFIG)
    fake = FakeD1(default_policy)
    result = run_history_test(_client(fake), _history(), "central", narrow.id, CONFIG, apply_change(CONFIG, narrow), seed=8)
    assert result.kind == "central" and set(result.new.quality) == {"disagreement_on_bad", "agreement_on_good"}
    assert result.calls == 28 == fake.count("central")
    assert all("[vitals]" not in p["state"] for p in fake.payloads("central")[:24])


@pytest.mark.live
def test_live_a_history_test_re_run_on_4_ticks():
    from system1_doom.d1_client import load_api_key

    key = load_api_key()
    if not key:
        pytest.skip("needs LIQUID_API_KEY")
    small = CONFIG.with_bounds(history_test_sample=4, history_test_noise=1, call_budget_sec=15.0)
    client = D1UltraClient(api_key=key, max_workers=2)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = run_history_test(
                client, _history(n_per_episode=4, episodes=2), "survival", WIDEN.id, small, apply_change(small, WIDEN),
                seed=11, executor=pool,
            )
    finally:
        client.shutdown(wait=False)
    assert result.status in ("passed", "failed") and len(result.ticks) == 4 and result.calls == 5
    answered = [t for t in result.ticks if t.new is not None and not t.new.missed]
    assert len(answered) >= 3, [(t.key, t.new) for t in result.ticks]
    assert result.usage.input_tokens > 0 and result.old.composite is not None and result.new.composite is not None
