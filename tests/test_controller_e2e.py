import json
from pathlib import Path
from typing import Dict
import pytest

from system1_doom.controller import ControllerConfig, DoomDecisionController
from system1_doom.d1_client import load_api_key
from system1_doom.llm_worker import ExpansionRequest
from system1_doom.modules import DecisionInput, DecisionModule
from system1_doom.vizdoom_env import ViZDoomBridge


def test_acceptance_runs_normally_with_llm_disabled_and_traces_every_tick(tmp_path: Path):
    """
    Acceptance Criteria:
    - Doom continues running normally if the LLM is completely disabled;
    - every executed action can be traced to a finite arbitration decision;
    - graceful degradation across full, reduced, and critical budgets.
    """
    log_dir = tmp_path / "logs"
    env = ViZDoomBridge(scenario="basic.cfg", window_visible=False, include_jpeg_frame=False)
    cfg = ControllerConfig(
        execution_mode="async_cached",
        enable_d1_ultra=False,
        enable_slow_llm=False,
        tick_budget_sec=0.03,
        log_dir=str(log_dir),
        deterministic_arbiter=True,
    )
    ctrl = DoomDecisionController(env=env, config=cfg)
    try:
        traces = ctrl.run_ticks(num_ticks=6)
        assert len(traces) == 6
        for t in traces:
            assert t.selected_action in t.available_actions
            assert sum(t.arbiter_distribution.values()) == pytest.approx(1.0, abs=1e-4)
            assert len(t.primitive_steps_executed) >= 1
            assert set(t.module_outputs.keys()) == {"survival", "combat", "navigation", "resource", "goal"}

        # Test critical budget degradation
        trace_crit = ctrl.step(budget_override_sec=0.001)
        assert trace_crit.budget_mode == "critical"
        assert trace_crit.selected_action in trace_crit.available_actions

        # Verify JSONL tick log file was written
        tick_log_lines = (log_dir / "ticks.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(tick_log_lines) == 7
    finally:
        ctrl.close()


def test_acceptance_module_replaceable_and_discovers_retains_reuses_new_macro(tmp_path: Path):
    """
    Acceptance Criteria:
    - module implementations can be replaced independently;
    - LLM output cannot directly execute game actions;
    - new LLM-generated actions must compile into bounded typed procedures before use;
    - the system can discover, test, retain, and later reuse at least one new macro-action
      without modifying the real-time controller code.
    """
    log_dir = tmp_path / "logs_macro"
    env = ViZDoomBridge(scenario="deadly_corridor.cfg", window_visible=False, include_jpeg_frame=False)

    def custom_proposal_generator(req: ExpansionRequest) -> str:
        return json.dumps(
            {
                "id": "corridor_blitz_macro",
                "description": "Strafe left, fire shotgun, advance forward, and strafe right down the corridor",
                "parameters": {"target": "corridor", "duration": 4},
                "preconditions": {"min_ammo": 0, "requires_visible_enemy": False},
                "maximum_duration": 4,
                "termination_condition": "corridor_step_complete",
                "primitive_expansion": ["strafe_left", "shoot", "move_forward", "strafe_right"],
                "strategy_id": "strat_corridor_blitz",
            }
        )

    cfg = ControllerConfig(
        execution_mode="async_cached",
        enable_d1_ultra=False,
        enable_slow_llm=True,
        use_codex_cli=False,
        log_dir=str(log_dir),
        deterministic_arbiter=True,
    )
    ctrl = DoomDecisionController(
        env=env,
        config=cfg,
        custom_llm_generator=custom_proposal_generator,
    )

    # Replace the GoalModule independently with a custom module that strongly favors corridor_blitz_macro once admitted
    class CustomGoalModule(DecisionModule):
        name = "goal"
        question_prompt = "Which action most increases probability of eventual level success?"

        def compute_local_utilities(self, inp: DecisionInput) -> Dict[str, float]:
            return {
                act.id: (10.0 if act.id == "corridor_blitz_macro" else 0.1)
                for act in inp.available_actions
            }

        def check_expansion_needed(self, inp: DecisionInput, uncertainty: float):
            if "corridor_blitz_macro" not in {a.id for a in inp.available_actions}:
                return True, "Need corridor_blitz_macro to clear deadly_corridor."
            return False, None

    ctrl.replace_module("goal", CustomGoalModule(d1_client=ctrl.d1_client))

    try:
        # Tick 1 triggers the expansion request from CustomGoalModule
        t1 = ctrl.step()
        assert "corridor_blitz_macro" not in t1.available_actions

        # Wait briefly for async slow LLM worker to finish and admit proposal on next tick
        import time

        deadline = time.time() + 2.0
        while ctrl.llm_worker.is_busy() and time.time() < deadline:
            time.sleep(0.01)

        # Next ticks drain admitted proposals, retain corridor_blitz_macro in vocabulary + archive, and reuse it
        t2 = ctrl.step()
        t3 = ctrl.step()
        assert "corridor_blitz_macro" in t2.available_actions
        assert "corridor_blitz_macro" in t3.available_actions
        assert t2.selected_action == "corridor_blitz_macro" or t3.selected_action == "corridor_blitz_macro"

        # Check proposal log recorded subsequent performance
        proposal_lines = (log_dir / "proposals.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(proposal_lines) >= 1
        prop_record = json.loads(proposal_lines[-1])
        assert prop_record["admission_decision"] is True
        assert prop_record["admitted_action_id"] == "corridor_blitz_macro"
    finally:
        ctrl.close()


def test_live_vizdoom_with_d1_ultra_sync_and_async_modes(tmp_path: Path):
    """
    Live end-to-end test running ViZDoom (`deadly_corridor.cfg`) with multimodal (vision + state)
    Liquid AI `d1-ultra` decisions in both `sync_d1` and `async_cached` modes.
    """
    api_key = load_api_key()
    assert api_key
    log_dir = tmp_path / "logs_live"
    env = ViZDoomBridge(scenario="deadly_corridor.cfg", window_visible=False, include_jpeg_frame=True)
    cfg = ControllerConfig(
        execution_mode="sync_d1",
        enable_d1_ultra=True,
        enable_slow_llm=False,
        tick_budget_sec=8.0,
        log_dir=str(log_dir),
        deterministic_arbiter=True,
    )
    ctrl = DoomDecisionController(env=env, config=cfg)
    try:
        traces = ctrl.run_ticks(num_ticks=2)
        assert len(traces) == 2
        for tr in traces:
            assert tr.used_d1_ultra is True
            assert tr.selected_action in tr.available_actions
            assert all(m["used_d1_ultra"] for m in tr.module_outputs.values())
    finally:
        ctrl.close()

    # Also verify async_cached mode refreshes d1-ultra in background without blocking ticks
    env_async = ViZDoomBridge(scenario="basic.cfg", window_visible=False, include_jpeg_frame=False)
    cfg_async = ControllerConfig(
        execution_mode="async_cached",
        enable_d1_ultra=True,
        enable_slow_llm=False,
        tick_budget_sec=0.04,
        log_dir=str(tmp_path / "logs_async"),
        deterministic_arbiter=True,
    )
    ctrl_async = DoomDecisionController(env=env_async, config=cfg_async)
    try:
        # First tick triggers non-blocking async d1-ultra submission
        t_first = ctrl_async.step()
        assert t_first.selected_action in t_first.available_actions
        import time

        deadline = time.time() + 5.0
        while ctrl_async.d1_client.call_count < 1 and time.time() < deadline:
            time.sleep(0.05)
        assert ctrl_async.d1_client.call_count >= 1
    finally:
        ctrl_async.close()
