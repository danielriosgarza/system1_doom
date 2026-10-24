from pathlib import Path
import numpy as np

from system1_doom.logger import ProposalTrace, TickTrace
from system1_doom.visualizer import EpisodeRecorder, render_decision_dashboard, render_hud_frame


def make_dummy_trace(tick: int = 1) -> TickTrace:
    return TickTrace(
        timestamp="2026-10-23T15:00:00Z",
        tick=tick,
        state_hash="abcdef0123456789",
        context_signature="hp:healthy|ammo:stocked|enemies:2:mid|dmg:clear|pickup:pickup_visible",
        budget_mode="full",
        available_actions=["circle_strafe_left", "peek_and_fire", "shoot", "move_forward"],
        module_outputs={
            "survival": {"top_action": "circle_strafe_left", "confidence": 0.82, "uncertainty": 0.18, "used_d1_ultra": True, "probabilities": {"circle_strafe_left": 0.6}},
            "combat": {"top_action": "peek_and_fire", "confidence": 0.77, "uncertainty": 0.23, "used_d1_ultra": True, "probabilities": {"peek_and_fire": 0.55}},
            "navigation": {"top_action": "move_forward", "confidence": 0.64, "uncertainty": 0.36, "used_d1_ultra": True, "probabilities": {"move_forward": 0.5}},
            "resource": {"top_action": "move_forward", "confidence": 0.51, "uncertainty": 0.49, "used_d1_ultra": True, "probabilities": {"move_forward": 0.4}},
            "goal": {"top_action": "circle_strafe_left", "confidence": 0.73, "uncertainty": 0.27, "used_d1_ultra": True, "probabilities": {"circle_strafe_left": 0.52}},
        },
        projection_results_used={
            "circle_strafe_left": {"expected_value": 1.85, "expected_damage_taken": 2.1, "expected_damage_dealt": 24.0, "survival_probability": 0.92}
        },
        arbiter_distribution={
            "circle_strafe_left": 0.54,
            "peek_and_fire": 0.26,
            "shoot": 0.12,
            "move_forward": 0.08,
        },
        selected_action="circle_strafe_left",
        primitive_steps_executed=["strafe_left", "turn_right", "shoot", "strafe_left"],
        exploration_state={"exploration_pressure": 0.22, "temperature": 0.32, "recent_failures": 0},
        active_strategy="strat_tactical_combat",
        reward_outcome=14.5,
        used_d1_ultra=True,
    )


def test_render_hud_frame_and_save_gif(tmp_path: Path):
    screen = np.zeros((240, 320, 3), dtype=np.uint8)
    screen[:, :, 0] = 60
    trace = make_dummy_trace(1)
    hud_img = render_hud_frame(screen, trace, health=85.0, armor=25.0, ammo=18)
    assert hud_img.width >= 800
    assert hud_img.height >= 400

    rec = EpisodeRecorder()
    rec.add_step([screen, screen], trace, health=85.0, armor=25.0, ammo=18)
    gif_path = tmp_path / "test_out.gif"
    rec.save_gif(gif_path, fps=8)
    assert gif_path.is_file()
    assert gif_path.stat().st_size > 500


def test_decision_dashboard_shows_d1_and_codex_sections():
    trace = make_dummy_trace(4)
    trace = trace.model_copy(
        update={
            "d1_arbiter_distribution": {"circle_strafe_left": 0.62, "shoot": 0.38},
            "module_outputs": {
                **trace.module_outputs,
                "combat": {
                    **trace.module_outputs["combat"],
                    "d1_top_action": "peek_and_fire",
                    "d1_probabilities": {"peek_and_fire": 0.71, "shoot": 0.29},
                    "request_action_expansion": True,
                },
            },
        }
    )
    proposal = ProposalTrace(
        timestamp="2026-10-23T15:00:01Z",
        request_context="combat:corridor:need a new strafe",
        raw_proposal="{}",
        parsed_proposal={"id": "evasive_burst_1", "description": "Sidestep, fire, and leave the line of fire."},
        validation_result="valid",
        admission_decision=True,
        admitted_action_id="evasive_burst_1",
        d1_admission_probability=0.81,
    )
    panel = render_decision_dashboard(
        trace,
        proposals=[proposal],
        health=80,
        armor=10,
        ammo=20,
        d1_enabled=True,
        codex_enabled=True,
        codex_busy=False,
    )
    assert panel.size == (560, 760)
    colors = panel.getcolors(maxcolors=50000)
    assert colors is not None and len(colors) > 8
