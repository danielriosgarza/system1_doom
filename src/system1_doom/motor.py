"""Bounded closed-loop motor for ViZDoom scenarios.

The arbiter picks one action from a finite set and the motor executes that action's
primitive list. Each primitive keeps a small amount of closed-loop assistance:
`shoot` aims at the locked target before firing, strafes keep tracking it, and the
forward steps of a pickup-seeking action steer toward the nearest visible pickup.
Every burst is bounded by the length of the action's primitive list.
"""

from __future__ import annotations

import time
from typing import Dict, Iterable, List, Optional, Sequence, Set

import numpy as np
import vizdoom as vzd

REFLEX_FRAME_SKIP = 2
STEPS_PER_DECISION = 4

ENEMY_KEYWORDS = (
    "zombieman",
    "shotgunguy",
    "chaingunguy",
    "doomimp",
    "demon",
    "spectre",
    "cacodemon",
    "hellknight",
    "baronofhell",
    "arachnotron",
    "painelemental",
    "revenant",
    "mancubus",
    "archvile",
    "cyberdemon",
    "spidermastermind",
    "marine",
)

PICKUP_KEYWORDS = (
    "medikit",
    "stimpack",
    "healthbonus",
    "soulsphere",
    "armor",
    "clip",
    "shell",
    "rocket",
    "cell",
    "shotgun",
    "chaingun",
    "plasmarifle",
    "bfg9000",
    "chainsaw",
)

FLAG_TO_PRIMITIVE = {
    "MOVE_FORWARD": "move_forward",
    "MOVE_BACKWARD": "move_backward",
    "MOVE_LEFT": "strafe_left",
    "MOVE_RIGHT": "strafe_right",
    "TURN_LEFT": "turn_left",
    "TURN_RIGHT": "turn_right",
    "ATTACK": "shoot",
    "USE": "use",
}

PRIMITIVE_TO_BUTTON = {prim: button for button, prim in FLAG_TO_PRIMITIVE.items()}
COMPOUND_STRAFE_FIRE = {"strafe_left_shoot": "MOVE_LEFT", "strafe_right_shoot": "MOVE_RIGHT"}
PRIMITIVE_BUTTONS: Dict[str, tuple] = {
    **{prim: (button,) for prim, button in PRIMITIVE_TO_BUTTON.items()},
    **{prim: (strafe, "ATTACK") for prim, strafe in COMPOUND_STRAFE_FIRE.items()},
}


def is_ignored_actor(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("dead", "player", "blood", "puff", "bullet", "gib"))


def is_enemy_name(name: str) -> bool:
    if is_ignored_actor(name):
        return False
    lowered = name.lower()
    return any(token in lowered for token in ENEMY_KEYWORDS)


def is_pickup_name(name: str) -> bool:
    if is_ignored_actor(name) or is_enemy_name(name):
        return False
    lowered = name.lower()
    return any(token in lowered for token in PICKUP_KEYWORDS)


def _screen_size(screen_buf: Optional[np.ndarray]) -> tuple[int, int]:
    if screen_buf is None or screen_buf.ndim < 2:
        return 320, 240
    if screen_buf.ndim == 3 and screen_buf.shape[0] in (1, 3, 4) and screen_buf.shape[0] < screen_buf.shape[1]:
        return int(screen_buf.shape[2]), int(screen_buf.shape[1])
    if screen_buf.ndim == 3:
        return int(screen_buf.shape[1]), int(screen_buf.shape[0])
    return int(screen_buf.shape[1]), int(screen_buf.shape[0])


class MotorBurst:
    def __init__(
        self,
        reward: float,
        primitives: List[str],
        frames: List[np.ndarray],
        terminated_early: bool,
        episode_finished: bool,
        health_after: float,
        damage_taken: float,
        kills: float,
        armor: float,
        kills_delta: float,
        hits_delta: float = 0.0,
        health_gain: float = 0.0,
        armor_gain: float = 0.0,
        ammo_gain: float = 0.0,
        died: bool = False,
    ) -> None:
        self.reward = reward
        self.primitives = primitives
        self.frames = frames
        self.terminated_early = terminated_early
        self.episode_finished = episode_finished
        self.health_after = health_after
        self.damage_taken = damage_taken
        self.kills = kills
        self.armor = armor
        self.kills_delta = kills_delta
        self.hits_delta = hits_delta
        self.health_gain = health_gain
        self.armor_gain = armor_gain
        self.ammo_gain = ammo_gain
        self.died = died


