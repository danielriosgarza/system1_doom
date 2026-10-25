"""The central instance and the pick: top under exploit, drawn under explore, missed on a miss."""

import random

import pytest

from system1_doom.configuration import default_configuration
from system1_doom.d1_client import D1UltraClient
from system1_doom.instance import InstanceResult
from system1_doom.system1 import System1, central_scope, pick_action
from tests.fake_d1 import FakeD1, choice, default_policy, menu_of, noul, section, spread_central
from tests.test_evidence import golden_inputs

EXPLOIT = default_configuration()
EXPLORE = default_configuration(exploration_level="explore")


def _system1(fake: FakeD1, seed: int = 0) -> System1:
    client = D1UltraClient(api_key="liquid_test_key", transport=fake, max_workers=6)
    return System1(client, pool_size=6, seed=seed)


def _tick(fake: FakeD1, config=EXPLOIT, seed: int = 0, inputs=None):
    s1 = _system1(fake, seed)
    try:
        return s1.tick(config, inputs or golden_inputs().model_copy(update={"messages": ()}), frame_b64="QUJD")
    finally:
        s1.shutdown()
        s1.client.shutdown(wait=False)


def _headers(state: str):
    return [line[1:-1] for line in state.splitlines() if line.startswith("[") and line.endswith("]")]


def test_the_central_payload_holds_only_its_scope_and_hears_the_messages():
    fake = FakeD1(default_policy)
    result = _tick(fake)
    (payload,) = fake.payloads("central")
    assert _headers(payload["state"]) == ["vitals", "menu", "exploration", "messages", "relevance"]
    assert set(payload["questions"]) == {"choose"} and "images" not in payload
    assert list(payload["questions"]["choose"]["criteria"]) == ["shoot", "strafe_left", "approach_pickup"]
    assert section(payload["state"], "messages") == "combat says shoot, strength 0.90, reason target aimed."
    assert "Zombieman" not in payload["state"] and "Medikit" not in payload["state"]
    assert result.central.evidence == payload["state"]
    assert result.messages[0].sense == "combat" and result.inputs.messages == result.messages


def test_exploit_executes_the_top_action():
    result = _tick(FakeD1(default_policy))
    assert result.pick.kind == "top" and result.pick.action == "shoot" == result.central.action
    assert result.pick.probability == pytest.approx(0.7) and result.pick.draw is None and not result.pick.tie
    assert list(result.instances) == ["survival", "combat", "navigation", "resource", "goal", "central"]
    assert not result.missed and result.wall_ms >= result.senses_ms


def test_the_central_decides_when_no_sense_spoke():
    def silent(name, payload):
        if name == "central":
            return {"choose": choice(menu_of(payload), "approach_pickup")}
        reasons = list(payload["questions"]["reason"]["criteria"])
        return {"speak": noul(0.1), "action": choice(menu_of(payload), "shoot"), "reason": choice(reasons, reasons[0])}

    fake = FakeD1(silent)
    result = _tick(fake)
    assert result.messages == ()
    assert section(fake.payloads("central")[0]["state"], "messages") == "no sense spoke this tick."
    assert result.pick.kind == "top" and result.pick.action == "approach_pickup"


def test_explore_draws_from_d1s_distribution_reproducibly_and_adds_novelty():
    assert central_scope(EXPLORE) == EXPLOIT.central.scope + ("novelty",)
    fake = FakeD1(spread_central)
    first = _tick(fake, EXPLORE, seed=7)
    (payload,) = fake.payloads("central")
    assert "novelty" in _headers(payload["state"])
    assert "draws" not in payload["state"] and "drawn from your probabilities" in section(payload["state"], "exploration")
    assert first.pick.kind == "drawn" and 0.0 <= first.pick.draw < 1.0
    again = _tick(FakeD1(spread_central), EXPLORE, seed=7)
    assert again.pick == first.pick
    # The draw walks d1's distribution in menu order: 0.4, 0.3, 0.3.
    expected = random.Random(7).random()
    assert first.pick.draw == expected
    assert first.pick.action == ("shoot" if expected < 0.4 else "strafe_left" if expected < 0.7 else "approach_pickup")


def test_explore_picks_follow_d1s_distribution_over_many_draws():
    central = InstanceResult(
        name="central", kind="central", evidence="", action="a",
        action_probabilities={"a": 0.5, "b": 0.3, "c": 0.2, "d": 0.0},
    )
    rng = random.Random(3)
    picks = [pick_action(central, ["a", "b", "c", "d"], "explore", rng) for _ in range(4000)]
    share = {k: sum(p.action == k for p in picks) / len(picks) for k in "abcd"}
    assert share["d"] == 0.0
    assert share["a"] == pytest.approx(0.5, abs=0.03) and share["b"] == pytest.approx(0.3, abs=0.03)
    assert all(p.kind == "drawn" and p.probability == central.action_probabilities[p.action] for p in picks)


def test_novelty_is_not_added_without_room():
    full = default_configuration(
        exploration_level="explore",
        central={"scope": ("messages", "relevance", "exploration", "vitals", "threats", "pickups", "menu"), "concern": "choosing"},
    )
    assert central_scope(full) == full.central.scope


def test_a_tie_goes_to_the_first_in_menu_order_and_is_logged():
    central = InstanceResult(
        name="central", kind="central", evidence="", action="b",
        action_probabilities={"a": 0.2, "b": 0.4, "c": 0.4},
    )
    pick = pick_action(central, ["a", "b", "c"], "exploit", random.Random(0))
    assert pick.action == "b" and pick.tie and pick.tied == ("b", "c")


@pytest.mark.parametrize("fault, reason", [("timeout", "timeout"), ("raise", "error"), ("off_menu", "off_menu"), ("malformed", "malformed")])
def test_a_missed_central_is_a_missed_pick_with_no_action(fault, reason):
    config = default_configuration().with_bounds(call_budget_sec=0.4)
    result = _tick(FakeD1(default_policy).fail("central", [0], fault), config)
    assert result.missed and result.pick.kind == "missed" and result.pick.action is None
    assert result.central.missed and result.central.miss_reason == reason
    assert result.misses() == ["central"]


def test_the_central_rate_limited_within_budget_still_answers():
    result = _tick(FakeD1(default_policy, retry_after=0.05).fail("central", [0], "http_429"))
    assert result.pick.kind == "top" and result.central.retries == 1


def test_usage_sums_over_the_six_instances():
    result = _tick(FakeD1(default_policy))
    usage = result.usage()
    assert usage.input_tokens == sum(r.usage.input_tokens for r in result.instances.values()) > 0
    assert usage.cost == pytest.approx(sum(r.usage.cost for r in result.instances.values()))
