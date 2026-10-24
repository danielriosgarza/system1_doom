from __future__ import annotations

import hashlib
import json
from typing import Dict, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field


class Pose3D(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    angle: float = 0.0


class EnemyObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    enemy_id: str
    name: str
    distance: float = Field(ge=0.0)
    angle_offset: float = 0.0
    screen_x: int = 160
    screen_y: int = 120
    width: int = 20
    height: int = 40
    is_attacking: bool = False


class PickupObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    pickup_id: str
    name: str
    category: Literal["health", "armor", "ammo", "weapon", "item"] = "item"
    distance: float = Field(ge=0.0)
    angle_offset: float = 0.0
    screen_x: int = 160
    screen_y: int = 120


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)

    tick: int = 0
    health: float = 100.0
    armor: float = 0.0
    ammo: int = 50
    current_weapon: str = "pistol"
    visible_enemies: Tuple[EnemyObservation, ...] = ()
    visible_pickups: Tuple[PickupObservation, ...] = ()
    recent_incoming_damage: float = 0.0
    recent_outgoing_damage: float = 0.0
    recent_kills: int = 0
    movement_state: str = "stationary"
    recent_actions: Tuple[str, ...] = ()
    position: Pose3D = Field(default_factory=Pose3D)
    episode_progress: Dict[str, float] = Field(default_factory=dict)
    frame_jpeg_b64: Optional[str] = None
    frame_brightness: float = 0.5
    screen_width: int = 320
    screen_height: int = 240
    wall_distance_front: float = 256.0
    wall_distance_left: float = 128.0
    wall_distance_right: float = 128.0


class ControllerMemory(BaseModel):
    model_config = ConfigDict(frozen=True)

    short_action_history: Tuple[str, ...] = ()
    recent_state_summaries: Tuple[str, ...] = ()
    discovered_locations: Tuple[str, ...] = ()
    strategy_archive_refs: Tuple[str, ...] = ()


class WorldState(BaseModel):
    """Immutable normalized state object S_t shared across all modules in one tick."""

    model_config = ConfigDict(frozen=True)

    observation: Observation
    memory: ControllerMemory = Field(default_factory=ControllerMemory)

    def state_hash(self) -> str:
        obs = self.observation
        payload = {
            "tick": obs.tick,
            "health": round(obs.health, 1),
            "armor": round(obs.armor, 1),
            "ammo": obs.ammo,
            "weapon": obs.current_weapon,
            "enemies": [(e.name, round(e.distance, 0), round(e.angle_offset, 0)) for e in obs.visible_enemies],
            "pickups": [(p.name, p.category, round(p.distance, 0)) for p in obs.visible_pickups],
            "in_dmg": round(obs.recent_incoming_damage, 1),
            "out_dmg": round(obs.recent_outgoing_damage, 1),
            "pos": (round(obs.position.x, 0), round(obs.position.y, 0), round(obs.position.angle, 0)),
            "recent_actions": list(obs.recent_actions[-4:]),
        }
        raw = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def context_signature(self) -> str:
        """Coarse discrete bucket signature for strategy archive and novelty tracking."""
        obs = self.observation
        hp_bucket = "critical" if obs.health <= 30 else ("medium" if obs.health <= 65 else "healthy")
        ammo_bucket = "empty" if obs.ammo <= 0 else ("low" if obs.ammo <= 8 else "stocked")
        enemy_count = len(obs.visible_enemies)
        nearest_enemy = min((e.distance for e in obs.visible_enemies), default=9999.0)
        range_bucket = (
            "none"
            if enemy_count == 0
            else ("melee" if nearest_enemy < 140 else ("mid" if nearest_enemy < 420 else "far"))
        )
        dmg_bucket = "under_fire" if obs.recent_incoming_damage > 0 else "clear"
        pickup_bucket = "pickup_visible" if len(obs.visible_pickups) > 0 else "no_pickup"
        return f"hp:{hp_bucket}|ammo:{ammo_bucket}|enemies:{enemy_count}:{range_bucket}|dmg:{dmg_bucket}|pickup:{pickup_bucket}"

    def to_d1_state_text(self) -> str:
        """Compact, structured state description passed to Liquid AI d1-ultra."""
        obs = self.observation
        enemies_str = (
            ", ".join(
                f"{e.name}(id={e.enemy_id}, dist={e.distance:.0f}, angle={e.angle_offset:+.0f}deg, x={e.screen_x})"
                for e in obs.visible_enemies
            )
            if obs.visible_enemies
            else "none"
        )
        pickups_str = (
            ", ".join(
                f"{p.name}(id={p.pickup_id}, cat={p.category}, dist={p.distance:.0f}, angle={p.angle_offset:+.0f}deg)"
                for p in obs.visible_pickups
            )
            if obs.visible_pickups
            else "none"
        )
        progress_str = ", ".join(f"{k}={v:.1f}" for k, v in sorted(obs.episode_progress.items()))
        return (
            f"DOOM_STATE_SNAPSHOT tick={obs.tick} hash={self.state_hash()} context={self.context_signature()}\n"
            f"Player: health={obs.health:.1f}, armor={obs.armor:.1f}, ammo={obs.ammo}, weapon={obs.current_weapon}, "
            f"movement={obs.movement_state}, pos=({obs.position.x:.0f},{obs.position.y:.0f},angle={obs.position.angle:.0f})\n"
            f"Combat Deltas: recent_incoming_damage={obs.recent_incoming_damage:.1f}, "
            f"recent_outgoing_damage={obs.recent_outgoing_damage:.1f}, recent_kills={obs.recent_kills}\n"
            f"Geometry: wall_front={obs.wall_distance_front:.0f}, wall_left={obs.wall_distance_left:.0f}, wall_right={obs.wall_distance_right:.0f}\n"
            f"Visible Enemies ({len(obs.visible_enemies)}): {enemies_str}\n"
            f"Visible Pickups ({len(obs.visible_pickups)}): {pickups_str}\n"
            f"Episode Progress: {progress_str or 'none'}\n"
            f"Memory: recent_actions={list(self.memory.short_action_history[-6:])}, "
            f"recent_summaries={list(self.memory.recent_state_summaries[-3:])}"
        )
