// Every word on the real-time screens: the rule tree played by Laya while the game goes on, a helper aiming between
// its answers. The numbers that are not read from the recording are docs/DOCUMENTATION.md section 15's, measured on
// 2026-10-28 and 29 on a Jetson Thor (Blackwell GPU, 122 GB of memory).
import type { ActionSegment, RuleTreeDecision, RuleTreeEpisodeMeta } from '../../schema/bundle'
import { QUESTIONS, RULES_WATCH } from '../rules/words'

const TIC_MS = 1000 / 35

/** Tics as milliseconds of game time. */
export const ticsMs = (tics: number): number => Math.round(tics * TIC_MS)

/** Keys pressed, in words: `turn left for 3 tics, then fire for 5 tics`. */
export const pressedWords = (segments: ActionSegment[]): string =>
  segments.map((s) => `${s.words} for ${s.tics} ${s.tics === 1 ? 'tic' : 'tics'}`).join(', then ')

export const REALTIME_WATCH: typeof RULES_WATCH = {
  ...RULES_WATCH,
  title: 'Laya plays while the game goes on: nothing waits for its answers.',
  subtitle:
    'The game runs at its own speed, 35 frames (tics) a second. Laya reads a description of the game as text and answers a few questions that lead through a tree of rules to an action, in about a tenth of a second. Meanwhile the game keeps going, so every action starts a few tics after the moment it was decided for. Between Laya’s answers a helper keeps the aim on the enemy Laya chose, using only what is on the screen. The helper chooses nothing: what to aim at and what to do come from Laya’s answers.',
  stripNote:
    'One row per question, in the order Laya was asked, and then the action. The bar is Laya’s probability for the answer it gave. The last rows say when this state was read and when its action began, and what the helper pressed until the next action. Click a question to see exactly what Laya was sent.',
  calls: (calls: number, ms: number) =>
    `${calls} ${calls === 1 ? 'question' : 'questions'} to Laya, ${Math.round(ms)} ms one after another, while the game went on`,
  honesty: (meta: RuleTreeEpisodeMeta) => {
    const r = meta.realtime
    const late = r ? `${r.lag_median} tics (about ${ticsMs(r.lag_median)} ms)` : 'a few tics'
    return `This is a recording, one image per decision. It was played on the real clock: the game never paused, and a decision’s action began a median ${late} after its state was read.`
  },
  cardsNote:
    'Each recording is one game of the deadly corridor on one seed, played in real time with the tree realtime-12, every question answered by Laya and every aim made by the helper. Click a recording to play it from the start.',
  frameAlt: (index: number, count: number, health: number, action: string) =>
    `The game at decision ${index + 1} of ${count}, health ${Math.round(health)}. Laya’s answers led to: ${action}.`,
  decider: 'Laya',
  decidedBy: 'decided by Laya, in real time',
  skill: (skill: string, caller: string) =>
    `${caller}’s action uses the ${skill} skill: the helper turns toward the focus at every tic until the crosshair is on it.`,
  actGloss: 'begun once the answers were in, the helper turning toward the focus first',
}

export const REALTIME_QUESTIONS: typeof QUESTIONS = {
  ...QUESTIONS,
  title: (decision: number) => `Decision ${decision}: what Laya was asked, and what it answered`,
  intro:
    'At this decision Laya answered the questions below, one after another, while the game went on. Each was sent with the state of the game as text, as it was when the decision began. Laya reads text only, so the screen was not sent. Pick a question to read the text exactly as Laya received it, and every probability it returned.',
  frame: 'The screen when this state was read (not sent: Laya reads the text only)',
  focusNote:
    'The [focus] channel at the end was added by the focus question before this one. It names the item Laya picked there, which the helper then aimed at.',
  options: 'Its options, with Laya’s probabilities',
  cached:
    'Laya had answered this exact question, with the same text, earlier in this game. That answer was used again and no call was made.',
  timing: (ms: number) => `answered in ${Math.round(ms)} ms, while the game went on`,
}

