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
> (“the design”; System 1, System 2 and the web app's rewrite are
> built).
> Background: [`spec.md`](spec.md) (the original 21-section spec, whose
> §21 invariant still holds) and
> [`superpowers/specs/2026-10-23-learning-controller-design.md`](superpowers/specs/2026-10-23-learning-controller-design.md)
> (the value networks). This document describes the code as it is.

**Package:** `system1-doom` 0.4.0 · **Python:** ≥ 3.11 · **Source layout:**
`src/system1_doom/` (32 modules, ≈ 11,500 LOC) · **Tests:** `tests/`
(25 files, 252 tests, 7 of them live) · **Web explainer:** `web/` (Vite +
React + TypeScript, on trace schema 2; 69 Vitest and 30 Playwright
tests), online at <https://danielriosgarza.github.io/system1_doom/>

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
   - 8.17 [The rule tree — `ruletree/`](#817-the-rule-tree--ruletree)
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
 Evidence channels (evidence.py): vitals · threats · incoming · outgoing · pickups · landmarks
      geometry · position · progress · history · frame · menu · projections (simulator) · values
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
| `LIQUID_API_KEY` | **Yes, to play on d1-ultra** | Read from env var `LIQUID_API_KEY`, else from `.env` in CWD or repo root (`d1_client.load_api_key()`). d1-ultra makes every decision, so `cli`, `train`, `export` and `serve` exit `2` without it. `export --check`, `--index` and `--schema` read files only and need no key. Tests answer from a fake transport and need no key except the seven live ones. |
| `TYPESAFE_API_KEY` | **Yes, to play on Jev** (`--decider jev`) | Read the same way (`load_api_key("jev")`). TypeSafe's Jev answers the same System One request at `https://api.typesafe.ai/v1/systemone`, so every instance runs on it unchanged (§8.10); the entry points exit `2` without the key. |
| `laya-serve` (pip `laya[serve]`, Convai Innovations) | Only for the rule tree on Laya (`--decider laya`) | Installed in an environment of its own (`laya` 0.4.15 brings torch and transformers) and started on the same machine with `LAYA_HOST=127.0.0.1 LAYA_DEVICE=cuda LAYA_MODELS=english laya-serve` (port 8000). The first start downloads the checkpoint from Hugging Face (`convaiinnovations/laya`, Apache 2.0). Without `LAYA_HOST` it listens on every interface with no key. |
| `LAYA_API_KEY` | No | Only when `laya-serve` was started with it; then read the same way (`load_api_key("laya")`) and sent as the bearer token. Without it no key is sent. |
| `kev.serve` ([github.com/jaredpalmer/kev](https://github.com/jaredpalmer/kev)) | Only for the rule tree on Kev (`--decider kev`) | A clone of the repository with an environment of its own; on the Jetson Thor torch must be overridden to a CUDA 13 build (`uv pip install -e ".[serve]" flash-linear-attention --override` a file holding `torch>=2.10`), since Kev pins torch below 2.9. Started with `python -m kev.serve --run jaredpalmer/kev-27b@v1.0 --port 8008`, which listens on 127.0.0.1 only; Kev-27B is 51 GB of weights from Hugging Face and needs about 66 GB of GPU memory. |
| `KEV_API_KEY` | No | Only when `kev.serve` was started with it; read and sent like `LAYA_API_KEY`. |
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

# 6) Play live and watch each decision in the web app as it is made
#    (http://127.0.0.1:8765/#live/watch).
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
├── tests/                          # 25 files, 234 tests, fake_d1.py and system2_fixtures.py (§16)
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
| `system2.py` | 1017 | `System2`: its thread, the cycle, System 2's central, trials and the judge, safety reverts, cooling, `system2.json` |
| `reflection.py` | 235 | `ReflectionTrace`, `TrialVerdictTrace`, `System2Note` (`reflections.jsonl`) and an episode's System 2 counts |
| `controller.py` | 750 | `DoomDecisionController`: one tick and one episode; configuration hook; System 2's host; misses; cost |
| `logger.py` | 145 | Schema-2 `TickTrace`/`ProposalTrace` JSONL logging, and System 2's `reflections.jsonl` |
| `tracing.py` | 276 | Typed trace records (state, pruning, projections, outcome, slow-path request), read-only |
| `export.py` | 1,060 | Episode bundles, `--check`, `--index`, `--schema` (`python -m system1_doom.export`) |
| `serve.py` | 636 | Live mode: plays episodes as `export` does and streams every tick (`python -m system1_doom.serve`) |
| `visualizer.py` | 347 | Split-screen HUD frames, GIF/MP4 recorder, live Tk panel of the six instances |
| `charts.py` | 117 | `learning_curves.png` from `metrics.jsonl` (matplotlib, dark theme) |
| `cli.py` | 220 | Play/watch entry point (`python -m system1_doom.cli`) |
| `train.py` | 492 | Training/evaluation entry point, `RunStore`, resume, best-checkpoint tracking, which configuration a run starts from (`starting_configuration`) (`python -m system1_doom.train`) |
| `__init__.py` | 3 | Package docstring + `__version__` |
| `ruletree/` | 2,100 | The rule tree, a second way to play (§8.17): `codes.py` (action codes), `tree.py` (rules, focus, skills, cornerstones, proposals), `walk.py` (one decision as Jev's answers down the tree, kept answers), `game.py` (the corridor, one 8-tic decision at a time), `check.py`, `gate.py`, `dossier.py`, `writers.py`, `loop.py` (the soft loop), `run.py` (the run folder), `bundle.py` (recordings for the website), `__main__.py` (`python -m system1_doom.ruletree`); `trees/` ships `general-9`, `general-11` and `codex-11`, `prompts/rule-writer.md` the rule writer's instructions |

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
| `approach_pickup` | forward ×4 (`pickup_id` param ⇒ motor steers) | walk to the pickup the resource sense chose, by its remembered position |
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
  centre, `angle_offset = atan((centre_x − cx)/centre_x)` in degrees
  (positive = left of crosshair; the screen spans 90°, so the edge is
  45°; a linear map, used until 2026-10-27, understated every angle off
  the centre), true distance from the objects buffer when
  available, else the sprite-size estimate `max(30, 3200/height)`.
  Name classification is keyword-based and shared with the motor
  (`is_enemy_name`, `is_pickup_name`, `is_ignored_actor` — dead actors,
  the player, blood/puffs/bullets/gibs are ignored). Pickup names map to
  categories via `PICKUP_CATEGORY_MAP` (medikit→health, greenarmor→armor,
  shellbox→ammo, shotgun→weapon, …). Each enemy carries how many of the
  agent's attacks on it in a row hit nothing (`attacks_without_hit`).
* **Remembered pickups** (`landmarks`): every pickup seen this episode
  whose position the objects buffer gives is remembered until it leaves
  the level's objects (picked up). Each carries, from the current
  position and facing, its distance and bearing (positive to the left),
  whether it is in view and when it was last seen; how the per-decision
  reward went with its distance over the decisions that moved the agent
  relative to it (a cosine, `reward_agreement`, and the number of such
  moves); and how many walks at it got no closer (`approaches_nowhere`).
* **Depth buffer** → mean depth of the centre/left/right thirds ×4 →
  `wall_distance_front/left/right`.
* **Screen buffer** → brightness, and a 320×240 JPEG (quality 75,
  base64), the image of every instance with `frame` in scope, when
  `include_jpeg_frame` is on (the default).
* Memory: last 10 actions, last 5 one-line state summaries, last 16
  discovered 128-unit grid sectors, archive strategy refs.

**`execute_action(action, targets)`** snapshots position, delegates to
`motor.burst(plan=action.primitive_expansion, steer_to_pickup=("pickup_id"
in parameters), enemy_target=…, pickup_target=…)` with the targets the
senses chose (`targets.enemy`, the visible enemy to aim at, and
`targets.pickup`, the remembered pickup to walk to; either may be
`None`), then derives everything the learner and logger need: reward,
damage taken, hits/kills deltas, health/armor/ammo *gains*, death,
displacement, and **new map cells** (128-unit grid cells first entered
this episode — the navigation reward). Two records feed the evidence,
and neither removes or chooses anything: a walk at the chosen pickup
(started with it within 30° of the facing) that got less than 12 units
closer adds one to its `approaches_nowhere`, and an attack on the chosen
enemy that hit nothing adds one to its `attacks_without_hit` (a hit
resets it). Every decision also adds to each remembered pickup's record
of how reward went with its distance.

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
`restart_episode(seed)` also clears the remembered pickups, the attack
records and the cell set.

### 8.2 Tactical motor — `motor.py`

The central instance picks an *action*; the motor executes that action's
**own** primitive list. The assists below are reflexes *inside* a
primitive (aim before firing, track while strafing, steer while walking
to a pickup), bounded by the plan; they never choose an action, and they
aim only at targets d1-ultra chose: the enemy the combat sense chose and
the pickup the resource sense chose (§8.6). With no chosen target the
primitive's keys are pressed as they are. `idle(frames)` presses
nothing, for a missed decision.

* **Timing.** Each primitive is held for `hold = max(1, 4 // len(plan))`
  motor steps, each step being `make_action(vector, frame_skip=2)`
  (2 game tics). A 1-primitive action and a 4-step macro therefore both
  last ≈ 8 tics; longer macros run longer. The burst stops at episode end.
* **Assisted primitives** (`_assisted_flags`) — every primitive keeps a
  small closed-loop assist, all bounded by the plan:
  * `shoot`: find the chosen enemy (`lock_id`, the object id of the
    combat sense's target; the motor never picks another); if it is
    off-centre by more than `align_px ≈ 10 px @320 wide`, press the turn
    button toward it (or strafe toward it on scenarios without turn
    buttons); fire only once centred. With no chosen enemy in view it
    fires straight ahead.
  * `strafe_left/right`: strafe, plus a tracking turn onto the chosen
    enemy while it is in view.
  * `strafe_left_shoot` / `strafe_right_shoot` (compound): strafe the
    whole step; turn toward the target, and press `ATTACK` in the same
    step once centred. This compound exists because no single primitive
    could move and fire simultaneously.
  * `move_forward` inside a pickup-seeking action: also turn toward the
    bearing of the chosen pickup's remembered position (outside a 4°
    deadband), so the walk works while the pickup is out of view.
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

| Instance | Scope | Reasons | Target |
|---|---|---|---|
| survival | `vitals`, `threats`, `incoming`, `projections`, `menu` | health_critical, under_fire, enemy_too_close, recovering, no_threat | — |
| combat | `threats`, `outgoing`, `vitals`, `frame`, `projections`, `menu` | target_aimed, target_off_centre, several_enemies, low_ammo, no_target | `enemy` |
| navigation | `landmarks`, `geometry`, `position`, `progress`, `menu` | path_clear, wall_ahead, stalled, off_course, door_or_switch_ahead, unexplored_side | — |
| resource | `landmarks`, `vitals`, `menu` | health_pickup_near, ammo_pickup_near, pickup_guarded, nothing_needed, nothing_visible | `pickup` |
| goal | `landmarks`, `progress`, `history`, `archive`, `values`, `menu` | making_progress, plateau, off_course, strategy_fits, strategy_failing, nearly_done | — |
| central | `messages`, `relevance`, `exploration`, `vitals`, `menu` (+ `novelty` while exploring, if there is room) | — | — |

A sense's **target** is the motor target it chooses: the combat sense
chooses which visible enemy the aim locks onto, the resource sense which
remembered pickup a pickup-seeking action walks to (§8.2, §8.6). Each
target kind is chosen by one sense at most; a configuration saved before
targets existed loads with these two.

No sense is shown `pickups` at first: `landmarks` lists every visible
pickup too (“in view”), with what walking at it has done. Shown both, the
resource sense kept choosing a clip that dozens of walks had failed to
reach, because the visible list named it plainly at 60 units without that
fact; shown `landmarks` alone it chose a pickup not yet failed in 11 of 12
logged moments. `pickups` stays a channel System 2 can widen a scope to.

**Validation** (a configuration that breaks any of these does not load):
the senses are exactly the five, in order; every channel is known and
appears once; every scope contains `menu`; a scope holds at most
`max_scope_channels` (7) channels; a sense's scope never contains
`messages`, `relevance` or `exploration`; reasons are unique lowercase
snake_case ids; each target kind belongs to one sense at most; only
macros can be admitted.

**`Bounds`** holds every number of the design in one place: per-call
budget 5 s; `yes_at` 0.5 (d1's own yes, for speaking and admitting);
scope 7 channels; caps of 6 enemies, 6 pickups, 8 remembered pickups, 6
history steps and 3 summaries; pools of 6 (System 1) and 2 (System 2); 1 trial in flight; 60
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
| `threats` | the visible enemies nearest first (at most 6): name, distance, angle, on-screen size, under the crosshair or attacking, how many of the agent's last attacks on it hit nothing; the count | observation, bridge |
| `incoming` | damage taken since the last decision; consecutive decisions under fire | observation, counter |
| `outgoing` | damage dealt, hits and kills since the last decision | observation |
| `pickups` | the visible pickups nearest first (at most 6): name, category, distance, angle | observation |
| `landmarks` | the pickups seen this episode and not picked up, nearest first (at most 8), each where it lies now from the agent's position and facing: distance, bearing (“behind you” past 90°), in view or when last seen, and how reward went with its distance (“reward rose as you got closer (agreement +0.97 over 8 moves)”); once walks at it got no closer, “cannot be walked to from here, N walks at it got no closer” in place of the reward link | bridge |
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
| `messages` | one line per spoken sense: “survival says strafe_left, strength 0.82, reason under fire.”, with the sense's target in the words it saw it in when it chose one (“…, aim at Zombieman at distance 180, 2 deg left, …”, “…, walk to GreenArmor (armor): 1192 away, …”) (central only) | System 1 |
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
| sense with a target | `target`: “Which visible enemy should the agent's aim lock onto?” (combat) or “When the agent walks to a pickup, which one should it walk to, given where each lies and whether walking at it has got the agent any closer?” (resource) | choice | the candidates its scope shows, id → the channel's own line for it (`threats` for enemies, `landmarks` for pickups); asked only when there are two or more |
| central | `choose`: “Choose the action the agent executes now.” | choice | exactly the legal menu |
| admit | `admit`: “Should this proposed macro-action enter the agent's legal menu?” | noul | — |
| reflector | `speak`: “Must the slow system's central hear a proposal from you now?” | noul | — |
| reflector | `change`: “Which configuration change do you propose?” | choice | its change menu after the bounds (§8.16) |
| reflector | `reason`: “Which reason best describes why?” | choice | the reflector's reasons |
| system2_central | `configure`: “Choose the one configuration change to make now, or none.” | choice | the proposals the bounds still allow, then `none` |
| judge | `verdict`: “Keep this configuration change, or revert it?” | choice | `keep`, `revert` |

`InstanceResult` keeps everything for the trace and the history: scope,
verbatim evidence, image reference, every answer in full, `spoke`,
`strength`, the top `action` and its distribution, the top `reason`, the
`target` with its distribution and its line,
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
action, reason, strength = the `speak` probability, unscaled, and its
target in the words it saw it in) to the central's `messages` channel; a silent sense is logged with the same
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
central's result, the messages, the pick, the motor's targets and the
timings (`senses_ms`, `central_ms`), and sums the tick's usage.

The **targets** (`Targets`: `enemy`, `pickup`, `chosen_by`) are the
senses' `target` answers, each from the sense the configuration gives
that kind; the controller passes them to `execute_action` with the pick.
A sense that missed leaves its target empty, and the motor then has
nothing to aim at. When there is a single candidate (one enemy in view,
one pickup remembered) it is the target without a question, since a
choice needs two options; `chosen_by` records it as `only candidate`.

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

* **Deciders.** The client takes a `Decider`, data naming the model the
  hierarchy runs on: `d1-ultra` (the default) or `jev`, TypeSafe's
  System One model, which answers the same request (`model`, `state`,
  `questions` of type `noul`, `choice` and `score`) with the same answer
  shapes at `POST https://api.typesafe.ai/v1/systemone`, model
  `jev-latest` (each response names the version that answered, counted
  by `models_answered()`). What differs is in the `Decider`: the
  endpoint, the model, the key's variable (`TYPESAFE_API_KEY`), how a
  screen is sent (Jev takes `assets`: the 320×240 JPEG is scaled up by a
  whole factor to 640×480, TypeSafe's minimum side being 280 px, and
  referenced from the end of the state under `[screen image]`, with the
  `TypeSafe-Danger-Zone-Images: true` header), and the published input
  price ($0.042 per million tokens, output free), which stands in for
  the `cost` a Jev usage block does not report. `ControllerConfig.decider`
  and `--decider` on every entry point select it; both of the
  controller's clients (System 1's and the slow path's) use the same one,
  so the senses, the central, the admit instance, the reflectors,
  System 2's central, the history test and the trial judge all run on it.
  A third decider, `laya`, is Convai Innovations' open-weight Laya (the
  English checkpoint: ModernBERT-large with a decision head, 421M
  parameters), served on the same machine by `laya-serve`, which answers
  the same request at `POST http://127.0.0.1:8000/v1/systemone`. Its
  `Decider` pins the `english` checkpoint, sends no screen
  (`images="none"`; Laya reads text only), needs no key unless the server
  has one (`key_required=False`), and carries `max_len: 2048` on every
  request (`Decider.request`): the checkpoint's own window of 512 tokens,
  question and options included, would cut a rule-tree state of 350 to
  750 tokens before its `[focus]` line. It has no price, so its cost is 0;
  every response names `laya-rl-agent`. A fourth, `kev`, is Jared
  Palmer's open-weight Kev, served on the same machine by `kev.serve` at
  `POST http://127.0.0.1:8008/v1/systemone` as `kev-latest` (the
  checkpoint is the one the server was started with); it is sent the text
  alone too, needs no key unless the server has one, and reads states of
  up to 65,536 tokens, so it carries no request fields of its own. Only
  the rule tree takes Laya and Kev so far (`DECIDER_NAMES`, the
  hierarchy's choices, stays `d1-ultra` and `jev`), since the combat sense
  reads the screen.

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
`BundleIndexEntry` and the run-file models; the app's types
(`web/src/schema/bundle.ts`) are generated from it, by `npm run schema`
and then `npm run types` (`web/scripts/gen-types.mjs`) in `web/`.

**The app reads schema version 2.** `SUPPORTED_SCHEMA_VERSION` in
`web/src/data/loader.ts` is 2. A schema-1 recording is refused with a
message saying it comes from the old architecture, where an arbiter
weighed five modules, and that it must be recorded again with `python -m
system1_doom.export`; any other version is refused with the version it
found. Every word and number on a screen is read from the bundle:
`web/src/data/readings.ts` (System 1's ticks), `system2.ts` (System 2's
records) and `learning.ts` (the ledgers and the tried counts) only
rearrange what was recorded, and nothing in the app ranks, scores or
decides.

The app (`web/`, see `web/README.md`) has six screens, picked from tabs
in the top bar (keys 1 to 6): Watch, The instances, The slow system,
Learning, Growing the menu and Reference. The URL hash is
`#<episode>/<tick>/<screen>`, with the screen ids `watch`, `instances`,
`slow`, `learning`, `menu` and `reference`; a link without a screen opens
The instances, a fresh visit lands on Watch with the most recently
recorded recording that cleared the corridor
(`#optimized-corridor-12/0/watch`), and `#live/<screen>`
follows live play. Every screen but Watch shares the timeline at the
bottom: the counter, the pace, and marks for damage, a kill, a death, a
miss, a drawn pick, a configuration change and each System 2 cycle.
Every panel has an explanation behind the toggle in its heading, which
links its glossary words once each and names the code that renders what
it shows. Only three give a formula: the n-step return behind “paid off”
(the ledger, and relevance over episodes) and the history test's metrics.

**Watch** plays the recording at the agent's own pace, one decision
every 8 game frames (8 ÷ 35 s, about 0.23 s; Slow is one a second), with
its frames fetched and decoded ahead and a crossfade from one to the
next. Beside the game is the strip, one row per instance at this
decision: the five senses, each spoke (its speak strength as a bar, the
action it named and its reason), silent, or missed (with the reason);
the central's row (its pick, the probability, whether the pick was its
top answer, drawn under explore, or a miss, and how many messages it
heard); the Act row (the primitives held over the 8 frames, and the
motor's targets with the sense that chose each, in recordings made since
the senses choose them); and a thin
configuration line (the version in force, the last change and what
became of it, and the trial in flight with its count of decisions). A
click on a row opens that instance on The instances at that decision.
Under the game are Play/Pause, the pace, the counter (decision N of M and
the game time) and a progress bar that seeks; below, a card per
recording, each playing from its first decision, with a link to how it
was made. Watch plays on its own only on a fresh visit or a link to its
first decision, never under reduced motion, and then loops, holding the
result 2.5 s at the end; anything the viewer does ends the loop, and a
link to a later decision waits for Play. A line under the game says it
is a recording replayed at the agent's pace and links to the `serve`
command that plays the same game live.

**The instances** shows one instance at a time, picked from a tab per
instance that says whether it spoke, stayed silent or missed (the
central's tab names its pick): its scope as chips, the channels it was
shown and those it was not (the survival sense's `pickups` chip is hidden
until System 2 widens its scope); the screen it was sent when `frame` is
in its scope, or a line saying it was sent none; its evidence verbatim,
the exact text of the trace with each `[channel]` header marked, which a
browser test compares character for character with `ticks.jsonl`; and its
answers as bars: the speak probability against yes_at 0.5 and the action
and reason distributions for a sense, with the target the combat or
resource sense chose (in the words it saw it in, with the target
question's distribution, or a note that a lone candidate needed no
question), and for the central its choice distribution over the legal
menu with the pick marked and the messages it heard, each naming its
target. A miss shows its reason and the raw answer as returned.

**The slow system** reads `reflections.jsonl`, `relevance.json` and the
configuration at the episode's start and end. First, a timeline of
configuration versions: each version's change in words, the reflector
that proposed it, System 2's central's probability for it, and what
became of it (kept, reverted, in trial, queued for the next episode).
Then the episode's cycles, each with its outcome; for the cycle picked,
every reflector in call order (not called, with the bound that left it
nothing to propose; silent; or proposing, with its change and reason
distributions) and, opened, the evidence it was sent, verbatim; and
System 2's central, with the proposals it heard, its choice distribution
and its evidence. The history test is a table: each sampled tick with
its stratum (bad, good or rest) and the old and new answers (`spoke ·
weave fire (0.90)`, `silent (0.15)`), then each metric under the old and
the new scope with the composite, the gain against the 0.05 margin, the
worst drop against 0.10, the noise re-asks, the calls and the verdict; a
sampled tick from this episode opens The instances there. The trial
shows its before and during table as the judge was shown it, the
judge's keep or revert with its distribution and evidence, and what a
revert restored. The relevance ledger is listed per sense and situation
(spoke, followed, paid off, overruled, overruled and paid off, mean
strength, and what this episode added), with the current decision's
situation marked and the central's `[relevance]` channel beside it,
verbatim. Last come each instance's scope, the admitted macros, the
strategy and the exploration level at the episode's start and end.

**Learning** draws the paid-off rate of each sense's followed messages
over episodes, one line per sense, from this episode's ledger before and
after and the other recordings' ledgers (a legend, a crosshair with a
tooltip, and the numbers in a table). Then the value networks as
evidence: the `values` channel's numbers for each legal action in this
situation, how many times each action was tried there in training
(`trust.json`, shown as n ÷ (n + 25)), the checkpoint, the network share
and the situations trained most.

**Growing the menu** follows the one path that adds to the menu: the
menu at this decision (each action as a primitive, a built-in macro or an
admitted one, legal now or not, and how often it was executed), the menu
reflector's answer at each cycle, each slow-path proposal (the request
verbatim, the text as returned, and each stage of the admission pipeline
it passed or failed) and the admit instance's probability against yes_at
with its evidence. A recording without a proposal says that System 2 did
not ask the slow path for a macro.

**Reference** states the one rule (every decision here is made by
d1-ultra) and the principles under it, with one line naming what the
design removed; a drawing of the two systems (System 1: evidence, the
five senses, messages, the central, the pick and Act; System 2: the
history channels, nine reflectors, its central, the history test or the
slow path and the admit instance, the configuration, the trial and the
judge), with every d1-ultra instance marked; the glossary of §18 (a
linked word anywhere in the app opens its entry, and each entry links to
the panels that show it and names its code); how this recording was made
(scenario, seed, networks, configuration versions, slow path, call
budget, calls and misses, the result, the `export` command that records
one like it and the `serve` command that plays live); and the keys.

**The recordings.** Nine bundles of the senses and central ship in
`web/public/episodes/` (with the rule tree's five, §8.17 and §15), all of
`deadly_corridor.cfg` with the best networks as evidence. Four show the
agent as it is now, the senses choosing the motor's targets:
`optimized-corridor-9` to `optimized-corridor-12`, seeds 9 to 12 from
version 1, played by Jev because d1-ultra's account had no credit when
they were made; every one recorded ships, and the cleared one (seed 12)
is the landing. The other five were recorded before the senses chose
targets, when the motor picked the enemy it aimed at and the pickup it
walked to; the index says which (`BundleIndexEntry.senses_choose_targets`,
read from the file: its starting configuration names a sense's
`target`), lists the four first, and the cards and the picker say it.
Of those five, three were played by d1-ultra: `corridor-9` and `corridor-11` start from the
design's version 1 (`--fresh-configuration`), and `corridor-9-v2` replays
seed 9 from version 2, the configuration System 2 reached and its judge
kept on the same run folder. Two were played by Jev (`--decider jev`,
§8.10): `jev-corridor-9` and `jev-corridor-11`, seeds 9 and 11 from
version 1, so each stands beside the d1-ultra recording of its seed. The
index names each recording's decider (`BundleIndexEntry.decider`), and
the app says it on the recording's card, in the picker, in the top bar
and wherever it counts calls. Their numbers, and what System 2 did in
each, are in §15.

**GitHub Pages.** `.github/workflows/pages.yml` builds `web/` and
publishes `web/dist` to <https://danielriosgarza.github.io/system1_doom/>
on every push to main (or by hand from the Actions tab); the build's
relative base (`./`) makes it work under `/system1_doom/`. The repository
needs Settings → Pages → Build and deployment → Source: GitHub Actions.
Live mode is not on Pages: a static site cannot stream, and without
`live/status.json` the app is the recordings only.

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
0.8 s measured, §15). The app asks for `live/status.json` at start; when
`serve` answers, the picker lists the live episodes, the top bar shows
LIVE, and `#live/<screen>` follows the episode in progress: each `tick`
event adds a decision to every screen, and each `reflection` event adds
System 2's record (a cycle, a verdict or a note) to The slow system as it
is written. Moving away stops following; the Follow button or the key l
goes back to it. Until a live episode ends, its `relevance.json` is the
ledger at the episode's start, so the app reads it as the before
(`ledgerAt` in the loader) and adds the episode's own ticks for the
after. A slow-path proposal still in flight when
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
configuration the one before saved, and a change the episode's end cycle
queued takes effect at the next episode's first tick boundary (that
episode's `configuration_start` is the version before it, its first tick
the version after). System 2's own state (its decision count, the last
cycle, cooling, the change log, recent tests and verdicts, the trial in
flight, a pending change) is saved atomically to `runs/<scenario>/system2.json` at every
cycle, verdict, note, configuration change and episode end, and when
play stops. It is restored at the first tick only when the session
starts from the configuration it was saved with (a fingerprint of that
configuration), which the default start ensures; a flag that changes the
configuration before play (a different `--call-budget`, `--explore` or
`--exploit`) changes the fingerprint, and System 2 starts fresh, with a
note, as it does from any other configuration. A revert or a queued
change saved before it took effect is queued again on restore: a revert
as the configuration it restores, a queued change rebuilt from the saved
configuration (`apply_change`), each as the saved version + 1, keeping
its prediction and cooling key, and the `restored` note says so. It takes
effect at the first tick boundary, where a queued change's trial starts
against the decisions before it, saved with the change (this process's
history does not hold them). A macro asked for or admitted is dropped,
with a note, since the slow worker does not outlive the process.

