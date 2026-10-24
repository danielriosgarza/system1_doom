# Doom Decision Controller (Liquid AI d1-ultra) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the bounded Doom Decision Controller defined in `docs/spec.md` using Liquid AI's `d1-ultra` decision model (`POST https://api.liquid.ai/decisions/v1/systemone`) for structured System-1 module/arbiter/exploration/admission decisions and OpenAI Codex CLI (`codex exec`) for the asynchronous slow-path macro-action proposal worker.

**Architecture:** Every control tick constructs an immutable `WorldState` snapshot `S_t` and evaluates a finite set of candidate actions (primitives + admitted bounded macro-actions) across 5 independent decision modules (`Survival`, `Combat`, `Navigation`, `Resource`, `Goal`), a bounded short-horizon simulator, an explicit `ExplorationController` + `StrategyArchive`, and a `FinalArbiter`. Decisions are powered by `d1-ultra` (supporting both synchronous step-by-step `d1-ultra` evaluation and non-blocking async background `d1-ultra` refresh with bounded local fallback so real-time ticks never block on network I/O). An asynchronous `SlowLLMWorker` invokes `codex exec` when modules emit `request_action_expansion = True`, and all proposals must pass a deterministic + `d1-ultra` admission gate before entering the active action vocabulary.

**Tech Stack:** Python 3.11+, ViZDoom 1.3+, Liquid AI `d1-ultra` REST API (`/decisions/v1/systemone`), Pydantic v2, NumPy, Pillow, OpenAI Codex CLI (`codex exec`), Pytest.

## Global Constraints

- Everything that can affect behavior must terminate in a finite decision over a finite set (`state -> candidate set -> decision -> selected candidate`).
- Fast path must never block on an LLM, unbounded search, or expensive planning; in real-time mode, network I/O runs asynchronously and the controller degrades gracefully (`full budget -> reduced budget -> critical budget`).
- World state `S_t` must be immutable within one control tick.
- Every action (primitive or macro-action) must define `id`, `parameters`, `preconditions`, `maximum_duration`, `termination_condition`, and `primitive_expansion` reducing to a finite sequence of primitive actions.
- All 5 modules (`Survival`, `Combat`, `Navigation`, `Resource`, `Goal`) implement the standard `DecisionInput -> DecisionOutput` contract and never execute actions directly.
- Bounded projections enforce explicit `max_candidate_count`, `max_simulation_depth`, `max_wall_clock_budget`, and `max_branching_factor`.
- Slow LLM worker (`codex exec`) only proposes candidate macro-actions/strategies asynchronously; every proposal passes deterministic schema/primitive/finiteness/bounds validation + optional sandbox + `d1-ultra` admission gate before entering the candidate space.
- Every tick and every LLM proposal produces a structured JSONL decision trace.

---

### Task 1: World State (`S_t`) and Finite Action Model

**Files:**
- Create: `src/system1_doom/__init__.py`
- Create: `src/system1_doom/state.py`
- Create: `src/system1_doom/actions.py`
- Test: `tests/test_state_and_actions.py`

**Interfaces:**
- Produces: `EnemyObservation`, `PickupObservation`, `Observation`, `ControllerMemory`, `WorldState`, `PrimitiveActionId`, `ActionSpec`, `ActionVocabulary`, `DEFAULT_PRIMITIVES`, `DEFAULT_MACROS`.

- [x] **Step 1: Write failing tests for immutable `WorldState` and finite `ActionSpec` expansion/validation**
- [x] **Step 2: Run pytest to verify failure**
- [x] **Step 3: Implement `state.py` and `actions.py`**
- [x] **Step 4: Run pytest to verify pass**

---

### Task 2: Liquid AI `d1-ultra` Decision Client

**Files:**
- Create: `src/system1_doom/d1_client.py`
- Test: `tests/test_d1_client.py`

**Interfaces:**
- Consumes: `WorldState` from `state.py`
- Produces: `NoulQuestion`, `ChoiceQuestion`, `ScoreQuestion`, `NoulAnswer`, `ChoiceAnswer`, `ScoreAnswer`, `D1Response`, `D1UltraClient` (supports multi-question batching in a single `/decisions/v1/systemone` request, optional JPEG frame encoding, strict timeouts, and background cache refresh).

- [x] **Step 1: Write failing unit and live integration tests for `D1UltraClient`**
- [x] **Step 2: Run pytest to verify failure**
- [x] **Step 3: Implement `d1_client.py`**
- [x] **Step 4: Run pytest to verify pass**

---

### Task 3: Bounded Projection / Simulator

**Files:**
- Create: `src/system1_doom/simulator.py`
- Test: `tests/test_simulator.py`

**Interfaces:**
- Consumes: `WorldState`, `ActionSpec`
- Produces: `ProjectionLimits`, `ProjectedOutcome`, `BoundedSimulator` enforcing `max_candidate_count`, `max_simulation_depth`, `max_wall_clock_budget`, and `max_branching_factor`.

