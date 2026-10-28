"""Real-time play on ViZDoom with canned answers: a lag of 0 is play() exactly, a lag shifts every action by its tics,
a longer lag spaces the decisions and fills the gap, and on the wall clock the game keeps time while the walk runs."""

import time

import pytest

from system1_doom.ruletree.codes import segments
from system1_doom.ruletree.game import Game, play
from system1_doom.ruletree.realtime import (TIC_RATE, Helper, Plan, drawn_lag, filled, tracked, held_turning, outcome_of, per_tic, play_realtime, run_length,
                                         shifted, summary, tracking, turned)
from system1_doom.ruletree.walk import Jev
from tests.fake_d1 import FakeD1
from tests.ruletree_fixtures import by_text, general_tree, jev_client, scripted
from tests.test_ruletree_game import _always, _jev


@pytest.fixture(scope="module")
def game():
    g = Game()
    yield g
    g.close()


def _codes(record, start, end):
    """The codes the windows say were pressed from tic `start` to `end`."""
    tics = [c for w in record["windows"] for c, n in segments(w["code"], partial=True) for _ in range(n)]
    return tics[start:end]


def test_codes_by_tic_and_back():
    assert per_tic("00R0:3+F001:5") == ["00R0"] * 3 + ["F001"] * 5
    assert run_length(per_tic("00R0:3+F001:5")) == "00R0:3+F001:5"
    assert run_length(["F001"] * 8) == "F001" and run_length(["F001"] * 3) == "F001:3"
    assert filled("F0R1", "hold") == "F0R1" and filled("F0R1", "idle") == "0000" and filled("F0R1", "steady") == "F001"


def test_no_lag_is_the_paused_game(game):
    tree = _always("00R0:3+F001:5")
    paused = play(game, tree, _jev(), 9, stop_after=20, keep_frames=False, stop_on_event=False)
    live = play_realtime(game, tree, _jev(), 9, lag=0, stop_on_event=False, max_tics=8 * 21)
    keys = ("health_after", "reward", "x", "y", "angle", "kills")
    assert [tuple(r.get(k) for k in keys) for r in paused] == [tuple(w.get(k) for k in keys) for w in live["windows"]]
    assert len(paused) > 5 and [d["observed"] for d in live["decisions"]] == [8 * i for i in range(len(paused))]
    assert all(d["lag"] == 0 and d["cut"] == 0 and d["filled"] == 0 for d in live["decisions"][:-1])


def test_a_short_lag_plays_every_action_in_full_that_many_tics_late(game):
    live = play_realtime(game, _always("00R0:3+F001:5"), _jev(), 9, lag=5, stop_on_event=False, max_tics=8 * 6)
    d = live["decisions"]
    assert [x["observed"] for x in d] == [0, 8, 16, 24, 32, 40] and [x["start"] for x in d] == [5, 13, 21, 29, 37, 45]
    assert all(x["played"] == 8 for x in d[:-1])
    # Nothing is pressed until the first answer is in; then each window is the end of one action and the start of the next.
    assert live["windows"][0]["code"] == "0000:5+00R0:3"
    assert live["windows"][1]["code"] == "F001:5+00R0:3"


def test_a_long_lag_spaces_the_decisions_and_fills_the_gap(game):
    for fill in ("hold", "idle", "steady"):
        live = play_realtime(game, _always("0001:3+F0R1:5"), _jev(), 9, lag=12, fill=fill, stop_on_event=False, max_tics=8 * 7)
        d = live["decisions"]
        assert [x["observed"] for x in d] == [0, 12, 24, 36] and [x["start"] for x in d] == [12, 24, 36, 48]
        assert all(x["played"] == 12 and x["filled"] == 4 for x in d[:-1]) and d[-1]["played"] == 8
        fill_code = {"hold": "F0R1", "idle": "0000", "steady": "F001"}[fill]
        assert _codes(live, 20, 24) == [fill_code] * 4


