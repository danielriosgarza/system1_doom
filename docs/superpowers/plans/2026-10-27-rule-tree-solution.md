# The rule tree as a second solution: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the rule tree a complete second way for this package to play Doom, with the same standing as the
current controller: its own module and command line, recorded episodes, a benchmark on the same seeds, its own
section of the documentation, and a copy of the website for it, chosen from a side tab.

**Starting point:** `experiments/soft-loop/` on branch `claude/project-thread-9jae9h` (code, prompt, the 9-rule
starting tree) and `experiments/soft-loop/NOTES.md` (what the three stages of the soft loop found). Milestone 2
removed the folder; the notes are now `docs/superpowers/notes/2026-10-27-soft-loop-stages.md`.

**Tech stack:** as the rest of the package: Python 3.11+, ViZDoom, Pydantic v2, the Jev client in `d1_client.py`,
Pytest; the web app's React, Vite, Vitest and Playwright. The rule writer is the Codex CLI (`codex exec`) or Claude.

---

## 1. The two solutions

Both follow the package's one rule: no hand-written rule makes a choice.

**Senses and central (the current controller).** At each decision, five sense instances each answer questions
about one part of the game, and a central instance chooses the action from a legal menu, using their answers.
While the agent plays, System 2 changes what each instance is shown.

**Rule tree (new).** At each decision, Jev walks a tree of rules. At each node it is asked "Which of these is true
right now?", with each child rule's condition as an option, plus "None of these is true right now." It moves into
the child it picks and is asked again, until it picks "none" or reaches a rule with no children. That rule's
action is played for the next 8 game frames. Some nodes first ask Jev to pick what to attend to (for example,
which visible enemy is the biggest danger); the rules below then speak about "the focus". A rule's action can call
a shared skill: one set of aiming rules turns toward the focus by an amount sized to its angle, then does what
the calling rule asks (fire, walk forward and fire, or walk forward).

System 2 for the rule tree works between games, not during them. It is the soft loop: play until something goes
wrong (the agent dies, or stops making progress), have a rule writer (Claude or Codex) propose one rule Jev could
have used at that moment, check the rule by replaying the game, try it on every training seed, and add it only if
it helps. The code only describes the game to Jev, walks to the rule Jev's answers lead to, presses that rule's
keys, and replays games to grade a proposed rule.

## 2. Where each one stands

Measured in milestone 2 (2026-10-27, every answer from `jev-1.14.0`; §15 of `docs/DOCUMENTATION.md`). Each
solution played every seed twice, before and after the angle fix of decision 1:

| | Seeds 201–215 and 301–315 | Seeds 9–59 | Cost per game |
|---|---|---|---|
| Senses and central | 20 and 22 of 30 | not played | $0.030 |
| Rule tree `general-11` (2 rules added with Claude as writer) | 29 and 28 of 30 | 48 and 51 of 51 | $0.0125 |
| Rule tree `codex-11` (2 rules added with Codex as writer) | 30 and 29 of 30 | 48 and 48 of 51 | $0.0127 |

Before milestone 2 (other days): senses and central 18 of 30 on the benchmark seeds and 1 of 4 in the shipped
recordings (seeds 9–12); the rule tree of the second stage, 40 rules naming enemy types, 15 of 20 on seeds 40–59.

## 3. Decisions for Daniel

Each has a recommendation; the plan follows it unless told otherwise.

1. **The two perception fixes.** The soft loop found two problems in what Jev is shown, and fixed them only for
   the rule tree: the threats list understated every enemy's angle by up to a quarter (it converted screen
   position to angle linearly instead of with atan), and the outgoing channel did not say when many decisions in
   a row had fired without hitting anything. *Recommendation:* fix both in the shared code (`vizdoom_env.py`,
   `evidence.py`), so both solutions see the same game, and re-run the senses benchmark after the change.
2. **Which tree ships.** Claude's tree and Codex's tree differ only in their last two rules. *Recommendation:*
   benchmark both in milestone 2, ship the better as the default, and show both trees' build records on the site.
3. **Where a new visitor lands.** *Recommendation:* keep today's landing (Watch, senses and central); the side tab
   remembers a visitor's last choice.
4. **Names.** *Recommendation:* "Rule tree" for the solution, "the soft loop" for how its rules are written,
   "Senses and central" for the current controller in the side tab.

## 4. Global constraints

