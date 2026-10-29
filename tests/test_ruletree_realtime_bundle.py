"""A real-time recording on ViZDoom with canned answers: the rule-tree folder the website reads, with when each state
was read and its action began, what the helper aimed at and the keys pressed, and the checks a shipped one passes."""

import json

from system1_doom.export import realtime_settings, rule_tree_index_entry
from system1_doom.ruletree.bundle import RuleTreeEpisodeMeta, check_recording, record_realtime_episode
from system1_doom.ruletree.tree import load_tree
from tests.fake_d1 import FakeD1
from tests.ruletree_fixtures import by_text, jev_client, scripted


def test_a_real_time_recording_keeps_the_timing_and_the_helpers_keys_and_passes_its_check(tmp_path):
    fake = FakeD1(scripted(by_text("at least one enemy", "no enemy")), decider="jev")
    out = tmp_path / "realtime-corridor-9"
    meta = record_realtime_episode(load_tree("realtime-5"), 9, out, jev_client(fake, budget=5.0), realtime_settings("5"))
    assert check_recording(out) == []
    assert meta.realtime is not None and meta.realtime.clock == "fixed" and meta.realtime.lag == [5, 5]
    assert meta.realtime.aim == "box" and meta.realtime.fire == "tap-narrow" and meta.realtime.track == "screen"
    decisions = [json.loads(line) for line in (out / "decisions.jsonl").read_text().splitlines()]
    assert len(decisions) == meta.decision_count > 1
    for d in decisions[:-1]:
        assert d["start_tic"] - d["observed_tic"] == 5 and d["pressed"]
    # The keys pressed from one action's start to the next's add up to the tics between them.
    for a, b in zip(decisions, decisions[1:]):
        assert sum(s["tics"] for s in a["pressed"]) == b["start_tic"] - a["start_tic"]
    assert any(d["target"] for d in decisions)
    entry = rule_tree_index_entry(out.name, RuleTreeEpisodeMeta.model_validate_json((out / "episode.json").read_text()))
    assert entry.realtime and entry.tree == "realtime-5"


def test_a_lag_on_the_command_line_is_the_helper_as_it_played_80_of_81():
    assert realtime_settings("wall") == {"lag": None, "track": "screen", "aim": "box", "fire": "tap-narrow", "reflex": 4}
    assert realtime_settings("3-9")["lag"] == (3, 9) and realtime_settings("7")["lag"] == 7
