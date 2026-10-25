"""Bundles of episodes d1-ultra played: schema version 2, every file, `--check`, `--schema`, `--index`."""

import json
from pathlib import Path
import shutil

import jsonschema
import pytest

from system1_doom import export
from system1_doom.actions import ActionVocabulary
from system1_doom.history import load_history, rerender_instance
from system1_doom.logger import TRACE_SCHEMA_VERSION, TickTrace
from system1_doom.reflection import load_reflections
from system1_doom.relevance import RelevanceLedger
from tests.fake_d1 import FakeD1, shoot_when_aimed
from tests.test_state_and_actions import make_sample_world_state

RECORDINGS = Path(__file__).resolve().parents[1] / "web" / "public" / "episodes"
INSTANCES = ["survival", "combat", "navigation", "resource", "goal", "central"]


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bundles") / "basic-none-3"
    export.record_bundle(
        scenario="basic.cfg", seed=3, out=out, run_dir=out.parent / "no_run", max_ticks=5,
        transport=FakeD1(shoot_when_aimed), api_key="liquid_test_key",
    )
    return out


def _ticks(bundle: Path) -> list:
    return [json.loads(line) for line in (bundle / "ticks.jsonl").read_text().splitlines()]


def test_export_writes_every_file_and_a_frame_per_tick(bundle):
    meta = json.loads((bundle / "episode.json").read_text())
    ticks = _ticks(bundle)
    assert meta["schema_version"] == 2 == TRACE_SCHEMA_VERSION
    assert meta["decider"] == "d1-ultra" and meta["value_networks"] == "none" and meta["checkpoint"] is None
    assert meta["slow_path"] == "templates" and "brains" not in meta and "model" not in meta and "modules" not in meta
    assert 1 <= len(ticks) == meta["tick_count"] <= 5
    assert {"episode.json", "ticks.jsonl", "history.jsonl", "relevance.json", "proposals.jsonl"} <= set(meta["files"])
    # System 2 is on: its end-of-episode cycle is in the bundle, and its calls are not in the episode's cost.
    assert "reflections.jsonl" in meta["files"] and meta["system2"]["enabled"] and meta["system2"]["cycles"] == 1
    (cycle,) = load_reflections((bundle / "reflections.jsonl").read_text())
    assert cycle.record == "cycle" and cycle.trigger == "episode_end" and cycle.calls == meta["system2"]["calls"] > 0
    for name in meta["files"]:
        assert (bundle / name).is_file(), name
    for tick in ticks:
        assert (bundle / "frames" / f"{tick['tick']:05d}.jpg").is_file()
        assert tick["state"]["tick"] == tick["tick"]
    assert meta["configuration_start"]["version"] == meta["configuration_end"]["version"] == 1
    assert meta["configuration_start"]["senses"]["combat"]["scope"] == ["threats", "outgoing", "vitals", "frame", "projections", "menu"]
    assert meta["cost"]["calls"] == 6 * len(ticks) and meta["cost"]["usd"] > 0 and meta["cost"]["input_tokens"] > 0
    assert meta["misses"] == {"total": 0, "missed_ticks": 0, "by_instance": {}}
    assert set(meta["instances"]) == set(INSTANCES) and meta["instances"]["central"]["calls"] == len(ticks)
    assert meta["result"]["finished_reason"] in ("episode_end", "max_ticks") and meta["config"]["call_budget_sec"] == 5.0
    assert set(meta["actions"]) >= {"shoot", "weave_fire"}
    assert export.check_bundle(bundle) == []


def test_pruned_and_available_actions_partition_the_vocabulary(bundle):
    vocabulary = set(json.loads((bundle / "episode.json").read_text())["actions"])
    for tick in _ticks(bundle):
        available, pruned = set(tick["available_actions"]), set(tick["pruned_actions"])
        assert available.isdisjoint(pruned)
        assert available | pruned == vocabulary
        assert all(reason for reason in tick["pruned_actions"].values())


