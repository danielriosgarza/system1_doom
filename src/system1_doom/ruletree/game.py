"""The game: Deadly Corridor on ViZDoom, played one decision (8 tics) at a time.

`Game` renders the state Jev reads (the package's evidence channels, under the goal), presses the buttons of one
action, and judges each decision against the goal only: dying, stalling (the furthest point reached grew by less
than 48 units over 24 decisions), timing out, or clearing the level. It also reports where every enemy really is,
for the rule writer's diagnosis; that is never shown to Jev.

The outgoing channel also says how many decisions in a row the agent fired without hitting anything, so firing at
an enemy the shots cannot reach no longer looks like ordinary misses (a representation fix found by the soft loop;
the senses and central controller has its own form of it, per target, in the threats list).
"""

from __future__ import annotations

import math
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

import vizdoom as vzd

from system1_doom.evidence import EvidenceCounters, build_inputs, render_channel
from system1_doom.motor import is_enemy_name
from system1_doom.vizdoom_env import ViZDoomBridge

from .codes import buttons, describe, fires, segments
from .tree import CHANNELS, RuleTree
from .walk import Jev, decide

SCENARIO = "deadly_corridor.cfg"
GOAL = (
    "[goal]\nYou are the player in Doom's Deadly Corridor. Reach the green armor at the far end of the corridor alive. "
    "Enemies stand along both sides. Each action is held for about a quarter of a second, then you choose again."
)
STALL_WINDOW = 24  # decisions (about 5.5 s) ...
STALL_MIN = 48  # ... in which the furthest point reached along the corridor must grow by this much
MISSED_SHOTS_SHOWN = 2  # the outgoing channel names the run of fruitless firing from this many decisions on

# ViZDoom starts its engine from shared files; games are started one at a time.
_START = threading.Lock()


