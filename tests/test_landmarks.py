"""Remembered pickups: where each lies from the current pose, how reward went with its distance, and walks
that got no closer; enemies keep how many attacks on them in a row hit nothing."""

import math

from system1_doom.actions import ActionVocabulary
from system1_doom.system1 import Targets
from system1_doom.vizdoom_env import ViZDoomBridge


def _vest(env):
    (vest,) = [m for m in env.acquire_world_state().observation.landmarks if m.name == "GreenArmor"]
    return vest


def test_the_vest_is_remembered_and_walking_to_it_is_learned_as_reward_rising_closer():
    vocab = ActionVocabulary.default()
    env = ViZDoomBridge(scenario="deadly_corridor.cfg", seed=3)
    try:
        vest = _vest(env)
        assert vest.in_view and abs(vest.bearing) < 5 and 1200 < vest.distance < 1400 and vest.reward_agreement is None
        for _ in range(4):
            env.execute_action(vocab.get("approach_pickup"), Targets(pickup=vest.landmark_id))
        walked = _vest(env)
        assert walked.distance < vest.distance - 100
        assert walked.approaches_nowhere == 0 and walked.reward_moves >= 3 and walked.reward_agreement > 0.5
        env.execute_action(vocab.get("turn_left"))
        env.execute_action(vocab.get("turn_left"))
        assert _vest(env).bearing < -30, "after turning left the vest lies to the right"
    finally:
        env.close()


def test_a_walk_that_gets_no_closer_is_counted_and_an_unchosen_pickup_is_not():
    vocab = ActionVocabulary.default()
    env = ViZDoomBridge(scenario="deadly_corridor.cfg", seed=3)
    try:
        vest = _vest(env)
        # Facing the corridor's side wall, a walk at a point beyond it gets no closer.
        for _ in range(3):
            env.execute_action(vocab.get("turn_left"))
        env.execute_action(vocab.get("move_forward"))
        pose = env.acquire_world_state().observation.position
        beyond = env._landmark_by_id(vest.landmark_id)
        beyond.x = pose.x + 400.0 * math.cos(math.radians(pose.angle))
        beyond.y = pose.y + 400.0 * math.sin(math.radians(pose.angle))
        bearing = _vest(env).bearing
        env.execute_action(vocab.get("approach_pickup"), Targets(pickup=vest.landmark_id))
        counted = _vest(env).approaches_nowhere
        env.execute_action(vocab.get("approach_pickup"), Targets())
        assert abs(bearing) <= 30 and counted == 1 and _vest(env).approaches_nowhere == 1
    finally:
        env.close()
