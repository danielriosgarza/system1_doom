"""Rule-tree recordings: every decision with its walk and frame, the check, the index beside the senses recordings,
the schema, and the recordings the site ships."""

import json
from pathlib import Path
import shutil

import jsonschema
import pytest

from system1_doom import export
from system1_doom.ruletree.bundle import RuleTreeDecision, RuleTreeEpisodeMeta, check_recording
from system1_doom.ruletree.tree import ROOT, load_tree
from tests.fake_d1 import FakeD1
from tests.ruletree_fixtures import by_text, scripted

RECORDINGS = Path(__file__).resolve().parents[1] / "web" / "public" / "episodes"
# Jev for the real corridor: an enemy in the threats list makes r1 true, the first item is the focus, and no rule
# below holds, so the walk aims with the skill's `then` (fire) and otherwise plays the root's random code.
ANSWERS = by_text("The threats list shows at least one enemy.")


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    out = tmp_path_factory.mktemp("rule-tree") / "rules-corridor-9"
    fake = FakeD1(scripted(ANSWERS), decider="jev")
    assert export.main(["--solution", "rule-tree", "--seed", "9", "--out", str(out)], transport=fake) == 0
    return out, fake


def _decisions(bundle: Path) -> list:
    return [RuleTreeDecision.model_validate_json(line) for line in (bundle / "decisions.jsonl").read_text().splitlines()]


def test_a_recording_holds_every_decision_with_its_walk_and_its_screen(recorded):
    out, fake = recorded
    meta = RuleTreeEpisodeMeta.model_validate_json((out / "episode.json").read_text())
    decisions = _decisions(out)
    assert meta.solution == "rule-tree" and meta.decider == "jev" and meta.schema_version == 2
    assert meta.tree == "general-11" and meta.tree_writer and meta.rules == 11 and meta.seed == 9
    assert meta.name == "rules-corridor-9" and meta.title == "deadly corridor, rule tree general-11, seed 9"
    assert len(decisions) == meta.decision_count == meta.result.decisions > 0
    assert [d.decision for d in decisions] == list(range(len(decisions)))
    assert meta.calls == sum(d.calls for d in decisions) == len(fake.requests) and meta.misses == 0
    assert set(meta.files) == {"decisions.jsonl", "tree.json", "build.jsonl"}
    assert (out / "cornerstones").is_dir() and meta.frames.end_frame == "frames/end.jpg" and (out / "frames" / "end.jpg").is_file()
    for d in decisions:
        assert (out / d.frame).is_file() and d.state_text.startswith("[goal]\n")
        assert sum(s.tics for s in d.segments) == 8 and d.action_words
    # The walk as Jev answered it: the root's question, the focus, the skill, and the random code when none held.
    walked = [d for d in decisions if any(s.kind == "skill" for s in d.steps)]
    assert walked, "no decision saw an enemy"
    kinds = [s.kind for s in walked[0].steps]
    assert kinds[:2] == ["rule", "focus"] and "skill" in kinds and walked[0].action.endswith("0001")
    assert walked[0].steps[0].node == ROOT and walked[0].steps[0].pick == "r1"
    assert all(d.node == ROOT for d in decisions if d.steps[0].pick == "none")
    last = decisions[-1]
    assert last.finished and meta.result.outcome in ("cleared", "died", "timed out")
    assert meta.result.died == last.died and meta.result.cleared == last.cleared
    assert check_recording(out) == [] and export.check_bundle(out) == [] and export.main(["--check", str(out)]) == 0