/** The rows Watch's strip adds for a real-time decision. */
export const REALTIME_STRIP = {
  /** Where the action came from: the aim skill has no turning rules of its own here, the helper turns. */
  source: (node: string, skill: { caller: string; skill: string } | null): string | null =>
    skill && node === skill.skill ? `${skill.caller}’s action, aimed by the helper` : null,
  timingLabel: 'Timing',
  timing: (d: RuleTreeDecision) => {
    const late = (d.start_tic ?? 0) - (d.observed_tic ?? 0)
    return `State read at tic ${d.observed_tic}; action began at tic ${d.start_tic}, ${late} ${late === 1 ? 'tic' : 'tics'} (${ticsMs(late)} ms) later. Laya took ${Math.round(d.walk_ms ?? 0)} ms.`
  },
  helperLabel: 'Helper',
  helper: (d: RuleTreeDecision) =>
    d.target
      ? `aimed at ${d.target}${d.after ? `; once it fell, ${d.after === 'F001' ? 'walk on toward the goal, firing' : `code ${d.after}`}` : ''}`
      : 'nothing to aim at: the keys are the action’s own',
  pressedLabel: 'Keys pressed until the next action',
  pressed: (d: RuleTreeDecision) =>
    d.pressed && d.pressed.length > 0 ? pressedWords(d.pressed) : 'none: the game ended',
}

/** One step of how a decision is made and acted on in real time. */
export interface TimingStep {
  title: string
  text: string
}

export const REALTIME_TIMING = {
  title: 'How it plays in real time',
  intro:
    'In the other tabs the game pauses at every decision until all the answers are in. Here it does not. The game runs at 35 tics a second; Laya answers in about a tenth of a second, 4 or 5 tics; and the helper presses the keys at every tic in between.',
  steps: [
    {
      title: 'The state is read',
      text: 'Every 8 tics the program writes the game as text, exactly as in the other tabs, and Laya starts walking the tree. The game does not stop.',
    },
    {
      title: 'Laya answers',
      text: 'Laya answers the walk’s questions one after another, about 30 to 50 ms each, on the same computer. The game has moved on a few tics by the time the last answer is in.',
    },
    {
      title: 'The action begins',
      text: 'The action of the rule Laya’s answers lead to begins at the first tic after the answers are in. Until then, the keys of the action before stay pressed.',
    },
    {
      title: 'The helper keeps the aim',
      text: 'When the action aims at an enemy or the goal that Laya picked, the helper turns toward it at every tic, from where its label is on the screen, until the crosshair is on it. Then it presses the action’s own keys, such as fire, or walk forward and fire. When the enemy falls, it plays what the rule says to do next.',
    },
  ] as TimingStep[],
  helperTitle: 'What the helper does, and what makes it fair',
  helper: [
    {
      title: 'It sees only what the player sees',
      text: 'The enemies on the screen, from the same labels the state text is written from, seen 4 tics late like a quick hand; where it is facing and how far it has turned since; and where the armor is once the player has seen it. An earlier version read every enemy’s true position from inside the game, including enemies behind walls. That was cheating, and its results are not shown here.',
    },
    {
      title: 'It presses the player’s buttons, nothing more',
      text: 'Forward, back, sidestep, turn and fire, at most once a tic, as a player can.',
    },
    {
      title: 'It fires only when the crosshair is on the enemy',
      text: 'Not merely when the enemy is within a few degrees, which is wider than a far enemy is.',
    },
    {
      title: 'It lifts the trigger between shots at a narrow enemy',
      text: 'Held down, Doom’s pistol fires every 14 tics, but every shot after the first scatters. Lifted at the right moment, it fires every 19 tics and each shot goes where it is aimed. The helper knows when it fired from its own ammunition.',
    },
    {
      title: 'It never turns back on the very next tic',
      text: 'Doom treats a turn key held either way as one long turn and doubles its speed after 5 tics, so turning left and right on alternate tics swung the player past a narrow enemy for ever. A reversal now waits one tic.',
    },
    {
      title: 'It chooses nothing',
      text: 'Which enemy, whether to fire, advance or wait, and what to do after a kill all come from Laya’s answers to the tree’s questions. The helper only carries them out at the game’s speed.',
    },
  ] as TimingStep[],
  tableTitle: 'Around this decision',
  tableNote:
    'Each decision of this recording near the one showing: when its state was read, when its action began, and how long Laya took.',
  tableColumns: ['Decision', 'State read', 'Action began', 'Late by', 'Laya took', 'Helper aimed at'],
  settingsTitle: 'This recording',
  settingsRows: (meta: RuleTreeEpisodeMeta): Array<[string, string]> => {
    const r = meta.realtime
    if (!r) return []
    return [
      [
        'Clock',
        r.clock === 'wall'
          ? 'the real clock: the game never waited'
          : `a lag of ${(r.lag ?? []).join(' to ')} tics, the game held while Laya answered`,
      ],
      ['Game played', `${r.tics} tics, ${(r.tics / 35).toFixed(1)} s`],
      ['From a state to its action (median)', `${r.lag_median} tics, about ${ticsMs(r.lag_median)} ms`],
      ['Laya per decision (median)', `${Math.round(r.walk_ms_median)} ms`],
      ['Tics the game fell behind the clock', String(r.late_tics)],
      [
        'The helper',
        `${r.track === 'screen' ? 'what is on the screen' : (r.track ?? 'none')}, ${r.reflex ?? 0} tics late; aims ${r.aim === 'box' ? 'until the crosshair is on the enemy' : 'within 3 degrees'}; fires ${r.fire === 'tap-narrow' ? 'with the trigger lifted between shots at a narrow enemy' : 'with the trigger held'}`,
      ],
    ]
  },
}

