# system1-doom — Full Package Documentation

> **Bounded decision controller for ViZDoom** with five independent decision
> modules, a finite arbiter, bounded simulation, explicit exploration, a
> strategy archive, per-module learned value networks, **Liquid AI d1-ultra**
> on a cached/synchronous decision path, and an asynchronous **Codex** slow
> path that can propose new macro-actions — which may only enter play after
> deterministic admission.
>
> This document explains *how everything works*: architecture, every module,
> every formula and threshold that matters, both entry points, all files on
> disk, failure behaviour, and how to extend the system.
>
> Normative background: [`spec.md`](spec.md) (the original 21-section
> implementation spec) and
> [`superpowers/specs/2026-10-23-learning-controller-design.md`](superpowers/specs/2026-10-23-learning-controller-design.md)
> (the learning extension). This document describes the code as it is;
> section references like “Spec §9” point back to `spec.md`.

**Package:** `system1-doom` 0.2.0 · **Python:** ≥ 3.11 · **Source layout:**
`src/system1_doom/` (23 modules, ≈ 6,600 LOC) · **Tests:** `tests/`
(14 files, 57 tests) · **Web explainer:** `web/` (Vite + React + TypeScript)

---

## Table of contents

1. [The one invariant & design principles](#1-the-one-invariant--design-principles)
2. [Architecture at a glance](#2-architecture-at-a-glance)
3. [Installation & external dependencies](#3-installation--external-dependencies)
4. [Quick start](#4-quick-start)
5. [Repository & module map](#5-repository--module-map)
6. [Core vocabulary: state, actions, context](#6-core-vocabulary-state-actions-context)
7. [The fast path, tick by tick](#7-the-fast-path-tick-by-tick)
8. [Subsystem deep dives](#8-subsystem-deep-dives)
   - 8.1 [Environment bridge — `vizdoom_env.py`](#81-environment-bridge--vizdoom_envpy)
   - 8.2 [Tactical motor — `motor.py`](#82-tactical-motor--motorpy)
   - 8.3 [Bounded simulator — `simulator.py`](#83-bounded-simulator--simulatorpy)
   - 8.4 [Five decision modules — `modules.py`](#84-five-decision-modules--modulespy)
   - 8.5 [Final arbiter — `arbiter.py`](#85-final-arbiter--arbiterpy)
   - 8.6 [Exploration — `exploration.py`](#86-exploration--explorationpy)
   - 8.7 [Strategy archive — `archive.py`](#87-strategy-archive--archivepy)
   - 8.8 [Feature encoding — `features.py`](#88-feature-encoding--featurespy)
   - 8.9 [Learning — `learning.py`](#89-learning--learningpy)
   - 8.10 [d1-ultra client — `d1_client.py`](#810-d1-ultra-client--d1_clientpy)
   - 8.11 [Slow LLM worker — `llm_worker.py`](#811-slow-llm-worker--llm_workerpy)
   - 8.12 [Admission pipeline — `admission.py`](#812-admission-pipeline--admissionpy)
   - 8.13 [Controller orchestration — `controller.py`](#813-controller-orchestration--controllerpy)
   - 8.14 [Logging & visualisation — `logger.py`, `visualizer.py`, `charts.py`](#814-logging--visualisation--loggerpy-visualizerpy-chartspy)
   - 8.15 [Episode bundles & the web explainer — `tracing.py`, `export.py`, `web/`](#815-episode-bundles--the-web-explainer--tracingpy-exportpy-web)
9. [The slow path end-to-end](#9-the-slow-path-end-to-end)
10. [The learning loop end-to-end](#10-the-learning-loop-end-to-end)
11. [Entry points & CLI reference](#11-entry-points--cli-reference)
12. [Configuration reference](#12-configuration-reference)
13. [Files on disk: logs, runs, checkpoints](#13-files-on-disk-logs-runs-checkpoints)
14. [Failure modes & graceful degradation](#14-failure-modes--graceful-degradation)
15. [Measured results](#15-measured-results)
16. [Testing](#16-testing)
17. [Extending the system](#17-extending-the-system)
18. [Glossary](#18-glossary)

---

## 1. The one invariant & design principles

> **Generative systems may propose possibilities; bounded decision systems
> decide what enters the controller and what is executed.** (Spec §21)

Everything else follows from that sentence:

| Principle | How it is enforced in code |
|---|---|
| **Every behaviour terminates in a finite decision over a finite set** | The only thing ever executed is an `ActionSpec` drawn from `ActionVocabulary.available_actions(state)` and chosen by `FinalArbiter.arbitrate()`. Modules, the simulator, exploration, the archive, d1-ultra and Codex never execute game actions directly. |
| **The real-time loop never blocks** | No LLM call, network I/O, disk search or unbounded planning on the fast path. d1-ultra is read from cache (`async_cached`) by default; Codex runs on a 1-thread background executor; learning trains *between* episodes. See §7 and §14. |
| **LLM output cannot execute** | Codex/d1 output must parse into the typed `MacroActionProposal` schema, reference only known primitives, satisfy duration bounds, survive a sandbox rollout and (if enabled) a d1-ultra admission gate before `register_admitted_macro()` is called. Free-form text never reaches the motor. |
| **Boundedness everywhere** | Macros ≤ 16 primitives (`MAX_ALLOWED_MACRO_DURATION`); projections ≤ 16 candidates × depth 4 × branching 2 × 15 ms; archive ≤ 12 strategies; replay ≤ 100 k transitions; empirical cache ≤ 50 samples per (context, action); module evaluation inside a thread-pool deadline. |
| **Modules are replaceable** | All five modules implement the same `DecisionModule` contract (`DecisionInput → DecisionOutput`). `DoomDecisionController.replace_module(name, module)` swaps one without touching the rest (Spec §16/§20, exercised by an acceptance test). |
| **Everything is traceable** | Every tick writes one `TickTrace` JSON line with the state hash, context, all module outputs, projections used, the arbiter distribution and its component breakdown, the selected action, exploration state and learning shares. Every proposal writes a `ProposalTrace`. |
| **Learning is advisory and data-gated** | Learned value networks only override a module's heuristic in proportion to how often *that action in that context* has actually been tried (`λ = n/(n+25)`). Untried actions stay purely heuristic, so learning can never hijack play on extrapolation alone. |

There is deliberately **no** end-to-end policy, no chain-of-thought in the
loop, no self-modifying code, and no single monolithic network — the five
modules learn *independently*, each against its own reward signal (§8.9).

---

## 2. Architecture at a glance

```text
                         SLOW PATH (async, seconds, never blocks play)
  ┌──────────────────────────────────────────────────────────────────────┐
  │  module requests expansion                                           │
  │        │  ExpansionRequest                                           │
  │        ▼                                                             │
  │  SlowLLMWorker ── codex exec ──► raw JSON ──► AdmissionPipeline      │
  │        │ (or deterministic fallback template)    │ parse → validate  │
  │        │                                         │ sandbox → d1 gate │
  │        │                                         ▼                   │
  │        │                              ActionVocabulary.register ─────┼─► new macro
  │        │                              StrategyArchive.admit ─────────┼─► new strategy
  │        └──── AdmissionDecisionResult drained at start of next tick   │
  └──────────────────────────────────────────────────────────────────────┘

                         FAST PATH (every control tick, budgeted)
  ViZDoom ──► ViZDoomBridge.acquire_world_state() ──► WorldState S_t (frozen)
                                                             │
              ┌──────────────────────────────────────────────┤
              │ (full budget only) BoundedSimulator          │
              │   project_candidates(): ≤16 actions, depth 4,│
              │   2 branches, 15 ms, + empirical cache       │
              │                       │ ProjectedOutcome ×N  │
              ▼                       ▼                      ▼
        ┌─────────────────────────────────────────────────────────┐
        │ BatchModuleEvaluator: 5 modules in parallel threads     │
        │  survival · combat · navigation · resource · goal       │
        │  each: heuristic utilities                              │
        │        ⊕ learned value net (blended by per-context λ)   │
        │        ⊕ d1-ultra probabilities (cached or sync)        │
        │  → DecisionOutput (distribution, confidence, requests)  │
        └──────────────────────────┬──────────────────────────────┘
                                   ▼
        FinalArbiter: score = expected_value (confidence×gate-weighted
          module votes + 0.20·projection + 0.15·strategy + 0.30·d1)
          + exploration_bonus + novelty_bonus − risk_penalty − exec_cost
          → softmax(temperature) → pick (greedy / committed / explored)
                                   ▼
        TacticalMotor.burst(selected.primitive_expansion)
          assisted primitives: aim-before-fire, tracking strafes,
          pickup steering ──► ViZDoom buttons (2 tics per step)
                                   ▼
        bookkeeping: empirical cache, archive outcome, exploration
        update, module failure counters, Learner.record_step(),
        DecisionLogger.log_tick() ──► logs/ticks.jsonl
```

**Two optional “brains” sit on top of the same skeleton:**

1. **d1-ultra** (Liquid AI's decision model, `d1_client.py`) — a *decision*
   model, not a chat model. It answers typed questions (`choice` / `noul` /
   `score`) about the current state and can influence module distributions,
   the arbiter, exploration and admission. It can be fully disabled and the
   game still plays (`--disable-d1`).
2. **Learned value networks** (`learning.py`, PyTorch) — one small MLP per
   module plus an arbiter gate, trained between episodes from a replay
   buffer. They can be fully absent (no torch installed) and the game still
   plays on heuristics.

---

## 3. Installation & external dependencies

### Python dependencies (`pyproject.toml`)

| Group | Packages | Needed for |
|---|---|---|
| core (always) | `numpy`, `pillow`, `pydantic ≥2.6`, `requests`, `vizdoom ≥1.2` | everything: state/action models (pydantic), frames (pillow), d1 HTTP (requests), the game itself |
| `learn` (optional) | `torch ≥2.2` (CPU index), `matplotlib ≥3.8` | `train.py`, learned play in `cli.py`, learning curves. Without torch the controller silently plays on heuristics; `train` prints the install hint and exits `2`. |
| `dev` (optional) | `pytest ≥8` | test suite |

Python ≥ 3.11. Source layout is `src/` (`setuptools`, `where = ["src"]`);
pytest is configured with `pythonpath = ["src", "."]`, so tests run from the
repo root without installing.

Typical setup (the repo is developed with `uv`):

```bash
uv pip install -e .                 # core
uv pip install -e ".[learn,dev]"    # + torch (CPU), matplotlib, pytest
```

### External, non-Python dependencies

| Dependency | Required? | Notes |
|---|---|---|
| ViZDoom scenarios + an IWAD | **Yes** | Scenario `.cfg` files ship with the `vizdoom` wheel (`vzd.scenarios_path`); an absolute path may also be passed. `_vizdoom.ini` in the repo root is the engine config ViZDoom generates/uses. `basic.cfg`, `deadly_corridor.cfg`, `defend_the_center.cfg`, `health_gathering*.cfg` are the scenarios referenced by code/tests. |
| `LIQUID_API_KEY` | Only for d1-ultra | Read from env var `LIQUID_API_KEY`, else from `.env` in CWD or repo root (`d1_client.load_api_key()`). No key ⇒ `D1UltraClient.enabled=False` ⇒ pure local play, zero network calls. |
| `codex` CLI (OpenAI Codex) | Only for the slow LLM path | Detected with `shutil.which("codex")`. Absent ⇒ deterministic fallback templates are used instead (§8.11). Disable entirely with `--disable-slow-llm`. |
| `ffmpeg` | Only for `--save-mp4` | GIF export needs only Pillow. |
| Tkinter + a display | Only for the live dashboard | Enabled by `--visible` (unless `--no-dashboard`); any failure disables the dashboard silently and play continues. |
| DejaVu fonts | Optional | Used by the dashboard renderer if present; falls back to Pillow's default font. |

---

## 4. Quick start

```bash
# 1) Watch it play on heuristics only — no API keys, no torch needed.
#    (sync_d1 is the default mode; --disable-d1 makes it purely local)
python -m system1_doom.cli --scenario basic.cfg --episodes 3 \
    --disable-d1 --disable-slow-llm

# 2) Train the learned modules (headless; resumes automatically).
python -m system1_doom.train --scenario deadly_corridor.cfg --episodes 200

# 3) Fair comparison: heuristics vs latest vs best checkpoint,
#    identical held-out seeds, no learning, no exploration.
python -m system1_doom.train --scenario deadly_corridor.cfg --evaluate 30

# 4) Play with the trained model (best.pt if present, else checkpoint.pt).
python -m system1_doom.cli --scenario deadly_corridor.cfg --episodes 3 --disable-d1

# 5) Watch it play, with the live decision dashboard.
python -m system1_doom.cli --scenario deadly_corridor.cfg --episodes 1 \
    --visible --disable-d1

# 6) Full system: d1-ultra in the loop + Codex proposing macros.
#    (requires LIQUID_API_KEY and the codex CLI)
python -m system1_doom.cli --scenario deadly_corridor.cfg --episodes 1 --visible
```

Training writes to `runs/<scenario-stem>/` by default; re-running the same
command resumes from `checkpoint.pt` — add `--fresh` to start over.
Ctrl+C during training saves first. Full flag reference: §11.

---

## 5. Repository & module map

```text
system1_doom/
├── pyproject.toml
├── docs/
│   ├── spec.md                     # original 21-section implementation spec
│   ├── DOCUMENTATION.md            # ← this file
│   └── superpowers/
│       ├── specs/2026-10-23-learning-controller-design.md
│       └── plans/2026-10-23-d1-ultra-doom-controller.md
├── src/system1_doom/               # the package (see table below)
├── tests/                          # 14 files, 57 tests (§16)
├── web/                            # the web explainer: Vite + React app and demo bundles (§8.15)
├── runs/<scenario>/                # training output, per scenario (§13)
├── bundles/                        # episode bundles from `system1_doom.export` (§13)
├── logs/                           # default decision logs (ticks/proposals.jsonl)
└── _vizdoom.ini, _vizdoom/         # ViZDoom engine config / WAD search dir
```

| File | Lines | Responsibility (one line) |
|---|---:|---|
| `state.py` | 153 | Immutable `WorldState`/`Observation` pydantic models; state hash, context signature, d1 text rendering |
| `actions.py` | 322 | Finite action vocabulary: 13 primitives + 6 built-in macros, preconditions, `ActionSpec` validation |
| `vizdoom_env.py` | 423 | ViZDoom ⇄ controller bridge: builds `WorldState` from labels/depth/game vars, executes actions via the motor, level-clear rules |
| `motor.py` | 332 | Closed-loop reflex execution of a primitive plan (aim, tracking strafe, pickup steering) |
| `simulator.py` | 276 | Bounded analytic short-horizon projections + empirical transition cache |
| `modules.py` | 482 | The five `DecisionModule`s (survival/combat/navigation/resource/goal) + parallel `BatchModuleEvaluator` |
| `arbiter.py` | 268 | `FinalArbiter`: combines module votes, projections, exploration, archive, d1 and learned gate into one pick |
| `exploration.py` | 136 | Visitation/novelty/failure tracking → `exploration_pressure` + sampler temperature |
| `archive.py` | 201 | Bounded (≤12) strategy archive with an explicit 4-way strategy meta-decision |
| `features.py` | 104 | Fixed-size encodings: `WorldState → float32[32]`, `ActionSpec → float32[12]` |
| `learning.py` | 411 | Per-module value MLPs + arbiter gate, replay buffer, n-step returns, checkpoints (PyTorch) |
| `d1_client.py` | 248 | Liquid AI d1-ultra HTTP client: typed questions, sync `decide()`, async cache, graceful disable |
| `llm_worker.py` | 236 | Async slow path: builds a bounded expansion prompt, runs `codex exec`, falls back to templates |
| `admission.py` | 230 | Deterministic + sandbox + d1 admission gate for LLM macro proposals |
| `controller.py` | 462 | `DoomDecisionController`: orchestrates one tick and one episode; budget degradation; module swapping |
| `logger.py` | 121 | `TickTrace`/`ProposalTrace` JSONL logging |
| `tracing.py` | 425 | Typed decision-anatomy records for traces (state, pruning, module and arbiter arithmetic, rollout, steering, outcome), read-only |
| `export.py` | 519 | Episode bundles for the web explainer, bundle checks, index, JSON Schema (`python -m system1_doom.export`) |
| `visualizer.py` | 386 | Split-screen HUD frames, GIF/MP4 recorder, live Tk decision dashboard |
| `charts.py` | 118 | `learning_curves.png` from `metrics.jsonl` (matplotlib, dark theme) |
| `cli.py` | 183 | Play/watch entry point (`python -m system1_doom.cli`) |
| `train.py` | 378 | Training/evaluation entry point, `RunStore`, resume, best-checkpoint tracking (`python -m system1_doom.train`) |
| `__init__.py` | 3 | Package docstring + `__version__` |

Dependencies point “downwards” only: `controller` wires everything;
`modules`/`arbiter` depend on `state`, `actions`, `simulator`, `d1_client`;
`learning` depends only on `features`; `tracing` depends on `features`
and only reads the others' records; nothing depends on `cli`/`train`/`export`.

---

## 6. Core vocabulary: state, actions, context

### 6.1 `WorldState` — the immutable snapshot (`state.py`)

All pydantic models are `frozen=True`: within one tick every module sees the
*identical* snapshot, so decisions are comparable (Spec §4).

```text
WorldState
├── observation: Observation
│   ├── tick, health, armor, ammo, current_weapon, movement_state
│   ├── visible_enemies:  (EnemyObservation…)   # id, name, distance,
│   │                                            # angle_offset°, screen x/y, w/h
│   ├── visible_pickups:  (PickupObservation…)  # id, name, category ∈
│   │                                            # health|armor|ammo|weapon|item
│   ├── recent_incoming_damage, recent_outgoing_damage, recent_kills
│   ├── position: Pose3D (x, y, z, angle)
│   ├── wall_distance_front / left / right      # from the depth buffer
│   ├── frame_jpeg_b64 (optional, for d1 vision), frame_brightness
│   └── episode_progress: {tick, episode_tick, reward_so_far, kills, …}
└── memory: ControllerMemory
    ├── short_action_history (last 10), recent_state_summaries (last 5)
    ├── discovered_locations (last 16 grid sectors)
    └── strategy_archive_refs
```

Two derived keys are used everywhere:

* **`state_hash()`** — first 16 hex chars of SHA-256 over a rounded
  JSON summary (vitals, enemies, pickups, position, last 4 actions).
  Written to every tick trace; identifies “the same situation”.
* **`context_signature()`** — a coarse human-readable bucket, e.g.
  `hp:healthy|ammo:stocked|enemies:2:mid|dmg:clear|pickup:pickup_visible`.
  Buckets: health `critical ≤30 / medium ≤65 / healthy`, ammo
  `empty 0 / low ≤8 / stocked`, enemy range `none / melee <140 / mid <420 /
  far` (by nearest enemy), damage `under_fire / clear`, pickups
  `pickup_visible / no_pickup`. This signature keys the simulator's
  empirical cache, exploration counts, the strategy archive, d1 cache keys,
  and the learner's per-context trust counts. It is the unit of
  “have I been here before?” for the whole system.
* **`to_d1_state_text()`** — the compact structured text snapshot sent to
  d1-ultra (state + combat deltas + geometry + enemies/pickups + memory).

### 6.2 Actions — primitives and macros (`actions.py`)

An `ActionSpec` is the *only* executable unit. It must declare `id`,
`description`, `parameters`, `preconditions`, `maximum_duration` (1–16),
`termination_condition`, and a `primitive_expansion` — a tuple of primitive
ids whose length may not exceed `maximum_duration`. A model validator
rejects empty/over-long expansions and any primitive not in
`PRIMITIVE_ACTION_IDS`; a non-macro must expand to exactly itself.
An action that cannot be reduced to a bounded procedure is invalid by
construction (Spec §5).

**13 primitives** (`PRIMITIVE_ACTION_IDS`):

```text
move_forward  move_backward  strafe_left  strafe_right  turn_left
turn_right    shoot          use          switch_weapon_1/2/3
strafe_left_shoot  strafe_right_shoot     ← compound: strafe + track + fire
```

**6 built-in macros** (`DEFAULT_MACROS`), e.g.:

| Macro | Expansion | Intent |
|---|---|---|
| `circle_strafe_left/right` | turn, shoot, strafe, shoot | orbit a side target while firing |
| `retreat_to_cover` | backward, strafe_left, backward | disengage at low HP |
| `approach_pickup` | forward ×4 (`pickup_id` param ⇒ motor steers) | collect the nearest pickup |
| `peek_and_fire` | strafe_left, shoot, strafe_right, shoot | weave + double burst |
| `weave_fire` | strafe_left_shoot ×2, strafe_right_shoot ×2 | strafe-fire both ways; empirically the strongest built-in on `deadly_corridor` (scripted check: 8/20 seeds cleared vs 2/20 for `peek_and_fire`) |

Each `ActionSpec` has **preconditions** (`PreconditionSpec`: ammo/health
windows, `requires_visible_enemy/pickup`, wall-distance window, excluded
weapons). `ActionVocabulary.available_actions(state)` filters by them; if
*no* action passes, it falls back to `(turn_left, turn_right, move_forward)`
so the arbiter always has a non-empty finite set. Examples: `shoot` needs
ammo ≥ 1 and a visible enemy; `move_backward` only exists at health ≤ 45
with an enemy visible (it is a retreat, not a general movement); `use`
needs a wall within 64 units.

`execution_cost = 0.02·len(expansion) + 0.02·(#shoot-like steps)` is the
arbiter's per-action cost term. `register_admitted_macro()` is the single
door through which new actions enter the vocabulary, and it refuses
non-macros.

### 6.3 Where actions can be unavailable

The vocabulary says what *may* be chosen; the scenario says what *can* be
executed. `DoomDecisionController.step()` additionally filters candidates
through `env.action_supported(action)` (e.g. a scenario without turn
buttons cannot run `turn_left`), falling back to the precondition-filtered
list if the motor filter would empty the set.

---

## 7. The fast path, tick by tick

`DoomDecisionController.step()` (`controller.py`) runs six phases. Default
tick budget is `ControllerConfig.tick_budget_sec = 0.035 s` in
`async_cached` mode; the CLI raises it to `5.0 s` in `sync_d1` mode (where
blocking d1 calls are expected) and `0.04 s` otherwise.

```text
budget_sec ──► budget_mode:  full      (> 0.012 s)
                             reduced   (0.004 s < b ≤ 0.012 s)
                             critical  (≤ 0.004 s)
```

| Phase | Full | Reduced | Critical |
|---|---|---|---|
| 0. Drain slow-LLM results → log `ProposalTrace`s | ✓ | ✓ | ✓ |
| 1. `acquire_world_state()` → frozen `WorldState`; filter actions by preconditions + motor support | ✓ | ✓ | ✓ |
| 2a. Encode state/actions; query `Learner` for per-module utilities, per-action trust, gate weights/share | ✓ | ✓ | — |
| 2b. `BoundedSimulator.project_candidates()` | ✓ | — | — |
| 2c. `BatchModuleEvaluator.evaluate_all()` (5 threads, deadline = 65% of budget) | ✓ | ✓ | — |
| 2d. Forward any module's expansion request to the slow worker (if not busy) | ✓ | ✓ | — |
| 2e. `FinalArbiter.arbitrate()` (35% of budget for its d1 call) | ✓ | ✓ | — |
| 2f. — instead: replay the cached reactive action with uniform stub module outputs | — | — | ✓ |
| 3. `env.execute_action(selected)` → motor burst in ViZDoom | ✓ | ✓ | ✓ |
| 4. If learning enabled: `Learner.record_step(state_vec, action_vec, result, module_top_actions, …)` | ✓ | ✓ | ✓ |
| 5. Bookkeeping: simulator empirical cache, archive outcome, exploration update + strategy meta-decision, module failure counters | ✓ | ✓ | ✓ |
| 6. `DecisionLogger.log_tick(TickTrace)`; optional recorder/dashboard update | ✓ | ✓ | ✓ |

Three properties to notice:

* **The game never waits for intelligence.** In `critical` mode the
  controller replays its last selected (“cached reactive”) action and
  fabricates uniform module outputs so the trace schema is unchanged.
* **Expansion requests are fire-and-forget.** A module sets
  `request_action_expansion=True` with a problem description; the
  controller enqueues at most one request (the worker is single-flight)
  and play continues. Results are drained at phase 0 of a later tick.
* **`run_episode()`** loops `step()` until the ViZDoom episode ends or
  `max_ticks` (default 500) decisions are made, then finalises the
  learner's pending episode (`end_episode()`) and returns a summary dict
  (`reward, kills, health, armor, cleared, died, ticks, transitions,
  explored_steps, network_share, actions, traces`). What “cleared” means
  is scenario-specific — see `ViZDoomBridge.level_cleared()` (§8.1).

---

## 8. Subsystem deep dives

### 8.1 Environment bridge — `vizdoom_env.py`

`ViZDoomBridge` is the only class that talks to `vizdoom.DoomGame`.

**Construction.** Loads the scenario config (name under
`vzd.scenarios_path`, or an absolute path), optional seed, window
visibility (visible ⇒ 640×480, headless ⇒ 320×240), screen format
`CRCGCB`, and enables objects info, labels buffer and depth buffer.
It constructs the `TacticalMotor` with the scenario's actual button list,
so all downstream logic is button-set-aware.

**`acquire_world_state(strategy_refs)`** builds one frozen `WorldState`:

* Game variables → health/armor/ammo/weapon (`SELECTED_WEAPON` 1–4 mapped
  to `fist_chainsaw/pistol/shotgun/chaingun`), position, velocity
  (→ `moving`/`stationary`), `HITCOUNT`/`KILLCOUNT` deltas →
  `recent_outgoing_damage = Δhits·20`, `recent_incoming_damage` from the
  health drop since the previous snapshot.
* **Labels buffer** → visible enemies/pickups. For each label: screen
  centre, `angle_offset = (centre_x − cx)/centre_x · 45°` (positive =
  left of crosshair), true distance from the objects buffer when
  available, else the sprite-size estimate `max(30, 3200/height)`.
  Name classification is keyword-based and shared with the motor
  (`is_enemy_name`, `is_pickup_name`, `is_ignored_actor` — dead actors,
  the player, blood/puffs/bullets/gibs are ignored). Pickup names map to
  categories via `PICKUP_CATEGORY_MAP` (medikit→health, greenarmor→armor,
  shellbox→ammo, shotgun→weapon, …). Pickups the motor has marked
  unreachable this episode are hidden here too.
* **Depth buffer** → mean depth of the centre/left/right thirds ×4 →
  `wall_distance_front/left/right`.
* **Screen buffer** → brightness, and a 320×240 JPEG (quality 75,
  base64) for d1-ultra vision when `include_jpeg_frame` is on.
* Memory: last 10 actions, last 5 one-line state summaries, last 16
  discovered 128-unit grid sectors, archive strategy refs.

**`execute_action(action)`** snapshots position, delegates to
`motor.burst(plan=action.primitive_expansion, steer_to_pickup=("pickup_id"
in parameters))`, then derives everything the learner and logger need:
reward, damage taken, hits/kills deltas, health/armor/ammo *gains*, death,
displacement, and **new map cells** (128-unit grid cells first entered
this episode — the navigation reward). If a pickup-seeking action moved
the player < 12 units, that pickup is added to `motor.ignored_pickups`
for the rest of the episode (otherwise a shotgun on a ledge would pin
the player against a wall until timeout — found in training).

**`level_cleared()`** is deliberately scenario-specific: `basic` ⇒ ≥1 kill
alive; `deadly_corridor` ⇒ episode finished, alive, armor ≥ 100 (reached
the vest); `health_gathering` (non-supreme) and `defend_*` ⇒ finished
alive; default ⇒ finished alive with ≥1 kill or armor ≥ 100.
`episode_status()` exposes `{health, armor, kills, reward}`.
`auto_restart` (default `True`) restarts finished episodes on the next
acquire; `run_episode` disables it and manages restarts itself.
`restart_episode(seed)` also resets the motor's target lock and cell set.

### 8.2 Tactical motor — `motor.py`

The arbiter picks an *action*; the motor executes that action's **own**
primitive list — the selected action genuinely drives play (this was the
central change of the learning-controller design; before it, the motor ran
a fixed reflex and the arbiter only set its length).

* **Timing.** Each primitive is held for `hold = max(1, 4 // len(plan))`
  motor steps, each step being `make_action(vector, frame_skip=2)`
  (2 game tics). A 1-primitive action and a 4-step macro therefore both
  last ≈ 8 tics; longer macros run longer. The burst stops at episode end.
* **Assisted primitives** (`_assisted_flags`) — every primitive keeps a
  small closed-loop assist, all bounded by the plan:
  * `shoot`: find the *locked* enemy (the motor keeps a `lock_id` across
    steps, re-acquiring the most-central enemy when the lock is lost);
    if it is off-centre by more than `align_px ≈ 10 px @320 wide`, press
    the turn button toward it (or strafe toward it on scenarios without
    turn buttons); fire only once centred.
  * `strafe_left/right`: strafe, plus a tracking turn onto the locked
    enemy when one is visible.
  * `strafe_left_shoot` / `strafe_right_shoot` (compound): strafe the
    whole step; turn toward the target, and press `ATTACK` in the same
    step once centred. This compound exists because no single primitive
    could move and fire simultaneously.
  * `move_forward` inside a pickup-seeking action: also turn toward the
    nearest visible pickup (tallest sprite = closest), recording
    `last_pickup_target` for the bridge's unreachable-pickup rule.
  * Everything else is pressed literally.
* **Support check.** `action_supported(expansion)` requires every
  primitive's buttons (including compound pairs) to exist in the
  scenario's button list.
* **Bookkeeping returned** (`MotorBurst`): summed reward, executed
  primitive labels (e.g. `"strafe_left+turn_left"`), last frame,
  health/armor/ammo before-after deltas, hits/kills deltas, death flag.

### 8.3 Bounded simulator — `simulator.py`

An *analytic* forward model — not a learned one and not a ViZDoom clone.
Its purpose is cheap short-horizon evidence (Spec §8), and its bounds are
explicit and validated by pydantic:

```python
ProjectionLimits(max_candidate_count=16,   # actions projected per tick
                 max_simulation_depth=4,    # primitives rolled out
                 max_wall_clock_budget_sec=0.015,
                 max_branching_factor=2)    # enemy-aggressiveness branches
```

`_step_primitive(state, primitive, aggressiveness)` applies a hand-written
transition: 28 units/step of movement along (or perpendicular to) heading
clamped by the front wall, 18° turns (aim-aware: turning toward a side
enemy rotates by its angle offset, clamped 4–28°), shooting deals
`40 · alignment · distance_factor` expected damage to the best target
(alignment 1.0 within ±15°, decaying to 0.25; distance factor floored at
0.35), strafe-fire compounds deal 32·… Enemies close/open distance by
primitive, incoming damage is `Σ 8·(proximity_risk + 0.25) ·
evasion_factor · suppression · aggressiveness`, where strafing/backing
away evades (0.35/0.45), advancing exposes (0.90), and dealing ≥ 18 damage
suppresses return fire (×0.55). Moving forward toward a pickup accrues
resource gain (14 for health/armor/weapon, 9 otherwise).

`project_action()` rolls the action's first `depth` primitives under each
branch scale in `[1.0, 1.35, 0.7, 1.6][:branching]` and averages the
branch values
`V = 0.12·dmg_out + 0.14·res + 0.18·pos − (dmg_in/steps)·(0.18 if HP≤40 else 0.09) − execution_cost`.
The result is a `ProjectedOutcome`: expected value, damage taken/dealt,
resource gain, positional progress, survival probability
(`clamp((HP − dmg_in/steps)/100)`), the projected state chain, and an
empirical-sample count.

**Empirical cache.** Every executed action records
`(reward_delta, damage_taken)` under `(context_signature, action_id)`,
capped at 50 samples. When samples exist, the analytic value is blended
with experience: `V ← 0.6·V + 0.4·(mean_reward·0.1 − mean_dmg·0.05)`.
`project_candidates()` honours the candidate cap and stops at the
wall-clock deadline (always returning at least one projection).

### 8.4 Five decision modules — `modules.py`

**Contract (Spec §6).** `DecisionInput` = world state + available actions
+ local memory + projected outcomes + time budget (+ optional learned
utilities/trust injected by the controller). `DecisionOutput` = ranked
actions, a probability distribution, raw utility estimates, confidence
and uncertainty (from normalised Shannon entropy of the distribution:
`uncertainty = H/log n`, `confidence = 1 − uncertainty`), the projections
used, `request_additional_simulation` (set when uncertainty > 0.72 and
projections are incomplete), `request_action_expansion` + problem
description, a local-memory update, and d1 provenance fields.

**How a module decides** (`DecisionModule.build_output`), in order:

1. `compute_local_utilities()` — the module's own fast heuristic (below).
2. **Learned blend** (if the controller supplied predictions): per action,
   `u ← (1−λ_a)·u_heuristic + λ_a·u_network`, where `λ_a` is the
   per-(context, action) trust from the learner (§8.9). Actions the
   network has never seen in this context keep `λ=0`.
3. `softmax(utilities, T=0.35)` → local distribution.
4. **d1-ultra blend** (if a d1 response is available): the module's
   distribution is mixed with d1's per-action probabilities with weight
   `0.75` normally, but only `0.25` when the local utility gap between
   the top-2 actions is ≥ 0.45 — i.e. when geometry already settles the
   question (aim/shoot/advance), d1 may advise but not override.
5. Confidence/uncertainty from entropy; expansion check (below), possibly
   overridden by d1: if d1's `noul` answer to “are current candidates
   insufficient?” exceeds **0.78** and the module didn't already request
   expansion, it does now.

**The five heuristics** (each also adds its projection terms):

| Module | Question it answers | Core heuristic signals |
|---|---|---|
| **survival** | Which action best reduces near-term probability of death? | `1.2·survival_prob − 0.22·low_hp_pressure·E[dmg_in]`; `low_hp_pressure = max(0.2, (100−HP)/60)` scales bonuses for retreat/orbit/weave macros (0.65·p), strafes/retreat (0.45·p), healing `approach_pickup` (0.55·p); advancing into visible enemies −0.40·p |
| **combat** | Which combat action best improves the current fight? | `0.05·E[dmg_out] − 0.04·E[dmg_in]`; if an enemy is aimed (nearest \|angle\| ≤ 12°): `shoot` +2.4, `weave_fire` +2.2, aimed `peek_and_fire` +1.6; turn/strafe *toward* the signed target angle +2.1; generic combat macros +0.35; no enemy: `move_forward` +0.2 |
| **navigation** | Which movement action best improves positional progress? | `0.45·E[pos_progress]`; `move_forward` +0.75 when front wall > 64; `approach_pickup` +0.55; `use` +0.80 when a wall is within 64; turn toward the more open side +0.70 |
| **resource** | Which action best improves resource state without unacceptable risk? | `0.12·E[res_gain] − 0.05·E[dmg_in]`; `approach_pickup` +1.15 when HP < 75 or ammo < 15 else +0.75; `move_forward` toward pickups +0.55; any shoot-containing action with no enemy visible −0.65 (don't waste ammo) |
| **goal** | Which action most increases probability of eventual level success? | `0.5·E[value]`; enemies visible ⇒ combat macros/`shoot`/`weave_fire` +0.60; none ⇒ `move_forward`/`approach_pickup` +0.70 |

**Expansion triggers** (`check_expansion_needed`) — the bridge to the slow
path; each is a concrete failure detector fed by controller-maintained
counters (§8.13): survival — HP < 35 with ≥ 15 incoming damage, or ≥ 4
consecutive damage ticks; combat — ≥ 3 repeated failures, or ≥ 4 damage
ticks against ≥ 2 enemies; navigation — ≥ 4 consecutive movement stalls
(chose to move but displaced < 4 units); resource — ammo ≤ 2 and HP ≤ 35
with pickups visible; goal — ≥ 6 plateau ticks.

**Parallel evaluation.** `BatchModuleEvaluator.evaluate_all()` builds all
five inputs over the *same* snapshot, assembles the 10 d1 questions
(5× `choice` + 5× `noul`), and either makes **one batched synchronous
d1 call** (`sync_d1`) or reads the per-context cache and fires a
non-blocking refresh (`async_cached`, cache key
`batch_mods:<context_signature>`, frame image attached when available).
The five `build_output` calls then run on a 5-thread pool inside the tick
deadline; any module that misses the deadline is recomputed locally
without d1 (graceful degradation — never a dropped module).

### 8.5 Final arbiter — `arbiter.py`

The arbiter is itself a bounded decision (Spec §9), not hand-written
reasoning. For each candidate action it computes:

```text
score(a) = expected_value + exploration_bonus + novelty_bonus
           − risk_penalty − execution_cost

expected_value   = Σ_m w_m · P_m(a)              (module votes)
                   + 0.20 · projection.expected_value
                   + 0.15 if a ∈ active strategy's action_sequence
                   + 0.30 · P_d1_arbiter(a)       (if d1 answered)
exploration_bonus= pressure · (0.35 · module_disagreement(a)
                   + 0.12 if a is a macro)
novelty_bonus    = 0.25 · pressure · novelty(context, a)     (§8.6)
risk_penalty     = 0.04 · E[dmg_in] · (1.8 if HP ≤ 35 else 0.8)
execution_cost   = 0.02·len + 0.02·shots                     (§6.2)
```

**Module weights `w_m`** blend two sources: (a) a context heuristic —
fighting (enemies visible, ammo > 0): combat 2.2, goal 1.2, resource 0.7,
survival 0.55, navigation 0.45; not fighting: navigation 1.7, survival
1.4 if HP ≤ 40 else 0.8, goal 1.3, resource 1.3 if pickups visible else
0.6, combat 0.35 — each scaled by `(0.4 + 0.6·confidence_m)` and
normalised; and (b) the **learned gate** (§8.9): `softmax(gate(state)/0.5)`,
mixed in with share `gate_trust(context)` (same `n/(n+25)` rule). Both
the weights used and the full per-component breakdown are recorded in the
decision/trace.

**Picking the winner**, in priority order:

1. **Committed pick.** If any module is overwhelmingly sure of one action
   (top utility ≥ 5.0, margin ≥ 4.0 over its runner-up, probability
   ≥ 0.9), that action is taken directly. This is the mechanism by which
   a newly admitted macro gets *reused* once a module adopts it strongly.
2. **Exploration floor.** With probability `exploration_floor` (set by
   the training schedule or `--learn`), sample from the score softmax at
   temperature ≥ 0.5 and flag the decision `explored=True`.
3. **Greedy** if `deterministic` is set, or the top-2 score margin
   ≥ 0.08, or exploration pressure < 0.45.
4. Otherwise **sample** from `softmax(scores / temperature)` with the
   exploration controller's temperature (§8.6).

The arbiter also has its own optional d1 question (`arbiter_choice`,
criteria annotated with every module's votes and the projection summary;
cache key `arbiter:<context_signature>`, same sync/async pattern), whose
distribution enters both as the 0.30 bonus above and `d1_distribution` in
the trace. Every arbitration records the executed action in the
exploration controller's visitation counts.

### 8.6 Exploration — `exploration.py`

`ExplorationController` maintains context visitation counts
(`context::action` keys), per-strategy usage, an EMA of progress
(`0.7·old + 0.3·delta`, where the controller passes
`progress_delta = 8·Δkills + max(0, reward)`), a failure counter
(±1 per step, clamped 0–20) and a stall streak (progress ≤ 0.05).

`update_and_decide()` computes, per tick:

```text
novelty(context)  = 1 / (1 + 0.5·(visits − 1))
pressure = 0.25·mean_module_uncertainty + 0.25·min(1, failures/4)
           + 0.25·plateau + 0.25·novelty          (plateau: stall ≥ 3 or failures ≥ 3)
pressure ×= 0.55  if progress EMA > 1.0   (a strategy is working)
pressure ×= 0.35  if HP ≤ 30 or heavy fire (high risk → exploit)
pressure ×= 0.25  if a near-term winning sequence is detected
                      (a kill this step, or armor ≥ 100)
pressure ∈ [0.02, 1];   temperature = 0.10 + 1.00·pressure ∈ [0.10, 1.10]
```

In `sync_d1` full-budget mode an additional d1 `score` question (“exploit
strictly / balanced / high exploration”) can move pressure halfway toward
its answer. Per-action novelty for the arbiter is
`action_novelty = 1/(1 + visits(context, action))`. The output
`ExplorationState` (recent progress, failures, novelty, strategy usage,
uncertainty, plateau flag, pressure, temperature) is embedded whole in
every tick trace.

Note there are **two distinct exploration mechanisms**: this
pressure/temperature pair (shapes the arbiter's sampling distribution)
and the learner-facing `exploration_floor` (§8.5, §10) — a flat
probability of sampling from a tempered distribution instead of taking
the top pick, scheduled by `train.py`.

### 8.7 Strategy archive — `archive.py`

A bounded memory of *named ways of playing* (Spec §11) that prevents
permanent collapse into one local optimum. An entry holds
`strategy_id, context_signature, action_sequence, observed_reward,
success_rate, failure_modes (≤5), usage_count, novelty_signature`.
Capacity is **12**; admitting beyond capacity evicts the lowest
`observed_reward + 5·success_rate` non-active entry. Three strategies are
seeded: `strat_tactical_combat` (peek-and-fire → circle-strafe → shoot),
`strat_evasive_survival` (retreat → strafe → approach pickup),
`strat_corridor_advance` (forward → approach pickup → use).

Every tick the controller records the executed action's outcome against
the *active* strategy (EMA α = 0.3 on reward and success; a step “fails”
on damage > 8 or death) and then runs an explicit 4-way meta-decision
over `continue_current_strategy / switch_to_archived_strategy /
explore_variation / request_new_strategy_proposal` with utility scores
driven by the active strategy's success rate, recent failures and
exploration pressure (optionally blended with a d1 `choice` in sync
mode). Choosing “switch” activates the archived strategy with the best
`success_rate + 0.1·observed_reward`. The active strategy influences play
concretely: its `action_sequence` gives member actions +0.15 in the
arbiter (§8.5). Admitted Codex macros also create archive entries
(`novelty_signature = llm_admitted:<id>`, §8.12).

### 8.8 Feature encoding — `features.py`

Scenario-agnostic, fixed-size, bounded encodings — the contract between
the game-facing world and the learned networks. Sizes are part of the
checkpoint format: changing them makes old checkpoints refuse to load.

**State → `float32[32]`** (`STATE_DIM`), all clipped:

| # | Features |
|---|---|
| 0–3 | health/100, armor/100, ammo/50 (each clipped to [0,2]), `ammo > 0` flag |
| 4–10 | enemy count/5; nearest-enemy distance/1000 (1.0 if none), signed angle/45 ∈ [−1,1], \|angle\|/45, `aimed (≤12°)` flag, `≥2 enemies` flag, `nearest < 140` flag |
| 11–18 | pickup count/5; nearest-pickup distance/1000, angle/45; 5 one-hots for its category (health/armor/ammo/weapon/item) |
| 19–24 | wall_front/left/right /256 ([0,2]); incoming damage/50, outgoing damage/50, recent kills ([0,2]) |
| 25–27 | `moving` flag; episode tick/100 ([0,3]); last displacement/64 |
| 28–31 | fraction of the last 6 actions containing `shoot` / `move_forward` / `strafe` / `turn` |

**Action → `float32[12]`** (`ACTION_DIM`): the fraction of the action's
primitive steps equal to each of the 8 base primitives
(`move_forward … use`; compound strafe-fire counts as *both* its strafe
and `shoot`), plus switch-weapon fraction, `len/16`, `is_macro`, and
“has `pickup_id` parameter”. Because actions are described by
*composition*, a Codex macro admitted at runtime is scored by the
networks immediately, with no retraining and no index bookkeeping.

### 8.9 Learning — `learning.py`

The learning design goal: each module improves *independently* against
its own reward, the arbiter learns *whose advice to follow*, and none of
it can destabilise play before it has data.

**Per-module rewards** for one executed decision (from `ExecutionStepResult`):

```text
survival    = −damage_taken/25 − 3·died
combat      =  0.5·hits_delta + 2·kills_delta
navigation  =  new 128-unit map cells entered this step (0/1)
resource    =  health_gain/25 + armor_gain/25 + ammo_gain/10
goal        =  scenario reward (the ViZDoom reward for the burst)
```

**Targets.** At episode end, each step's target is the **8-step
discounted return** of its module reward stream (γ = 0.9, truncated at
episode end), standardised by running mean/std (`RunningStats`, Chan's
parallel update, persisted in the checkpoint).

**Networks** (PyTorch; `LearnerConfig`: hidden 64, gate-hidden 32,
lr 1e-3 Adam, batch 256, 200 steps/episode, seed 0, single-threaded —
these nets are faster without thread synchronisation):

* Five value MLPs `(state⊕action) 44 → 64 → 64 → 1`, one per module,
  implemented as a single batched `ModuleValueNets` (stacked
  `baddbmm` weights) so all five are evaluated in one call.
* An **arbiter gate** MLP `state 32 → 32 → 5`. It is trained only on
  transitions where a module's top pick *was* the executed action
  (the `gate_mask`), against the goal return — i.e. it learns “in
  states like this, following module *m* paid off”. At play time
  `softmax(gate/0.5)` becomes the learned module-weight distribution.

**Trust (the stabiliser).** A network's say is gated per (context,
action): `λ = n/(n + trust_count)`, `trust_count = 25` by default — an
action tried 25 times in this context gets 50% network weight, 100
tries ≈ 80%. The gate uses the same rule per context. This per-context
rule replaced a global experience-based λ after experiments showed the
global version first improved then degraded play (networks dominating
and chasing overestimated, rarely-tried actions). `network_share` (the
experience-weighted mean trust) is the headline “how much of play the
networks now steer” metric in logs and charts.

**Experience.** `record_step()` accumulates the pending episode
(state/action vectors, module rewards, gate mask, `(context, action)`
keys). `end_episode()` converts it to n-step returns, updates the
running stats and trust counters, and appends to a **100 k-transition
ring-buffer replay** (`states, actions, returns, gate_mask` as flat
NumPy arrays; persisted separately as `replay.npz`).
`discard_episode()` drops a half-finished episode (used on interruption
and at `run_episode` start). Training (between episodes only) runs a
fixed 200 Adam steps on batches of 256, MSE per network plus the masked
gate MSE; it is a no-op below 32 transitions. Training cost is therefore
constant per episode and never inside the tick loop.

**Checkpoints** (`Learner.save/load`, `checkpoint.pt`, format v1):
network + gate + optimiser state dicts, running stats, counters
(episodes, transitions, updates, best score), per-action/context trust
counts, last losses, and the `LearnerConfig`. `load()` raises
`CheckpointMismatch` on format/feature-size/module-list mismatch —
callers turn that into “retrain with `--fresh`” rather than playing with
silently wrong weights. Architecture fields (`hidden`, `gate_hidden`)
cannot be overridden after the fact; other config fields can.

### 8.10 d1-ultra client — `d1_client.py`

A thin, defensive client for Liquid AI's decision endpoint
(`POST https://api.liquid.ai/decisions/v1/systemone`, model `d1-ultra`).

* **Typed questions.** Three pydantic question kinds — `noul`
  (a probability that the instructed proposition holds), `choice`
  (probabilities over named criteria), `score` (a score over an ordered
  criteria list) — serialised via `to_payload()`; answers are validated
  into `NoulAnswer`/`ChoiceAnswer`/`ScoreAnswer` through `D1Response`.
  Callers pass a *dict of named questions* and read answers by name, so
  modules, the arbiter, exploration, the archive and admission can share
  one batched call.
* **Synchronous** `decide(state, questions, images, timeout)` — used in
  `sync_d1` mode and by admission; returns `None` (never raises) on any
  transport error, counting it in `error_count`.
* **Asynchronous** `submit_async(context_key, …)` + `get_cached(key)` —
  a 2-thread pool refreshes a per-context cache in the background;
  duplicate in-flight keys are dropped. This is the default
  (`async_cached`): the loop reads whatever is cached for *this context
  signature* (strictly no “latest answer for a different context” in
  module/arbiter calls — `fallback_to_latest=False`) and keeps playing.
* **Graceful disable.** `enabled = enabled ∧ api_key present`;
  `LIQUID_API_KEY` comes from the environment or a `.env` file.
  Disabled ⇒ every call returns `None` immediately and all callers fall
  back to local logic. The JPEG frame (≤ 8 images) is attached so d1
  answers are multimodal (vision + state text).

### 8.11 Slow LLM worker — `llm_worker.py`

`SlowLLMWorker` (Spec §12) turns an `ExpansionRequest` (source module,
problem description, world-state snapshot, existing action ids) into at
most one new macro:

* **Generator selection.** (1) a caller-supplied `custom_generator`
  (used by tests and embedders); else (2) the **Codex CLI**:
  `codex exec --ephemeral --skip-git-repo-check -s read-only
  -c model_reasoning_effort="low" --output-schema <schema> -o <out>`
  with a 20 s timeout, prompted to propose *one* bounded macro as JSON
  matching `PROPOSAL_JSON_SCHEMA` (id, description ≤ 200 chars,
  `maximum_duration` 2–8, termination phrase, 2–8 primitives drawn from
  the enum of allowed primitive ids, strategy id); else/on any failure
  (3) a **deterministic fallback template** per source module
  (e.g. survival/combat → `evasive_burst_n`: strafe-right, shoot,
  strafe-left, backpedal; navigation → `corner_clear_step_n`: use, turn,
  forward, strafe). The fallback guarantees the slow path is testable
  and useful with no LLM at all.
* **Concurrency.** One background thread, single-flight: `enqueue_request`
  returns `False` while busy, and the controller only enqueues when not
  busy. Results wait in a completed list until the controller drains
  them at phase 0 of a tick. The worker never touches the vocabulary
  itself — generation and admission are separate (next section).

### 8.12 Admission pipeline — `admission.py`

`ProposalAdmissionPipeline.evaluate_and_admit()` (Spec §13) — the gate
every proposal must pass; rejection at any step returns
`AdmissionDecisionResult(admitted=False, rejection_reason=…)`:

1. **Parse**: extract the JSON object (fences tolerated) and validate
   into `MacroActionProposal` (id 2–64 chars, description 5–256,
   duration 1–16, ≥ 1 primitive).
2. **Legality**: id must match `^[a-z][a-z0-9_]{1,62}$`, must not shadow
   a built-in primitive, and must construct a valid `ActionSpec`
   (known primitives only, expansion length ≤ duration) — this reuses
   the same validator as hand-written actions.
3. **Sandbox**: `BoundedSimulator.project_action()` on the reference
   state; a rollout with survival probability 0 from a
   non-critical (HP > 25) state is rejected as predicted-fatal.
4. **d1-ultra gate** (only when d1 is enabled): a `noul` question
   (“should this bounded macro be admitted as safe, finite and
   tactically useful?”) plus a tactical-quality `score`. Rejected when
   `noul < 0.40`, unless quality ≥ 0.85 *and* noul ≥ 0.20 (a strong
   macro with a lukewarm safety vote survives; a weak one doesn't).
5. **Admit**: `vocabulary.register_admitted_macro(spec)` and an archive
   entry seeded with the sandbox expected value (success rate 0.65).

Only step 5 mutates anything. Admitted macros persist across runs via
`runs/<scenario>/macros.json` and are re-validated on load (§13).

### 8.13 Controller orchestration — `controller.py`

`DoomDecisionController` wires all of the above (§7) and owns the small
amounts of cross-tick state:

* **Per-module local memories** — the counters the expansion triggers
  read: `consecutive_damage_ticks` (any incoming damage last tick),
  `repeated_failures` (arbiter-executed step had damage > 8 or death),
  `consecutive_stalls` (navigation only: chose a `move_*`-containing
  action but displaced < 4 units), `plateau_ticks`. These are updated
  from the executed result each tick, after module evaluation.
* **Cached reactive action** — the last arbiter pick, reused in
  `critical` budget mode.
* **Dashboard/recorder hooks** — opt-in; dashboard failures are caught
  and permanently disable the dashboard, never play.
* **`replace_module(name, module)`** — validates the slot name and swaps
  the module in the evaluator (used by the acceptance test to inject a
  custom goal module that adopts an admitted macro).
* **`restore_macros(specs)` / `admitted_macros()`** — round-trip
  non-built-in vocabulary entries for persistence and for the
  dashboard/metrics count.
* **`close()`** — drains pending proposals (so their traces are logged),
  shuts down the module pool, slow worker, d1 executor and the game.

`ControllerConfig` (frozen pydantic) is the play-time configuration;
see §12 for every field.

### 8.14 Logging & visualisation — `logger.py`, `visualizer.py`, `charts.py`

**`DecisionLogger`** appends two JSONL streams (`ticks.jsonl`,
`proposals.jsonl`) under `log_dir`. `TickTrace` fields: timestamp, tick,
state hash, context signature, budget mode, available actions, per-module
outputs (top action, confidence, uncertainty, expansion request, local
*and* d1 probability maps, `used_d1_ultra`), projection summaries,
arbiter distribution, selected action, primitive steps actually
executed, full exploration state, active strategy, reward outcome, d1
arbiter distribution, and a `learning` block (network share for the
selected action, gate share, module weights, explored flag, exploration
floor). `ProposalTrace` records request context, raw proposal, parsed
proposal, validation/admission outcome, admitted id and d1 probability;
`record_macro_performance()` additionally appends follow-up traces with
the rewards later obtained by executing an admitted macro, so its
subsequent performance is auditable.

Since trace schema version 1 (`logger.TRACE_SCHEMA_VERSION`) each tick
also carries the decision's *anatomy*, built by `tracing.py` from values
the fast path already computes (nothing in it feeds back into control):
`state` (vitals, position, walls, every visible enemy and pickup with
angle, distance and screen box), `pruned_actions` (each vocabulary action
left off the menu → the first precondition it failed, from
`PreconditionSpec.failing_condition`, or `unsupported_by_scenario`),
per-module `utility_heuristic` / `utility_learned` / `trust` /
`utility_blended` / `d1_weight` / `memory` inside `module_outputs`,
`arbiter` (scores, the full component breakdown including the module-vote
and projection terms, table/gate/used module weights, gate share,
temperature, `pick_rule` ∈ committed/explored/greedy/sampled/critical_cached,
score margin, committing module), `projection_chain` (the selected
action's rollout step by step), `steering` (the 4-way strategy decision
with scores, probabilities, the active strategy before/after and the
archive), `exploration_state.terms` (the four quarter-terms and three
dampers), `outcome` (what the action changed plus the five per-module
rewards), `slow_path_request`, `budget_sec` and `timing_ms`. All of these
are optional, so traces written before them still parse. `ProposalTrace`
gains the drain `tick`, `source` (codex/template/custom), `source_module`,
per-stage `stage_results` (parse → legality → sandbox → d1 → admit, each
with pass/skip and a reason), `sandbox_summary` and `admitted_strategy_id`.

**`visualizer.render_hud_frame()`** composes a 1080×480 split-screen
frame (640×480 game view with tick/HP/action banners + a right panel
showing the five modules' top actions and confidences, the arbiter's
top-6 distribution, projection and exploration readouts).
`EpisodeRecorder` collects these when `record_frames` is on and exports
GIF (Pillow) or MP4 (via `ffmpeg`). `render_decision_dashboard()` /
`LiveDecisionDashboard` render the 560×760 Tk side window used with
`--visible`: d1 status, per-module d1-vs-local picks, the d1 arbiter
pick vs the executed action, and the latest Codex recommendations with
ADMITTED/REJECTED tags.

**`charts.render_learning_curves()`** reads `metrics.jsonl` and draws
the 2×2 dark-themed `learning_curves.png`: episode reward, cleared/
survived rates, health & kills, and network-share + per-module losses
(log scale). Rolling means use the same `rolling_mean` helper that
best-checkpoint selection uses.

### 8.15 Episode bundles & the web explainer — `tracing.py`, `export.py`, `web/`

The web explainer is a static site that replays one recorded episode
tick by tick and explains every level of the decision with a three-layer
explainer (one sentence, a paragraph, and the formula with that tick's
numbers substituted). The browser never talks to ViZDoom: it reads
**episode bundles** written by `python -m system1_doom.export` (§11).

A bundle is one folder per episode:

| File | Contents |
|---|---|
| `episode.json` | `EpisodeMeta`: schema version, scenario, seed, model (`heuristics`/`best`/`latest`), checkpoint info, which brains were on, play config, the `run_episode` result, tick range, the action catalog (description, primitives, preconditions, execution cost, 12-number encoding) and each module's question |
| `ticks.jsonl` | One enriched `TickTrace` per tick (§8.14) |
| `proposals.jsonl` | One `ProposalTrace` per slow-path proposal |
| `frames/00042.jpg` | The 320×240 screen the controller saw when it **decided** tick 42 (captured at state acquisition by `RecordingBridge`, so overlays drawn from `state` line up with the picture); `frames/end.jpg` is the screen after the last action |
| `metrics.jsonl`, `evaluation.json`, `macros.json` | Copied from the run folder when present: one `MetricsRow` per training episode, the `EvaluationSummary` of `train.evaluate`, and the admitted macros as `ActionSpec`s |
| `trust.json` | `TrustFile`: `action_counts` (keyed `<context>\|<action>`), `context_counts`, `trust_count`, network share and episodes from the loaded checkpoint |

`--schema` dumps one JSON Schema (from the pydantic models) whose
`$defs` hold `EpisodeMeta`, `TickTrace`, `ProposalTrace`,
`BundleIndexEntry`, and the models of the copied run files
(`MetricsRow`, `EvaluationSummary`, `TrustFile`, `ActionSpec`);
`web/scripts/gen-types.mjs` turns it into `web/src/schema/bundle.ts`, so
the Python models and the browser cannot drift apart. `--check`
validates a bundle and every file `episode.json` lists against the
models and checks that every tick has a frame; `--index DIR` writes `DIR/index.json`, the
list the app's episode picker reads.

The app (`web/`, see `web/README.md`) has four screens over one shared
timeline, picked from tabs in the top bar. The URL hash is
`#<episode>/<tick>/<screen>`; a link without a screen opens the tick
inspector, and a fresh visit opens the overview.

**Overview** is the whole controller on one diagram: the six-beat fast
path down the middle (freeze the world, shorten the menu, five opinions,
one decision, act, see and remember), the slow path on the right (a
module asks, the slow worker writes, the admission gate, the macro joins
the menu), learning on the left (five rewards, the replay buffer, the
learned networks with their trust λ and gate share g), the bounded
simulator, the strategy archive and d1-ultra. Every box shows the current
tick's number and opens its explanation; the slow-path boxes light while
a request is in flight or a proposal arrives; dashed arrows are learned,
dotted ones d1-ultra. During playback a pulse runs down the fast path
once per tick (not under reduced motion). The **tour** walks the six
beats on the inspector over a featured tick (the first kill with an
enemy in view, else the first tick with one), one coach mark per beat
naming the invariant it shows, then ends on the hierarchy.

**Tick** (the inspector) shows, for the tick under the timeline cursor:
the frame with enemy/pickup boxes, the ±12° aim band and
wall-distance arcs drawn from the trace; the world state and its five
context buckets; the menu (legal, pruned with the failed precondition,
and macros admitted during the episode); the simulator's projections and
the selected action's rollout; the five modules' probabilities, split
into heuristic (solid) and learned (hatched, by trust λ) shares; the
arbiter's score for each action stacked from its parts, the table and
gate module-weight rings, and the pick rule in words; the motor's steps
in words, with reflexes marked; and the outcome, its five module rewards
and where it is filed.

**Hierarchy** draws the same tick as a tower of six levels, slowest at
the top, each as the same decision card (its menu, a score per option,
the rule that chose, its bounds, what it reads and writes): growing the
menu (the admission gate's five stages, or the macros admitted so far),
steering (the archive's four-way choice, decided after the action with
that tick's pressure, and the 12 archive slots), the menu (legal and
pruned), the five opinions, the arbiter's decision, and the motor's
steps. Side cards feed the levels with drawn connectors: exploration
pressure (its four terms, the dampers and the clamp, recomputed from
`exploration_state` — the arbiter of tick t uses the state left by tick
t − 1), d1-ultra, the learned networks and the simulator.

**Learning** answers how the networks earned their say and what they
do with it at this tick. Across episodes: the evaluation table (each
brain on the same seeded episodes) and the two recordings of the same
seed side by side on one tick axis; then the training run from
`metrics.jsonl` as small multiples (reward, decisions, kills, health,
cleared and survived rates, network share, the exploration floor, which
falls linearly from 0.6 to 0.05 over the first 100 episodes, and the
losses), with the checkpoint and this recording marked. At this tick:
the trust map from `trust.json` (situations × the actions tried in
training, λ = n ÷ (n + 25), this tick's situation pinned) beside this
tick's row with each module's heuristic, learned and blended utility;
the gate view (the hand-written module weights, the gate's proposal and
the normalised blend by g the arbiter used, marking the modules whose
own top pick was taken, which are the only ones the gate learns from);
and the reward anatomy (the five module rewards and the raw 8-step
return, γ = 0.9, each becomes). Without networks, the trust map and gate
view say so and link to the recording that has them. A Plain/Formula
toggle hides or shows the arithmetic on every screen. Two demo bundles
ship in `web/public/episodes/`.

---

## 9. The slow path end-to-end

```text
module detects a failure pattern (e.g. navigation stalls ≥ 4)
  → DecisionOutput.request_action_expansion = True (+ description)
  → controller (if worker idle) enqueues ExpansionRequest   [tick N]
  → background thread: codex exec (20 s cap) or fallback template
  → AdmissionPipeline: parse → legality → sandbox → d1 gate
  → AdmissionDecisionResult queued
  → controller drains it at phase 0 of a later tick, logs ProposalTrace
  → if admitted: macro is in the vocabulary + archive from that tick on
  → modules can rank it, the arbiter can pick it (committed-pick rule
    lets a convinced module make it stick), the learner encodes and
    scores it immediately, and its rewards flow into proposals.jsonl
```

Invariants: the fast loop never waits for any of this; at most one
request is in flight; nothing is admitted without passing the same
`ActionSpec` validator as built-in actions; disabling the slow path
(`enable_slow_llm=False`) removes the whole column with no other change.

---

## 10. The learning loop end-to-end

```text
train.py / cli.py --learn
  per episode:  controller.run_episode()
                  └─ every tick: Learner.record_step(state_vec,
                       action_vec, result, module_top_actions, context)
                  └─ episode end: Learner.end_episode()
                       8-step γ=0.9 returns → RunningStats → ReplayBuffer
                       trust counters (context|action, context) += 1
                learn_from_episode(): Learner.train() — 200 Adam steps,
                  batch 256 (value nets on own rewards; gate on goal
                  return where its module's pick was executed)
                metrics row appended; checkpoint.pt + replay.npz +
                  macros.json saved; if rolling-20 reward beats
                  best_score → checkpoint copied to best.pt
                learning_curves.png redrawn every --chart-every episodes
  per tick (play): Learner.module_utilities(state, actions) → per-module
                  predictions; λ = n/(n+25) per (context, action) blends
                  them into module utilities; gate_weights(state) blended
                  into arbiter module weights by gate trust
```

Key behaviours: resume is automatic (`checkpoint.pt` + `replay.npz` +
episode numbering continue); `best.pt` usually outperforms the latest
checkpoint because value learning oscillates, so `cli.py` plays with
`best.pt` by preference while `--learn` continues from `checkpoint.pt`;
exploration during training is the `exploration_floor`, decayed linearly
0.6 → 0.05 over the first 100 episodes (`exploration_schedule`);
`--evaluate` replays identical seeds (`EVAL_SEED_BASE = 10_000 + i`)
greedily with heuristics vs latest vs best and writes `evaluation.json`.

---

## 11. Entry points & CLI reference

### `python -m system1_doom.cli` — play / watch

| Flag | Default | Meaning |
|---|---|---|
| `--scenario` | `deadly_corridor.cfg` | ViZDoom scenario cfg (name or path) |
| `--episodes N` | 0 | Play N complete episodes (cap `--ticks` each, default 500); prints a JSON summary with per-episode cleared/reward/kills/actions |
| `--ticks N` | 15 (or episode cap) | Control ticks to run when `--episodes` is unset |
| `--mode` | `sync_d1` | `sync_d1` (blocking batched d1 per tick, budget 5 s) or `async_cached` (cache-only, budget 0.04 s) |
| `--disable-d1` | — | No Liquid calls at all |
| `--disable-slow-llm` | — | No Codex slow path |
| `--visible` | — | 640×480 ViZDoom window + live dashboard (unless `--no-dashboard`); default step delay becomes 120 ms |
| `--step-delay-ms` | 0 (120 if visible) | Pause after each game step |
| `--save-gif/--save-mp4` | — | Record HUD frames and export on exit |
| `--log-dir` | `logs` | Where `ticks.jsonl`/`proposals.jsonl` go |
| `--run-dir` | `runs/<scenario-stem>` | Run folder to load trained models/macros from |
| `--no-learned` | — | Ignore `best.pt`/`checkpoint.pt`; pure heuristics |
| `--learn` | — | Continue training between episodes (exploration floor 0.05); requires torch |

Output is a JSON summary on stdout (episode results, d1 call/error
counts, log paths; per-episode training lines go to stderr when
`--learn`). Without `--episodes` it runs the fixed tick count and
reports total reward and the action sequence.

### `python -m system1_doom.train` — train / evaluate

| Flag | Default | Meaning |
|---|---|---|
| `--scenario` | `deadly_corridor.cfg` | Scenario to train on (any cfg; metrics/models are per run folder) |
| `--episodes` | 100 | Episodes this session (numbering resumes) |
| `--max-ticks` | 500 | Decision cap per episode |
| `--run-dir` | `runs/<scenario-stem>` | Run folder |
| `--fresh` | — | Delete models/history in the run folder first |
| `--train-steps` | 200 | Gradient steps after each episode |
| `--trust-count` | 25 | Tries of an action in a context before its network gets 50% weight |
| `--explore-start/--explore-end/--explore-decay` | 0.6 / 0.05 / 100 | Linear exploration-floor schedule |
| `--chart-every` | 5 | Redraw `learning_curves.png` every N episodes |
| `--seed` | — | ViZDoom + network seed |
| `--d1` | off | Use d1-ultra (`async_cached`) while training |
| `--codex` | off | Let the slow Codex worker propose macros while training |
| `--evaluate N` | 0 | Skip training; compare heuristics/latest/best on N identical seeded episodes and write `evaluation.json` |

One line per episode is printed
(`ep … reward … kills … hp … clear/dead/alive … net % … explore … loss … ticks … s`),
followed by a session summary (first-vs-last window means, network share,
replay size). Exit code 2 with the install hint when torch/matplotlib is
missing, and on checkpoint mismatch (with a `--fresh` remedy).

### `python -m system1_doom.export` — record episode bundles for the web explainer

| Flag | Default | Meaning |
|---|---|---|
| `--scenario` | `deadly_corridor.cfg` | ViZDoom scenario cfg |
| `--episodes N` | 1 | Episodes to record, with seeds `seed, seed+1, …` |
| `--seed` | 7 | Seed of the first episode (`env.restart_episode(seed)` before each) |
| `--model` | `heuristics` | `heuristics`, `best` (`best.pt`) or `latest` (`checkpoint.pt`) from the run folder |
| `--run-dir` | `runs/<scenario-stem>` | Run folder with trained models, macros and metrics |
| `--out` | `bundles/<stem>-<model>-<seed>` | Bundle folder (a parent folder when `--episodes` > 1) |
| `--name`, `--title` | folder name / generated | How the app lists the episode |
| `--max-ticks` | 500 | Decision cap per episode |
| `--d1` | off | Use d1-ultra (needs `LIQUID_API_KEY`) |
| `--codex` | off | Let the slow path call the Codex CLI; otherwise it runs on fallback templates |
| `--no-slow-path` | — | Switch the slow path off |
| `--deterministic` | off | Always take the arbiter's top score |
| `--check BUNDLE` | — | Validate a bundle and exit (exit code 1 on problems) |
| `--index DIR` | — | Write `DIR/index.json` listing its bundles and exit |
| `--schema OUT.json` | — | Write the bundle JSON Schema and exit |

Recording uses `async_cached` mode with a 40 ms budget, exploration
floor 0 and `record_experience` off, so a replay only reads the
networks. To publish a bundle in the app:

```bash
python -m system1_doom.export --scenario deadly_corridor.cfg --seed 9 --model latest \
    --out web/public/episodes/deadly_corridor-learned-9
python -m system1_doom.export --check web/public/episodes/deadly_corridor-learned-9
python -m system1_doom.export --index web/public/episodes
```

There is no `python -m system1_doom` `__main__`; use the three module
entry points above (or embed `DoomDecisionController` directly — §17).

---

## 12. Configuration reference

### `ControllerConfig` (`controller.py`, frozen)

| Field | Default | Effect |
|---|---|---|
| `execution_mode` | `async_cached` | `async_cached` (d1 from cache, non-blocking refresh) vs `sync_d1` (one batched blocking d1 call per stage) |
| `enable_d1_ultra` | `True` | Master d1 switch (still inert without an API key) |
| `enable_slow_llm` | `True` | Master Codex-slow-path switch |
| `use_codex_cli` | `True` | Use `codex exec` when available; else fallback templates |
| `tick_budget_sec` | `0.035` | Per-tick budget driving the budget-mode thresholds |
| `reduced_budget_threshold_sec` | `0.012` | At/below ⇒ reduced mode (no projections) |
| `critical_budget_threshold_sec` | `0.004` | At/below ⇒ critical mode (cached reactive action) |
| `log_dir` | `logs` | JSONL log directory |
| `deterministic_arbiter` | `False` | Always take the arbiter's top-scored action |
| `show_dashboard` | `False` | Live Tk dashboard (set by `--visible`) |
| `exploration_floor` | `0.0` | Per-tick probability of a tempered exploratory pick (mutated by the training schedule via `ctrl.exploration_floor`) |
| `record_experience` | `False` | Record learner transitions each tick (on during training/`--learn`) |
| `record_frames` | `False` | Capture HUD frames for GIF/MP4 export |

### `LearnerConfig` (`learning.py`, frozen)

`gamma=0.9`, `n_step=8`, `hidden=64`, `gate_hidden=32`, `lr=1e-3`,
`batch_size=256`, `train_steps=200`, `replay_capacity=100_000`,
`trust_count=25.0`, `gate_temperature=0.5`, `seed=0`.
(Architecture fields `hidden`/`gate_hidden` are frozen into checkpoints.)

### `ProjectionLimits` (`simulator.py`)

`max_candidate_count=16`, `max_simulation_depth=4`,
`max_wall_clock_budget_sec=0.015`, `max_branching_factor=2` — see §8.3.

### Environment variables & files

`LIQUID_API_KEY` (env or `.env` in CWD/repo root) enables d1-ultra.
Presence of the `codex` binary enables real slow-path generation.
Everything else is CLI/config driven — there is no other global config.

---

## 13. Files on disk: logs, runs, checkpoints

**`logs/` (or `--log-dir`)** — `ticks.jsonl` (one `TickTrace`/tick),
`proposals.jsonl` (one `ProposalTrace`/admission + follow-up
performance records). These are append-only and are the audit trail:
any executed action can be replayed as state → module outputs →
projections → arbiter distribution → pick.

**`runs/<scenario-stem>/`** (training run folder, `RunStore` in `train.py`):

| File | Contents |
|---|---|
| `checkpoint.pt` | Latest learner: value nets, gate, optimiser, running stats, trust counters, best score (format v1, §8.9) |
| `best.pt` | Copy of the checkpoint with the best rolling-20 mean episode reward (≥ 5 episodes required) |
| `replay.npz` | Replay buffer arrays (`states, actions, returns, gate_mask`), chronological |
| `macros.json` | Admitted Codex macros as `ActionSpec` JSON; **re-validated on load**, so a hand-edited file cannot smuggle in an illegal action |
| `metrics.jsonl` | One row/episode: reward, kills, health, armor, ticks, cleared/died, transitions, replay size, network share, exploration floor, explored steps, per-module + gate losses, macro count, timings, d1 calls |
| `learning_curves.png` | The 2×2 chart of §8.14 |
| `evaluation.json` | Latest `--evaluate` report (heuristics/latest/best means over identical seeds) |
| `ticks.jsonl`, `proposals.jsonl` | The run's own decision logs (log_dir is pointed at the run folder during training); `eval/` holds evaluation logs |

The repo ships example runs for `deadly_corridor` (300 episodes) and
`defend_the_center` (200 episodes) — see §15.

**`bundles/<stem>-<model>-<seed>/`** — episode bundles written by
`python -m system1_doom.export` (§8.15); gitignored. Bundles the web app
should show are written to `web/public/episodes/<name>/` instead and
committed, with `web/public/episodes/index.json` listing them.

---

## 14. Failure modes & graceful degradation

| Failure | Behaviour |
|---|---|
| No `LIQUID_API_KEY` / `--disable-d1` | d1 client disabled; modules, arbiter, exploration and admission fall back to local logic; play is unaffected (this is an acceptance criterion, covered by tests). |
| d1 network error / timeout | `decide()` returns `None`, `error_count += 1`; cached answers simply age; no tick ever fails because of d1. |
| No `codex` binary / Codex times out (20 s) | Deterministic fallback template proposal instead; admission still applies. `--disable-slow-llm` removes the path entirely. Slow worker busy ⇒ new expansion requests are dropped, not queued unboundedly. |
| Illegal LLM proposal | Rejected with a reason at parse/legality/sandbox/d1 step; vocabulary unchanged; rejection is logged in `proposals.jsonl`. |
| No PyTorch | `cli.py` plays on heuristics (warning on stderr); `train.py` exits 2 with the install hint. The core package never imports torch at module load (the learner is injected). |
| Checkpoint mismatch (format/feature sizes/modules) | `CheckpointMismatch` → `train` exits 2 advising `--fresh`; `cli --learn` exits 2; plain `cli` falls back to heuristics. |
| Training error mid-run | Design intent: logged, play continues on current weights. Ctrl+C: the pending episode is discarded, progress is saved, and the same command resumes. Save/load of checkpoints and replay uses write-to-temp + `os.replace` (atomic). |
| Tick budget collapses | Reduced mode drops projections; critical mode replays the cached reactive action with stub module outputs (same trace schema). A module missing its thread deadline is recomputed locally without d1. |
| Dashboard/Tk failure | Caught once, dashboard disabled for the session, play continues. MP4 export requires `ffmpeg` and raises if frames are empty — only when explicitly requested. |
| Episode finished mid-burst | The motor burst stops early (`terminated_early`), and the bridge returns a well-formed result; `auto_restart` or `run_episode` handles the restart. |
| No action passes preconditions | Vocabulary falls back to `(turn_left, turn_right, move_forward)`; if the scenario can't support a candidate, the precondition list is used instead — the arbiter always faces a non-empty finite set. |

---

## 15. Measured results

From `docs/superpowers/specs/2026-10-23-learning-controller-design.md`
(2026-10-23; `--evaluate 30`, identical held-out seeds, greedy, no
exploration, d1/Codex off):

| Scenario | Training | Heuristics only | Latest checkpoint | Best checkpoint |
|---|---|---|---|---|
| `deadly_corridor` | 300 ep | 13% cleared, reward 548 | 37% cleared, reward 1034 | **50% cleared, reward 1407** (ep. 220) |
| `defend_the_center` | 200 ep | 8.5 kills | **17.4 kills** | — |

The shipped run folders' `evaluation.json` files contain the same kind of
comparison (e.g. deadly corridor: reward 548 → 1034, cleared 13.3% →
36.7%; defend the center: 8.5 → 17.4 kills with episodes lasting
68 → 117 ticks). Improvement is measured with `--evaluate` on identical
seeds rather than by an automated test, because a meaningful run takes
minutes and the heuristic baseline already solves `basic.cfg` (a test
does assert that: `test_heuristic_controller_clears_basic_scenario`).

Two empirical findings worth knowing before tuning:

* **Per-context trust matters.** A single global λ (network weight by
  total experience) improved reward for ~75 episodes then degraded it;
  `λ = n/(n+25)` per (context, action) is the fix (§8.9).
* **`weave_fire` matters.** The compound strafe-fire primitives exist
  because no single primitive could move and fire in one step; a scripted
  check cleared 8/20 deadly-corridor seeds with `weave_fire` vs 2/20
  with `peek_and_fire`.

---

## 16. Testing

```bash
python -m pytest            # 57 tests, 14 files, from the repo root
```

Tests use real ViZDoom headlessly, so the suite takes longer than a pure
unit suite; a few tests are **live** (marked `test_live_*`) and assert on
a real `LIQUID_API_KEY`/d1-ultra — run them only with a key available,
and expect them to fail (by assertion, not skip) without one.

| File | Covers |
|---|---|
| `test_state_and_actions.py` | `WorldState` immutability, hash/text rendering, `ActionSpec` rejection of unbounded/illegal expansions, precondition filtering of the default vocabulary |
| `test_features.py` | State/action encoder sizes, bounds, threat/pickup sensitivity, strafe-fire decomposition, new-macro encodability |
| `test_modules.py` | All five modules satisfy the `DecisionOutput` contract without network; expansion request on repeated failure; live batched d1 evaluation |
| `test_arbiter.py` | Arbiter combines modules/projections/exploration without network; live d1 arbiter decision |
| `test_simulator.py` | Projection bounds enforcement; combat-vs-retreat-vs-pickup outcome ordering; empirical cache effect |
| `test_exploration_and_archive.py` | Pressure rises on stall / falls under high risk; archive capacity bound + explicit strategy decision |
| `test_d1_client.py` | Request serialisation with a mock transport; async non-blocking cache; disabled mode; live API call |
| `test_llm_and_admission.py` | Admission rejects illegal/unbounded proposals; admits a valid one (live d1 + sandbox); async Codex worker generation + admission |
| `test_learning.py` | n-step returns; per-module rewards; running stats vs NumPy; bounded replay round-trip; each value net learns its own signal; gate learns whom to trust; episode→replay credit assignment; discard; checkpoint round-trip/overrides/mismatch |
| `test_training.py` | `train` writes the full run folder and resumes with continued numbering; admitted macros persist and are re-validated; exploration schedule shape |
| `test_controller_e2e.py` | **Acceptance**: plays normally with LLMs disabled, traces every tick, budget degradation; module replacement + discover→admit→retain→reuse a new macro; live ViZDoom in sync + async d1 modes |
| `test_level_clearance.py` | Heuristic controller clears `basic.cfg`; every executed step follows the selected action's own plan; learning controller records every decision |
| `test_visualizer.py` | HUD frame render + GIF save; dashboard shows d1/Codex sections |
| `test_export.py` | A 5-tick `basic.cfg` bundle has every file and a frame per tick; pruned + legal actions partition the vocabulary; each arbiter breakdown adds up to its score; module anatomy and outcome are recorded; the schema dump validates a trace; pre-anatomy traces still parse; `failing_condition` agrees with `is_satisfied`; admission records each stage |

The web explainer has its own checks, run from `web/`: `npm run build`
and `npm run lint` (type-check and oxlint), `npm test` (Vitest: the
loader and the trace readings on a five-tick fixture bundle) and
`npm run e2e` (Playwright: scrubbing to tick 5 shows the traced action
in every panel).

---

## 17. Extending the system

**Replace a module** (the sanctioned extension point): subclass
`DecisionModule`, implement `compute_local_utilities()` and
`check_expansion_needed()`, then `ctrl.replace_module("goal", MyModule())`.
You inherit learned-value blending, d1 blending, entropy confidence and
the output contract for free.

**Add a built-in action**: append an `ActionSpec` to `DEFAULT_PRIMITIVES`
or `DEFAULT_MACROS` in `actions.py`. For a *new primitive* you must also
teach the motor (`PRIMITIVE_BUTTONS`/`FLAG_TO_PRIMITIVE` in `motor.py`),
the simulator's `_step_primitive`, and decide whether `features.py`
needs a new component (if so, `ACTION_DIM` changes and old checkpoints
will — correctly — refuse to load).

**Add a scenario**: point `--scenario` at any ViZDoom cfg. If its
win condition differs, extend `ViZDoomBridge.level_cleared()`; if it
lacks turn/attack buttons, the motor and vocabulary filtering already
adapt (aim falls back to strafing).

**Use a different slow-path generator**: pass
`custom_generator: Callable[[ExpansionRequest], str]` to
`DoomDecisionController` (it must return the proposal JSON string) — or
replace the Codex invocation in `llm_worker._invoke_codex_cli`.
Admission is unchanged either way; that separation is the point.

**Embed the controller** (no CLI):

```python
from system1_doom.controller import ControllerConfig, DoomDecisionController
from system1_doom.vizdoom_env import ViZDoomBridge

env = ViZDoomBridge(scenario="basic.cfg", window_visible=False,
                    include_jpeg_frame=False)
cfg = ControllerConfig(enable_d1_ultra=False, enable_slow_llm=False,
                       log_dir="logs", deterministic_arbiter=True)
ctrl = DoomDecisionController(env=env, config=cfg)   # learner=None → heuristics
try:
    result = ctrl.run_episode(max_ticks=500)
    print(result["cleared"], result["reward"], result["actions"])
finally:
    ctrl.close()
```

**Tune learning**: `--trust-count` (how fast networks earn authority),
`--train-steps`, `--explore-*` (the exploration floor schedule), and
`LearnerConfig` fields (`gamma`, `n_step`, `hidden`, …) via
`load_learner(..., overrides=…)` when embedding `train.py`'s helpers
(`RunStore`, `learn_from_episode`, `load_play_learner` are importable
and reused by `cli.py`).

---

## 18. Glossary

| Term | Meaning |
|---|---|
| **Action / `ActionSpec`** | The only executable unit: a bounded tuple of primitives with preconditions, a duration cap and a termination condition. Primitives are 1-step actions; macros are named multi-step ones. |
| **Arbiter** | `FinalArbiter` — turns five module distributions, projections, exploration, archive and d1 advice into one finite pick, with an auditable score breakdown. |
| **Budget mode** | Per-tick degradation tier (`full`/`reduced`/`critical`) derived from the tick budget (§7). |
| **Committed pick** | Arbiter shortcut: a module that is overwhelmingly certain (utility ≥ 5, margin ≥ 4, p ≥ 0.9) decides directly (§8.5). |
| **Context signature** | Coarse bucketed state key (`hp:…\|ammo:…\|enemies:…`) used for novelty, trust, caching and archive matching (§6.1). |
| **d1-ultra** | Liquid AI's decision model; answers typed `choice`/`noul`/`score` questions. Advisory everywhere it appears. |
| **Exploration floor** | Flat probability of a tempered exploratory arbiter pick (training-time), distinct from exploration *pressure*. |
| **Exploration pressure / temperature** | State-dependent exploration intensity from `ExplorationController`; temperature = 0.10 + pressure drives arbiter sampling. |
| **Gate** | Learned `state → 5` network estimating how much following each module pays off in goal return; blended into arbiter module weights. |
| **Macro** | Multi-primitive `ActionSpec` (`is_macro=True`); built-in, hand-added, or Codex-proposed-and-admitted. |
| **Module** | One of survival/combat/navigation/resource/goal; a `DecisionModule` producing a distribution over the same candidate set. |
| **Network share** | Experience-weighted mean trust λ — how much of play the learned networks currently steer. |
| **Projection** | A bounded analytic rollout (`ProjectedOutcome`) of one candidate action: expected value, damage, resources, survival. |
| **Slow path** | The async Codex → admission pipeline that can grow the action vocabulary; never blocks play. |
| **Trust λ** | `n/(n+25)`: weight of a network's opinion for an action tried `n` times in the current context. |
| **Tick** | One control decision (state → pick → motor burst of ≈ 8 game tics), not one ViZDoom game tic. |

---

*Maintainers: when a formula, threshold or file format changes, update the
matching section here and the design notes in
`docs/superpowers/specs/`. The spec (`docs/spec.md`) states intent; this
document states behaviour; the code is the truth when they disagree.*