**The controller's side** is the `System2Host` protocol (§8.13). An
episode's counts land in the `run_episode` result and in `episode.json`
as `system2`. The calls are in the per-instance counters and, because a
cycle runs while the agent plays, in the cost of the episode during
which they were made.

---

### 8.17 The rule tree — `ruletree/`

The rule tree is a second way to play, separate from the senses and the
central. It uses the same bridge (§8.1), the same evidence channels
(§8.5) and the same Jev client (§8.10); nothing else of System 1 or
System 2. Every decision is still an answer of the decision model: the
code walks the tree, renders the state and presses the keys of the rule
Jev's answers led to.

**A decision is a walk down the tree.** Each node is a rule: a
condition, one sentence Jev judges from the state, and an action. A
rule's children are its exceptions. At a node with children Jev is asked
one choice question, "Which of these is true right now?", whose options
are the children's conditions and "None of these is true right now."
The walk moves into the child with the highest probability and asks
again. It stops at a node without children, or when Jev answers none,
and that node's action is played for the decision's 8 tics. The root has
no condition; its action is a random code, drawn from the game's seed and
the decision's number so that a replay draws the same one.

**Focus.** A node may have a focus. Before its children are asked, Jev
picks one listed item of some channels, for example "Which of these
enemies is the biggest danger to me right now?" over the threats list.
The item is added to the state as a `[focus]` channel, so the rules below
speak of "the focus" instead of naming a monster. With one item there is
no question.

