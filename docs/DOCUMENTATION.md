# system1-doom — Full Package Documentation

> **Every decision this agent makes is made by a Liquid AI d1-ultra
> instance.** The code renders evidence, keeps the bounds and presses the
> keys; it never ranks, scores, blends, thresholds or picks an action
> itself. Five senses (survival, combat, navigation, resource, goal) each
> see only the evidence in their scope and decide whether to send a
> message; a central instance hears the messages and chooses the action;
> the motor executes that action's fixed primitives. A missed answer is
> recorded as a miss, never filled in by a rule. A slow System 2 reads
> the history and changes what each instance sees, one change at a time:
> nine reflectors propose, a central instance chooses one change or none,
> and a trial judge keeps or reverts it; each of them is a d1-ultra
> instance too.
>
> This document explains *how everything works*: the architecture, every
> module, every bound that matters, the entry points, the files on disk,
> what happens when d1-ultra does not answer, and how to extend the system.
>
> Design: [`superpowers/specs/2026-10-25-d1-decision-maker-design.md`](superpowers/specs/2026-10-25-d1-decision-maker-design.md)
> (“the design”; System 1 and System 2 are built, and the web app's
> rewrite is the third pull request).
> Background: [`spec.md`](spec.md) (the original 21-section spec, whose
> §21 invariant still holds) and
> [`superpowers/specs/2026-10-23-learning-controller-design.md`](superpowers/specs/2026-10-23-learning-controller-design.md)
> (the value networks). This document describes the code as it is.

**Package:** `system1-doom` 0.3.0 · **Python:** ≥ 3.11 · **Source layout:**
`src/system1_doom/` (32 modules, ≈ 11,500 LOC) · **Tests:** `tests/`
(25 files, 232 tests, 4 of them live) · **Web explainer:** `web/` (Vite +
React + TypeScript; still on trace schema 1 until the third pull request
of the design), online at <https://danielriosgarza.github.io/system1_doom/>

---

## Table of contents

