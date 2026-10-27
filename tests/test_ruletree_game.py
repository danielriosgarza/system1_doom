"""The game on ViZDoom with canned answers: decisions are 8 tics, a replayed prefix gives the same game, stalls and
deaths are detected, and the state shows the two representation fixes."""

import ast
import math
from pathlib import Path

import pytest

from system1_doom.ruletree.game import Game, outcome, play
from system1_doom.ruletree.tree import Proposal, RuleNode, RuleTree, with_rule
from system1_doom.ruletree.walk import Jev
from tests.fake_d1 import FakeD1
from tests.ruletree_fixtures import by_text, jev_client, scripted

SRC = Path(__file__).resolve().parents[1] / "src" / "system1_doom" / "ruletree"


def _always(code: str) -> RuleTree:
    """A tree with one rule that always holds and plays `code`."""
    root = RuleNode(id="root", parent=None, condition=None, action="random", children=[])
    tree = RuleTree(name="always", writer="test", nodes={"root": root})
    tree, _ = with_rule(tree, Proposal(trace="t", frame=0, condition="The game is running.", action=code), attach_to="root")
    return tree


def _jev():
    return Jev(jev_client(FakeD1(scripted(by_text("The game is running.")), decider="jev")))


@pytest.fixture(scope="module")
def game():
    g = Game()
    yield g
    g.close()


def test_each_decision_is_8_tics_and_the_rule_reached_plays(game):
    trace = play(game, _always("0001"), _jev(), seed=9, stop_after=4, stop_on_event=False)
    # The episode clock starts at 1.
    assert len(trace) == 5 and game.g.get_episode_time() == 1 + 8 * 5
    assert all(r["node"] == "r1" and r["code"] == "0001" and r["route"] == "r1" for r in trace)
    assert trace[0]["steps"][0]["kind"] == "rule" and trace[0]["steps"][0]["pick"] == "r1"
    assert "[goal]\nYou are the player in Doom's Deadly Corridor." in trace[0]["text"] and trace[0]["frame"]


def test_standing_in_the_corridor_dies(game):
    trace = play(game, _always("0000"), _jev(), seed=9)
    assert outcome(trace) == "died" and trace[-1]["died"] and trace[-1]["health_after"] == 0


def test_no_progress_over_24_decisions_is_a_stall(game):
    game.reset(9)
    rec = {"died": False, "finished": False}
    game.max_x = [100.0] * 24
    assert game.events(rec) == []
    game.max_x = [100.0] * 24 + [147.0]
    assert game.events(rec) == ["stalled"]
    game.max_x = [100.0] * 24 + [148.0]
    assert game.events(rec) == []


def test_a_replayed_prefix_is_the_same_game_and_asks_nothing(game):
    first = play(game, _always("F001"), _jev(), seed=11, stop_after=9, stop_on_event=False)
    prefix = [r["code"] for r in first[:10]]
    fake = FakeD1(scripted(by_text("never")), decider="jev")
    again = play(game, _always("0000"), Jev(jev_client(fake)), seed=11, prefix=prefix, stop_after=9, stop_on_event=False)
    assert [(r["x"], r["y"], r["health_after"]) for r in again] == [(r["x"], r["y"], r["health_after"]) for r in first]
    assert [r["text"] for r in again] == [r["text"] for r in first]
    assert all(r["node"] == "replay" for r in again) and fake.calls == []


def test_the_outgoing_channel_counts_decisions_of_fruitless_firing(game):
    trace = play(game, _always("B001"), _jev(), seed=9, stop_after=8, stop_on_event=False)
    lines = [r["text"].split("[outgoing]\n", 1)[1].split("\n", 1)[0] for r in trace]
    assert not any("hit nothing" in line for line in lines[:2])
    assert lines[2].endswith("; the last 2 decisions in which you fired hit nothing")
    assert lines[8].endswith("; the last 8 decisions in which you fired hit nothing")


def test_threat_angles_are_true_angles(game):
    game.reset(9)
    text, _ = game.observe()
    obs = game.bridge.acquire_world_state().observation
    half = obs.screen_width / 2
    assert obs.visible_enemies
    for e in obs.visible_enemies:
        true = math.degrees(math.atan((half - e.screen_x) / half))
        linear = (half - e.screen_x) / half * 45.0
        assert abs(e.angle_offset - true) <= 0.05 and abs(true) > abs(linear) + 2
        side = "left" if true > 0 else "right"
        assert f"- {e.name} at distance {round(e.distance)}, {round(abs(true))} deg {side}" in text


def test_keys_are_pressed_only_by_the_games_step():
    pressing = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("make_action", "set_action", "advance_action"):
                pressing.append(path.name)
    assert pressing and set(pressing) == {"game.py"}


def test_keeping_the_screen_plays_the_same_game(game):
    """A recording holds each segment's keys one tic at a time to keep the last screen; the game is the same."""
    tree, seen = _always("00R0:3+F001:5"), []
    for g in (game, Game(keep_screen=True)):
        trace = play(g, tree, _jev(), 9, stop_after=30, keep_frames=False)
        seen.append([(r["health_after"], r["reward"], r.get("x"), r.get("y"), r.get("angle")) for r in trace])
    assert seen[0] == seen[1] and len(seen[0]) > 1
    assert g.last_screen is not None and game.last_screen is None
    g.close()
