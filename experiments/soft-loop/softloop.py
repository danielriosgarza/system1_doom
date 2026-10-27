"""The soft loop: play, stop at the first unwanted event, write one rule, check it, play again.

A rule is a condition Jev answers from the agent's state, plus what to do while it holds. Rules nest as
exceptions (Ripple-Down Rules): at a node with children Jev chooses which child's condition holds now, or
none, and the deepest node reached gives the action. Where no rule is reached the agent walks randomly.
The engine only plays and replays; it never answers a condition.

  play   RUN SEED             play from the start with the current rules until the first unwanted event
  check  RUN RULE.json        test a proposed rule: Jev sees it, it avoids the event, older frames unchanged
  commit RUN RULE.json        add a rule that passed its check to the tree
  show   RUN                  print the rule tree
  eval   RUN LO-HI            play seeds LO..HI once each, in parallel, with fresh Jev answers
  gate   RUN RULE.json LO-HI  play seeds LO..HI with the current tree and with the rule, side by side

An action is a code held for the whole decision (`F001`), or a sequence inside the decision that adds up to its
8 tics (`00R0:3+0001:5`: turn right for 3 tics, then fire for 5).

Two structures keep rules general rather than tied to one scene:
- a node may have a `focus`: when the walk enters it, Jev picks one item from some channels of the state (for
  example the most dangerous enemy in the threats list), and that item is shown to Jev below as the [focus]
  channel, so the rules under it speak of "the focus" instead of naming enemy types;
- an action may call a `skill`, a shared subtree (`{"skill": "aim", "then": "0001"}`): the walk goes on in the
  skill, whose rules may give part of a decision (`00R0:3`, turn for 3 tics) that the caller's `then` completes,
  or `then` itself. One aiming skill then serves shooting, walking to the goal, and anything added later.
"""
import base64
import hashlib
import io
import json
import math
import os
import random
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
import vizdoom as vzd
from PIL import Image

from system1_doom.d1_client import load_api_key
from system1_doom.evidence import EvidenceCounters, build_inputs, render_channel
from system1_doom.motor import is_enemy_name
from system1_doom.vizdoom_env import ViZDoomBridge

MODEL = "jev-1.14.0"
KEY = load_api_key("jev")  # TYPESAFE_API_KEY from the environment or .env; without one the request goes keyless
URL = "https://api.typesafe.ai/v1/systemone"
BASE = Path(os.environ.get("SOFTLOOP_BASE", Path(__file__).parent / "runs"))
TICS = 8                 # one decision holds its buttons for 8 tics, about a quarter of a second
STALL_WINDOW = 24        # decisions (about 5.5 s) ...
STALL_MIN = 48           # ... in which the furthest point reached along the corridor must grow by this much
DOSSIER_WINDOW = 12      # decisions shown before the event
AVOID_MARGIN = 24        # decisions played past the original event when checking a rule
CHANNELS = ["vitals", "threats", "incoming", "outgoing", "pickups", "landmarks", "geometry", "position", "progress", "history"]
GOAL = ("[goal]\nYou are the player in Doom's Deadly Corridor. Reach the green armor at the far end of the corridor alive. "
        "Enemies stand along both sides. Each action is held for about a quarter of a second, then you choose again.")
NODE_QUESTION = "Which of these is true right now?"
NONE_TEXT = "None of these is true right now."
MENU_QUESTION = "Which of these should I do right now?"

AXES = [
    ("walk", {"F": "walk forward", "0": "no walking", "B": "walk backward"}),
    ("strafe", {"L": "sidestep left", "0": "no sidestep", "R": "sidestep right"}),
    ("turn", {"L": "turn left", "0": "no turning", "R": "turn right"}),
    ("fire", {"1": "fire", "0": "no firing"}),
]
COMBOS = ["".join((w, s, t, f)) for w in "F0B" for s in "L0R" for t in "L0R" for f in "10"]