class TacticalMotor:
    """Executes an action's primitive plan with aim, tracking, and pickup-steering assists."""

    def __init__(self, game: vzd.DoomGame, button_names: List[str], scenario: str) -> None:
        self.game = game
        self.button_names = list(button_names)
        self.scenario = scenario
        self.lock_id: Optional[int] = None
        self.ignored_pickups: Set[int] = set()
        self.last_pickup_target: Optional[int] = None

    def reset(self) -> None:
        self.lock_id = None
        self.ignored_pickups.clear()
        self.last_pickup_target = None

    def action_supported(self, primitive_expansion: Iterable[str]) -> bool:
        prims = list(primitive_expansion)
        if not prims or any(p not in PRIMITIVE_BUTTONS for p in prims):
            return False
        return all(button in self.button_names for p in prims for button in PRIMITIVE_BUTTONS[p])

    def burst(self, plan: Sequence[str], steer_to_pickup: bool = False, step_delay_ms: int = 0) -> MotorBurst:
        hp_before = self._var(vzd.GameVariable.HEALTH, 100.0)
        kills_before = self._var(vzd.GameVariable.KILLCOUNT, 0.0)
        hits_before = self._var(vzd.GameVariable.HITCOUNT, 0.0)
        armor_before = self._var(vzd.GameVariable.ARMOR, 0.0)
        ammo_before = self._var(vzd.GameVariable.SELECTED_WEAPON_AMMO, 0.0)

        reward = 0.0
        primitives: List[str] = []
        last_frame: Optional[np.ndarray] = None
        terminated_early = False
        hold = max(1, STEPS_PER_DECISION // max(1, len(plan)))
        self.last_pickup_target = None

        for primitive in plan:
            for _ in range(hold):
                if self.game.is_episode_finished():
                    terminated_early = True
                    break
                flags = self._assisted_flags(primitive, steer_to_pickup)
                if not flags:
                    continue
                reward += self._press(flags)
                primitives.append(self._format_flags(flags))
                state = self.game.get_state()
                if state is not None and state.screen_buffer is not None:
                    last_frame = state.screen_buffer.copy()
                if step_delay_ms > 0:
                    time.sleep(step_delay_ms / 1000.0)
            if terminated_early:
                break

        finished = bool(self.game.is_episode_finished())
        hp_after = self._var(vzd.GameVariable.HEALTH, hp_before)
        kills_after = self._var(vzd.GameVariable.KILLCOUNT, kills_before)
        hits_after = self._var(vzd.GameVariable.HITCOUNT, hits_before)
        armor_after = self._var(vzd.GameVariable.ARMOR, armor_before)
        ammo_after = self._var(vzd.GameVariable.SELECTED_WEAPON_AMMO, ammo_before)
        frames = [last_frame] if last_frame is not None else []
        return MotorBurst(
            reward=reward,
            primitives=primitives or ["idle"],
            frames=frames,
            terminated_early=terminated_early or finished,
            episode_finished=finished,
            health_after=hp_after,
            damage_taken=max(0.0, hp_before - hp_after),
            kills=kills_after,
            armor=armor_after,
            kills_delta=max(0.0, kills_after - kills_before),
            hits_delta=max(0.0, hits_after - hits_before),
            health_gain=max(0.0, hp_after - hp_before),
            armor_gain=max(0.0, armor_after - armor_before),
            ammo_gain=max(0.0, ammo_after - ammo_before),
            died=bool(self.game.is_player_dead()),
        )

    def _var(self, variable: vzd.GameVariable, default: float) -> float:
        try:
            return float(self.game.get_game_variable(variable))
        except Exception:
            return default

    def _press(self, flags: Set[str]) -> float:
        vector = [1 if name in flags else 0 for name in self.button_names]
        return float(self.game.make_action(vector, REFLEX_FRAME_SKIP))

    def _format_flags(self, flags: Set[str]) -> str:
        ordered = [FLAG_TO_PRIMITIVE[name] for name in FLAG_TO_PRIMITIVE if name in flags]
        return "+".join(ordered) if ordered else "idle"

    def _assisted_flags(self, primitive: str, steer_to_pickup: bool) -> Set[str]:
        state = self.game.get_state()
        screen_w = 320
        if state is not None and state.screen_buffer is not None:
            screen_w, _ = _screen_size(state.screen_buffer)
        center = screen_w / 2.0
        align_px = max(8.0, screen_w * 10.0 / 320.0)

        if primitive == "shoot":
            target = self._locked_enemy(self._living_enemies(state), center)
            if target is None:
                return {"ATTACK"} if "ATTACK" in self.button_names else set()
            return self._aim_buttons(target["cx"], center, align_px)

        if primitive in COMPOUND_STRAFE_FIRE:
            # Keep moving sideways the whole step; turn onto the target, fire once it is centred.
            flags = {COMPOUND_STRAFE_FIRE[primitive]}
            target = self._locked_enemy(self._living_enemies(state), center)
            turn = self._turn_toward(target["cx"], center, align_px) if target is not None else None
            flags.add(turn if turn is not None else "ATTACK")
            return flags

        button = PRIMITIVE_TO_BUTTON.get(primitive)
        if button is None or button not in self.button_names:
            return set()
        flags = {button}
        if primitive in ("strafe_left", "strafe_right"):
            target = self._locked_enemy(self._living_enemies(state), center)
            if target is not None:
                turn = self._turn_toward(target["cx"], center, align_px)
                if turn is not None:
                    flags.add(turn)
        elif primitive == "move_forward" and steer_to_pickup:
            pickup = self._nearest_pickup(state)
            if pickup is not None:
                self.last_pickup_target = int(pickup.object_id)
                turn = self._turn_toward(float(pickup.x + pickup.width / 2.0), center, align_px)
                if turn is not None:
                    flags.add(turn)
        return flags

    def _living_enemies(self, state: Optional[object]) -> List[Dict[str, float]]:
        if state is None or not getattr(state, "labels", None):
            return []
        enemies: List[Dict[str, float]] = []
        for label in state.labels:
            if not is_enemy_name(label.object_name):
                continue
            enemies.append(
                {
                    "id": float(label.object_id),
                    "cx": float(label.x + label.width / 2.0),
                    "height": float(label.height),
                }
            )
        return enemies

    def _nearest_pickup(self, state: Optional[object]) -> Optional[object]:
        if state is None or not getattr(state, "labels", None):
            return None
        pickups = [
            label
            for label in state.labels
            if is_pickup_name(label.object_name) and int(label.object_id) not in self.ignored_pickups
        ]
        if not pickups:
            return None
        # A taller sprite is a closer pickup.
        return max(pickups, key=lambda label: label.height)

    def _locked_enemy(self, enemies: List[Dict[str, float]], center: float) -> Optional[Dict[str, float]]:
        target = None
        if self.lock_id is not None:
            target = next((enemy for enemy in enemies if int(enemy["id"]) == self.lock_id), None)
        if target is None and enemies:
            target = min(enemies, key=lambda enemy: abs(enemy["cx"] - center))
            self.lock_id = int(target["id"])
        if target is None:
            self.lock_id = None
        return target

    def _turn_toward(self, cx: float, center: float, align_px: float) -> Optional[str]:
        if cx < center - align_px and "TURN_LEFT" in self.button_names:
            return "TURN_LEFT"
        if cx > center + align_px and "TURN_RIGHT" in self.button_names:
            return "TURN_RIGHT"
        return None

    def _aim_buttons(self, cx: float, center: float, align_px: float) -> Set[str]:
        for side, turn, strafe in (("left", "TURN_LEFT", "MOVE_LEFT"), ("right", "TURN_RIGHT", "MOVE_RIGHT")):
            off_side = cx < center - align_px if side == "left" else cx > center + align_px
            if not off_side:
                continue
            if turn in self.button_names:
                return {turn}
            if strafe in self.button_names:
                return {strafe}
        return {"ATTACK"} if "ATTACK" in self.button_names else set()