def test_each_tick_holds_six_instances_their_evidence_and_the_pick(bundle):
    for tick in _ticks(bundle):
        assert list(tick["instances"]) == INSTANCES
        assert tick["executed_action"] == tick["pick"]["action"] and tick["pick"]["kind"] == "top"
        assert tick["configuration_version"] == 1 and tick["exploration_level"] == "exploit"
        combat = tick["instances"]["combat"]
        assert combat["image_ref"] == f"frames/{tick['tick']:05d}.jpg" and (bundle / combat["image_ref"]).is_file()
        assert tick["instances"]["survival"]["image_ref"] is None
        for name, instance in tick["instances"].items():
            assert instance["evidence"] and set(instance["answers"]) == ({"choose"} if name == "central" else {"speak", "action", "reason"})
        outcome = tick["outcome"]
        assert outcome["reward"] == pytest.approx(tick["reward_outcome"], abs=1e-3)
        assert set(outcome["module_rewards"]) == {"survival", "combat", "navigation", "resource", "goal"}
        for removed in ("module_outputs", "arbiter", "arbiter_distribution", "budget_mode", "exploration_state", "used_d1_ultra", "learning", "d1_arbiter_distribution", "steering"):
            assert removed not in tick, removed


def test_the_bundles_history_rerenders_what_each_instance_saw(bundle):
    records = load_history(bundle / "history.jsonl")
    ticks = [TickTrace.model_validate(t) for t in _ticks(bundle)]
    assert [r.tick for r in records] == [t.tick for t in ticks]
    for record, trace in zip(records, ticks):
        for name in INSTANCES:
            assert rerender_instance(record, name).text == trace.instances[name].evidence, (trace.tick, name)
    RelevanceLedger.model_validate_json((bundle / "relevance.json").read_text())


def test_schema_dump_validates_a_recorded_trace(bundle, tmp_path):
    out = tmp_path / "bundle.schema.json"
    assert export.main(["--schema", str(out)]) == 0
    schema = json.loads(out.read_text())
    assert "schema_version 2" in schema["description"]

    def valid(document, name):
        jsonschema.validate(document, {"$defs": schema["$defs"], "$ref": f"#/$defs/{name}"})

    valid(_ticks(bundle)[0], "TickTrace")
    valid(json.loads((bundle / "episode.json").read_text()), "EpisodeMeta")
    valid(json.loads((bundle / "history.jsonl").read_text().splitlines()[0]), "TickRecord")
    valid(json.loads((bundle / "relevance.json").read_text()), "RelevanceLedger")


def test_copied_run_files_validate_against_their_models(tmp_path):
    # Training needs torch; without it train.main exits early and there is nothing to validate.
    pytest.importorskip("torch")
    from system1_doom import train

    run_dir = tmp_path / "run"
    fake = FakeD1(shoot_when_aimed)
    argv = ["--scenario", "basic.cfg", "--max-ticks", "4", "--run-dir", str(run_dir), "--seed", "3", "--train-steps", "2", "--episodes", "2"]
    assert train.main(argv, transport=fake) == 0
    train.evaluate("basic.cfg", train.RunStore(run_dir), episodes=1, max_ticks=3, transport=fake, api_key="liquid_test_key")
    out = tmp_path / "basic-latest-3"
    meta = export.record_bundle(
        scenario="basic.cfg", seed=3, out=out, networks="latest", run_dir=run_dir, max_ticks=3,
        transport=fake, api_key="liquid_test_key",
    )

    assert meta.value_networks == "latest" and meta.checkpoint is not None
    assert {"metrics.jsonl", "evaluation.json", "macros.json", "trust.json"} <= set(meta.files)
    rows = [export.MetricsRow.model_validate_json(line) for line in (out / "metrics.jsonl").read_text().splitlines()]
    assert [row.episode for row in rows] == [1, 2] and all(row.cost_usd > 0 and row.d1_calls > 0 for row in rows)
    evaluation = export.EvaluationSummary.model_validate_json((out / "evaluation.json").read_text())
    assert evaluation.trained_episodes == 2 and evaluation.none is not None and evaluation.latest is not None
    trust = export.TrustFile.model_validate_json((out / "trust.json").read_text())
    assert trust.episodes == 2 and trust.trust_count == 25.0
    assert sum(trust.context_counts.values()) == sum(trust.action_counts.values()) == sum(row.transitions for row in rows)
    assert export.MacroList.validate_json((out / "macros.json").read_text()) == []
    assert "learned from past play" in json.loads((out / "ticks.jsonl").read_text().splitlines()[0])["instances"]["goal"]["evidence"]
    assert export.check_bundle(out) == []
    # The run folder's ledger grew with every episode played there: two trained, one recorded.
    assert RelevanceLedger.model_validate_json((run_dir / "relevance.json").read_text()).episodes == 3

    schema = export.bundle_json_schema()
    jsonschema.validate(json.loads((out / "trust.json").read_text()), {"$defs": schema["$defs"], "$ref": "#/$defs/TrustFile"})
    jsonschema.validate(
        json.loads((out / "evaluation.json").read_text()), {"$defs": schema["$defs"], "$ref": "#/$defs/EvaluationSummary"}
    )


