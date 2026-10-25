# d1-ultra as the decision maker — design (2026-10-25)

Status: agreed with the project owner on 2026-10-25; built in three pull requests (section 12), all three built (package 0.4.0).
This document is the design; `DOCUMENTATION.md` describes the code as it is after each PR.

## 1. The concept

Every decision this agent makes is made by a d1-ultra instance. The code renders evidence, keeps the bounds, and presses the keys; it never ranks or scores an action itself.

Two nested systems, both built from the same part: an instance is one d1-ultra call with its own evidence (a scope) and its own finite questions.

- **System 1** decides the action at every tick. Five senses (survival, combat, navigation, resource, goal) each see only the evidence in their scope and decide whether to send a message: an action, a reason, a strength. A central instance reads the messages that arrived, with each sense's learned relevance, plus the legal menu and whatever world evidence its own scope grants, and decides the action. Act executes that action's fixed primitives.
- **System 2** reflects on System 1's history, asynchronously and over flexible windows. It has the same shape: reflectors (senses over history) message a central that decides one configuration change at a time. The configuration is what System 2 owns: each sense's scope, the central's scope, the exploration level, the active strategy, and the menu (admitting or retiring a macro). Every scope change is tested on history before it is applied, applied as a trial, and reverted if the trial does not pay off.

What stays hand-written is bounds and evidence only: which actions are legal now (preconditions), how long a call may take, how big a scope may grow, one trial in flight at a time, and the simulator's and the value networks' numbers shown to the instances as evidence.

When d1-ultra does not answer in time, the agent does not fall back to rules. A silent sense is silent; a missed central holds no keys and the tick is recorded as missed (section 7).

The words used below: a **channel** is one named piece of evidence (section 3); a **scope** is the set of channels an instance is shown; a **message** is what a sense sends; **strength** is the sense's own urgency; **relevance** is its learned track record (section 6); the **configuration** is everything System 2 can change; a **trial** is a change under observation.

```text
 Evidence channels: vitals · threats · incoming · outgoing · pickups · geometry · position · progress
                    history · frame · menu · projections (simulator) · values (networks) · novelty · archive
        │           │            │             │            │
   ┌────▼───┐  ┌────▼───┐  ┌─────▼─────┐  ┌────▼────┐  ┌───▼──┐      each sense: a d1-ultra instance
   │survival│  │ combat │  │navigation │  │resource │  │ goal │      that sees its scope only
   └────┬───┘  └────┬───┘  └─────┬─────┘  └────┬────┘  └───┬──┘
        └───────────┴──── messages: action, reason, strength ──┘
                                 │
                       ┌─────────▼──────────┐
                       │  Central instance  │  hears the messages (+ relevance, menu,
                       └─────────┬──────────┘  its own world channels), chooses the action
                                 │
                       ┌─────────▼──────────┐        ┌─────────┐
                       │ Act: fixed primitives, 8 frames ├──────► History │
                       └────────────────────┘        └────┬────┘
                                                          │
   ┌──────────────────────────────────────────────────────▼────────────────────────────┐
   │ System 2, slow and asynchronous: reflectors over the history message a central    │
   │ that makes one configuration change at a time; a scope change is tested on the    │
   │ history first, applied as a trial, and reverted if it does not pay off.           │
   └───────────────────────────── configuration (scopes, menu, strategy, exploration) ─┘
```

## 2. What goes, what stays

Everything that today weighs, scores or picks an action is removed. What stays is either a bound the instances work inside, or evidence they are shown.

