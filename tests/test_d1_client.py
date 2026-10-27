import time
from types import SimpleNamespace

import pytest

from system1_doom import d1_client
from system1_doom.d1_client import (
    DECIDERS,
    DEFAULT_LAYA_URL,
    JEV_IMAGES_HEADER,
    LAYA_MAX_LEN,
    TYPESAFE_SYSTEMONE_URL,
    ChoiceQuestion,
    D1HTTPError,
    D1UltraClient,
    NoulQuestion,
    ScoreQuestion,
    decider_of,
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


def _screen(width: int = 320, height: int = 240) -> str:
    """A JPEG screen as the bridge encodes it: a data URL."""
    import base64
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), (80, 20, 20)).save(out, format="JPEG", quality=75)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def _decoded(asset: dict):
    import base64
    import io

    from PIL import Image

    return Image.open(io.BytesIO(base64.b64decode(asset["data_base64"])))


def test_jev_is_the_same_request_at_typesafe_with_the_screen_as_an_asset():
    captured = []

    def fake_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
        captured.append((url, headers, payload))
        return {"model": "jev-1.14.0", "answers": {"speak": {"type": "noul", "noul": 0.9}}, "usage": {"input_tokens": 1000, "output_tokens": 12}}

    client = D1UltraClient(api_key="ts_test_key", decider="jev", transport=fake_transport, max_workers=1)
    result = client.call("combat", state="[vitals]\nhealth 40", questions={"speak": NoulQuestion(instructions="Speak?")}, images=[_screen()])
    client.shutdown()

    ((url, headers, payload),) = captured
    assert url == "https://api.typesafe.ai/v1/systemone" == TYPESAFE_SYSTEMONE_URL
    assert headers["Authorization"] == "Bearer ts_test_key" and headers[JEV_IMAGES_HEADER] == "true"
    assert payload["model"] == "jev-latest" and "images" not in payload
    assert payload["questions"] == {"speak": {"type": "noul", "instructions": "Speak?"}}
    # The screen is an asset, referenced from the end of the state, where the model reads it in its place.
    ((ref, asset),) = payload["assets"].items()
    assert payload["state"] == f"[vitals]\nhealth 40\n\n[screen image]\n{ref}"
    assert asset["type"] == "image" and asset["format"] == "jpeg" and "data:" not in asset["data_base64"]
    with _decoded(asset) as image:
        # TypeSafe rejects a side under 280 px: the 320x240 screen is doubled, never cropped or padded.
        assert image.format == "JPEG" and image.size == (640, 480)
    assert result.answered and result.response.model == "jev-1.14.0" and result.response.noul("speak").noul == pytest.approx(0.9)
    # Jev's usage names no cost: the input tokens at the published $0.042 per million, output free.
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.cost) == (1000, 12, pytest.approx(4.2e-5))
    assert client.models_answered() == {"jev-1.14.0": 1} and client.counters()["combat"].cost == pytest.approx(4.2e-5)


def test_a_jev_call_without_a_screen_sends_no_assets_and_a_reported_cost_is_kept():
    captured = []

    def fake_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
        captured.append((headers, payload))
        return {"model": "jev-1.14.0", "answers": {"q": {"type": "noul", "noul": 0.1}}, "usage": {"input_tokens": 10, "output_tokens": 1, "cost": 0.5}}

    client = D1UltraClient(api_key="k", decider="jev", transport=fake_transport)
    result = client.call("goal", "[vitals]\nhealth 40", {"q": NoulQuestion(instructions="?")})
    client.shutdown()
    ((headers, payload),) = captured
    assert payload["state"] == "[vitals]\nhealth 40" and "assets" not in payload and JEV_IMAGES_HEADER not in headers
    assert result.usage.cost == 0.5
    # A screen too small to stand (one pixel) is a miss of that call, never an exception in play.
    tiny = D1UltraClient(api_key="k", decider="jev", transport=fake_transport)
    bad = tiny.call("combat", "s", {"q": NoulQuestion(instructions="?")}, images=["data:image/jpeg;base64,AA=="])
    tiny.shutdown()
    assert bad.miss_reason == "error" and bad.response is None