def test_the_wall_clock_keeps_game_time_while_the_walk_runs(game):
    def slow(name, payload):
        time.sleep(0.1)
        return scripted(by_text("The game is running."))(name, payload)

    jev = Jev(jev_client(FakeD1(slow, decider="jev")))
    t0 = time.perf_counter()
    live = play_realtime(game, _always("B001"), jev, 9, lag=None, stop_on_event=False, max_tics=8 * 10)
    elapsed = time.perf_counter() - t0
    assert abs(elapsed - live["tics"] / TIC_RATE) < 0.15
    lags = [d["lag"] for d in live["decisions"]]
    # A walk of one question at 0.1 s is 4 tics; an answer is used at the first tic after it is in.
    assert lags and all(3 <= x <= 6 for x in lags)
    s = summary(live)
    assert s["decisions"] == len(lags) and s["event"] == outcome_of(live) and s["lag_median"] == sorted(lags)[len(lags) // 2]


def test_doom_turns_slowly_for_five_tics_then_twice_as_fast():
    assert turned(["00R0"] * 3) == pytest.approx(-3 * 1.7578, abs=1e-3)
    assert turned(["00L0"] * 7) == pytest.approx(5 * 1.7578 + 2 * 3.5156, abs=1e-3)
    assert turned(["00L0"] * 2, held=5) == pytest.approx(2 * 3.5156, abs=1e-3)
    assert turned(["00L0", "0001", "00L0"]) == pytest.approx(2 * 1.7578, abs=1e-3)
    assert held_turning(["00L0", "0001", "00R0", "F0R1"]) == 2


def test_predicting_shifts_the_angles_of_what_is_seen_by_the_turn_to_come():
    text = ("[threats]\n1 enemy visible, nearest first:\n- Zombieman at distance 130, 10 deg left, size 41x104 px\n\n"
            "[landmarks]\n- GreenArmor (armor): 1328 away, straight ahead, in view\n\n[position]\nx 39, y -16, facing 300 deg")
    out = shifted(text, 6.0)  # the view will have turned 6 degrees left
    assert "Zombieman at distance 130, 4 deg left" in out and "1328 away, 6 deg right, in view" in out
    assert out.endswith("facing 300 deg") and shifted(text, 0.2) == text
    assert "10 deg left" in shifted(text, 0.0) and "straight ahead" in shifted(text.replace("10 deg left", "6 deg left"), 6.0)


def test_sequential_asks_once_the_last_action_has_played(game):
    live = play_realtime(game, _always("00R0:3+F001:5"), _jev(), 9, lag=5, cadence="sequential", fill="idle",
                         stop_on_event=False, max_tics=8 * 7)
    d = live["decisions"]
    assert [x["observed"] for x in d] == [0, 13, 26, 39] and [x["start"] for x in d] == [5, 18, 31, 44]
    assert all(x["played"] == 13 and x["filled"] == 5 for x in d[:-1])
    assert _codes(live, 13, 18) == ["0000"] * 5


def test_no_lag_with_either_cure_is_the_paused_game(game):
    tree = _always("00R0:3+F001:5")
    paused = play(game, tree, _jev(), 9, stop_after=20, keep_frames=False, stop_on_event=False)
    keys = ("health_after", "reward", "x", "y", "angle")
    for kw in ({"cadence": "sequential"}, {"predict": True}):
        live = play_realtime(game, tree, _jev(), 9, lag=0, stop_on_event=False, max_tics=8 * 21, **kw)
        assert [tuple(r.get(k) for k in keys) for r in paused] == [tuple(w.get(k) for k in keys) for w in live["windows"]]


def test_predicting_reads_the_turn_still_to_come(game):
    live = play_realtime(game, _always("00R0:3+F001:5"), _jev(), 9, lag=7, predict=True, stop_on_event=False, max_tics=8 * 4)
    # At tic 8 the action started at tic 7 has 2 of its 3 right-turn tics still to play before the next starts at 15.
    assert "predicted_turn" not in live["decisions"][0] or live["decisions"][0]["predicted_turn"] == 0
    assert live["decisions"][1]["predicted_turn"] == pytest.approx(-2 * 1.76, abs=0.01)


def test_a_tracked_action_turns_while_the_focus_is_off_and_does_its_then_once_aimed():
    assert tracking("0001", 10.0) == "00L0" and tracking("F001", -4.0) == "00R0"
    assert tracking("0001", 2.9) == "0001" and tracking("F000", None) == "F000"


@pytest.mark.parametrize("track", ["screen", "engine"])
def test_tracking_turns_toward_the_focus_whatever_band_the_tree_read(game, track):
    # The scripted answers always say "more than 12 degrees to the right"; the reflex turns toward the enemy instead.
    jev = Jev(jev_client(FakeD1(scripted(by_text("at least one enemy", "more than 12 degrees to the right")), decider="jev")))
    live = play_realtime(game, general_tree(), jev, 9, lag=0, track=track, stop_on_event=False, max_tics=8 * 2)
    d = live["decisions"][0]
    assert d["route"] == "r1/aim/r6" and d["code"] == "00R0:7+0001:1" and d["target"][0] == "enemy"
    focus = next(s["pick"] for s in d["steps"] if s["kind"] == "focus")
    toward = "00L0" if "deg left" in focus else "00R0"
    assert live["windows"][0]["code"].startswith(toward)
    assert "0001" in live["windows"][0]["code"] + live["windows"][1]["code"]


def test_a_lag_range_draws_each_decisions_lag_and_a_replay_draws_the_same(game):
    draws = [drawn_lag(7, 52, 9, i) for i in range(200)]
    assert all(7 <= x <= 52 for x in draws) and {7, 52} <= set(draws) and draws == [drawn_lag(7, 52, 9, i) for i in range(200)]
    live = play_realtime(game, _always("B001"), _jev(), 9, lag=(7, 52), stop_on_event=False, max_tics=8 * 30)
    assert [d["lag"] for d in live["decisions"]] == draws[: len(live["decisions"])]
    with pytest.raises(ValueError):
        play_realtime(game, _always("F001"), _jev(), 9, lag=(9, 7))


class _Seen:
    """A stand-in for the game as the helper sees it: the labels on screen and the facing, tic by tic."""

    def __init__(self):
        self.sight, self.facing = {}, 0.0

    def on_screen(self):
        return dict(self.sight)

    def var(self, name):
        assert name == "ANGLE"
        return self.facing


def test_the_fair_helper_sees_late_counts_its_own_turning_and_remembers_where_an_enemy_went():
    seen = _Seen()
    helper = Helper(seen, reflex=2)
    seen.sight = {7: ("ShotgunGuy", 10.0)}
    helper.look()
    assert helper.bearing(("enemy", 7)) == pytest.approx(10.0)
    # The player turns 4 degrees left and the enemy steps 6 to the left: the helper still sees him as two tics ago,
    # less its own turn.
    seen.facing, seen.sight = 4.0, {7: ("ShotgunGuy", 12.0)}
    helper.look()
    assert helper.bearing(("enemy", 7)) == pytest.approx(6.0)
    helper.look()
    helper.look()
    assert helper.bearing(("enemy", 7)) == pytest.approx(12.0)
    # Out of view: where he was last seen.
    seen.sight = {}
    for _ in range(3):
        helper.look()
    seen.facing = 10.0
    assert helper.bearing(("enemy", 7)) == pytest.approx(6.0)
    # Dead: gone. Never seen: nothing to turn toward.
    seen.sight = {7: ("DeadShotgunGuy", 0.0)}
    for _ in range(3):
        helper.look()
    assert helper.bearing(("enemy", 7)) is None and helper.bearing(("enemy", 99)) is None


def test_once_the_focus_is_dead_a_rule_with_a_follow_up_walks_on_toward_the_goal():
    plan = Plan(per_tic("00L0:5+0001:3"), 0, {}, ("enemy", 7), "F001")
    bearings = {("enemy", 7): 10.0, ("point", (900.0, 0.0)): -5.0}
    look = bearings.get
    assert tracked(plan, look, ("point", (900.0, 0.0)), lambda target: False) == "00L0"
    assert tracked(plan, look, ("point", (900.0, 0.0)), lambda target: True) == "00R0"
    bearings[("point", (900.0, 0.0))] = 1.0
    assert tracked(plan, look, ("point", (900.0, 0.0)), lambda target: True) == "F001"
    assert tracked(plan, look, None, lambda target: True) == "F001"
    # Without a follow-up the rule's own code goes on.
    assert tracked(Plan(per_tic("0001"), 0, {}, ("enemy", 7)), look, None, lambda target: True) == "00L0"