def segments(action, partial=False):
    """An action is a code held for the whole decision, or `CODE:TICS+CODE:TICS...` adding up to one decision
    (or, inside a skill, to less: the caller's `then` does the rest)."""
    if ":" not in action:
        return [(action, TICS)]
    segs = [(c, int(t)) for c, t in (part.split(":") for part in action.split("+"))]
    total = sum(t for _, t in segs)
    assert (total < TICS if partial and total != TICS else total == TICS) and all(c in COMBOS for c, _ in segs), action
    return segs


def complete(action, then):
    """A skill's partial action finished with the caller's `then` code for the tics left."""
    if action == "then":
        return then
    left = TICS - sum(t for _, t in segments(action, partial=True))
    return action if left == 0 else f"{action}+{then}:{left}"


def check_action(action, in_skill=False):
    if isinstance(action, dict):
        assert set(action) == {"skill", "then"} and action["then"] in COMBOS, action
    elif isinstance(action, str) and action not in ("random", "then"):
        segments(action, partial=in_skill)


def describe(action):
    def one(code):
        parts = [AXES[i][1][v] for i, v in enumerate(code) if v != "0"]
        return " + ".join(parts) if parts else "stand still"
    if isinstance(action, dict):
        return f"use skill {action['skill']}, then {one(action['then'])}"
    if action == "then":
        return "the caller's action"
    segs = segments(action, partial=True)
    if len(segs) == 1 and segs[0][1] == TICS:
        return one(segs[0][0])
    text = ", then ".join(f"{one(c)} for {t} tics" for c, t in segs)
    return text if sum(t for _, t in segs) == TICS else text + ", then the caller's action"


def buttons(code):
    w, s, t, f = code
    # MOVE_LEFT, MOVE_RIGHT, ATTACK, MOVE_FORWARD, MOVE_BACKWARD, TURN_LEFT, TURN_RIGHT
    return [int(x) for x in (s == "L", s == "R", f == "1", w == "F", w == "B", t == "L", t == "R")]


def random_code(seed, step):
    return random.Random(f"{seed}:{step}").choice(COMBOS)


# --------------------------------------------------------------------------- Jev, with a cache per run

class Jev:
    """Plays ask afresh (`read=False`) and keep their answers in their own shard; checks reuse every shard, so a
    replayed state gets the answer it got in play and the old and new trees are compared on equal terms."""

    def __init__(self, run_dir, read=True, shard="jev-cache.json"):
        self.path = run_dir / shard
        self.cache = {}
        if read:
            for p in sorted(run_dir.glob("jev-cache*.json")):
                self.cache.update(json.loads(p.read_text()))
        self.lock = threading.Lock()
        self.calls = 0
        self.seconds = 0.0

    def save(self):
        with self.lock:
            self.path.write_text(json.dumps(self.cache))

    def ask(self, text, frame_b64, instructions, criteria):
        key = hashlib.sha256(json.dumps([MODEL, text, frame_b64, instructions, sorted(criteria.items())]).encode()).hexdigest()
        with self.lock:
            if key in self.cache:
                return self.cache[key]
        ref = str(uuid.uuid4())
        body = {"model": MODEL, "state": text + "\n\n[screen image]\n" + ref, "assets": {ref: _asset(frame_b64)},
                "questions": {"q": {"type": "choice", "instructions": instructions, "criteria": criteria}}}
        headers = {"Content-Type": "application/json", "TypeSafe-Danger-Zone-Images": "true"}
        if KEY:
            headers["Authorization"] = f"Bearer {KEY}"
        t0 = time.time()
        for attempt in range(5):
            try:
                r = requests.post(URL, json=body, headers=headers, timeout=60)
            except requests.RequestException as e:
                err = str(e)
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                probs = r.json()["answers"]["q"]["probabilities"]
                with self.lock:
                    self.cache[key] = probs
                    self.calls += 1
                    self.seconds += time.time() - t0
                return probs
            err = f"{r.status_code} {r.text[:300]}"
            time.sleep(2 ** attempt)
        raise RuntimeError(err)