**Skills.** An action may call a skill, `{"skill": "aim", "then":
"0001"}`. A skill is a second tree without a condition at its top, and
the walk goes on there. A rule inside a skill may give only the start of
a decision, such as `00R0:3` (turn right for 3 tics); the caller's
`then` fills the tics left. With no rule of the skill true, the caller's
`then` is the whole decision.

**Actions** (`codes.py`). A code has four letters: walk (`F`, `0`, `B`),
sidestep (`L`, `0`, `R`), turn (`L`, `0`, `R`) and fire (`1`, `0`), so
`F0R1` walks forward while turning right and firing. There are 54 codes.
A code alone is held for 8 tics; a sequence `CODE:TICS+CODE:TICS` splits
them (`00R0:3+0001:5`). The keys are pressed in `game.py` only.

**Misses.** A failed call is a miss: the walk stops at the node it has
reached and that node's action is played; a skill call stopped this way
plays its `then`. The decision records the miss. Nothing stands in for
the answer.

**The state** (`game.py`). A goal paragraph ("Reach the green armor at
the far end of the corridor alive ..."), then ten channels of §8.5 in
order (vitals, threats, incoming, outgoing, pickups, landmarks,
geometry, position, progress, history) and the screen. The outgoing
channel adds "the last N decisions in which you fired hit nothing" once
N is 2: firing at an enemy the shots cannot reach, behind the edge of a
wall, otherwise looks like ordinary misses. Every game starts as on a new
bridge (tick count and total reward at zero), so a replay shows Jev the
same state as the game it replays.

**The trees** (`ruletree/trees/`). A tree is a folder that plays on its
own: `tree.json` (the rules, focus questions and skills), `cornerstones/`
(the screen of each frame a rule was written from) and `build.jsonl`
(the record of the soft loop that built it). Three ship; `general-11`
plays when no tree is named (§15: it cleared about as many games as
`codex-11`, in fewer decisions):

| Tree | Rules | How it was made |
|---|---:|---|
| `general-9` | 9 | Written by hand from what the first two stages of the soft loop taught: a focus question picks the enemy or the goal, one aiming skill turns toward it, the caller says what to do next. No monster names and no map distances. |
| `general-11` | 11 | `general-9` plus two rules the soft loop added with Claude as the rule writer (r11, r12 below). |
| `codex-11` | 11 | `general-9` plus two rules the soft loop added with Codex as the rule writer: when the focus is at most 2 pixels wide, at least 6 tall and to one side, aim and sidestep away from that side while firing. |

`python -m system1_doom.ruletree show --tree general-11`:

```text
root: default -> random walk
  r1: if 'The threats list shows at least one enemy.' [focus: 'Which of these enemies is the biggest danger to me right now?' among threats] -> use skill aim, then fire
    r2: if 'The focus channel says the enemy is more than 400 units away.' -> use skill aim, then walk forward + fire
    r11: if 'The outgoing channel says the last 5 or more decisions in which I fired hit nothing.' -> use skill aim, then walk forward + fire
      r12: if 'The focus channel shows the enemy at least 6 pixels wide.' -> use skill aim, then fire
  r3: if 'The threats list says no enemy is visible.' [focus: 'Which of these is the goal I am trying to reach?' among landmarks] -> use skill aim, then walk forward
skill aim:
  aim: default -> the caller's action
    r4: if 'The focus channel says it is between 3 and 7 degrees to the right.' -> turn right for 3 tics, then the caller's action (00R0:3)
    r5: ... between 7 and 12 degrees to the right -> turn right for 5 tics (00R0:5)
    r6: ... more than 12 degrees to the right -> turn right for 7 tics (00R0:7)
    r7, r8, r9: the same three to the left
```

The turns come from the measured turning table: from rest, 3 tics turn
5.3 degrees, 5 tics 8.8 and 7 tics 15.8. Every turning action ends with
at least one tic without turning, because a turn that runs on into the
next decision goes about twice as fast and overshoots.

**The soft loop** (`loop.py`) writes the rules, one failure at a time:

1. Play every training seed once with fresh answers.
2. Take the first game that went wrong: the agent died, stalled (its
   furthest point grew by less than 48 units over 24 decisions) or ran
   out of time. Its dossier (`dossier.py`) shows the tree, the last 12
   decisions (the action, the walk and its probabilities, health,
   position, the screen, and where the enemies really were, for the
   writer only) and the state Jev read at each, word for word.
3. The rule writer (`writers.py`: Codex through `codex exec`, Claude
   through `claude -p`, or a file a person fills in) answers one rule, or
   a small group that forms one skill, written from one frame of that
   game; or it says the state lacks what is needed. Its instructions are
   `ruletree/prompts/rule-writer.md`.
4. The check (`check.py`):
   * **sees**: at its frame, the walk through the new tree passes
     through the new rule;
   * **unchanged**: the frames earlier rules were written from take the
     same route, or replaying their game from there to their own horizon
     with the new tree ends no worse than the rule's own check did;
   * **avoids**: the game is replayed to the frame and played 24
     decisions past the failure, once with the old tree and once with
     the new one. Each ends as (alive, goal reached, health, furthest
     point). Alive beats dead and the goal reached beats not reached;
     otherwise the new tree must be no worse on health and furthest
     point and better on one. If both die, the rule fails: dying a
     little further on does not avoid the death.
5. The gate (`gate.py`): every training seed is played with the current
   tree and with the new one; the new one must clear at least as many.
6. A rule that passes both is added as an exception to the node that
   decided at its frame (or to a node on that walk the writer names), and
   the frame becomes its cornerstone: the seed, the actions that led
   there, the state text, the screen, the route the walk took, the
   horizon and the standing there.

A failed check or gate goes back to the writer with the report, up to
three proposals per failure. The writer never plays: the engine plays
and replays games and grades proposals, and Jev never sees the engine.

**Answers are kept** (`walk.py`). A game asks Jev afresh and keeps each
answer, keyed by the state, the screen, the question and the options. A
check reads every kept answer first, so a replayed state gets the answer
it got in play and the old and new trees are compared on the same
answers up to the frame.

**The run folder** (`run.py`):

```text
<run>/tree/              the tree being built (tree.json, cornerstones/)
<run>/games/<game>.json  one game: seed, tree, and per decision the action, the walk with every
                         question, option, probability, latency and cost, health, position, events,
                         the state text and the screen
<run>/games/<game>/      its dossier (dossier.md, frame-NNN.jpg)
<run>/answers/           Jev's answers, one file per game or check
<run>/proposals/         every prompt, answer, check report and gate report
<run>/build.jsonl        one line per start, pass, proposal, check, gate, commit and evaluation
```

Games run in parallel threads (`--workers`, default 6), each borrowing a
game from a pool, with one client for all.

**Recordings** (`bundle.py`). `python -m system1_doom.export --solution
rule-tree` plays one seed with a tree from the start to the end of the
episode (a stall does not stop it, as it stops a game of the soft loop)
and writes it as a folder the website reads:

```text
episode.json       RuleTreeEpisodeMeta: the tree, the seed, how the episode ended, Jev's calls, cost and misses
decisions.jsonl    one RuleTreeDecision per decision: the state text Jev was sent, every step of the walk
                   (question, options, probabilities, pick, focus, skill), the action in codes and in words,
                   health before and after, kills, position, reward and events
tree.json          the tree as played, with cornerstones/ (the screen each rule was written from)
build.jsonl        the soft loop's record of how the tree was written
frames/00042.jpg   the screen Jev was sent at decision 42; frames/end.jpg after the last action
```

To keep the screen after the last action, a recording holds each
segment's keys one tic at a time; the game plays the same (a test plays
a seed both ways). `--check` checks that every decision has a walk, that
the action played is the action of the node the walk reached, and that
every frame exists.