| Today | Fate | Why |
| --- | --- | --- |
| Module utilities and their softmax (`modules.py`, `compute_local_utilities`) | Removed | A sense is a d1 instance; it has nothing of its own to blend |
| d1 mixing weights in the modules (0.75, or 0.25 on a wide utility gap) | Removed | d1's answer is the decision, not an ingredient |
| Expansion-request rules (`check_expansion_needed`, the 0.78 noul threshold) | Removed | System 2's menu reflector decides when a new move is needed |
| The arbiter's score: module votes, 0.20 × projection, 0.15 strategy bonus, 0.30 × d1, exploration and novelty bonuses, risk, execution cost; committed, greedy, sampled picks | Removed | The central instance decides |
| The exploration pressure formula and sampler temperature (`exploration.py`) | Removed | The exploration level is a System 2 decision; visit counts stay as evidence |
| The strategy meta-decision scores (`archive.decide_strategy_action`) | Removed | System 2's strategy reflector and central decide |
| Admission thresholds (reject under 0.40 unless quality ≥ 0.85 and p ≥ 0.20) | Removed | The admit instance's own yes or no |
| The arbiter gate network (`learning.py` gate) | Removed | The relevance ledger (section 6) replaces it |
| `async_cached` mode, the cached answer for a context, the critical budget's repeat | Removed | Every tick waits for d1 within a per-call budget; a miss is recorded, never papered over |
| Legal menu from preconditions (`actions.py`) | Stays, as a bound | The finite set an instance may choose from |
| Bounded simulator (`simulator.py`) | Stays, as evidence | The `projections` channel, labelled as a rough model |
| Value networks (`learning.py`, five nets) | Stay, as evidence | The `values` channel, per the owner's choice; trained between episodes as today |
| Motor and bridge (`motor.py`, `vizdoom_env.py`) | Stay | Act: fixed primitives per action |
| Codex and template generation (`llm_worker.py`) | Stays | Proposes a macro only when System 2 asks |
| Parse, legality and sandbox stages (`admission.py`) | Stay, as bounds | A proposal must be a finite typed procedure before any instance sees it |
| d1 client (`d1_client.py`) | Stays, extended | Parallel calls, per-call timing, usage and miss accounting |
| Traces, bundles, the site | Rewritten | Schema version 2 and a new story (section 10) |

## 3. System 1: evidence channels and scopes

A channel renders one named piece of evidence as plain text (or attaches the frame). A scope is the set of channels an instance is shown, and nothing else reaches it. The rendered text of every instance is logged verbatim, so the site can show exactly what each instance saw.

| Channel | What it renders | Source |
| --- | --- | --- |
| `vitals` | health, armor, ammo, weapon | observation |
| `threats` | each visible enemy: name, distance, angle, on-screen size, attacking; the count | observation |
| `incoming` | damage taken since the last decision; consecutive decisions under fire | observation, counter |
| `outgoing` | damage dealt, hits and kills since the last decision | observation |
| `pickups` | each visible pickup: name, category, distance, angle | observation |
| `geometry` | wall distance ahead, left, right; moving or still | depth buffer |
| `position` | x, y, facing; sectors discovered this episode | observation, memory |
| `progress` | decisions so far, reward so far, kills, last displacement, stall streak | observation, counter |
| `history` | the last 6 primitives executed and the last 3 decision summaries | memory |
| `frame` | the 320 × 240 JPEG, attached as the call's image | screen buffer |
| `menu` | the legal actions now, each with its description | preconditions |
| `projections` | per legal action: the simulator's expected value, damage in and out, survival, progress, labelled as a rough projection | `simulator.py` |
| `values` | per legal action: each value network's predicted return and how often that action was tried here, labelled as learned from past play | `learning.py` |
| `novelty` | how often each legal action has been taken in this context | counter |
| `archive` | the strategies, the active one and its record | `archive.py` |
| `exploration` | the exploration level System 2 has set, and what it asks of the chooser | configuration |
| `messages` | the senses' messages this tick: sense, action, reason, strength | System 1 |
| `relevance` | each sense's track record in this context (section 6) | ledger |

The `messages`, `relevance` and `exploration` channels exist only for the central. Every instance that chooses an action has `menu`, because the finite set is the question's criteria.

Initial scopes, which System 2 can widen or narrow one channel at a time:

| Instance | Initial scope |
| --- | --- |
| survival | `vitals`, `threats`, `incoming`, `projections`, `menu` |
| combat | `threats`, `outgoing`, `vitals`, `frame`, `projections`, `menu` |
| navigation | `geometry`, `position`, `progress`, `projections`, `menu` |
| resource | `pickups`, `vitals`, `menu` |
| goal | `progress`, `archive`, `history`, `values`, `menu` |
| central | `messages`, `relevance`, `exploration`, `vitals`, `menu` |

Bounds: a scope holds at most 7 channels; a channel's text is capped (6 enemies, 6 pickups, 6 history steps, 3 summaries); rendering is deterministic and covered by golden-text tests. A sense's scope must not contain `messages` or `relevance`, and no scope may be empty of `menu`.

## 4. System 1: the sense instance

A sense is one d1-ultra call per tick: its scope's text as the state, the frame as the image when `frame` is in scope, and three finite questions. The five senses are called in parallel.

