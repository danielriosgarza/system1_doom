import time
import pytest

from system1_doom.d1_client import (
    ChoiceQuestion,
    D1UltraClient,
    NoulQuestion,
    ScoreQuestion,
    load_api_key,
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
                "expand": {
                    "type": "noul",
                    "noul": 0.12,
                },
            },
            "usage": {"input_tokens": 120, "output_tokens": 0, "cost": 5.04e-6},
        }

    client = D1UltraClient(api_key="liquid_test_key", transport=fake_transport)
    resp = client.decide(
        state="Health=30, Enemy=Imp at 100",
        questions={
            "pick_action": ChoiceQuestion(
                instructions="Choose survival action",
                criteria={"strafe_left": "Dodge left", "shoot": "Fire weapon"},
            ),
            "threat": ScoreQuestion(
                instructions="Rate threat",
                criteria=["Low", "Medium", "High"],
            ),
            "expand": NoulQuestion(instructions="Request macro expansion?"),
        },
        images=["data:image/jpeg;base64,AA=="],
    )

    assert len(captured_payloads) == 1
    url, headers, payload, _ = captured_payloads[0]
    assert url == "https://api.liquid.ai/decisions/v1/systemone"
    assert headers["Authorization"] == "Bearer liquid_test_key"
    assert payload["model"] == "d1-ultra"
    assert payload["images"] == ["data:image/jpeg;base64,AA=="]

    assert resp is not None
    assert resp.model == "d1-ultra"
    assert resp.choice("pick_action").choice == "strafe_left"
    assert resp.choice("pick_action").probabilities["strafe_left"] == pytest.approx(0.75)
    assert resp.score("threat").score == pytest.approx(1.8)
    assert resp.noul("expand").noul == pytest.approx(0.12)


def test_d1_async_nonblocking_cache_and_disabled_mode():
    def slow_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
        time.sleep(0.05)
        return {
            "model": "d1-ultra",
            "answers": {
                "gate": {"type": "noul", "noul": 0.91},
            },
            "usage": {"input_tokens": 40, "output_tokens": 0},
        }

    client = D1UltraClient(api_key="liquid_test_key", transport=slow_transport)
    # Submitting async should return immediately without blocking
    t0 = time.perf_counter()
    client.submit_async(
        context_key="ctx_1",
        state="test state",
        questions={"gate": NoulQuestion(instructions="Is it safe?")},
    )
    elapsed_submit = time.perf_counter() - t0
    assert elapsed_submit < 0.03

    # Wait for background worker to populate cache
    deadline = time.time() + 1.0
    cached = None
    while time.time() < deadline:
        cached = client.get_cached("ctx_1")
        if cached is not None:
            break
        time.sleep(0.01)

    assert cached is not None
    assert cached.noul("gate").noul == pytest.approx(0.91)
    client.shutdown()

    # Disabled client returns None cleanly without error
    disabled_client = D1UltraClient(api_key="liquid_test_key", enabled=False, transport=slow_transport)
    assert disabled_client.decide("state", {"gate": NoulQuestion(instructions="Is it safe?")}) is None


def test_live_d1_ultra_api_call():
    api_key = load_api_key()
    assert api_key, "LIQUID_API_KEY must be available in .env or environment"
    client = D1UltraClient(api_key=api_key)
    resp = client.decide(
        state="DOOM tick=5: player health=20, armor=0, 2 ShotgunGuys at distance 110 firing at player.",
        questions={
            "evade": ChoiceQuestion(
                instructions="Which immediate action minimizes probability of death?",
                criteria={
                    "retreat_to_cover": "Move backward and sidestep behind cover",
                    "move_forward": "Run straight into enemy shotgun fire",
                },
            ),
            "is_critical": NoulQuestion(
                instructions="Is the player in immediate danger of dying within the next few ticks?"
            ),
        },
        timeout=15.0,
    )
    assert resp is not None
    assert resp.model == "d1-ultra"
    assert resp.choice("evade").choice == "retreat_to_cover"
    assert resp.noul("is_critical").noul > 0.5