- [x] **Step 1: Write failing tests for bounded simulator limits and kinematic/combat state transitions**
- [x] **Step 2: Run pytest to verify failure**
- [x] **Step 3: Implement `simulator.py`**
- [x] **Step 4: Run pytest to verify pass**

---

### Task 4: Standard Decision Module Contract & 5 Modules (`Survival`, `Combat`, `Navigation`, `Resource`, `Goal`)

**Files:**
- Create: `src/system1_doom/modules.py`
- Test: `tests/test_modules.py`

**Interfaces:**
- Consumes: `WorldState`, `ActionSpec`, `ProjectedOutcome`, `D1UltraClient`
- Produces: `DecisionInput`, `DecisionOutput`, `DecisionModule`, `SurvivalModule`, `CombatModule`, `NavigationModule`, `ResourceModule`, `GoalModule`, `BatchModuleEvaluator` (evaluates all 5 modules in parallel or batched `d1-ultra` call with local heuristic reflex fallback when budget is critical or API is disabled).

- [x] **Step 1: Write failing tests for all 5 modules, time budgets, and `d1-ultra` + fallback evaluation**
- [x] **Step 2: Run pytest to verify failure**
- [x] **Step 3: Implement `modules.py`**
- [x] **Step 4: Run pytest to verify pass**

---

### Task 5: Exploration Controller and Strategy Archive

**Files:**
- Create: `src/system1_doom/exploration.py`
- Create: `src/system1_doom/archive.py`
- Test: `tests/test_exploration_and_archive.py`

**Interfaces:**
- Consumes: `WorldState`, `ActionSpec`, `D1UltraClient`
- Produces: `ExplorationState`, `ExplorationDecision`, `ExplorationController`, `StrategyEntry`, `StrategyDecisionChoice`, `StrategyArchive`.

- [x] **Step 1: Write failing tests for exploration state transitions, temperature control, and strategy archive switching**
- [x] **Step 2: Run pytest to verify failure**
- [x] **Step 3: Implement `exploration.py` and `archive.py`**
- [x] **Step 4: Run pytest to verify pass**

---

### Task 6: Final Arbiter

**Files:**
- Create: `src/system1_doom/arbiter.py`
- Test: `tests/test_arbiter.py`

**Interfaces:**
- Consumes: `WorldState`, `DecisionOutput`, `ProjectedOutcome`, `ExplorationState`, `StrategyEntry`, `D1UltraClient`
- Produces: `ArbiterDecision`, `FinalArbiter` combining expected value, exploration bonus, novelty bonus, risk penalty, execution cost, and `d1-ultra` arbitration probability distribution.

- [x] **Step 1: Write failing tests for `FinalArbiter` scoring, distribution normalization, and action selection**
- [x] **Step 2: Run pytest to verify failure**
- [x] **Step 3: Implement `arbiter.py`**
- [x] **Step 4: Run pytest to verify pass**

---

### Task 7: Slow LLM Worker (`codex exec`) and Proposal Admission Pipeline

**Files:**
- Create: `src/system1_doom/llm_worker.py`
- Create: `src/system1_doom/admission.py`
- Test: `tests/test_llm_and_admission.py`

**Interfaces:**
- Consumes: `ActionSpec`, `PrimitiveActionId`, `BoundedSimulator`, `D1UltraClient`
- Produces: `ExpansionRequest`, `MacroActionProposal`, `ValidationResult`, `ProposalAdmissionPipeline`, `SlowLLMWorker` (asynchronous background queue calling `codex exec` with JSON schema + deterministic fallback).

- [x] **Step 1: Write failing tests for illegal primitive rejection, unbounded duration rejection, sandbox evaluation, `d1-ultra` admission gate, and async `SlowLLMWorker`**
- [x] **Step 2: Run pytest to verify failure**
- [x] **Step 3: Implement `admission.py` and `llm_worker.py`**
- [x] **Step 4: Run pytest to verify pass**

---

### Task 8: Decision Logger, Timing/Concurrency Controller, and ViZDoom Environment

**Files:**
- Create: `src/system1_doom/logger.py`
- Create: `src/system1_doom/vizdoom_env.py`
- Create: `src/system1_doom/controller.py`
- Create: `src/system1_doom/cli.py`
- Test: `tests/test_controller_e2e.py`

**Interfaces:**
- Consumes: All earlier modules
- Produces: `TickTrace`, `ProposalTrace`, `DecisionLogger`, `ViZDoomBridge`, `ControllerConfig`, `DoomDecisionController` supporting both `async_cached` (non-blocking real-time loop with background `d1-ultra` worker) and `sync_d1` (step-by-step live `d1-ultra` decisions) modes, plus graceful budget degradation (`full`, `reduced`, `critical`).

- [x] **Step 1: Write failing end-to-end tests covering all Section 20 acceptance criteria**
- [x] **Step 2: Run pytest to verify failure**
- [x] **Step 3: Implement `logger.py`, `vizdoom_env.py`, `controller.py`, and `cli.py`**
- [x] **Step 4: Run full test suite and live ViZDoom + `d1-ultra` + `codex` verification**
