"""`play`: the flags reach the controller, and play fails fast without the key."""

import json

from system1_doom import cli
from system1_doom.logger import TickTrace
from tests.fake_d1 import FakeD1, explore_level_system2, shoot_when_aimed


def test_play_fails_fast_without_the_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_api_key", lambda *a, **k: None)
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
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["configuration_version"] == 2 and f"configuration: {path} (version 2)" in captured.err
    (trace,) = [TickTrace.model_validate_json(line) for line in (tmp_path / "logs" / "ticks.jsonl").read_text().splitlines()]
    assert trace.active_strategy == "strat_corridor_advance" and trace.configuration_version == 2


def _notes(path, kind):
    from system1_doom.reflection import System2Note, load_reflections

    return [r for r in load_reflections(path.read_text()) if isinstance(r, System2Note) and r.kind == kind]


def test_the_configuration_and_system2_carry_across_runs_unless_started_fresh(tmp_path, capsys):
    from system1_doom.configuration import Configuration
    from system1_doom.controller import ControllerConfig, DoomDecisionController
    from system1_doom.system2 import System2State
    from system1_doom.train import RunStore
    from system1_doom.vizdoom_env import ViZDoomBridge

    store = RunStore(tmp_path / "run")
    # Run 1, played as the entry points play: System 2 changes the level at the first episode's end, the
    # change takes effect at the second episode's first tick boundary (version 2), and its trial is in flight.
    env = ViZDoomBridge(scenario="basic.cfg", window_visible=False, seed=4)
    cfg = ControllerConfig(
        enable_slow_llm=False, log_dir=str(tmp_path / "logs1"), relevance_path=str(store.relevance), enable_system2=True,
        configuration_out=str(store.configuration), system2_state_path=str(store.system2),
    )
    ctrl = DoomDecisionController(env=env, config=cfg, transport=FakeD1(shoot_when_aimed, system2_policy=explore_level_system2), api_key="liquid_test_key")
    try:
        ctrl.run_episode(max_ticks=3)
        assert ctrl.wait_system2(30)
        env.restart_episode()
        second = ctrl.run_episode(max_ticks=3)
    finally:
        ctrl.close()
    saved = Configuration.load(store.configuration)
    assert second["configuration_end"].version == 2 and saved.version == 2 and saved.exploration_level == "explore"
    state = System2State.model_validate_json(store.system2.read_text())
    assert state.configuration_version == 2 and state.trial is not None and state.trial.change == "level:explore"
    decisions = state.decisions

    # Run 2, a new process with no flag: it starts from the saved version 2, and System 2's state restores.
    argv = ["--scenario", "basic.cfg", "--ticks", "3", "--run-dir", str(store.root), "--disable-slow-llm"]
    assert cli.main(argv + ["--log-dir", str(tmp_path / "logs2")], transport=FakeD1(shoot_when_aimed, system2_policy=explore_level_system2)) == 0
    captured = capsys.readouterr()
    assert f"configuration: {store.configuration} (version 2)" in captured.err
    (result,) = json.loads(captured.out)["results"]
    assert result["configuration_version"] == 2
    traces = [TickTrace.model_validate_json(line) for line in (tmp_path / "logs2" / "ticks.jsonl").read_text().splitlines()]
    assert traces and all(t.configuration_version == 2 and t.exploration_level == "explore" for t in traces)
    (restored,) = _notes(tmp_path / "logs2" / "reflections.jsonl", "restored")
    assert "trial of level:explore continues" in restored.detail and _notes(tmp_path / "logs2" / "reflections.jsonl", "fresh_start") == []
    state = System2State.model_validate_json(store.system2.read_text())
    assert state.decisions == decisions + result["ticks"] and state.trial is not None and state.trial.change == "level:explore"

    # Run 3 with --fresh-configuration: the design's version 1, and System 2 starts over.
    assert cli.main(argv + ["--fresh-configuration", "--log-dir", str(tmp_path / "logs3")], transport=FakeD1(shoot_when_aimed, system2_policy=explore_level_system2)) == 0
    captured = capsys.readouterr()
    assert "configuration: the design's version 1" in captured.err
    (result,) = json.loads(captured.out)["results"]
    assert result["configuration_version"] == 1
    traces = [TickTrace.model_validate_json(line) for line in (tmp_path / "logs3" / "ticks.jsonl").read_text().splitlines()]
    assert traces and all(t.configuration_version == 1 and t.exploration_level == "exploit" for t in traces)
    assert _notes(tmp_path / "logs3" / "reflections.jsonl", "restored") == []
    state = System2State.model_validate_json(store.system2.read_text())
    assert state.decisions == result["ticks"] and state.cycles == 1 and state.trial is None and state.configuration_version == 1
    assert Configuration.load(store.configuration).version == 1