def test_check_validates_the_reflections_and_the_counts_episode_json_gives(bundle, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(bundle, copy)
    (line,) = (copy / "reflections.jsonl").read_text().splitlines()
    schema = export.bundle_json_schema()
    jsonschema.validate(json.loads(line), {"$defs": schema["$defs"], "$ref": "#/$defs/ReflectionTrace"})
    (copy / "reflections.jsonl").write_text(line + "\n" + '{"record": "cycle"}\n')
    problems = export.check_bundle(copy)
    assert len(problems) == 1 and problems[0].startswith("reflections.jsonl line 2")
    (copy / "reflections.jsonl").write_text("")  # valid, but episode.json counts one cycle
    problems = export.check_bundle(copy)
    assert len(problems) == 1 and "does not match reflections.jsonl" in problems[0]


def test_export_without_system2_records_no_reflections(tmp_path, capsys):
    out = tmp_path / "off"
    argv = ["--scenario", "basic.cfg", "--seed", "3", "--max-ticks", "3", "--run-dir", str(tmp_path / "run"), "--out", str(out), "--no-system2"]
    assert export.main(argv, transport=FakeD1(shoot_when_aimed)) == 0
    meta = export.EpisodeMeta.model_validate_json((out / "episode.json").read_text())
    assert meta.system2 is not None and not meta.system2.enabled and meta.system2.cycles == 0
    assert (out / "reflections.jsonl").read_text() == "" and export.check_bundle(out) == []
    assert "configuration version 1 -> 1" in capsys.readouterr().out


def test_exported_episodes_start_from_the_saved_configuration_and_carry_it_on(tmp_path, capsys):
    from system1_doom.configuration import default_configuration

    run = tmp_path / "run"
    run.mkdir()
    saved = run / "configuration.json"
    default_configuration().with_changes(exploration_level="explore").save(saved)
    argv = ["--scenario", "basic.cfg", "--seed", "3", "--max-ticks", "2", "--episodes", "2", "--run-dir", str(run), "--no-system2"]
    assert export.main(argv + ["--out", str(tmp_path / "a")], transport=FakeD1(shoot_when_aimed)) == 0
    assert capsys.readouterr().err.count(f"configuration: {saved} (version 2)") == 2
    metas = [export.EpisodeMeta.model_validate_json((b / "episode.json").read_text()) for b in sorted((tmp_path / "a").iterdir())]
    assert [m.configuration_start.version for m in metas] == [2, 2]
    assert all(m.configuration_start.exploration_level == "explore" for m in metas)
    # --fresh-configuration: the first episode starts from the design's version 1; the next one carries on from it.
    assert export.main(argv + ["--out", str(tmp_path / "b"), "--fresh-configuration"], transport=FakeD1(shoot_when_aimed)) == 0
    err = capsys.readouterr().err
    assert "configuration: the design's version 1" in err and f"configuration: {saved} (version 1)" in err
    metas = [export.EpisodeMeta.model_validate_json((b / "episode.json").read_text()) for b in sorted((tmp_path / "b").iterdir())]
    assert [(m.configuration_start.version, m.configuration_start.exploration_level) for m in metas] == [(1, "exploit"), (1, "exploit")]


def test_a_change_queued_at_an_exported_episodes_end_takes_effect_in_the_next_episode(tmp_path, capsys):
    from tests.fake_d1 import explore_level_system2

    out = tmp_path / "two"
    argv = ["--scenario", "basic.cfg", "--seed", "3", "--max-ticks", "3", "--episodes", "2", "--run-dir", str(tmp_path / "run"),
            "--out", str(out), "--no-slow-path"]
    assert export.main(argv, transport=FakeD1(shoot_when_aimed, system2_policy=explore_level_system2)) == 0
    first, second = sorted(out.iterdir())
    metas = [export.EpisodeMeta.model_validate_json((b / "episode.json").read_text()) for b in (first, second)]
    # Episode 1's end cycle queued the level change; its controller closed before any tick boundary.
    (cycle,) = [r for r in load_reflections((first / "reflections.jsonl").read_text()) if r.record == "cycle"]
    assert cycle.trigger == "episode_end" and cycle.outcome == "queued" and cycle.choice == "level:explore"
    assert metas[0].configuration_end.version == 1
    # Episode 2 restores it: from its first tick it plays at the bumped version, and the trial starts there.
    ticks = [TickTrace.model_validate_json(line) for line in (second / "ticks.jsonl").read_text().splitlines()]
    assert ticks[0].configuration_version == 2 and ticks[0].configuration_changed and all(t.exploration_level == "explore" for t in ticks)
    assert metas[1].configuration_end.version == 2 and metas[1].configuration_end.exploration_level == "explore"
    kinds = [r.kind for r in load_reflections((second / "reflections.jsonl").read_text()) if r.record == "note"]
    assert kinds[:2] == ["restored", "trial_started"] and metas[1].system2.trials_started == 1
    assert export.check_bundle(first) == [] and export.check_bundle(second) == []


def test_index_lists_shippable_schema_2_bundles(bundle):
    entries = export.write_index(bundle.parent)
    assert [e.name for e in entries] == [bundle.name]
    index = json.loads((bundle.parent / "index.json").read_text())
    assert index["schema_version"] == 2 and index["episodes"][0]["value_networks"] == "none"
    # What the app's cards say before a bundle is opened: the kills and the configuration versions.
    meta = export.EpisodeMeta.model_validate_json((bundle / "episode.json").read_text())
    line = index["episodes"][0]
    assert line["kills"] == meta.result.kills and line["configuration_start"] == line["configuration_end"] == 1
    # An index line written before these fields existed still loads.
    old = {k: v for k, v in line.items() if k not in ("kills", "configuration_start", "configuration_end")}
    assert export.BundleIndexEntry.model_validate(old).configuration_start == 1


def test_the_schema_names_every_model_the_app_reads():
    defs = export.bundle_json_schema()["$defs"]
    for name in (
        "EpisodeMeta", "TickTrace", "InstanceResult", "Message", "Pick", "ProposalTrace", "ReflectionTrace",
        "TrialVerdictTrace", "TrialRecord", "TrialTable", "System2Note", "HistoryTestResult", "TestTick", "Metrics",
        "Configuration", "SenseConfig", "Bounds", "RelevanceLedger", "RelevanceCounts", "BundleIndexEntry",
        "TrustFile", "System2EpisodeSummary", "Proposal", "ConfigDiff", "AppliedChange", "Window",
    ):
        assert name in defs, name


def test_an_episode_that_lost_the_connection_is_written_but_not_shippable(tmp_path, capsys):
    fake = FakeD1(shoot_when_aimed).fail("central", [0, 1, 2], "raise")
    out = tmp_path / "eps" / "lost"
    code = export.main(
        ["--scenario", "basic.cfg", "--seed", "3", "--max-ticks", "10", "--run-dir", str(tmp_path / "no_run"), "--out", str(out)],
        transport=fake,
    )
    assert code == 1 and "not shippable" in capsys.readouterr().err
    meta = export.EpisodeMeta.model_validate_json((out / "episode.json").read_text())
    assert meta.result.finished_reason == "connection_lost" and meta.tick_count == 3 and meta.misses.missed_ticks == 3
    assert meta.result.actions == ["missed"] * 3
    problems = export.check_bundle(out)
    assert len(problems) == 1 and "connection_lost" in problems[0]
    assert export.main(["--check", str(out)]) == 1
    assert export.write_index(out.parent) == []


def test_a_bundle_of_another_schema_version_is_reported_and_left_out_of_an_index(bundle, tmp_path):
    old = tmp_path / "eps" / "old"
    shutil.copytree(bundle, old)
    meta = json.loads((old / "episode.json").read_text())
    (old / "episode.json").write_text(json.dumps({**meta, "schema_version": 1}))
    assert export.check_bundle(old) == [f"episode.json: schema_version 1, expected {TRACE_SCHEMA_VERSION}"]
    assert export.write_index(old.parent) == []


def test_export_fails_fast_without_the_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(export, "load_api_key", lambda: None)
    assert export.main(["--scenario", "basic.cfg", "--out", str(tmp_path / "x")]) == 2
    assert "LIQUID_API_KEY" in capsys.readouterr().err and not (tmp_path / "x").exists()
    # --check, --index and --schema read files only and need no key.
    assert export.main(["--schema", str(tmp_path / "s.json")]) == 0


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