def _asset(frame_b64):
    img = Image.open(io.BytesIO(base64.b64decode(frame_b64))).convert("RGB")
    img = img.resize((img.width * 2, img.height * 2), Image.Resampling.NEAREST)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return {"type": "image", "format": "jpeg", "data_base64": base64.b64encode(out.getvalue()).decode()}


# --------------------------------------------------------------------------- the rule tree

def load_tree(run_dir):
    p = run_dir / "tree.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"root": {"id": "root", "parent": None, "condition": None, "action": "random", "children": [], "cornerstones": []}}


def items(text, channel):
    """The listed items of one channel of the state, word for word as Jev reads them."""
    head = f"[{channel}]\n"
    if head not in text:
        return []
    block = text.split(head, 1)[1].split("\n\n", 1)[0]
    return [line[2:] for line in block.splitlines() if line.startswith("- ")]


def with_focus(text, frame, node, jev, path):
    """Jev picks the focus among the items of the node's channels; the state gains a [focus] channel naming it."""
    text = text.split("\n\n[focus]\n", 1)[0]
    f = node["focus"]
    options = [(ch, it) for ch in f["from"] for it in items(text, ch)]
    if len(options) > 1:
        probs = jev.ask(text, frame, f["question"], {f"i{k}": it for k, (_, it) in enumerate(options)})
        k = max(probs, key=probs.get)
        chosen, p = options[int(k[1:])], round(probs[k], 3)
    else:
        chosen, p = (options[0] if options else None), 1.0
    path.append({"focus": node["id"], "pick": chosen[1] if chosen else None, "p": p})
    line = f"{chosen[1]} (from the {chosen[0]} list)" if chosen else "nothing"
    return text + f"\n\n[focus]\n{line}"


def decide(tree, jev, text, frame, seed, step):
    """Walk the tree with Jev: the deepest node whose condition holds gives the action. A node with a focus first
    has Jev pick it; an action that calls a skill goes on walking in the skill, which the caller's `then` completes."""
    node, path, then = tree["root"], [], None
    while True:
        if node.get("focus"):
            text = with_focus(text, frame, node, jev, path)
        if node["children"]:
            criteria = {c: tree[c]["condition"] for c in node["children"]}
            criteria["none"] = NONE_TEXT
            probs = jev.ask(text, frame, NODE_QUESTION, criteria)
            pick = max(probs, key=probs.get)
            path.append({"at": node["id"], "pick": pick, "p": round(probs[pick], 3)})
            if pick != "none":
                node = tree[pick]
                continue
        if isinstance(node["action"], dict):
            then = node["action"]["then"]
            path.append({"skill": node["action"]["skill"], "from": node["id"]})
            node = tree[node["action"]["skill"]]
            continue
        break
    action = node["action"]
    if action == "random":
        code = random_code(seed, step)
    elif isinstance(action, list):
        probs = jev.ask(text, frame, MENU_QUESTION, {c: describe(c) for c in action})
        code = max(probs, key=probs.get)
        path.append({"menu": node["id"], "pick": code, "p": round(probs[code], 3)})
    elif then is not None:
        code = complete(action, then)
    else:
        code = action
    return code, node["id"], path


# --------------------------------------------------------------------------- the game