| Question | Kind | Instructions (the sense's name and concern come from configuration) | Answer used |
| --- | --- | --- | --- |
| `speak` | noul | "You are the survival sense of a Doom agent; you see only the evidence given. Must the action chooser hear from you before the next decision?" | its probability is the strength |
| `action` | choice over the legal menu; criteria = each action's description | "Which legal action do you recommend now?" | the top action, with the full distribution |
| `reason` | choice over the sense's reason vocabulary | "Which reason best describes why?" | the top reason, with the distribution |

The sense speaks when its `speak` probability is 0.5 or more: d1's own yes. There is no tuned threshold. A spoken message carries the sense, the action, the reason and the strength to the central's `messages` channel. A silent sense is logged with the same answers but reaches the central as silence.

Each sense's reason vocabulary is a short finite list, part of the configuration, so the message stays a finite decision:

| Sense | Concern in its instructions | Reasons |
| --- | --- | --- |
| survival | staying alive in the next few seconds | health critical, under fire, enemy too close, recovering, no threat |
| combat | winning the current fight | target aimed, target off centre, several enemies, low ammo, no target |
| navigation | moving through the level | path clear, wall ahead, stalled, door or switch ahead, unexplored side |
| resource | health, armor and ammo | health pickup near, ammo pickup near, pickup guarded, nothing needed, nothing visible |
| goal | finishing the level | making progress, plateau, strategy fits, strategy failing, nearly done |

The instructions never say how to weigh anything; they name the sense, its concern, and that it sees only the evidence given. The criteria are exactly the legal menu's ids and descriptions; projections and values appear in the state text, not in the criteria, and a test asserts the two never mix.

A sense's answer is a miss when the call exceeds its budget, fails, or names an action outside the menu. A missed sense is silent and marked `missed` in the trace; nothing stands in for it.

## 5. System 1: the central instance

The central is one d1-ultra call after the senses have answered. Its state is its scope: the messages that arrived, each sense's relevance record, the exploration level, the world channels System 2 has granted it, and the legal menu. Its one question is a choice over the menu: "Choose the action the agent executes now."

The `messages` channel renders one line per spoken sense, for example: "survival says retreat_to_cover, strength 0.82, reason under fire." The `relevance` channel adds the record: "survival here: spoke 14 times, followed 9, paid off 7 of 9; overruled 5, the chosen action paid off 2 of 5." When no sense spoke, the channel says so and the central decides from the menu and its world channels.

How the answer becomes the action depends on the exploration level, a System 2 setting with two values, also stated in the central's `exploration` channel so d1 knows what is asked of it:

- `exploit`: the action with the highest probability.
- `explore`: one action drawn from d1's own distribution, with a seeded generator; the draw is logged. The channel text adds: "prefer a less-tried action when the messages do not demand otherwise", and `novelty` is granted to the central while this level is on.

There is no temperature and no bonus. Where the probabilities tie, the first in menu order is taken and the tie is logged.

A missed central (budget exceeded, error, or an action outside the menu) executes no keys for the decision's 8 frames and the tick is marked `missed`. Three consecutive misses end the episode as `connection_lost`; such an episode is never shipped as a recording (section 7).

The trace keeps, for the central and for every sense, the verbatim evidence text, the image reference, each question's full answer, the call's timing and usage, and how the pick was made: `top`, `drawn`, or `missed`.

## 6. Trainable strength and relevance

What is learned is shown to the central as evidence; nothing learned is ever multiplied into a decision. Strength is d1's own `speak` probability and is not rescaled. Relevance is the sense's track record, kept per sense and context signature in a ledger, and rendered in the `relevance` channel.

The ledger is updated at the end of every episode from the history, because a decision's worth needs its future. For each tick where a sense spoke:

- followed: the central executed the sense's action; paid off: the n-step return of the next 8 decisions (discount 0.9, the learner's existing return) was positive.
- overruled: the central executed another action; the ledger records whether that action paid off, so the central can see when ignoring a sense was right.
- calibration: the sense's mean strength on ticks that paid off, and on ticks that did not.

The rendered record is counts, not a weight: "survival here: spoke 14, followed 9, paid off 7 of 9; overruled 5, the chosen action paid off 2 of 5; mean strength 0.81 when it paid off, 0.64 when not." A sense with no record here says so. Counts under 5 are shown as counts, so d1 sees how thin the evidence is.