def test_a_change_queued_when_a_run_ends_takes_effect_at_the_next_runs_first_tick_boundary(tmp_path, capsys):
    from system1_doom.configuration import Configuration
    from system1_doom.controller import ControllerConfig, DoomDecisionController
    from system1_doom.system2 import System2State
    from system1_doom.train import RunStore
    from system1_doom.vizdoom_env import ViZDoomBridge

    store = RunStore(tmp_path / "run")
    # Run 1: the episode's end cycle queues `level:explore`, and the run ends before any tick boundary.
    env = ViZDoomBridge(scenario="basic.cfg", window_visible=False, seed=4)
    cfg = ControllerConfig(
        enable_slow_llm=False, log_dir=str(tmp_path / "logs1"), relevance_path=str(store.relevance), enable_system2=True,
        configuration_out=str(store.configuration), system2_state_path=str(store.system2),
    )
    ctrl = DoomDecisionController(env=env, config=cfg, transport=FakeD1(shoot_when_aimed, system2_policy=explore_level_system2), api_key="liquid_test_key")
    try:
        first = ctrl.run_episode(max_ticks=3)
        assert ctrl.wait_system2(30)
    finally:
        ctrl.close()
    assert Configuration.load(store.configuration).version == 1
    state = System2State.model_validate_json(store.system2.read_text())
    assert state.pending is not None and state.pending.stage == "queued" and state.pending.change == "level:explore"
    assert state.pending.version == 2 and len(state.pending.before) == first["ticks"] and state.trial is None
    decisions = state.decisions

    # Run 2 restores the queued change; it takes effect at the first tick boundary as version 2, and its
    # trial starts there, against the decisions before it saved with the change.
    argv = ["--scenario", "basic.cfg", "--ticks", "3", "--run-dir", str(store.root), "--disable-slow-llm", "--log-dir", str(tmp_path / "logs2")]
    assert cli.main(argv, transport=FakeD1(shoot_when_aimed, system2_policy=explore_level_system2)) == 0
    captured = capsys.readouterr()
    assert f"configuration: {store.configuration} (version 1)" in captured.err
    traces = [TickTrace.model_validate_json(line) for line in (tmp_path / "logs2" / "ticks.jsonl").read_text().splitlines()]
    assert traces[0].configuration_version == 2 and traces[0].configuration_changed and traces[0].exploration_level == "explore"
    log = tmp_path / "logs2" / "reflections.jsonl"
    (restored,) = _notes(log, "restored")
    assert "level:explore had not taken effect and is queued again as version 2" in restored.detail
    (started,) = _notes(log, "trial_started")
    assert started.version == 2 and f"against the {first['ticks']} before it" in started.detail
    state = System2State.model_validate_json(store.system2.read_text())
    assert state.pending is None and state.trial is not None and state.trial.change == "level:explore" and state.trial.version == 2
    assert state.trial.started_decision == decisions and state.trial.cooling_key == "system2"
    assert [t.period for t in state.trial.ticks].count("before") == first["ticks"]
    assert Configuration.load(store.configuration).version == 2


def test_a_configuration_that_does_not_load_stops_play_with_its_remedy(tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    (run / "configuration.json").write_text('{"version": "broken"}')
    argv = ["--scenario", "basic.cfg", "--ticks", "1", "--run-dir", str(run), "--disable-slow-llm", "--log-dir", str(tmp_path / "logs")]
    assert cli.main(argv, transport=FakeD1()) == 2
    assert "--fresh-configuration" in capsys.readouterr().err and not (tmp_path / "logs").exists()
    assert cli.main(argv + ["--configuration", str(tmp_path / "missing.json")], transport=FakeD1()) == 2
    assert "no such configuration file" in capsys.readouterr().err


def test_play_runs_system2_unless_switched_off(tmp_path, capsys):
    from tests.fake_d1 import is_system2

    fake = FakeD1(shoot_when_aimed)
    argv = ["--scenario", "basic.cfg", "--ticks", "3", "--run-dir", str(tmp_path / "run"), "--disable-slow-llm"]
    assert cli.main(argv + ["--log-dir", str(tmp_path / "logs")], transport=fake) == 0
    summary = json.loads(capsys.readouterr().out)
    (result,) = summary["results"]
    # The episode's end starts a System 2 cycle; its calls are in the instance counters, not the episode's cost.
    assert result["system2"]["enabled"] and summary["reflections_log"] == str(tmp_path / "logs" / "reflections.jsonl")
    assert (tmp_path / "logs" / "reflections.jsonl").read_text().count('"record":"cycle"') == 1
    assert any(is_system2(name) for name in summary["instances"]) and (tmp_path / "run" / "configuration.json").is_file()
    fake = FakeD1(shoot_when_aimed)
    assert cli.main(argv + ["--no-system2", "--log-dir", str(tmp_path / "off")], transport=fake) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["results"][0]["system2"]["enabled"] is False and summary["reflections_log"] is None
    assert not any(is_system2(name) for name, _ in fake.calls) and not (tmp_path / "off" / "reflections.jsonl").exists()


def test_play_on_jev_reaches_the_summary_and_every_call_goes_to_typesafe(tmp_path, capsys):
    from system1_doom.d1_client import TYPESAFE_SYSTEMONE_URL

    fake = FakeD1(shoot_when_aimed, decider="jev")
    argv = [
        "--scenario", "basic.cfg", "--ticks", "2", "--decider", "jev", "--no-system2",
        "--log-dir", str(tmp_path / "logs"), "--run-dir", str(tmp_path / "run"), "--disable-slow-llm",
    ]
    assert cli.main(argv, transport=fake) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["decider"] == "jev" and summary["models"] == {"jev-1.14.0": len(fake.calls)} and len(fake.calls) >= 6
    assert all(url == TYPESAFE_SYSTEMONE_URL for url, _ in fake.requests)
    (result,) = summary["results"]
    assert result["cost"]["usd"] > 0 and summary["instances"]["combat"]["cost"] > 0


def test_play_on_jev_fails_fast_without_its_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_api_key", lambda *a, **k: None)
    assert cli.main(["--scenario", "basic.cfg", "--decider", "jev", "--log-dir", str(tmp_path / "logs")]) == 2
    err = capsys.readouterr().err
    assert "TYPESAFE_API_KEY is not set" in err and "jev makes every decision" in err and not (tmp_path / "logs").exists()
