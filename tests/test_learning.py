from types import SimpleNamespace

import numpy as np
import pytest
import torch

from system1_doom.actions import ActionVocabulary
from system1_doom.features import STATE_DIM, encode_action
from system1_doom.learning import (
    CheckpointMismatch,
    Learner,
    LearnerConfig,
    MODULE_NAMES,
    ReplayBuffer,
    RunningStats,
    module_rewards,
    n_step_returns,
)


def _fake_result(**overrides):
    base = dict(
        damage_taken=0.0,
        died=False,
        hits_delta=0.0,
        kills_delta=0.0,
        new_cells=0,
        health_gain=0.0,
        armor_gain=0.0,
        ammo_gain=0.0,
        reward=0.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _fill(learner: Learner, states, actions, returns, mask) -> None:
    learner.stats.update(returns)
    learner.replay.add(states, actions, returns, mask)


def test_n_step_returns_discount_and_truncate_at_episode_end():
    rewards = np.ones((3, 1), dtype=np.float32)
    returns = n_step_returns(rewards, gamma=0.5, n=2)
    assert returns[:, 0].tolist() == pytest.approx([1.5, 1.5, 1.0])


def test_module_rewards_follow_each_modules_signal():
    rewards = module_rewards(
        _fake_result(damage_taken=25.0, died=True, hits_delta=2, kills_delta=1, new_cells=1, health_gain=25.0, ammo_gain=10.0, reward=7.5)
    )
    assert rewards.tolist() == pytest.approx([-4.0, 3.0, 1.0, 2.0, 7.5])


def test_running_stats_match_numpy():
    data = np.random.default_rng(0).normal(3.0, 2.0, size=(100, 5))
    stats = RunningStats(5)
    stats.update(data[:30])
    stats.update(data[30:])
    assert stats.mean == pytest.approx(data.mean(axis=0))
    assert stats.std == pytest.approx(data.std(axis=0, ddof=1))


def test_replay_buffer_is_bounded_and_round_trips(tmp_path):
    buf = ReplayBuffer(capacity=5)
    states = np.zeros((8, buf.states.shape[1]), dtype=np.float32)
    states[:, 0] = np.arange(8)
    buf.add(states, np.zeros((8, buf.actions.shape[1]), np.float32), np.zeros((8, 5), np.float32), np.zeros((8, 5), np.float32))
    assert buf.size == 5
    assert sorted(buf.states[:, 0].tolist()) == [3, 4, 5, 6, 7]

    path = tmp_path / "replay.npz"
    buf.save(path)
    restored = ReplayBuffer(capacity=5)
    restored.load(path)
    assert restored.size == 5
    assert restored.states[:5, 0].tolist() == [3, 4, 5, 6, 7]


def test_each_module_network_learns_which_action_pays_off_for_it():
    vocab = ActionVocabulary.default()
    shoot, forward = encode_action(vocab.get("shoot")), encode_action(vocab.get("move_forward"))
    rng = np.random.default_rng(1)
    n = 600
    states = rng.random((n, STATE_DIM), dtype=np.float32)
    is_shoot = np.arange(n) % 2 == 1
    actions = np.where(is_shoot[:, None], shoot, forward).astype(np.float32)
    returns = np.zeros((n, 5), dtype=np.float32)
    returns[:, MODULE_NAMES.index("combat")] = is_shoot
    returns[:, MODULE_NAMES.index("navigation")] = ~is_shoot

    learner = Learner(LearnerConfig(seed=0, batch_size=128))
    _fill(learner, states, actions, returns, np.zeros((n, 5), np.float32))
    first = learner.train(steps=1)
    later = learner.train(steps=300)
    assert later["combat"] < first["combat"]
    assert later["navigation"] < first["navigation"]

    utils = learner.module_utilities(states[0], np.stack([shoot, forward]))
    assert utils["combat"][0] > utils["combat"][1]
    assert utils["navigation"][1] > utils["navigation"][0]


def test_gate_learns_to_trust_the_module_whose_advice_paid_off():
    rng = np.random.default_rng(2)
    n = 400
    states = rng.random((n, STATE_DIM), dtype=np.float32)
    actions = np.zeros((n, 12), dtype=np.float32)
    returns = np.zeros((n, 5), dtype=np.float32)
    mask = np.zeros((n, 5), dtype=np.float32)
    followed_combat = np.arange(n) % 2 == 0
    returns[:, MODULE_NAMES.index("goal")] = np.where(followed_combat, 1.0, -1.0)
    mask[followed_combat, MODULE_NAMES.index("combat")] = 1.0
    mask[~followed_combat, MODULE_NAMES.index("navigation")] = 1.0

    learner = Learner(LearnerConfig(seed=0, batch_size=128))
    _fill(learner, states, actions, returns, mask)
    learner.train(steps=300)
    weights = learner.gate_weights(states[0])
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["combat"] > weights["navigation"]


def test_recorded_episode_moves_into_replay_with_gate_credit_and_trust():
    learner = Learner(LearnerConfig(trust_count=4.0))
    vocab = ActionVocabulary.default()
    state = np.zeros(STATE_DIM, dtype=np.float32)
    for _ in range(4):
        learner.record_step(
            state,
            encode_action(vocab.get("shoot")),
            _fake_result(hits_delta=1),
            {"combat": "shoot", "goal": "move_forward"},
            "shoot",
            "ctx:a",
        )
    assert learner.action_trust("ctx:a", ["shoot"]) == {"shoot": 0.0}
    assert learner.end_episode() == 4
    assert learner.replay.size == 4
    assert learner.episodes == 1
    assert learner.replay.gate_mask[0].tolist() == [0.0, 1.0, 0.0, 0.0, 0.0]
    assert learner.pending_steps == 0

    # Networks earn a say only for actions actually tried in that situation.
    trust = learner.action_trust("ctx:a", ["shoot", "move_forward"])
    assert trust["shoot"] == pytest.approx(0.5)
    assert trust["move_forward"] == 0.0
    assert learner.action_trust("ctx:b", ["shoot"])["shoot"] == 0.0
    assert learner.gate_trust("ctx:a") == pytest.approx(0.5)
    assert learner.network_share == pytest.approx(0.5)


def test_discarded_episode_leaves_no_trace():
    learner = Learner()
    learner.record_step(np.zeros(STATE_DIM, np.float32), np.zeros(12, np.float32), _fake_result(), {}, "shoot", "ctx")
    learner.discard_episode()
    assert learner.pending_steps == 0
    assert learner.end_episode() == 0
    assert learner.replay.size == 0 and learner.action_counts == {}


def test_checkpoint_round_trip_overrides_and_mismatch(tmp_path):
    rng = np.random.default_rng(3)
    learner = Learner(LearnerConfig(seed=0))
    _fill(
        learner,
        rng.random((64, STATE_DIM), dtype=np.float32),
        rng.random((64, 12), dtype=np.float32),
        rng.random((64, 5), dtype=np.float32),
        np.ones((64, 5), np.float32),
    )
    learner.transitions_seen = 64
    learner.episodes = 3
    learner.action_counts = {"ctx|shoot": 7}
    learner.context_counts = {"ctx": 7}
    learner.train(steps=5)
    path = tmp_path / "checkpoint.pt"
    learner.save(path)

    loaded = Learner.load(path, overrides={"trust_count": 50.0, "hidden": 8})
    assert loaded.episodes == 3 and loaded.transitions_seen == 64 and loaded.updates == 5
    assert loaded.action_counts == {"ctx|shoot": 7} and loaded.context_counts == {"ctx": 7}
    assert loaded.config.trust_count == 50.0
    assert loaded.config.hidden == learner.config.hidden
    s, a = rng.random(STATE_DIM, dtype=np.float32), rng.random((3, 12), dtype=np.float32)
    for name in MODULE_NAMES:
        assert loaded.module_utilities(s, a)[name] == pytest.approx(learner.module_utilities(s, a)[name])

    payload = torch.load(path, weights_only=True)
    payload["state_dim"] = STATE_DIM + 1
    torch.save(payload, path)
    with pytest.raises(CheckpointMismatch):
        Learner.load(path)