export const REALTIME_RESULTS = {
  title: 'Results: from 9 of 81 to 80 of 81',
  intro:
    'The same 81 benchmark seeds as the other tabs, each played once on the real clock with nothing paused. Laya cleared 9 of them the first time, with the rules made for a paused game, and 80 after the changes below.',
  pathColumns: ['Step', 'What changed', 'Cleared on the real clock, of 81'],
  path: [
    [
      'Start',
      'The rules made for a paused game (general-11), Laya trained on Kev’s paused answers, played without the pause',
      '9',
    ],
    [
      'A fair helper',
      'Laya picks the target and what to do; the helper aims between its answers, from what is on screen',
      '44',
    ],
    [
      'Aim onto the enemy',
      'Fire only once the crosshair is on the enemy (with the first loop’s rule, realtime-6)',
      '66',
    ],
    ['No swinging', 'Never turn back on the very next tic', '70'],
    ['Rules for real time', 'The rule writer’s second loop, on games played at Laya’s speed', '69'],
    ['Tap firing', 'Lift the trigger between shots at a narrow enemy (after two more loops)', '77'],
    [
      'More rules, and Laya retrained',
      'A fifth loop (realtime-12); Kev played it at Laya’s speed with the game held, and Laya learned its answers',
      '80',
    ],
  ] as string[][],
  pathSource:
    'docs/DOCUMENTATION.md, section 15. For comparison: the same seeds with the game paused for every decision, 76 (Laya on general-11); under answers 3 to 9 tics late at random instead of the real clock, the final setup clears 78.',
  loopsColumns: ['Loop', 'Training seeds', 'Answers late by', 'Rules kept', 'Training seeds cleared'],
  loops: [
    ['1', '600 to 619 (Kev answering)', '7 tics', '1', '15 → 20 of 20'],
    ['2', '600 to 659', '3 to 9 tics, at random', '1', '57 → 59 of 60'],
    ['3', '600 to 719', '3 to 9 tics', '1', '111 → 114 of 120'],
    ['4', '600 to 719', '3 to 9 tics', '1', '114 → 115 of 120'],
    ['5', '600 to 839, with tap firing', '3 to 9 tics', '3', '231 → 236 of 240'],
  ] as string[][],
  loopsSource:
    'Codex wrote every rule from a failed game; a rule was kept only when the training seeds cleared at least as well with it, and the 81 benchmark seeds were never used to write rules. The loops were run with Laya answering, except the first, where Kev did.',
  trainingColumns: ['Step', 'Number'],
  training: [
    [
      'Kev-27B played realtime-12 at Laya’s speed, the game held while it answered, seeds 500 to 599',
      '95 of 100 cleared',
    ],
    ['Questions kept to train on (seeds 500 to 589)', '6,922'],
    ['Questions kept apart to check (seeds 590 to 599)', '807'],
    ['Laya’s pick the same as Kev’s, on the 807, before training', '95.0%'],
    ['The same, after training (ruletree-rt-v2)', '98.3%'],
  ] as string[][],
  lagColumns: ['Answers late by', '0 tics (paused)', '2', '4', '7', '8', '12', '24', '40'],
  lag: [['Cleared, of 41', '39', '34', '32', '2', '2', '8', '0', '0']] as string[][],
  lagSource:
    'The first day’s measurement: the rules made for a paused game, each action started a fixed number of tics after its state, on 41 of the seeds. One action of lag (8 tics) is the worst: the aim turns twice for one angle. Kev-27B takes about 46 tics per decision, too slow to play this way without the game held.',
  totalsRows: (meta: RuleTreeEpisodeMeta): Array<[string, string]> => [
    [
      'Result',
      `${meta.result.outcome}, ${meta.result.decisions} decisions, ${meta.result.kills} kills, health ${meta.result.health}`,
    ],
    [
      'Questions to Laya',
      `${meta.calls}, about ${(meta.calls / Math.max(1, meta.decision_count)).toFixed(1)} per decision`,
    ],
    ['Misses', String(meta.misses)],
    ['Game time', meta.realtime ? `${(meta.realtime.tics / 35).toFixed(1)} s` : '–'],
    ['Cost', 'nothing: every answer was computed on this computer'],
  ],
}