class Game:
    def __init__(self, scenario: str = SCENARIO) -> None:
        with _START:
            self.bridge = ViZDoomBridge(scenario=scenario, seed=0, window_visible=False)
        self.bridge.auto_restart = False
        self.g = self.bridge.game
        self.max_x: List[float] = []
        self.decisions = self.under_fire = self.stall = self.missed = 0

    def close(self) -> None:
        self.bridge.close()

    def var(self, name: str) -> float:
        return self.g.get_game_variable(getattr(vzd.GameVariable, name))

    def reset(self, seed: int) -> None:
        # Every game starts as on a new bridge, so a replay shows Jev the same state as the game it replays.
        self.bridge.restart_episode(seed)
        self.bridge.reset_tick_count()
        self.bridge._total_reward = 0.0
        self.bridge._discovered_locations.clear()
        self.max_x = [self.var("POSITION_X")]
        self.decisions = self.under_fire = self.stall = self.missed = 0

    def observe(self) -> Tuple[str, str]:
        """The state text Jev reads and the screen (base64 JPEG)."""
        ws = self.bridge.acquire_world_state()
        obs = ws.observation
        counters = EvidenceCounters(
            decisions=self.decisions,
            under_fire_streak=self.under_fire,
            stall_streak=self.stall,
            sectors_discovered=len(self.bridge._episode_cells),
        )
        inputs = build_inputs(ws, menu=[], counters=counters)
        text = GOAL + "\n\n" + "\n\n".join(render_channel(inputs, c) for c in CHANNELS)
        if self.missed >= MISSED_SHOTS_SHOWN:
            head = "[outgoing]\n"
            before, after = text.split(head, 1)
            line, rest = after.split("\n", 1)
            text = before + head + line + f"; the last {self.missed} decisions in which you fired hit nothing\n" + rest
        return text, obs.frame_jpeg_b64

    def truth(self) -> List[Dict[str, Any]]:
        """For the rule writer's diagnosis only: every enemy the engine knows, relative to the player."""
        st = self.g.get_state()
        on_screen = {label.object_id for label in st.labels}
        px, py, ang = self.var("POSITION_X"), self.var("POSITION_Y"), self.var("ANGLE")
        rows = []
        for o in st.objects:
            if not is_enemy_name(o.name):
                continue
            dx, dy = o.position_x - px, o.position_y - py
            bearing = (math.degrees(math.atan2(dy, dx)) - ang + 180) % 360 - 180
            side = "ahead" if abs(bearing) <= 45 else ("left" if bearing > 0 else "right") if abs(bearing) <= 135 else "behind"
            rows.append({"name": o.name, "id": o.id, "dist": round(math.hypot(dx, dy)), "bearing": round(bearing),
                         "side": side, "on_screen": o.id in on_screen})
        return sorted(rows, key=lambda r: r["dist"])

    def step(self, code: str) -> Dict[str, Any]:
        """Press one action's buttons for its 8 tics; the decision's outcome."""
        b = self.bridge
        x0, y0, h0, r0 = self.var("POSITION_X"), self.var("POSITION_Y"), self.var("HEALTH"), self.g.get_total_reward()
        hits0 = self.var("HITCOUNT")
        b._episode_cells.add(b._current_cell())
        for seg, tics in segments(code):
            self.g.make_action(buttons(seg), tics)
            if self.g.is_episode_finished():
                break
        finished = self.g.is_episode_finished()
        reward = self.g.get_total_reward() - r0
        if not finished:
            self.missed = 0 if self.var("HITCOUNT") > hits0 else self.missed + 1 if fires(code) else self.missed
        out: Dict[str, Any] = {"code": code, "health_before": h0, "reward": round(reward, 1), "finished": finished}
        if finished:
            dead = bool(self.g.is_player_dead())
            out.update(died=dead, health_after=0.0 if dead else h0)
        else:
            out.update(died=False, health_after=self.var("HEALTH"), x=round(self.var("POSITION_X")), y=round(self.var("POSITION_Y")),
                       angle=round(self.var("ANGLE")), armor=self.var("ARMOR"), kills=self.var("KILLCOUNT"))
            self.stall = 0 if self.var("POSITION_X") > self.max_x[-1] + 8 else self.stall + 1
            self.max_x.append(max(self.max_x[-1], self.var("POSITION_X")))
            self.under_fire = self.under_fire + 1 if out["health_after"] < h0 else 0
            b._last_displacement = math.hypot(self.var("POSITION_X") - x0, self.var("POSITION_Y") - y0)
            b._learn_landmarks(x0, y0, reward)
        self.decisions += 1
        b._action_history.append(describe(code))
        b._tick += 1
        b._episode_tick += 1
        b._total_reward += reward
        b._last_reward = reward
        b._state_summaries.append(f"tick={b._tick} act={describe(code)} hp={out['health_after']:.0f} r={reward:+.1f}")
        return out

    def events(self, rec: Dict[str, Any]) -> List[str]:
        """The unwanted events of a decision, judged against the goal only: dying, timing out, or not getting further."""
        if rec["died"]:
            return ["died"]
        if rec["finished"]:
            return [] if self.bridge.level_cleared() else ["timed out"]
        if len(self.max_x) > STALL_WINDOW and self.max_x[-1] - self.max_x[-1 - STALL_WINDOW] < STALL_MIN:
            return ["stalled"]
        return []

    def cleared(self) -> bool:
        return self.bridge.level_cleared()


def play(
    game: Game,
    tree: RuleTree,
    jev: Jev,
    seed: int,
    prefix: Sequence[str] = (),
    stop_after: Optional[int] = None,
    keep_frames: bool = True,
    stop_on_event: bool = True,
) -> List[Dict[str, Any]]:
    """Replay `prefix` (actions, no Jev), then decide with the tree until the first unwanted event, the end of the
    game, or decision `stop_after`. One record per decision."""
    game.reset(seed)
    trace: List[Dict[str, Any]] = []
    i = 0
    while True:
        text, frame = game.observe()
        if i < len(prefix):
            code, node, route, steps, missed = prefix[i], "replay", "replay", [], False
        else:
            d = decide(tree, jev, text, frame, seed, i)
            code, node, route, steps, missed = d.action, d.node, d.route, [s.model_dump(exclude_none=True) for s in d.steps], d.missed
        truth = game.truth()
        rec = game.step(code)
        rec.update(i=i, node=node, route=route, steps=steps, missed=missed, truth=truth, max_x=round(game.max_x[-1]))
        if keep_frames:
            rec.update(text=text, frame=frame)
        rec["events"] = game.events(rec)
        rec["cleared"] = rec["finished"] and not rec["events"]
        trace.append(rec)
        i += 1
        if rec["finished"] or (stop_on_event and rec["events"] and i > len(prefix)) or (stop_after is not None and i > stop_after):
            return trace


def outcome(trace: List[Dict[str, Any]]) -> str:
    """How a played game ended: cleared, died, stalled, timed out, or (cut short) none."""
    last = trace[-1]
    if last["events"]:
        return last["events"][0]
    return "cleared" if last.get("cleared") else "none"