- No hand-written rule makes a choice. Every condition is judged by Jev; every action played is the action of the
  rule Jev's answers led to. A failed Jev call is a miss: the walk stops at the node it has reached and that node's
  action is played. Nothing replaces a missing answer.
- The engine never informs Jev. It plays and replays games, and grades proposed rules by their outcome.
- Rules speak about the agent's own situation: the focus, its angle, distance and size on screen, the agent's
  health, damage taken, shots that missed, the goal. A rule does not name a monster type, an item or a map
  distance (see `rule-writer-prompt.md`).
- A tree is a file that can be played without anything else: its rules, its focus questions, its skills, and for
  each rule the frame it was written from (seed, the actions that led there, the state text and the screen).
- Everything is recorded: every question Jev was asked, its options, its answer probabilities, the pick, timing and
  cost; every round of the soft loop, with the dossier, the proposal, the check, the gate and the outcome.
- Milestones 1 and 3 do not change the controller's files (`controller.py`, `cli.py`, `logger.py`,
  `visualizer.py`), where there is work in progress. The perception fixes (decision 1) are a separate, small change.

## 5. Writing on the website

The rule-tree pages must make sense to someone who has never seen the project. Every screen follows these rules,
which are also how the current site is written:

- Open each screen with one or two sentences that say what it shows and why it matters.
- Plain words and short sentences. One idea per sentence. Say what is on the screen, then what it means.
- No metaphors, no slogans, no jokes, no rhetorical questions, no exclamation marks, no "simply" or "just".
- Every number comes from the recording. Nothing is rounded into a claim the recording does not support.
- Use the same terms everywhere, and link each one to the glossary the first time a panel uses it.
- Say what the code does and does not do in the same plain terms as the Reference screen does today.

For example, the Watch screen of the rule tree opens with:

> Every action in this game is chosen by Jev, by walking a tree of rules.
>
> At each decision, Jev answers a short series of multiple-choice questions. The first asks which of a few
> situations is true now. Each answer leads to the next question, until an answer leads to a rule with an action.
> The rows beside the game show each question and the answer Jev chose at the decision shown.

---

## Milestone 1: the rule tree as a package module

### Task 1.1: Action codes

**Files:**
- Create: `src/system1_doom/ruletree/__init__.py`, `src/system1_doom/ruletree/codes.py`
- Test: `tests/test_ruletree_codes.py`

**Interfaces:**
- Produces: `segments(action, partial=False)`, `complete(action, then)`, `describe(action)`, `buttons(code)`,
  `COMBOS` (the 54 four-letter codes), `TICS = 8`.

- [x] **Step 1:** Write tests: a code alone is held 8 tics; `00R0:3+0001:5` is two segments; a skill's partial
  action `00R0:3` is completed by the caller's `then` (`00R0:3+0001:5`); sums other than 8 are refused outside a
  skill; `describe` gives the words the site shows ("turn right for 3 tics, then fire for 5 tics").
- [x] **Step 2:** Move the code from `experiments/soft-loop/softloop.py`; run the tests.

### Task 1.2: The tree

**Files:**
- Create: `src/system1_doom/ruletree/tree.py`
- Test: `tests/test_ruletree_tree.py`

**Interfaces:**
- Produces: Pydantic models `Focus` (`from_channels`, `question`), `SkillCall` (`skill`, `then`), `Cornerstone`
  (`seed`, `prefix` of action codes, `state_text`, `frame` file name, `expect` route, `event_at`, `horizon`,
  `standing`), `RuleNode` (`id`, `parent`, `condition`, `action`, `focus`, `children`, `cornerstones`,
  `provenance`), `RuleTree` (nodes, skills, `name`, `writer`); `load_tree(path)`, `save_tree(tree, path)`,
  `with_rule(tree, proposal)`, `route(path)`, `tree_lines(tree)`.

- [x] **Step 1:** Tests: adding one rule and a group; a rule with its own focus; a rule inside a skill may give a
  partial action, a rule outside may not; ids stay unique; `tree_lines` prints the skill after the tree.
- [x] **Step 2:** Self-contained trees: a cornerstone keeps the seed and the actions that led to its frame, instead
  of the name of a trace file. Frames are JPEG files next to `tree.json` (`cornerstones/<rule>-<n>.jpg`).
