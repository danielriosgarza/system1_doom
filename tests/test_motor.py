"""The motor's assistance aims only at targets d1 chose: the chosen enemy, the chosen pickup's bearing."""

import pytest
import vizdoom as vzd

from system1_doom.motor import TacticalMotor, bearing_to

BUTTONS = ["MOVE_LEFT", "MOVE_RIGHT", "ATTACK", "MOVE_FORWARD", "MOVE_BACKWARD", "TURN_LEFT", "TURN_RIGHT"]


class _Label:
    def __init__(self, object_id: int, name: str, x: int, width: int = 20, height: int = 40) -> None:
        self.object_id, self.object_name, self.x, self.width, self.height = object_id, name, x, width, height


class _State:
    screen_buffer = None

    def __init__(self, labels):
        self.labels = labels


class _Game:
    """Just enough of a DoomGame: a pose and the labels in view."""

    def __init__(self, x=0.0, y=0.0, angle=0.0, labels=()):
        self.vars = {vzd.GameVariable.POSITION_X: x, vzd.GameVariable.POSITION_Y: y, vzd.GameVariable.ANGLE: angle}
        self.labels = list(labels)

    def get_game_variable(self, variable):
        return self.vars[variable]

    def get_state(self):
        return _State(self.labels)


def _motor(game) -> TacticalMotor:
    return TacticalMotor(game, BUTTONS, "deadly_corridor.cfg")


@pytest.mark.parametrize(
    "facing, target, expected",
    [(0.0, (100.0, 0.0), 0.0), (0.0, (0.0, 100.0), 90.0), (90.0, (100.0, 0.0), -90.0), (0.0, (-100.0, 0.0), 180.0)],
)
def test_bearing_is_positive_to_the_left(facing, target, expected):
    assert bearing_to(0.0, 0.0, facing, *target) == pytest.approx(expected)


def test_a_pickup_walk_turns_toward_the_chosen_pickup_and_turns_in_place_when_it_lies_behind():
    ahead_left = _motor(_Game(angle=0.0))
    ahead_left.pickup_target = (100.0, 30.0)
    assert ahead_left._assisted_flags("move_forward") == {"MOVE_FORWARD", "TURN_LEFT"}
    straight = _motor(_Game(angle=0.0))
    straight.pickup_target = (100.0, 2.0)
    assert straight._assisted_flags("move_forward") == {"MOVE_FORWARD"}
    behind_right = _motor(_Game(angle=0.0))
    behind_right.pickup_target = (-100.0, -30.0)
    assert behind_right._assisted_flags("move_forward") == {"TURN_RIGHT"}
    no_target = _motor(_Game(angle=0.0))
    assert no_target._assisted_flags("move_forward") == {"MOVE_FORWARD"}


def test_the_aim_follows_only_the_chosen_enemy():
    # Two enemies: id 1 left of centre, id 2 right of centre (screen 320 wide, centre 160).
    labels = [_Label(1, "Zombieman", x=40), _Label(2, "ShotgunGuy", x=250)]
    chosen = _motor(_Game(labels=labels))
    chosen.lock_id = 2
    assert chosen._assisted_flags("shoot") == {"TURN_RIGHT"}
    chosen.lock_id = 1
    assert chosen._assisted_flags("shoot") == {"TURN_LEFT"}
    unchosen = _motor(_Game(labels=labels))
    assert unchosen._assisted_flags("shoot") == {"ATTACK"}
    gone = _motor(_Game(labels=labels))
    gone.lock_id = 7
    assert gone._assisted_flags("strafe_left") == {"MOVE_LEFT"}
