# Learning Doom Controller — Design

Extends `docs/spec.md` (Section 16, Learning) so the controller improves with experience and keeps what it
learned across runs.

## Problem

Before this change the arbiter's choice did not control play: `TacticalMotor.burst()` ran a fixed reflex
(aim, shoot, strafe, walk forward) and the selected action only set the burst length. Nothing persisted
between processes (empirical cache, archive, exploration counts, admitted macros).

## Decisions

| Topic | Decision |
| --- | --- |
| Execution | Assisted primitives: every action runs its own primitive list. |
| Learning | One small value network per module plus a learned arbiter gate. |
| Scenarios | Any `--scenario`; generic metrics; models and experience stored per run folder. |
| Deliverable | `python -m system1_doom.train` with resume, checkpoints, metrics and learning curves. |

## 1. Execution: the chosen action drives play

`TacticalMotor.burst(plan)` executes the selected `ActionSpec.primitive_expansion`:

- `shoot`: turn (or strafe, when the scenario has no turn buttons) toward the locked enemy; fire only once it
  is centred.
- `strafe_left` / `strafe_right`: strafe, plus a tracking turn toward the locked enemy when one is visible.
- `move_forward` inside an action that targets a pickup (`parameters.pickup_id`): steer toward the nearest
  visible pickup while advancing.
- `strafe_left_shoot` / `strafe_right_shoot` (compound primitives): strafe the whole step, turning onto the
  locked target and firing once it is centred. The built-in macro `weave_fire` is two steps each way. Added
  because no single primitive could move and fire in the same step; a scripted check on deadly corridor
  cleared 8/20 seeds with `weave_fire` versus 2/20 with `peek_and_fire`.
- All other primitives are pressed literally.

Each primitive is held for `max(1, 4 // len(plan))` motor steps (2 game tics each), so single primitives and
4-step macros both last about 8 tics and longer macros run longer. A burst stops when the episode ends.
The bridge reports hits, kills, health/armor/ammo gains, death, distance moved, and newly reached 128-unit
map cells.

If a pickup-seeking action moves the player less than 12 units, the pickup it steered toward is marked
unreachable for the rest of the episode and hidden from steering and from the world state. (Found in
training: a shotgun dropped on a ledge in deadly corridor otherwise pinned the player against a wall until
timeout.)

## 2. Learning core

- `features.py` encodes `WorldState` into 32 bounded numbers and `ActionSpec` into 12 numbers describing its
  primitive composition. New Codex macros are scored immediately because actions are described, not indexed.
- Each module owns an MLP `(state ⊕ action) → 64 → 64 → 1` predicting the module's standardised 8-step
  discounted return (γ = 0.9, truncated at episode end) from its own reward:
  - survival: `−damage/25 − 3·died`
  - combat: `0.5·hits + 2·kills`
  - navigation: `+1` per new map cell this episode
  - resource: `health_gain/25 + armor_gain/25 + ammo_gain/10`
  - goal: the scenario reward
- Module utility = `λ·network + (1 − λ)·heuristic` per candidate action, with `λ = n / (n + 25)` where `n`
  is how often that action was executed in the current context signature. Networks only steer where they
  have data; untried actions stay on the heuristic. (A first version used one global `λ` that grew with total
  experience: reward rose for ~75 episodes, then fell once networks dominated and chased overestimated,
  rarely tried actions.) Counts are stored in the checkpoint. d1-ultra blending stays on top when enabled.
- Arbiter gate: `state → 32 → 5` values, one per module, trained on the goal return of transitions where that
  module's top pick was the executed action. `softmax(values / 0.5)` replaces the hand-tuned module weights,
  faded in by the same count rule per context.
- Training runs between episodes: a fixed 200 Adam steps (batch 256) over a replay buffer of at most 100k
  transitions. Targets are standardised with running statistics stored in the checkpoint.
- Exploration: `ControllerConfig.exploration_floor` is the probability of sampling from the tempered arbiter
  distribution instead of taking the top pick. `train` decays it linearly 0.6 → 0.05 over 100 episodes.

## 3. Persistence, commands, failure handling

Run folder (default `runs/<scenario stem>/`):

- `checkpoint.pt` — networks, gate, optimiser, target statistics, counters
- `best.pt` — best rolling-20 mean episode reward
- `replay.npz` — bounded experience buffer
- `macros.json` — admitted Codex macros, revalidated and reloaded at start-up
- `metrics.jsonl` — one row per episode
- `learning_curves.png` — reward, success rate, health/kills, network share and losses
- `evaluation.json` — latest learned-versus-heuristics comparison
- `ticks.jsonl`, `proposals.jsonl` — existing decision traces

Commands:

- `python -m system1_doom.train --scenario X --episodes N` — headless, d1-ultra and Codex off unless `--d1` /
  `--codex`; resumes automatically, `--fresh` starts over; one line per episode; Ctrl+C saves first.
- `python -m system1_doom.train --scenario X --evaluate N` — no training; plays N identical seeded episodes
  greedily with heuristics only, the latest checkpoint, and `best.pt`, prints the comparison and writes
  `evaluation.json`.
- `python -m system1_doom.cli` — plays with `best.pt` (falling back to `checkpoint.pt`) when present
  (`--no-learned` disables); `--learn` continues from `checkpoint.pt` and keeps training between episodes.
  Value learning oscillates between episodes, so the best checkpoint is usually stronger than the latest.

Failure handling: without PyTorch, play uses heuristics and `train` prints the install command. A checkpoint
with different feature sizes is refused (use `--fresh`). A training error is logged and play continues on the
current weights.

## Measured results (2026-10-23)

`--evaluate 30`, identical held-out seeds, no exploration, d1-ultra and Codex off:

| Scenario | Training | Heuristics | Latest checkpoint | Best checkpoint |
| --- | --- | --- | --- | --- |
| deadly_corridor | 300 episodes | 13% cleared, reward 548 | 37% cleared, reward 1034 | 50% cleared, reward 1407 (episode 220) |
| defend_the_center | 200 episodes | 8.5 kills | 17.4 kills | — |

## Testing

Unit: encoder sizes/bounds, n-step returns, networks fitting synthetic targets, gate credit assignment,
per-context trust, replay bounds, checkpoint round trip, macro persistence. ViZDoom: motor plan execution,
aim-before-fire on `basic.cfg`, train then resume with continued numbering, evaluation without side effects.
Improvement is measured with `--evaluate` on identical seeds rather than with an automated test, because a
meaningful run takes minutes and the heuristic baseline already solves `basic.cfg`.