**On the website.** A side tab on the left of every page (two buttons
above the top bar on a phone) switches between the senses and central
and the rule tree. The rule tree has six screens of its own, keys 1 to 6:

- **Watch**: the recording at the agent's pace, beside the walk of the
  decision shown: one row per question (where it was asked, Jev's pick
  and its probability), the skill steps, and the action played with the
  rule it came from.
- **The questions**: every question of one decision, each with the text
  Jev was sent exactly as sent (the state text, and after a focus its
  `[focus]` line), the screen, every option with Jev's probability, and
  where the answer led.
- **How the rules were written**: `build.jsonl` step by step: each pass
  over the training seeds, each proposal with the writer's reason, its
  check and its gate, the rules added, and the held-out seeds.
- **Results**: the seeds cleared at each pass, the benchmark of §15 (cited,
  not computed from the recording), how often each rule was walked into
  and played in this recording, and its calls and cost.
- **The rule tree**: the whole tree as an outline with this decision's
  walk marked, and for any rule its action, who wrote it and why, the
  proposal that added it, and its cornerstone.
- **Reference**: the one rule and principles as they apply here, a
  drawing of the walk and the soft loop, the glossary's rule-tree terms
  (§18), how this recording was made, and the keys.

Its links are `#rules/<recording>/<decision>/<screen>`, with the screen
ids `watch`, `questions`, `written`, `results`, `tree` and `reference`; a
link without a screen opens The questions, and every senses-and-central
link works as before. Switching keeps the screen at the same position and
opens the other solution's recording of the same seed at its first
decision; the picker lists only the shown solution's recordings, and the
choice is remembered with the theme and the pace, so a later visit
without a link lands on that solution's Watch. Without a link the rule
tree opens a `general-11` recording (`DEFAULT_TREE`), the newest that
cleared. A browser test rebuilds the text each question was sent from
`decisions.jsonl` and compares it with The questions character for
character.

**On Laya and Kev.** Every command that plays takes `--decider laya` or
`--decider kev`: the same walk, with each question sent to that model on
this machine (§8.10) instead of Jev, and the same records, whose `models`
then name `laya-rl-agent` or `kev-latest`. A run's answer book keys each
answer by the model, so the models' answers are never mixed.
With `--ahead`, before a rule question the walk sends in one request
every question it may ask next about the same text (`walk.upcoming`: the
node's own, its children's focus questions while the text has no focus,
and the questions of the children and skills it reaches without a focus),
and takes the answers it reaches from there; an answer asked that way
carries its share of the request's latency and cost and `batch`. For a
model that reads the state once and answers each question as its own
row, as Kev does, the extra questions cost little; the walk and its picks
are the same. `ruletree/teach.py` turns the games of runs into training
data for a model of one's own: every question once, as it was sent, with the
answer of the model that played (or, with `--labels text`, the answer
the state text settles), in the form `laya-train` reads. `ruletree/agreement.py` asks a decider the
questions of the shipped recordings again, with the text and options Jev
was sent, and scores both models where the state text settles the
answer: at the root whether the threats list names an enemy, in the aim
skill which band the focus angle is in (an angle on a band's edge is
left out), under r1 the focus's distance and the run of fruitless
firing, and which landmark is the GreenArmor. Laya, out of the box,
clears none of the benchmark seeds; fine-tuned on 3,212 of Jev's
answers it clears 75 of 81, and Kev-27B answers as well as Jev without
fine-tuning (§15).

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
| `--decider {d1-ultra,jev}` | `d1-ultra` | The decision model every instance calls (§8.10); `jev` needs `TYPESAFE_API_KEY`. On `train`, `export` and `serve` too |
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
| `--call-budget`, `--decider`, `--explore`/`--exploit` | 5 / d1-ultra / exploit | As above |
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
| `--call-budget`, `--decider`, `--explore`/`--exploit` | 5 / d1-ultra / exploit | As above |
| `--codex` | off | Let the slow path call the Codex CLI; otherwise it runs on templates |
| `--no-slow-path` | — | Switch the slow path off |
| `--no-system2` | — | Switch System 2 off; `reflections.jsonl` is then empty |
| `--configuration PATH`, `--fresh-configuration` | the run folder's, else the design's | As `cli`, for the first episode; each next one starts from the configuration the one before saved, and a change its end cycle queued takes effect at the next one's first tick |
| `--check BUNDLE` | — | Validate a bundle and exit (exit code 1 on problems); no key needed |
| `--index DIR` | — | Write `DIR/index.json` listing its shippable bundles and exit; no key needed |
| `--schema OUT.json` | — | Write the bundle JSON Schema and exit; no key needed |
| `--solution` | `senses-and-central` | `rule-tree` records the rule tree instead (§8.17): Jev decides, `deadly_corridor.cfg` only; `--episodes`, `--seed`, `--out` (default `bundles/rule-tree-<tree>-<seed>`), `--name`, `--title` and `--call-budget` (default 10) apply, the senses' flags do not |
| `--tree` | `general-11` | With `--solution rule-tree`: a shipped tree or a tree folder |

`--check` and `--index` read both kinds of bundle. An index line says
which way of playing recorded it (`solution`, absent in lines written
before there were two) and, for a rule tree, which tree (`tree`); the
index lists the senses and central first.

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
python -m system1_doom.export --solution rule-tree --tree general-11 --seed 9 \
    --name rules-corridor-9 --out web/public/episodes/rules-corridor-9