The ledger lives in `runs/<scenario>/relevance.json`, is restored at start, grows across episodes, and is copied into every bundle. Its update and rendering are pure functions with unit tests on synthetic histories.

The five value networks keep training between episodes on d1-played experience exactly as today (`record_experience`, replay, n-step returns); their predictions and trust counts are the `values` channel. The gate network is dropped: the relevance ledger is its replacement, and it is readable.

Considered and rejected: a learned scalar that scales a message's strength before the central sees it. It would weigh in on the decision instead of informing it.

## 7. Robustness: misses, budgets, bounds

The agent waits for d1-ultra at every tick, inside a per-call budget, and records every miss instead of filling it. ViZDoom advances only when the controller steps it, so waiting does not change the game; a recording replays at the agent's own pace, and live play shows the real latency.

Measured on the shipped d1 recording (44 decisions): a module batch call took 509 ms and the arbiter call 452 ms on average. Five parallel sense calls then one central call should keep a tick near 1 to 1.5 s; the first live run measures this.

| Event | Behaviour | Recorded as |
| --- | --- | --- |
| A sense exceeds the call budget, errors, or names an action outside the menu | Silent this tick | `missed` on that sense, with the error class or the raw answer |
| The central exceeds the budget, errors, or names an action outside the menu | No keys held for the decision's 8 frames | `missed` on the tick, pick `missed` |
| Three consecutive central misses | The episode ends | `connection_lost` in the result; not shippable |
| HTTP 429 | Wait per `Retry-After`, within the budget | counted as a retry |
| Malformed probabilities (not summing near 1, negative) | Treated as a miss, never repaired | raw answer kept |

Bounds, all in configuration and all logged:

| Bound | Value | Why |
| --- | --- | --- |
| Per-call budget | 5 s (`--call-budget`) | Long enough for a round trip with an image, short enough to notice an outage |
| Calls in flight, System 1 | 6 (5 senses + central) | One tick's worth; the pool is sized to it |
| Calls in flight, System 2 | 2, on its own pool | Never starves System 1 |
| Scope size | 7 channels | Widening stays bounded; see section 3 for the fixed channel caps |
| Trials in flight | 1 | One change under observation at a time, so its effect can be read |
| Cooling per instance | 60 decisions after a change to it | Lets a change show its effect before the next |
| History kept in memory | 2,000 ticks (all are persisted) | Enough for System 2's samples and the relevance update |
| History test sample | 24 ticks, stratified | Section 9 |
| System 2 calls per cycle | at most 40 | Reflectors, central, and the history test |

Every call's `usage` (tokens, cost) is logged per instance and summed per episode and per System 2 cycle, so cost is a number in the bundle, not a guess.

For tests, the client takes a fake transport (section 11) and all randomness is seeded, so every behaviour above is exercised deterministically.

## 8. System 2: the reflective loop

System 2 is a d1 system of the same shape as System 1, run over System 1's history on its own thread and call pool. It never blocks a tick; whatever it decides is applied at the next tick boundary, where the controller checks for a pending change before acquiring the state.

**History store.** Every tick is kept whole: the world state, the legal menu, the projections, the values, the novelty counts, the relevance snapshot, the messages, each instance's evidence text and answers, the frame's path, and the outcome. The last 2,000 ticks stay in memory; all are appended to `history.jsonl` and copied into the bundle. From a stored tick any instance can be re-rendered under any scope, which is what the history test needs.

**Cadence and windows.** A cycle starts when 20 new decisions have been made since the last one, or an episode has ended, provided no trial is in flight. Reflectors are shown history channels over three windows at once: the last 20 decisions, the last 100, and the last 3 episodes, so a short-lived problem and a long trend both have a view.

**History channels** (System 2's evidence): `h_outcomes` (decisions, reward, kills, deaths, damage, stalls, misses per window), `h_sense:<name>` (spoke, followed, paid off, overruled, calibration; the sense's current scope and the channels it could add), `h_central` (how often it followed the strongest message, picks that paid off, ties, misses, its scope), `h_actions` (each action's count and mean return, actions never tried, admitted macros and their record), `h_strategy` (the archive and the active strategy's record), `h_exploration` (the level, the share of less-tried actions taken, the progress trend), `h_config` (the configuration version, the change log, the trial in flight, cooling), `h_tests` (recent history tests and trial verdicts).