class Game:
    def __init__(self):
        self.bridge = ViZDoomBridge(scenario="deadly_corridor.cfg", seed=0, window_visible=False)
        self.bridge.auto_restart = False
        self.g = self.bridge.game

    def var(self, name):
        return self.g.get_game_variable(getattr(vzd.GameVariable, name))

    def reset(self, seed):
        self.bridge.restart_episode(seed)
        self.max_x = [self.var("POSITION_X")]
        self.decisions = self.under_fire = self.stall = self.missed = 0

    def observe(self):
        ws = self.bridge.acquire_world_state()
        # Representation fix (round 9): the bridge maps screen offset to angle linearly (offset x 45 degrees), which
        # understates every angle; the true angle of a point on a 90-degree-wide screen is atan(offset).
        obs = ws.observation
        half = obs.screen_width / 2.0
        fixed = tuple(e.model_copy(update={"angle_offset": round(math.degrees(math.atan((half - e.screen_x) / half)), 1)})
                      for e in obs.visible_enemies)
        ws = ws.model_copy(update={"observation": obs.model_copy(update={"visible_enemies": fixed})})
        counters = EvidenceCounters(decisions=self.decisions, under_fire_streak=self.under_fire, stall_streak=self.stall,
                                    sectors_discovered=len(self.bridge._episode_cells))
        inputs = build_inputs(ws, menu=[], counters=counters)
        text = GOAL + "\n\n" + "\n\n".join(render_channel(inputs, c) for c in CHANNELS)
        # Representation fix (v3): the outgoing channel only told the last decision's hits, so firing at an enemy
        # that the shots never reach (behind the edge of a wall) looked the same as ordinary misses. It now also
        # remembers how many decisions in a row the agent fired without hitting anything.
        if self.missed >= 2:
            head = "[outgoing]\n"
            a, b = text.split(head, 1)
            line, rest = b.split("\n", 1)
            text = a + head + line + f"; the last {self.missed} decisions in which you fired hit nothing\n" + rest
        return text, ws.observation.frame_jpeg_b64

    def truth(self):
        """For the rule writer's diagnosis only: every enemy the engine knows, relative to the player."""
        st = self.g.get_state()
        on_screen = {l.object_id for l in st.labels}
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

    def step(self, code):
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
            fired = any(seg[3] == "1" for seg, _ in segments(code))
            self.missed = 0 if self.var("HITCOUNT") > hits0 else self.missed + 1 if fired else self.missed
        out = {"code": code, "health_before": h0, "reward": round(reward, 1), "finished": finished}
        if finished:
            out.update(died=bool(self.g.is_player_dead()), health_after=0.0 if self.g.is_player_dead() else h0)
        else:
            out.update(died=False, health_after=self.var("HEALTH"), x=round(self.var("POSITION_X")),
                       y=round(self.var("POSITION_Y")), angle=round(self.var("ANGLE")), armor=self.var("ARMOR"),
                       kills=self.var("KILLCOUNT"))
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

    def events(self, i, rec):
        """The unwanted events of decision i, judged against the goal only: dying, or not getting further."""
        ev = []
        if rec["died"]:
            ev.append("died")
        elif rec["finished"]:
            ev.append("cleared" if self.bridge.level_cleared() else "timed out")
        else:
            if len(self.max_x) > STALL_WINDOW and self.max_x[-1] - self.max_x[-1 - STALL_WINDOW] < STALL_MIN:
                ev.append("stalled")
        return [e for e in ev if e != "cleared"]


def play(game, tree, jev, seed, prefix=(), stop_after=None, keep_frames=True, stop_on_event=True):
    """Replay `prefix` (codes, no Jev), then decide with the tree until the first unwanted event."""
    game.reset(seed)
    trace = []
    i = 0
    while True:
        text, frame = game.observe()
        if i < len(prefix):
            code, node, path = prefix[i], "replay", []
        else:
            code, node, path = decide(tree, jev, text, frame, seed, i)
        truth = game.truth()
        rec = game.step(code)
        rec.update(i=i, node=node, path=path, truth=truth, max_x=round(game.max_x[-1]))
        if keep_frames:
            rec.update(text=text, frame=frame)
        rec["events"] = game.events(i, rec)
        trace.append(rec)
        i += 1
        if rec["finished"] or (stop_on_event and rec["events"] and i > len(prefix)) or (stop_after is not None and i > stop_after):
            return trace


# --------------------------------------------------------------------------- commands

