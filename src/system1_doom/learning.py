"""The five value networks: evidence learned from past play, never a decision.

Each network (survival, combat, navigation, resource, goal) scores (state, action) pairs against
its own reward signal: the n-step discounted return of what followed the action. Their predictions,
with how often each action was tried in the situation, are rendered in the `values` evidence channel
(design spec, sections 3 and 6); no prediction is multiplied into a choice. Training runs between
episodes on a bounded replay buffer of d1-played experience, so play only ever performs fixed-size
forward passes.

The arbiter gate network of earlier versions is gone (the relevance ledger replaced it). Checkpoints
and replay files written with it still load: the gate's weights, its optimizer state and the replay's
gate mask are ignored.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import torch
from torch import nn

# module_rewards and n_step_returns live with the torch-free encodings, so traces and the relevance
# ledger can use them without importing torch.
from system1_doom.features import ACTION_DIM, MODULE_NAMES, STATE_DIM, module_rewards, n_step_returns

CHECKPOINT_FORMAT = 1
ARCHITECTURE_FIELDS = ("hidden",)
# Checkpoints written before the gate was removed hold these; loading ignores them.
LEGACY_GATE_KEYS = ("gate",)
__all__ = ["CheckpointMismatch", "Learner", "LearnerConfig", "ReplayBuffer", "RunningStats", "n_step_returns"]


class CheckpointMismatch(ValueError):
    """Raised when a checkpoint was produced with incompatible feature sizes or modules."""


@dataclass(frozen=True)
class LearnerConfig:
    gamma: float = 0.9
    n_step: int = 8
    hidden: int = 64
    lr: float = 1e-3
    batch_size: int = 256
    train_steps: int = 200
    replay_capacity: int = 100_000
    trust_count: float = 25.0
    seed: int = 0


class RunningStats:
    """Per-column running mean and variance (Chan et al. parallel update)."""

    def __init__(self, width: int) -> None:
        self.count = 0.0
        self.mean = np.zeros(width, dtype=np.float64)
        self.m2 = np.zeros(width, dtype=np.float64)

    def update(self, batch: np.ndarray) -> None:
        if batch.shape[0] == 0:
            return
        b_count = float(batch.shape[0])
        b_mean = batch.mean(axis=0)
        b_m2 = ((batch - b_mean) ** 2).sum(axis=0)
        total = self.count + b_count
        delta = b_mean - self.mean
        self.mean = self.mean + delta * (b_count / total)
        self.m2 = self.m2 + b_m2 + delta**2 * (self.count * b_count / total)
        self.count = total

    @property
    def std(self) -> np.ndarray:
        if self.count < 2:
            return np.ones_like(self.mean)
        return np.maximum(np.sqrt(self.m2 / (self.count - 1)), 1e-3)

    def normalize(self, values: np.ndarray) -> np.ndarray:
        return ((values - self.mean) / self.std).astype(np.float32)

    def to_dict(self) -> Dict[str, Any]:
        return {"count": self.count, "mean": self.mean.tolist(), "m2": self.m2.tolist()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunningStats":
        stats = cls(len(data["mean"]))
        stats.count = float(data["count"])
        stats.mean = np.asarray(data["mean"], dtype=np.float64)
        stats.m2 = np.asarray(data["m2"], dtype=np.float64)
        return stats


class ReplayBuffer:
    """Bounded ring buffer of (state, action, per-network return)."""

    def __init__(self, capacity: int, state_dim: int = STATE_DIM, action_dim: int = ACTION_DIM) -> None:
        self.capacity = max(1, capacity)
        width = len(MODULE_NAMES)
        self.states = np.zeros((self.capacity, state_dim), dtype=np.float32)
        self.actions = np.zeros((self.capacity, action_dim), dtype=np.float32)
        self.returns = np.zeros((self.capacity, width), dtype=np.float32)
        self.size = 0
        self._next = 0

    def add(self, states: np.ndarray, actions: np.ndarray, returns: np.ndarray) -> None:
        for row in range(states.shape[0]):
            i = self._next
            self.states[i] = states[row]
            self.actions[i] = actions[row]
            self.returns[i] = returns[row]
            self._next = (i + 1) % self.capacity
            self.size = min(self.capacity, self.size + 1)

    def sample(self, batch_size: int, rng: np.random.Generator) -> Dict[str, np.ndarray]:
        idx = rng.integers(0, self.size, size=min(batch_size, self.size))
        return {
            "states": self.states[idx],
            "actions": self.actions[idx],
            "returns": self.returns[idx],
        }

    def save(self, path: Union[str, Path]) -> None:
        path = Path(path)
        tmp = path.with_name(path.stem + ".tmp.npz")
        n = self.size
        order = np.arange(n) if n < self.capacity else (np.arange(n) + self._next) % self.capacity
        np.savez_compressed(
            tmp,
            states=self.states[order],
            actions=self.actions[order],
            returns=self.returns[order],
        )
        os.replace(tmp, path)

    def load(self, path: Union[str, Path]) -> None:
        with np.load(Path(path)) as data:
            if data["states"].shape[1:] != self.states.shape[1:] or data["actions"].shape[1:] != self.actions.shape[1:]:
                raise CheckpointMismatch(f"Replay buffer {path} has different feature sizes.")
            keep = slice(max(0, data["states"].shape[0] - self.capacity), None)
            self.size = 0
            self._next = 0
            # A replay file from before the gate was removed also holds `gate_mask`; it is ignored.
            self.add(data["states"][keep], data["actions"][keep], data["returns"][keep])


class ModuleValueNets(nn.Module):
    """One independent MLP per module (separate weights), evaluated together with batched matmuls."""

    def __init__(self, count: int, in_dim: int, hidden: int) -> None:
        super().__init__()
        self.count = count

        def param(*shape: int, fan_in: int) -> nn.Parameter:
            bound = 1.0 / math.sqrt(fan_in)
            return nn.Parameter(torch.empty(*shape).uniform_(-bound, bound))

        self.w1 = param(count, in_dim, hidden, fan_in=in_dim)
        self.b1 = param(count, 1, hidden, fan_in=in_dim)
        self.w2 = param(count, hidden, hidden, fan_in=hidden)
        self.b2 = param(count, 1, hidden, fan_in=hidden)
        self.w3 = param(count, hidden, 1, fan_in=hidden)
        self.b3 = param(count, 1, 1, fan_in=hidden)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """(batch, in_dim) -> (modules, batch)"""
        h = torch.relu(torch.baddbmm(self.b1, x.unsqueeze(0).expand(self.count, -1, -1), self.w1))
        h = torch.relu(torch.baddbmm(self.b2, h, self.w2))
        return torch.baddbmm(self.b3, h, self.w3).squeeze(-1)


class Learner:
    """Owns the five value networks, their experience, and training."""

    def __init__(self, config: LearnerConfig = LearnerConfig()) -> None:
        self.config = config
        # Networks this small run fastest single-threaded; extra threads only add sync overhead.
        torch.set_num_threads(1)
        torch.manual_seed(config.seed)
        self.value_nets = ModuleValueNets(len(MODULE_NAMES), STATE_DIM + ACTION_DIM, config.hidden)
        self.optimizer = torch.optim.Adam(list(self.value_nets.parameters()), lr=config.lr)
        self.stats = RunningStats(len(MODULE_NAMES))
        self.replay = ReplayBuffer(config.replay_capacity)
        self.episodes = 0
        self.transitions_seen = 0
        self.updates = 0
        self.best_score = -math.inf
        self.last_losses: Dict[str, float] = {}
        # How often each (context signature, action) and each context was experienced: shown beside the
        # predictions in the values channel, so d1 sees how much play stands behind each number.
        self.action_counts: Dict[str, int] = {}
        self.context_counts: Dict[str, int] = {}
        self._rng = np.random.default_rng(config.seed)
        self._pending: Dict[str, List[Any]] = {
            "states": [],
            "actions": [],
            "rewards": [],
            "keys": [],
        }

    def _trust(self, count: float) -> float:
        return count / (count + self.config.trust_count)

    def tried_counts(self, context_signature: str, action_ids: List[str]) -> Dict[str, int]:
        """How often each action was tried in this context in training (the values channel's 'tried')."""
        return {aid: int(self.action_counts.get(f"{context_signature}|{aid}", 0)) for aid in action_ids}

    def action_trust(self, context_signature: str, action_ids: List[str]) -> Dict[str, float]:
        """n / (n + trust_count) of each action's tries in this context: a summary of experience, for reports."""
        return {aid: self._trust(self.action_counts.get(f"{context_signature}|{aid}", 0)) for aid in action_ids}

    @property
    def network_share(self) -> float:
        """Experience-weighted trust over everything seen so far: how familiar play has become to the networks."""
        total = sum(self.action_counts.values())
        if total == 0:
            return 0.0
        return sum(n * self._trust(n) for n in self.action_counts.values()) / total

    @property
    def pending_steps(self) -> int:
        return len(self._pending["states"])

    def predict_returns(self, state_vec: np.ndarray, action_mat: np.ndarray) -> Dict[str, np.ndarray]:
        """Predicted standardised return of every candidate action, per network."""
        with torch.no_grad():
            s = torch.as_tensor(state_vec, dtype=torch.float32).unsqueeze(0).expand(action_mat.shape[0], -1)
            x = torch.cat([s, torch.as_tensor(action_mat, dtype=torch.float32)], dim=1)
            preds = self.value_nets(x).numpy()
        return {name: preds[i] for i, name in enumerate(MODULE_NAMES)}

    def record_step(
        self,
        state_vec: np.ndarray,
        action_vec: np.ndarray,
        result: Any,
        executed_action_id: str,
        context_signature: str = "",
    ) -> None:
        """Keep one executed decision of the episode in play, for `end_episode`."""
        self._pending["states"].append(np.asarray(state_vec, dtype=np.float32))
        self._pending["actions"].append(np.asarray(action_vec, dtype=np.float32))
        self._pending["rewards"].append(module_rewards(result))
        self._pending["keys"].append((context_signature, executed_action_id))

    def discard_episode(self) -> None:
        for buf in self._pending.values():
            buf.clear()

    def end_episode(self) -> int:
        """Turn the pending episode into n-step returns and move it into the replay buffer."""
        steps = self.pending_steps
        self.episodes += 1
        if steps == 0:
            return 0
        rewards = np.stack(self._pending["rewards"])
        returns = n_step_returns(rewards, self.config.gamma, self.config.n_step)
        self.stats.update(returns)
        self.replay.add(
            np.stack(self._pending["states"]),
            np.stack(self._pending["actions"]),
            returns,
        )
        for context, action_id in self._pending["keys"]:
            key = f"{context}|{action_id}"
            self.action_counts[key] = self.action_counts.get(key, 0) + 1
            self.context_counts[context] = self.context_counts.get(context, 0) + 1
        self.transitions_seen += steps
        self.discard_episode()
        return steps

    def train(self, steps: Optional[int] = None) -> Dict[str, float]:
        """Run a fixed number of gradient steps. Returns the mean loss per network."""
        n_steps = self.config.train_steps if steps is None else steps
        if self.replay.size < 32 or n_steps <= 0:
            return {}
        totals = {name: 0.0 for name in MODULE_NAMES}
        for _ in range(n_steps):
            batch = self.replay.sample(self.config.batch_size, self._rng)
            states = torch.as_tensor(batch["states"])
            x = torch.cat([states, torch.as_tensor(batch["actions"])], dim=1)
            targets = torch.as_tensor(self.stats.normalize(batch["returns"]))

            module_mse = torch.mean((self.value_nets(x) - targets.T) ** 2, dim=1)
            losses = {name: module_mse[i] for i, name in enumerate(MODULE_NAMES)}

            self.optimizer.zero_grad()
            torch.stack(list(losses.values())).sum().backward()
            self.optimizer.step()
            for name, loss in losses.items():
                totals[name] += float(loss.detach())
        self.updates += n_steps
        self.last_losses = {name: round(total / n_steps, 5) for name, total in totals.items()}
        return dict(self.last_losses)

    def save(self, path: Union[str, Path]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": CHECKPOINT_FORMAT,
            "state_dim": STATE_DIM,
            "action_dim": ACTION_DIM,
            "modules": list(MODULE_NAMES),
            "config": asdict(self.config),
            "value_nets": self.value_nets.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "stats": self.stats.to_dict(),
            "counters": {
                "episodes": self.episodes,
                "transitions_seen": self.transitions_seen,
                "updates": self.updates,
                "best_score": self.best_score if math.isfinite(self.best_score) else None,
            },
            "action_counts": dict(self.action_counts),
            "context_counts": dict(self.context_counts),
            "last_losses": dict(self.last_losses),
        }
        tmp = path.with_name(path.name + ".tmp")
        torch.save(payload, tmp)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Union[str, Path], overrides: Optional[Dict[str, Any]] = None) -> "Learner":
        payload = torch.load(Path(path), map_location="cpu", weights_only=True)
        if payload.get("format") != CHECKPOINT_FORMAT:
            raise CheckpointMismatch(f"{path} uses checkpoint format {payload.get('format')}, expected {CHECKPOINT_FORMAT}.")
        if payload.get("state_dim") != STATE_DIM or payload.get("action_dim") != ACTION_DIM:
            raise CheckpointMismatch(
                f"{path} was trained with state/action sizes {payload.get('state_dim')}/{payload.get('action_dim')}, "
                f"this code uses {STATE_DIM}/{ACTION_DIM}."
            )
        if list(payload.get("modules", [])) != list(MODULE_NAMES):
            raise CheckpointMismatch(f"{path} has modules {payload.get('modules')}, expected {list(MODULE_NAMES)}.")

        known = {f.name for f in fields(LearnerConfig)}
        stored = {k: v for k, v in payload["config"].items() if k in known}
        for key, value in (overrides or {}).items():
            if key in known and key not in ARCHITECTURE_FIELDS:
                stored[key] = value
        learner = cls(LearnerConfig(**stored))
        learner.value_nets.load_state_dict(payload["value_nets"])
        learner.optimizer.load_state_dict(_value_net_optimizer_state(payload["optimizer"], len(list(learner.value_nets.parameters()))))
        for group in learner.optimizer.param_groups:
            group["lr"] = learner.config.lr
        learner.stats = RunningStats.from_dict(payload["stats"])
        counters = payload["counters"]
        learner.episodes = int(counters["episodes"])
        learner.transitions_seen = int(counters["transitions_seen"])
        learner.updates = int(counters["updates"])
        best = counters.get("best_score")
        learner.best_score = float(best) if best is not None else -math.inf
        learner.action_counts = {str(k): int(v) for k, v in payload.get("action_counts", {}).items()}
        learner.context_counts = {str(k): int(v) for k, v in payload.get("context_counts", {}).items()}
        learner.last_losses = {k: v for k, v in dict(payload.get("last_losses", {})).items() if k not in LEGACY_GATE_KEYS}
        return learner


def _value_net_optimizer_state(state: Dict[str, Any], count: int) -> Dict[str, Any]:
    """The optimizer state of the value networks' `count` parameters.

    Checkpoints from before the gate was removed hold one Adam state over the value networks'
    parameters followed by the gate's; the value networks' come first, so the first `count` are kept.
    """
    groups = state.get("param_groups", [])
    if len(groups) != 1 or len(groups[0].get("params", [])) == count:
        return state
    kept = list(groups[0]["params"])[:count]
    return {
        "state": {k: v for k, v in state.get("state", {}).items() if k in set(kept)},
        "param_groups": [{**groups[0], "params": kept}],
    }
