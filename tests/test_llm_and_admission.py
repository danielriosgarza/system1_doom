"""Admission: the bounds (parse, legality, sandbox) first, then the admit instance's own yes or no."""

import json
import time

import pytest

from system1_doom.actions import ActionVocabulary
from system1_doom.admission import ProposalAdmissionPipeline, admit_evidence
from system1_doom.d1_client import D1UltraClient
from system1_doom.llm_worker import ExpansionRequest, SlowLLMWorker
from system1_doom.simulator import BoundedSimulator
from tests.fake_d1 import FakeD1, noul
from tests.test_state_and_actions import make_sample_world_state

GOOD = json.dumps(
    {
        "id": "zigzag_fire",
        "description": "Strafe and fire both ways",
        "preconditions": {"min_ammo": 1},
        "maximum_duration": 4,
        "termination_condition": "sequence_completed",
        "primitive_expansion": ["strafe_left", "shoot", "strafe_right", "shoot"],
        "strategy_id": "strat_zigzag",
    }
)


def _pipeline(fake: FakeD1, budget: float = 2.0):
    vocab = ActionVocabulary.default()
    client = D1UltraClient(api_key="liquid_test_key", transport=fake, max_workers=2)
    return ProposalAdmissionPipeline(vocabulary=vocab, simulator=BoundedSimulator(), d1_client=client, call_budget_sec=budget), vocab


def _answering(p: float):
    def policy(name, payload):
        assert name == "admit"
        return {"admit": noul(p)}

    return policy


def test_the_bounds_reject_before_any_instance_is_asked():
    fake = FakeD1(_answering(0.9))
    pipeline, vocab = _pipeline(fake)
    state = make_sample_world_state(health=40.0, ammo=10, enemies=2, pickups=0)
    assert not pipeline.evaluate_and_admit("just run left and shoot everything!", state).admitted
    illegal = pipeline.evaluate_and_admit(GOOD.replace("strafe_right", "noclip_warp"), state)
    assert not illegal.admitted and [(s.stage, s.passed) for s in illegal.stage_results] == [("parse", True), ("legality", False)]
    unbounded = json.loads(GOOD)
    unbounded.update(maximum_duration=999, primitive_expansion=["turn_left"] * 50)
    assert not pipeline.evaluate_and_admit(json.dumps(unbounded), state).admitted
    builtin = json.loads(GOOD)
    builtin["id"] = "shoot"
    assert not pipeline.evaluate_and_admit(json.dumps(builtin), state).admitted
    assert fake.count("admit") == 0 and vocab.get("zigzag_fire") is None


def test_the_admit_instance_decides_at_its_own_yes():
    state = make_sample_world_state()
    for p, admitted in ((0.5, True), (0.49, False), (0.8, True), (0.1, False)):
        fake = FakeD1(_answering(p))
        pipeline, vocab = _pipeline(fake)
        result = pipeline.evaluate_and_admit(GOOD, state, problem_description="need a way to fire while dodging")
        assert result.admitted is admitted, p
        assert result.d1_admission_probability == p and result.admit_instance.admit == p
        assert result.admit_instance.answers == {"admit": {"type": "noul", "noul": p}}
        stages = [(s.stage, s.passed) for s in result.stage_results]
        assert stages[:3] == [("parse", True), ("legality", True), ("sandbox", True)]
        assert stages[3] == ("d1", admitted)
        # The pipeline never mutates the menu: an admitted macro joins the configuration at a tick boundary.
        assert vocab.get("zigzag_fire") is None
        if admitted:
            assert stages[4] == ("admit", True)
            assert result.admitted_action.id == "zigzag_fire" and result.admitted_strategy.strategy_id == "strat_zigzag"


@pytest.mark.parametrize("fault", ["raise", "timeout"])
def test_a_missed_admit_call_rejects_and_nothing_stands_in(fault):
    fake = FakeD1(_answering(0.9), timeout_overrun=0.05).fail("admit", [0], fault)
    pipeline, _ = _pipeline(fake, budget=0.3)
    result = pipeline.evaluate_and_admit(GOOD, make_sample_world_state())
    assert not result.admitted and result.admit_instance.missed and result.d1_admission_probability is None
    assert result.stage_results[-1].stage == "d1" and not result.stage_results[-1].passed and not result.stage_results[-1].skipped


def test_the_admit_evidence_is_the_proposal_and_its_rough_sandbox_summary():
    fake = FakeD1(_answering(0.7))
    pipeline, _ = _pipeline(fake)
    pipeline.evaluate_and_admit(GOOD, make_sample_world_state(), problem_description="need a dodge")
    (payload,) = fake.payloads("admit")
    state = payload["state"]
    assert state.startswith("[proposal]\nid zigzag_fire: Strafe and fire both ways")
    assert "primitives in order: strafe_left, shoot, strafe_right, shoot" in state
    assert "[sandbox]\na rough projection from a hand-written simulator, not the game" in state
    assert "[request]\nneed a dodge" in state and "[menu]\nthe actions that exist now: " in state
    assert set(payload["questions"]) == {"admit"} and "images" not in payload
    instructions = payload["questions"]["admit"]["instructions"]
    assert "admission instance" in instructions and "only the evidence given" in instructions


def test_admit_evidence_is_deterministic():
    pipeline, vocab = _pipeline(FakeD1(_answering(0.7)))
    state = make_sample_world_state()
    result = pipeline.evaluate_and_admit(GOOD, state)
    ids = [a.id for a in vocab.all_actions()]
    first = admit_evidence(result.admitted_action, result.sandbox_outcome, "x", ids)
    assert first == admit_evidence(result.admitted_action, result.sandbox_outcome, "x", ids)


def test_the_slow_worker_runs_in_the_background_and_hands_back_the_admission():
    fake = FakeD1(_answering(0.8))
    pipeline, vocab = _pipeline(fake)
    worker = SlowLLMWorker(admission_pipeline=pipeline, use_codex_cli=False)
    state = make_sample_world_state(health=30.0, ammo=8, enemies=2, pickups=0)
    request = ExpansionRequest(
        source_module="combat",
        problem_description="need an evasive strafe-and-fire macro",
        world_state=state,
        existing_action_ids=tuple(a.id for a in vocab.all_actions()),
    )
    started = time.perf_counter()
    assert worker.enqueue_request(request) is True
    assert time.perf_counter() - started < 0.05
    assert worker.enqueue_request(request) is False or worker.is_busy() is False
    deadline = time.time() + 5.0
    completed = []
    while time.time() < deadline and not completed:
        completed = worker.drain_completed_results()
        time.sleep(0.01)
    worker.shutdown()
    (result,) = completed
    assert result.admitted and result.source == "template" and result.source_module == "combat"
    assert result.admitted_action_id == "evasive_burst_1" and fake.count("admit") == 1
