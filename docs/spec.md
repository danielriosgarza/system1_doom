# Doom Decision Controller — Implementation Spec

> **Status (2026-10-25).** This is the original spec, kept as the statement of intent. Its §21
> invariant holds unchanged. Since [the d1-ultra design](superpowers/specs/2026-10-25-d1-decision-maker-design.md), every decision is made by a d1-ultra instance, and the
> parts below that weighed, scored or picked an action by hand (the module heuristics, the final
> arbiter's score, the exploration formula, the strategy meta-decision, the admission thresholds) are
> removed. Notes like this one mark each section the design changed; `DOCUMENTATION.md` describes the code.

## 1. Objective

Build an intelligent Doom controller in which **all control logic is expressed as explicit, bounded decisions**.

The controller should:

- run inside a fast real-time game loop;
- decompose behavior into independent decision modules;
- allow bounded simulation/projection of candidate actions;
- combine module outputs through another explicit decision;
- explore systematically rather than relying only on greedy choices;
- use a traditional LLM only on a slow asynchronous path to propose new actions, abstractions, or strategies;
- never require an LLM call for the real-time loop to continue.

The initial target environment should be ViZDoom or an equivalent Doom API that exposes observations and accepts discrete actions.

---

## 2. Core Principle

Everything that can affect behavior must terminate in a finite decision over a finite set.

Conceptually:

```text
state -> candidate set -> decision -> selected candidate
```

This applies recursively to:

- primitive actions;
- tactical choices;
- module outputs;
- arbitration between modules;
- exploration vs exploitation;
- requests for simulation;
- requests to expand the action space;
- adoption or rejection of LLM-generated proposals.

No component may contain an unrestricted reasoning loop that directly controls the game.

---

## 3. Runtime Architecture

> **Now:** the five boxes are d1-ultra *senses*, each seeing only its scope of evidence and deciding
> whether to send a message; the Final Arbiter and Action Selector are one *central* d1-ultra
> instance that hears the messages and chooses the action. The fast path waits for d1-ultra inside a
> per-call budget instead of never calling a model; a missed answer is recorded, never filled in.

```text
                         +---------------------+
                         |   Slow LLM Worker   |
                         | action/strategy     |
                         | proposal generation |
                         +----------+----------+
                                    |
                                    v
                           proposal validation
                                    |
                                    v
+---------+    +-----------------------------------------------+
|  Doom   | -> |                  World State                  |
+---------+    +-----------------------------------------------+
                                    |
              +---------------------+---------------------+
              |          |          |          |          |
              v          v          v          v          v
          Survival    Combat    Navigation   Resource    Goal
              |          |          |          |          |
              +----------+----------+----------+----------+
                                    |
                              module proposals
                                    |
                                    v
                              Final Arbiter
                                    |
                                    v
                              Action Selector
                                    |
                                    v
                                  Doom
```

There are two execution paths:

### Fast path

Runs every game tick or control tick.

It must never block on:

- an LLM;
- network I/O;
- expensive planning;
- unbounded search.

### Slow path

Runs asynchronously and may take seconds.

It may:

- propose new macro-actions;
- propose new tactical abstractions;
- propose changes to candidate sets;
- propose strategy templates.

Its output is advisory until validated and admitted into the controller's finite action vocabulary.

---

## 4. World State

The controller maintains a normalized state object `S_t`.

Minimum contents:

```text
observation
- current visual frame or extracted visual features
- player health
- armor
- ammo
- current weapon
- visible enemies
- visible pickups
- recent incoming damage
- recent outgoing damage
- recent kills
- movement state
- recent actions
- estimated position/orientation if available
- episode progress indicators

memory
- short action history
- recent state summaries
- discovered locations / objects
- strategy archive references
```

The world state should be immutable within one control tick.

Modules receive the same snapshot so their decisions can be compared consistently.

---

## 5. Action Model

Actions exist at multiple levels.

### Primitive actions

Examples:

```text
move_forward
move_backward
strafe_left
strafe_right
turn_left
turn_right
shoot
use
switch_weapon_X
```

### Macro-actions

A macro-action is a finite, executable procedure composed from primitive actions.

Examples:

```text
circle_strafe_left(target, duration)
retreat_to_cover(direction, duration)
approach_pickup(pickup_id, duration)
peek_and_fire(direction, burst_length)
```

Every action must define:

```text
id
parameters
preconditions
maximum duration
termination condition
primitive expansion
```

An action that cannot be reduced to a bounded executable procedure is invalid.

---

## 6. Standard Decision Module Contract

> **Now:** the contract is the instance: one d1-ultra call whose state is its scope's rendered
> evidence and whose questions are finite (`speak`, `action` over the legal menu, `reason` for a
> sense; `choose` over the menu for the central). `DecisionInput`/`DecisionOutput` are gone with
> `modules.py`.

All decision modules follow the same interface.

### Input

```text
DecisionInput
- world_state
- available_actions
- local_memory
- optional bounded projections
- time_budget
```

### Output

```text
DecisionOutput
- ranked candidate actions or probability distribution
- utility estimates
- uncertainty/confidence
- optional projected outcomes
- optional request for additional simulation
- optional request to expand the action space
- optional local-memory update
```

A module does not execute an action directly.

It only produces a decision over candidates.

---

## 7. Initial Modules

> **Now:** the same five questions are the five senses' concerns; no sense has a hand-written
> heuristic. What each one sees is its scope in the configuration.

The first implementation should use five modules.

### Survival

Question:

> Which available action best reduces near-term probability of death?

Signals may include:

- health;
- recent damage;
- enemy proximity;
- projectile risk;
- escape routes.

### Combat

Question:

> Which available combat action best improves the current fight?

Signals may include:

- target visibility;
- weapon suitability;
- ammo;
- expected damage;
- exposure.

### Navigation

Question:

> Which movement action best improves positional progress?

### Resource

Question:

> Which action best improves resource state without unacceptable risk?

### Goal

Question:

> Which action or projected state most increases probability of eventual level success?

This module provides the closest thing to a global value signal.

---

## 8. Bounded Projection / Simulation

Modules may request short projections of candidate actions.

A projection must always have explicit limits:

```text
max candidate count
max simulation depth
max wall-clock budget
max branching factor
```

Conceptually:

```text
(S_t, action) -> projected_state_1 ... projected_state_k
```

The simulator may initially be simple and approximate.

Examples:

- deterministic movement approximation;
- learned next-state predictor;
- short rollouts against scripted enemy assumptions;
- cached empirical transition outcomes.

The purpose is not perfect world simulation. It is to provide enough short-horizon evidence for better decisions.

---

## 9. Final Arbiter

> **Now:** removed. The central d1-ultra instance outputs the one finite decision over the legal
> menu; there is no hand-written score, bonus, penalty or temperature.

The arbiter receives:

```text
world state
module proposals
module confidence/uncertainty
projected outcomes
current exploration state
```

It outputs one finite decision over currently valid actions.

Example conceptual score:

```text
score(action) =
    expected_value
  + exploration_bonus
  + novelty_bonus
  - risk_penalty
  - execution_cost
```

The arbiter itself must be implemented as a bounded decision model, not hand-written open-ended reasoning.

---

## 10. Exploration

> **Now:** the pressure formula and sampler temperature are removed. Exploration is one explicit
> variable in the configuration, the level `exploit` or `explore`; under `explore` the central's
> action is drawn from d1-ultra's own distribution with a seeded generator. Visit counts remain, as
> the `novelty` evidence channel. Deciding the level belongs to System 2 in the design.

Exploration should be explicit and state-dependent.

Maintain an exploration state containing at least:

```text
recent progress
recent failures
state visitation novelty
strategy usage frequency
uncertainty estimates
performance plateau signal
```

Exploration pressure increases when:

- progress stalls;
- uncertainty is high;
- the same strategies repeatedly fail;
- unfamiliar states are encountered.

Exploration pressure decreases when:

- a strategy is producing reliable progress;
- the controller is in a high-risk state;
- a near-term winning sequence is identified.

Temperature may be used by the final action sampler, but it should be controlled by the exploration decision rather than be fixed globally.

---

## 11. Strategy Archive

> **Now:** the archive stays, as evidence (the `archive` channel). The four-way strategy decision
> below is removed; which strategy is active is part of the configuration, for System 2 to decide.

Maintain a bounded archive of distinct strategies or macro-action patterns.

Each entry may contain:

```text
strategy_id
context signature
macro/action sequence
observed reward
success rate
failure modes
usage count
novelty signature
```

The archive exists to prevent the controller from collapsing permanently into one local optimum.

The controller may explicitly decide to:

```text
continue current strategy
switch to archived strategy
explore variation
request new strategy proposal
```

---

## 12. LLM Slow Path

> **Now:** decision modules no longer emit expansion requests. The controller's
> `request_expansion` is the entry point; in the design, System 2's menu reflector decides when a
> new move is needed.

The LLM is never part of the synchronous control loop.

A decision module may emit:

```text
request_action_expansion = true
```

with a bounded description of the problem.

Examples:

```text
"Existing combat macros repeatedly fail against this enemy configuration."

"Current navigation actions cannot reliably cross this obstacle."
```

The request enters an asynchronous queue.

The LLM may return candidate:

- macro-actions;
- tactical strategies;
- parameterized action templates;
- new state abstractions.

The LLM must not return the next real-time game action.

---

## 13. LLM Proposal Admission

> **Now:** parse, legality and the sandbox stay as bounds; the decision to admit is an admit
> instance's d1-ultra yes or no, with no thresholds of the code's own. An admitted macro joins the
> configuration at the next tick boundary.

Every LLM proposal passes through a deterministic/decidable admission pipeline.

```text
LLM proposal
    -> parse into typed schema
    -> verify referenced primitives exist
    -> verify finite execution
    -> verify resource/time bounds
    -> reject illegal game actions
    -> optional sandbox evaluation
    -> decision: admit / reject
```

Only admitted proposals enter the active candidate space.

No free-form text reaches the executor.

---

## 14. Timing Model

> **Now:** there are no budget tiers and no cached or reactive decisions. Each d1-ultra call has a
> per-call budget (5 s by default); a sense that misses it is silent, a central that misses it holds
> no keys for the decision's frames, and three central misses in a row end the episode as
> `connection_lost`.

The real-time controller must be designed around strict budgets.

Example target structure:

```text
control tick
- acquire state
- update lightweight features
- run modules in parallel
- perform bounded projections if budget allows
- arbitrate
- execute action
```

The system should degrade gracefully under load:

```text
full budget      -> modules + projections
reduced budget   -> modules without some projections
critical budget  -> cached/reactive decisions
```

An unavailable slow-path result must have zero impact on the ability to continue playing.

---

## 15. Concurrency

> **Now:** the five senses are parallel d1-ultra calls over the same snapshot, on a pool of six with
> the central; late answers are misses, never cached for later use. The slow path has its own pool.

The implementation should treat modules as independent workers over the same state snapshot.

Recommended structure:

```text
Game Thread
- state acquisition
- deadline management
- arbitration
- action execution

Module Workers
- survival
- combat
- navigation
- resource
- goal

Background Workers
- projection/model updates
- strategy archive maintenance
- LLM requests
- LLM proposal validation/testing
```

The arbiter uses only module results received before the tick deadline.

Late results are discarded or cached for later use.

---

## 16. Learning

> **Now:** the five value networks keep learning between episodes, and their predictions are shown to
> the instances as the `values` channel; a relevance ledger keeps each sense's track record as the
> `relevance` channel. Nothing learned is multiplied into a decision.

The architecture should allow modules to improve independently.

A module may be implemented using:

- a System-1 style decision model;
- a small neural policy/classifier;
- a learned value function;
- a calibrated probabilistic model;
- a fixed heuristic during early prototyping.

The architectural requirement is the interface, not the initial model family.

All learned outputs should ultimately be converted into finite decisions or probability distributions over finite candidates.

---

## 17. Logging

> **Now:** the per-tick trace (schema version 2) records, for each of the six instances, its scope,
> the verbatim evidence, every answer, timing and usage, plus the messages, the pick and the
> executed primitives; every tick is also stored whole in `history.jsonl`.

Every tick should produce a compact decision trace:

```text
timestamp
state hash / summary
available actions
module outputs
projection results used
arbiter distribution
selected action
exploration state
active strategy
reward/outcome when available
```

For LLM proposals also record:

```text
request context
raw proposal
parsed proposal
validation result
admission decision
subsequent performance
```

The purpose is to make every action explainable as a sequence of explicit decisions.

---

## 18. First Prototype

> **Now:** items 4 to 6 are the five senses, the central instance and the configuration's exploration
> level; the rest stands.

The first version should deliberately remain small.

Implement:

1. ViZDoom integration.
2. Fixed primitive action set.
3. Shared world-state representation.
4. Five decision modules.
5. Final arbiter.
6. Simple exploration controller.
7. Short bounded projections for a small subset of actions.
8. Strategy archive.
9. Asynchronous LLM proposal queue.
10. Typed macro-action validation and admission.
11. Full decision logging.

Do not initially optimize for strong Doom performance. Optimize for architectural correctness and observability.

---

## 19. Non-Goals for Version 1

Do not require:

- end-to-end LLM control;
- long chain-of-thought reasoning;
- perfect world modeling;
- unrestricted planning;
- dynamic self-modifying code;
- an LLM call on every state;
- a single monolithic policy.

---

## 20. Acceptance Criteria

> **Now:** “the LLM” here is the slow path's generator; Doom still runs with it disabled. d1-ultra is
> the decision maker and is required to play. Every executed action traces to the central's finite
> choice; module replacement is replaced by changing an instance's scope in the configuration.

The prototype is architecturally successful when:

- Doom continues running normally if the LLM is completely disabled;
- every executed action can be traced to a finite arbitration decision;
- every module operates within a fixed time budget;
- simulations have fixed depth and branching limits;
- LLM output cannot directly execute game actions;
- new LLM-generated actions must compile into bounded typed procedures before use;
- exploration behavior can be changed through explicit decision variables;
- module implementations can be replaced independently;
- the system can discover, test, retain, and later reuse at least one new macro-action without modifying the real-time controller code.

---

## 21. Architectural Invariant

The core invariant for the entire project is:

> **Generative systems may propose possibilities; bounded decision systems decide what enters the controller and what is executed.**

