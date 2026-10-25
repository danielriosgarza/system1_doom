import json

import pytest
import vizdoom as vzd
from pydantic import ValidationError

from system1_doom import train
from system1_doom.actions import ActionSpec, ActionVocabulary
from system1_doom.controller import ControllerConfig, DoomDecisionController
from system1_doom.learning import Learner
from system1_doom.logger import TickTrace
from system1_doom.relevance import load_ledger
from system1_doom.vizdoom_env import ViZDoomBridge
from tests.fake_d1 import FakeD1, default_policy


@pytest.fixture
def vocab() -> ActionVocabulary:
    return ActionVocabulary.default()


def test_motor_executes_the_selected_actions_own_plan(vocab):
    env = ViZDoomBridge(scenario="deadly_corridor.cfg", seed=1)
    try:
        angle_before = env.game.get_game_variable(vzd.GameVariable.ANGLE)
        turn = env.execute_action(vocab.get("turn_left"))
        assert turn.primitive_steps_executed == ["turn_left"] * 4
        assert env.game.get_game_variable(vzd.GameVariable.ANGLE) != angle_before

        back = env.execute_action(vocab.get("move_backward"))
        assert all(step.startswith("move_backward") for step in back.primitive_steps_executed)

        retreat = env.execute_action(vocab.get("retreat_to_cover"))
        steps = retreat.primitive_steps_executed
        assert len(steps) == 3
        assert steps[0].startswith("move_backward") and "strafe_left" in steps[1] and steps[2].startswith("move_backward")
    finally:
        env.close()


def test_weave_fire_keeps_strafing_while_it_aims_and_fires(vocab):
    env = ViZDoomBridge(scenario="deadly_corridor.cfg", seed=1)
    try:
        steps = env.execute_action(vocab.get("weave_fire")).primitive_steps_executed
        assert len(steps) == 4
        assert all("strafe_left" in s for s in steps[:2]) and all("strafe_right" in s for s in steps[2:])
        assert all(("shoot" in s) != ("turn_left" in s or "turn_right" in s) for s in steps)
    finally:
        env.close()


def test_shoot_aims_at_the_target_before_firing(vocab):
    env = ViZDoomBridge(scenario="basic.cfg", seed=5)
    try:
        hits = 0.0
        for _ in range(15):
            if env.is_episode_finished():
                break
            hits += env.execute_action(vocab.get("shoot")).hits_delta
        assert hits >= 1.0
    finally:
        env.close()


def test_train_command_writes_run_folder_and_resumes(tmp_path):
    run_dir = tmp_path / "run"
    fake = FakeD1(default_policy)
    common = ["--scenario", "health_gathering.cfg", "--max-ticks", "12", "--run-dir", str(run_dir), "--seed", "3", "--train-steps", "5"]
    assert train.main(common + ["--episodes", "2"], transport=fake) == 0
    store = train.RunStore(run_dir)
    for path in (store.checkpoint, store.replay, store.macros, store.metrics, store.curves, store.relevance, run_dir / "ticks.jsonl", run_dir / "history.jsonl"):
        assert path.is_file(), path
    assert [row["episode"] for row in store.load_metrics()] == [1, 2]
    assert fake.count("central") == 24, "d1-ultra decided every training decision"

    assert train.main(common + ["--episodes", "1"], transport=fake) == 0
    rows = store.load_metrics()
    assert [row["episode"] for row in rows] == [1, 2, 3]
    assert rows[-1]["transitions"] > 0 and rows[-1]["losses"] and set(rows[-1]["losses"]) == {"survival", "combat", "navigation", "resource", "goal"}
    assert rows[-1]["d1_calls"] == 6 * rows[-1]["ticks"] and rows[-1]["cost_usd"] > 0 and rows[-1]["missed_ticks"] == 0
    assert "exploration_floor" not in rows[-1] and "explored_steps" not in rows[-1]
    assert Learner.load(store.checkpoint).episodes == 3
    assert load_ledger(store.relevance).episodes == 3

    report = train.evaluate("health_gathering.cfg", store, episodes=2, max_ticks=5, transport=fake, api_key="liquid_test_key")
    assert set(report) == {"none", "latest"}
    assert json.loads((run_dir / "evaluation.json").read_text())["trained_episodes"] == 3
    # Evaluation never trains or adds experience.
    assert Learner.load(store.checkpoint).episodes == 3

    # Watching uses the best checkpoint once one exists.
    best = Learner.load(store.checkpoint)
    best.episodes = 99
    best.save(store.best)
    assert train.load_play_learner(store).episodes == 99


