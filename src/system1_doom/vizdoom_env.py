from __future__ import annotations

import base64
import io
import math
import os
from typing import Dict, List, Literal, Optional, Set, Tuple
import numpy as np
from PIL import Image
import vizdoom as vzd

from system1_doom.actions import ActionSpec
from system1_doom.motor import TacticalMotor, _screen_size, is_enemy_name, is_ignored_actor, is_pickup_name
from system1_doom.state import (
    ControllerMemory,
    EnemyObservation,
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


UNREACHABLE_PICKUP_PROGRESS = 12.0


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
        ammo_raw = self._safe_var(vzd.GameVariable.SELECTED_WEAPON_AMMO, 25.0)
        ammo = int(max(0.0, ammo_raw)) if ammo_raw >= 0 else 25
        weapon_id = int(self._safe_var(vzd.GameVariable.SELECTED_WEAPON, 2.0))
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
                    # Positive offset means the actor is left of the crosshair.
                    angle_offset = (center_x - cx) / max(1.0, center_x) * 45.0
                    if lbl.object_id in obj_pos_by_id:
                        ox, oy = obj_pos_by_id[lbl.object_id]
                        dist = math.hypot(ox - px, oy - py)
                    else:
                        dist = max(30.0, 3200.0 / max(8, lbl.height))

                    if is_enemy_name(lbl.object_name):
                        enemies.append(
                            EnemyObservation(
                                enemy_id=f"{lbl.object_name}_{lbl.object_id}_{idx}",
                                name=lbl.object_name,
                                distance=round(dist, 1),
                                angle_offset=round(angle_offset, 1),
                                screen_x=cx,
                                screen_y=cy,
                                width=int(lbl.width),
                                height=int(lbl.height),
                            )
                        )
                    elif is_pickup_name(lbl.object_name) and int(lbl.object_id) not in self.motor.ignored_pickups:
                        cat: Literal["health", "armor", "ammo", "weapon", "item"] = "item"
                        for k_sub, k_cat in PICKUP_CATEGORY_MAP.items():
                            if k_sub in name_low:
                                cat = k_cat
                                break
                        pickups.append(
                            PickupObservation(
                                pickup_id=f"{lbl.object_name}_{lbl.object_id}_{idx}",
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

    def execute_action(self, action: ActionSpec) -> ExecutionStepResult:
        """Realize the selected action as a bounded closed-loop reflex burst."""
        if self.game.is_episode_finished() and not self.auto_restart:
            return ExecutionStepResult(
                reward=0.0,
                primitive_steps_executed=["idle"],
                terminated_early=True,
                episode_finished=True,
            )

        self._episode_cells.add(self._current_cell())
        x0 = self._safe_var(vzd.GameVariable.POSITION_X, 0.0)
        y0 = self._safe_var(vzd.GameVariable.POSITION_Y, 0.0)
        steer = "pickup_id" in action.parameters
        burst = self.motor.burst(
            plan=action.primitive_expansion,
            steer_to_pickup=steer,
            step_delay_ms=self.step_delay_ms,
        )
        self._last_displacement = math.hypot(
            self._safe_var(vzd.GameVariable.POSITION_X, x0) - x0,
            self._safe_var(vzd.GameVariable.POSITION_Y, y0) - y0,
        )
        if steer and self.motor.last_pickup_target is not None and self._last_displacement < UNREACHABLE_PICKUP_PROGRESS:
            # Walking at this pickup got nowhere (ledge, wall, or a full inventory); stop chasing it this episode.
            self.motor.ignored_pickups.add(self.motor.last_pickup_target)
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
        self._state_summaries.append(
            f"tick={self._tick} act={action.id} hp={burst.health_after:.0f} r={burst.reward:+.1f}"
        )
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
            displacement=self._last_displacement,
        )

    def close(self) -> None:
        try:
            self.game.close()
        except Exception:
            pass
