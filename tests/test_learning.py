from pathlib import Path
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

LEGACY_RUN = Path("/mnt/attach/project-files/runs/deadly_corridor")


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


def _fill(learner: Learner, states, actions, returns) -> None:
    learner.stats.update(returns)
    learner.replay.add(states, actions, returns)


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
    buf.add(states, np.zeros((8, buf.actions.shape[1]), np.float32), np.zeros((8, 5), np.float32))
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
    _fill(learner, states, actions, returns)
    first = learner.train(steps=1)
    later = learner.train(steps=300)
    assert later["combat"] < first["combat"]
    assert later["navigation"] < first["navigation"]

    utils = learner.predict_returns(states[0], np.stack([shoot, forward]))
    assert utils["combat"][0] > utils["combat"][1]
    assert utils["navigation"][1] > utils["navigation"][0]


def test_recorded_episode_moves_into_replay_with_its_tries():
    learner = Learner(LearnerConfig(trust_count=4.0))
    vocab = ActionVocabulary.default()
    state = np.zeros(STATE_DIM, dtype=np.float32)
    for _ in range(4):
        learner.record_step(state, encode_action(vocab.get("shoot")), _fake_result(hits_delta=1), "shoot", "ctx:a")
    assert learner.tried_counts("ctx:a", ["shoot"]) == {"shoot": 0}
    assert learner.end_episode() == 4
    assert learner.replay.size == 4
    assert learner.episodes == 1
    assert learner.pending_steps == 0
    assert not hasattr(learner, "gate") and not hasattr(learner.replay, "gate_mask")

    # How often each action was tried in a situation is shown beside the predictions in the values channel.
    assert learner.tried_counts("ctx:a", ["shoot", "move_forward"]) == {"shoot": 4, "move_forward": 0}
    assert learner.tried_counts("ctx:b", ["shoot"]) == {"shoot": 0}
    assert learner.action_trust("ctx:a", ["shoot"])["shoot"] == pytest.approx(0.5)
    assert learner.network_share == pytest.approx(0.5)


def test_discarded_episode_leaves_no_trace():
    learner = Learner()
    learner.record_step(np.zeros(STATE_DIM, np.float32), np.zeros(12, np.float32), _fake_result(), "shoot", "ctx")
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
        assert loaded.predict_returns(s, a)[name] == pytest.approx(learner.predict_returns(s, a)[name])

    payload = torch.load(path, weights_only=True)
    payload["state_dim"] = STATE_DIM + 1
    torch.save(payload, path)
    with pytest.raises(CheckpointMismatch):
        Learner.load(path)


def _legacy_payload(path: Path) -> None:
    """Rewrite a checkpoint as one from before the gate was removed: gate weights, its config and
    loss, and an Adam state over the value networks' six parameters followed by the gate's six."""
    from torch import nn

    payload = torch.load(path, weights_only=True)
    gate = nn.Sequential(nn.Linear(STATE_DIM, 32), nn.ReLU(), nn.Linear(32, 32), nn.ReLU(), nn.Linear(32, 5))
    payload["gate"] = gate.state_dict()
    payload["config"].update({"gate_hidden": 32, "gate_temperature": 0.5})
    payload["last_losses"]["gate"] = 0.3
    optimizer = payload["optimizer"]
    for index in range(6, 12):
        optimizer["state"][index] = {k: v.clone() if hasattr(v, "clone") else v for k, v in optimizer["state"][0].items()}
    optimizer["param_groups"][0]["params"] = list(range(12))
    torch.save(payload, path)


def test_checkpoints_and_replays_from_before_the_gate_was_removed_still_load(tmp_path):
    rng = np.random.default_rng(4)
    learner = Learner(LearnerConfig(seed=0))
    _fill(learner, rng.random((64, STATE_DIM), dtype=np.float32), rng.random((64, 12), dtype=np.float32), rng.random((64, 5), dtype=np.float32))
    learner.train(steps=3)
    path = tmp_path / "checkpoint.pt"
    learner.save(path)
    _legacy_payload(path)
    replay = tmp_path / "replay.npz"
    np.savez_compressed(
        replay,
        states=learner.replay.states[:64],
        actions=learner.replay.actions[:64],
        returns=learner.replay.returns[:64],
        gate_mask=np.ones((64, 5), np.float32),
    )

    loaded = Learner.load(path)
    assert "gate" not in loaded.last_losses and len(loaded.optimizer.state_dict()["state"]) == 6
    s, a = rng.random(STATE_DIM, dtype=np.float32), rng.random((2, 12), dtype=np.float32)
    assert loaded.predict_returns(s, a)["goal"] == pytest.approx(learner.predict_returns(s, a)["goal"])
    loaded.replay.load(replay)
    assert loaded.replay.size == 64
    assert set(loaded.train(steps=2)) == set(MODULE_NAMES)


@pytest.mark.skipif(not (LEGACY_RUN / "checkpoint.pt").is_file(), reason="the shipped training run is not attached")
def test_the_shipped_training_runs_checkpoints_load():
    for name in ("checkpoint.pt", "best.pt"):
        learner = Learner.load(LEGACY_RUN / name)
        assert learner.episodes > 0 and set(learner.last_losses) <= set(MODULE_NAMES)
    learner.replay.load(LEGACY_RUN / "replay.npz")
    assert learner.replay.size > 0
