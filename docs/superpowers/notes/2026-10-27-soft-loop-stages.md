# Soft loop: notes from the three stages

These notes were written in `experiments/soft-loop/` while the soft loop was an experiment. Its code now lives in
`src/system1_doom/ruletree/` (§8.17 of `docs/DOCUMENTATION.md`; `python -m system1_doom.ruletree --help`), and the
experiment's scripts named below were removed once the module reproduced their results. The folders named below
(`pilot/`, `v2/`, `v3/`, `example-dossier/`) are kept with the project files, not in the repository.

**Current result (third stage, below): 11 general rules, with no monster names and no map facts, clear the
training seeds 22 of 22, held-out seeds 20 to 39 39 of 40, and new seeds 40 to 59 18 of 20.** The 40 scene-specific
rules of the second stage cleared those new seeds 15 of 20.

Play from the start; stop at the first unwanted event (death, or less than 48 units of progress in 24 decisions);
write one rule Jev could have used; check it; play again. Rules nest as exceptions (Ripple-Down Rules): at a node
with children Jev chooses which child's condition holds now, or none, and the deepest node reached acts. Where no
rule applies the agent walks randomly over the 54 button combinations. One decision holds its buttons for 8 tics.
The engine only plays and replays; Jev never sees it.

- `softloop.py`: `play RUN SEED`, `check RUN RULE.json`, `commit RUN RULE.json`, `gate RUN RULE.json LO-HI`,
  `show RUN`, `eval RUN LO-HI`
- `rule-writer-prompt.md`: the instructions for an LLM rule writer (updated with everything below)
- `seqtest.py`, `view.py`, `report.py`: the rule writer's workbench (replay a trace and try action sequences;
  print a trace; print a check report)
- `example-dossier/`: what the rule writer is given for one failure
- `pilot/`: the first tree (v1): rules, proposals and check reports
- `v2/`: the second tree: rule tree now and at full success, proposals, committed rules, every game by seed
- `v3/`: the general tree: `general-tree.py` builds its 9 starting rules; rule tree, proposals (accepted and
  rejected), committed rules, every game by seed

The sections below describe the first two stages as they ran; the third stage changed the check (see there).

## The check every rule must pass

1. **Sees**: at its frame, Jev's walk through the new tree reaches the new rule.
2. **Unchanged**: frames earlier rules were built from still reach their node, or replaying from them is no worse.
3. **Avoids**: from its frame to 12 decisions past the failure, the new tree ends better than the old one:
   alive where the old one died, or no worse on health and furthest point and better on one.

## What happened (seed 9, I wrote the rules)

| round | failure | rule (attached under) | effect in its check |
|---|---|---|---|
| 0 | random walk died at decision 9, 72 units in | | |
| 1 | that death | r1: an enemy is visible → Jev picks fire, turn left + fire, or turn right + fire (root) | no death through decision 21 (it had died at 9), health 10 |
| 2 | stalled: fired straight 14 times at an enemy 35° right | r2: nearest enemy >10° right → turn right + fire (r1) | health 10 → 40 |
| 3 | died: enemy 24° left | r3: mirror of r2 (r1). **First version rejected**: on r2's frame the image showed a dying enemy on the left, so Jev picked "left". Naming the threats list fixed it. | dead → alive |
| 4 | stalled after both guards died | r4: threats list empty → walk forward (r1) | furthest 5 → 86 |
| 5 | stalled firing at enemies 520 units away | r5: nearest enemy >300 units and near centre → walk forward + fire (r1) | furthest point at the failure's time 111 → 363 |
| 6 | died: ChaingunGuy 8° right at 190 units | r6: within 300 units and 5–10° right → turn right + fire (r1) | dead → alive |
| 7 | **seed 9 cleared** at decision 51 with 10 health | | |

Rules 1–6 were checked with an earlier, looser avoid test (failure gone or later, or better at the failure's
time); none of them won by a mere delay.

Then, with those six rules and no new ones: seeds 10–19 cleared 4 of 10 (10, 12, 13, 16); five died, one stalled.
Seed 9 itself, replayed with fresh Jev answers instead of cached ones, died twice at the last pair of enemies.