```

### `python -m system1_doom.serve` — play live and stream ticks

| Flag | Default | Meaning |
|---|---|---|
| `--scenario`, `--seed`, `--networks`, `--run-dir`, `--max-ticks`, `--call-budget`, `--decider`, `--explore`/`--exploit`, `--codex`, `--no-slow-path`, `--no-system2`, `--configuration`, `--fresh-configuration` | as `export` | How to play; episode k gets seed `seed + k - 1` |
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

### `python -m system1_doom.ruletree` — the rule tree

The rule tree's own entry point (§8.17). It needs `TYPESAFE_API_KEY`
(Jev makes every decision); without it every command but `show` and
`finish` exits `2`. With `--decider laya` or `--decider kev` Laya or Kev
makes every decision instead, on the `laya-serve` or `kev.serve` of this
machine (§3), and no key is needed.
`RUN` is a run folder; the first command on it names the tree it starts
from with `--tree` (a shipped tree's name or a tree folder). `play` and
`eval` start from `general-11` when no tree is named; `show` prints it.

| Command | What it does |
|---|---|
| `show [--tree T]` | Print a tree |
| `play RUN --seed N` | Play one seed; the game and its dossier go to `RUN/games/` |
| `eval RUN --seeds 201-215,301-315` | Play each seed once, in parallel, and print one line per seed and the number cleared |
| `loop RUN --writer codex\|claude\|file --train 9-19 --held 20-39 --rounds 12` | Run the soft loop until every training seed clears (then play the held-out seeds) or the rounds run out |
| `check RUN PROPOSAL.json` | Check a proposal against a game of the run; exit 0 if it passes |
| `gate RUN PROPOSAL.json --seeds 9-19` | Check it, then play the seeds with and without it |
| `commit RUN PROPOSAL.json` | Check it and, if it passes, add it to the run's tree |
| `finish RUN OUT` | Copy the run's tree and `build.jsonl` into a tree folder that plays on its own |

Every command but `show` takes `--workers N` (games played at once,
default 6), `--decider jev|laya|kev` (default `jev`), `--model`
(default `jev-latest` for Jev, `english` for Laya, `kev-latest` for Kev;
`ruletree-jev-v1` names the fine-tuned Laya, §15), `--endpoint` (the
decider's System One URL, when it is not the default), `--budget S`
(seconds a question may take before it is a miss; default 10) and
`--ahead` (ask the questions the walk may ask next about the same state
in one request; for a model that answers each question on its own, such
as Kev or Laya, §8.17).
`loop` also takes `--writer-cmd` (the writer's command, reading the
prompt on stdin; `{out}` names its answer file) and `--attempts`
(proposals per failure, default 3).

```bash
python -m system1_doom.ruletree eval runs/rt --tree general-11 --seeds 9-19
python -m system1_doom.ruletree eval runs/rt-laya --tree general-11 --seeds 9-19 --decider laya
python -m system1_doom.ruletree loop runs/codex1 --tree general-9 --writer codex --train 9-19 --held 20-39
```

`python -m system1_doom.ruletree.agreement OUT.json --decider laya`
asks the questions of the shipped recordings again and prints, per
question, how often the decider picked as Jev did and, where the state
text settles the answer, how often each model was right and what a
uniform pick would score; every answer goes to `OUT.json`. It takes
`--model`, `--endpoint`, `--max-len N` (Laya's window; `0` sends none)
and `--episodes`.

`python -m system1_doom.ruletree.teach OUT.jsonl RUN [RUN ...] --seeds
400-424 [--labels teacher|text|text+teacher]` writes the questions of the
runs' games on those seeds as training data for `laya-train` (§8.17).

There is no `python -m system1_doom` `__main__`; use the module entry
points above (or embed `DoomDecisionController` directly — §17).

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
`python -m system1_doom.export` (§8.15); gitignored. A rule tree's
recordings default to `bundles/rule-tree-<tree>-<seed>/` (§8.17).

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
| The session ends with a revert or a change queued but not yet in play (an end-of-episode cycle's, in a multi-episode `export`) | Saved in `system2.json` and queued again when the next session starts from the same configuration, taking effect at its first tick boundary as the saved version + 1 | note `restored`, then `trial_started` or `revert_applied` |
| The session ends with a macro asked for or admitted but not in play | Dropped: the slow worker does not outlive the process | note `restored` |
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

**The shipped recordings** (2026-10-25, `export --scenario
deadly_corridor.cfg --networks best`: the run folder's `best.pt` after 7
training episodes, network share 0.43; the default 5 s budget; the slow
path on, with templates; System 2 on; the two `jev-` recordings with
`--decider jev`, otherwise the same). These five, recorded before the
senses chose the motor's targets, are 44.3 MB in all,
which is over the 25 MB a static site should carry: 17.1 MB of
`ticks.jsonl` (the six instances' verbatim evidence and answers, about
23 KB a decision), 18.1 MB of `history.jsonl` (the same decisions as
System 2's history store keeps them, which the app does not read) and
7.4 MB of frames. The text files are served compressed (a 4.5 MB
`ticks.jsonl` is 0.5 MB gzipped), so the size weighs on the repository
more than on a visit.

| Recording | Decider | Configuration | Decisions | Result | Mean tick | Calls (System 1 + System 2) | Cost (System 1 + System 2) | Misses | Size |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| `corridor-9` | d1-ultra | 1 → 1 | 59 | cleared, 6 kills (reward 2,280) | 818 ms | 354 + 86 | $0.0139 + $0.0038 | 0 | 4.3 MB |
| `jev-corridor-9` | Jev | 1 → 1 | 42 | cleared, 6 kills (reward 2,279) | 797 ms | 252 + 27 | $0.0150 + $0.0015 | 0 | 2.9 MB |
| `corridor-11` | d1-ultra | 1 → 1 | 179 | cleared, 7 kills (reward 2,277) | 796 ms | 1,074 + 139 | $0.0375 + $0.0053 | 0 | 11.7 MB |
| `jev-corridor-11` | Jev | 1 → 3 | 211 | died, 5 kills (reward 843) | 749 ms | 1,266 + 143 | $0.0641 + $0.0067 | 0 | 11.2 MB |
| `corridor-9-v2` | d1-ultra | 2 → 4 | 233 | died, 8 kills (reward 820) | 764 ms | 1,398 + 86 | $0.0448 + $0.0035 | 0 | 14.2 MB |

`episode.json`'s `cost` counts System 1's six instances and the System 2
calls made while the episode played, but not the cycle at the episode's
end; the table splits the calls by system instead (System 2's from its
`system2` counts). A tick is about 0.8 s: the five senses in parallel
take 0.49–0.56 s on average and the central 0.25–0.27 s. Every pick was
the central's top answer (exploit), no instance missed, and the slow path
was never asked for a macro. On the two cleared episodes d1-ultra mostly
chose `weave_fire` and `approach_pickup`; the resource, navigation and
goal senses spoke on almost every tick, the combat sense on a third to
a half and the survival sense rarely (4 of 59 and 29 of 179).

* **`corridor-9`** (3 cycles, 86 calls). At decision 20 System 2's
  central chose the combat auditor's `widen:combat:incoming`; the history
  test waited, with 20 stored ticks under the current scope, fewer than
  24. At decision 40 and at the episode's end it chose the same change
  and the test ran on 24 ticks: it failed at composite −0.04 (good
  agreement fell from 0.875 to 0.75, a drop of 0.12 over the 0.10 limit),
  then at +0.04, short of the 0.05 margin. The configuration stayed at
  version 1.
* **`corridor-11`** (9 cycles, 139 calls). Seven cycles had no proposal;
  at decisions 100 and 160 `widen:combat:incoming` was tested and failed
  at composite +0.00 both times, the combat sense answering alike with
  `incoming` in view. Version 1 throughout.
* **How version 2 was reached.** After `corridor-11`, two `cli` episodes
  on the same run folder (seeds 21 and 22, System 2 on, 314 decisions,
  about 4 minutes, $0.0478 and $0.0212 with both systems' calls). In the
  first, which did not clear the corridor (222 decisions, reward −116),
  System 2's central chose the strategy reflector's
  `strategy:strat_evasive_survival` (0.69) at the episode's end. It took
  effect at the second episode's first tick as version 2, and its trial
  compared 60 decisions with the 60 before: reward per decision −0.71 →
  16.13, kills 0 → 6, the paid-off rate 0.40 → 1.00. The judge kept it,
  and that episode cleared the corridor in 92 decisions.
* **`corridor-9-v2`** (10 cycles, 86 calls; System 2 restored at 493
  decisions). At decision 533 `widen:combat:incoming` failed its test
  again (composite −0.04, good agreement down 0.12). At decision 573
  System 2's central chose the strategy reflector's
  `strategy:strat_tactical_combat` (0.56); it took effect as version 3,
  and after 60 decisions the judge compared reward per decision 12.03
  before with 0.61 during (kills 3 → 1, paid-off rate 0.72 → 0.70) and
  reverted: version 4 restores version 2. Four cycles made no call,
  System 2 resting after a trial (one after the kept one, three after
  this revert). At the episode's end the same change was chosen again (0.37)
  and queued, to take effect at the next episode's first tick, so the
  recording ends at version 4. The episode died after 233 decisions.

**The senses choose the motor's targets** (2026-10-25). Seed by seed
and phase by phase, the corridor was lost in two ways: the motor aimed
and walked at targets no instance chose, and the agent kept walking at
pickups dropped in the alcoves, behind lines it cannot cross, for a
hundred decisions or more. Since then the combat and resource senses
choose the targets (§8.6, §8.7), the bridge remembers every pickup seen
with what walking at it has done (`landmarks`), and the resource sense
is shown `landmarks` alone (§8.4). With Jev deciding (d1-ultra's credit
had run out), the controller before and after, on the same seeds:

| Seeds | Controller | Cleared | Mean reward | Decisions to clear | Timeouts |
|---|---|---:|---:|---:|---:|
| 201–215 | before | 6 of 15 | 1,154 | 124 | 2 |
| 201–215 | after, without the last change (`landmarks` alone for resource) | 9 of 15 | 1,605 | 76 | 0 |
| 301–315, untouched while developing | before | 6 of 15 | 1,194 | 101 | 0 |
| 301–315, untouched while developing | after | 9 of 15 | 1,503 | 83 | 0 |

That is 18 of 30 against 12 of 30 on seeds held out from each change, a
consistent gain but not yet a statistically solid one (Fisher's exact
p ≈ 0.2). On seeds 201–215 walks at pickups that walking had already
failed to reach fell from 204 to 5 with the last change. Every loss
left on 301–315 is a death in a fight: the opening's damage at skill 5,
walking while an enemy still shoots, and the last pair's ChaingunGuy at
300–400 units, where the pistol hits on about 9% of decisions. The
benchmarks cost about $1.74 of d1-ultra and $2.92 of Jev.

**The recordings of the agent as it is now** (2026-10-26, `export
--decider jev --scenario deadly_corridor.cfg --networks best
--fresh-configuration`, seeds 9 to 12, slow path on templates, System 2
on, 5 s budget). Four seeds were fixed before recording and all four
ship. No instance missed and every tick names the motor's targets; no
walk went at a pickup walking had already failed to reach.

| Recording | Decider | Configuration | Decisions | Result | Mean tick | Calls (System 1 + System 2) | Cost (System 1 + System 2) | Misses | Size |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| `optimized-corridor-9` | Jev | 1 → 1 | 37 | died, 3 kills (reward 503) | 884 ms | 222 + 19 | $0.0161 + $0.0010 | 0 | 3.1 MB |
| `optimized-corridor-10` | Jev | 1 → 3 | 123 | died, 5 kills (reward 567) | 767 ms | 738 + 20 | $0.0518 + $0.0010 | 0 | 9.2 MB |
| `optimized-corridor-11` | Jev | 1 → 2 | 54 | died, 5 kills (reward 639) | 881 ms | 324 + 10 | $0.0247 + $0.0005 | 0 | 4.5 MB |
| `optimized-corridor-12` | Jev | 1 → 1 | 61 | cleared, 6 kills (reward 2,283) | 770 ms | 366 + 36 | $0.0252 + $0.0020 | 0 | 4.7 MB |

One of four cleared, below the 18 of 30 above: on so few seeds that is
within chance, and all three deaths were in fights. In
`optimized-corridor-10` System 2 put the agent on explore at decision 42
and after 60 decisions the judge compared reward per decision 7.07
before with 4.70 during (kills 4 → 0) and reverted it (version 3); in
`optimized-corridor-11` it did the same at decision 22 and the agent
died during the trial, at version 2.

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

**Live, Jev deciding** (2026-10-25, `export --decider jev --scenario
deadly_corridor.cfg --networks best --fresh-configuration`, seeds 9 and
11, slow path on templates, System 2 on, 5 s budget: the settings of the
shipped recordings `corridor-9` and `corridor-11`, which d1-ultra played
and which stand beside them here; all four ship, in the table above).
Calls, input tokens and cost are System 1's (six per decision); System
2's own are in the last column. Jev's usage block reports no cost, so its
cost is its input tokens at the published $0.042 per million, which is
also what d1-ultra's reported cost comes to per token.

| Recording | Decider | Decisions | Result | Mean tick (senses / central) | Calls | Misses | Input tokens | Cost | System 2 |
|---|---|---:|---|---:|---:|---:|---:|---:|---|
| `corridor-9` | d1-ultra | 59 | cleared, 6 kills, health 70 (reward 2280) | 818 ms (557 / 248) | 354 | 0 | 330,466 | $0.0139 | 3 cycles, 2 history tests, both failed; 86 calls, $0.0038 |
| `jev-corridor-9` | Jev | 42 | cleared, 6 kills, health 70 (reward 2279) | 797 ms (559 / 226) | 252 | 0 | 356,289 | $0.0150 | 3 cycles, no proposal; 27 calls, $0.0015 |
| `corridor-11` | d1-ultra | 179 | cleared, 7 kills, health 46 (reward 2277) | 796 ms (517 / 266) | 1,074 | 0 | 891,708 | $0.0375 | 9 cycles, 2 history tests, both failed; 139 calls, $0.0053 |
| `jev-corridor-11` | Jev | 211 | died, 5 kills (reward 843); ended at configuration version 3 with version 4 queued | 749 ms (500 / 237) | 1,266 | 0 | 1,525,526 | $0.0641 | 9 cycles, 1 trial, reverted; 3 history tests, 1 passed; 143 calls, $0.0067 |

Every call was answered by `jev-1.14.0`, with no miss and no retry in
1,518 System 1 calls and 170 System 2 calls. A tick takes the same
0.75–0.8 s: Jev answers the text-only senses in 300–325 ms (d1-ultra
276–398) and the central in 225–236 ms (d1-ultra 247–266), and the
combat sense, which carries the screen as a 640×480 asset, in 480–534 ms
(d1-ultra 309–311 with the 320×240 data URL), so the slowest sense sets
the tick on both. Jev counts about half as many input tokens again per
call (1,200–1,400 against 830–930 for the same evidence), and reports
output tokens (140–170 per call), which are free, so a decision costs
about $0.00033 on Jev against $0.00023 on d1-ultra.

On seed 9 Jev cleared the corridor in 42 decisions to d1-ultra's 59,
with the same six kills and the same health, choosing `approach_pickup`
23 times and `weave_fire` 15 (d1-ultra: `weave_fire` 27, `approach_pickup`
24); its survival sense spoke on 16 decisions of 42 (d1-ultra's on 4 of
59). On seed 11 the two runs parted at System 2's third cycle: on Jev
the exploration reflector proposed `level:explore` (`progress_stalled`,
0.53) beside the resource auditor's `widen:resource:threats`
(`missing_evidence`, 0.57), System 2's central chose the level (0.46,
against 0.35 for `none`), and the change took effect at decision 62 as
version 2. Under it 61 decisions were drawn instead of taken from the
top; the trial judge compared 60 decisions before and 60 during (reward
per decision 8.32 against −8.59, 5 kills against none, 43 paying off
against 17) and reverted at decision 122, to version 3. After the
cooling (three cycles in which the bounds left every reflector no
change, so none was called) the resource auditor's `widen:resource:threats`
was chosen in each of the last three cycles: the history test rejected
it twice (composite gain +0.25 with a worst metric drop of 0.25, then
+0.12 with 0.12, both over the 0.10 allowed) and passed it at the
episode's end (+0.25, worst drop 0.00), so version 4 was queued for the
next episode. The agent, with its five kills from before the trial, died
at decision 211. On d1-ultra the same seed's System 2 proposed
`widen:combat:incoming` twice and the history test failed it twice
(composite +0.00), so the agent played all 179 decisions on version 1
and cleared the corridor. One recording per seed says nothing about which
decider plays better; it says the hierarchy, System 2 included, runs
unchanged on either, at the same tick, for about 45% more per decision
on Jev, and that the two make different decisions from the same
evidence.

---

**The rule tree on the benchmark seeds** (2026-10-27, `python -m
system1_doom.ruletree eval RUN --tree general-11` and `--tree codex-11`,
seeds 201–215, 301–315 and 9–59, six games at a time; every answer from
`jev-1.14.0`, none reused from an earlier run). Each tree played every
seed once before the angle fix (commit `ae9c029`) and once after
(`4dc5d11`, which gives each enemy's and pickup's angle with atan, §8.1),
eleven minutes apart. Neither tree was written on seeds 201–315; the
soft loop trained on 9–19 and held out 20–39.

| Seeds | `general-11` before | `general-11` after | `codex-11` before | `codex-11` after |
|---|---:|---:|---:|---:|
| 201–215 | 15 of 15 | 14 of 15 | 15 of 15 | 14 of 15 |
| 301–315 | 14 of 15 | 14 of 15 | 15 of 15 | 15 of 15 |
| 9–19 (trained on) | 11 of 11 | 11 of 11 | 11 of 11 | 11 of 11 |
| 20–39 (held out) | 19 of 20 | 20 of 20 | 18 of 20 | 18 of 20 |
| 40–59 (new) | 18 of 20 | 20 of 20 | 19 of 20 | 19 of 20 |
| All | 77 of 81 | 79 of 81 | 78 of 81 | 77 of 81 |
| Decisions to clear | 44.6 | 44.6 | 46.9 | 45.8 |
| Jev calls per game | 147 | 149 | 154 | 150 |
| Cost per game | $0.0124 | $0.0125 | $0.0129 | $0.0125 |

Over the two runs `general-11` cleared 156 of 162 games and `codex-11`
155. Every loss of `general-11` was a death in the last fights (furthest
x 728–824; a cleared game ends near 1,260); `codex-11` died twice on
seed 28 at x 323, at the first pair of enemies, and stalled once, on
seed 27. `general-11`
is the default tree for that reason and for its two fewer decisions per
game; the difference in games cleared is within chance.

A decision asks Jev 3.3 questions on average (a focus question when
there is more than one item to pick from, then one question per level
of the tree and of the skill), one after another, so it takes about
1.1 s here (the median call 300 ms). It costs $0.00028. No call missed in
48,591.

**Senses and central before and after the angle fix** (2026-10-27,
`cli --scenario deadly_corridor.cfg --decider jev --episodes 1
--fresh-configuration` with the run folder's `best.pt`, 220 training
episodes; slow path and System 2 on). The two versions alternated seed
by seed, four games at a time, within ten minutes, on another machine
than the rule tree's.

| Seeds | Before the fix (`ae9c029`) | After (`4dc5d11`) |
|---|---:|---:|
| 201–215 | 10 of 15 | 11 of 15 |
| 301–315 | 10 of 15 | 11 of 15 |
| Decisions to clear | 81 | 72 |
| Mean reward | 1,682 | 1,824 |
| Cost per game (System 1 + System 2) | $0.0295 + $0.0014 | $0.0284 + $0.0014 |

The fix cleared 5 seeds the old code lost (201, 202, 203, 305, 306) and
lost 4 it cleared (210, 215, 312, 313): no measurable effect (Fisher's
exact p ≈ 0.78). The code before the fix cleared 18 of 30 on these seeds
on 2026-10-25 and 20 of 30 here, which shows how much results move from
one run to the next. The mean tick was 458–503 ms, every game loaded the value
networks and no instance missed.

**The two solutions, on the same 30 seeds.**

| | Senses and central | Rule tree, `general-11` | Rule tree, `codex-11` |
|---|---:|---:|---:|
| Cleared, before and after the fix | 20 and 22 of 30 | 29 and 28 of 30 | 30 and 29 of 30 |
| Calls per decision | 6, in parallel, and System 2's | 3.3, one after another | 3.3 |
| Cost per game | $0.030 | $0.0125 | $0.0127 |

Pooled over both versions the rule tree cleared 57 (`general-11`) and
59 (`codex-11`) of 60 against 42 of 60 (Fisher's exact p ≈ 0.0005 and
0.00002). A rule-tree decision holds its buttons for 8 tics and a senses
decision does not, so decisions to clear are not compared across the
two.

**How much Jev's answers move.** Jev is not fixed from hour to hour.
Between 07:15 and 07:25 that day `general-11` cleared 27 of 31 of seeds
9–39, with the module and with the experiment's own code alike; when the
soft loop built it, its two passes on those seeds had cleared 61 of 62
(p ≈ 0.04), and at 08:09 and 08:20 the tree cleared 30 and 31 of 31. Asked again the 519 questions of
four games, with the same text, screen and options, Jev answered 4
differently, each a near tie (an enemy 2° to the right read as "between
3 and 7 degrees"). A game is a chain of about 150 answers, and one
changed answer early on sends it elsewhere. Compare solutions within one
run, as above, not across days.

**The rule tree's recordings** (2026-10-27, `export --solution rule-tree
--tree general-11`, seeds 9 to 12, the seeds of the senses' recordings
`optimized-corridor-9` to `-12`, and `--tree codex-11` on seed 9, so the
site shows both trees and how each was written; 10 s budget). All five
ship in `web/public/episodes/`, 3.6 MB in all.

| Recording | Decisions | Result | Calls | Cost | Misses | Time per decision | Size |
|---|---:|---|---:|---:|---:|---:|---:|
| `rules-corridor-9` | 43 | cleared, 6 kills, health 70 (reward 2,279) | 143 | $0.0119 | 0 | 0.92 s | 0.74 MB |
| `rules-corridor-10` | 37 | cleared, 6 kills, health 46 (reward 2,278) | 119 | $0.0100 | 0 | 0.91 s | 0.65 MB |
| `rules-corridor-11` | 47 | cleared, 6 kills, health 100 (reward 2,280) | 166 | $0.0138 | 0 | 0.96 s | 0.80 MB |
| `rules-corridor-12` | 42 | cleared, 6 kills, health 46 (reward 2,282) | 141 | $0.0117 | 0 | 0.93 s | 0.73 MB |
| `rules-codex-corridor-9` (`codex-11`) | 43 | cleared, 6 kills, health 70 (reward 2,281) | 140 | $0.0117 | 0 | 0.92 s | 0.72 MB |

Every call was answered by `jev-1.14.0`, and no decision was marked
stalled. On the same seeds the senses' recordings cleared one of four
(seed 12, in 61 decisions).

---

**The rule tree on open-weight models** (2026-10-27, on a Jetson Thor
with 122 GB of unified memory, every model served on its GPU at
127.0.0.1). Three stand-ins for Jev, each reached with `--decider`:

- **Laya**, base: `laya` 0.4.15, the `english` checkpoint (ModernBERT-large,
  421M) at revision `7b928d8`, a window of 2,048 tokens.
- **Laya, fine-tuned on Jev's answers** (`ruletree-jev-v1`): Jev played
  `general-11` on 30 seeds never used anywhere else (400–429; it cleared
  26, answered 4,061 questions with no miss, for $0.34).
  `python -m system1_doom.ruletree.teach` wrote every question of seeds
  400–424 once, as it was sent, with Jev's probabilities as its target
  (3,212 questions); seeds 425–429 (633) were kept to check. `laya-train
  --base convaiinnovations/laya --loss soft-ce --shuffle-options --max-len
  2048` trained four epochs in 48 minutes (2,891 questions, 321 held for
  calibration). On the 633 it picked as Jev did 98.7% of the time, against
  41% before. It is served beside the base checkpoint with
  `LAYA_EXTRA_MODELS='{"ruletree-jev-v1": "<checkpoint folder>"}'` and
  asked with `--model ruletree-jev-v1`.
- **Kev-27B**, base: `jaredpalmer/kev-27b` at tag `v1.0` (a full-weight
  fine-tune of Qwen3.8-27B, 51 GB in bf16), with torch 2.14.1+cu130 (Kev
  pins torch below 2.9, which has no CUDA 13 build for the Thor's GPU, so
  it was installed with an override). As installed, `kev.serve` ran it in
  bf16 without its fused kernels (they require flash-linear-attention
  0.5.2; 0.6.0 is installed) and with PyTorch's slow causal convolution.
  `tools/kev_thor/serve_thor.py` serves it tuned for the Thor: the fused
  kernels on 0.6.0 (only a launch patch written for 0.5.2 is skipped; the
  last hidden state matched to a cosine of 0.9998), and low-precision
  projections on the Blackwell tensor cores, where bf16 multiplies reach
  about 92 TFLOPS, FP8 about 190 and NVFP4 about twice FP8 here: the MLP
  projections in NVFP4 and the others in FP8 (`KEV_QUANT=nvfp4-mlp`), 20 GB
  of weights. A question about a new state took 1,093 ms as installed and
  462 ms tuned (median), another question about the same state 339 and 151
  ms (`tools/kev_thor/README.md` has each step).

*The recorded questions.* `python -m system1_doom.ruletree.agreement`
asked each model the 709 questions Jev answered in the five recordings
above, with the same text and options. The state text settles the answer
of 561 of them:

| Question | Settled | Jev | Laya | Laya, fine-tuned | Kev-27B as installed | Kev-27B tuned | Uniform pick |
|---|---:|---:|---:|---:|---:|---:|---:|
| Root: does the threats list name an enemy? | 212 | 212 | 148 | 212 | 212 | 212 | 33% |
| Aim: which band is the focus angle in? | 158 | 157 | 57 | 158 | 158 | 157 | 14% |
| r1: is the focus far, or has firing hit nothing for 5 decisions? | 89 | 88 | 20 | 89 | 89 | 89 | 33% |
| Goal focus: which landmark is the GreenArmor? | 102 | 102 | 17 | 102 | 102 | 102 | 21% |
| All settled | 561 | 559 (99.6%) | 242 (43%) | 561 (100%) | 561 (100%) | 560 (99.8%) | 26% |
| Same pick as Jev, of all 709 | | | 322 | 698 | 699 | 697 | |
| A question (median) | | about 300 ms | 51 ms | 51 ms | 1,075 ms | 464 ms | |

Base Laya's probabilities were nearly flat (the median top probability
0.45 at the root, 0.23 in the aim skill), and its picks kept to a few
options whatever the state said: none for 147 of the 212 aim questions,
r11 for 83 of the 109 under r1. Its other setups did no better on the
561: its own 512-token window 241 (43%), the multilingual checkpoint 156
(28%), the typed-decisions checkpoint 176 (31%). The recordings were
made on seeds 9 to 12, which the fine-tuned Laya never saw. Tuned, Kev-27B
gave the same pick as installed on 706 of the 709 (FP8 alone: 707).

*Play.* `eval --tree general-11` on the 81 benchmark seeds (201–215,
301–315 and 9–59). The Laya runs played six games at a time. Kev-27B,
tuned, played four at a time with `--budget 60 --ahead`: as installed, its
calls queued behind each other on the one GPU and some reached the walk's
10 s (3 misses in about 450 calls of its first three games). Asking ahead
sends the questions about one state together (§8.17); on seeds 201 and
202, one game at a time, the games were the same decision for decision
with and without it, and a decision took 1.33 s against 1.36 s (wall
clock, the game's own work included): three questions about a new state
take 544 ms in one request against 488 ms for one, but most states here
are asked one or two questions.

| | Jev (above, two runs) | Laya | Laya, fine-tuned | Kev-27B |
|---|---:|---:|---:|---:|
| Cleared | 77 and 79 of 81 | 0 of 81 | 75 of 81 | 77 of 81 |
| 201–215 / 301–315 / 9–19 / 20–39 / 40–59 | 14–15 / 14 / 11 / 19–20 / 18–20 | 0 / 0 / 0 / 0 / 0 | 15 / 12 / 11 / 19 / 18 | 15 / 15 / 11 / 18 / 18 |
| Games not cleared | 4 and 2, deaths in the last fights | 81, all deaths | 6, deaths in the last fights (x 692–829) | 4 deaths: three in the last fights (x 698–798), one at the first pair (seed 40, x 324) |
| Decisions | 44.6 to clear (mean) | 10 before dying (median; at most 33) | 43.9 to clear (mean) | 42.6 to clear (mean) |
| Questions per decision | 3.3 | 4.1 | 3.3 | 3.3 |
| Misses | 0 | 0 | 0 | 0 |
| Cost per game | $0.0125 | $0 (this machine) | $0 (this machine) | $0 (this machine) |

The fine-tuned Laya's 75 of 81 does not differ from Jev's 156 of 162 over
its two runs beyond chance (Fisher's exact p ≈ 0.22). Jev's runs were made
earlier that day, not in the same run, and Jev's results move from run to
run (above), so the comparison is not within one run. Kev-27B, never trained on these questions, cleared 77 of 81, as many as Jev's first run (Fisher's exact p ≈ 0.74 against Jev's 156 of 162). The 81 games took 61 minutes four at a time on this PC; alone, a decision takes about 1.3 s, against about 1.1 s on Jev.

Laya's model card reports that its base checkpoints are near chance on
decision sets they were not fine-tuned for and that strong results
depend on fine-tuning; these questions ask it to read numbers from a
structured state of 350 to 750 tokens and compare them with ranges in
the options. Three thousand of Jev's answers on other seeds were enough
for this tree. A tree with conditions worded otherwise (a new rule from
the soft loop) has not been tried on the fine-tuned checkpoint, and may
need answers to its own questions.

## 16. Testing

```bash
python -m pytest                 # 252 tests, 25 files, from the repo root
python -m pytest -k "not live"   # the 245 that need no key, as CI runs them
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
ticks. `FakeD1(..., decider="jev")` answers as Jev would (the versioned
model, a usage block without cost) and records every call's URL and
headers, so the Jev tests assert that every instance's call went to
TypeSafe with the screen as an asset. The seven live tests
(`@pytest.mark.live`, named `test_live_*`) call the real APIs: four on
d1-ultra (one call, one tick with six instances, a history-test re-run on
4 stored ticks, and one System 2 cycle on a short real history), which
skip without `LIQUID_API_KEY`, and three on Jev (one call, one tick with
six instances, and 16 corridor decisions with a System 2 cycle every 8),
which skip without `TYPESAFE_API_KEY`. Tests use real ViZDoom headlessly;
the suite takes about 40 seconds without the live tests and about a
minute with them.

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
| `test_d1_client.py` | Request serialisation through an injected transport; typed misses counted per instance; `Retry-After` parsing; the default transport's typed 429; one live call; on Jev: the same request at TypeSafe with the screen as a 640×480 asset under its header, the state ending with the reference, no cost in the usage so the input tokens at the published price, each decider reading its own key, and a live Jev call; on Laya: the same request at the server on this machine with the text alone, the English checkpoint and a 2,048-token window, no key sent without one, and no cost; on Kev: the text alone at its own server as `kev-latest`, with no request fields |
| `test_controller_e2e.py` | On `basic.cfg` with the fake: six instances per tick with the payload's state equal to the evidence; a fake that shoots when aimed clears the level; a scripted outage gives missed ticks with idle steps, then `connection_lost`; isolated misses do not end the episode; every motor step follows the action's plan; the value networks learn and appear in `values`; the ledger updates and is restored; a pending configuration applies at the boundary; explore draws reproduce; an admitted macro enters at the next boundary; play needs the key; one live tick with six instances answering; the whole hierarchy on the fake Jev (24 `basic.cfg` decisions with System 2 every 8): every call of every instance, System 1's and System 2's, at TypeSafe with the Jev key, the combat sense's state its evidence plus the one asset, every other state its evidence exactly, the cost at the published price, a trial and a verdict; a controller on Jev needs `TYPESAFE_API_KEY`; live on Jev: one tick with six instances, and 16 corridor decisions with System 2 |
| `test_architecture.py` | The removed `modules.py`, `arbiter.py` and `exploration.py` are gone and nothing in `src/` or `tests/` imports them; keys are pressed only in `controller.py`, from the pick or the typed miss; only `system1.py` builds a `Pick`, and only it and `history_test.py` (the seeded sample of stored ticks) import `random`; at run time the executed action is the central's answer and a miss idles |
| `test_llm_and_admission.py` | The bounds reject before any call; the admit instance admits at its yes; a missed admit rejects; the admit evidence and its determinism; the background worker |
| `test_archive.py` | The archive holds no decision; the active strategy follows the configuration; a full archive makes room by age, never by score; outcomes update the record shown as evidence |
| `test_learning.py` | n-step returns; per-network rewards; running stats; replay round-trip; each value net learns its own signal; episode credit assignment; checkpoint round-trip, overrides and mismatch; a checkpoint with gate weights loads (synthetic, and the shipped one when present) |
| `test_training.py` | The motor executes an action's own plan; `train` writes the full run folder (with the ledger and history) and resumes; training and evaluation start from the saved configuration (evaluation with System 2 off, saving nothing) and `--fresh` forgets it; admitted macros persist and are re-validated; no exploration schedule; fail fast without the key; the idle burst |
| `test_cli.py` | Fail fast without the key; the flags reach the controller; a configuration file; System 2 runs unless `--no-system2`, its cycle in `reflections.jsonl` and the configuration saved; a second run in the same run folder starts at the saved version and restores System 2's state, and `--fresh-configuration` starts at version 1 with System 2 fresh; a change queued when a run ends takes effect at the next run's first tick boundary as the saved version + 1, its trial starting there; a configuration that does not load stops play with its remedy; `--decider jev` reaches the summary (`decider`, `models`) and every call goes to TypeSafe; `--decider jev` fails fast naming `TYPESAFE_API_KEY` |
| `test_export.py` | A `basic.cfg` bundle (schema 2) has every file and a frame per tick; pruned + legal partition the vocabulary; six instances, their evidence and the pick per tick; the history re-renders what each instance saw; the schema validates a trace, a meta, a history record and the ledger; copied run files; the index; a `connection_lost` episode is written but not shippable; a schema-1 bundle is reported; fail fast without the key; `failing_condition` agrees with `is_satisfied`; `reflections.jsonl` in every bundle, checked line by line against System 2's records and `episode.json`'s counts; `--no-system2` records none; exported episodes start from the run folder's saved configuration and carry it on, the first from version 1 with `--fresh-configuration`; a change queued at an exported episode's end takes effect at the next episode's first tick; every shipped recording in `web/public/episodes/` passes `--check`, is a schema-2 bundle played by d1-ultra or Jev and is listed in the index with its decider and whether the senses chose the motor's targets, and the site ships recordings by each decider, the newest cleared one with the senses choosing targets; a bundle whose configuration names no sense's target is indexed as recorded before the senses chose targets, after the ones since; a bundle played by the fake Jev names its decider, validates against the schema (whose `decider` enum is `d1-ultra`, `jev`) and passes `--check` |
| `test_serve.py` | Two live `basic.cfg` episodes in-process on the fake: the event order, frames on disk before their tick, the episode in progress from memory, each finished episode a valid schema-2 bundle, the next seed, the status; stopping mid-episode; clearing the live folder; a macro admitted mid-episode reaching the catalog with configuration versions 1 → 2; a slow-path answer in flight at the end logged in its own episode; the flags in the status and serving needs the key; System 2's records streamed as `reflection` events, equal to the bundle's file; `--no-system2`, `--configuration` and `--fresh-configuration`; `--decider jev` reaches the status |
| `test_ruletree_codes.py`, `test_ruletree_tree.py`, `test_ruletree_walk.py`, `test_ruletree_game.py`, `test_ruletree_check.py`, `test_ruletree_loop.py`, `test_ruletree_cli.py`, `test_ruletree_agreement.py`, `test_ruletree_teach.py`, `test_ruletree_bundle.py` | The rule tree (§8.17): codes and sequences; rules added as exceptions, groups, a rule's own focus, actions checked where they are placed, a tree folder with its cornerstones, the shipped trees; the walk on the fake Jev (none, the focus asked before the children, a skill finished by `then`, one focus option needs no question, misses, kept answers, and asking ahead: the same walk in two requests instead of four); the game on ViZDoom (8-tic decisions, a replayed prefix is the same game, deaths and stalls, true angles, the run of fruitless firing, keys pressed only in `game.py`, the same game when keys are held one tic at a time); the comparisons, and a check, gate and commit on a stand-in corridor (`tests/ruletree_fixtures.py`); the loop end to end with scripted writers and its `build.jsonl`; the command line, `--budget` and `--ahead` reaching every walk, and `eval --decider laya` and `--decider kev` with no key, every question at that model's server on this machine with the text alone; the agreement check (`test_ruletree_agreement.py`: a recording's questions rebuilt as they were sent, the answers the text settles, both models scored); training data from games (`test_ruletree_teach.py`: each question once as it was sent, the teacher's or the text's label, misses and other seeds left out); a recording of seed 9 on ViZDoom (every decision with its walk and screen, `--check` finding a changed action and a missing frame, the schema, the index listing it after the senses' recordings, the shipped rule-tree recordings) |
| `test_state_and_actions.py`, `test_features.py`, `test_simulator.py`, `test_visualizer.py` | The state, action, encoding and simulator contracts; the HUD and the panel of the six instances |