def cmd_play(run, seed):
    """One game from the start with fresh Jev answers, until the first unwanted event or the end."""
    run_dir = BASE / run
    run_dir.mkdir(parents=True, exist_ok=True)
    n = len(list(run_dir.glob(f"trace-s{seed}-*.json")))
    name = f"trace-s{seed}-{n:02d}"
    tree, jev, game = load_tree(run_dir), Jev(run_dir, read=False, shard=f"jev-cache-{name}.json"), Game()
    t0 = time.time()
    trace = play(game, tree, jev, seed)
    jev.save()
    (run_dir / f"{name}.json").write_text(json.dumps({"seed": seed, "trace": trace}))
    write_dossier(run_dir, name, seed, trace)
    last = trace[-1]
    result = {"trace": name, "seed": seed, "decisions": len(trace), "max_x": round(game.max_x[-1]),
              "event": last["events"][0] if last["events"] else ("cleared" if last["finished"] else None),
              "health": last["health_after"], "jev_calls": jev.calls, "wall_sec": round(time.time() - t0, 1)}
    print(json.dumps(result), flush=True)
    return result


def play_all(jobs, workers=6):
    """Play (run, seed) jobs in parallel subprocesses with fresh answers; return their results."""
    import subprocess
    procs, results, pending = {}, [], list(jobs)
    while pending or procs:
        while pending and len(procs) < workers:
            run, seed = pending.pop(0)
            procs[(run, seed)] = subprocess.Popen([sys.executable, __file__, "play", run, str(seed)],
                                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for (run, seed), p in list(procs.items()):
            if p.poll() is not None:
                out = p.stdout.read().strip().splitlines()
                results.append({"run": run, **(json.loads(out[-1]) if out else {"seed": seed, "event": "crashed"})})
                del procs[(run, seed)]
        time.sleep(0.5)
    return sorted(results, key=lambda r: (r["run"], r["seed"]))


def cmd_eval(run, seeds, workers=6):
    """Play every seed once, in parallel, with fresh answers; print one line per seed and a total."""
    results = play_all([(run, s) for s in seeds], workers)
    for r in results:
        print(f"seed {r['seed']}: {r['event']} at decision {r.get('decisions')}, furthest {r.get('max_x')}, health {r.get('health')}, {r.get('trace')}")
    print(f"cleared {sum(r['event'] == 'cleared' for r in results)} of {len(results)}")


def cmd_gate(run, rule_path, seeds):
    """A rule that passed its check on one game, against every training seed: the current tree and the tree
    with the rule each play every seed once, side by side, with fresh answers."""
    import shutil
    run_dir = BASE / run
    rule = json.loads(Path(rule_path).read_text())
    data = json.loads((run_dir / f"{rule['trace']}.json").read_text())
    k = rule["frame"]
    tree = load_tree(run_dir)
    _, deciding, walk = decide(tree, Jev(run_dir), data["trace"][k]["text"], data["trace"][k]["frame"], data["seed"], k)
    on_path = ["root"] + route(deciding, walk).split("/")
    rule["attach_to"] = rule["under"] if rule.get("under") in on_path else deciding
    new, ids = with_rule(tree, rule)
    gate = f"{run}-gate"
    shutil.rmtree(BASE / gate, ignore_errors=True)
    (BASE / gate).mkdir(parents=True)
    (BASE / gate / "tree.json").write_text(json.dumps(new))
    results = play_all([(r, s) for s in seeds for r in (run, gate)], workers=12)
    rows = {r: {x["seed"]: x for x in results if x["run"] == r} for r in (run, gate)}
    for s in seeds:
        a, b = rows[run][s], rows[gate][s]
        print(f"seed {s}: current {a['event']} (x {a.get('max_x')}, health {a.get('health')}), "
              f"with {'+'.join(ids)} {b['event']} (x {b.get('max_x')}, health {b.get('health')}, {gate}/{b.get('trace')})")
    n = {r: sum(x["event"] == "cleared" for x in rows[r].values()) for r in rows}
    print(json.dumps({"current": n[run], "with_rule": n[gate], "of": len(seeds), "pass": n[gate] >= n[run]}))


def write_dossier(run_dir, name, seed, trace):
    d = run_dir / name
    d.mkdir(exist_ok=True)
    f = len(trace) - 1
    lines = [f"# {name}: seed {seed}, unwanted event at decision {f}: {', '.join(trace[f]['events']) or 'none'}", "",
             "## the rule tree that played", "", "```", *tree_lines(load_tree(run_dir)), "```", "",
             f"## the last {DOSSIER_WINDOW} decisions", ""]
    for rec in trace[max(0, f - DOSSIER_WINDOW + 1):]:
        i = rec["i"]
        img = d / f"frame-{i:03d}.jpg"
        img.write_bytes(base64.b64decode(rec["frame"]))
        enemies = "; ".join(f"{e['name']}#{e['id']} {e['dist']}u {e['bearing']:+d}deg {e['side']}{' on screen' if e['on_screen'] else ''}"
                            for e in rec["truth"] if e["dist"] < 1200) or "none within 1200"
        lines += [f"## decision {i}: {describe(rec['code'])} ({rec['code']}), by {rec['node']}",
                  f"health {rec['health_before']:.0f} -> {rec['health_after']:.0f}, x {rec.get('x')}, events {rec['events'] or 'none'}",
                  f"path {rec['path']}", f"engine truth (not shown to Jev): {enemies}", f"frame: {img}", ""]
    lines += ["## the state Jev saw at each of these decisions", ""]
    for rec in trace[max(0, f - DOSSIER_WINDOW + 1):]:
        lines += [f"### decision {rec['i']}", "```", rec["text"], "```", ""]
    (d / "dossier.md").write_text("\n".join(lines))


def standing(tr, i):
    """What the goal needs, at decision i: alive, the goal reached, health, furthest point reached."""
    r = tr[min(i, len(tr) - 1)]
    dead = any(x["died"] for x in tr[: i + 1])
    cleared = not dead and len(tr) <= i + 1 and tr[-1]["finished"] and "timed out" not in tr[-1]["events"]
    return (0 if dead else 1, int(cleared), 0 if dead else r["health_after"], r["max_x"])


def better(new, old):
    """Alive beats dead, and the goal reached beats not reached; otherwise no worse on health and furthest
    point, and better on one of them. Dead is never better than dead: dying a few units further on does not
    avoid the death."""
    new, old = [tuple(s) if len(s) == 4 else (s[0], 0, *s[1:]) for s in (new, old)]
    if new[:2] != old[:2]:
        return new[:2] > old[:2]
    if new[0] == 0:
        return False
    return all(n >= o for n, o in zip(new[2:], old[2:])) and new[2:] != old[2:]


def route(node, path):
    """Every node a walk went through, the skills it entered included: what a cornerstone expects to reach."""
    ids = [p["pick"] if "at" in p else p["skill"] for p in path if ("at" in p and p["pick"] != "none") or "skill" in p]
    return "/".join(ids) or node


def same_route(expect, node, path):
    # Cornerstones from before skills existed expect only the node reached.
    return (route(node, path) if "/" in expect or expect != node else node) == expect


def top(tree, nid):
    """The root, or the skill, a node belongs to."""
    while tree[nid]["parent"] is not None:
        nid = tree[nid]["parent"]
    return nid


def with_rule(tree, rule):
    """Add one rule, or a group: `group` lists rules whose `under` is "frame" (an exception to the node deciding at
    the frame) or the index of an earlier rule in the group. Returns the new tree and the new ids."""
    new = json.loads(json.dumps(tree))
    members = rule.get("group") or [{"condition": rule["condition"], "action": rule["action"], "under": "frame",
                                     **({"focus": rule["focus"]} if rule.get("focus") else {})}]
    ids = []
    for m in members:
        rid = f"r{len(new)}"
        while rid in new:
            rid = f"r{int(rid[1:]) + 1}"
        parent = rule["attach_to"] if m["under"] == "frame" else ids[m["under"]]
        check_action(m["action"], in_skill=top(new, parent) != "root")
        new[rid] = {"id": rid, "parent": parent, "condition": m["condition"], "action": m["action"],
                    "children": [], "cornerstones": [], "meta": {k: rule[k] for k in ("trace", "frame", "why") if k in rule}}
        if m.get("focus"):
            assert set(m["focus"]) == {"from", "question"} and all(c in CHANNELS for c in m["focus"]["from"]), m["focus"]
            new[rid]["focus"] = m["focus"]
        new[parent]["children"].append(rid)
        ids.append(rid)
    return new, ids


def cmd_check(run, rule_path, commit=False):
    run_dir = BASE / run
    rule = json.loads(Path(rule_path).read_text())
    data = json.loads((run_dir / f"{rule['trace']}.json").read_text())
    seed, trace, k = data["seed"], data["trace"], rule["frame"]
    f = len(trace) - 1
    tree, jev, game = load_tree(run_dir), Jev(run_dir), Game()
    # Ripple-Down Rules: the new rule is an exception to the node that decides at its frame under the current tree
    # (which may be newer than the tree that played the trace).
    # The writer may instead name an ancestor on that walk, to place the exception higher (`under` in the proposal).
    _, deciding, walk = decide(tree, jev, trace[k]["text"], trace[k]["frame"], seed, k)
    on_path = ["root"] + [p["pick"] if "at" in p else p["skill"] for p in walk
                          if ("at" in p and p["pick"] != "none") or "skill" in p]
    rule["attach_to"] = rule["under"] if rule.get("under") in on_path else deciding
    new, ids = with_rule(tree, rule)
    rid = ids[0] if len(ids) == 1 else "+".join(ids)
    report = {"rule": rid, "attach_to": rule["attach_to"], "frame": k, "event_at": f, "event": trace[f]["events"]}

    # 1. Jev sees it: at its frame the walk through the new tree reaches the new rule.
    _, node, path = decide(new, jev, trace[k]["text"], trace[k]["frame"], seed, k)
    went = route(node, path).split("/")
    store_at = next((i for i in reversed(went) if i in ids), None)
    report["sees"] = {"pass": store_at is not None, "reached": node, "path": path}

    # 2. Nothing older changes: every earlier rule's frames still reach the node they reached.
    # A frame that now reaches another node is allowed only if replaying its episode with the new tree leaves
    # the agent no worse, at that rule's event time, than the rule itself did when it was added.
    corners = [(nid, c) for nid, n in tree.items() for c in n["cornerstones"]]
    with ThreadPoolExecutor(8) as pool:
        got = list(pool.map(lambda nc: decide(new, jev, nc[1]["text"], nc[1]["frame"], 0, 0), corners))
    changed = []
    for (nid, c), g in zip(corners, got):
        if same_route(c["expect"], g[1], g[2]):
            continue
        ctrace = json.loads((run_dir / f"{c['trace']}.json").read_text())
        # Compared where the rule's own check compared it: at the horizon past its event.
        until = c.get("horizon", c["event_at"])
        replay = play(Game(), new, jev, ctrace["seed"], prefix=[r["code"] for r in ctrace["trace"][: c["i"]]],
                      stop_after=until, keep_frames=False, stop_on_event="horizon" not in c)
        now = standing(replay, until)
        worse = better(tuple(c["standing"]), now)
        changed.append({"rule": nid, "now_reaches": route(g[1], g[2]), "standing_then": c["standing"], "standing_now": now, "worse": worse})
    report["unchanged"] = {"pass": not any(x["worse"] for x in changed), "cornerstones": len(corners), "changed": changed}

    # 3. It avoids the event: replay up to its frame, then play on to a fixed horizon past the old event, once
    # with the old tree and once with the new one, and compare the two futures on what the goal needs.
    horizon = f + AVOID_MARGIN
    prefix = [r["code"] for r in trace[:k]]
    before = play(game, tree, jev, seed, prefix=prefix, stop_after=horizon, keep_frames=False, stop_on_event=False)
    after = play(game, new, jev, seed, prefix=prefix, stop_after=horizon, keep_frames=False, stop_on_event=False)
    first = next((r for r in after[k:] if r["events"]), None)
    old_s, new_s = standing(before, horizon), standing(after, horizon)
    report["avoids"] = {"pass": better(new_s, old_s), "horizon": horizon,
                        "at_horizon": {"old_tree": old_s, "new_tree": new_s},
                        "first_event_after": None if first is None else {"i": first["i"], "events": first["events"]},
                        "end": {"i": after[-1]["i"], "health": after[-1]["health_after"], "kills": after[-1].get("kills"),
                                "x": after[-1].get("x")},
                        "actions": " ".join(f"{r['i']}:{r['code']}:{r['node']}" for r in after[k:])}
    report["pass"] = all(report[c]["pass"] for c in ("sees", "unchanged", "avoids"))
    jev.save()
    report["jev_calls"] = jev.calls
    if commit:
        if not report["pass"]:
            sys.exit("not committed: the check failed\n" + json.dumps(report, indent=1))
        new[store_at]["cornerstones"].append({"text": trace[k]["text"], "frame": trace[k]["frame"], "expect": route(node, path),
                                         "trace": rule["trace"], "i": k, "event_at": f, "horizon": horizon,
                                         "standing": standing(after, horizon)})
        # A frame that moved without harm now expects the node it reaches.
        for (nid, c), g in zip(corners, got):
            if not same_route(c["expect"], g[1], g[2]):
                next(cc for cc in new[nid]["cornerstones"] if (cc["trace"], cc["i"]) == (c["trace"], c["i"]))["expect"] = route(g[1], g[2])
        (run_dir / "tree.json").write_text(json.dumps(new))
        (run_dir / "rules.jsonl").open("a").write(json.dumps({"id": rid, **rule, "report": report}) + "\n")
    print(json.dumps(report, indent=1))


def tree_lines(tree):
    lines = []

    def walk(nid, depth):
        n = tree[nid]
        acts = n["action"] if isinstance(n["action"], list) else [n["action"]]
        does = "random walk" if acts == ["random"] else " | ".join(
            describe(a) + ("" if isinstance(a, dict) or a == "then" else f" ({a})") for a in acts)
        label = "default" if n["parent"] is None else f"if {n['condition']!r}"
        focus = f" [focus: {n['focus']['question']!r} among {', '.join(n['focus']['from'])}]" if n.get("focus") else ""
        lines.append("  " * depth + f"{nid}: {label}{focus} -> {does}")
        for c in n["children"]:
            walk(c, depth + 1)
    walk("root", 0)
    for nid in [k for k, n in tree.items() if n["parent"] is None and k != "root"]:
        lines.append(f"skill {nid}:")
        walk(nid, 1)
    return lines


def cmd_show(run):
    print("\n".join(tree_lines(load_tree(BASE / run))))


if __name__ == "__main__":
    cmd, run = sys.argv[1], sys.argv[2]
    if cmd == "play":
        cmd_play(run, int(sys.argv[3]))
    elif cmd in ("check", "commit"):
        cmd_check(run, sys.argv[3], commit=cmd == "commit")
    elif cmd == "show":
        cmd_show(run)
    elif cmd == "eval":
        lo, hi = map(int, sys.argv[3].split("-"))
        cmd_eval(run, range(lo, hi + 1))
    elif cmd == "gate":
        lo, hi = map(int, sys.argv[4].split("-"))
        cmd_gate(run, sys.argv[3], list(range(lo, hi + 1)))