def test_laya_is_the_same_request_on_this_machine_with_the_text_alone():
    captured = []

    def fake_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
        captured.append((url, headers, payload))
        probs = {"r1": 0.9, "none": 0.1}
        return {"model": "laya-rl-agent", "routing": {"model": "english"},
                "answers": {"rule": {"type": "choice", "choice": "r1", "probabilities": probs, "confidence": 0.53}},
                "usage": {"input_tokens": 812, "output_tokens": 0, "truncated": False}}

    question = ChoiceQuestion(instructions="Which of these is true right now?",
                              criteria={"r1": "The threats list shows at least one enemy.", "none": "None of these is true right now."})
    client = D1UltraClient(api_key="", decider="laya", transport=fake_transport, max_workers=1)
    result = client.call("rule:root", "[threats]\n1 enemy visible", {"rule": question}, images=[_screen()])
    client.shutdown()

    ((url, headers, payload),) = captured
    assert url == DEFAULT_LAYA_URL == "http://127.0.0.1:8000/v1/systemone"
    # No key is needed on this machine, and none is sent; the text-only model is sent no screen.
    assert "Authorization" not in headers and JEV_IMAGES_HEADER not in headers
    assert payload == {"model": "english", "state": "[threats]\n1 enemy visible", "questions": {"rule": question.to_payload()},
                       "max_len": LAYA_MAX_LEN}
    assert result.answered and result.response.choice("rule").choice == "r1"
    # Open weights on this machine: no price, so no cost.
    assert (result.usage.input_tokens, result.usage.cost) == (812, 0.0)
    assert client.models_answered() == {"laya-rl-agent": 1}
    # A server started with LAYA_API_KEY is sent the key.
    keyed = D1UltraClient(api_key="laya_local", decider="laya", transport=fake_transport, max_workers=1)
    keyed.call("rule:root", "s", {"rule": question})
    keyed.shutdown()
    assert captured[-1][1]["Authorization"] == "Bearer laya_local"


def test_each_decider_reads_its_own_key(monkeypatch, tmp_path):
    monkeypatch.delenv("LIQUID_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    missing = tmp_path / "none.env"
    assert load_api_key("d1-ultra", missing) is None and load_api_key("jev", missing) is None
    monkeypatch.setenv("TYPESAFE_API_KEY", " ts_env ")
    assert load_api_key("jev", missing) == "ts_env" and load_api_key("d1-ultra", missing) is None
    monkeypatch.delenv("TYPESAFE_API_KEY")
    dotenv = tmp_path / ".env"
    dotenv.write_text('LIQUID_API_KEY="liq"\nTYPESAFE_API_KEY=ts_file\n')
    assert load_api_key("d1-ultra", dotenv) == "liq" and load_api_key("jev", dotenv) == "ts_file"
    assert load_api_key(DECIDERS["jev"], dotenv) == "ts_file"
    with pytest.raises(ValueError, match="unknown decider"):
        decider_of("gpt")
    no_key = D1UltraClient(api_key="", decider="jev", transport=lambda *a: {})
    no_key.api_key = None
    assert no_key.call("a", "s", {"q": NoulQuestion(instructions="?")}).error == "no TYPESAFE_API_KEY"
    assert D1UltraClient(api_key="k", transport=lambda *a: {}).decider.name == "d1-ultra"


@pytest.mark.live
@pytest.mark.skipif(not load_api_key("jev"), reason="needs TYPESAFE_API_KEY")
def test_live_jev_api_call():
    client = D1UltraClient(decider="jev")
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
    assert resp.model.startswith("jev-"), resp.model
    assert resp.choice("evade").choice == "retreat_to_cover"
    assert resp.noul("is_critical").noul > 0.5
    assert result.usage.input_tokens > 0 and result.usage.cost > 0
