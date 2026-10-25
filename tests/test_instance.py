"""One instance, one call: the payload holds only its scope; answers are read, or the call is a miss."""

import time

import pytest

from system1_doom.configuration import default_configuration
from system1_doom.d1_client import D1UltraClient
from system1_doom.instance import ADMIT_SPEC, central_spec, run_admit, run_instance, sense_spec
from tests.fake_d1 import FakeD1, choice, menu_of, noul, section
from tests.test_evidence import golden_inputs

CONFIG = default_configuration()


def _client(fake: FakeD1, **kwargs) -> D1UltraClient:
    return D1UltraClient(api_key="liquid_test_key", transport=fake, **kwargs)


def _sense(name: str, fake: FakeD1, budget: float = 2.0, **kwargs):
    client = _client(fake)
    try:
        return run_instance(client, sense_spec(name, CONFIG.senses[name]), golden_inputs(), budget=budget, **kwargs), client
    finally:
        client.shutdown(wait=False)


def test_a_sense_sends_one_payload_of_its_scope_its_questions_and_the_frame_only_when_in_scope():
    fake = FakeD1()
    combat, _ = _sense("combat", fake, frame_b64="QUJD")
    survival, _ = _sense("survival", fake, frame_b64="QUJD")
    (combat_payload,), (survival_payload,) = fake.payloads("combat"), fake.payloads("survival")
    assert combat_payload["model"] == "d1-ultra" and set(combat_payload["questions"]) == {"speak", "action", "reason"}
    assert combat_payload["state"] == combat.evidence and combat_payload["images"] == ["data:image/jpeg;base64,QUJD"]
    assert combat.image_ref == "frames/00042.jpg" and survival.image_ref is None and "images" not in survival_payload
    assert section(survival_payload["state"], "pickups") == "" and "Medikit" not in survival_payload["state"]
    questions = combat_payload["questions"]
    assert questions["speak"]["type"] == "noul" and questions["action"]["type"] == questions["reason"]["type"] == "choice"
    assert menu_of(combat_payload) == ["shoot", "strafe_left", "approach_pickup"]
    assert list(questions["reason"]["criteria"]) == list(CONFIG.senses["combat"].reasons)
    instructions = questions["speak"]["instructions"]
    assert "combat sense" in instructions and "winning the current fight" in instructions and "only the evidence given" in instructions
    for forbidden in ("weigh", "prefer", "probability", "score"):
        assert all(forbidden not in q["instructions"] for q in questions.values()), forbidden


def test_a_sense_speaks_at_one_half_and_its_message_carries_action_reason_strength():
    def at(p):
        def policy(name, payload):
            return {
                "speak": noul(p),
                "action": choice(menu_of(payload), "strafe_left"),
                "reason": choice(list(payload["questions"]["reason"]["criteria"]), "under_fire"),
            }

        return policy

    spoke, _ = _sense("survival", FakeD1(at(0.5)))
    assert spoke.spoke and spoke.strength == 0.5 and spoke.speak == 0.5
    assert (spoke.action, spoke.reason) == ("strafe_left", "under_fire")
    assert spoke.action_probabilities["strafe_left"] == pytest.approx(0.7)
    assert spoke.answers["speak"] == {"type": "noul", "noul": 0.5}
    silent, _ = _sense("survival", FakeD1(at(0.49)))
    assert not silent.spoke and silent.strength == 0.49 and silent.action == "strafe_left" and not silent.missed


@pytest.mark.parametrize(
    "fault, reason",
    [("timeout", "timeout"), ("raise", "error"), ("off_menu", "off_menu"), ("malformed", "malformed"), ("negative", "malformed")],
)
def test_a_failed_sense_is_a_miss_and_nothing_stands_in(fault, reason):
    fake = FakeD1().fail("combat", [0], fault)
    started = time.monotonic()
    result, client = _sense("combat", fake, budget=0.3)
    assert time.monotonic() - started < 0.3 + 0.15
    assert result.missed and result.miss_reason == reason
    assert not result.spoke and result.action is None and result.strength is None and result.reason is None
    assert result.action_probabilities == {}
    assert result.evidence and result.latency_ms > 0
    if fault in ("off_menu", "malformed", "negative"):
        assert result.raw_answer is not None and result.answers
    assert client.counters()["combat"].misses == {reason: 1}


def test_an_off_vocabulary_reason_is_malformed():
    def policy(name, payload):
        return {"speak": noul(0.9), "action": choice(menu_of(payload), "shoot"), "reason": choice(["because"], "because")}

    result, _ = _sense("combat", FakeD1(policy))
    assert result.missed and result.miss_reason == "malformed" and result.action is None


def test_rate_limits_wait_within_the_budget_and_count_as_retries():
    fake = FakeD1(retry_after=0.05).fail("goal", [0], "http_429")
    result, client = _sense("goal", fake, budget=2.0)
    assert not result.missed and result.retries == 1 and client.counters()["goal"].retries == 1
    slow = FakeD1(retry_after=5.0).fail("goal", [0], "http_429")
    result, _ = _sense("goal", slow, budget=0.5)
    assert result.missed and result.miss_reason == "http_429_exhausted"


def test_usage_and_latency_are_recorded():
    result, client = _sense("resource", FakeD1())
    assert result.usage.input_tokens == len(result.evidence) // 4 and result.usage.cost > 0
    counters = client.counters()["resource"]
    assert counters.calls == counters.answered == 1 and counters.input_tokens == result.usage.input_tokens


def test_the_central_payload_holds_only_its_scope_and_one_choice_over_the_menu():
    fake = FakeD1()
    client = _client(fake)
    result = run_instance(client, central_spec(CONFIG.central), golden_inputs(), frame_b64="QUJD")
    client.shutdown(wait=False)
    (payload,) = fake.payloads("central")
    assert set(payload["questions"]) == {"choose"} and "images" not in payload
    assert list(payload["questions"]["choose"]["criteria"]) == ["shoot", "strafe_left", "approach_pickup"]
    headers = [line for line in payload["state"].splitlines() if line.startswith("[")]
    assert headers == ["[vitals]", "[menu]", "[exploration]", "[messages]", "[relevance]"]
    assert "Zombieman" not in payload["state"] and "expected value" not in payload["state"]
    # The fake central picks the first message's action: survival's strafe_left.
    assert result.action == "strafe_left" and result.action_probabilities["strafe_left"] == pytest.approx(0.7)


def test_the_admit_instance_asks_one_noul_over_the_proposal():
    fake = FakeD1()
    client = _client(fake)
    result = run_admit(client, "Proposal: zigzag_fire\nSandbox: survives")
    client.shutdown(wait=False)
    (payload,) = fake.payloads("admit")
    assert set(payload["questions"]) == {"admit"} and payload["questions"]["admit"]["type"] == "noul"
    assert payload["state"] == "Proposal: zigzag_fire\nSandbox: survives"
    assert result.admit == 0.8 and result.kind == "admit" and ADMIT_SPEC.concern in payload["questions"]["admit"]["instructions"]