**Reflectors**, each a d1 instance with `speak`, a finite `change` choice and a `reason` choice:

| Reflector | Scope | Changes it can propose |
| --- | --- | --- |
| one auditor per sense (5) | `h_sense:<name>`, `h_outcomes` | widen that sense with one named channel; narrow it by one; keep |
| central auditor | `h_central`, `h_outcomes` | widen or narrow the central's scope by one channel; keep |
| menu reflector | `h_actions`, `h_outcomes` | ask for a new macro, naming the sense whose problem it is; retire an admitted macro; keep |
| strategy reflector | `h_strategy`, `h_outcomes` | switch to a named archived strategy; keep |
| exploration reflector | `h_exploration`, `h_outcomes` | set `exploit` or `explore` |

**System 2's central** reads the reflectors' messages, `h_config` and `h_outcomes`, and answers one choice: "Choose the one configuration change to make now, or none." Its criteria are the proposed changes the bounds still allow (cooling, one trial in flight, scope size, built-in actions cannot be retired) plus "no change". The bounds filter the finite set; the instance decides.

**What each change does.**

| Change | Path to play |
| --- | --- |
| widen or narrow a sense or the central | the history test (section 9); if passed, applied as a trial at the next tick boundary; if failed, logged as rejected |
| ask for a new macro | `llm_worker` generates (Codex or template); parse, legality and sandbox as today; an admit instance (d1, `admit` noul, the sandbox as evidence) says yes or no; an admitted macro enters the menu as a trial |
| retire a macro | removed from the menu at the next tick boundary; built-in actions are out of reach |
| switch strategy | the active strategy changes at the next boundary; it is evidence in `archive` and its record accrues |
| set exploration level | applied at the next boundary |

**Trial lifecycle.** A change applied as a trial bumps the configuration version and is observed for 60 decisions, across episodes if needed. Then a trial judge (a d1 instance) reads a before-and-during table (reward and damage per decision, kills, deaths, the instance's paid-off rate, the history test's prediction) and answers keep or revert. One safety bound sits above it: if the changed instance's paid-off rate fell by more than 0.15 on at least 10 followed messages, the change is reverted without asking. Revert restores the previous scope or menu exactly.

Every cycle writes a `ReflectionTrace`: the windows, each reflector's evidence and answers, the central's choice, the test, the applied version, and later the trial's verdict.

## 9. System 2: the history test for a scope change

No scope change reaches play until the instance, run under the new scope on the agent's own past, has done at least as well as it did under the old one, by a fixed margin, on a fixed sample, with every number logged.

**Sample.** 24 stored ticks from the current windows, drawn with a seeded generator and stratified: 8 with bad outcomes (n-step return in the bottom quarter of the window), 8 with good outcomes (top quarter), 8 from the rest; at most 4 from any one context signature. The tick ids are logged with the test.

**Re-run.** For each sampled tick the instance is re-rendered under the new scope from the stored inputs and asked its questions again: 24 calls. The old scope needs no calls, because the answer the instance gave at the time, under that very scope, is in the history. The comparison is therefore against what really happened.

**Metrics**, computed for both scopes on the same ticks. For a sense:

| Metric | Measured on | Definition |
| --- | --- | --- |
| alarm recall | bad-outcome ticks | share where the sense spoke and recommended an action other than the one executed |
| good agreement | good-outcome ticks | share where the sense was silent or recommended the executed action |
| quiet | the rest | share where the sense was silent |
| cost | all | mean evidence size in characters and mean call latency |

For the central: agreement with the executed action on good ticks, disagreement on bad ticks, and cost.

**Verdict.** The composite is the mean of the three quality metrics. The new scope passes when its composite is at least 0.05 above the old one and no single metric is worse by more than 0.10; its evidence size must stay under the channel caps. A failed test blocks the change; a passed test makes it a trial (section 8). The margin and the sample size are bounds in configuration, and the test's full table is written to the `ReflectionTrace` and shown on the site.

**Honest limits, stated in the trace.** Hindsight labels come from what the agent did; a tick's alternative actions were never played, so the test measures agreement with good outcomes and alarms before bad ones, not counterfactual value. d1's answers are not deterministic, so the test also re-asks the old scope on 4 of the 24 ticks and reports the agreement with the stored answers as a noise estimate. With fewer than 24 stored ticks in the windows, no test runs and the change waits.

