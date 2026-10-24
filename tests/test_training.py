import json

import pytest
import vizdoom as vzd
from pydantic import ValidationError

from system1_doom import train
from system1_doom.actions import ActionSpec, ActionVocabulary
from system1_doom.controller import ControllerConfig, DoomDecisionController
from system1_doom.learning import Learner
from system1_doom.vizdoom_env import ViZDoomBridge


@pytest.fixture
def vocab() -> ActionVocabulary:
    return ActionVocabulary.default()


def test_motor_executes_the_selected_actions_own_plan(vocab):
    env = ViZDoomBridge(scenario="deadly_corridor.cfg", include_jpeg_frame=False, seed=1)
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
    env = ViZDoomBridge(scenario="deadly_corridor.cfg", include_jpeg_frame=False, seed=1)
    try:
        steps = env.execute_action(vocab.get("weave_fire")).primitive_steps_executed
        assert len(steps) == 4
        assert all("strafe_left" in s for s in steps[:2]) and all("strafe_right" in s for s in steps[2:])
        assert all(("shoot" in s) != ("turn_left" in s or "turn_right" in s) for s in steps)
    finally:
        env.close()


def test_shoot_aims_at_the_target_before_firing(vocab):
    env = ViZDoomBridge(scenario="basic.cfg", include_jpeg_frame=False, seed=5)
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
    common = ["--scenario", "health_gathering.cfg", "--max-ticks", "15", "--run-dir", str(run_dir), "--seed", "3", "--train-steps", "5"]
    assert train.main(common + ["--episodes", "2"]) == 0
    store = train.RunStore(run_dir)
    for path in (store.checkpoint, store.replay, store.macros, store.metrics, store.curves, run_dir / "ticks.jsonl"):
        assert path.is_file(), path
    assert [row["episode"] for row in store.load_metrics()] == [1, 2]

    assert train.main(common + ["--episodes", "1"]) == 0
    rows = store.load_metrics()
    assert [row["episode"] for row in rows] == [1, 2, 3]
    assert rows[-1]["transitions"] > 0 and rows[-1]["losses"]
    assert Learner.load(store.checkpoint).episodes == 3

    report = train.evaluate("health_gathering.cfg", store, episodes=2, max_ticks=10)
    assert set(report) == {"heuristics", "latest"}
    assert json.loads((run_dir / "evaluation.json").read_text())["trained_episodes"] == 3
    # Evaluation never trains or adds experience.
    assert Learner.load(store.checkpoint).episodes == 3

    # Watching uses the best checkpoint once one exists.
    best = Learner.load(store.checkpoint)
    best.episodes = 99
    best.save(store.best)
    assert train.load_play_learner(store).episodes == 99


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

    env = ViZDoomBridge(scenario="basic.cfg", include_jpeg_frame=False)
    ctrl = DoomDecisionController(
        env=env,
        config=ControllerConfig(enable_d1_ultra=False, enable_slow_llm=False, log_dir=str(tmp_path / "logs")),
    )
    try:
        ctrl.restore_macros(store.load_macros())
        assert [m.id for m in ctrl.admitted_macros()] == ["zigzag_fire"]
        assert "zigzag_fire" in ctrl.step().available_actions
    finally:
        ctrl.close()

    bad = macro.model_dump(mode="json")
    bad["primitive_expansion"] = ["strafe_left", "noclip"]
    store.macros.write_text(json.dumps([bad]), encoding="utf-8")
    with pytest.raises(ValidationError):
        store.load_macros()


def test_exploration_schedule_decays_linearly():
    assert train.exploration_schedule(0, 0.6, 0.05, 100) == pytest.approx(0.6)
    assert train.exploration_schedule(50, 0.6, 0.05, 100) == pytest.approx(0.325)
    assert train.exploration_schedule(500, 0.6, 0.05, 100) == pytest.approx(0.05)
