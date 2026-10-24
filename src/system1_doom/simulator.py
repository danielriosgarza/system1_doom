from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from system1_doom.actions import ActionSpec
from system1_doom.state import EnemyObservation, Observation, PickupObservation, Pose3D, WorldState


class ProjectionLimits(BaseModel):
    """Explicit bounds for short-horizon projections (Spec Section 8)."""

    model_config = ConfigDict(frozen=True)

    max_candidate_count: int = Field(default=16, ge=1, le=32)
    max_simulation_depth: int = Field(default=4, ge=1, le=16)
    max_wall_clock_budget_sec: float = Field(default=0.015, gt=0.0, le=1.0)
    max_branching_factor: int = Field(default=2, ge=1, le=4)


class ProjectedOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    depth_reached: int
    projected_states: Tuple[WorldState, ...]
    branch_values: Tuple[float, ...]
    expected_value: float
    expected_damage_taken: float
    expected_damage_dealt: float
    expected_resource_gain: float
    expected_positional_progress: float
    survival_probability: float = Field(ge=0.0, le=1.0)
    empirical_samples: int = 0


class BoundedSimulator:
    """
    Approximate short-horizon simulator with strict candidate, depth, branching,
    and wall-clock bounds, plus empirical transition caching.
    """

    def __init__(self, limits: ProjectionLimits = ProjectionLimits()) -> None:
        self.limits = limits
        self._empirical_cache: Dict[Tuple[str, str], List[Tuple[float, float]]] = {}

    def record_empirical_outcome(
        self, context_signature: str, action_id: str, reward_delta: float, damage_taken: float
    ) -> None:
        key = (context_signature, action_id)
        bucket = self._empirical_cache.setdefault(key, [])
        bucket.append((reward_delta, damage_taken))
        if len(bucket) > 50:
            bucket.pop(0)

    def _step_primitive(
        self, state: WorldState, primitive: str, enemy_aggressiveness: float = 1.0
    ) -> Tuple[WorldState, float, float, float, float]:
        obs = state.observation
        step_dist = 28.0
        turn_deg = 18.0
        rad = math.radians(obs.position.angle)

        dx, dy, d_angle = 0.0, 0.0, 0.0
        evasion_factor = 1.0
        dmg_dealt = 0.0
        resource_gain = 0.0
        pos_progress = 0.0
        ammo_next = obs.ammo

        if primitive == "move_forward":
            eff = min(step_dist, max(0.0, obs.wall_distance_front - 8.0))
            dx = eff * math.cos(rad)
            dy = eff * math.sin(rad)
            # Advancing when corridor is clear yields strong progress; advancing into close enemy fire is risky
            pos_progress += (eff / 20.0) * (1.4 if not obs.visible_enemies else 0.3)
            evasion_factor = 0.90
        elif primitive == "move_backward":
            dx = -step_dist * math.cos(rad)
            dy = -step_dist * math.sin(rad)
            pos_progress -= 0.4
            evasion_factor = 0.45
        elif primitive in ("strafe_left", "strafe_left_shoot"):
            dx = step_dist * math.cos(rad + math.pi / 2)
            dy = step_dist * math.sin(rad + math.pi / 2)
            pos_progress += 0.15
            evasion_factor = 0.35
        elif primitive in ("strafe_right", "strafe_right_shoot"):
            dx = step_dist * math.cos(rad - math.pi / 2)
            dy = step_dist * math.sin(rad - math.pi / 2)
            pos_progress += 0.15
            evasion_factor = 0.35
        elif primitive == "turn_left":
            left_enemies = [e for e in obs.visible_enemies if e.angle_offset > 0]
            if left_enemies:
                target_e = min(left_enemies, key=lambda e: e.distance)
                d_angle = min(28.0, max(4.0, target_e.angle_offset))
            else:
                d_angle = turn_deg
            evasion_factor = 0.75
        elif primitive == "turn_right":
            right_enemies = [e for e in obs.visible_enemies if e.angle_offset < 0]
            if right_enemies:
                target_e = min(right_enemies, key=lambda e: e.distance)
                d_angle = -min(28.0, max(4.0, abs(target_e.angle_offset)))
            else:
                d_angle = -turn_deg
            evasion_factor = 0.75
        elif primitive == "shoot" and obs.ammo > 0:
            ammo_next = max(0, obs.ammo - 1)
            evasion_factor = 0.85
            if obs.visible_enemies:
                best_enemy = min(obs.visible_enemies, key=lambda e: e.distance + abs(e.angle_offset) * 3.0)
                # Motor controller aligns within +-15 deg on shoot; stronger alignment yields higher damage
                if abs(best_enemy.angle_offset) <= 15.0:
                    align = 1.0
                    d_angle = best_enemy.angle_offset
                else:
                    align = max(0.25, 1.0 - (abs(best_enemy.angle_offset) - 15.0) / 45.0)
                dist_factor = max(0.35, 1.0 - best_enemy.distance / 800.0)
                dmg_dealt = 40.0 * align * dist_factor
        elif primitive == "use":
            pos_progress += 0.4 if obs.wall_distance_front < 64.0 else 0.0

        if primitive.endswith("_shoot") and obs.ammo > 0 and obs.visible_enemies:
            ammo_next = max(0, obs.ammo - 1)
            best_enemy = min(obs.visible_enemies, key=lambda e: e.distance + abs(e.angle_offset) * 3.0)
            align = 1.0 if abs(best_enemy.angle_offset) <= 15.0 else max(0.25, 1.0 - (abs(best_enemy.angle_offset) - 15.0) / 45.0)
            dmg_dealt = 32.0 * align * max(0.35, 1.0 - best_enemy.distance / 800.0)

        # Update enemy distances and calculate expected incoming damage
        new_enemies: List[EnemyObservation] = []
        base_threat = 0.0
        for e in obs.visible_enemies:
            dist_delta = -14.0 if primitive == "move_forward" else (18.0 if primitive == "move_backward" else -2.0)
            next_dist = max(20.0, e.distance + dist_delta)
            next_angle = e.angle_offset - d_angle
            new_enemies.append(
                EnemyObservation(
                    enemy_id=e.enemy_id,
                    name=e.name,
                    distance=next_dist,
                    angle_offset=next_angle,
                    screen_x=e.screen_x,
                    screen_y=e.screen_y,
                    width=e.width,
                    height=e.height,
                    is_attacking=e.is_attacking,
                )
            )
            proximity_risk = max(0.0, (450.0 - next_dist) / 450.0)
            base_threat += 8.0 * (proximity_risk + 0.25)

        if obs.recent_incoming_damage > 0 and not obs.visible_enemies:
            base_threat += obs.recent_incoming_damage * 0.6

        suppression = 0.55 if dmg_dealt >= 18.0 else 1.0
        dmg_taken = base_threat * evasion_factor * suppression * enemy_aggressiveness

        # Check pickup collection / approach
        new_pickups: List[PickupObservation] = []
        for p in obs.visible_pickups:
            if primitive == "move_forward":
                next_p_dist = max(0.0, p.distance - step_dist)
                if next_p_dist < 160.0 or not obs.visible_enemies:
                    resource_gain += 14.0 if p.category in ("health", "armor", "weapon") else 9.0
                new_pickups.append(p.model_copy(update={"distance": next_p_dist}))
            else:
                new_pickups.append(p)

        next_health = max(0.0, min(200.0, obs.health - dmg_taken + (resource_gain * 0.4 if resource_gain > 0 else 0.0)))
        next_obs = obs.model_copy(
            update={
                "tick": obs.tick + 1,
                "health": next_health,
                "ammo": ammo_next,
                "visible_enemies": tuple(new_enemies),
                "visible_pickups": tuple(new_pickups),
                "recent_incoming_damage": dmg_taken,
                "recent_outgoing_damage": dmg_dealt,
                "recent_actions": tuple(list(obs.recent_actions[-5:]) + [primitive]),
                "position": Pose3D(
                    x=obs.position.x + dx,
                    y=obs.position.y + dy,
                    z=obs.position.z,
                    angle=(obs.position.angle + d_angle) % 360.0,
                ),
            }
        )
        return WorldState(observation=next_obs, memory=state.memory), dmg_taken, dmg_dealt, resource_gain, pos_progress

    def project_action(self, state: WorldState, action: ActionSpec, limits: Optional[ProjectionLimits] = None) -> ProjectedOutcome:
        cfg = limits or self.limits
        steps = action.primitive_expansion[: cfg.max_simulation_depth]

        branch_scales = [1.0, 1.35, 0.7, 1.6][: cfg.max_branching_factor]
        branch_values: List[float] = []
        primary_states: List[WorldState] = []
        primary_dmg_taken = 0.0
        primary_dmg_dealt = 0.0
        primary_res_gain = 0.0
        primary_pos_prog = 0.0

        for b_idx, scale in enumerate(branch_scales):
            cur = state
            tot_taken = 0.0
            tot_dealt = 0.0
            tot_res = 0.0
            tot_pos = 0.0
            for prim in steps:
                cur, dt, dd, rg, pp = self._step_primitive(cur, prim, enemy_aggressiveness=scale)
                tot_taken += dt
                tot_dealt += dd
                tot_res += rg
                tot_pos += pp
                if b_idx == 0:
                    primary_states.append(cur)

            steps_len = max(1, len(steps))
            val = (
                (tot_dealt * 0.12)
                + (tot_res * 0.14)
                + (tot_pos * 0.18)
                - ((tot_taken / steps_len) * (0.18 if state.observation.health <= 40 else 0.09))
                - action.execution_cost
            )
            branch_values.append(val)
            if b_idx == 0:
                primary_dmg_taken = tot_taken
                primary_dmg_dealt = tot_dealt
                primary_res_gain = tot_res
                primary_pos_prog = tot_pos

        n_steps = max(1, len(primary_states))
        norm_dmg_taken = primary_dmg_taken / n_steps
        expected_val = sum(branch_values) / max(1, len(branch_values))
        emp = self._empirical_cache.get((state.context_signature(), action.id), [])
        if emp:
            emp_reward = sum(r for r, _ in emp) / len(emp)
            emp_dmg = sum(d for _, d in emp) / len(emp)
            expected_val = 0.6 * expected_val + 0.4 * (emp_reward * 0.1 - emp_dmg * 0.05)

        final_hp = max(0.0, state.observation.health - norm_dmg_taken)
        survival_prob = max(0.0, min(1.0, final_hp / 100.0))

        return ProjectedOutcome(
            action_id=action.id,
            depth_reached=len(primary_states),
            projected_states=tuple(primary_states),
            branch_values=tuple(branch_values),
            expected_value=expected_val,
            expected_damage_taken=norm_dmg_taken,
            expected_damage_dealt=primary_dmg_dealt,
            expected_resource_gain=primary_res_gain,
            expected_positional_progress=primary_pos_prog,
            survival_probability=survival_prob,
            empirical_samples=len(emp),
        )

    def project_candidates(
        self,
        state: WorldState,
        candidates: List[ActionSpec],
        limits: Optional[ProjectionLimits] = None,
    ) -> Dict[str, ProjectedOutcome]:
        cfg = limits or self.limits
        deadline = time.perf_counter() + cfg.max_wall_clock_budget_sec
        results: Dict[str, ProjectedOutcome] = {}

        for action in candidates[: cfg.max_candidate_count]:
            if results and time.perf_counter() >= deadline:
                break
            results[action.id] = self.project_action(state, action, limits=cfg)
        return results
