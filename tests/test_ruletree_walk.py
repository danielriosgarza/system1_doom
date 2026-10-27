"""The walk: Jev's answers lead down the tree; a focus is picked before the children are asked; a skill call goes
on in the skill and the caller's `then` completes it; a failed call is a miss and the node reached acts."""

from system1_doom.ruletree.walk import NONE, AnswerBook, Jev, decide, random_code
from tests.fake_d1 import FakeD1
from tests.ruletree_fixtures import ONE_THREAT, STATE, by_text, general_tree, jev_client, scripted, screen_b64

SCREEN = screen_b64()


def _jev(answer, book=None):
    fake = FakeD1(scripted(answer), decider="jev")
    return fake, Jev(jev_client(fake), book)


def test_the_walk_stops_at_none_and_the_root_walks_randomly():
    fake, jev = _jev(lambda kind, options, state: NONE if "none" in options else "i0")
    d = decide(general_tree(), jev, STATE, SCREEN, seed=9, step=4)
    assert d.node == "root" and d.action == random_code(9, 4) and not d.missed
    assert [s.kind for s in d.steps] == ["rule"] and d.steps[0].pick == NONE
    assert d.steps[0].options == {"r1": "The threats list shows at least one enemy.", "r3": "The threats list says no enemy is visible.",
                                  "none": "None of these is true right now."}
    assert d.route == "root"


def test_a_focus_is_picked_and_shown_before_the_children_are_asked():
    # Focus on the second threat (i1); the threat is close, so r2 does not hold, and it is 4 degrees left.
    def answer(kind, options, state):
        if kind == "focus":
            return "i1"
        return by_text("at least one enemy", "between 3 and 7 degrees to the left")(kind, options, state)

    fake, jev = _jev(answer)
    d = decide(general_tree(), jev, STATE, SCREEN, seed=9, step=4)
    kinds = [(s.kind, s.node) for s in d.steps]
    assert kinds == [("rule", "root"), ("focus", "r1"), ("rule", "r1"), ("skill", "r1"), ("rule", "aim")]
    focus = d.steps[1]
    assert focus.pick == "Zombieman at distance 520, 4 deg left, 3 px wide"
    assert focus.focus_line == "Zombieman at distance 520, 4 deg left, 3 px wide (from the threats list)"
    asked = [p["state"] for name, p in fake.calls]
    assert "[focus]" not in asked[0] and "[focus]" not in asked[1]
    assert "\n\n[focus]\nZombieman at distance 520, 4 deg left, 3 px wide (from the threats list)\n\n[screen image]\n" in asked[2]
    # In the skill, the band turns left for 3 tics and the caller's `then` (fire) does the other 5.
    assert d.node == "r7" and d.action == "00L0:3+0001:5" and d.route == "r1/aim/r7"


def test_a_single_focus_option_needs_no_question():
    fake, jev = _jev(by_text("at least one enemy", "more than 12 degrees to the right"))
    d = decide(general_tree(), jev, ONE_THREAT, SCREEN, seed=9, step=0)
    focus = d.steps[1]
    assert focus.kind == "focus" and focus.answer is None
    assert focus.focus_line == "ShotgunGuy at distance 300, 10 deg right, 8 px wide (from the threats list)"
    assert fake.count("focus") == 0
    assert d.action == "00R0:7+0001:1"


def test_a_skill_with_no_band_true_plays_the_callers_then():
    fake, jev = _jev(by_text("at least one enemy", "more than 400 units"))
    d = decide(general_tree(), jev, ONE_THREAT, SCREEN, seed=9, step=0)
    assert d.node == "aim" and d.action == "F001" and d.route == "r1/r2/aim"


def test_a_failed_call_is_a_miss_and_the_node_reached_acts():
    answer = by_text("at least one enemy", "more than 12 degrees to the right")
    fake = FakeD1(scripted(answer), decider="jev").fail("rule", [2], "raise")
    jev = Jev(jev_client(fake))
    d = decide(general_tree(), jev, ONE_THREAT, SCREEN, seed=9, step=0)
    # Calls: root (0), r1 (1), then aim (2) fails: the walk is in the skill, which plays the caller's `then`.
    assert d.missed and d.node == "aim" and d.action == "0001"
    assert d.steps[-1].answer.miss == "error"

    fake = FakeD1(scripted(answer), decider="jev").fail("rule", [1], "off_menu")
    d = decide(general_tree(), Jev(jev_client(fake)), ONE_THREAT, SCREEN, seed=9, step=0)
    # r1's question is answered off the menu: r1 acts, and its skill call without the skill is its `then`.
    assert d.missed and d.node == "r1" and d.action == "0001" and d.steps[-1].answer.miss == "off_menu"

    fake = FakeD1(scripted(answer), decider="jev").fail("rule", [0], "timeout")
    d = decide(general_tree(), Jev(jev_client(fake, budget=0.2)), ONE_THREAT, SCREEN, seed=9, step=3)
    assert d.missed and d.node == "root" and d.action == random_code(9, 3)


def test_answers_are_kept_and_reused(tmp_path):
    answer = by_text("at least one enemy", "more than 12 degrees to the right")
    book = AnswerBook(tmp_path, "s9-00.json", read=False)
    fake, jev = _jev(answer, book)
    first = decide(general_tree(), jev, STATE, SCREEN, seed=9, step=0)
    book.save()
    calls = len(fake.calls)
    assert calls == 4 and first.calls == 4 and first.cost > 0

    # A check reads every recorded answer: the same state is answered from the book, without a call.
    fake2, jev2 = _jev(lambda kind, options, state: NONE if "none" in options else "i0", AnswerBook(tmp_path))
    again = decide(general_tree(), jev2, STATE, SCREEN, seed=9, step=0)
    assert len(fake2.calls) == 0 and again.action == first.action and again.calls == 0
    assert all(s.answer.cached for s in again.steps if s.answer)


def test_asking_ahead_walks_the_same_with_fewer_requests():
    """The questions about one state go in one request; the walk, its picks and its record are the same."""
    def answer(kind, options, state):
        if kind == "focus":
            return "i1"
        return by_text("at least one enemy", "between 3 and 7 degrees to the left")(kind, options, state)

    one_by_one, jev = _jev(answer)
    plain = decide(general_tree(), jev, STATE, SCREEN, seed=9, step=4)
    together, jev_ahead = _jev(answer)
    jev_ahead.ahead = True
    ahead = decide(general_tree(), jev_ahead, STATE, SCREEN, seed=9, step=4)
    assert (ahead.action, ahead.node, ahead.route) == (plain.action, plain.node, plain.route)
    assert [(s.kind, s.node, s.pick, s.focus_line) for s in ahead.steps] == [(s.kind, s.node, s.pick, s.focus_line) for s in plain.steps]
    # Four questions one by one; ahead, the root and r1's focus about the state, then r1 and the aim skill about the
    # state with its focus line: two requests.
    assert len(one_by_one.calls) == 4 and len(together.calls) == 2
    assert [sorted(p["questions"]) for _, p in together.calls] == [["focus.1", "rule"], ["rule", "rule.1"]]
    answers = [s.answer for s in ahead.steps if s.answer]
    assert all(a.batch == 2 and not a.cached for a in answers) and ahead.calls == 4
    # A model's answers are kept as in play: a check replays them from the book.
    assert all(jev_ahead.book.get(k) is not None for k in [jev_ahead.key("rule", STATE, SCREEN, "Which of these is true right now?",
                                                                         plain.steps[0].options)])
