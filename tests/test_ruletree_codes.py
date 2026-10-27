"""Action codes: a code is held for a whole decision, a sequence divides its 8 tics, a skill's partial action is
finished by the caller's `then`."""

import pytest

from system1_doom.ruletree.codes import COMBOS, TICS, ActionError, buttons, complete, describe, fires, segments


def test_there_are_54_codes_and_a_decision_is_8_tics():
    assert len(COMBOS) == len(set(COMBOS)) == 54
    assert TICS == 8
    assert {"F001", "0000", "BLR1"} <= set(COMBOS)


def test_a_code_alone_is_held_for_the_whole_decision():
    assert segments("F001") == [("F001", 8)]


def test_a_sequence_is_its_segments():
    assert segments("00R0:3+0001:5") == [("00R0", 3), ("0001", 5)]


def test_outside_a_skill_a_sequence_must_add_up_to_8_tics():
    with pytest.raises(ActionError):
        segments("00R0:3")
    with pytest.raises(ActionError):
        segments("00R0:3+0001:6")
    with pytest.raises(ActionError):
        segments("XXXX")
    with pytest.raises(ActionError):
        segments("00R0:0+0001:8")


def test_inside_a_skill_a_partial_action_is_finished_by_the_callers_then():
    assert segments("00R0:3", partial=True) == [("00R0", 3)]
    assert complete("00R0:3", "0001") == "00R0:3+0001:5"
    assert complete("00R0:7", "F000") == "00R0:7+F000:1"
    assert complete("then", "F001") == "F001"
    # A full action inside a skill needs nothing from the caller.
    assert complete("00R0:3+0001:5", "F000") == "00R0:3+0001:5"
    with pytest.raises(ActionError):
        segments("00R0:9", partial=True)


def test_describe_gives_the_words_the_site_shows():
    assert describe("00R0:3+0001:5") == "turn right for 3 tics, then fire for 5 tics"
    assert describe("F001") == "walk forward + fire"
    assert describe("0000") == "stand still"
    assert describe("00L0:5") == "turn left for 5 tics, then the caller's action"
    assert describe({"skill": "aim", "then": "0001"}) == "use skill aim, then fire"
    assert describe("then") == "the caller's action"


def test_buttons_follow_the_scenario_order():
    # MOVE_LEFT, MOVE_RIGHT, ATTACK, MOVE_FORWARD, MOVE_BACKWARD, TURN_LEFT, TURN_RIGHT
    assert buttons("F0R1") == [0, 0, 1, 1, 0, 0, 1]
    assert buttons("BL00") == [1, 0, 0, 0, 1, 0, 0]
    assert buttons("0000") == [0] * 7


def test_fires():
    assert fires("00R0:3+0001:5") and fires("F001")
    assert not fires("F000") and not fires("00R0:3+F000:5")