**Cost.** 24 to 28 calls per test, inside the 40-call cycle budget, in the background.

## 10. Traces, bundles and the site's story

The trace schema moves to version 2, because the record of a decision is now six instances and their evidence, not five utilities and a score.

**Per tick** (`ticks.jsonl`): the tick, the configuration version, the frozen state and the legal and pruned actions as today; for each of the six instances its scope, verbatim evidence text, image reference, every answer in full (`speak`, `action`, `reason` with their distributions), `spoke`, `missed`, timing and usage; the messages the central received; the pick (`top`, `drawn`, `missed`) and the executed action and primitives; the outcome; the exploration level and active strategy.

**Per System 2 cycle** (`reflections.jsonl`, new): the windows, each reflector's evidence and answers, the central's choice, the history test with its sample ids, per-tick answers and metrics table, the applied change and configuration diff, and later the trial's verdict.

**Per proposal** (`proposals.jsonl`): as today, with the admit instance's answer in place of the thresholds.

**Bundle**: `episode.json` gains the decider (`d1-ultra`), the configuration at start and end, the cost in calls and tokens, and the miss counts; new files `reflections.jsonl`, `history.jsonl`, `relevance.json`. `export --check` validates them; the JSON schema and the TypeScript types are regenerated; `TRACE_SCHEMA_VERSION` and the app's `SUPPORTED_SCHEMA_VERSION` move to 2 together, in the PR that ships the new recordings.

**The site's one story**: every decision here is made by d1-ultra. Five senses each see a slice of the world and decide whether to speak; one central instance hears them and chooses; a slow system watches the history and changes what each instance is allowed to see.

| Screen | What it shows |
| --- | --- |
| Watch (landing) | The game at the agent's pace, as today. Beside it, the tick's instances as a strip: five sense rows (spoke or silent, strength bar, action, reason), the central row (its pick and probability), Act. A thin line under the strip: configuration version, the last change, the trial in flight. |
| The instances | One decision opened: for each instance the evidence text it saw, verbatim, the frame if it had one, and its answers as bars. A reader can check that the survival sense never saw the pickups. |
| The slow system | A timeline of configuration versions: each change, its history test table, its trial verdict; the relevance ledger per sense. |
| Learning | Relevance over episodes; the value networks as the evidence they are. |
| Growing the menu | Proposals as today, with the admit instance's answer. |
| Reference | Glossary and principles rewritten around the one rule; a two-system drawing replaces the twenty-box diagram. |

Gone from the site: the arbiter and score panels, the module utility matrix, the Formula depth toggle (the only formulas left are the n-step return and the test metrics, shown where they apply), and the brains chips (there is one decider).

**Recordings**: new recordings of deadly corridor played by d1-ultra, including one from a later configuration version so System 2's work is visible. The four current recordings show an architecture that no longer exists and are removed from the site when the new ones ship (owner's decision, 2026-10-25); they stay in git history.

## 11. Tests

Every behaviour in this plan is exercised without a key through a fake transport, and a handful of live tests prove the real API agrees. CI runs the Python suite without the live tests and the web suite, as today.

