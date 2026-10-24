"""The controller should finish ViZDoom episodes with its own choices driving play."""

from system1_doom.actions import ActionVocabulary
from system1_doom.controller import ControllerConfig, DoomDecisionController
from system1_doom.learning import Learner
from system1_doom.motor import STEPS_PER_DECISION
from system1_doom.vizdoom_env import ViZDoomBridge


def _play(scenario: str, max_ticks: int, log_dir: str, learner=None) -> dict:
    env = ViZDoomBridge(scenario=scenario, window_visible=False, include_jpeg_frame=False, seed=11)
    cfg = ControllerConfig(
        execution_mode="async_cached",
        enable_d1_ultra=False,
        enable_slow_llm=False,
        tick_budget_sec=0.05,
        log_dir=log_dir,
        deterministic_arbiter=True,
        record_experience=learner is not None,
    )
    ctrl = DoomDecisionController(env=env, config=cfg, learner=learner)
    try:
        return ctrl.run_episode(max_ticks=max_ticks)
    finally:
        ctrl.close()


def test_heuristic_controller_clears_basic_scenario(tmp_path):
    result = _play("basic.cfg", max_ticks=40, log_dir=str(tmp_path / "logs"))
    assert result["cleared"], {k: v for k, v in result.items() if k != "traces"}
    assert result["kills"] >= 1


def test_every_executed_step_follows_the_selected_actions_plan(tmp_path):
    vocab = ActionVocabulary.default()
    result = _play("deadly_corridor.cfg", max_ticks=20, log_dir=str(tmp_path / "logs"))
    assert result["traces"]
    for trace in result["traces"]:
        plan = vocab.get(trace.selected_action).primitive_expansion
        hold = max(1, STEPS_PER_DECISION // len(plan))
        for i, step in enumerate(trace.primitive_steps_executed):
            pressed = set(step.split("+"))
            planned = plan[i // hold]
            if planned == "shoot":
                # Aiming at the locked target stands in for the shot until it is centred.
                assert pressed <= {"shoot", "turn_left", "turn_right", "strafe_left", "strafe_right"}
            elif planned.endswith("_shoot"):
                assert planned[: -len("_shoot")] in pressed, (trace.selected_action, i, step)
            else:
                assert planned in pressed, (trace.selected_action, i, step)


def test_learning_controller_records_every_decision(tmp_path):
    learner = Learner()
    result = _play("health_gathering.cfg", max_ticks=30, log_dir=str(tmp_path / "logs"), learner=learner)
    assert result["transitions"] == result["ticks"] > 0
    assert learner.replay.size == result["ticks"]
    assert all(trace.learning["network_share"] == 0.0 for trace in result["traces"])
    assert sum(learner.action_counts.values()) == result["ticks"]
