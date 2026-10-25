import time
from types import SimpleNamespace

import pytest

from system1_doom import d1_client
from system1_doom.d1_client import (
    ChoiceQuestion,
    D1HTTPError,
    D1UltraClient,
    NoulQuestion,
    ScoreQuestion,
    load_api_key,
    parse_retry_after,
)


def test_d1_request_serialization_and_mock_transport():
    captured_payloads = []

    def fake_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
        captured_payloads.append((url, headers, payload, timeout))
        return {
            "model": "d1-ultra",
            "answers": {
                "pick_action": {
                    "type": "choice",
                    "choice": "strafe_left",
                    "probabilities": {"strafe_left": 0.75, "shoot": 0.25},
                    "confidence": 0.68,
                },
                "threat": {
                    "type": "score",
                    "score": 1.8,
                    "probabilities": {"0": 0.05, "1": 0.10, "2": 0.85},
                    "legend": {"0": "Low", "1": "Medium", "2": "High"},
                    "confidence": 0.82,
                },
                "expand": {"type": "noul", "noul": 0.12},
            },
            "usage": {"input_tokens": 120, "output_tokens": 0, "cost": 5.04e-6},
        }

    client = D1UltraClient(api_key="liquid_test_key", transport=fake_transport, max_workers=2)
    result = client.call(
        "tester",
        state="Health=30, Enemy=Imp at 100",
        questions={
            "pick_action": ChoiceQuestion(
                instructions="Choose survival action",
                criteria={"strafe_left": "Dodge left", "shoot": "Fire weapon"},
            ),
            "threat": ScoreQuestion(instructions="Rate threat", criteria=["Low", "Medium", "High"]),
            "expand": NoulQuestion(instructions="Request macro expansion?"),
        },
        images=["data:image/jpeg;base64,AA=="],
        budget=3.0,
    )
    client.shutdown()

    assert len(captured_payloads) == 1
    url, headers, payload, timeout = captured_payloads[0]
    assert url == "https://api.liquid.ai/decisions/v1/systemone"
    assert headers["Authorization"] == "Bearer liquid_test_key"
    assert payload["model"] == "d1-ultra" and payload["state"] == "Health=30, Enemy=Imp at 100"
    assert payload["images"] == ["data:image/jpeg;base64,AA=="]
    assert payload["questions"]["pick_action"] == {
        "type": "choice",
        "instructions": "Choose survival action",
        "criteria": {"strafe_left": "Dodge left", "shoot": "Fire weapon"},
    }
    assert 0 < timeout <= 3.0

    assert result.answered and result.miss_reason is None and result.retries == 0
    resp = result.response
    assert resp.model == "d1-ultra"
    assert resp.choice("pick_action").choice == "strafe_left"
    assert resp.choice("pick_action").probabilities["strafe_left"] == pytest.approx(0.75)
    assert resp.score("threat").score == pytest.approx(1.8)
    assert resp.noul("expand").noul == pytest.approx(0.12)
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.cost) == (120, 0, pytest.approx(5.04e-6))
    assert result.latency_ms >= 0
    counters = client.counters()["tester"]
    assert counters.calls == counters.answered == 1 and counters.input_tokens == 120 and client.call_count == 1


def test_misses_are_typed_and_counted_per_instance():
    def slow(url, headers, payload, timeout):
        time.sleep(timeout + 0.1)
        return {"answers": {}}

    def broken(url, headers, payload, timeout):
        raise ConnectionError("down")

    question = {"q": NoulQuestion(instructions="?")}
    no_key = D1UltraClient(api_key="", transport=broken)
    no_key.api_key = None
    assert no_key.call("a", "s", question).miss_reason == "error"
    client = D1UltraClient(api_key="k", transport=slow)
    started = time.monotonic()
    late = client.call("survival", "s", question, budget=0.2)
    assert late.miss_reason == "timeout" and late.response is None and time.monotonic() - started < 0.35
    client = D1UltraClient(api_key="k", transport=broken)
    failed = client.call("combat", "s", question)
    assert failed.miss_reason == "error" and "down" in failed.error
    assert client.counters()["combat"].misses == {"error": 1}
    garbled = D1UltraClient(api_key="k", transport=lambda *a: {"no": "answers"}).call("goal", "s", question)
    assert garbled.miss_reason == "malformed"


def test_retry_after_parsing():
    assert parse_retry_after("2") == 2.0
    assert parse_retry_after(None) is None and parse_retry_after("soon") is None
    assert 0.0 <= parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") <= 0.0


def test_the_default_transport_raises_a_typed_429(monkeypatch):
    response = SimpleNamespace(status_code=429, headers={"Retry-After": "1.5"}, text="slow down", json=lambda: {})
    monkeypatch.setattr(d1_client.requests, "post", lambda *a, **k: response)
    with pytest.raises(D1HTTPError) as exc:
        d1_client._default_requests_transport("u", {}, {}, 1.0)
    assert exc.value.status == 429 and exc.value.retry_after == 1.5


@pytest.mark.live
@pytest.mark.skipif(not load_api_key(), reason="needs LIQUID_API_KEY")
def test_live_d1_ultra_api_call():
    api_key = load_api_key()
    client = D1UltraClient(api_key=api_key)
    result = client.call(
        "live",
        state="DOOM tick=5: player health=20, armor=0, 2 ShotgunGuys at distance 110 firing at player.",
        questions={
            "evade": ChoiceQuestion(
                instructions="Which immediate action minimizes probability of death?",
                criteria={
                    "retreat_to_cover": "Move backward and sidestep behind cover",
                    "move_forward": "Run straight into enemy shotgun fire",
                },
            ),
            "is_critical": NoulQuestion(instructions="Is the player in immediate danger of dying within the next few ticks?"),
        },
        budget=15.0,
    )
    client.shutdown()
    assert result.answered, result.error
    resp = result.response
    assert resp.model == "d1-ultra"
    assert resp.choice("evade").choice == "retreat_to_cover"
    assert resp.noul("is_critical").noul > 0.5
    assert result.usage.input_tokens > 0
