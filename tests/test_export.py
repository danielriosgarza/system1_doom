import json
from pathlib import Path

import jsonschema
import pytest

from system1_doom import export
from system1_doom.actions import ActionVocabulary
from system1_doom.admission import ProposalAdmissionPipeline
from system1_doom.archive import StrategyArchive
from system1_doom.logger import TickTrace
from system1_doom.simulator import BoundedSimulator
from tests.test_state_and_actions import make_sample_world_state
from tests.test_visualizer import make_dummy_trace


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bundles") / "basic-heuristics-3"
    export.record_bundle(
        scenario="basic.cfg", seed=3, out=out, run_dir=out.parent / "no_run", max_ticks=5, deterministic=True
    )
    return out


def _ticks(bundle: Path) -> list:
    return [json.loads(line) for line in (bundle / "ticks.jsonl").read_text().splitlines()]


def test_export_writes_every_file_and_a_frame_per_tick(bundle):
    meta = json.loads((bundle / "episode.json").read_text())
    ticks = _ticks(bundle)
    assert meta["schema_version"] == 1 and meta["model"] == "heuristics" and meta["checkpoint"] is None
    assert meta["brains"] == {"heuristics": True, "learned_networks": False, "d1_ultra": False, "slow_path": "templates"}
    assert 1 <= len(ticks) == meta["tick_count"] <= 5
    for name in meta["files"]:
        assert (bundle / name).is_file(), name
    for tick in ticks:
        assert (bundle / "frames" / f"{tick['tick']:05d}.jpg").is_file()
        assert tick["state"]["tick"] == tick["tick"]
    assert set(meta["actions"]) >= {"shoot", "weave_fire"} and set(meta["modules"]) == set(ticks[0]["module_outputs"])
    assert export.check_bundle(bundle) == []


def test_pruned_and_available_actions_partition_the_vocabulary(bundle):
    vocabulary = set(json.loads((bundle / "episode.json").read_text())["actions"])
    for tick in _ticks(bundle):
        available, pruned = set(tick["available_actions"]), set(tick["pruned_actions"])
        assert available.isdisjoint(pruned)
        assert available | pruned == vocabulary
        assert all(reason for reason in tick["pruned_actions"].values())


def test_arbiter_breakdown_adds_up_to_each_score(bundle):
    for tick in _ticks(bundle):
        arbiter = tick["arbiter"]
        assert set(arbiter["action_scores"]) == set(tick["available_actions"])
        for action_id, parts in arbiter["component_breakdown"].items():
            assert parts["total_score"] == pytest.approx(arbiter["action_scores"][action_id], abs=1e-3)
            total = (
                parts["expected_value"]
                + parts["exploration_bonus"]
                + parts["novelty_bonus"]
                - parts["risk_penalty"]
                - parts["execution_cost"]
            )
            assert total == pytest.approx(parts["total_score"], abs=1e-3)
        if arbiter["pick_rule"] == "greedy":
            assert tick["selected_action"] == max(arbiter["action_scores"], key=arbiter["action_scores"].get)


def test_module_anatomy_and_outcome_are_recorded(bundle):
    for tick in _ticks(bundle):
        for module in tick["module_outputs"].values():
            # Heuristics only: no learned utilities, so the blend is the heuristic itself.
            assert module["utility_learned"] == {} and module["trust"] == {}
            assert module["utility_blended"] == module["utility_heuristic"]
            assert set(module["probabilities"]) == set(tick["available_actions"])
            assert set(module["memory"]) == {"consecutive_damage_ticks", "repeated_failures", "consecutive_stalls", "plateau_ticks"}
        outcome = tick["outcome"]
        assert outcome["reward"] == pytest.approx(tick["reward_outcome"], abs=1e-3)
        assert set(outcome["module_rewards"]) == {"survival", "combat", "navigation", "resource", "goal"}
        assert outcome["module_rewards"]["goal"] == pytest.approx(outcome["reward"], abs=1e-3)
        terms = tick["exploration_state"]["terms"]
        assert {"uncertainty", "failures", "plateau", "novelty", "progress_damper", "risk_damper", "winning_damper"} <= set(terms)
        assert tick["steering"]["active_after"] == tick["active_strategy"]


def test_schema_dump_validates_a_recorded_trace(bundle, tmp_path):
    out = tmp_path / "bundle.schema.json"
    assert export.main(["--schema", str(out)]) == 0
    schema = json.loads(out.read_text())
    trace = _ticks(bundle)[0]
    jsonschema.validate(trace, {"$defs": schema["$defs"], "$ref": "#/$defs/TickTrace"})
    meta = json.loads((bundle / "episode.json").read_text())
    jsonschema.validate(meta, {"$defs": schema["$defs"], "$ref": "#/$defs/EpisodeMeta"})


def test_index_lists_bundles(bundle):
    entries = export.write_index(bundle.parent)
    assert [e.name for e in entries] == [bundle.name]
    assert json.loads((bundle.parent / "index.json").read_text())["episodes"][0]["model"] == "heuristics"


def test_traces_written_before_the_anatomy_fields_still_parse():
    legacy = json.loads(make_dummy_trace(2).model_dump_json())
    for key in ("state", "pruned_actions", "arbiter", "projection_chain", "steering", "outcome", "slow_path_request", "budget_sec", "timing_ms"):
        legacy.pop(key)
    trace = TickTrace.model_validate(legacy)
    assert trace.state is None and trace.pruned_actions == {}
    assert trace.module_outputs["combat"]["top_action"] == "peek_and_fire"


def test_failing_condition_names_the_precondition_is_satisfied_rejects():
    vocabulary = ActionVocabulary.default()
    for state in (
        make_sample_world_state(),
        make_sample_world_state(health=20.0, ammo=0, enemies=2, pickups=0),
        make_sample_world_state(enemies=0, pickups=0),
    ):
        for action in vocabulary.all_actions():
            failing = action.preconditions.failing_condition(state)
            assert (failing is None) == action.preconditions.is_satisfied(state), (action.id, failing)


def test_admission_records_each_stage():
    vocabulary = ActionVocabulary.default()
    pipeline = ProposalAdmissionPipeline(vocabulary=vocabulary, archive=StrategyArchive(), simulator=BoundedSimulator())
    state = make_sample_world_state()
    good = json.dumps(
        {
            "id": "zigzag_fire",
            "description": "Strafe and fire both ways",
            "maximum_duration": 4,
            "termination_condition": "sequence_completed",
            "primitive_expansion": ["strafe_left", "shoot", "strafe_right", "shoot"],
        }
    )
    admitted = pipeline.evaluate_and_admit(good, state)
    assert admitted.admitted
    assert [(s.stage, s.passed, s.skipped) for s in admitted.stage_results] == [
        ("parse", True, False),
        ("legality", True, False),
        ("sandbox", True, False),
        ("d1", True, True),
        ("admit", True, False),
    ]
    rejected = pipeline.evaluate_and_admit(good.replace("strafe_right", "noclip"), state)
    assert not rejected.admitted
    assert [(s.stage, s.passed) for s in rejected.stage_results] == [("parse", True), ("legality", False)]