The web explainer has its own checks, run from `web/`: `npm run lint`
(oxlint), `npx prettier --check src e2e`, `npm test` (Vitest, 88 tests in
7 files), `npm run build` (type-check and bundle) and `npm run e2e`
(Playwright, 44 tests in 7 files, about 50 s with the build). Both read
`web/e2e/fixtures/episodes/fixture-corridor`, a 40-tick schema-2 bundle
the fake d1-ultra plays on the corridor (`web/scripts/record_fixture.py`
records it, without the real API), whose System 2 admits a macro
(version 2, kept) and widens the survival sense's scope to `pickups`
after a passed history test (version 3, kept); a navigation sense that
fails on its 4th call and a central that answers off the menu on its 6th
give the app a miss of each kind to show.

| File | Covers |
|---|---|
| `src/data/loader.test.ts` | The index with its configuration versions; a bundle's meta, every tick in order with its six instances, the proposals, System 2's records, the ledger and the tried counts; a schema-1 index or bundle refused with a message naming the old architecture and how to record again, and any version but 2 refused; a tick count that disagrees with the meta, unless live; frame and image references; an unlisted or missing extra file; the recording a fresh visit opens; JSONL lines |
| `src/data/readings.test.ts` | On the fixture: the strip's five sense rows and the central row (spoke, silent, missed; pick, probability, top), the Act keys, the configuration line; each instance's evidence split back into its `[channel]` sections, the survival text without `[pickups]` until version 3 and the combat text never with `[messages]`; the frame only with `frame` in scope; the answer bars; a miss's raw answer; the configuration versions placed on the ticks; System 2's cycles and their outcomes; the timeline marks; n-step returns; the ledger before and after; the values channel |
| `src/data/system2.test.ts` | A cycle's nine reflectors in call order with who proposed what, and those not called with why; the cycle a screen opens on; a cycle's trial verdict; outcomes and changes in words; the history test's ticks (bad, good, rest) with old and new answers and each metric; the configuration at start and end; the relevance points over episodes; the tried counts of this tick's situation |
| `src/data/live.test.ts`, `src/data/playback.test.ts` | Live events applied to the open episode: newer ticks only, each of System 2's records once and in order, the proposals and the catalog, the final meta; the picker's list with the live episodes; an episode in progress with no tick yet, read with the ledger it started from; the live status, and none without `serve` or from a `serve` of the old schema; the pace (8 game frames a decision, or one a second), the end's hold and the start once eight frames are ready |
| `src/content/glossary.test.ts` | Every term of §18 is in the app's glossary (as a term or alias) and every app term is in §18, at least 16; the design's words are there and the removed architecture's are not; every link names a screen and panel that exist; every `code` names a real `.py` under `src/system1_doom/` and a symbol defined in it; unique ids and aliases, none one letter or a bare “gate”; only the n-step return and the history test explain with a formula; linked words are whole words, longest first, once each |
| `src/data/rules.test.ts` | On the shipped rule-tree recordings: a recording's decisions in order, its tree and record; a decision count that disagrees with `episode.json`, or a senses recording, refused; the text each question was sent (the state text, the `[focus]` line after a focus, none for a skill step); actions in words; every walk counted at the root and each decision once where it ended; both formats of `build.jsonl` (outcomes, a stopped check, a round played again, the held-out runs); the default tree's recording opened first |
| `e2e/watch.spec.ts` | On the fixture: a fresh visit lands on Watch and plays within 1.5 s; pausing holds the decision in the address; no sideways scroll at 390 px |
| `e2e/instances.spec.ts` | The strip shows five senses and the central, with spoke, silent or missed and the pick; a central miss; the configuration line moving to version 2; a click on a row opens that instance; the survival evidence is verbatim with no `[pickups]` and the combat evidence has no `[messages]`, both equal to `ticks.jsonl`; the frame; the miss's reason and raw answer; the answers as bars |
| `e2e/screens.spec.ts` | The slow system's version timeline, the history test's table (12 ticks, the metrics, the verdict), the trial and the judge's evidence, a sampled tick opening The instances, a cycle's reflectors and their evidence, the ledger; Learning's chart and tables; Growing the menu's proposal, stages and admit instance; Reference's rule, drawing, glossary and provenance; a linked word opening its entry; no sideways scroll at 390 px on any screen; the top bar on one row at 1280 px |
| `e2e/live.spec.ts` | Against the live stand-in: Watch follows schema-2 ticks as they arrive; The slow system fills in from `reflection` events (cycles, versions 2 and 3, the history test); The instances follows the newest tick |
| `e2e/recordings.spec.ts` | Against the built site with the shipped recordings: the landing plays the newest cleared one, and the cards mark the ones recorded before the senses chose targets; on it, Act names the motor's targets and the combat sense shows its target answer; every recording opens on every screen without an error and with no sideways scroll at 390 px; the top bar on one row at 1280 px |
| `e2e/solutions.spec.ts` | Against the shipped recordings: the side tab switches solution at the same screen position, to the recording of the same seed, and Back crosses between them; the picker lists only the shown solution's recordings; the choice is remembered, and links to either solution still open it; the rule tree's top bar on one row at 1280 px beside the side tab, and the side tab above it at 390 px |
| `e2e/rules.spec.ts` | Against the shipped recordings: Watch's rows, picks, skills and action equal `decisions.jsonl`; a row opens its question; the text of every question on The questions equals the text rebuilt from `decisions.jsonl`, character for character (every decision of one recording, every seventh of the others); a rule added by the soft loop links to the tree and back; Results' counts add up to the decisions; The rule tree marks the walk; Reference's drawing, glossary and provenance; every screen of every recording without an error or sideways scroll at 390 px |

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

