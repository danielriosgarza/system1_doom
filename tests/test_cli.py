"""`play`: the flags reach the controller, and play fails fast without the key."""

import json

from system1_doom import cli
from system1_doom.logger import TickTrace
from tests.fake_d1 import FakeD1, shoot_when_aimed


def test_play_fails_fast_without_the_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_api_key", lambda: None)
    assert cli.main(["--scenario", "basic.cfg", "--log-dir", str(tmp_path / "logs")]) == 2
    assert "LIQUID_API_KEY" in capsys.readouterr().err and not (tmp_path / "logs").exists()


def test_play_with_the_flags(tmp_path, capsys):
    fake = FakeD1(shoot_when_aimed)
    argv = [
        "--scenario", "basic.cfg", "--ticks", "3", "--seed", "4", "--explore", "--call-budget", "2.5",
        "--log-dir", str(tmp_path / "logs"), "--run-dir", str(tmp_path / "run"), "--disable-slow-llm",
    ]
    assert cli.main(argv, transport=fake) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["decider"] == "d1-ultra" and summary["exploration_level"] == "explore" and summary["call_budget_sec"] == 2.5
    (result,) = summary["results"]
    assert 1 <= result["ticks"] <= 3 and result["finished_reason"] in ("episode_end", "max_ticks")
    assert summary["instances"]["central"]["calls"] == result["ticks"] and result["cost"]["usd"] > 0
    traces = [TickTrace.model_validate_json(line) for line in (tmp_path / "logs" / "ticks.jsonl").read_text().splitlines()]
    assert all(t.pick.kind == "drawn" for t in traces) and all(t.timing_ms["total"] > 0 for t in traces)
    assert all(t.instances["central"].latency_ms > 0 for t in traces)
    assert (tmp_path / "run" / "relevance.json").is_file() and (tmp_path / "logs" / "history.jsonl").is_file()
    # The budget reaches every call: no transport call was given longer than 2.5 s.
    assert fake.timeouts and max(fake.timeouts) <= 2.5


def test_play_starts_from_a_configuration_file(tmp_path, capsys):
    from system1_doom.configuration import default_configuration

    path = tmp_path / "configuration.json"
    default_configuration().with_changes(active_strategy="strat_corridor_advance").save(path)
    argv = ["--scenario", "basic.cfg", "--ticks", "1", "--configuration", str(path), "--log-dir", str(tmp_path / "logs"),
            "--run-dir", str(tmp_path / "run"), "--disable-slow-llm"]
    assert cli.main(argv, transport=FakeD1()) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["configuration_version"] == 2
    (trace,) = [TickTrace.model_validate_json(line) for line in (tmp_path / "logs" / "ticks.jsonl").read_text().splitlines()]
    assert trace.active_strategy == "strat_corridor_advance" and trace.configuration_version == 2
