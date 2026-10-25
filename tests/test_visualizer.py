"""The HUD and the side panel show the tick's six d1-ultra instances."""

from pathlib import Path

import numpy as np

from system1_doom.configuration import default_configuration
from system1_doom.d1_client import D1UltraClient
from system1_doom.logger import ProposalTrace, TickTrace
from system1_doom.system1 import Pick, System1
from system1_doom.tracing import OutcomeTrace
from system1_doom.visualizer import EpisodeRecorder, instance_rows, render_decision_dashboard, render_hud_frame
from tests.fake_d1 import FakeD1
from tests.test_evidence import golden_inputs


def make_dummy_trace(tick: int = 1, fake: FakeD1 = None) -> TickTrace:
    """A schema-2 trace from one System 1 tick on the golden evidence, answered by the fake."""
    client = D1UltraClient(api_key="liquid_test_key", transport=fake or FakeD1(), max_workers=6)
    s1 = System1(client, pool_size=6)
    try:
        inputs = golden_inputs().model_copy(update={"messages": ()})
        result = s1.tick(default_configuration(), inputs)
    finally:
        s1.shutdown()
        client.shutdown(wait=False)
    return TickTrace(
        timestamp="2026-10-25T15:00:00Z",
        tick=tick,
        episode_id="test",
        configuration_version=1,
        state_hash="abcdef0123456789",
        context_signature=inputs.context,
        state=inputs.state,
        available_actions=inputs.menu_ids(),
        instances=result.instances,
        messages=list(result.messages),
        pick=result.pick,
        executed_action=result.pick.action,
        primitive_steps_executed=["shoot", "shoot", "shoot", "shoot"],
        outcome=OutcomeTrace(reward=14.5),
        reward_outcome=14.5,
        missed=result.missed,
        exploration_level="exploit",
        active_strategy="strat_tactical_combat",
        timing_ms={"total": 812.0, "senses": 520.0, "central": 290.0},
        usage=result.usage(),
    )


def test_instance_rows_name_each_sense_and_the_centrals_pick():
    trace = make_dummy_trace()
    rows = instance_rows(trace)
    assert [r[0] for r in rows] == ["survival", "combat", "navigation", "resource", "goal", "central"]
    assert rows[1][:2] == ("combat", "spoke") and rows[1][3] == 0.9 and "shoot" in rows[1][2]
    assert rows[0][1] == "silent" and rows[-1][:2] == ("central", "top") and rows[-1][2] == "shoot"
    missed = trace.model_copy(update={"pick": Pick(kind="missed"), "executed_action": None, "missed": True})
    assert instance_rows(missed)[-1][1] == "missed"


def test_render_hud_frame_and_save_gif(tmp_path: Path):
    screen = np.zeros((240, 320, 3), dtype=np.uint8)
    screen[:, :, 0] = 60
    trace = make_dummy_trace(1)
    hud_img = render_hud_frame(screen, trace, health=85.0, armor=25.0, ammo=18)
    assert hud_img.size == (1080, 480)

    rec = EpisodeRecorder()
    rec.add_step([screen, screen], trace, health=85.0, armor=25.0, ammo=18)
    gif_path = tmp_path / "test_out.gif"
    rec.save_gif(gif_path, fps=8)
    assert gif_path.is_file() and gif_path.stat().st_size > 500


def test_decision_dashboard_shows_the_instances_and_proposals():
    trace = make_dummy_trace(4, FakeD1().fail("navigation", [0], "raise"))
    assert instance_rows(trace)[2][1] == "missed"
    proposal = ProposalTrace(
        timestamp="2026-10-25T15:00:01Z",
        request_context="test:corridor:need a new strafe",
        raw_proposal="{}",
        parsed_proposal={"id": "evasive_burst_1", "description": "Sidestep, fire, and leave the line of fire."},
        validation_result="valid",
        admission_decision=True,
        admitted_action_id="evasive_burst_1",
        d1_admission_probability=0.81,
    )
    panel = render_decision_dashboard(trace, proposals=[proposal], health=80, armor=10, ammo=20, codex_enabled=True)
    assert panel.size == (560, 760)
    colors = panel.getcolors(maxcolors=50000)
    assert colors is not None and len(colors) > 8
