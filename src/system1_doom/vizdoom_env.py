from __future__ import annotations

import base64
import io
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
import numpy as np
from PIL import Image
import vizdoom as vzd

from system1_doom.actions import ActionSpec
from system1_doom.motor import (
    WALK_CONE_DEG,
    MotorBurst,
    TacticalMotor,
    _screen_size,
    bearing_to,
    is_enemy_name,
    is_ignored_actor,
    is_pickup_name,
)
from system1_doom.state import (
    ControllerMemory,
    EnemyObservation,
    LandmarkObservation,
    Observation,
    PickupObservation,
    Pose3D,
    WorldState,
)

PICKUP_CATEGORY_MAP: Dict[str, Literal["health", "armor", "ammo", "weapon", "item"]] = {
    "medikit": "health",
    "stimpack": "health",
    "healthbonus": "health",
    "soulsphere": "health",
    "greenarmor": "armor",
    "bluearmor": "armor",
    "armorbonus": "armor",
    "clip": "ammo",
    "clipbox": "ammo",
    "shell": "ammo",
    "shellbox": "ammo",
    "rocketammo": "ammo",
    "rocketbox": "ammo",
    "cell": "ammo",
    "cellpack": "ammo",
    "shotgun": "weapon",
    "supershotgun": "weapon",
    "chaingun": "weapon",
    "rocketlauncher": "weapon",
    "plasmarifle": "weapon",
    "bfg9000": "weapon",
    "chainsaw": "weapon",
}


# An approach that got less than this much closer to the chosen pickup counts as getting nowhere.
UNREACHABLE_PICKUP_PROGRESS = 12.0
# A decision that changed a landmark's distance by less than this tells nothing about reward and distance.
LANDMARK_MOVE_UNITS = 1.0


@dataclass
class _Remembered:
    """A pickup the agent has seen this episode: where it was seen, and how reward went with its distance."""

    landmark_id: str
    object_id: int
    name: str
    category: str
    x: float
    y: float
    last_seen_tick: int
    gone: bool = False
    moves: int = 0
    reward_closer: float = 0.0  # sum of reward x (distance lost)
    distance_sq: float = 0.0  # sum of (distance change)^2
    reward_sq: float = 0.0  # sum of reward^2
    approaches_nowhere: int = 0

    def agreement(self) -> Optional[float]:
        """How reward went with getting closer: the cosine of the per-decision rewards and distance lost."""
        if self.distance_sq <= 0.0 or self.reward_sq <= 0.0:
            return None
        return max(-1.0, min(1.0, self.reward_closer / math.sqrt(self.distance_sq * self.reward_sq)))


class ExecutionStepResult:
    def __init__(
        self,
        reward: float,
        primitive_steps_executed: List[str],
        terminated_early: bool,
        episode_finished: bool,
        frames_captured: Optional[List[np.ndarray]] = None,
        damage_taken: float = 0.0,
        health_after: float = 0.0,
        kills_delta: float = 0.0,
        armor: float = 0.0,
        hits_delta: float = 0.0,
        health_gain: float = 0.0,
        armor_gain: float = 0.0,
        ammo_gain: float = 0.0,
        died: bool = False,
        new_cells: int = 0,
        displacement: float = 0.0,
    ) -> None:
        self.reward = reward
        self.primitive_steps_executed = primitive_steps_executed
        self.terminated_early = terminated_early
        self.episode_finished = episode_finished
        self.frames_captured: List[np.ndarray] = frames_captured or []
        self.damage_taken = damage_taken
        self.health_after = health_after
        self.kills_delta = kills_delta
        self.armor = armor
        self.hits_delta = hits_delta
        self.health_gain = health_gain
        self.armor_gain = armor_gain
        self.ammo_gain = ammo_gain
        self.died = died
        self.new_cells = new_cells
        self.displacement = displacement