Round 8 (seed 11, died at the last pair, two enemies at the same distance on both sides): r7, two enemies within
400 units on both sides → walk backward + fire (under r5). "Stand and fire" was rejected because it only delayed
the death by one decision. With r7, seed 11 still dies there: the agent swings between the two enemies.

## What it taught

- **Cheap.** About 0.25 s per Jev call and about 100 calls per game; a round takes a minute plus the writer's time.
- **The checks are the method.** The regression test caught a rule that took over another rule's frame. The first
  version of the avoid test accepted a rule that delayed a death by one decision; comparing old and new futures
  at a fixed horizon fixed that.
- **Jev's answers vary between calls.** The loop cached them, so seed 9 looked solved, but fresh answers died
  twice. Checks should use fresh answers, more than once, and conditions need margin.
- **The image can mislead.** Dying enemies still look alive. Conditions that name the threats list were reliable.
- **Mirror rules come one failure at a time** (r2 then r3; r6 has no left twin yet).
- **The real limit is the action vocabulary.** One decision turns 12–19°, too coarse to settle on a target, so aim
  oscillates (left, right, left...) and the last pair kills the agent. No condition fixes that; it needs a finer
  action (for example a short turn then fire), which is a Type 2 change to the vocabulary, not a rule.


# Second stage: finer actions until full success (v2)

**Result: all 11 training seeds (9 to 19) cleared in one pass with fresh Jev answers, after 10 commits.**
That is not yet robust: two later passes cleared 8 and 9 of 11, and held-out seeds 20 to 39 cleared 11 and 12
of 20. Every game is listed in `v2/games-by-seed.txt`.

| step | what changed | training seeds cleared (9 to 19) |
|---|---|---|
| v1 tree + two fine-aim rules | | 4 of 11 |
| v2: aim group (turn sized to the angle) + walk forward when clear | rules r1 to r10 | 6 of 11 |
| advance on far enemies; turn to a ShotgunGuy first at the start | r11, r12 | 7 of 11 |
| shoot a ChaingunGuy, then a ShotgunGuy, first, named concretely | group r13 to r26 | 10 of 11 |
| a ChaingunGuy first, also inside the aim-left rule | group r27 to r33 | 8 of 11 |
| every turning action ends with a tic at rest; advance on a far ShotgunGuy | vocabulary change, r34 | 10 of 11 |
| sidestep right when hurt and a ChaingunGuy or ShotgunGuy is near on the right | r35 | **11 of 11**, then 8 of 11 |
| held-out seeds 20 to 39 | | 11 of 20 |
| aim at the ChaingunGuy even when hurt | group r36 to r40 | 9 of 11; held-out 12 of 20 |

## What the second stage taught

- **Finer actions were necessary but not sufficient.** A turn sized to the enemy's angle (3, 5 or 7 tics, then
  fire) fixed the swinging aim, but the big jump came from *which* enemy to shoot: ChaingunGuy, then ShotgunGuy.
- **Jev judges concrete statements, not comparisons.** "The ShotgunGuy is more than 7 degrees to the left" got
  0.98; "the most dangerous enemy is more than 7 degrees to the left" got 0.06 on the same frame. Mutually
  exclusive angle bands as siblings were answered perfectly; nested "more than" chains were not.
- **Two fixes were not rules.** Perception: the threats list understated every angle by up to a quarter (linear
  instead of atan); corrected in the state. Vocabulary: Doom turns faster while the key stays held, so a fine
  turn right after a full turn overshot; every turning action now ends with one tic at rest.
- **The check is too local.** The sidestep rule passed because the agent died a little further on, then made
  three held-out seeds die. Commits should also be gated on the training seeds, not one replay.
- **The tree grows redundant.** The same ChaingunGuy band group now appears three times in different places,
  because exceptions attach where the failure was. A periodic Type 2 "compaction" step would merge them.
- **Cost.** About 0.25 s per Jev call, 80 to 160 calls per game, a pass over 11 seeds in about a minute.


# Third stage: general rules (v3)

**Result: 11 rules clear the training seeds 22 of 22 (two passes), held-out seeds 20 to 39 39 of 40 (two
passes) and new seeds 40 to 59 18 of 20, all with fresh Jev answers.** The 40-rule v2 tree cleared the same new
seeds 15 of 20, and held-out seeds 11 and 12 of 20. Every game is in `v3/games-by-seed.txt`.

