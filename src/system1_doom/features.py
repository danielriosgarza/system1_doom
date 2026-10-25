"""Fixed-size numeric encodings of world states and actions for the value networks, and their rewards.

The encodings are scenario-agnostic. Actions are described by their primitive composition rather
than by identity, so a newly admitted macro-action gets predictions in the values channel the moment
it enters the menu. `n_step_returns` is the return both the networks and the relevance ledger use.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from system1_doom.actions import STRAFE_FIRE_PRIMITIVES, ActionSpec
from system1_doom.state import WorldState

PICKUP_CATEGORIES = ("health", "armor", "ammo", "weapon", "item")
ACTION_PRIMITIVES = (
    "move_forward",
    "move_backward",
    "strafe_left",
    "strafe_right",
    "turn_left",
    "turn_right",
    "shoot",
    "use",
)
HISTORY_TOKENS = ("shoot", "move_forward", "strafe", "turn")

STATE_DIM = 32
ACTION_DIM = len(ACTION_PRIMITIVES) + 4
MODULE_NAMES = ("survival", "combat", "navigation", "resource", "goal")


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return float(min(high, max(low, value)))


def encode_state(state: WorldState) -> np.ndarray:
    obs = state.observation
    enemies = sorted(obs.visible_enemies, key=lambda e: e.distance)
    pickups = sorted(obs.visible_pickups, key=lambda p: p.distance)
    nearest = enemies[0] if enemies else None
    pickup = pickups[0] if pickups else None

    vec = [
        _clip(obs.health / 100.0, 0.0, 2.0),
        _clip(obs.armor / 100.0, 0.0, 2.0),
        _clip(obs.ammo / 50.0, 0.0, 2.0),
        1.0 if obs.ammo > 0 else 0.0,
        _clip(len(enemies) / 5.0),
        _clip(nearest.distance / 1000.0) if nearest else 1.0,
        _clip(nearest.angle_offset / 45.0, -1.0, 1.0) if nearest else 0.0,
        _clip(abs(nearest.angle_offset) / 45.0) if nearest else 0.0,
        1.0 if nearest and abs(nearest.angle_offset) <= 12.0 else 0.0,
        1.0 if len(enemies) >= 2 else 0.0,
        1.0 if nearest and nearest.distance < 140.0 else 0.0,
        _clip(len(pickups) / 5.0),
        _clip(pickup.distance / 1000.0) if pickup else 1.0,
        _clip(pickup.angle_offset / 45.0, -1.0, 1.0) if pickup else 0.0,
    ]
    vec.extend(1.0 if pickup and pickup.category == cat else 0.0 for cat in PICKUP_CATEGORIES)
    vec.extend(
        [
            _clip(obs.wall_distance_front / 256.0, 0.0, 2.0),
            _clip(obs.wall_distance_left / 256.0, 0.0, 2.0),
            _clip(obs.wall_distance_right / 256.0, 0.0, 2.0),
            _clip(obs.recent_incoming_damage / 50.0, 0.0, 2.0),
            _clip(obs.recent_outgoing_damage / 50.0, 0.0, 2.0),
            _clip(float(obs.recent_kills), 0.0, 2.0),
            1.0 if obs.movement_state == "moving" else 0.0,
            _clip(obs.episode_progress.get("episode_tick", float(obs.tick)) / 100.0, 0.0, 3.0),
            _clip(obs.episode_progress.get("last_displacement", 64.0) / 64.0),
        ]
    )
    history = obs.recent_actions[-6:]
    for token in HISTORY_TOKENS:
        vec.append(sum(1 for step in history if token in step) / 6.0)
    return np.asarray(vec, dtype=np.float32)


def _components(primitive: str) -> tuple[str, ...]:
    if primitive in STRAFE_FIRE_PRIMITIVES:
        return (primitive[: -len("_shoot")], "shoot")
    return (primitive,)


def encode_action(action: ActionSpec) -> np.ndarray:
    plan = action.primitive_expansion
    length = max(1, len(plan))
    parts = [c for p in plan for c in _components(p)]
    vec = [sum(1 for c in parts if c == prim) / length for prim in ACTION_PRIMITIVES]
    vec.extend(
        [
            sum(1 for p in plan if p.startswith("switch_weapon")) / length,
            len(plan) / 16.0,
            1.0 if action.is_macro else 0.0,
            1.0 if "pickup_id" in action.parameters else 0.0,
        ]
    )
    return np.asarray(vec, dtype=np.float32)


def encode_actions(actions: Sequence[ActionSpec]) -> np.ndarray:
    return np.stack([encode_action(a) for a in actions]).astype(np.float32)


def n_step_returns(rewards: np.ndarray, gamma: float, n: int) -> np.ndarray:
    """Discounted sum of the next `n` rewards for every step, truncated at episode end.

    The learner's targets and the relevance ledger's "paid off" both use it, so it lives here, free of torch.
    """
    steps = rewards.shape[0]
    returns = np.zeros_like(rewards, dtype=np.float32)
    for t in range(steps):
        horizon = rewards[t : min(steps, t + n)]
        discounts = gamma ** np.arange(horizon.shape[0], dtype=np.float32)
        if rewards.ndim == 1:
            returns[t] = (horizon * discounts).sum()
        else:
            returns[t] = (horizon * discounts[:, None]).sum(axis=0)
    return returns


def module_rewards(result: Any) -> np.ndarray:
    """Each value network's reward for one executed decision, ordered like MODULE_NAMES."""
    died = 1.0 if getattr(result, "died", False) else 0.0
    return np.asarray(
        [
            -float(result.damage_taken) / 25.0 - 3.0 * died,
            0.5 * float(result.hits_delta) + 2.0 * float(result.kills_delta),
            float(result.new_cells),
            float(result.health_gain) / 25.0 + float(result.armor_gain) / 25.0 + float(result.ammo_gain) / 10.0,
            float(result.reward),
        ],
        dtype=np.float32,
    )