def test_the_check_finds_an_action_the_walk_did_not_give_and_a_missing_frame(recorded, tmp_path):
    out, _ = recorded
    bad = tmp_path / "bad"
    shutil.copytree(out, bad)
    lines = (bad / "decisions.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    played = first["action"]
    first["action"] = "B000" if played != "B000" else "F000"
    (bad / "decisions.jsonl").write_text("\n".join([json.dumps(first)] + lines[1:]) + "\n")
    (bad / "frames" / "00001.jpg").unlink()
    problems = check_recording(bad)
    assert f"decision 0: played {first['action']}, but {first['node']} gives {played}" in problems
    assert "decision 1: missing frame frames/00001.jpg" in problems


def test_the_schema_validates_a_recording(recorded):
    out, _ = recorded
    defs = export.bundle_json_schema()["$defs"]

    def valid(instance, name):
        jsonschema.validate(instance, {"$defs": defs, "$ref": f"#/$defs/{name}"})

    valid(json.loads((out / "episode.json").read_text()), "RuleTreeEpisodeMeta")
    for line in (out / "decisions.jsonl").read_text().splitlines():
        valid(json.loads(line), "RuleTreeDecision")
    valid(json.loads((out / "tree.json").read_text()), "RuleTree")
    assert load_tree(out).name == "general-11"


def test_the_index_lists_rule_tree_recordings_after_the_senses_and_central(recorded, tmp_path):
    out, _ = recorded
    episodes = tmp_path / "episodes"
    shutil.copytree(out, episodes / out.name)
    senses = min(
        (p.parent for p in RECORDINGS.glob("*/episode.json") if "solution" not in json.loads(p.read_text())),
        key=lambda p: sum(f.stat().st_size for f in p.rglob("*")),
    )
    shutil.copytree(senses, episodes / senses.name)
    entries = export.write_index(episodes)
    assert [e.name for e in entries] == [senses.name, out.name]
    assert [e.solution for e in entries] == ["senses-and-central", "rule-tree"] and entries[1].tree == "general-11"
    meta = RuleTreeEpisodeMeta.model_validate_json((out / "episode.json").read_text())
    assert entries[1].ticks == meta.decision_count and entries[1].decider == "jev" and entries[1].recorded_at == meta.recorded_at
    # An index line written before there were two solutions is senses and central.
    line = json.loads((episodes / "index.json").read_text())["episodes"][0]
    old = {k: v for k, v in line.items() if k not in ("solution", "tree")}
    assert export.BundleIndexEntry.model_validate(old).solution == "senses-and-central"


def test_recording_a_rule_tree_needs_the_corridor_a_known_tree_and_an_empty_folder(recorded, tmp_path, capsys):
    out, _ = recorded
    fake = FakeD1(scripted(ANSWERS), decider="jev")
    assert export.main(["--solution", "rule-tree", "--scenario", "basic.cfg"], transport=fake) == 2
    assert "plays deadly_corridor.cfg only" in capsys.readouterr().err
    assert export.main(["--solution", "rule-tree", "--tree", "no-such-tree", "--out", str(tmp_path / "x")], transport=fake) == 2
    assert "no tree at 'no-such-tree'" in capsys.readouterr().err
    assert export.main(["--solution", "rule-tree", "--out", str(out)], transport=fake) == 2
    assert "is not empty" in capsys.readouterr().err and not fake.requests


SHIPPED = sorted(
    p.parent for p in RECORDINGS.glob("*/episode.json") if json.loads(p.read_text()).get("solution") == "rule-tree"
)


def test_a_local_model_records_the_same_way_and_names_itself(tmp_path, monkeypatch):
    """--tree-decider laya: the same recording, played by Laya on this machine with no key, and named so."""
    monkeypatch.delenv("LAYA_API_KEY", raising=False)
    monkeypatch.setattr("system1_doom.export.load_api_key", lambda decider: None)
    out = tmp_path / "local-corridor-9"
    fake = FakeD1(scripted(ANSWERS), decider="laya")
    args = ["--solution", "rule-tree", "--seed", "9", "--out", str(out), "--tree-decider", "laya", "--tree-model", "ruletree-kev-v1"]
    assert export.main(args, transport=fake) == 0
    meta = RuleTreeEpisodeMeta.model_validate_json((out / "episode.json").read_text())
    assert (meta.decider, meta.model, meta.models) == ("laya", "ruletree-kev-v1", {"laya-rl-agent": meta.calls})
    assert meta.cost == 0 and meta.misses == 0 and check_recording(out) == []
    assert all(p["model"] == "ruletree-kev-v1" and "assets" not in p for _, p in fake.calls)
    assert export.rule_tree_index_entry(out.name, meta).decider == "laya"


@pytest.mark.skipif(not SHIPPED, reason="no shipped rule-tree recordings")
@pytest.mark.parametrize("shipped", SHIPPED, ids=[p.name for p in SHIPPED])
def test_every_shipped_rule_tree_recording_is_valid_and_listed(shipped):
    assert export.check_bundle(shipped) == []
    meta = RuleTreeEpisodeMeta.model_validate_json((shipped / "episode.json").read_text())
    assert meta.name == shipped.name and meta.misses == 0
    listed = json.loads((RECORDINGS / "index.json").read_text())["episodes"]
    assert export.rule_tree_index_entry(shipped.name, meta).model_dump() in listed