The v2 rules were written one failure at a time, each with the simplest wording that passed, so they spoke the
scene's language: ChaingunGuy first, 400 units, walk forward when nothing is in view. Nothing in one corridor
contradicts a rule that only fits that corridor. The rewrite keeps conditions concrete but makes them speak about
the agent's own situation:

- **Focus.** One Jev choice picks what to attend to: "Which of these enemies is the biggest danger to me right
  now?" among the threats list, or "Which of these is the goal I am trying to reach?" among the landmarks. The
  pick is shown to Jev as a `[focus]` channel. On sampled states with mixed enemies Jev always ranked ShotgunGuy
  over Zombieman and ChaingunGuy over Zombieman; ChaingunGuy against ShotgunGuy was a close call. The priority
  the v2 tree hard-coded by name comes from Jev's own judgment here.
- **One shared aiming skill.** Six sibling bands ("The focus channel says it is between 3 and 7 degrees to the
  right") turn by an amount from the turning table; the caller says what to do in the rest of the decision
  (fire, walk forward and fire, walk forward). Shooting and walking to the goal both use it. In v2 the same
  bands appeared five times, per enemy type and per place in the tree. On 60 sampled states Jev reached the right band 57 times;
  the 3 misses were at exactly 3 degrees.
- **Goals at the top.** Threat visible: aim at the focus and fire (walk in when it is more than 400 units away).
  No threat: aim at the goal and walk. Walking to the goal now corrects the heading after a fight, which the
  v2 "walk forward" did not.

| step | training 9 to 19 | held-out 20 to 39 | new 40 to 59 |
|---|---|---|---|
| v2 tree, 40 rules | 11, then 8 and 9 of 11 | 11 and 12 of 20 | 15 of 20 |
| general tree, 9 rules | 8 and 9 of 11 | 14 of 20 | |
| + memory of missed shots (representation), r11, r12 | 11 and 11 of 11 | 20 and 19 of 20 | 18 of 20 |

## What the loop added

- **Representation:** stalls came from firing for 10 to 17 decisions at an enemy shown 1 to 3 pixels wide,
  behind the edge of a wall, never hitting it. The outgoing channel told only the last decision's hits, so this
  looked like ordinary misses. It now also says "the last N decisions in which you fired hit nothing".
- **r11** (under the threat node): "The outgoing channel says the last 5 or more decisions in which I fired hit
  nothing." aim, then walk forward and fire. A threshold of 3 rushed into the next enemies and died; requiring
  no damage taken did too.
- **r12** (exception to r11): "The focus channel shows the enemy at least 6 pixels wide." aim, then fire. The
  gate games showed r11 walking into a fully visible enemy after misses at long range.
- **Rejected by the gate:** "Besides the focus, another enemy within 400 units is more than 12 degrees to the
  side" then back away while aiming. It passed its check (dead became alive with 22 health) and kept far more
  health in the gate games, but cleared 10 of 11 training seeds where the current tree cleared 11.

## What the third stage taught

- **General wording generalized better, and with a quarter of the rules.** The gap was largest on seeds the
  rules were never written from.
- **Jev ranks well when ranking is the question.** "The most dangerous enemy is 7 degrees left" failed (0.06)
  because it hides a ranking inside a condition; "Which of these enemies is the biggest danger?" as its own
  choice among listed items works. So rankings go in focus questions and conditions stay plain.
- **Who is hurting me is not readable.** The incoming channel says how much damage, not from whom, so "shoot
  whatever hurts me" cannot be a condition yet. That would be a representation change.
- **The opening volley is luck.** Turning, backing, sidestepping or advancing at the start all took the same
  18 to 72 damage, depending on the seed.
- **The check changed.** It now plays 24 decisions past the failure instead of 12, counts reaching the goal
  above health, and compares earlier rules' frames at their own horizon. Under the old comparison r11 was
  rejected for losing health, although it was 700 units further on and went on to reach the armor.
- **The gate is the real test.** Two of three rules that passed their check also passed the gate; the third did
  not. It costs one pass over the training seeds with and without the rule, about 90 s.
- **Remaining failures:** all 3 losses with the final tree died at the last enemy pair (about 700 to 830 units
  in), already low on health, while a second enemy shot from the side. In two of them r11 had walked the agent
  closer to the pair after misses at a barely visible enemy: the next failure for the loop.