export const REALTIME_REFERENCE = {
  title: 'Reference: how it works, the terms, and how this recording was made',
  rule: 'Every choice here is Laya’s; the helper only carries it out at the game’s speed.',
  ruleNote:
    'Laya judges every condition of the tree, picks the enemy or the goal to aim at, and the action of the rule its answers lead to is what is done. The program writes the state as text, asks the tree’s questions and follows the answers; the helper presses the player’s keys between answers, from what is on the screen, and decides nothing.',
  principles: [
    {
      title: 'The game never waits',
      text: 'The game runs at 35 tics a second while Laya answers. A decision’s action begins at the first tic after its answers are in, a few tics after its state was read.',
    },
    {
      title: 'Every condition is judged by Laya',
      text: 'The program never tests a condition itself. Laya’s answers decide where the walk goes and which enemy is the focus.',
    },
    {
      title: 'The helper is fair',
      text: 'It sees only what the player sees, presses only the player’s buttons, and chooses nothing. It aims at the focus Laya picked and does the action’s keys once the crosshair is on it.',
    },
    {
      title: 'The rules were written for this speed',
      text: 'The rule writer, Codex, wrote new rules from games played at Laya’s speed; Kev-27B then answered them in games played at that speed with the game held, and Laya learned its answers.',
    },
    {
      title: 'What is recorded',
      text: 'Every question Laya was asked, with its options, probabilities and time; when each state was read and its action began; what the helper aimed at; and every key pressed between decisions.',
    },
  ],
  provenance: {
    decider: 'Decided by',
    deciderValue: 'Laya, trained on Kev-27B’s real-time answers, on this computer',
    checkpoint: 'Checkpoint',
    clock: 'Played',
  },
  keys: [
    ['1 to 6', 'switch screens, in the order of the tabs'],
    ['← →', 'previous or next decision (with Shift, ten at a time)'],
    ['Home, End', 'first or last decision'],
    ['space', 'play or pause'],
  ] as Array<[string, string]>,
}