- [x] **Step 3:** Convert the shipped trees into this form: `trees/general-9/` (the starting tree),
  `trees/general-11/` (Claude as writer), `trees/codex-11/` (Codex as writer, from Daniel's machine,
  `~/GitHub/system1_doom-softloop/experiments/soft-loop/runs/codex1`). Each folder has `tree.json`,
  `cornerstones/` and `build.jsonl` (the soft loop's record that produced it). Done: they ship with the package
  in `src/system1_doom/ruletree/trees/`, so `--tree general-11` works wherever the package is installed.

### Task 1.3: The walk

**Files:**
- Create: `src/system1_doom/ruletree/walk.py`
- Test: `tests/test_ruletree_walk.py` (with `tests/fake_d1.py` answering)

**Interfaces:**
- Consumes: `D1UltraClient` with the `jev` decider (key, retries, timeouts, cost).
- Produces: `decide(tree, client, state_text, frame) -> Decision`, where `Decision` holds the action code, the node
  reached, and the steps: each question (node, options with their texts, probabilities, pick, latency, cost), each
  focus pick (the options it chose from, the pick, the `[focus]` line added to the state), each skill entered.

- [x] **Step 1:** Tests: the walk stops at "none"; a focus node adds the `[focus]` channel before its children are
  asked; a skill call continues in the skill and the caller's `then` completes the action; a single focus option
  needs no question; a failed call is a miss and the node reached acts.
- [x] **Step 2:** Implement with the package's Jev client instead of the experiment's own HTTP code, keeping the
  answer cache used by checks.

### Task 1.4: The game

**Files:**
- Create: `src/system1_doom/ruletree/game.py`
- Test: `tests/test_ruletree_game.py` (marked to need ViZDoom)

**Interfaces:**
- Produces: `Game` (reset, observe, step with action sequences, events: died, stalled, cleared, timed out),
  `play(tree, client, seed, prefix=())`.

- [x] **Step 1:** Move `Game` and `play`. Until decision 1 is taken, keep the two perception fixes here.
- [x] **Step 2:** Test one seed with canned answers: the episode runs, decisions are 8 tics, stall and death are
  detected.

### Task 1.5: The soft loop

**Files:**
- Create: `src/system1_doom/ruletree/check.py`, `gate.py`, `dossier.py`, `writers.py`, `loop.py`
- Create: `src/system1_doom/ruletree/prompts/rule-writer.md`
- Test: `tests/test_ruletree_check.py`, `tests/test_ruletree_loop.py`

**Interfaces:**
- Produces: `check(tree, proposal) -> CheckReport` (sees, unchanged, avoids), `gate(tree, proposal, seeds) ->
  GateReport`, `write_dossier(trace)`, writers `CodexWriter` (`codex exec`), `ClaudeWriter`, `FileWriter` (a person
  or another program puts the proposal in a file), `run_loop(tree, writer, train, held, rounds)`.

- [x] **Step 1:** Tests for the comparisons: alive beats dead; reaching the goal beats not; if both die the rule
  fails; otherwise no worse on health and furthest point and better on one.
- [x] **Step 2:** Test the loop end to end with a writer that returns a fixed proposal and a fake game.
- [x] **Step 3:** The loop writes `build.jsonl`: one line per round (seed, failure, decision), per proposal (text,
  writer, seconds), per check, per gate, per commit.

### Task 1.6: Command line

**Files:**
- Create: `src/system1_doom/ruletree/__main__.py`
- Test: `tests/test_ruletree_cli.py`

- [x] **Step 1:** `python -m system1_doom.ruletree play|eval|show|check|gate|commit|loop`, with `--tree`,
  `--seeds`, `--writer codex|claude|file`.
- [x] **Step 2:** Remove `experiments/soft-loop/` once the module reproduces its results (milestone 2). Done: the
  module's cornerstone replays matched the experiment's, and both codes cleared the same 27 of 31 seeds within the
  same ten minutes; `NOTES.md` moved to `docs/superpowers/notes/2026-10-27-soft-loop-stages.md`.

## Milestone 2: benchmark

### Task 2.1: The same seeds as the current controller

- [x] **Step 1:** Play `general-11` and `codex-11` on seeds 201–215 and 301–315 with fresh Jev answers, and on
  seeds 9–59. Record cleared, decisions to clear, Jev calls and cost per game, and the time per decision. Done
  twice, before and after decision 1 (§2 above; §15 of the documentation).
- [x] **Step 2:** If decision 1 is taken, re-run the senses-and-central benchmark after the perception fixes. Done:
  the angle fix went into `vizdoom_env.py` (commit `4dc5d11`); the missed-shots line was not needed there, since
  the senses' evidence already says "your last N attacks on it hit nothing" per enemy. 20 of 30 before, 22 of 30
  after (Fisher's exact p ≈ 0.78).
- [x] **Step 3:** Pick the default tree (decision 2). `general-11`: 156 of 162 games over the two runs against
  155 for `codex-11`, in about two fewer decisions per game, and no early deaths. `play` and `eval` use it when no
  tree is named (`DEFAULT_TREE` in `tree.py`).

### Task 2.2: Documentation

**Files:**
- Modify: `docs/DOCUMENTATION.md` (new §8.17 "The rule tree", rows in §11 and §15, glossary entries in §18)

- [x] **Step 1:** Write the section in the same plain style: what a rule is, how the walk works, what the soft loop
  does, the checks, the measured results.
- [x] **Step 2:** Keep the glossary test in step (`web/src/content/glossary.test.ts` compares it with §18). Moved
  to milestone 4: each glossary entry links to the screen that shows it, and the rule-tree screens come there.
  Done in milestone 4: 13 rule-tree terms, and Jev, Channel, Miss and Bundle with a meaning for each solution.

## Milestone 3: recordings

### Task 3.1: The rule-tree bundle

**Files:**
- Modify: `src/system1_doom/export.py` (a `--solution rule-tree` option that plays and records with a tree)
- Test: `tests/test_export.py` (new cases)

**Bundle contents** (one folder per episode, like today's):

| File | Contents |
|---|---|
| `episode.json` | `RuleTreeEpisodeMeta`: `solution: "rule-tree"`, schema version, name, title, scenario, seed, the tree's name and writer, the result, cost, calls, misses, files |
| `decisions.jsonl` | One `RuleTreeTick` per decision: the state text exactly as Jev was sent it, every step of the walk (question, options, probabilities, pick; focus; skill), the action and its segments in words, health before and after, kills, position, events |
| `tree.json` | The tree as played, without its cornerstone frames |
| `build.jsonl` | The soft loop's record of how that tree was written |
| `frames/00042.jpg` | The screen Jev was sent at each decision; `frames/end.jpg` after the last action |

- [x] **Step 1:** Models and writer; `--check` validates a rule-tree bundle (every decision has a walk, the action
  played equals the action of the node reached, every frame exists). Done in `ruletree/bundle.py`: the line model
  is `RuleTreeDecision`, and the tree ships with its cornerstone frames (about 30 KB), so the site can show the
  screen each rule was written from. The episode plays to its end; a stall is marked, not stopped at.
- [x] **Step 2:** `--index` lists both kinds; each entry gains `solution` (absent means senses and central, so the
  recordings already shipped stay valid without re-export). Until milestone 4 the site's loader keeps the senses
  entries only, so the landing and the picker are unchanged.
- [x] **Step 3:** `--schema` adds the new models to `$defs`; regenerate `web/src/schema/bundle.ts` with
  `npm run schema` and `npm run types`.
- [x] **Step 4:** Record seeds 9 to 12 with the default tree, the same seeds as the shipped senses recordings, and
  ship them in `web/public/episodes/` as `rules-corridor-9` to `rules-corridor-12`. Done: all four cleared, in 37
  to 47 decisions, 2.9 MB in all (§15 of the documentation). The history channel Jev reads says "for 1 tics";
  the recordings' action words say "for 1 tic". Changing what Jev reads would need the benchmark again, so it
  is left as it is.

## Milestone 4: the website

The rule-tree site mirrors the current one: the same layout, the same six screen positions and keys, the same
timeline, the same components where they fit, and the same way of writing (section 5).

### Task 4.1: The side tab

**Files:**
- Create: `web/src/components/SolutionTabs.tsx`
- Modify: `web/src/App.tsx`, `web/src/store.ts`, `web/src/components/TopBar.tsx`, `web/src/styles.css`
- Test: `web/e2e/solutions.spec.ts`

- [x] **Step 1:** A vertical tab bar on the left edge of every screen with two tabs, "Senses and central" and "Rule
  tree". The selected tab is marked. On a narrow screen it becomes a two-button switch above the top bar.
- [x] **Step 2:** URLs: today's `#<episode>/<tick>/<screen>` keeps meaning senses and central, so every existing link
  still works; the rule tree uses `#rules/<episode>/<tick>/<screen>`.
- [x] **Step 3:** Switching keeps the screen position (screen 3 opens screen 3) and opens the same seed when the
  other solution has a recording of it, at its first decision.
- [x] **Step 4:** The episode picker lists only the selected solution's recordings; the choice is remembered with
  the theme and pace.

### Task 4.2: The six screens

**Files:**
- Create: `web/src/screens/rules/Watch.tsx`, `Questions.tsx`, `HowWritten.tsx`, `Results.tsx`, `Tree.tsx`,
  `Reference.tsx`; `web/src/content/rules/*.ts` (every word on these screens); `web/src/data/rules.ts` (reading
  the bundle, nothing decided)
- Test: Vitest for `data/rules.ts`; Playwright `web/e2e/rules-*.spec.ts`

| Key | Senses and central | Rule tree | What the rule-tree screen shows |
|---|---|---|---|
| 1 | Watch | Watch | The game at the agent's pace. Beside it, one row per question Jev answered at this decision, top to bottom: the question, the answer it picked in words, and the probability as a bar; the focus it picked; then the Act row with the action in words and its tics. Under the game, the same controls, counter and recording cards. |
| 2 | The instances | The questions | One question at a time, from a tab per question asked at this decision: the state Jev was sent, exactly as sent, with each `[channel]` header marked and the `[focus]` channel highlighted; the screen it was sent; every option as a bar with the pick marked. |
| 3 | The slow system | How the rules were written | The soft loop's record for this tree, round by round: which seed failed and how; the writer's proposal (the condition, the action, where it was added, the writer's reason); the check (each of its three tests with its numbers); the gate (seeds cleared with and without the rule); added or rejected. Opening a round shows the dossier the writer was given. |
| 4 | Learning | Results | Seeds cleared on each pass as rules were added, for training, held-out and new seeds; and for this recording, how many decisions each rule decided. |
| 5 | Growing the menu | The rule tree | The whole tree as an outline: each rule's condition and action, the focus questions and the aiming skill, with the route of the current decision highlighted. Clicking a rule shows where it came from: the failure, the writer, the check and the gate. |
| 6 | Reference | Reference | The one rule and the principles for this solution; a drawing of its two systems (Jev walking the tree; the soft loop writing rules); the glossary; how this recording was made (tree, writer, seed, command); the keys. |

- [x] **Step 1:** The timeline at the bottom is shared, with marks for damage, a kill, a death, a miss, and which
  top-level rule decided (threat or goal).
- [x] **Step 2:** Each screen opens with its one or two explaining sentences, written to section 5, and each panel
  has the explanation toggle the current site has.
- [x] **Step 3:** A browser test compares the state text on The questions with `decisions.jsonl` character for
  character, as `instances.spec.ts` does for the senses.
- [x] **Step 4:** A first-time reading: someone who has not seen the project reads each screen's opening and
  explanations, and every sentence they stop at is rewritten.

Notes from building it:
- The dossier the writer was given is not in the recording (it stays in the run folder that wrote the tree). How
  the rules were written says so; The rule tree shows the screen and state text each rule was written for (its
  cornerstone) instead.
- Results cites the benchmark from `docs/DOCUMENTATION.md` §15 and says so; a recording holds one game, not 81.
- `general-11`'s record had one held-out line for two runs on different seeds; it is now two lines (seeds 20-39,
  20 of 20; seeds 40-59, 18 of 20), with the second pass on 20-39 after them.
- A `codex-11` recording of seed 9 ships beside `general-11`'s four, so both trees' records are on the site
  (decision 2). With nothing named, the rule tree opens a `general-11` recording.
- In `codex-11`'s record two checks stopped on an API error; they show as "the check stopped", not as rejected.

### Task 4.3: Ship

- [x] **Step 1:** `npm run lint`, `npm test`, `npm run e2e`, `pytest`.
- [x] **Step 2:** Update `web/README.md` (the side tab, the six rule-tree screens) and `README.md`.
- [ ] **Step 3:** One pull request per milestone, from `claude/project-thread-9jae9h` or a branch per milestone.

## Not in this plan

- Live play of the rule tree in the web app (`serve.py` streams senses-and-central ticks only). It can follow once
  the recordings work.
- Other scenarios. The tree's rules are written to work in any part of any level; testing that needs a second
  scenario, after this plan.
