"""The senses: five parallel calls, each a message, silence, or a typed miss that nothing replaces."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from system1_doom.configuration import SENSE_NAMES, default_configuration
from system1_doom.d1_client import D1UltraClient
from system1_doom.evidence import Message
from system1_doom.senses import message_of, messages_of, run_senses, sense_specs
from tests.fake_d1 import FakeD1, sense_answers, default_policy, menu_of, section
from tests.test_evidence import golden_inputs

CONFIG = default_configuration()


def _run(fake: FakeD1, config=CONFIG, frame_b64=None):
    client = D1UltraClient(api_key="liquid_test_key", transport=fake, max_workers=config.bounds.system1_pool)
    pool = ThreadPoolExecutor(max_workers=config.bounds.system1_pool)
    try:
        return run_senses(client, config, golden_inputs(), pool, frame_b64=frame_b64)
    finally:
        pool.shutdown(wait=False)
        client.shutdown(wait=False)


def test_the_five_senses_come_from_the_configuration_in_order():
    specs = sense_specs(CONFIG)
    assert tuple(s.name for s in specs) == SENSE_NAMES
    assert all(s.kind == "sense" and "menu" in s.scope for s in specs)
    assert specs[1].scope == CONFIG.senses["combat"].scope and specs[1].reasons == CONFIG.senses["combat"].reasons


def test_each_sense_sees_only_its_scope():
    fake = FakeD1()
    results = _run(fake, frame_b64="QUJD")
    for name in SENSE_NAMES:
        (payload,) = fake.payloads(name)
        headers = [line[1:-1] for line in payload["state"].splitlines() if line.startswith("[") and line.endswith("]")]
        assert tuple(headers) == tuple(c for c in results[name].scope), name
        assert set(headers) == set(CONFIG.senses[name].scope), name
        assert section(payload["state"], "messages") == "" and section(payload["state"], "relevance") == ""
        assert ("images" in payload) == ("frame" in CONFIG.senses[name].scope), name
    assert "Medikit" not in fake.payloads("survival")[0]["state"]
    assert "Medikit" in fake.payloads("resource")[0]["state"]


def test_spoken_senses_become_messages_in_sense_order_and_silent_ones_do_not():
    # The golden fixture has an enemy under the crosshair: combat speaks at 0.9; survival (health 64) at 0.2.
    results = _run(FakeD1(default_policy))
    assert results["combat"].spoke and not results["survival"].spoke
    assert messages_of(results) == (
        Message(
            sense="combat", action="shoot", reason="target_aimed", strength=0.9, target="zombie_1", target_kind="enemy",
            target_line="Zombieman at distance 180, 2 deg left, size 24x56 px, under the crosshair",
        ),
    )
    assert message_of(results["survival"]) is None


def test_a_missed_sense_is_silence_and_the_others_still_speak():
    def everyone_speaks(name, payload):
        return sense_answers(payload, 0.8, menu_of(payload)[-1])

    fake = FakeD1(everyone_speaks).fail("combat", [0], "raise").fail("goal", [0], "off_menu")
    results = _run(fake)
    assert results["combat"].missed and results["combat"].miss_reason == "error"
    assert results["goal"].missed and results["goal"].miss_reason == "off_menu"
    assert [m.sense for m in messages_of(results)] == ["survival", "navigation", "resource"]
    assert all(m.action == "approach_pickup" and m.strength == 0.8 for m in messages_of(results))


def test_the_senses_run_in_parallel_within_the_budget():
    def slow(name, payload):
        time.sleep(0.3)
        return default_policy(name, payload)

    started = time.monotonic()
    results = _run(FakeD1(slow))
    elapsed = time.monotonic() - started
    assert len(results) == 5 and not any(r.missed for r in results.values())
    assert elapsed < 0.9, f"five 0.3 s calls took {elapsed:.2f} s: not parallel"


def test_a_sense_over_budget_is_a_timeout_miss():
    config = default_configuration().with_bounds(call_budget_sec=0.3)
    fake = FakeD1().fail("navigation", [0], "timeout")
    started = time.monotonic()
    results = _run(fake, config)
    assert time.monotonic() - started < 0.3 + 0.3
    assert results["navigation"].missed and results["navigation"].miss_reason == "timeout"
    assert results["navigation"].action is None and results["navigation"].strength is None
    assert sum(r.missed for r in results.values()) == 1


@pytest.mark.parametrize("p, spoke", [(0.5, True), (0.4999, False), (1.0, True), (0.0, False)])
def test_the_speak_line_is_d1s_own_yes(p, spoke):
    def policy(name, payload):
        return sense_answers(payload, p, "shoot")

    results = _run(FakeD1(policy))
    assert all(r.spoke is spoke and r.strength == p for r in results.values())
    assert len(messages_of(results)) == (5 if spoke else 0)