**The fake transport.** `FakeD1` answers from the payload it receives, deterministically: it reads the question names and the state text, follows a scripted policy (for example, the combat sense speaks at 0.9 when an enemy is aimed, else 0.2; the central picks the first message's action), and records every payload so a test can assert exactly what each instance saw. It can be told to exceed the budget, raise, return an action outside the menu, or return malformed probabilities, at a chosen tick.

| Area | What the tests prove |
| --- | --- |
| Evidence | Each channel's golden text on a fixture state; a scope renders only its channels (the survival text contains no pickup); the caps hold; the choice criteria equal the legal menu |
| Sense instance | Speaks at 0.5 and above; the message carries action, reason, strength; a budget overrun, an error or an off-menu action is a miss and nothing stands in |
| Central instance | Its payload holds only its scope; `top` under exploit; `drawn` under explore reproduces with the seed; decides when no sense spoke; a miss holds no keys; three misses end the episode as `connection_lost` |
| Relevance | Ledger counts and calibration from a synthetic history; rendering; save and restore |
| History store | The ring bound; persistence; re-rendering a stored tick under its own scope reproduces the text seen at the time |
| System 2 | Reflectors see only their history channels; the central's criteria exclude changes the bounds block (cooling, trial in flight, scope size, built-in actions); one change per cycle; applied only at a tick boundary; the trial judge's keep and revert; the safety revert; revert restores the previous configuration exactly |
| History test | Metrics as defined on a labelled synthetic history; the margin rule; the stratified sample and the context cap; no test under 24 ticks; the noise estimate; at most 28 calls |
| Controller, end to end | On `basic.cfg` with the fake: every executed action is in the menu and is the central's pick; every tick records six instances with evidence text; traces validate against the schema; a scripted outage yields missed ticks then `connection_lost`; a fake that shoots when aimed clears the level |
| Export and serve | A bundle has `history.jsonl`, `reflections.jsonl`, `relevance.json`; `--check` passes; schema version 2; live events carry version 2 ticks |
| Architecture | No import of the removed modules remains; the only path from an answer to the keys takes a typed d1 answer, and the only other path is the typed miss |
| Live (need `LIQUID_API_KEY`) | One real tick with six instances answering; a history test re-run on 4 ticks; one System 2 cycle |

**Web.** Vitest on the version 2 readings (instance rows, the strip, the configuration timeline, the glossary against the docs); Playwright on the landing's autoplay as today, the strip's five senses and central, an instance panel showing verbatim evidence that excludes out-of-scope channels on the fixture, the slow-system screen's test table, and the 390 px fit.

Before this design the suite had 70 Python tests and 93 Vitest and 41 Playwright tests. The design removes the tests of the removed parts (about 25) and adds about 45 Python tests; the web counts move with the screens.

## 12. Phasing, cost, decisions

Three pull requests, each green on CI and reviewed before the next starts. The site changes only in the third, so main stays coherent and the live site keeps working throughout.

| PR | Contents | Tests |
| --- | --- | --- |
| 1. System 1 | `evidence.py`, `instance.py`, `senses.py`, `system1.py`, `relevance.py`, `history.py`, `configuration.py` (data only); the controller rewritten around them; the d1 client extended; trace schema 2 in Python; `modules.py`, `arbiter.py`, `exploration.py` and the archive's decision removed; admission thresholds replaced by the admit instance; `cli`, `train`, `export`, `serve` adapted; docs | `FakeD1`; the evidence, instance, central, relevance, history store, controller, export and architecture rows of section 11 |
| 2. System 2 | history channels, reflectors, System 2's central, the history test, the trial lifecycle, `ReflectionTrace`; export and serve carry reflections; docs | the System 2 and history test rows; live tests |
| 3. Recordings and site | new recordings played by d1-ultra; the web app rewritten for schema 2 and the new story; the glossary and docs; version 0.4.0 | the web rows; `--check` on every shipped bundle |

**Cost and time per episode** (from the shipped d1 recording's call times and a test call's usage line): about 6 calls and 1 to 1.5 s per decision, so a 50-decision episode is about 300 calls and a minute and a half, plus 2 or 3 System 2 cycles of up to 40 calls each in the background. Recording four episodes is roughly 1,600 calls and 10 minutes. A test call reported a cost of about 5 millionths of a dollar for 111 input tokens, so an episode costs cents; the first live run measures the real figure and the bundle carries it.

Training the value networks on d1-played episodes is now a d1 cost too: 50 episodes are about 20,000 calls and an hour. It is optional; the shipped checkpoint keeps serving the `values` channel until a run is wanted.

**Decisions taken in this design** (agreed 2026-10-25):

1. One call per instance, the five senses in parallel, then the central. One batched call would show every sense everything.
2. A sense speaks at d1's own 0.5; strength is its `speak` probability, unscaled.
3. The reason is a finite choice per sense, because d1 returns probabilities, not prose.
4. Exploration is two levels set by System 2; `explore` draws from d1's own distribution.
5. A missed sense is silent; a missed central holds no keys; three misses end the episode as `connection_lost`. No rule ever picks an action.
6. Relevance is a readable ledger of counts shown to the central, never a multiplier; the gate network goes.
7. The history test's sample (24) and margin (0.05 on the composite, no metric worse by 0.10) are bounds; a failed test blocks the change.
8. One safety revert (paid-off rate down 0.15 on at least 10 followed messages) sits above the trial judge.
9. The site changes only in PR 3, together with the new recordings.
10. `LIQUID_API_KEY` is a project secret in the cloud environment; live tests and recordings run there.
11. The four pre-design recordings are removed from the site when the new ones ship.
