"""The check and the gate: the comparisons on what the goal needs, and a proposal checked, gated and committed on
the stand-in corridor."""

import pytest

from system1_doom.ruletree.check import ProposalError, better, check, commit, standing
from system1_doom.ruletree.gate import gate
from system1_doom.ruletree.run import Run
from system1_doom.ruletree.tree import Proposal
from tests.fake_d1 import FakeD1
from tests.ruletree_fixtures import CorridorGame, jev_client, scripted, sees_imp, walk_on_tree


def test_alive_beats_dead_and_the_goal_beats_no_goal():
    assert better((1, 0, 10.0, 300.0), (0, 0, 0.0, 900.0))
    assert not better((0, 0, 0.0, 900.0), (1, 0, 10.0, 300.0))
    assert better((1, 1, 5.0, 1200.0), (1, 0, 90.0, 1300.0))


def test_if_both_die_the_rule_fails():
    assert not better((0, 0, 0.0, 700.0), (0, 0, 0.0, 690.0))
    assert not better((0, 0, 0.0, 690.0), (0, 0, 0.0, 690.0))


def test_otherwise_no_worse_on_health_and_furthest_point_and_better_on_one():
    assert better((1, 0, 50.0, 400.0), (1, 0, 50.0, 390.0))
    assert better((1, 0, 60.0, 400.0), (1, 0, 50.0, 400.0))
    assert not better((1, 0, 60.0, 380.0), (1, 0, 50.0, 400.0))
    assert not better((1, 0, 50.0, 400.0), (1, 0, 50.0, 400.0))


def test_standing_reads_a_game_at_a_decision():
    trace = [
        {"died": False, "finished": False, "events": [], "health_after": 90.0, "max_x": 50},
        {"died": False, "finished": False, "events": [], "health_after": 70.0, "max_x": 100},
        {"died": True, "finished": True, "events": ["died"], "health_after": 0.0, "max_x": 120},
    ]
    assert standing(trace, 1) == (1, 0, 70.0, 100.0)
    assert standing(trace, 2) == standing(trace, 30) == (0, 0, 0.0, 120.0)
    won = trace[:2] + [{"died": False, "finished": True, "events": [], "health_after": 70.0, "max_x": 400}]
    assert standing(won, 2) == (1, 1, 70.0, 400.0)


@pytest.fixture
def run(tmp_path):
    r = Run(tmp_path / "run", client=jev_client(FakeD1(scripted(sees_imp), decider="jev")), workers=2, game_factory=CorridorGame)
    r.start(walk_on_tree())
    yield r
    r.close()


def test_a_rule_is_checked_gated_and_committed(run):
    tree = run.tree()
    (lost,) = run.play_many([9])
    assert lost["event"] == "died" and lost["decisions"] == 5
    k = next(r["i"] for r in run.game_record(lost["game"])["trace"] if "- Imp" in r["text"])
    proposal = Proposal(trace=lost["game"], frame=k, condition="An enemy is in view.", action="0001", why="stand and shoot")
    result = check(run, tree, proposal, name="p1")
    report = result.report
    assert report.passed and report.rule == "r1" and report.attach_to == "root"
    assert report.sees["route"] == "r1"
    assert report.avoids["old_tree"][0] == 0 and report.avoids["new_tree"][:2] == [1, 1]

    g = gate(run, tree, result.tree, [9, 10])
    assert (g.current, g.with_rule, g.of, g.passed) == (0, 2, 2, True)

    new = commit(result)
    (c,) = new.nodes["r1"].cornerstones
    assert c.seed == 9 and c.decision == k and c.expect == "r1" and c.standing[:2] == (1, 1)
    run.save(new)
    assert run.tree().frame_b64(run.tree().nodes["r1"].cornerstones[0]) == result.frame_b64


def test_a_rule_jev_does_not_see_fails_and_bad_proposals_are_refused(run):
    tree = run.tree()
    (lost,) = run.play_many([9])
    k = 3
    unseen = check(run, tree, Proposal(trace=lost["game"], frame=k, condition="The level is dark.", action="0001"), name="p2")
    assert not unseen.report.passed and not unseen.report.sees["pass"]
    assert "sees: FAIL" in unseen.report.summary()
    with pytest.raises(ProposalError):
        check(run, tree, Proposal(trace=lost["game"], frame=99, condition="c", action="0001"))
    with pytest.raises(ProposalError):
        check(run, tree, Proposal(trace="s9-77", frame=1, condition="c", action="0001"))
    with pytest.raises(ProposalError):
        check(run, tree, Proposal(trace=lost["game"], frame=1, condition="c", action="00R0:3"))
