import json
import time
import pytest

from system1_doom.actions import ActionVocabulary
from system1_doom.admission import ProposalAdmissionPipeline
from system1_doom.archive import StrategyArchive
from system1_doom.d1_client import D1UltraClient, load_api_key
from system1_doom.llm_worker import ExpansionRequest, SlowLLMWorker
from system1_doom.simulator import BoundedSimulator
from tests.test_state_and_actions import make_sample_world_state


def test_admission_pipeline_rejects_illegal_or_unbounded_proposals():
    vocab = ActionVocabulary.default()
    archive = StrategyArchive()
    sim = BoundedSimulator()
    pipeline = ProposalAdmissionPipeline(
        vocabulary=vocab,
        archive=archive,
        simulator=sim,
        d1_client=D1UltraClient(enabled=False),
    )
    state = make_sample_world_state(health=40.0, ammo=10, enemies=2, pickups=0)

    # 1. Malformed JSON / free-form text must be rejected
    res_bad_json = pipeline.evaluate_and_admit("just run left and shoot everything!", state)
    assert res_bad_json.admitted is False
    assert "parse" in res_bad_json.rejection_reason.lower()

    # 2. Unknown / illegal primitive action must be rejected
    bad_prim_raw = json.dumps(
        {
            "id": "wallhack_teleport",
            "description": "Teleport behind enemy",
            "parameters": {"duration": 2},
            "preconditions": {"min_ammo": 0, "requires_visible_enemy": True},
            "maximum_duration": 2,
            "termination_condition": "duration_elapsed",
            "primitive_expansion": ["noclip_warp", "shoot"],
        }
    )
    res_bad_prim = pipeline.evaluate_and_admit(bad_prim_raw, state)
    assert res_bad_prim.admitted is False
    assert vocab.get("wallhack_teleport") is None

    # 3. Unbounded / excessive duration (> 16) must be rejected
    unbounded_raw = json.dumps(
        {
            "id": "infinite_spin",
            "description": "Spin forever",
            "parameters": {"duration": 999},
            "preconditions": {"min_ammo": 0, "requires_visible_enemy": False},
            "maximum_duration": 999,
            "termination_condition": "never",
            "primitive_expansion": ["turn_left"] * 50,
        }
    )
    res_unbounded = pipeline.evaluate_and_admit(unbounded_raw, state)
    assert res_unbounded.admitted is False
    assert vocab.get("infinite_spin") is None


def test_admission_pipeline_admits_valid_proposal_with_live_d1_ultra_and_sandbox():
    api_key = load_api_key()
    assert api_key
    client = D1UltraClient(api_key=api_key)
    vocab = ActionVocabulary.default()
    archive = StrategyArchive()
    sim = BoundedSimulator()
    pipeline = ProposalAdmissionPipeline(
        vocabulary=vocab,
        archive=archive,
        simulator=sim,
        d1_client=client,
    )
    state = make_sample_world_state(health=35.0, ammo=10, enemies=2, pickups=0)

    valid_raw = json.dumps(
        {
            "id": "sidestep_double_tap",
            "description": "Dodge right to evade incoming fireballs, align aim left, fire a quick shot, and step back to cover",
            "parameters": {"direction": "right", "duration": 4},
            "preconditions": {"min_ammo": 1, "requires_visible_enemy": True},
            "maximum_duration": 4,
            "termination_condition": "enemy_damaged_or_duration_elapsed",
            "primitive_expansion": ["strafe_right", "turn_left", "shoot", "move_backward"],
            "strategy_id": "strat_sidestep_double_tap",
        }
    )
    res = pipeline.evaluate_and_admit(valid_raw, state)
    assert res.admitted is True, f"Expected admission, got rejection: {res.rejection_reason}"
    assert res.used_d1_ultra is True
    assert vocab.get("sidestep_double_tap") is not None
    assert archive.get("strat_sidestep_double_tap") is not None


def test_slow_llm_worker_asynchronous_codex_generation_and_admission():
    vocab = ActionVocabulary.default()
    archive = StrategyArchive()
    sim = BoundedSimulator()
    client = D1UltraClient(api_key=load_api_key())
    pipeline = ProposalAdmissionPipeline(
        vocabulary=vocab,
        archive=archive,
        simulator=sim,
        d1_client=client,
    )
    worker = SlowLLMWorker(admission_pipeline=pipeline, use_codex_cli=True, codex_timeout_sec=25.0)
    state = make_sample_world_state(health=30.0, ammo=8, enemies=2, pickups=0)

    req = ExpansionRequest(
        source_module="combat",
        problem_description="Existing combat macros repeatedly fail against twin Imps in close corridor; need an evasive strafe-and-fire macro.",
        world_state=state,
        existing_action_ids=tuple(a.id for a in vocab.all_actions()),
    )

    # Enqueue must be instantaneous and non-blocking
    t0 = time.perf_counter()
    queued = worker.enqueue_request(req)
    elapsed = time.perf_counter() - t0
    assert queued is True
    assert elapsed < 0.02

    # Wait for background worker to finish processing via Codex CLI (or fallback) and admit into vocabulary
    deadline = time.time() + 30.0
    completed = []
    while time.time() < deadline:
        completed = worker.drain_completed_results()
        if completed:
            break
        time.sleep(0.1)

    worker.shutdown()
    assert len(completed) == 1
    adm_result = completed[0]
    assert adm_result.admitted is True
    assert adm_result.admitted_action_id is not None
    assert vocab.get(adm_result.admitted_action_id) is not None