The web app's glossary (`web/src/content/glossary.ts`, on its Reference
screen) carries every term below in its own words, with where to see it
and the code that keeps it, and a test reads this table: a term added
here fails the app's tests until the glossary has it. The terms after
**Slow path** are the rule tree's (§8.17); Jev, channel, miss and bundle
are used by both solutions, and the glossary gives each its rule-tree
meaning beside the senses and central's. The words of the
architecture this design replaced (the arbiter, the modules, the gate
network, budget modes, committed picks, exploration pressure) are gone
from both; the Reference screen names them in one line of history.

| Term | Meaning |
|---|---|
| **d1-ultra** | Liquid AI's decision model; answers typed `choice`/`noul`/`score` questions with distributions. Every decision is one of its answers: the five senses, the central and the admit instance are each one call (§8.6, §8.10), and so are System 2's reflectors, its central and the trial judge (§8.16). |
| **Jev** | TypeSafe's decision model, which answers the same typed questions in the same form at `api.typesafe.ai`; with `--decider jev` every instance of both systems calls it instead of d1-ultra, with the same evidence and questions (§8.10). The screen goes to it as an image asset, and its cost is counted at its published price per input token, since its usage block names none. Six of the shipped senses-and-central recordings were played by it (§15), and every rule-tree recording: each question of a walk is one call. |
| **System 1** | The fast system that decides every action, once per tick: five senses, then the central, then Act (`system1.py`, §7, §8.7). It never waits for System 2. |
| **System 2** | The slow system, on its own thread: it reads the history and changes the configuration one change at a time — reflectors propose, its central chooses one change or none, a scope change must pass the history test, and every change is a trial the judge keeps or reverts (§8.16). |
| **Instance** | One d1-ultra call with its own scope and its own finite questions (`InstanceSpec`, `run_instance`). Its instructions name its concern and say it sees only the evidence given; they never say how to weigh anything (§8.6). |
| **Sense** | One of the five System 1 instances — survival, combat, navigation, resource, goal. Each sees only its scope and answers `speak` (noul), `action` (a choice over the legal menu) and `reason` (a choice over its reasons) (§8.6). |
| **Central** | The instance that chooses the executed action: one choice over the legal menu, after the messages, each sense's relevance record and the exploration level (§8.7). System 2 has a central of its own, which chooses one configuration change or none. |
| **Channel** | One named piece of evidence rendered as plain text under a `[name]` header; eighteen in all, in a fixed order. `messages`, `relevance` and `exploration` are for the central only (§8.5). The rule tree's state has its own eleven, `goal` to `history`, and `[focus]` after a focus question (`ruletree/game.py`). |
| **Scope** | The channels an instance is shown: at most 7, always with `menu`. Whatever a scope leaves out never reaches the instance; System 2 widens or narrows a scope one channel at a time (§8.4, §8.16). |
| **Message** | What a sense that spoke sends the central: action, reason, strength — one line of the central's `messages` channel. A silent or missed sense sends nothing (§8.6). |
| **Target** | What the motor aims or walks at, chosen by a sense: the combat sense's `target` answer is the visible enemy the aim locks onto, the resource sense's the remembered pickup a pickup-seeking action walks to (`system1.targets_of`, §8.7). With one candidate no question is asked and that one is the target; a sense that missed leaves its target empty, and the motor never picks one of its own. |
| **Strength** | A message's strength: the sense's `speak` probability, unscaled. A sense speaks at `yes_at` (0.5), d1's own yes, not a tuned threshold (§8.6). |
| **Relevance / relevance ledger** | Each sense's track record per context signature: spoke, followed and paid off, overruled and whether the chosen action paid off, mean strength either way. Shown to the central as counts; nothing in it is multiplied into a decision (`relevance.py`, §8.8). |
| **Paid off / n-step return** | A decision paid off when its n-step return (n = 8, γ = 0.9, over the per-decision game reward, truncated at the episode's end; `features.n_step_returns`) was positive. The ledger, the history test's strata and the trials all read it (§8.8). |
| **Configuration** | Everything System 2 may change, as versioned data: scopes, the exploration level, the active strategy, the admitted macros, and the bounds. Version 1 is the design's; each change makes the next version and takes effect only at a tick boundary (§8.4). |
| **Miss** | An answer that did not come or could not be read: timeout, error, HTTP 429 past the budget, off the menu, malformed. Nothing stands in for it: a missed sense is silent, a missed central holds no keys (§8.6, §14). In the rule tree the walk stops at the node it has reached and plays that node's action (§8.17). |
| **Pick** | How the central's answer becomes the action: `top` under `exploit`, `drawn` from d1's own distribution under `explore` (seeded), or `missed` (`system1.pick_action`, §8.7). |
| **Exploration level** | Configuration: `exploit` or `explore`, stated to the central in its `exploration` channel. There is no temperature and no bonus (§8.7). |
| **Reflector** | One of System 2's nine instances — five sense auditors, a central auditor, the menu, strategy and exploration reflectors — each reading history channels over three windows and proposing at most one change from a menu the bounds have filtered (`reflectors.py`, §8.16). |
| **Cycle** | One round of System 2: every 20 new decisions or at an episode's end, only while no trial is in flight. Its record (`ReflectionTrace`) keeps every reflector's and its central's evidence and answers (§8.16). |
| **History test** | What stands between a scope change and play: the instance asked again under the new scope on stored ticks it already answered, stratified into bad, good and rest by the n-step return; it passes when the composite gains at least 0.05 and no metric falls by more than 0.10 (`history_test.py`, §8.16). |
| **Trial** | Every change that takes effect, one at a time: observed for 60 decisions against the 60 before it, then kept or reverted; a revert restores the previous configuration with the version bumped (§8.16). |
| **Judge / trial judge** | The instance that ends a trial: shown the before-and-during table, it answers `keep` or `revert`. A missed judge extends the trial; the safety bound may revert first without asking it (§8.16). |
| **Cooling** | The rest after a verdict: the changed instance is offered no change for 60 decisions; after a menu, strategy or level change, System 2 as a whole rests (§8.16). |
| **Admit instance** | The instance that decides whether a proposed macro enters the menu, after parse, legality and the sandbox: one noul, yes at 0.5 (`instance.run_admit`, §8.12). |
| **Action / `ActionSpec`** | The only executable unit: a bounded tuple of primitives with preconditions, a duration cap and a termination condition. Primitives are 1-step actions; macros are named multi-step ones. The legal menu of a tick is the set of actions whose preconditions hold. |
| **Macro** | Multi-primitive `ActionSpec` (`is_macro=True`); built-in, or proposed by the slow path when System 2 asks and admitted by the admit instance into the configuration. |
| **Context signature** | Coarse bucketed state key (`hp:…\|ammo:…\|enemies:…`) that keys the relevance ledger, the novelty counts, the simulator's empirical cache and the value networks' tried counts (§6.1). |
| **Projection** | A bounded analytic rollout (`ProjectedOutcome`) of one legal action: expected value, damage, resources, survival. Shown to instances as the `projections` channel, labelled as a rough projection. |
| **Value network** | One of five small networks trained between episodes on the agent's own play, one per sense's reward. Their predicted returns are evidence in the `values` channel, with how often each action was tried there in training; they decide nothing (`learning.py`, §8.9). |
| **Network share** | Experience-weighted mean of `n/(n+25)` over the tries seen in training: how familiar play has become to the value networks. A report only; it weighs nothing. |
| **Tick** | One decision: state → evidence → five senses → central → the action's primitives over ≈ 8 game tics, not one ViZDoom game tic. |
| **Bundle** | One recorded episode as the web app reads it: `episode.json`, `ticks.jsonl`, `reflections.jsonl`, `proposals.jsonl`, the relevance ledger, the training counts and the frames, written and checked by `python -m system1_doom.export` (§8.15). A rule-tree bundle holds `episode.json`, `decisions.jsonl` (every walk, question by question), `tree.json` with its cornerstones, `build.jsonl` and the frames (`export --solution rule-tree`, §8.17). |
| **Live episode** | An episode being played right now by `python -m system1_doom.serve` and streamed tick by tick, with System 2's records as they happen; when it ends it is a bundle like any recording (§8.15). |
| **Slow path** | The async proposal worker (Codex or templates) and the admission bounds and admit instance that can grow the menu, asked by System 2's menu reflector; never blocks a tick, and changes the configuration only at a tick boundary (§9). |
| **Rule tree** | The second solution: a tree of rules Jev walks at every decision (`ruletree/`, §8.17). A tree is a file: rules, focus questions, skills, and each added rule's cornerstone. |
| **Rule** | A node of the tree: a condition and an action. A rule under another is an exception to it; the walk goes into it when Jev picks its condition (`RuleNode`). |
| **Condition** | A rule's sentence about what the state shows ("The focus channel says the enemy is more than 400 units away."), offered to Jev as one option of a choice; the program never tests it. |
| **Walk** | One decision of the rule tree: from the root, "Which of these is true right now?" at each node with children, into the child Jev picks, until it picks `none` or reaches a leaf; that node's action plays (`walk.decide`). |
| **Focus** | One listed item Jev picked at a node with a focus question (the biggest danger among the threats, the goal among the landmarks); later questions read it as a `[focus]` channel (`walk.with_focus`). |
| **Skill** | A set of rules any rule can call as its action, with a `then` code that finishes the decision; the shipped trees have one, `aim` (`SkillCall`). |
| **Action code** | Four letters, walk/sidestep/turn/fire (`F001` walks forward and fires), held for the decision's 8 tics, or a sequence such as `00R0:3+0001:5` (`ruletree/codes.py`). |
| **Tic** | One step of the game clock, 1/35 s. A rule-tree decision is 8 tics; a senses-and-central tick holds its action for about as long. |
| **Soft loop** | How a tree's rules are written between games: play the training seeds, have a rule writer propose a rule for a failure, check it on that game (sees, unchanged, avoids), gate it on every training seed, and add it only if it passes both (`ruletree/loop.py`). |
| **Rule writer** | The model that proposes rules in the soft loop, Codex or Claude, from a dossier of the failed game (`ruletree/writers.py`). It never plays; Jev judges every condition. |
| **Cornerstone** | The decision a rule was written for, kept with it: seed, prefix of actions, state text, screen, expected route and standing. Later rules must keep it on its route or end no worse (`Cornerstone`). |
| **Seed** | A number that sets the game's random events, so each seed is a different game (`ruletree/game.py`, `Game.reset`). A recording is one game on one seed. |
| **Training seed** | A seed the soft loop plays and writes rules for: 9–19 for the shipped trees. A rule's gate counts training seeds cleared with and without it. |
| **Held-out seed** | A seed the soft loop writes no rule for: 20–39 for the shipped trees, played after every training seed clears, and 40–59, never played while they were written. |

---

*Maintainers: when a channel, bound, question or file format changes,
update the matching section here and the design in
`docs/superpowers/specs/`. The spec (`docs/spec.md`) states the original
intent; this document states behaviour; the code is the truth when they
disagree.*