class ViZDoomBridge:
    """
    Integrates ViZDoom with the bounded decision controller:
    - Extracts immutable `WorldState` snapshots (`S_t`)
    - Maps finite primitive/macro `ActionSpec` expansions to ViZDoom button vectors
    """

    def __init__(
        self,
        scenario: str = "deadly_corridor.cfg",
        window_visible: bool = False,
        frame_skip: int = 4,
        include_jpeg_frame: bool = True,
        step_delay_ms: int = 0,
        seed: Optional[int] = None,
    ) -> None:
        self.scenario = scenario
        self.window_visible = window_visible
        self.frame_skip = frame_skip
        self.include_jpeg_frame = include_jpeg_frame
        self.step_delay_ms = step_delay_ms

        self.game = vzd.DoomGame()
        cfg_path = scenario if os.path.isabs(scenario) else os.path.join(vzd.scenarios_path, scenario)
        self.game.load_config(cfg_path)
        if seed is not None:
            self.game.set_seed(int(seed))
        self.game.set_window_visible(window_visible)
        self.game.set_screen_resolution(
            vzd.ScreenResolution.RES_640X480 if window_visible else vzd.ScreenResolution.RES_320X240
        )
        self.game.set_screen_format(vzd.ScreenFormat.CRCGCB)
        self.game.set_objects_info_enabled(True)
        self.game.set_labels_buffer_enabled(True)
        self.game.set_depth_buffer_enabled(True)
        self.game.init()
        self.button_names: List[str] = [b.name for b in self.game.get_available_buttons()]
        self.motor = TacticalMotor(self.game, self.button_names, scenario)
        self.auto_restart = True

        self._tick = 0
        self._episode_tick = 0
        self._prev_health = self._safe_var(vzd.GameVariable.HEALTH, 100.0)
        self._prev_hits = self._safe_var(vzd.GameVariable.HITCOUNT, 0.0)
        self._prev_kills = int(self._safe_var(vzd.GameVariable.KILLCOUNT, 0.0))
        self._total_reward = 0.0
        self._action_history: List[str] = []
        self._state_summaries: List[str] = []
        self._discovered_locations: List[str] = []
        self._episode_cells: Set[Tuple[int, int]] = set()
        self._last_displacement: Optional[float] = None
        self._last_reward: Optional[float] = None
        self._landmarks: Dict[int, _Remembered] = {}
        # Per enemy object id: how many of the agent's attacks on it in a row, as the chosen target, hit nothing.
        self._attacks_without_hit: Dict[int, int] = {}

    def _safe_var(self, var: vzd.GameVariable, default: float = 0.0) -> float:
        try:
            return float(self.game.get_game_variable(var))
        except Exception:
            return default

    def _encode_jpeg_b64(self, screen_buf: np.ndarray) -> Optional[str]:
        if not self.include_jpeg_frame or screen_buf is None:
            return None
        arr = screen_buf
        if arr.ndim == 3 and arr.shape[0] in (1, 3, 4):
            arr = np.transpose(arr, (1, 2, 0))
        img = Image.fromarray(arr.astype(np.uint8))
        if img.size != (320, 240):
            img = img.resize((320, 240), Image.Resampling.BILINEAR)
        bio = io.BytesIO()
        img.save(bio, format="JPEG", quality=75)
        return base64.b64encode(bio.getvalue()).decode("ascii")

    def is_episode_finished(self) -> bool:
        return bool(self.game.is_episode_finished())

    def restart_episode(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.game.set_seed(int(seed))
        self.game.new_episode()
        self.motor.reset()
        self._prev_health = self._safe_var(vzd.GameVariable.HEALTH, 100.0)
        self._prev_hits = self._safe_var(vzd.GameVariable.HITCOUNT, 0.0)
        self._prev_kills = int(self._safe_var(vzd.GameVariable.KILLCOUNT, 0.0))
        self._action_history.clear()
        self._state_summaries.clear()
        self._episode_cells.clear()
        self._episode_tick = 0
        self._last_displacement = None
        self._last_reward = None
        self._landmarks.clear()
        self._attacks_without_hit.clear()

    def reset_tick_count(self) -> None:
        """Number the next observation tick 0, as a new bridge would; otherwise the count runs on across episodes."""
        self._tick = 0

    def _current_cell(self) -> Tuple[int, int]:
        px = self._safe_var(vzd.GameVariable.POSITION_X, 0.0)
        py = self._safe_var(vzd.GameVariable.POSITION_Y, 0.0)
        return int(px // 128), int(py // 128)

    def episode_status(self) -> Dict[str, float]:
        return {
            "health": self._safe_var(vzd.GameVariable.HEALTH, 0.0),
            "armor": self._safe_var(vzd.GameVariable.ARMOR, 0.0),
            "kills": self._safe_var(vzd.GameVariable.KILLCOUNT, 0.0),
            "reward": float(self.game.get_total_reward()),
        }

    def level_cleared(self) -> bool:
        """Scenario-specific clear: kill, vest, or surviving until the episode timeout."""
        status = self.episode_status()
        finished = self.is_episode_finished()
        alive = status["health"] > 0.0
        name = self.scenario.lower()
        if "basic" in name:
            return alive and status["kills"] >= 1.0
        if "deadly_corridor" in name:
            return finished and alive and status["armor"] >= 100.0
        if "health_gathering" in name and "supreme" not in name:
            return finished and alive
        if name.startswith("defend_") or "defend_" in name:
            return finished and alive
        return finished and alive and (status["kills"] >= 1.0 or status["armor"] >= 100.0)

    def action_supported(self, action: ActionSpec) -> bool:
        return self.motor.action_supported(action.primitive_expansion)

    def acquire_world_state(self, strategy_refs: Tuple[str, ...] = ()) -> WorldState:
        if self.game.is_episode_finished() and self.auto_restart:
            self.restart_episode()

        v_state = self.game.get_state()
        health = max(0.0, self._safe_var(vzd.GameVariable.HEALTH, 100.0))
        armor = max(0.0, self._safe_var(vzd.GameVariable.ARMOR, 0.0))
        weapon_id = int(self._safe_var(vzd.GameVariable.SELECTED_WEAPON, 2.0))
        ammo_raw = self._safe_var(vzd.GameVariable.SELECTED_WEAPON_AMMO, -1.0)
        if weapon_id < 1 or ammo_raw < 0:
            # Before the first game tic the selected weapon is not reported yet: the player holds the pistol,
            # whose rounds are the bullets (AMMO2).
            weapon_id = 2
            ammo_raw = self._safe_var(vzd.GameVariable.AMMO2, 25.0)
        ammo = int(max(0.0, ammo_raw))
        weapon_name = {1: "fist_chainsaw", 2: "pistol", 3: "shotgun", 4: "chaingun"}.get(weapon_id, f"weapon_{weapon_id}")

        hits = self._safe_var(vzd.GameVariable.HITCOUNT, 0.0)
        kills = int(self._safe_var(vzd.GameVariable.KILLCOUNT, 0.0))

        recent_in_dmg = max(0.0, self._prev_health - health)
        recent_hits = int(max(0.0, hits - self._prev_hits))
        recent_out_dmg = max(0.0, (hits - self._prev_hits) * 20.0)
        recent_kills = max(0, kills - self._prev_kills)

        self._prev_health = health
        self._prev_hits = hits
        self._prev_kills = kills

        px = self._safe_var(vzd.GameVariable.POSITION_X, 0.0)
        py = self._safe_var(vzd.GameVariable.POSITION_Y, 0.0)
        pz = self._safe_var(vzd.GameVariable.POSITION_Z, 0.0)
        angle = self._safe_var(vzd.GameVariable.ANGLE, 0.0)
        vx = self._safe_var(vzd.GameVariable.VELOCITY_X, 0.0)
        vy = self._safe_var(vzd.GameVariable.VELOCITY_Y, 0.0)
        speed = math.hypot(vx, vy)
        movement_state = "moving" if speed > 0.5 else "stationary"

        # Extract visible enemies and pickups from labels + objects
        enemies: List[EnemyObservation] = []
        pickups: List[PickupObservation] = []
        in_view: Set[int] = set()
        wall_front, wall_left, wall_right = 256.0, 128.0, 128.0
        frame_b64: Optional[str] = None
        brightness = 0.5
        screen_w, screen_h = 320, 240

        if v_state is not None:
            if v_state.screen_buffer is not None:
                screen_w, screen_h = _screen_size(v_state.screen_buffer)
                brightness = float(np.mean(v_state.screen_buffer) / 255.0)
                frame_b64 = self._encode_jpeg_b64(v_state.screen_buffer)

            if v_state.depth_buffer is not None and v_state.depth_buffer.size > 0:
                db = v_state.depth_buffer
                h, w = db.shape[:2]
                wall_front = float(np.mean(db[h // 3 : 2 * h // 3, w // 3 : 2 * w // 3])) * 4.0
                wall_left = float(np.mean(db[h // 3 : 2 * h // 3, : w // 3])) * 4.0
                wall_right = float(np.mean(db[h // 3 : 2 * h // 3, 2 * w // 3 :])) * 4.0

            obj_pos_by_id: Dict[int, Tuple[float, float]] = {}
            if v_state.objects:
                for obj in v_state.objects:
                    obj_pos_by_id[obj.id] = (float(obj.position_x), float(obj.position_y))

            center_x = screen_w / 2.0
            if v_state.labels:
                for idx, lbl in enumerate(v_state.labels):
                    name_low = lbl.object_name.lower()
                    if is_ignored_actor(lbl.object_name):
                        continue
                    cx = int(lbl.x + lbl.width // 2)
                    cy = int(lbl.y + lbl.height // 2)
                    # Positive offset means the actor is left of the crosshair. The screen spans 90 degrees, so a
                    # point's angle is atan of its offset from the centre (a linear map understates every angle).
                    angle_offset = math.degrees(math.atan((center_x - cx) / max(1.0, center_x)))
                    if lbl.object_id in obj_pos_by_id:
                        ox, oy = obj_pos_by_id[lbl.object_id]
                        dist = math.hypot(ox - px, oy - py)
                    else:
                        dist = max(30.0, 3200.0 / max(8, lbl.height))

                    if is_enemy_name(lbl.object_name):
                        enemies.append(
                            EnemyObservation(
                                enemy_id=f"{lbl.object_name}_{lbl.object_id}",
                                name=lbl.object_name,
                                distance=round(dist, 1),
                                angle_offset=round(angle_offset, 1),
                                screen_x=cx,
                                screen_y=cy,
                                width=int(lbl.width),
                                height=int(lbl.height),
                                attacks_without_hit=self._attacks_without_hit.get(int(lbl.object_id), 0),
                            )
                        )
                    elif is_pickup_name(lbl.object_name):
                        cat: Literal["health", "armor", "ammo", "weapon", "item"] = "item"
                        for k_sub, k_cat in PICKUP_CATEGORY_MAP.items():
                            if k_sub in name_low:
                                cat = k_cat
                                break
                        if lbl.object_id in obj_pos_by_id:
                            self._remember(lbl.object_name, int(lbl.object_id), cat, *obj_pos_by_id[lbl.object_id])
                            in_view.add(int(lbl.object_id))
                        pickups.append(
                            PickupObservation(
                                pickup_id=f"{lbl.object_name}_{lbl.object_id}",
                                name=lbl.object_name,
                                category=cat,
                                distance=round(dist, 1),
                                angle_offset=round(angle_offset, 1),
                                screen_x=cx,
                                screen_y=cy,
                                width=int(lbl.width),
                                height=int(lbl.height),
                            )
                        )

        if v_state is not None and v_state.objects:
            # A remembered pickup no longer among the level's objects was picked up.
            for remembered in self._landmarks.values():
                if remembered.object_id not in obj_pos_by_id:
                    remembered.gone = True

        grid_loc = f"sector_{int(px // 128)}_{int(py // 128)}"
        if grid_loc not in self._discovered_locations:
            self._discovered_locations.append(grid_loc)
            self._discovered_locations = self._discovered_locations[-16:]

        obs = Observation(
            tick=self._tick,
            health=health,
            armor=armor,
            ammo=ammo,
            current_weapon=weapon_name,
            visible_enemies=tuple(enemies),
            visible_pickups=tuple(pickups),
            landmarks=self._landmark_observations(px, py, angle, in_view),
            recent_incoming_damage=recent_in_dmg,
            recent_outgoing_damage=recent_out_dmg,
            recent_hits=recent_hits,
            recent_kills=recent_kills,
            movement_state=movement_state,
            recent_actions=tuple(self._action_history[-6:]),
            position=Pose3D(x=px, y=py, z=pz, angle=angle),
            episode_progress={
                "tick": float(self._tick),
                "episode_tick": float(self._episode_tick),
                "reward_so_far": round(self._total_reward, 2),
                **({"last_reward": round(self._last_reward, 2)} if self._last_reward is not None else {}),
                "kills": float(kills),
                **(
                    {"last_displacement": round(self._last_displacement, 1)}
                    if self._last_displacement is not None
                    else {}
                ),
            },
            frame_jpeg_b64=frame_b64,
            frame_brightness=round(brightness, 3),
            screen_width=screen_w,
            screen_height=screen_h,
            wall_distance_front=round(wall_front, 1),
            wall_distance_left=round(wall_left, 1),
            wall_distance_right=round(wall_right, 1),
        )
        mem = ControllerMemory(
            short_action_history=tuple(self._action_history[-10:]),
            recent_state_summaries=tuple(self._state_summaries[-5:]),
            discovered_locations=tuple(self._discovered_locations),
            strategy_archive_refs=strategy_refs,
        )
        return WorldState(observation=obs, memory=mem)

    def _remember(self, name: str, object_id: int, category: str, x: float, y: float) -> None:
        remembered = self._landmarks.get(object_id)
        if remembered is None:
            self._landmarks[object_id] = _Remembered(
                landmark_id=f"{name}_{object_id}", object_id=object_id, name=name, category=category,
                x=x, y=y, last_seen_tick=self._tick,
            )
        else:
            remembered.x, remembered.y, remembered.last_seen_tick = x, y, self._tick

    def _landmark_observations(self, px: float, py: float, facing: float, in_view: Set[int]) -> Tuple[LandmarkObservation, ...]:
        out = []
        for r in self._landmarks.values():
            if r.gone:
                continue
            agreement = r.agreement()
            out.append(
                LandmarkObservation(
                    landmark_id=r.landmark_id,
                    name=r.name,
                    category=r.category,  # type: ignore[arg-type]
                    x=round(r.x, 1),
                    y=round(r.y, 1),
                    distance=round(math.hypot(r.x - px, r.y - py), 1),
                    bearing=round(bearing_to(px, py, facing, r.x, r.y), 1),
                    in_view=r.object_id in in_view,
                    last_seen_tick=r.last_seen_tick,
                    reward_agreement=None if agreement is None else round(agreement, 3),
                    reward_moves=r.moves,
                    approaches_nowhere=r.approaches_nowhere,
                )
            )
        return tuple(out)

    def _landmark_by_id(self, landmark_id: Optional[str]) -> Optional[_Remembered]:
        if not landmark_id:
            return None
        return next((r for r in self._landmarks.values() if r.landmark_id == landmark_id and not r.gone), None)

    @staticmethod
    def _object_id(target_id: Optional[str]) -> Optional[int]:
        """The object id at the end of an enemy or pickup id such as `ShotgunGuy_2`."""
        if not target_id:
            return None
        tail = target_id.rsplit("_", 1)[-1]
        return int(tail) if tail.isdigit() else None

    def _learn_landmarks(self, x0: float, y0: float, reward: float) -> None:
        """Add one decision to every remembered pickup's record of how reward went with its distance."""
        x1 = self._safe_var(vzd.GameVariable.POSITION_X, x0)
        y1 = self._safe_var(vzd.GameVariable.POSITION_Y, y0)
        for r in self._landmarks.values():
            if r.gone:
                continue
            change = math.hypot(r.x - x1, r.y - y1) - math.hypot(r.x - x0, r.y - y0)
            if abs(change) < LANDMARK_MOVE_UNITS:
                continue
            r.moves += 1
            r.reward_closer += reward * -change
            r.distance_sq += change * change
            r.reward_sq += reward * reward

    @property
    def episode_cells_discovered(self) -> int:
        """Map cells (128 x 128 units) visited this episode, shown in the position channel."""
        return len(self._episode_cells)

    def execute_action(self, action: ActionSpec, targets: Optional[Any] = None) -> ExecutionStepResult:
        """Realize the selected action as a bounded closed-loop reflex burst.

        `targets` carries what d1-ultra chose for the motor's assistance: `enemy`, the visible enemy to aim
        at, and `pickup`, the remembered pickup a pickup-seeking action walks to (ids, either may be None).
        Without them the assistance has no target.
        """
        if self.game.is_episode_finished() and not self.auto_restart:
            return self._finished_result()
        self._episode_cells.add(self._current_cell())
        x0 = self._safe_var(vzd.GameVariable.POSITION_X, 0.0)
        y0 = self._safe_var(vzd.GameVariable.POSITION_Y, 0.0)
        steer = "pickup_id" in action.parameters
        pickup = self._landmark_by_id(getattr(targets, "pickup", None)) if steer else None
        before = math.hypot(pickup.x - x0, pickup.y - y0) if pickup is not None else 0.0
        # A walk at the pickup, not an arc round toward it: it starts with the pickup ahead, within the cone.
        walked_at = pickup is not None and abs(
            bearing_to(x0, y0, self._safe_var(vzd.GameVariable.ANGLE, 0.0), pickup.x, pickup.y)
        ) <= WALK_CONE_DEG
        enemy = self._object_id(getattr(targets, "enemy", None))
        burst = self.motor.burst(
            plan=action.primitive_expansion,
            steer_to_pickup=steer,
            step_delay_ms=self.step_delay_ms,
            enemy_target=enemy,
            pickup_target=(pickup.x, pickup.y) if pickup is not None else None,
        )
        if enemy is not None and any("shoot" in p for p in action.primitive_expansion) and not burst.episode_finished:
            # An attack on the chosen enemy: the evidence keeps how many in a row hit nothing.
            self._attacks_without_hit[enemy] = 0 if burst.hits_delta > 0 else self._attacks_without_hit.get(enemy, 0) + 1
        displacement = self._displacement(x0, y0)
        # The episode's first decision barely moves (the game is still starting): it is not a walk that failed.
        if pickup is not None and walked_at and self._episode_tick > 0 and not burst.episode_finished:
            x1 = self._safe_var(vzd.GameVariable.POSITION_X, x0)
            y1 = self._safe_var(vzd.GameVariable.POSITION_Y, y0)
            if before - math.hypot(pickup.x - x1, pickup.y - y1) < UNREACHABLE_PICKUP_PROGRESS:
                # Walking at this pickup got nowhere (a ledge, a wall, a full inventory): the evidence says so.
                pickup.approaches_nowhere += 1
        if not burst.episode_finished:
            self._learn_landmarks(x0, y0, burst.reward)
        return self._account(action.id, burst, displacement)

    def execute_idle(self, frames: int) -> ExecutionStepResult:
        """Hold no key for `frames` game frames: what a decision the central instance missed executes."""
        if self.game.is_episode_finished() and not self.auto_restart:
            return self._finished_result()
        self._episode_cells.add(self._current_cell())
        x0 = self._safe_var(vzd.GameVariable.POSITION_X, 0.0)
        y0 = self._safe_var(vzd.GameVariable.POSITION_Y, 0.0)
        burst = self.motor.idle(frames)
        displacement = self._displacement(x0, y0)
        if not burst.episode_finished:
            self._learn_landmarks(x0, y0, burst.reward)
        return self._account("missed", burst, displacement)

    @staticmethod
    def _finished_result() -> ExecutionStepResult:
        return ExecutionStepResult(
            reward=0.0,
            primitive_steps_executed=["idle"],
            terminated_early=True,
            episode_finished=True,
        )

    def _displacement(self, x0: float, y0: float) -> float:
        self._last_displacement = math.hypot(
            self._safe_var(vzd.GameVariable.POSITION_X, x0) - x0,
            self._safe_var(vzd.GameVariable.POSITION_Y, y0) - y0,
        )
        return self._last_displacement

    def _account(self, label: str, burst: MotorBurst, displacement: float) -> ExecutionStepResult:
        new_cells = 0
        if not burst.episode_finished:
            cell = self._current_cell()
            if cell not in self._episode_cells:
                self._episode_cells.add(cell)
                new_cells = 1
        self._action_history.extend(burst.primitives)
        self._tick += 1
        self._episode_tick += 1
        self._total_reward += burst.reward
        self._last_reward = burst.reward
        self._state_summaries.append(f"tick={self._tick} act={label} hp={burst.health_after:.0f} r={burst.reward:+.1f}")
        return ExecutionStepResult(
            reward=burst.reward,
            primitive_steps_executed=burst.primitives,
            terminated_early=burst.terminated_early,
            episode_finished=burst.episode_finished,
            frames_captured=burst.frames,
            damage_taken=burst.damage_taken,
            health_after=burst.health_after,
            kills_delta=burst.kills_delta,
            armor=burst.armor,
            hits_delta=burst.hits_delta,
            health_gain=burst.health_gain,
            armor_gain=burst.armor_gain,
            ammo_gain=burst.ammo_gain,
            died=burst.died,
            new_cells=new_cells,
            displacement=displacement,
        )

    def close(self) -> None:
        try:
            self.game.close()
        except Exception:
            pass