def test_train_and_evaluation_start_from_the_saved_configuration_and_fresh_forgets_it(tmp_path, capsys):
    from system1_doom.configuration import Configuration, default_configuration

    store = train.RunStore(tmp_path / "run")
    default_configuration().with_changes(exploration_level="explore").save(store.configuration)
    store.system2.write_text("{}")
    fake = FakeD1(default_policy)
    common = ["--scenario", "basic.cfg", "--max-ticks", "3", "--run-dir", str(store.root), "--seed", "3", "--train-steps", "2"]

    # Evaluation plays under the saved configuration, with System 2 off, and saves nothing.
    assert train.main(common + ["--evaluate", "1"], transport=fake) == 0
    assert f"configuration: {store.configuration} (version 2)" in capsys.readouterr().err
    traces = [TickTrace.model_validate_json(line) for line in (store.root / "eval" / "none" / "ticks.jsonl").read_text().splitlines()]
    assert traces and all(t.configuration_version == 2 and t.exploration_level == "explore" for t in traces)
    assert not (store.root / "eval" / "none" / "reflections.jsonl").exists() and store.system2.read_text() == "{}"

    # --fresh clears the run folder, so the session starts from the design's version 1.
    assert train.main(common + ["--episodes", "1", "--fresh", "--no-system2"], transport=fake) == 0
    assert "configuration: the design's version 1" in capsys.readouterr().err
    assert Configuration.load(store.configuration).version == 1 and not store.system2.exists()


def test_admitted_macros_persist_and_are_revalidated(tmp_path):
    store = train.RunStore(tmp_path)
    macro = ActionSpec(
        id="zigzag_fire",
        description="Zigzag and fire",
        is_macro=True,
        maximum_duration=4,
        termination_condition="sequence_completed",
        primitive_expansion=("strafe_left", "shoot", "strafe_right", "shoot"),
    )
    store.save_macros([macro])

    env = ViZDoomBridge(scenario="basic.cfg")
    ctrl = DoomDecisionController(
        env=env,
        config=ControllerConfig(enable_slow_llm=False, log_dir=str(tmp_path / "logs")),
        api_key="liquid_test_key",
        transport=FakeD1(),
    )
    try:
        ctrl.restore_macros(store.load_macros())
        assert [m.id for m in ctrl.admitted_macros()] == ["zigzag_fire"]
        # Restored before play, the macros are part of the initial configuration (still version 1).
        assert ctrl.configuration.version == 1 and [m.id for m in ctrl.configuration.admitted_macros] == ["zigzag_fire"]
        assert "zigzag_fire" in ctrl.step().available_actions
    finally:
        ctrl.close()

    bad = macro.model_dump(mode="json")
    bad["primitive_expansion"] = ["strafe_left", "noclip"]
    store.macros.write_text(json.dumps([bad]), encoding="utf-8")
    with pytest.raises(ValidationError):
        store.load_macros()


def test_train_has_no_exploration_schedule_and_fails_fast_without_the_key(monkeypatch, capsys):
    assert not hasattr(train, "exploration_schedule")
    with pytest.raises(SystemExit):
        train.build_parser().parse_args(["--explore-start", "0.5"])
    monkeypatch.setattr(train, "load_api_key", lambda: None)
    assert train.main(["--episodes", "1"]) == 2 and "LIQUID_API_KEY" in capsys.readouterr().err


def test_the_motor_idles_for_a_missed_decision():
    env = ViZDoomBridge(scenario="basic.cfg", seed=1)
    try:
        tick = env.acquire_world_state().observation.tick
        idle = env.execute_idle(8)
        assert idle.primitive_steps_executed == ["idle"] * 4 and idle.displacement == pytest.approx(0.0, abs=1e-3)
        state = env.acquire_world_state()
        assert state.observation.tick == tick + 1 and state.observation.recent_actions[-4:] == ("idle",) * 4
        assert "act=missed" in state.memory.recent_state_summaries[-1]
    finally:
        env.close()