1. [The one rule & design principles](#1-the-one-rule--design-principles)
2. [Architecture at a glance](#2-architecture-at-a-glance)
3. [Installation & external dependencies](#3-installation--external-dependencies)
4. [Quick start](#4-quick-start)
5. [Repository & module map](#5-repository--module-map)
6. [Core vocabulary: state, actions, context](#6-core-vocabulary-state-actions-context)
7. [System 1, tick by tick](#7-system-1-tick-by-tick)
8. [Subsystem deep dives](#8-subsystem-deep-dives)
   - 8.1 [Environment bridge — `vizdoom_env.py`](#81-environment-bridge--vizdoom_envpy)
   - 8.2 [Tactical motor — `motor.py`](#82-tactical-motor--motorpy)
   - 8.3 [Bounded simulator — `simulator.py`](#83-bounded-simulator--simulatorpy)
   - 8.4 [The configuration — `configuration.py`](#84-the-configuration--configurationpy)
   - 8.5 [Evidence channels — `evidence.py`](#85-evidence-channels--evidencepy)
   - 8.6 [Instances and senses — `instance.py`, `senses.py`](#86-instances-and-senses--instancepy-sensespy)
   - 8.7 [The central instance and the pick — `system1.py`](#87-the-central-instance-and-the-pick--system1py)
   - 8.8 [Relevance and history — `relevance.py`, `history.py`](#88-relevance-and-history--relevancepy-historypy)
   - 8.9 [Value networks and features — `learning.py`, `features.py`](#89-value-networks-and-features--learningpy-featurespy)
   - 8.10 [d1-ultra client — `d1_client.py`](#810-d1-ultra-client--d1_clientpy)
   - 8.11 [Slow LLM worker — `llm_worker.py`](#811-slow-llm-worker--llm_workerpy)
   - 8.12 [Admission pipeline — `admission.py`](#812-admission-pipeline--admissionpy)
   - 8.13 [Controller and strategy archive — `controller.py`, `archive.py`](#813-controller-and-strategy-archive--controllerpy-archivepy)
   - 8.14 [Traces & visualisation — `logger.py`, `tracing.py`, `visualizer.py`, `charts.py`](#814-traces--visualisation--loggerpy-tracingpy-visualizerpy-chartspy)
   - 8.15 [Episode bundles & the web explainer — `export.py`, `serve.py`, `web/`](#815-episode-bundles--the-web-explainer--exportpy-servepy-web)
   - 8.16 [System 2 — `system2.py`, `reflectors.py`, `history_channels.py`, `history_test.py`, `reflection.py`](#816-system-2--system2py-reflectorspy-history_channelspy-history_testpy-reflectionpy)
9. [The slow path end-to-end](#9-the-slow-path-end-to-end)
10. [The learning loop end-to-end](#10-the-learning-loop-end-to-end)
11. [Entry points & CLI reference](#11-entry-points--cli-reference)
12. [Configuration reference](#12-configuration-reference)
13. [Files on disk: logs, runs, checkpoints](#13-files-on-disk-logs-runs-checkpoints)
14. [Misses, budgets & failure modes](#14-misses-budgets--failure-modes)
15. [Measured results](#15-measured-results)
16. [Testing](#16-testing)
17. [Extending the system](#17-extending-the-system)
18. [Glossary](#18-glossary)

---

## 1. The one rule & design principles

> **Generative systems may propose possibilities; bounded decision systems
> decide what enters the controller and what is executed.** (Spec §21)

The design sharpens that sentence into one rule: *hand-written rules that
choose are cheating.* Every choice is a d1-ultra instance: one call with
its own evidence (a scope) and its own finite questions. What stays
hand-written is bounds and evidence only.

| Principle | How it is enforced in code |
|---|---|
| **Every decision is a d1-ultra instance** | The executed action is the central instance's answer to a `choice` over the legal menu (`system1.pick_action`); a macro enters the menu only on the admit instance's yes (`instance.run_admit`). `tests/test_architecture.py` checks that keys are pressed only in `controller.py`, from the pick or the typed miss, and that only `system1.py` builds a `Pick` (random numbers are drawn only there and in the history test's seeded sample of stored ticks). System 2's choices are instances too: each reflector's proposal, System 2's central's one change or none, and the trial judge's keep or revert (§8.16); its code only filters the finite set of changes by the bounds, tests, applies and reverts. |
| **Code renders evidence, keeps bounds and presses keys** | `evidence.py` renders channels as plain text; `configuration.Bounds` holds every limit (per-call budget, pool sizes, scope size, channel caps, history ring, miss limit); `motor.py` executes the chosen action's fixed primitives. None of them ranks, scores or picks an action. |
| **An instance sees only its scope** | The payload's `state` is the rendered scope and nothing else; `images` carries the frame only when `frame` is in scope; the choice criteria are exactly the legal menu, so projections and values never become criteria (`tests/test_instance.py`). |
| **A miss is a miss** | A sense that times out, fails, names an off-menu action or returns malformed probabilities is silent; a central miss holds no keys for the decision's 8 frames; three central misses in a row end the episode as `connection_lost`. Nothing stands in for a missing answer (§14). |
| **What is learned is evidence** | The value networks' predictions and the relevance ledger's counts are channels (`values`, `relevance`); nothing learned is multiplied into a decision. The gate network that used to blend module weights is gone. |
| **Boundedness everywhere** | Scopes ≤ 7 channels; channel caps of 6 enemies, 6 pickups, 6 history steps, 3 summaries; 6 calls in flight for System 1 and 2 for the slow path; macros ≤ 16 primitives; projections ≤ 16 candidates × depth 4 × 2 branches × 15 ms; archive ≤ 12 strategies; history ring 2,000 ticks; replay ≤ 100 k transitions; System 2: one cycle at a time, ≤ 40 calls per cycle, one trial in flight, trials and cooling of 60 decisions, a history-test sample of 24 ticks. |
| **Everything is traceable** | Every tick writes a schema-2 `TickTrace` with the six instances' scopes, verbatim evidence, image references, full answers, timing and usage, the messages, the pick and the executed primitives; every tick is also stored whole in `history.jsonl`, from which any instance's evidence re-renders byte for byte. Every System 2 cycle, verdict and note is a line of `reflections.jsonl`, with each reflector's verbatim evidence and full answers (§8.16). |

There is deliberately **no** fallback policy, no hand-written arbiter, no
exploration formula, no admission threshold and no rule that changes the
configuration. Without `LIQUID_API_KEY`
there is nothing that could decide, so `cli`, `train`, `export` and
`serve` refuse to play and say so.

---

## 2. Architecture at a glance

```text
 Evidence channels (evidence.py): vitals · threats · incoming · outgoing · pickups · geometry
      position · progress · history · frame · menu · projections (simulator) · values (networks)
      novelty · archive                      central only: exploration · messages · relevance
        │           │            │             │            │
   ┌────▼───┐  ┌────▼───┐  ┌─────▼─────┐  ┌────▼────┐  ┌───▼──┐   five senses (senses.py): one
   │survival│  │ combat │  │navigation │  │resource │  │ goal │   d1-ultra call each, in parallel,
   └────┬───┘  └────┬───┘  └─────┬─────┘  └────┬────┘  └───┬──┘   each seeing its scope only
        └───────────┴──── messages: action, reason, strength ──┘   (speak ≥ 0.5 is d1's own yes)
                                 │
                       ┌─────────▼──────────┐   one d1-ultra call (system1.py): hears the
                       │  Central instance  │   messages, each sense's relevance record, the
                       └─────────┬──────────┘   exploration level, vitals and the menu
                                 │ pick: top (exploit) · drawn (explore, seeded) · missed
                       ┌─────────▼──────────┐
                       │ Act: the action's  │   motor.py: fixed primitives over 8 frames,
                       │ fixed primitives   │   or no keys when the central missed
                       └─────────┬──────────┘
                                 ▼
   History (history.jsonl, ring of 2,000) ──► relevance ledger (end of episode, relevance.json)
   Value networks (learning.py) ◄── executed decisions, trained between episodes

   Slow path (async, its own pool of 2): request_expansion → Codex or template → parse →
   legality → sandbox → admit instance (d1-ultra noul) → the macro joins the configuration
   at the next tick boundary

   System 2 (its own thread, on the slow path's pool of 2; every 20 decisions or at an episode end):
   history over three windows → nine reflectors (one d1-ultra call each) → proposals →
   System 2's central (one change, or none) → history test for a scope change (24 stored ticks
   re-run) → queued for the next tick boundary → trial of 60 decisions → trial judge: keep or revert
```

**What is hand-written, and what is not.** The legal menu
(preconditions), the simulator, the value networks, the motor's reflexes
inside a primitive, and every bound are code. They produce evidence or
limits. Every choice among actions (what each sense recommends, whether
it speaks, which action is executed, whether a macro is admitted) and
every change to the configuration (which change, whether to keep it) is
a d1-ultra answer.

**System 2** (the design, §8–9; §8.16 here) reflects on the history and
changes the configuration one step at a time, on its own thread, without
ever holding up a tick. Its reflectors propose, its central chooses one
change or none, a scope change must first pass the history test (the
instance re-run under the new scope on the agent's own stored ticks),
and after 60 decisions the trial judge keeps or reverts the change.
Changes take effect only at a tick boundary, through the same hook an
admitted macro uses (§8.4). `--no-system2` switches it off.

---

## 3. Installation & external dependencies

### Python dependencies (`pyproject.toml`)

| Group | Packages | Needed for |
|---|---|---|
| core (always) | `numpy`, `pillow`, `pydantic ≥2.6`, `requests`, `vizdoom ≥1.2` | everything: state, evidence and trace models (pydantic), frames (pillow), d1-ultra HTTP (requests), the game itself |
| `learn` (optional) | `torch ≥2.2` (CPU index), `matplotlib ≥3.8` | the value networks (`train.py`, the `values` channel in play), learning curves. Without torch play goes on and the `values` channel says no networks are loaded; `train` prints the install hint and exits `2`. |
| `dev` (optional) | `pytest ≥8`, `jsonschema` | test suite |

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
| `LIQUID_API_KEY` | **Yes, to play** | Read from env var `LIQUID_API_KEY`, else from `.env` in CWD or repo root (`d1_client.load_api_key()`). d1-ultra makes every decision, so `cli`, `train`, `export` and `serve` exit `2` without it. `export --check`, `--index` and `--schema` read files only and need no key. Tests answer from a fake transport and need no key except the four live ones. |
| `codex` CLI (OpenAI Codex) | Only for real slow-path proposals | Detected with `shutil.which("codex")`. Absent ⇒ deterministic fallback templates are used instead (§8.11). Disable entirely with `--disable-slow-llm` / `--no-slow-path`. |
| `ffmpeg` | Only for `--save-mp4` | GIF export needs only Pillow. |
| Tkinter + a display | Only for the live dashboard | Enabled by `--visible` (unless `--no-dashboard`); any failure disables the dashboard silently and play continues. |
| DejaVu fonts | Optional | Used by the dashboard renderer if present; falls back to Pillow's default font. |

---

## 4. Quick start

```bash
export LIQUID_API_KEY=...   # or put it in .env; every decision is a d1-ultra call

# 1) Play 15 decisions of basic.cfg and print a JSON summary: per-episode
#    result, cost, misses, mean tick time, and each instance's counters.
python -m system1_doom.cli --scenario basic.cfg --disable-slow-llm

# 2) Watch it play, with the six instances in a side window.
python -m system1_doom.cli --scenario deadly_corridor.cfg --episodes 1 --visible

# 3) Train the value networks on episodes d1-ultra plays (headless, resumes;
#    about 6 calls per decision, so 50 episodes are thousands of calls).
python -m system1_doom.train --scenario deadly_corridor.cfg --episodes 50

# 4) Compare no, latest and best networks as evidence on identical seeds.
python -m system1_doom.train --scenario deadly_corridor.cfg --evaluate 10

# 5) Record a bundle (schema 2) and check it.
python -m system1_doom.export --scenario deadly_corridor.cfg --seed 9 --networks best \
    --out bundles/deadly_corridor-best-9
python -m system1_doom.export --check bundles/deadly_corridor-best-9

# 6) Play live and stream each tick to a local server (the web app renders
#    schema-2 ticks from the design's third pull request on).
python -m system1_doom.serve --scenario deadly_corridor.cfg --networks best
```

Play writes `ticks.jsonl`, `history.jsonl`, `proposals.jsonl`,
`reflections.jsonl` (System 2's cycles) and the frames d1-ultra saw under
`--log-dir` (default `logs/`), and updates the relevance ledger in
`runs/<scenario-stem>/relevance.json`. The configuration System 2 reaches
is saved in `runs/<scenario-stem>/configuration.json` (System 2's own
state in `system2.json`), and the next run in that folder starts from it,
so System 2's work carries on; `--fresh-configuration` starts from the
design's version 1 instead, and `--no-system2` keeps the configuration as
it starts. Each run says on stderr which configuration it starts from.
Training writes
to `runs/<scenario-stem>/`; re-running the same command resumes from
`checkpoint.pt` — add `--fresh` to start over. Full flag reference: §11.

---

## 5. Repository & module map

```text
system1_doom/
├── pyproject.toml
├── docs/
│   ├── spec.md                     # original 21-section implementation spec
│   ├── DOCUMENTATION.md            # ← this file
│   └── superpowers/
│       ├── specs/2026-10-25-d1-decision-maker-design.md   # the design this code follows
│       ├── specs/2026-10-23-learning-controller-design.md
│       └── plans/2026-10-23-d1-ultra-doom-controller.md
├── src/system1_doom/               # the package (see table below)
├── tests/                          # 25 files, 232 tests, fake_d1.py and system2_fixtures.py (§16)
├── web/                            # the web explainer: Vite + React app and demo bundles (§8.15)
├── runs/<scenario>/                # training output, the relevance ledger, the configuration and System 2's state (§13)
├── bundles/                        # episode bundles from `system1_doom.export` (§13)
├── logs/                           # default decision logs (ticks, history, proposals, reflections, frames)
└── _vizdoom.ini, _vizdoom/         # ViZDoom engine config / WAD search dir
```

| File | Lines | Responsibility (one line) |
|---|---:|---|
| `state.py` | 156 | Immutable `WorldState`/`Observation` pydantic models; state hash, context signature |
| `actions.py` | 354 | Finite action vocabulary: 13 primitives + 6 built-in macros, preconditions, `ActionSpec` validation |
| `vizdoom_env.py` | 454 | ViZDoom ⇄ controller bridge: builds `WorldState`, executes an action's primitives or an idle, level-clear rules |
| `motor.py` | 378 | Closed-loop execution of a primitive plan (aim, tracking strafe, pickup steering); the idle burst |
| `simulator.py` | 276 | Bounded analytic short-horizon projections + empirical transition cache: the `projections` channel |
| `configuration.py` | 251 | The versioned configuration: scopes, concerns, reasons, exploration level, strategy, admitted macros, `Bounds` (System 2's included) |
| `evidence.py` | 462 | The 18 evidence channels rendered as plain text; `EvidenceInputs`; deterministic scope rendering |
| `instance.py` | 316 | One d1-ultra instance: the payload, the finite questions per kind, reading answers, typed misses; `run_system2_instance` for System 2's |
| `senses.py` | 92 | The five senses: run in parallel, their messages |
| `system1.py` | 168 | One System 1 tick: senses, the central's scope, the central, the pick (`top`/`drawn`/`missed`) |
| `relevance.py` | 172 | The relevance ledger: each sense's record per context, pure update and rendering |
| `history.py` | 190 | `TickRecord`, the history ring (with each tick's frame in memory) and `history.jsonl`, re-rendering a stored tick |
| `archive.py` | 129 | Bounded (≤12) strategy archive, kept as evidence |
| `features.py` | 137 | Fixed-size encodings (`WorldState → float32[32]`, `ActionSpec → float32[12]`), per-network rewards, n-step returns |
| `learning.py` | 373 | Five value MLPs, replay buffer, trust counts, checkpoints (PyTorch) |
| `d1_client.py` | 365 | d1-ultra HTTP client: typed questions, per-call budget, 429 handling, typed misses, usage and per-instance counters |
| `llm_worker.py` | 242 | Async slow path: builds a bounded expansion prompt, runs `codex exec`, falls back to templates |
| `admission.py` | 301 | Parse, legality and sandbox bounds, then the admit instance, for macro proposals |
| `history_channels.py` | 605 | System 2's evidence: the history channels over three windows (`h_outcomes`, `h_sense:<name>`, `h_central`, `h_actions`, `h_strategy`, `h_exploration`, `h_config`, `h_tests`, `messages`) |
| `reflectors.py` | 430 | The nine reflectors: specs, finite change menus, the bounds that filter them, `apply_change`, configuration diffs |
| `history_test.py` | 482 | The history test: a scope change's instance re-run on 24 stratified stored ticks; metrics, margin rule, noise estimate |
| `system2.py` | 996 | `System2`: its thread, the cycle, System 2's central, trials and the judge, safety reverts, cooling, `system2.json` |
| `reflection.py` | 235 | `ReflectionTrace`, `TrialVerdictTrace`, `System2Note` (`reflections.jsonl`) and an episode's System 2 counts |
| `controller.py` | 750 | `DoomDecisionController`: one tick and one episode; configuration hook; System 2's host; misses; cost |
| `logger.py` | 145 | Schema-2 `TickTrace`/`ProposalTrace` JSONL logging, and System 2's `reflections.jsonl` |
| `tracing.py` | 276 | Typed trace records (state, pruning, projections, outcome, slow-path request), read-only |
| `export.py` | 914 | Episode bundles, `--check`, `--index`, `--schema` (`python -m system1_doom.export`) |
| `serve.py` | 636 | Live mode: plays episodes as `export` does and streams every tick (`python -m system1_doom.serve`) |
| `visualizer.py` | 347 | Split-screen HUD frames, GIF/MP4 recorder, live Tk panel of the six instances |
| `charts.py` | 117 | `learning_curves.png` from `metrics.jsonl` (matplotlib, dark theme) |
| `cli.py` | 220 | Play/watch entry point (`python -m system1_doom.cli`) |
| `train.py` | 492 | Training/evaluation entry point, `RunStore`, resume, best-checkpoint tracking, which configuration a run starts from (`starting_configuration`) (`python -m system1_doom.train`) |
| `__init__.py` | 3 | Package docstring + `__version__` |

Dependencies point “downwards” only: `controller` wires everything;
`system1` depends on `senses`, `instance`, `configuration` and
`d1_client`; `instance` on `evidence` and `d1_client`; `evidence` on
`configuration`, `relevance` and `tracing`; `learning` only on
`features`; `system2` on `reflectors`, `history_channels`,
`history_test`, `reflection`, `instance` and `history`, and reaches the
controller only through its `System2Host` protocol; nothing in System 1
depends on System 2, and nothing depends on `cli`/`train`/`export`/`serve`.

---

## 6. Core vocabulary: state, actions, context

### 6.1 `WorldState` — the immutable snapshot (`state.py`)

All pydantic models are `frozen=True`: within one tick every instance's
evidence is rendered from the *identical* snapshot (Spec §4).

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
  empirical cache, the novelty counts, the relevance ledger and the value
  networks' tried counts. It is the unit of “have I been here before?”
  for the whole system.
* **`to_d1_state_text()`** — a compact text snapshot, now used only in the
  slow worker's prompt; the instances see the evidence channels (§8.5).

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
so the menu is never empty. Examples: `shoot` needs
ammo ≥ 1 and a visible enemy; `move_backward` only exists at health ≤ 45
with an enemy visible (it is a retreat, not a general movement); `use`
needs a wall within 64 units.

`execution_cost = 0.02·len(expansion) + 0.02·(#shoot-like steps)` is a
term of the simulator's projected value (§8.3). `register_admitted_macro()`
is the single door through which new actions enter the vocabulary (the
controller calls it when a configuration with a new admitted macro takes
effect), and it refuses non-macros; `retire_macro()` removes one and
refuses built-ins.

### 6.3 Where actions can be unavailable

The vocabulary says what *may* be chosen; the scenario says what *can* be
executed. `DoomDecisionController.step()` additionally filters candidates
through `env.action_supported(action)` (e.g. a scenario without turn
buttons cannot run `turn_left`), keeping the precondition-filtered list
if the motor filter would empty it. The result is the menu: the criteria
of every action choice that tick.

---

## 7. System 1, tick by tick

`DoomDecisionController.step()` (`controller.py`) runs one decision. There
is no tick budget that degrades the decision: every tick waits for
d1-ultra inside a per-call budget (5 s by default, `--call-budget`), and
ViZDoom advances only when the controller steps it, so waiting does not
change the game.

| Step | What happens | Where |
|---|---|---|
| 1. Configuration | A pending configuration (a System 2 change or revert, an admitted macro, or `request_configuration`) takes effect here and nowhere else; the vocabulary and the active strategy follow it; it is saved to `runs/<scenario>/configuration.json`, and System 2 is told (its trial starts) | `_apply_pending_configuration` |
| 2. Slow path | Finished proposals are drained and logged as `ProposalTrace`s | `llm_worker.drain_completed_results`, `_handle_proposals` |
| 3. State and menu | `acquire_world_state()` → frozen `WorldState`; the legal menu is the vocabulary's precondition filter, narrowed to actions the scenario's buttons support (the unnarrowed list if that would be empty); every other action is listed as pruned with the first precondition it failed | `_menu`, `tracing.pruned_actions` |
| 4. Evidence | One `EvidenceInputs` for every channel: the simulator's projections of the menu, the value networks' predictions and tried counts, novelty counts, the archive, the relevance records for this context, counters (decisions, under-fire streak, stall streak, sectors), the frame saved as `frames/<tick>.jpg` | `evidence.build_inputs` |
| 5. System 1 | Five senses in parallel (pool of 6), each its own d1-ultra call; then the central, one call over the messages that arrived; then the pick | `System1.tick` (§8.6, §8.7) |
| 6. Act | The picked action's fixed primitives (`env.execute_action`), or, when the central missed, no keys for the decision's 8 frames (`env.execute_idle`) | the only two key-pressing calls, checked by `tests/test_architecture.py` |
| 7. Value networks | When `record_experience` is on and an action was executed: `Learner.record_step(state_vec, action_vec, result, action_id, context)` | §8.9 |
| 8. Counters | Novelty count, the simulator's empirical cache, the archive outcome of the active strategy, an admitted macro's follow-up reward, the stall streak; or, on a miss, the central-miss streak, which ends the episode as `connection_lost` at 3 | |
| 9. History and trace | The tick is stored whole in the history (`history.jsonl`, its frame kept in memory beside it); System 2 is told (`on_tick`: it counts the decision, checks a trial's safety bound, and may start a cycle on its own thread); a schema-2 `TickTrace` is logged (`ticks.jsonl`); the recorder and dashboard are fed | §8.8, §8.16, §8.14 |

Three properties to notice:

* **Nothing stands in for d1-ultra.** A silent or missed sense is
  silence; a missed central is an idle tick recorded with pick `missed`;
  three in a row end the episode. There is no cached action, no repeated
  pick and no local policy.
* **The configuration changes only at the tick boundary.** A change
  queued while a tick runs (by System 2, by the slow path's admit
  instance, or by `request_configuration`) waits for step 1 of the next tick, so every
  instance of a tick sees one configuration version, recorded in the trace.
* **`run_episode()`** loops `step()` until the ViZDoom episode ends,
  `max_ticks` decisions are made, play is stopped, or the connection is
  lost; then it finalises the learner's pending episode, updates and
  saves the relevance ledger, saves the configuration, tells System 2
  the episode ended, and returns a summary dict (`reward, kills,
  health, armor, cleared, died, finished, finished_reason, ticks,
  transitions, cost, misses, instances, actions, configuration_start,
  configuration_end, system2, traces`). `finished_reason` is one of `episode_end`,
  `max_ticks`, `stopped`, `connection_lost`. What “cleared” means is
  scenario-specific — see `ViZDoomBridge.level_cleared()` (§8.1).

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
  base64), the image of every instance with `frame` in scope, when
  `include_jpeg_frame` is on (the default).
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

**`execute_idle(frames)`** holds no keys for `frames // 2` motor steps
(4 steps for a decision's 8 frames) and accounts the result exactly as
an action's, labelled `missed` in the memory's state summaries: it is
what a tick whose central missed executes. `episode_cells_discovered`
feeds the `position` channel.

**`level_cleared()`** is deliberately scenario-specific: `basic` ⇒ ≥1 kill
alive; `deadly_corridor` ⇒ episode finished, alive, armor ≥ 100 (reached
the vest); `health_gathering` (non-supreme) and `defend_*` ⇒ finished
alive; default ⇒ finished alive with ≥1 kill or armor ≥ 100.
`episode_status()` exposes `{health, armor, kills, reward}`.
`auto_restart` (default `True`) restarts finished episodes on the next
acquire; `run_episode` disables it and manages restarts itself.
`restart_episode(seed)` also resets the motor's target lock and cell set.

### 8.2 Tactical motor — `motor.py`

The central instance picks an *action*; the motor executes that action's
**own** primitive list. The assists below are reflexes *inside* a
primitive (aim before firing, track while strafing), bounded by the plan;
they never choose an action. `idle(frames)` presses nothing, for a missed
decision.

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
Its purpose is cheap short-horizon evidence (Spec §8): its numbers reach
the instances only as the `projections` channel, headed “a rough
projection from a hand-written simulator, not the game”, and never as a
score of the decision. Its bounds are explicit and validated by pydantic:

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

### 8.4 The configuration — `configuration.py`

The configuration is everything that shapes what each instance sees, as
versioned, frozen data — what System 2 owns (§8.16). It is data only:
nothing in it decides.

```text
Configuration (version ≥ 1)
├── senses: {survival, combat, navigation, resource, goal} → SenseConfig
│     scope (channels), concern (named in its instructions), reasons (finite ids)
├── central: CentralConfig (scope, concern)
├── exploration_level: exploit | explore
├── active_strategy: an archive strategy id
├── admitted_macros: (ActionSpec…)         # macros admitted into the menu
└── bounds: Bounds                         # every hand-written limit, never a weight
```

**Initial scopes** (version 1, `default_configuration()`, the design's
tables):

| Instance | Scope | Reasons |
|---|---|---|
| survival | `vitals`, `threats`, `incoming`, `projections`, `menu` | health_critical, under_fire, enemy_too_close, recovering, no_threat |
| combat | `threats`, `outgoing`, `vitals`, `frame`, `projections`, `menu` | target_aimed, target_off_centre, several_enemies, low_ammo, no_target |
| navigation | `geometry`, `position`, `progress`, `projections`, `menu` | path_clear, wall_ahead, stalled, door_or_switch_ahead, unexplored_side |
| resource | `pickups`, `vitals`, `menu` | health_pickup_near, ammo_pickup_near, pickup_guarded, nothing_needed, nothing_visible |
| goal | `progress`, `archive`, `history`, `values`, `menu` | making_progress, plateau, strategy_fits, strategy_failing, nearly_done |
| central | `messages`, `relevance`, `exploration`, `vitals`, `menu` (+ `novelty` while exploring, if there is room) | — |

**Validation** (a configuration that breaks any of these does not load):
the senses are exactly the five, in order; every channel is known and
appears once; every scope contains `menu`; a scope holds at most
`max_scope_channels` (7) channels; a sense's scope never contains
`messages`, `relevance` or `exploration`; reasons are unique lowercase
snake_case ids; only macros can be admitted.

**`Bounds`** holds every number of the design in one place: per-call
budget 5 s; `yes_at` 0.5 (d1's own yes, for speaking and admitting);
scope 7 channels; caps of 6 enemies, 6 pickups, 6 history steps and 3
summaries; pools of 6 (System 1) and 2 (System 2); 1 trial in flight; 60
decisions of cooling; a history ring of 2,000; a history-test sample of
24; 40 System 2 calls per cycle; 3 consecutive central misses; 8 frames
per decision; an 8-step return with discount 0.9; a probability
tolerance of 0.02; a thin record under 5; a stall under 4 units. And
System 2's: a cycle every 20 new decisions; windows of 20 and 100
decisions and 3 episodes; trials of 60 decisions, extended by 20 when the
judge misses and ended as a revert with no verdict at its third miss; a
history test of 24 ticks with 4 noise re-asks, at most 4
per context, bad and good as the bottom and top quarter of returns, a
pass margin of 0.05 and a worst drop of 0.10; a safety revert at a
paid-off rate drop of 0.15 on 10 followed messages.

**Versions.** `with_changes(**fields)` returns the next version, validated
as a whole; `replace(**fields)` and `with_bounds(**fields)` keep the
version and are for setting up the initial configuration before play
(`--call-budget`, `--explore`, macros restored from a run folder).
`save()`/`load()` round-trip JSON. The entry points save the
configuration in play to `runs/<scenario>/configuration.json` at every
change that takes effect and at every episode end, and start from that
file when it exists (`--configuration PATH` names another,
`--fresh-configuration` starts from version 1; §11, §8.16). The
controller applies a queued configuration only at a tick boundary
(`request_configuration`, §8.13); the trace records each tick's
`configuration_version` and whether it changed, and the bundle the
configuration at the start and the end of the episode.

### 8.5 Evidence channels — `evidence.py`

A channel renders one named piece of evidence as plain text. Every
channel reads one `EvidenceInputs`, built once per tick by `build_inputs`
from the world state, the legal menu, the projections, the value
predictions, the novelty counts, the archive, the relevance records, the
counters, the messages, the exploration level and the frame reference.
A scope renders only its channels, in the fixed order of
`configuration.CHANNELS`, each under a `[name]` header line.

| Channel | What it renders | Source |
|---|---|---|
| `vitals` | health, armor, ammo, weapon | observation |
| `threats` | the visible enemies nearest first (at most 6): name, distance, angle, on-screen size, under the crosshair or attacking; the count | observation |
| `incoming` | damage taken since the last decision; consecutive decisions under fire | observation, counter |
| `outgoing` | damage dealt, hits and kills since the last decision | observation |
| `pickups` | the visible pickups nearest first (at most 6): name, category, distance, angle | observation |
| `geometry` | wall distance ahead, left, right; moving or still | depth buffer |
| `position` | x, y, facing; sectors discovered this episode | observation, bridge |
| `progress` | decisions so far, reward so far, kills, last displacement, stall streak | observation, counter |
| `history` | the last 6 primitives executed and the last 3 decision summaries | memory |
| `frame` | a one-line note; the 320 × 240 JPEG is attached as the call's image | screen buffer |
| `menu` | the legal actions now, each with its description | preconditions |
| `projections` | per legal action: expected value, damage in and out, survival, progress — headed “a rough projection from a hand-written simulator, not the game” | `simulator.py` |
| `values` | per legal action: each value network's predicted return (standardised) and how often the action was tried here in training — headed “learned from past play”; “no value networks are loaded” without them | `learning.py` |
| `novelty` | how often each legal action has been taken in this situation so far | controller counter |
| `archive` | the strategies, the active one and each one's record | `archive.py` |
| `exploration` | the level and what it asks of the chooser (central only) | configuration |
| `messages` | one line per spoken sense: “survival says strafe_left, strength 0.82, reason under fire.” (central only) | System 1 |
| `relevance` | each sense's record in this situation (central only, §8.8) | ledger |

Rendering is **deterministic**: the same inputs and scope give the same
text, byte for byte (golden-text tests in `tests/test_evidence.py`), so
a tick stored in the history re-renders exactly what each instance saw.
Nothing in this module ranks or scores an action; the menu is listed in
the vocabulary's order, and projections and values in the menu's order.

A survival sense's evidence on the test fixture, verbatim:

```text
[vitals]
health 64, armor 25, ammo 17, weapon pistol

[threats]
2 enemies visible, nearest first:
- Zombieman at distance 180, 2 deg left, size 24x56 px, under the crosshair
- DoomImp at distance 410, 21 deg right, size 20x40 px, attacking

[incoming]
damage taken since the last decision 8; consecutive decisions under fire 2

[menu]
the legal actions now:
- shoot: Aim and fire current weapon at visible enemy target
- strafe_left: Sidestep left perpendicular to heading to dodge projectiles or reposition
- approach_pickup: Sprint forward down the corridor toward visible armor, health, weapon, or goal pickup

[projections]
a rough projection from a hand-written simulator, not the game; per legal action:
- shoot: expected value +3.34, damage in 3.2, damage out 31.0, survival 0.77, progress 0.00
- strafe_left: expected value -0.25, damage in 2.4, damage out 0.0, survival 0.78, progress 0.15
- approach_pickup: not projected
```

### 8.6 Instances and senses — `instance.py`, `senses.py`

An **instance** is one d1-ultra call with its own scope and its own
finite questions. `InstanceSpec` is data (name, kind, scope, concern,
reasons); `run_instance` renders the scope, builds exactly one payload
and reads the answers:

* `state` is the rendered scope text, and nothing else;
* `images` carries the frame only when `frame` is in the scope;
* the questions depend on the kind, and every instruction starts with
  the instance's name, its concern and that it sees only the evidence
  given — it never says how to weigh anything:

| Kind | Question | d1 kind | Criteria |
|---|---|---|---|
| sense | `speak`: “Must the action chooser hear from you before the next decision?” | noul | — |
| sense | `action`: “Which legal action do you recommend now?” | choice | exactly the legal menu, id → description, in menu order |
| sense | `reason`: “Which reason best describes why?” | choice | the sense's reasons |
| central | `choose`: “Choose the action the agent executes now.” | choice | exactly the legal menu |
| admit | `admit`: “Should this proposed macro-action enter the agent's legal menu?” | noul | — |
| reflector | `speak`: “Must the slow system's central hear a proposal from you now?” | noul | — |
| reflector | `change`: “Which configuration change do you propose?” | choice | its change menu after the bounds (§8.16) |
| reflector | `reason`: “Which reason best describes why?” | choice | the reflector's reasons |
| system2_central | `configure`: “Choose the one configuration change to make now, or none.” | choice | the proposals the bounds still allow, then `none` |
| judge | `verdict`: “Keep this configuration change, or revert it?” | choice | `keep`, `revert` |

`InstanceResult` keeps everything for the trace and the history: scope,
verbatim evidence, image reference, every answer in full, `spoke`,
`strength`, the top `action` and its distribution, the top `reason`,
`missed` and `miss_reason`, the raw answer, latency and usage. System 2's
instances are sent with `run_system2_instance`: their evidence is history
text (never a frame), and they also fill `change` or `verdict` with its
distribution.

**Misses.** An answer is a miss when the call times out, fails, the
budget runs out waiting on an HTTP 429, the top action is not on the menu
or the top change not in the criteria (`off_menu`), or a distribution is malformed — a negative probability, or
a sum further than 0.02 from 1 (`malformed`). The raw answer is kept and
nothing is repaired or substituted. Ties in a choice go to the first
option in menu order.

The five **senses** (`senses.py`) run in parallel on System 1's pool,
each inside the per-call budget (the pool waits 2 s past the budget at
most, against a starved thread, and then records a timeout). A sense
speaks when its `speak` probability is at least `yes_at` (0.5): d1's own
yes, not a tuned threshold. A spoken sense sends a `Message` (sense,
action, reason, strength = the `speak` probability, unscaled) to the
central's `messages` channel; a silent sense is logged with the same
answers but reaches the central as silence, and a missed sense is silent
and marked `missed`.

### 8.7 The central instance and the pick — `system1.py`

`System1.tick(configuration, inputs, frame_b64)` runs one decision: the
five senses, the messages they sent (in sense order), then the central —
one call whose evidence is its scope with the messages and the
configuration's exploration level filled in. `central_scope()` adds
`novelty` while the level is `explore`, if the scope has room within its
7 channels.

`pick_action()` turns the central's answer into the action, and is the
only place a `Pick` is made:

| Pick | When | Action |
|---|---|---|
| `top` | level `exploit` | the action d1 gave the highest probability; on a tie the first in menu order, with `tie` and `tied` logged |
| `drawn` | level `explore` | one action drawn from d1's own distribution, walking the menu in order with a seeded `random.Random` (`--seed`); the uniform number is logged as `draw` |
| `missed` | the central missed | none: the controller holds no keys for the decision's 8 frames |

There is no temperature and no bonus. The `exploration` channel tells
the central what its level means, so d1 knows what is asked of it.
`System1Result` carries the inputs, the five sense results, the
central's result, the messages, the pick and the timings (`senses_ms`,
`central_ms`), and sums the tick's usage.

### 8.8 Relevance and history — `relevance.py`, `history.py`

**The relevance ledger** is each sense's track record per context
signature, shown to the central as counts in the `relevance` channel;
nothing in it is multiplied into a decision. At the end of every episode
`update_ledger()` walks the episode's ticks; for every tick where a sense
spoke:

* **followed**: the central executed the sense's action; **paid off**:
  the decision's n-step return (n = 8, γ = 0.9, over the per-decision
  game reward, `features.n_step_returns`) was positive;
* **overruled**: the central executed another action, and whether *that*
  action paid off, so the central can see when ignoring a sense was right;
* **calibration**: the sense's mean strength on ticks that paid off and on
  ticks that did not.

A tick whose central missed executed nothing, so it is neither followed
nor overruled (its idle reward still counts in the returns of the
decisions before it). The record renders as: “survival here: spoke 14,
followed 9, paid off 7 of 9; overruled 5, the chosen action paid off 2
of 5; mean strength 0.81 when it paid off, 0.64 when not.” A mean over
fewer than 5 ticks is shown with its count; a sense with no record says
so. Update and rendering are pure functions. The ledger
(`RelevanceLedger`, entries keyed `<sense>|<context>`) is saved to
`runs/<scenario>/relevance.json`, restored at start, grows across
episodes, and is copied into every bundle.

**The history** keeps every tick whole: a `TickRecord` holds the
`EvidenceInputs` (messages included), the six `InstanceResult`s, the
messages, the pick, the executed action and primitives, the reward, the
configuration version, the level and the strategy. `HistoryStore` keeps
the last 2,000 records in memory and appends every one to
`history.jsonl` in the log folder. `rerender(record, scope)` renders a
stored tick under any scope; under an instance's own scope it reproduces
the instance's evidence byte for byte (tested on every tick of a
recorded bundle). System 2's history test uses exactly this (§8.16).
Each ring record also keeps, in memory beside it, the frame its
instances were shown (`HistoryStore.frame(record)`), because a later
episode rewrites `frames/<tick>.jpg` in the log folder. A record carries
what the action changed (`outcome`) and whether it `stalled`, for
System 2's `h_outcomes`; older records without them still load.

### 8.9 Value networks and features — `learning.py`, `features.py`

The five value networks keep training between episodes, now on episodes
d1-ultra plays; their predictions are the `values` channel. They never
weigh in on a decision.

**Encodings** (`features.py`, sizes are part of the checkpoint format):
state → `float32[32]` (`STATE_DIM`: vitals, nearest enemy and pickup,
walls, damage, kills, motion, recent action mix) and action →
`float32[12]` (`ACTION_DIM`: the fraction of the action's steps per base
primitive, length, macro flag, pickup parameter). Because an action is
described by its composition, an admitted macro gets predictions the
moment it enters the menu.

**Per-network rewards** for one executed decision (`module_rewards`):

```text
survival    = −damage_taken/25 − 3·died
combat      =  0.5·hits_delta + 2·kills_delta
navigation  =  new 128-unit map cells entered this step (0/1)
resource    =  health_gain/25 + armor_gain/25 + ammo_gain/10
goal        =  scenario reward (the ViZDoom reward for the burst)
```

**Targets.** At episode end, each step's target is the 8-step discounted
return of its reward stream (γ = 0.9, truncated at episode end),
standardised by running mean/std (`RunningStats`, persisted in the
checkpoint).

**Networks** (PyTorch; `LearnerConfig`: hidden 64, lr 1e-3 Adam, batch
256, 200 steps/episode, replay 100 k, trust count 25, seed 0): five MLPs
`(state⊕action) 44 → 64 → 64 → 1`, batched as one `ModuleValueNets`.
`predict_returns(state, actions)` gives every candidate's standardised
prediction per network; `tried_counts(context, ids)` gives how often each
was tried in this context — both are rendered in `values`. `action_trust`
(`n/(n+25)`) and `network_share` remain as reports in metrics and charts.

**Experience.** `record_step()` is called only for executed decisions (a
missed tick executed nothing to learn from). `end_episode()` turns the
episode into returns, updates the running stats and the tried counts, and
appends to the 100 k ring-buffer replay (`replay.npz`). Training runs
200 Adam steps on batches of 256 between episodes, a no-op below 32
transitions.

**Checkpoints** (`checkpoint.pt`, format 1): value networks, optimiser,
running stats, counters, tried counts, last losses and `LearnerConfig`.
The gate network is gone: a checkpoint written before its removal loads,
its `gate` weights and gate loss are ignored (`LEGACY_GATE_KEYS`), and
the optimiser state keeps only the value networks' parameters. A replay
file with the old `gate_mask` column loads too. `load()` still raises
`CheckpointMismatch` on a format, feature-size or network-list mismatch.

### 8.10 d1-ultra client — `d1_client.py`

`POST https://api.liquid.ai/decisions/v1/systemone`, model `d1-ultra`,
payload `{model, state, questions, images}`; the answers come back by
question name with a `usage` block (input and output tokens, cost).

* **Typed questions** — `noul` (the probability a proposition holds),
  `choice` (probabilities over named criteria), `score`; answers are
  validated into `NoulAnswer`/`ChoiceAnswer`/`ScoreAnswer`.
* **`call(instance, state, questions, images, budget)`** never raises. It
  returns a `D1CallResult`: the response, or a typed miss (`timeout`,
  `error`, `http_429_exhausted`, `malformed` for a response without an
  answers object), with the latency, the retries and the usage. The
  budget bounds the call from start to answer, retries included.
* **HTTP 429** waits per `Retry-After` (seconds or an HTTP date; 0.5 s
  when absent) and counts a retry, but only while the budget lasts.
* **Pools.** Calls run on a worker pool sized by the owner: the
  controller's System 1 client has 6 workers (`system1_pool`), the slow
  path's client its own 2 (`system2_pool`), shared by the admit instance
  and System 2, so neither ever starves a tick.
* **Counters.** `counters()` gives, per instance name, calls, answers,
  misses by reason, retries, total latency, tokens and cost; the
  controller sums them per episode into `cost`, `misses` and `instances`.
* **Transport injection.** `TransportFn(url, headers, payload, timeout)`
  replaces the HTTP post; `tests/fake_d1.py` answers from the payload it
  receives, deterministically, and can be scripted to time out, raise,
  answer off the menu or return malformed probabilities at chosen calls.
* **The key** comes from `LIQUID_API_KEY` or `.env`; it is sent only as
  the bearer token and never logged.

### 8.11 Slow LLM worker — `llm_worker.py`

`SlowLLMWorker` (Spec §12) turns an `ExpansionRequest` (source, problem
description, world-state snapshot, existing action ids) into at most one
new macro:

* **Generator selection.** (1) a caller-supplied `custom_generator`
  (used by tests and embedders); else (2) the **Codex CLI**:
  `codex exec --ephemeral --skip-git-repo-check -s read-only
  -c model_reasoning_effort="low" --output-schema <schema> -o <out>`
  with a 20 s timeout, prompted to propose *one* bounded macro as JSON
  matching `PROPOSAL_JSON_SCHEMA` (id, description ≤ 200 chars,
  `maximum_duration` 2–8, termination phrase, 2–8 primitives drawn from
  the enum of allowed primitive ids, strategy id); else/on any failure
  (3) a **deterministic fallback template** per source
  (e.g. survival/combat → `evasive_burst_n`; navigation →
  `corner_clear_step_n`). Generation only proposes; it never decides.
* **Concurrency.** One background thread, single-flight: `enqueue_request`
  returns `False` while busy. Results wait until the controller drains
  them at the start of a tick. The worker never touches the vocabulary.
* **Who asks.** System 2's menu reflector: when System 2's central
  chooses `macro:<sense>`, System 2 calls
  `DoomDecisionController.request_expansion(source, description)` with a
  description built from the reflector's reason and that sense's concern
  (§8.16). The modules' expansion rules are gone; tests and embedders use
  the same entry point.

### 8.12 Admission pipeline — `admission.py`

`ProposalAdmissionPipeline.evaluate_and_admit()` (Spec §13). The first
three stages are bounds a proposal must satisfy before any instance sees
it; the decision is the admit instance's:

1. **Parse**: extract the JSON object (fences tolerated) and validate
   into `MacroActionProposal`.
2. **Legality**: id `^[a-z][a-z0-9_]{1,62}$`, no shadowing of a built-in,
   and a valid `ActionSpec` (known primitives only, expansion ≤ duration).
3. **Sandbox**: `BoundedSimulator.project_action()` on the reference
   state; a rollout predicted fatal from a state above 25 health fails
   the bound.
4. **The admit instance** (`instance.run_admit`, on the slow path's own
   client): one d1-ultra call whose state is `admit_evidence()` — the
   proposal, the sandbox rollout labelled as a rough projection, the
   request, and the current menu — and whose one question is the `admit`
   noul. A yes (≥ 0.5) admits; anything else, a miss included, rejects.
   There are no thresholds of our own.
5. **Admit**: the result carries the admitted `ActionSpec` and its
   strategy; the controller queues a configuration with the macro added,
   which joins the menu (and the archive) at the next tick boundary.

Every stage's pass or fail and reason, the sandbox summary and the
admit instance's full result are recorded in `proposals.jsonl`.
Admitted macros persist via `runs/<scenario>/macros.json` and are
re-validated on load (§13).

### 8.13 Controller and strategy archive — `controller.py`, `archive.py`

`DoomDecisionController(env, config, api_key, transport, custom_llm_generator,
learner)` wires everything (§7). It raises `MissingAPIKey` without a key
(tests pass a placeholder key with a fake transport). Besides the tick it owns:

* **The configuration hook** — `request_configuration(new)` queues a
  configuration; `_apply_pending_configuration()` applies it at the next
  tick boundary and syncs the vocabulary (admitted macros registered,
  dropped ones retired) and the active strategy. `restore_macros(specs)`
  sets the initial configuration's macros before the first tick, or
  queues them after. `admitted_macros()` and `known_actions()` (the
  vocabulary plus a pending configuration's macros) serve metrics and
  the bundle's action catalog.
* **The slow path** — `request_expansion(source, description)` enqueues an
  `ExpansionRequest` if the worker is idle; `drain_slow_path()` logs the
  finished proposals now rather than at the next tick (used at the end of
  a live episode).
* **System 2** — with `enable_system2` the controller builds
  `System2(self, …)` when play begins and is its host (`System2Host`:
  `configuration`, `next_configuration()` (a pending one, else the
  current), `history`, `logger`, `slow_client`, `episode_id`,
  `request_configuration`, `request_expansion`, `slow_path_available()`,
  `archive_lines()`). It calls `begin()` at the first tick (restoring
  `system2.json`), `on_tick(record)` once the history keeps a tick,
  `on_configuration_applied(old, new)` at the boundary, `on_proposal`
  for each drained proposal and `on_episode_end` after an episode with at
  least one tick. `add_reflection_listener(fn)` hands every System 2
  record to `fn` as it is written (serve streams them), and
  `wait_system2(timeout)` waits until System 2 is idle. The configuration
  is saved to `configuration_out` at every change that takes effect and
  at every episode end.
* **Counters** — decisions, novelty per `context|action`, the under-fire
  and stall streaks, the central-miss streak, missed ticks.
* **Episode accounting** — `run_episode` sums the client counters' deltas
  into `cost` (calls, tokens, USD), `misses` (total, missed ticks, by
  instance and reason) and `instances` (System 2's calls made meanwhile
  included), and adds `system2`, the counts of System 2's records written
  while the episode was played.
* **`use_log_dir(path)`** points the logs, history and frames at another
  folder (each live episode is its own bundle); **`close()`** lets
  System 2 finish a cycle or judge in flight (at most 120 s) and stops
  it, then drains proposals, shuts down System 1, both clients, the slow worker and the game.

**The strategy archive** (`archive.py`) is a bounded store of named ways
of playing, kept as evidence for the `archive` channel: at most 12
entries (`strategy_id`, context signature, action sequence, observed
reward, success rate, failure modes, usage count, novelty signature);
three are seeded. The controller records each executed decision's
outcome against the active strategy (EMA α 0.3; a step “fails” on damage
> 8 or death). Admitting beyond capacity evicts the oldest non-active
entry. Which strategy is active is the configuration's, not the
archive's: the four-way strategy meta-decision is gone, and System 2's
strategy reflector proposes a change of strategy (§8.16).

### 8.14 Traces & visualisation — `logger.py`, `tracing.py`, `visualizer.py`, `charts.py`

**`DecisionLogger`** appends `ticks.jsonl`, `proposals.jsonl` and, with
System 2 on, `reflections.jsonl` (`log_reflection`: one line per cycle,
verdict or note, §8.16) under the log folder. Trace schema version 2 (`logger.TRACE_SCHEMA_VERSION`):

| `TickTrace` field | Contents |
|---|---|
| `tick`, `episode_id`, `timestamp` | which decision |
| `configuration_version`, `configuration_changed` | the configuration the tick ran under |
| `state_hash`, `context_signature`, `state` | the frozen snapshot (vitals, position, walls, every enemy and pickup) |
| `available_actions`, `pruned_actions` | the legal menu; each other action → the first precondition it failed, or `unsupported_by_scenario` |
| `instances` | the six `InstanceResult`s in order (five senses, then `central`): scope, verbatim evidence, `image_ref` (`frames/<tick>.jpg` when `frame` is in scope), answers in full, spoke, strength, action, reason, missed, miss reason, raw answer, latency, usage |
| `messages` | the messages the central received |
| `pick`, `executed_action`, `primitive_steps_executed`, `missed` | how the answer became the action, and what the motor pressed (`idle` steps on a miss) |
| `outcome`, `reward_outcome` | what the action changed, with the five per-network rewards |
| `exploration_level`, `active_strategy` | from the configuration |
| `projection_results_used`, `projection_chain` | the simulator's numbers (also in the evidence), and the executed action's rollout |
| `slow_path_request`, `timing_ms`, `usage` | the request in flight; acquire, evidence, senses, central, decision, motor, total; the tick's tokens and cost |

`ProposalTrace` records request context, raw and parsed proposal, the
per-stage results (parse → legality → sandbox → d1 → admit), the sandbox
summary, the admission decision, the admitted id and strategy, and
`admit_instance` with `d1_admission_probability` (the admit instance's
probability). `record_macro_performance()` appends follow-up records of
the rewards an admitted macro later earned.

**`visualizer.render_hud_frame()`** composes a 1080×480 split-screen
frame: the game view, and a panel with the six instances (spoke or
silent with the strength bar, the action and reason, missed; the
central's pick and probability), the configuration version, the level,
the strategy, the messages and the tick's cost. `EpisodeRecorder` collects
frames for GIF (Pillow) or MP4 (`ffmpeg`). `render_decision_dashboard()`
/ `LiveDecisionDashboard` draw the 560×760 Tk side window used with
`--visible`: the same instance rows, then the latest proposals with
ADMITTED/REJECTED tags.

**`charts.render_learning_curves()`** draws `learning_curves.png` from
`metrics.jsonl`: episode reward, cleared/survived rates, health & kills,
and missed ticks with the value-network losses.

### 8.15 Episode bundles & the web explainer — `export.py`, `serve.py`, `web/`

The web explainer is a static site that replays one recorded episode
tick by tick. The browser never talks to ViZDoom: it reads **episode
bundles** written by `python -m system1_doom.export` (§11).

**Bundles, schema version 2.** A bundle is one folder per episode, every
decision in it made by d1-ultra:

| File | Contents |
|---|---|
| `episode.json` | `EpisodeMeta`: schema version 2, name, title, scenario, seed; `decider` (`d1-ultra`); `value_networks` (`none`/`best`/`latest`) and the checkpoint; the slow path; the play config (call budget, seed, max ticks); `configuration_start` and `configuration_end`; the `run_episode` result with `finished_reason`; `cost` (calls, tokens, USD), `misses` (total, missed ticks, by instance and reason) and per-instance counters; `system2` (System 2's counts: enabled, cycles, history tests and passes, trials started and judged, kept, reverted, calls, USD); tick range, buttons, frames, the action catalog, the files, package version and time |
| `ticks.jsonl` | One schema-2 `TickTrace` per tick (§8.14) |
| `history.jsonl` | One `TickRecord` per tick (§8.8): the inputs every instance's evidence re-renders from |
| `relevance.json` | The relevance ledger after the episode |
| `proposals.jsonl` | One `ProposalTrace` per slow-path proposal, with the admit instance |
| `reflections.jsonl` | System 2's records written during the episode, its end-of-episode cycle included: a `ReflectionTrace` per cycle, a `TrialVerdictTrace` per verdict, a `System2Note` per note (§8.16); empty with System 2 off |
| `frames/00042.jpg` | The 320×240 screen d1-ultra saw when it decided tick 42 (the image of every instance with `frame` in scope); `frames/end.jpg` is the screen after the last action |
| `metrics.jsonl`, `evaluation.json`, `macros.json`, `trust.json` | Copied from the run folder when present: one `MetricsRow` per training episode (with finished reason, missed ticks and cost), the `EvaluationSummary` (no, latest and best networks), the admitted macros, and the tried counts as `TrustFile` |

`--check BUNDLE` validates `episode.json` and every file it lists against
the models, and per tick: six instances with evidence, every
`image_ref` on disk, the executed action equal to the pick, the
configuration version within the episode's range, a frame; and each
line of `reflections.jsonl` as one of System 2's records, each cycle's
calls equal to its reflectors', central's and history test's and within
the bound, its configuration version within the episode's range, and
`episode.json`'s `system2` counts equal to the file's. A bundle of
another schema version gets one problem (`episode.json: schema_version 1,
expected 2`); an episode that ended as `connection_lost` is reported and
never shippable (`export` exits 1 after writing it). `--index DIR` writes
`DIR/index.json`, listing only shippable schema-2 bundles. `--schema
OUT.json` dumps one JSON Schema whose `$defs` hold `EpisodeMeta`,
`TickTrace`, `ProposalTrace`, `TickRecord`, `RelevanceLedger`,
`ReflectionTrace`, `TrialVerdictTrace`, `System2Note`,
`BundleIndexEntry` and the run-file models; the app's generated types
(`web/scripts/gen-types.mjs` → `web/src/schema/bundle.ts`) are
regenerated from it in the design's third pull request, together with
the app's `SUPPORTED_SCHEMA_VERSION`.

**The app is on schema version 1 until then.** Everything below
describes the app and its four shipped recordings as they are: recorded
by the architecture this design removed (five modules, an arbiter, an
exploration controller, a learned gate), and read by an app that rejects
any bundle whose schema version is not 1. The third pull request
replaces the recordings with episodes d1-ultra plays and rewrites the
screens around the instances (the design, §10).

The app (`web/`, see `web/README.md`) has six screens, picked from tabs
in the top bar (keys 1 to 6): Watch, The chain, The inspector, The
diagram, Learning and Growing the menu. The URL hash is
`#<episode>/<tick>/<screen>`, with the screen ids `watch`, `hierarchy`,
`tick`, `overview`, `learning` and `menu`; a link without a screen opens
the inspector, and a fresh visit lands on Watch with the first recording
that cleared the corridor (`#deadly_corridor-learned-9/0/watch`). Every
screen but Watch shares the timeline at the bottom, with the tick counter
and the pace.

**Watch** plays the recording at the controller's own pace, one decision
every 8 game frames (8 ÷ 35 s, about 0.23 s; Slow is one a second), with
its frames fetched and decoded ahead and a 100 ms crossfade from one to
the next. Beside the game, the decision chain reads the tower below as
six rows in plain words, slowest at the top: growing the menu (nothing
proposed, a module asked, a macro added or turned away), steering
(continue, switch, explore a variation, ask for a new playbook, with the
chosen option's probability), the menu (legal of known actions), the five
opinions (how many modules named the pick first), the decision (the
action and the pick rule in words) and act (the keys held over the four
steps). A row pulses when its words change from the decision before; on
the cleared recording the top row never changes and the bottom one
changes on 40 of the 51 decisions after the first. A click on a row pauses and opens The
chain at that decision with that level expanded. Under the game are
Play/Pause, the pace, the counter (decision N of M and the game time) and
a progress bar with the health line that seeks; below, a card per
recording (who played it and how it ended), each playing from its first
decision. Watch plays on its own only on a fresh visit or a link to its
first decision, never under reduced motion, and then loops, holding the
result 2.5 s at the end; anything the viewer does ends the loop, and a
link to a later decision waits for Play. A line under the game says it
is a recording replayed at the agent's pace and opens This recording at
the serve command that plays the same game live.

**The diagram** (`overview`) is the whole controller on one diagram: the six-beat fast
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
naming the invariant it shows, then ends on The chain; it starts from the
headers of The chain and The inspector, or the key t.

**The inspector** (`tick`) shows, for the tick under the timeline cursor:
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

**The chain** (`hierarchy`) draws the same tick as a tower of six levels, slowest at
the top, each as the same decision card (its menu, a score per option,
the rule that chose, its bounds, what it reads and writes): growing the
menu (the admission gate's five stages, or the macros admitted so far),
steering (the archive's four-way choice, decided after the action with
that tick's pressure, and the 12 archive slots), the menu (legal and
pruned), the five opinions, the arbiter's decision, and the motor's
steps. Side cards feed the levels with drawn connectors: what it saw
(the frame at that decision, with its overlays), exploration
pressure (its four terms, the dampers and the clamp, recomputed from
`exploration_state` — the arbiter of tick t uses the state left by tick
t − 1), d1-ultra, the learned networks and the simulator. Opened from a
row on Watch, it expands that level's card and flashes it.

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
view say so and link to the recording that has them.

**Growing the menu** follows the one path that adds to a menu, from a
module's complaint to a new chip. Over the whole episode, one strip per
module: the counter its expansion rule watches against its threshold
(survival: damage on 4 ticks in a row, or health under 35 with 15+
recent damage; combat: 3 failures, or 4 damage ticks against 2+ enemies;
navigation: 4 stalls; resource: ammo ≤ 2 and health ≤ 35 with a pickup
in view; goal's plateau counter is never advanced, so goal never asks),
the ticks where the other condition held, each request, the span the
worker was busy (one proposal in flight, 20 s), and the arrival at the
gate. Then, for the proposal that arrived at this tick or the last one
before it: the sentence that asked, the text as returned and the parsed
macro; the gate card from the hierarchy with each stage's reason and the
sandbox rollout (it fails only a predicted death from a state above 25
health, read at the request); the vocabulary on the tick before and the
tick it arrived, with the new macro's 12-number encoding beside a
built-in one; and the follow-up: ticks legal, picks, the reward each
time it ran, and when steering adopted its strategy, whose +0.15 the
arbiter adds to the legal actions of its sequence from the next tick.
On a recording without a request, the strips still show the counters
and the closest call, with a link to the recording of the same seed that
asked. A Plain/Formula toggle, in the header of The chain, The
inspector, Learning and Growing the menu, hides or shows the arithmetic
on every screen.

**The recordings.** Four bundles ship in `web/public/episodes/`, two
per seed, so the Learning screen's side-by-side pairs each recording
with the other brain on the same seed: `deadly_corridor-heuristics-9`
and `deadly_corridor-learned-9` (the 300-episode checkpoint, which
clears the corridor), and `deadly_corridor-heuristics-11` and
`deadly_corridor-learned-d1-11`, the same checkpoint with d1-ultra's
advice. The export of that architecture normally played in `async_cached` mode, where d1's answers
came from a cache that is never awaited, so a recording would show d1
only on ticks whose situation had been answered before. The d1 recording
was made with its `--d1-sync` flag instead (since removed): `execution_mode` `sync_d1` and a
tick budget of 5 s. The reduced and critical thresholds are absolute
(a budget of 12 ms or 4 ms or less), so every tick keeps the full budget
and waits for d1's batched answers: each module's action and whether it
should ask for a new one, the arbiter's action, the exploration level,
and at the gate the admission probability and tactical quality. On
seed 11 d1 answered at all 44 ticks (134 calls, a median round trip of
0.46 s, about a minute of wall time); the pick was d1's own first choice
on 43 of the 44, d1's top action differed from the module's first choice
after the mix on 43 of 220 module answers, and the gate's d1 stage turned away both proposals
(admission probability 0.38, under 0.40 with tactical quality under
0.85, and 0.15, under the 0.20 floor). The episode died after 44
decisions with 4 kills and reward 760, where the heuristics alone died
after 55 with reward 589.

Where a recording has d1's answers, the app shows them: the overview's
d1-ultra box carries the arbiter's answer for the tick in a dotted ring;
each module column names d1's top action, its probability and the
weight it was mixed in at (0.75, or 0.25 when the module's own two best
utilities are 0.45 apart), and every bar splits into the module's own
softmax and d1's share; the arbiter card lists d1's answer and the
0.3 × p bonus each action got; the exploration gauge shows the
controller's pressure pulled halfway to d1's level; the admission gate
shows d1's probability against the 0.40 and 0.20 thresholds; the
hierarchy's d1-ultra card says the same in words; and the timeline marks
a macro the gate rejected.

**GitHub Pages.** `.github/workflows/pages.yml` builds `web/` and
publishes `web/dist` to <https://danielriosgarza.github.io/system1_doom/>
on every push to main (or by hand from the Actions tab); the build's
relative base (`./`) makes it work under `/system1_doom/`. The repository
needs Settings → Pages → Build and deployment → Source: GitHub Actions.
Live mode is not on Pages: a static site cannot stream, and without
`live/status.json` the app is the recordings only.

**The reference drawer** opens over any screen from the Reference button
in the top bar, or the keys g, i and ?. Its four
tabs are the glossary (the terms of §18 and the words the app's own copy
leans on, each with its meaning, this tick's value where there is one,
links to the panels that show it, and its place in the code; every
explanation links its glossary words, once each), the seven principles
of the recorded architecture with where the app shows each, this recording (from `episode.json`
and the index: which brains were on, how it was played, the checkpoint,
the result, the files, the `python -m system1_doom.export` command
that made it, and the `python -m system1_doom.serve` command that
played the same game live, both in that architecture's flags), and the keyboard (1 to 6 switch screens, t
starts the tour, f toggles the depth). It is a modal dialog: focus stays inside
until Esc or a click outside closes it, and it is not in the URL hash.

**Live mode.** `python -m system1_doom.serve` plays episodes with the
same bridge, controller and configuration as `export` (`record_bundle`
is split into the build, the episode and the finish that both use), every
decision made by d1-ultra, and writes each episode as a schema-2 bundle in
`live/live-<k>`, with seeds `seed, seed+1, …`. The controller is built
once, so a macro admitted in one live episode stays in the configuration
for the next, and so do System 2's state and every change it made; `use_log_dir` points the logs, history and frames at each
episode's folder in turn. One local server (127.0.0.1:8765 by default)
answers on one origin: the built app, the shipped recordings, the live
episodes (the one in progress from memory, so a reader never sees a
half-written line; finished ones from disk), `live/status.json` (what is
playing, the finished live episodes, the settings including `decider`
and `networks`, and `schema_version` 2) and `live/events`, a stream of
server-sent events: `hello` on connect; `start` with the opening
`episode.json`; `tick` with each schema-2 trace as it is decided, its
frame already on disk; `proposals` with the whole list, and the action
catalog, whenever they change; `reflection` with each System 2 record
as it is written; `end` with the final meta and its index line;
`stopped` when play stops. Publishing a tick is a queue put per
viewer, a viewer whose queue fills is dropped, and the pacing (`--pace`,
0.23 s per tick by default, eight game frames) is a wait after a tick,
never inside one; a tick itself takes as long as its d1-ultra calls (about
0.8 s measured, §15). The current app asks for `live/status.json` at
start but reads schema version 1 only, so it does not render these
ticks until the third pull request; the stream, the status and the
bundles are already version 2. A slow-path proposal still in flight when
an episode ends is waited for (at most the Codex timeout), so it is
logged in the episode that asked; System 2's work at an episode's end is
waited for too (at most 120 s), so its records land in that episode's
bundle, and a change it queues takes effect in the next episode.
Ctrl+C finishes the current episode's files with `finished` false. A finished live episode is an ordinary
bundle: `export --check live/live-1` passes.

### 8.16 System 2 — `system2.py`, `reflectors.py`, `history_channels.py`, `history_test.py`, `reflection.py`

System 2 (the design, §8–9) changes the configuration while the agent
plays: what each sense and the central see, the admitted macros, the
active strategy and the exploration level. It reads System 1's history,
and every choice it makes is a d1-ultra instance: a reflector proposes a
change, System 2's central chooses one change or none, and the trial
judge keeps or reverts it. The code renders the history as evidence,
filters the finite set of changes by the bounds, runs the history test,
applies and reverts; nothing in it ranks or chooses a change, and nothing
stands in for a missed answer. `--no-system2` switches it off (§11).

**Thread and cadence.** `System2(host, seed, state_path)` runs on its own
daemon thread and calls d1-ultra through the controller's `slow_client`,
a pool of 2 calls (`system2_pool`) it shares with the admit instance, so
it never takes a call from a tick and a tick never waits for it. The
controller tells it about every tick once the history keeps it
(`on_tick`), every configuration that takes effect
(`on_configuration_applied`), every slow-path proposal (`on_proposal`)
and every episode end (`on_episode_end`). A **cycle** starts when 20 new
decisions have been made since the last one (`system2_cadence`), or when
an episode has ended with at least one new decision, and only while no
trial is in flight; a change queued, a macro asked for and a revert
waiting count as in flight. One cycle runs at a time, and the change it
makes takes effect at the next tick boundary (`request_configuration`),
never inside a tick.

**Evidence: the history channels** (`history_channels.py`). One
`HistoryInputs` is built per cycle from the history ring, the
configuration, the strategy archive and System 2's own record, and every
channel renders over three windows at once: the last 20 decisions, the
last 100, and the last 3 episodes (fewer while the history holds fewer),
so a short-lived problem and a long trend both have a view.

| Channel | What it renders |
|---|---|
| `h_outcomes` | per window: decisions, reward, kills, deaths, damage taken, stalls, missed ticks |
| `h_sense:<name>` | per window: spoke, followed, paid off, overruled, calibration, misses; the scope, and the channels it could add and drop |
| `h_central` | per window: followed the strongest message, picks that paid off, ties, misses; the scope, and what it could add and drop |
| `h_actions` | per window: each action's count and mean return; actions never executed; admitted macros and their record |
| `h_strategy` | the archive, and per window the decisions under each strategy with their mean return |
| `h_exploration` | the level; per window: the share of less-tried actions taken, drawn picks, the progress trend |
| `h_config` | the configuration version, the change log, the trial in flight, cooling per instance |
| `h_tests` | recent history tests and trial verdicts (rendered and tested; no instance in the design's tables has it in scope) |
| `messages` | System 2's central only: the reflectors' proposals this cycle |

“Paid off” means the decision's n-step return (n = 8, γ = 0.9) was
positive, computed per episode over the stored ticks, as in the relevance
ledger (§8.8). Rendering is deterministic, each channel under its
`[name]` header in a fixed order, and lists follow the menu's, the
archive's or the configuration's own order: nothing is sorted by a score.

**The nine reflectors** (`reflectors.py`) are instances like the senses:
one call each on System 2's pool, with three questions — `speak` (noul:
“Must the slow system's central hear a proposal from you now?”),
`change` (a choice over the changes it may propose) and `reason` (a
choice over its own short vocabulary).

| Reflector | Scope | `change` criteria | `reason` criteria |
|---|---|---|---|
| survival, combat, navigation, resource and goal auditors | `h_sense:<name>`, `h_outcomes` | `widen:<name>:<channel>` per channel it could add, `narrow:<name>:<channel>` per channel it could drop, `keep` | missing_evidence, needless_evidence, poor_payoff, doing_well, too_little_data |
| central auditor | `h_central`, `h_outcomes` | `widen:central:<channel>`, `narrow:central:<channel>`, `keep` | as the sense auditors |
| menu reflector | `h_actions`, `h_outcomes` | `macro:<sense>` (a new macro for that sense's problem), `retire:<macro>` per admitted macro, `keep` | no_fitting_action, macro_failing, macro_unused, menu_serves, too_little_data |
| strategy reflector | `h_strategy`, `h_outcomes` | `strategy:<id>` per archived strategy that is not active, `keep` | strategy_failing, better_strategy_archived, strategy_working, too_little_data |
| exploration reflector | `h_exploration`, `h_outcomes` | `level:exploit`, `level:explore` | stuck_or_repeating, progress_stalled, progress_steady, too_little_data |

Before the calls, the bounds take changes off each menu (`blocked_by`;
each removal is logged with its bound): a trial in flight, cooling (of
the instance, or of System 2 as a whole), a scope already at 7 channels,
`menu` (never narrowed), a channel a sense may not have, a built-in
action (never retired), a strategy not in the archive, `macro:<sense>`
while the slow path is off or busy, and any change whose configuration
would not validate. A reflector the bounds leave without a change is not
called (logged as skipped). A reflector speaks at `yes_at` (0.5), d1's
own yes; one that speaks for a change sends a proposal (reflector,
change, reason, strength). A silent or missed reflector, or one that
chose `keep` (or the level already set), sends nothing.

**System 2's central.** No proposal means no further call
(`no_proposal`). Otherwise it is one call over `messages`, `h_config`
and `h_outcomes`, with one question, `configure`: “Choose the one
configuration change to make now, or none.” Its criteria are the
proposed changes the bounds still allow, in reflector order, then
`none`. A tie goes to the first option and is logged (`tie`, `tied`); a
missed central means no change this cycle (`central_missed`). What
follows depends on the choice:

| Choice | What happens |
|---|---|
| `widen:…`, `narrow:…` | the history test; the change is queued only when it passes (`queued`), else `test_failed`, or `test_waiting` when there are too few stored ticks or calls left |
| `macro:<sense>` | the slow path is asked (`request_expansion`) with a description built from the reflector's reason and that sense's concern (`macro_requested`); the admit instance decides, and an admitted macro joins the configuration at a tick boundary as the trial. A rejected proposal ends the request; one not answered within 60 decisions is abandoned |
| `retire:<macro>`, `strategy:<id>`, `level:<level>` | queued (`queued`) |
| `none` | nothing (`none_chosen`) |

**The history test** (`history_test.py`, the design's §9) stands between
a scope change and play. From the last 3 episodes the history holds, it
takes the ticks the instance answered under its current scope (ticks
whose central missed are left out); with fewer than 24 there is no test
and the change waits. It draws 24 with a seeded `random.Random`,
stratified by the decision's n-step return: 8 from the bottom quarter
(bad), 8 from the top quarter (good) and 8 from the rest, at most 4 from
any one context signature. A stratum the window cannot fill hands its
shortfall to the rest, and the cap is relaxed only for a stratum it
would leave short; both are logged. Each sampled tick is re-rendered
under the new scope from its stored `EvidenceInputs`, with the screen
the instance saw when `frame` is in the new scope (the ring keeps each
tick's frame, §8.8), and the instance is asked again: 24 calls, counted
as `history_test:<instance>`. The old scope's answers are the stored
ones.

| Instance | Bad ticks | Good ticks | Rest |
|---|---|---|---|
| a sense | alarm recall: spoke for an action other than the executed one | good agreement: silent, or recommended the executed action | quiet: silent |
| the central | disagreement with the executed action | agreement with the executed action | — |

The composite is the mean of these quality metrics. The test passes when
the new composite is at least 0.05 above the old and no quality metric
is worse by more than 0.10. A missed re-run counts as silent (for the
central, as no action) and is counted. The old scope is re-asked on 4 of
the 24 ticks, and the share whose answer matches the stored one is the
noise estimate; the mean evidence length and latency are reported as
cost. The labels come from what the agent did, so the test measures
agreement with good outcomes and alarms before bad ones, not
counterfactual value. The `ReflectionTrace` keeps its whole table.

**Trials.** Every change that takes effect is a trial, one at a time
(`trials_in_flight`). It is observed for 60 decisions
(`trial_decisions`, across episodes if need be); then the trial judge,
one call whose evidence is the trial table, answers `verdict`: “Keep
this configuration change, or revert it?” (`keep` or `revert`). The
table compares up to 60 decisions before the change with those during
it: reward and damage per decision, kills, deaths, missed ticks, and the
paid-off rate of the changed instance's followed messages (of all
executed decisions for a menu, strategy or level change), with the
history test's prediction.

* **Safety revert.** For a scope change, when the changed instance's
  paid-off rate falls by more than 0.15 (`safety_drop`) on at least 10
  followed messages during the trial (`safety_followed`), counting only
  returns whose 8 rewards are all held (or whose episode ended), the
  change is reverted without asking; the verdict records
  `safety_revert`.
* **Revert.** A revert restores the previous configuration exactly, with
  the version bumped (version 2 reverted becomes version 3, equal to
  version 1 in everything else): a reverted macro is retired, and a
  reverted retire re-admits the macro. It waits for the next tick
  boundary like any change.
* **A missed judge** extends the trial by 20 decisions
  (`judge_extension`), and the judge is asked again then. At its third
  miss (`judge_extensions_max`) the trial ends as `revert` with no
  verdict: a `TrialVerdictTrace` like the others, its table included,
  with `by: "no verdict"`, and a `no_verdict` note saying the judge never
  answered. Nothing stands in for a missed verdict, and the configuration
  before the change is the honest state to return to; cooling starts as
  after any verdict.
* **Cooling.** From the verdict, the changed instance rests 60 decisions
  (`cooling_decisions`): no change to it is offered. After a menu,
  strategy or level change, System 2 as a whole rests.

**Calls.** A cycle makes at most 9 reflector calls, 1 central call and,
for a scope change, 28 history-test calls (24 + 4 noise): 38, inside the
bound of 40 per cycle (`system2_calls_per_cycle`), which is asserted. A
history test that the calls left in the cycle cannot cover waits. The
judge is one call per attempt.

**Records** (`reflection.py`; `reflections.jsonl` in the log folder).
Each cycle writes a `ReflectionTrace` (`record: "cycle"`): the trigger,
the decision count, the configuration version, the windows, each
reflector's full `InstanceResult` (its verbatim evidence and answers),
the changes each was offered and the bounds that removed the rest, the
skipped reflectors, the messages, the central's result, criteria,
choice and tie, the outcome, the history test's whole table, the change
applied with its configuration diff, the calls and the usage. A verdict
is a `TrialVerdictTrace` (`record: "verdict"`) referring to the cycle
that made the change, with the trial record: when it started and was
judged, every judge attempt, the before-and-during table, the verdict,
`by` (the trial judge, the safety bound, or no verdict) and
`safety_revert`. Short `System2Note`s (`record: "note"`) mark what
happens in between: `trial_started`, `judge_missed`, `no_verdict`, `macro_admitted`,
`macro_rejected`, `macro_abandoned`, `revert_applied`, `external_change`
(a configuration System 2 did not make), `restored`, `fresh_start` and
`error`. `load_reflections` reads a file; `summarize` gives the counts
`episode.json` carries.

**Persistence.** The configuration is saved to
`runs/<scenario>/configuration.json` at every change that takes effect
and at every episode end, and every entry point that plays starts from
that file when it exists, so System 2's work carries across runs and a
recording can start from a later configuration version without a flag.
`--configuration PATH` names another file; `--fresh-configuration`
starts from the design's version 1 and forgets the saved configuration
and System 2's state (`train --fresh` implies it). Each run says which in
one line on stderr: `configuration: runs/basic/configuration.json
(version 2)`, or `configuration: the design's version 1`. The saved
configuration already holds every macro admitted and retired, so the run
folder's `macros.json` is merged only into a configuration that is not
the run folder's own. A multi-episode `export` plays each episode with
its own controller: the first starts as asked, each next one from the
configuration the one before saved. System 2's own state (its decision count, the last cycle, cooling, the
change log, recent tests and verdicts, the trial in flight, a pending
change) is saved atomically to `runs/<scenario>/system2.json` at every
cycle, verdict, note, configuration change and episode end, and when
play stops. It is restored at the first tick only when the session
starts from the configuration it was saved with (a fingerprint of that
configuration), which the default start ensures; a flag that changes the
configuration before play (a different `--call-budget`, `--explore` or
`--exploit`) changes the fingerprint, and System 2 starts fresh, with a
note, as it does from any other configuration. A revert
saved before it took effect is queued again on restore; any other
pending change is dropped, with a note.

**The controller's side** is the `System2Host` protocol (§8.13). An
episode's counts land in the `run_episode` result and in `episode.json`
as `system2`. The calls are in the per-instance counters and, because a
cycle runs while the agent plays, in the cost of the episode during
which they were made.

---

## 9. The slow path end-to-end

```text
request_expansion(source, description)          [System 2's menu reflector, tests, embedders]
  → ExpansionRequest enqueued if the worker is idle (single flight)
  → background thread: codex exec (20 s cap) or fallback template
  → parse → legality → sandbox (bounds) → admit instance (one d1-ultra noul,
    on the slow path's own pool of 2)
  → AdmissionDecisionResult drained at the start of a later tick, ProposalTrace logged
  → if admitted: a configuration with the macro is queued
  → next tick boundary: the configuration version bumps, the macro joins the
    vocabulary and the archive, appears on the menu when its preconditions
    hold, the value networks encode it at once, and its rewards flow into
    proposals.jsonl as follow-up records
```

Invariants: no tick waits for any of this; at most one request is in
flight; nothing is admitted without passing the same `ActionSpec`
validator as built-in actions and the admit instance's yes; the
configuration changes only at a tick boundary; disabling the slow path
(`enable_slow_llm=False`) removes the whole column with no other change.
In play only System 2 calls `request_expansion`, when its central
chooses a `macro:<sense>` change; the admitted macro is then System 2's
trial, and a reverted one is retired (§8.16).

---

## 10. The learning loop end-to-end

```text
train.py / cli.py --learn          (every decision made by d1-ultra)
  per episode:  controller.run_episode()
                  └─ every executed tick: Learner.record_step(state_vec,
                       action_vec, result, action_id, context)
                  └─ episode end: Learner.end_episode()
                       8-step γ=0.9 returns → RunningStats → ReplayBuffer
                       tried counts (context|action, context) += 1
                  └─ episode end: relevance ledger updated and saved
                learn_from_episode(): Learner.train() — 200 Adam steps,
                  batch 256, each value net on its own reward's returns
                metrics row appended (reward, kills, finished reason,
                  missed ticks, cost, d1 calls, losses …); checkpoint.pt +
                  replay.npz + macros.json saved; if rolling-20 reward beats
                  best_score → checkpoint copied to best.pt
                learning_curves.png redrawn every --chart-every episodes
  per tick (play): Learner.predict_returns(state, menu) and
                  tried_counts(context, menu) → the `values` channel
```

Key behaviours: resume is automatic (`checkpoint.pt` + `replay.npz` +
episode numbering continue); `cli.py` shows `best.pt`'s predictions by
preference while `--learn` continues from `checkpoint.pt`; there is no
exploration schedule — the exploration level is part of the
configuration (`--explore` plays the whole session at the explore level,
where the central's answer is drawn from its own distribution);
`--evaluate N` replays identical seeds (`EVAL_SEED_BASE = 10_000 + i`)
with no networks, the latest and the best as evidence, and writes
`evaluation.json`. Training is now a d1-ultra cost: about 6 calls per
decision.

---

## 11. Entry points & CLI reference

All four entry points that play (`cli`, `train`, `export`, `serve`) exit
`2` with a message when `LIQUID_API_KEY` is missing, before touching the
game; each takes `--call-budget SEC` (per-call budget, default 5),
`--explore`/`--exploit` (the starting exploration level, default
exploit), `--seed` (the game's seed and System 1's draw seed),
`--configuration PATH`, `--fresh-configuration` and `--no-system2`.
Each starts from the run folder's `configuration.json` when it exists
(System 2's `system2.json` then restores), from `--configuration PATH`
when given, or from the design's version 1 with `--fresh-configuration`
(which forgets the saved configuration and System 2's state), and prints
which on stderr; a file that does not load stops the run with exit code
2 and that remedy. System 2 is on by default; with `--no-system2` the
configuration stays as it starts. `train --evaluate` always plays with
System 2 off, under the configuration a run would start from, and saves
nothing, so the brains it compares face one configuration.

### `python -m system1_doom.cli` — play / watch

| Flag | Default | Meaning |
|---|---|---|
| `--scenario` | `deadly_corridor.cfg` | ViZDoom scenario cfg (name or path) |
| `--episodes N` | 0 | Play N complete episodes (cap `--ticks` each, default 500) |
| `--ticks N` | 15 (500 with `--episodes`) | Decision cap: of the one episode played without `--episodes`, or per episode with it |
| `--call-budget SEC` | 5 | Per-call budget for each d1-ultra call |
| `--explore` / `--exploit` | exploit | Starting exploration level |
| `--seed` | — | ViZDoom seed and System 1's draw seed |
| `--configuration PATH` | the run folder's `configuration.json` if it exists, else the design's version 1 | Another `configuration.json` to start from (§8.4) |
| `--fresh-configuration` | — | Start from the design's version 1, forgetting the run folder's saved configuration and System 2 state |
| `--disable-slow-llm` | — | No slow path |
| `--no-system2` | — | Switch System 2 off: the configuration stays as it starts |
| `--visible` | — | 640×480 ViZDoom window + the six-instance side window (unless `--no-dashboard`); default step delay becomes 120 ms |
| `--step-delay-ms` | 0 (120 if visible) | Pause after each game step |
| `--save-gif/--save-mp4` | — | Record HUD frames and export on exit |
| `--log-dir` | `logs` | Where `ticks.jsonl`, `history.jsonl`, `proposals.jsonl` and `frames/` go |
| `--run-dir` | `runs/<scenario-stem>` | Run folder: trained networks, macros, the relevance ledger |
| `--no-learned` | — | Load no value networks (the `values` channel says so) |
| `--learn` | — | Keep training the value networks between episodes; requires torch |

Output is a JSON summary on stdout: `decider`, the configuration
version, level and call budget, per-episode results (cleared, finished
reason, ticks, reward, health, armor, kills, cost, misses, mean tick
time, actions, the configuration version it ended at, and `system2`:
the counts of System 2's records written while it was played, so an
episode's end-of-episode cycle is counted with the next episode), each
instance's counters (calls, answered, misses, retries, mean latency,
tokens, cost; System 2's instances and `history_test:<instance>`
included) and the paths, with `reflections_log` and `configuration`.
With System 2 on, `cli` waits for its last cycle (at most 120 s) before
it prints. Exit code 1 when
an episode ended as `connection_lost`.

### `python -m system1_doom.train` — train / evaluate

| Flag | Default | Meaning |
|---|---|---|
| `--scenario` | `deadly_corridor.cfg` | Scenario to train on |
| `--episodes` | 50 | Episodes this session (numbering resumes) |
| `--max-ticks` | 500 | Decision cap per episode |
| `--run-dir` | `runs/<scenario-stem>` | Run folder |
| `--fresh` | — | Delete the run folder's models, ledger, history, configuration and System 2 state first (so it implies `--fresh-configuration`) |
| `--train-steps` | 200 | Gradient steps after each episode |
| `--trust-count` | 25 | Tries at which the reported network share reaches 50% |
| `--chart-every` | 5 | Redraw `learning_curves.png` every N episodes |
| `--seed` | — | ViZDoom, network and System 1 draw seed |
| `--call-budget`, `--explore`/`--exploit` | 5 / exploit | As above |
| `--codex` | off | Let the slow worker call the Codex CLI |
| `--no-system2` | — | Switch System 2 off |
| `--configuration PATH`, `--fresh-configuration` | the run folder's, else the design's | As `cli` |
| `--evaluate N` | 0 | Skip training; play N identical seeded episodes with no, the latest and the best networks as evidence and write `evaluation.json` |

One line per episode is printed (reward, kills, health, outcome, network
share, missed ticks, cost, loss, ticks, seconds), then a session summary.
Exit code 2 without the key, without torch/matplotlib (with the install
hint), or on a checkpoint mismatch (with a `--fresh` remedy).

### `python -m system1_doom.export` — record episode bundles

| Flag | Default | Meaning |
|---|---|---|
| `--scenario` | `deadly_corridor.cfg` | ViZDoom scenario cfg |
| `--episodes N` | 1 | Episodes to record, with seeds `seed, seed+1, …` |
| `--seed` | 7 | Seed of the first episode (also System 1's draw seed) |
| `--networks` | `none` | Value networks for the `values` channel: `none`, `best` (`best.pt`) or `latest` (`checkpoint.pt`) from the run folder |
| `--run-dir` | `runs/<scenario-stem>` | Run folder with trained networks, macros, metrics and the ledger |
| `--out` | `bundles/<stem>-<networks>-<seed>` | Bundle folder (a parent folder when `--episodes` > 1) |
| `--name`, `--title` | folder name / generated | How the app lists the episode |
| `--max-ticks` | 500 | Decision cap per episode |
| `--call-budget`, `--explore`/`--exploit` | 5 / exploit | As above |
| `--codex` | off | Let the slow path call the Codex CLI; otherwise it runs on templates |
| `--no-slow-path` | — | Switch the slow path off |
| `--no-system2` | — | Switch System 2 off; `reflections.jsonl` is then empty |
| `--configuration PATH`, `--fresh-configuration` | the run folder's, else the design's | As `cli`, for the first episode; each next one starts from the configuration the one before saved |
| `--check BUNDLE` | — | Validate a bundle and exit (exit code 1 on problems); no key needed |
| `--index DIR` | — | Write `DIR/index.json` listing its shippable bundles and exit; no key needed |
| `--schema OUT.json` | — | Write the bundle JSON Schema and exit; no key needed |

Recording keeps `record_experience` off, so a recording only reads the
networks; it does update the run folder's relevance ledger, which is
copied into the bundle, and, with System 2 on, its configuration and
System 2 state. Exit code 1 when an episode ended as
`connection_lost` (the bundle is written, and reported as not shippable).

```bash
python -m system1_doom.export --scenario deadly_corridor.cfg --seed 9 --networks best \
    --out bundles/deadly_corridor-best-9
python -m system1_doom.export --check bundles/deadly_corridor-best-9
python -m system1_doom.export --index bundles
```

### `python -m system1_doom.serve` — play live and stream ticks

| Flag | Default | Meaning |
|---|---|---|
| `--scenario`, `--seed`, `--networks`, `--run-dir`, `--max-ticks`, `--call-budget`, `--explore`/`--exploit`, `--codex`, `--no-slow-path`, `--no-system2`, `--configuration`, `--fresh-configuration` | as `export` | How to play; episode k gets seed `seed + k - 1` |
| `--episodes N` | until Ctrl+C | Episodes to play; afterwards the server keeps serving until Ctrl+C |
| `--pace SEC` | 0.23 | Least wall time per tick (8 game frames at 35 fps); 0 plays flat out |
| `--rest SEC` | 3 | Pause between episodes |
| `--host` | `127.0.0.1` | Address to listen on; any other address exposes the stream with no authentication |
| `--port` | 8765 | Port to listen on |
| `--out DIR` | `live` | Folder for the live episodes; earlier `live-<k>` folders are cleared at start, and anything else there stops it |
| `--app DIR` | `web/dist` | The built app (`cd web && npm run build`); without it the data is still served, for `npm run dev`, which passes `/live` and `/episodes/live-*` through |
| `--recordings DIR` | `web/public/episodes` | The shipped recordings and their index |

```bash
python -m system1_doom.serve --scenario deadly_corridor.cfg --networks best   # http://127.0.0.1:8765/
python -m system1_doom.export --check live/live-1                            # a finished live episode
```

There is no `python -m system1_doom` `__main__`; use the four module
entry points above (or embed `DoomDecisionController` directly — §17).

---

## 12. Configuration reference

### `ControllerConfig` (`controller.py`, frozen) — how a controller plays

| Field | Default | Effect |
|---|---|---|
| `call_budget_sec` | `None` | Overrides the configuration's per-call budget (`--call-budget`) |
| `seed` | `0` | Seeds System 1's generator for draws under the explore level |
| `configuration` | `None` | The initial `Configuration` (else `configuration_path`, else the design's) |
| `configuration_path` | `None` | A `configuration.json` to start from (the entry points pass the run folder's when it exists, `train.starting_configuration`) |
| `exploration_level` | `None` | Overrides the initial level |
| `enable_slow_llm` | `True` | Master slow-path switch |
| `use_codex_cli` | `True` | Use `codex exec` when available; else fallback templates |
| `log_dir` | `logs` | Traces, history and frames |
| `relevance_path` | `None` | The ledger to restore and save (`runs/<scenario>/relevance.json` from the entry points) |
| `enable_system2` | `False` | Run System 2 beside play (the entry points turn it on unless `--no-system2`) |
| `configuration_out` | `None` | Where the configuration in play is saved at every change that takes effect and at every episode end (`runs/<scenario>/configuration.json` from the entry points) |
| `system2_state_path` | `None` | System 2's state to restore and save (`runs/<scenario>/system2.json` from the entry points) |
| `record_experience` | `False` | Record executed decisions for the value networks (training, `--learn`) |
| `record_frames` | `False` | Capture HUD frames for GIF/MP4 export |
| `show_dashboard` | `False` | Live Tk side window (set by `--visible`) |

### `Configuration` and `Bounds` (`configuration.py`) — what each instance sees

See §8.4 for every field and bound. A configuration file is the
`Configuration` model as JSON; `default_configuration().save(path)`
writes the design's version 1 to start from.

### `LearnerConfig` (`learning.py`, frozen)

`gamma=0.9`, `n_step=8`, `hidden=64`, `lr=1e-3`, `batch_size=256`,
`train_steps=200`, `replay_capacity=100_000`, `trust_count=25.0`,
`seed=0`. (`hidden` is frozen into checkpoints.)

### `ProjectionLimits` (`simulator.py`)

`max_candidate_count=16`, `max_simulation_depth=4`,
`max_wall_clock_budget_sec=0.015`, `max_branching_factor=2` — see §8.3.

### Environment variables & files

`LIQUID_API_KEY` (env or `.env` in CWD/repo root) is required to play.
Presence of the `codex` binary enables real slow-path generation.
Everything else is CLI, `ControllerConfig` or configuration-file driven.

---

## 13. Files on disk: logs, runs, checkpoints

**`logs/` (or `--log-dir`)** — `ticks.jsonl` (one schema-2 `TickTrace`
per tick), `history.jsonl` (one `TickRecord` per tick), `proposals.jsonl`
(one `ProposalTrace` per proposal + follow-up performance records),
`reflections.jsonl` (System 2's cycles, verdicts and notes, §8.16), and
`frames/<tick>.jpg` (the screen d1-ultra saw; a folder holding several
episodes keeps the latest episode's screens). These are append-only and
are the audit trail: any executed action can be traced to the central's
answer, the messages it heard and the evidence each instance saw, and
any configuration change to the cycle, the proposals and the evidence
that led to it.

**`runs/<scenario-stem>/`** (run folder, `RunStore` in `train.py`):

| File | Contents |
|---|---|
| `checkpoint.pt` | Latest learner: value nets, optimiser, running stats, tried counts, best score (format 1, §8.9) |
| `best.pt` | Copy of the checkpoint with the best rolling-20 mean episode reward (≥ 5 episodes required) |
| `replay.npz` | Replay buffer arrays (`states, actions, returns`), chronological |
| `macros.json` | Admitted macros as `ActionSpec` JSON; **re-validated on load** |
| `relevance.json` | The relevance ledger, restored at start and saved after every episode played with this run folder (play, training, recording) |
| `configuration.json` | The configuration in play, saved at every change that takes effect and at every episode end; every entry point that plays starts from it when it exists (`--fresh-configuration` starts from the design's version 1 instead) |
| `system2.json` | System 2's state: decision count, cooling, change log, recent tests and verdicts, the trial in flight; restored when a session starts from the configuration it was saved with, as it does by default |
| `metrics.jsonl` | One row per training episode: reward, kills, health, armor, ticks, cleared/died, finished reason, missed ticks, cost, d1 calls, transitions, replay size, network share, per-network losses, macros, timings |
| `learning_curves.png` | The chart of §8.14 |
| `evaluation.json` | Latest `--evaluate` report (no/latest/best networks over identical seeds) |
| `ticks.jsonl`, `history.jsonl`, `proposals.jsonl`, `reflections.jsonl`, `frames/` | The run's own logs (log_dir is the run folder during training); `eval/` holds evaluation logs |

The repo ships example runs for `deadly_corridor` (300 episodes) and
`defend_the_center` (200 episodes), trained under the old architecture;
their checkpoints load (the gate keys are ignored) and serve the
`values` channel.

**`bundles/<stem>-<networks>-<seed>/`** — episode bundles written by
`python -m system1_doom.export` (§8.15); gitignored.

---

## 14. Misses, budgets & failure modes

| Event | Behaviour | Recorded as |
|---|---|---|
| No `LIQUID_API_KEY` | `cli`, `train`, `export`, `serve` exit 2 with a message before the game starts; the controller raises `MissingAPIKey` | — |
| A sense exceeds the call budget, errors, names an off-menu action, or returns malformed probabilities | Silent this tick; the central hears the others | `missed` on that sense, `miss_reason`, the raw answer |
| The central does the same | No keys for the decision's 8 frames (`execute_idle`: 4 empty steps) | pick `missed`, `missed: true`, `executed_action: null`, actions `missed` |
| Three consecutive central misses | The episode ends | `finished_reason: connection_lost`; `export` exits 1, `--check` reports it, `--index` leaves it out |
| HTTP 429 | Wait per `Retry-After` while the budget lasts, then retry | a retry; `http_429_exhausted` if the wait would exceed the budget |
| No `codex` binary / Codex times out (20 s) | Deterministic fallback template instead; admission still applies | proposal `source` |
| Illegal proposal | Rejected with a reason at parse, legality or sandbox, before any instance sees it | `proposals.jsonl` |
| The admit instance misses | Rejected: a miss is not a yes | stage `d1` failed |
| A reflector misses (timeout, error, a change outside its criteria, malformed probabilities) | It sends nothing this cycle; the other reflectors still count | `missed` on that reflector in the `ReflectionTrace` |
| System 2's central misses | No change this cycle | outcome `central_missed` |
| System 2's central ties | The first option in criteria order | `tie`, `tied` |
| A history-test re-run misses | Counted as silent (for the central, as no action) and counted | `new_missed`, `noise_missed` in the test |
| Fewer than 24 stored ticks for the history test, or too few calls left in the cycle | No test: the change waits, and a later cycle may propose it again | outcome `test_waiting` |
| The trial judge misses | The trial is extended by 20 decisions and the judge asked again | note `judge_missed`; `extensions` on the trial |
| The trial judge misses a third time (`judge_extensions_max`) | The trial ends as revert with no verdict: the configuration before the change is restored at the next tick boundary, and cooling starts | verdict `by: "no verdict"` with its table; note `no_verdict` |
| The run folder's `configuration.json`, or `--configuration PATH`, does not load | The entry point exits 2 before the game starts, naming `--fresh-configuration` | — |
| The slow path cannot take System 2's macro request (off or busy) | No change this cycle | outcome `macro_not_enqueued` |
| System 2's macro request unanswered for 60 decisions | Abandoned; cycles resume | note `macro_abandoned` |
| The session ends with a revert queued but not yet in play | Saved in `system2.json` and queued again when the next session starts from the same configuration | note `restored` |
| An exception in a System 2 job | Recorded; play goes on, and System 2 tries again at the next tick | note `error` |
| No PyTorch | Play goes on; the `values` channel says no networks are loaded; `train` and `cli --learn` exit 2 | — |
| Checkpoint mismatch (format/feature sizes/networks) | `train` and `cli --learn` exit 2 advising `--fresh`; plain `cli` plays without networks | — |
| Dashboard/Tk failure | Caught once, dashboard disabled for the session, play continues | — |
| Episode finished mid-burst | The motor burst stops early, and the bridge returns a well-formed result | — |
| No action passes preconditions | The vocabulary falls back to `(turn_left, turn_right, move_forward)`, so the menu is never empty | — |

Every miss is counted per instance and reason in the client, summed per
episode into `misses`, and kept in the trace with the raw answer. There
is no budget-mode degradation, no cached reactive action and no
local fallback: a tick waits for d1-ultra or records that it did not
answer.

---

## 15. Measured results

**Live, d1-ultra deciding** (2026-10-25, `basic.cfg`, seed 3, slow path
off, no value networks, default 5 s budget):

| Run | Decisions | Result | Mean tick | Calls | Misses | Input tokens | Cost |
|---|---:|---|---:|---:|---:|---:|---:|
| `--ticks 8` | 8 | not cleared in 8 decisions (reward −84) | 816 ms | 48 | 0 | 34,370 | $0.00144 |
| `--episodes 2`, episode 1 | 17 | cleared, 1 kill (reward −69) | 836 ms | 102 | 0 | 73,330 | $0.00308 |
| `--episodes 2`, episode 2 | 26 | cleared, 1 kill (reward −177) | 796 ms | 156 | 0 | 116,158 | $0.00488 |

A tick is about 0.8 s: the five senses in parallel take 0.40–0.65 s (the
slowest sense sets it), the central 0.25–0.30 s, everything else about
15 ms. Per-call mean latency was 360–400 ms for the senses and 255–270 ms
for the central; there were no retries. The response's usage reports
input tokens only (output 0), about 700 per call; a decision costs about
$0.00018, so a 50-decision episode costs about a cent. On these runs
d1-ultra mostly chose `weave_fire`, with the combat sense speaking every
tick and the goal sense often.

**System 2, live** (2026-10-25, `cli --scenario basic.cfg --episodes 2
--ticks 40 --seed 3 --disable-slow-llm`, System 2 on, otherwise as
above):

| Episode | Decisions | Result | Mean tick | Calls (System 1 + System 2) | Cost |
|---|---:|---|---:|---:|---:|
| 1 | 15 | cleared, 1 kill (reward −48) | 872 ms | 90 + 0 | $0.00271 |
| 2 | 24 | cleared, 1 kill (reward −144); ended at configuration version 2 | 771 ms | 144 + 18 | $0.00500 |

System 2's calls run on its own pool while the agent plays, so they are
counted in the episode during which they were made: cycle-1 started at
the end of episode 1 and ran as episode 2 began.

* **cycle-1** (`episode_end`, decision 15, configuration version 1). The
  menu reflector was not called: with the slow path off and no admitted
  macro, the bounds left it no change. The other eight answered in
  205–285 ms. Two spoke for a change: the combat auditor for
  `widen:combat:incoming` (speak 0.59, `missing_evidence`) and the
  exploration reflector for `level:explore` (0.55,
  `stuck_or_repeating`). The goal auditor, the central auditor and the
  strategy reflector spoke above 0.5 but chose `keep`, which sends
  nothing. System 2's central chose `widen:combat:incoming` (0.537,
  against 0.282 for `level:explore` and 0.181 for `none`). The history
  test waited: 15 stored ticks, fewer than 24. 9 calls, 6,818 input
  tokens, $0.000286.
* **cycle-2** (`decisions`, decision 35). Three proposals:
  `widen:combat:incoming` (0.50), `strategy:strat_evasive_survival`
  (0.88, `strategy_failing`) and `level:explore` (0.71). The central
  chose the strategy (0.703; `none` 0.066). Queued, it took effect at the
  tick boundary of decision 39 as version 2 (active strategy
  `strat_tactical_combat` → `strat_evasive_survival`), and its trial
  started, to be observed for 60 decisions against the 38 before it; the
  session ended before the judge was due. 9 calls, $0.000284.
* In all, System 2 made 18 calls with no miss: a mean of 222–370 ms per
  reflector and 264 ms for its central, about 750 input tokens per call,
  $0.00057 in all, under a tenth of the session's cost. A cycle without
  a history test costs about $0.0003.
* **The history test, live.** Run by hand on this session's 39 stored
  ticks for the change cycle-1 chose (`widen:combat:incoming`, seed
  3001): 24 ticks drawn from pools of 9 bad, 9 good and 21 rest; 28
  calls (24 + 4 noise re-asks), 25,813 input tokens, $0.00108, 296 ms
  per answer, about 4 s on the pool of 2. It failed: the composite was
  0.333 under both scopes (alarm recall 0, good agreement 0.875, quiet
  0.125: the combat sense answered alike with `incoming` in view), short
  of the 0.05 margin. The evidence grew from 1,694 to 1,781 characters,
  and the 4 noise re-asks all matched the stored answers. (Run from the
  log folder, where episode 2 had rewritten episode 1's screens, the
  sampled ticks of episode 1 went without theirs; in play the ring keeps
  them.)

**The value networks** were measured under the old architecture
(`docs/superpowers/specs/2026-10-23-learning-controller-design.md`,
`--evaluate 30`, identical seeds): on `deadly_corridor` after 300
episodes, cleared 13% with heuristics only, 37% with the latest
checkpoint and 50% with the best; on `defend_the_center` after 200
episodes, 8.5 → 17.4 kills. Those numbers describe the removed
modules and arbiter steering by the networks; under this design the
networks are evidence, and their effect on d1-ultra's play is measured
with `train --evaluate` (no, latest and best networks on the same seeds).

---

## 16. Testing

```bash
python -m pytest                 # 232 tests, 25 files, from the repo root
python -m pytest -k "not live"   # the 228 that need no key, as CI runs them
```

Every behaviour is exercised without a key through `tests/fake_d1.py`:
`FakeD1` answers from the payload it receives, deterministically, with a
scripted policy (`default_policy`; `shoot_when_aimed`, under which the
combat sense speaks when an enemy is aimed and the central follows the
first message), records every payload so a test can assert exactly what
each instance saw, and can be told to time out, raise, return an action
outside the menu or malformed probabilities at chosen calls. For
System 2 it answers the reflectors, System 2's central and the trial
judge from their payloads too (`default_system2_policy`: the survival
auditor proposes `widen:survival:pickups` when, over the last 100
decisions, the survival sense's followed messages paid off less than
half the time; the central takes the first proposal; the judge keeps),
and `survival_until_pickups` scripts a survival sense that speaks for
the first menu action until it sees `pickups`, so that widen has
something to pass. `tests/system2_fixtures.py` builds synthetic
histories of `TickRecord`s with known rewards that re-render like played
ticks. The four live tests (`@pytest.mark.live`, named `test_live_*`:
one d1-ultra call, one tick with six instances, a history-test re-run on
4 stored ticks, and one System 2 cycle on a short real history) call the
real API and skip without `LIQUID_API_KEY`. Tests use real ViZDoom
headlessly; the suite takes about half a minute without the live tests
and about 45 seconds with them.

| File | Covers |
|---|---|
| `test_evidence.py` | Each channel's golden text on a fixture state; a scope renders only its channels (the survival text has no pickup); the caps; deterministic re-rendering; labels of `projections` and `values` |
| `test_configuration.py` | The design's initial configuration; every validation rule; versions; save and load |
| `test_instance.py` | A sense's one payload: its scope, its questions, the frame only when in scope; speaking at 0.5 with action, reason and strength; a failed call is a miss and nothing stands in; an off-vocabulary reason is malformed; rate limits wait within the budget and count as retries; usage and latency; the central's one choice over the menu; the admit instance's one noul |
| `test_senses.py` | The five from the configuration, each seeing only its scope; spoken senses become messages in sense order; a missed sense is silence and the others still speak; the five run in parallel within the budget; over budget is a timeout miss; the speak line is d1's own yes |
| `test_system1.py` | The central's payload holds only its scope and hears the messages; `top` under exploit, ties to the first in menu order and logged; `drawn` under explore reproduces with the seed and follows d1's distribution; `novelty` added while exploring, only with room; a decision when no sense spoke; a central miss is a `missed` pick; a rate-limited central within budget still answers; usage summed over the six |
| `test_relevance.py` | Ledger counts and calibration from synthetic histories; the n-step return; missed ticks left out; rendering; save and restore |
| `test_history.py` | The ring bound; persistence; re-rendering a stored tick under its own scope reproduces the text seen at the time; each ring record's frame kept in memory and dropped with it |
| `test_history_channels.py` | The three windows as the history holds them, across a long ring; paid off as the per-episode n-step return; each channel's golden text; a scope renders only its channels, in order and deterministically; what a sense could add and drop follows the bounds; an empty history says so |
| `test_reflectors.py` | Nine reflectors, each over its history channel and `h_outcomes`; questions that name the reflector and never say how to weigh; one channel at a time, never `menu`; the menu, strategy and exploration menus; the bounds (cooling, the trial, scope size, built-ins, `menu`); a change bumps the version and the diff says what changed; one call, and a proposal only when it speaks for a change; a change outside the criteria is a miss |
| `test_history_test.py` | The sense and central metrics on labelled ticks; the margin rule on both sides; strata by rank; the seeded stratified sample, the context cap and when it is relaxed; a change that quiets a sense on its unpaid messages passes, one under the margin fails; no test and no call under 24 ticks; the noise estimate; a missed re-run counts as silent; the screen attached when `frame` joins the scope; the central's test; one live re-run on 4 ticks |
| `test_system2.py` | On a synthetic history and on `basic.cfg` with the fake: a cycle every 20 decisions or at an episode end, none during a trial; each reflector sees only its channels and the central its three; the central's criteria are the allowed proposals and `none`; one change per cycle, at a tick boundary; the judge keeps after 60 decisions; a revert restores the previous configuration exactly with the version bumped, then cooling; a revert queued again on restore; a missed judge extends the trial by 20; a judge that never answers ends the trial as revert with no verdict, and one that misses twice and then answers is followed; the safety revert; a missed central changes nothing and a tie goes to the first option; the calls counted and kept under the bound; a macro request through the slow path, and a reverted macro retired; the state saved and restored only onto its configuration; end to end, a widen tested, applied and kept, ending at configuration version 2, in the controller and in served bundles; off unless asked; one live cycle on a short real history |
| `test_d1_client.py` | Request serialisation through an injected transport; typed misses counted per instance; `Retry-After` parsing; the default transport's typed 429; one live call |
| `test_controller_e2e.py` | On `basic.cfg` with the fake: six instances per tick with the payload's state equal to the evidence; a fake that shoots when aimed clears the level; a scripted outage gives missed ticks with idle steps, then `connection_lost`; isolated misses do not end the episode; every motor step follows the action's plan; the value networks learn and appear in `values`; the ledger updates and is restored; a pending configuration applies at the boundary; explore draws reproduce; an admitted macro enters at the next boundary; play needs the key; one live tick with six instances answering |
| `test_architecture.py` | The removed `modules.py`, `arbiter.py` and `exploration.py` are gone and nothing in `src/` or `tests/` imports them; keys are pressed only in `controller.py`, from the pick or the typed miss; only `system1.py` builds a `Pick`, and only it and `history_test.py` (the seeded sample of stored ticks) import `random`; at run time the executed action is the central's answer and a miss idles |
| `test_llm_and_admission.py` | The bounds reject before any call; the admit instance admits at its yes; a missed admit rejects; the admit evidence and its determinism; the background worker |
| `test_archive.py` | The archive holds no decision; the active strategy follows the configuration; a full archive makes room by age, never by score; outcomes update the record shown as evidence |
| `test_learning.py` | n-step returns; per-network rewards; running stats; replay round-trip; each value net learns its own signal; episode credit assignment; checkpoint round-trip, overrides and mismatch; a checkpoint with gate weights loads (synthetic, and the shipped one when present) |
| `test_training.py` | The motor executes an action's own plan; `train` writes the full run folder (with the ledger and history) and resumes; training and evaluation start from the saved configuration (evaluation with System 2 off, saving nothing) and `--fresh` forgets it; admitted macros persist and are re-validated; no exploration schedule; fail fast without the key; the idle burst |
| `test_cli.py` | Fail fast without the key; the flags reach the controller; a configuration file; System 2 runs unless `--no-system2`, its cycle in `reflections.jsonl` and the configuration saved; a second run in the same run folder starts at the saved version and restores System 2's state, and `--fresh-configuration` starts at version 1 with System 2 fresh; a configuration that does not load stops play with its remedy |
| `test_export.py` | A `basic.cfg` bundle (schema 2) has every file and a frame per tick; pruned + legal partition the vocabulary; six instances, their evidence and the pick per tick; the history re-renders what each instance saw; the schema validates a trace, a meta, a history record and the ledger; copied run files; the index; a `connection_lost` episode is written but not shippable; a schema-1 bundle is reported; fail fast without the key; `failing_condition` agrees with `is_satisfied`; `reflections.jsonl` in every bundle, checked line by line against System 2's records and `episode.json`'s counts; `--no-system2` records none; exported episodes start from the run folder's saved configuration and carry it on, the first from version 1 with `--fresh-configuration` |
| `test_serve.py` | Two live `basic.cfg` episodes in-process on the fake: the event order, frames on disk before their tick, the episode in progress from memory, each finished episode a valid schema-2 bundle, the next seed, the status; stopping mid-episode; clearing the live folder; a macro admitted mid-episode reaching the catalog with configuration versions 1 → 2; a slow-path answer in flight at the end logged in its own episode; the flags in the status and serving needs the key; System 2's records streamed as `reflection` events, equal to the bundle's file; `--no-system2`, `--configuration` and `--fresh-configuration` |
| `test_state_and_actions.py`, `test_features.py`, `test_simulator.py`, `test_visualizer.py` | The state, action, encoding and simulator contracts; the HUD and the panel of the six instances |

The web explainer has its own checks, run from `web/`: `npm run build`
and `npm run lint` (type-check and oxlint), `npm test` (Vitest: the
loader and the trace readings on a five-tick schema-1 fixture bundle, and
the glossary against §18 and the code it names) and `npm run e2e`
(Playwright, against the shipped schema-1 recordings and a live
stand-in that replays one of them).

**Continuous integration.** `.github/workflows/checks.yml` runs on every
pull request and every push to main, in two jobs of at most ten minutes
each. `web` (Node 22): `npm ci`, `npm run lint`,
`npx prettier --check src e2e`, `npm test`, `npm run build`, then
Playwright with the Inter font and `npm run e2e`. `python` (3.11): torch
from the CPU wheel index, `pip install -e ".[dev,learn]"`, and
`python -m pytest -k "not live"`; the live tests need `LIQUID_API_KEY`
and are run locally. `.github/workflows/pages.yml` deploys the site
(§8.15).

---

## 17. Extending the system

**Change what an instance sees**: write a configuration (start from
`default_configuration().save("configuration.json")`), edit a scope,
concern or reason list, and play with `--configuration`. Validation keeps
it bounded (§8.4). System 2 changes the configuration through the same
model, one validated version at a time, and saves the one in play to
`runs/<scenario>/configuration.json`.

**Add a reflector**: append a `ReflectorSpec` to `REFLECTORS` in
`reflectors.py` (its scope: a history channel and `h_outcomes`; its
concern; its reasons) and give `change_menu` its finite changes; a new
kind of change also needs `apply_change`, `blocked_by` and a cooling
key. A history channel is a renderer in `history_channels.py` with a
golden-text test, like an evidence channel.

**Add an evidence channel**: add its name to `configuration.CHANNELS`,
its inputs to `EvidenceInputs`, and a renderer in `evidence.py`; give it
a golden-text test. A channel renders evidence; it never ranks or scores.

**Add a built-in action**: append an `ActionSpec` to `DEFAULT_PRIMITIVES`
or `DEFAULT_MACROS` in `actions.py`. For a *new primitive* you must also
teach the motor (`PRIMITIVE_BUTTONS`/`FLAG_TO_PRIMITIVE` in `motor.py`),
the simulator's `_step_primitive`, and decide whether `features.py`
needs a new component (if so, `ACTION_DIM` changes and old checkpoints
will — correctly — refuse to load).

**Add a scenario**: point `--scenario` at any ViZDoom cfg. If its win
condition differs, extend `ViZDoomBridge.level_cleared()`; if it lacks
turn/attack buttons, the motor and the menu already adapt.

**Use a different slow-path generator**: pass
`custom_llm_generator: Callable[[ExpansionRequest], str]` to
`DoomDecisionController` (it must return the proposal JSON string).
Admission is unchanged either way; that separation is the point.

**Embed the controller** (no CLI):

```python
from system1_doom.controller import ControllerConfig, DoomDecisionController
from system1_doom.vizdoom_env import ViZDoomBridge

env = ViZDoomBridge(scenario="basic.cfg", window_visible=False)
cfg = ControllerConfig(enable_slow_llm=False, log_dir="logs", call_budget_sec=5.0)
ctrl = DoomDecisionController(env=env, config=cfg)   # needs LIQUID_API_KEY
try:
    result = ctrl.run_episode(max_ticks=500)
    print(result["cleared"], result["finished_reason"], result["cost"], result["actions"])
finally:
    ctrl.close()
```

For tests, pass `transport=FakeD1(...)` (from `tests/fake_d1.py`) and any
placeholder `api_key`. `ControllerConfig(enable_system2=True,
configuration_out=..., system2_state_path=...)` runs System 2 beside
play; call `ctrl.wait_system2(timeout)` before reading its records.

---

## 18. Glossary

The web app's glossary (`web/src/content/glossary.ts`) carries every term
below in its own words, and a test reads this table, so a term added here
fails the app's tests until the glossary has it. The app still explains
the schema-1 recordings, so several terms below name parts this design
removed; their entries say what replaced them. The design's own words —
**instance**, **sense**, **central**, **channel**, **scope**, **message**,
**strength**, **relevance**, **configuration**, **miss** — are defined in
§8.4–§8.8, and System 2's — **reflector**, **history test**, **trial** —
in §8.16; they join this table with the app's rewrite in the third pull
request.

| Term | Meaning |
|---|---|
| **Action / `ActionSpec`** | The only executable unit: a bounded tuple of primitives with preconditions, a duration cap and a termination condition. Primitives are 1-step actions; macros are named multi-step ones. The legal menu of a tick is the set of actions whose preconditions hold. |
| **Arbiter** | Removed. The hand-written `FinalArbiter` that scored module votes, projections and bonuses into one pick is gone; the central instance, one d1-ultra choice over the legal menu, decides the action (§8.7). |
| **Budget mode** | Removed. There are no `full`/`reduced`/`critical` tiers: every tick waits for d1-ultra inside a per-call budget (5 s, `--call-budget`), and a call that misses it is recorded as a miss (§14). |
| **Committed pick** | Removed with the arbiter. The central's answer becomes the action as `top` (exploit), `drawn` (explore) or `missed` (§8.7). |
| **Context signature** | Coarse bucketed state key (`hp:…\|ammo:…\|enemies:…`) that keys the relevance ledger, the novelty counts, the simulator's empirical cache and the value networks' tried counts (§6.1). |
| **d1-ultra** | Liquid AI's decision model; answers typed `choice`/`noul`/`score` questions. It makes every decision: the five senses, the central and the admit instance are each one d1-ultra call (§8.6, §8.10), and so are System 2's reflectors, its central and the trial judge (§8.16). |
| **Exploration floor** | Removed with the training schedule. Exploration is the configuration's level: under `explore` the central's action is drawn from d1's own distribution with a seeded generator (§8.7). |
| **Exploration pressure / temperature** | Removed. There is no pressure formula and no temperature; the exploration level (`exploit` or `explore`) is configuration, stated to the central in its `exploration` channel. |
| **Gate network** | Removed. The relevance ledger replaced it: each sense's track record per context, shown to the central as counts (§8.8). Old checkpoints' gate weights are ignored on load. |
| **Live episode** | An episode being played right now by `python -m system1_doom.serve` and streamed tick by tick; when it ends it is a bundle like any recording (§8.15). |
| **Macro** | Multi-primitive `ActionSpec` (`is_macro=True`); built-in, or proposed by the slow path and admitted by the admit instance into the configuration. |
| **Module** | Removed. The five hand-written deciders became five senses: d1-ultra instances with their own scopes that decide whether to send the central a message (§8.6). The five value networks keep the names. |
| **Network share** | Experience-weighted mean of `n/(n+25)` over the tries seen in training: how familiar play has become to the value networks. A report only; it weighs nothing. |
| **Projection** | A bounded analytic rollout (`ProjectedOutcome`) of one legal action: expected value, damage, resources, survival. Shown to instances as the `projections` channel, labelled as a rough projection. |
| **Slow path** | The async proposal worker (Codex or templates) and the admission bounds and admit instance that can grow the menu, asked by System 2's menu reflector; never blocks a tick, and changes the configuration only at a tick boundary (§9). |
| **Trust λ** | `n/(n+25)` for an action tried `n` times in a context in training. No longer a blend weight: the tries themselves are shown in the `values` channel. |
| **Tick** | One decision: state → evidence → five senses → central → the action's primitives over ≈ 8 game tics, not one ViZDoom game tic. |

---

*Maintainers: when a channel, bound, question or file format changes,
update the matching section here and the design in
`docs/superpowers/specs/`. The spec (`docs/spec.md`) states the original
intent; this document states behaviour; the code is the truth when they
disagree.*
