// Every word on the real-time screens: the rule tree played by Laya without pausing the game, with a helper that aims
// between Laya's answers. The numbers that are not read from the recording are docs/DOCUMENTATION.md section 15's,
// measured on 2026-10-28 and 29 on a Jetson Thor (Blackwell GPU, 122 GB of memory).
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
  title: 'Laya plays the game in real time, without pausing it.',
  subtitle:
    'The game runs at 35 frames (tics) a second. At each decision, Laya reads a text description of the game and answers a few questions that lead through a tree of rules to an action. This takes about a tenth of a second, during which the game keeps running, so each action starts a few tics after the state it was based on. Between Laya’s answers, a helper turns the player toward the enemy that Laya selected, using only what is visible on the screen. Laya’s answers determine the target and the action; the helper only aims.',
  stripNote:
    'Each row is one question, in the order Laya was asked, followed by the action. The bar shows Laya’s probability for its answer. The last two rows show when the state was read, when the action started, and which keys the helper pressed until the next action. Click a question to see exactly what Laya was sent.',
  calls: (calls: number, ms: number) =>
    `${calls} ${calls === 1 ? 'question' : 'questions'} to Laya, ${Math.round(ms)} ms in total`,
  honesty: (meta: RuleTreeEpisodeMeta) => {
    const r = meta.realtime
    const late = r ? `${r.lag_median} tics (about ${ticsMs(r.lag_median)} ms)` : 'a few tics'
    return `This recording shows one image per decision. The game was not paused during play. The median delay between reading a state and starting its action was ${late}.`
  },
  cardsNote:
    'Each recording is one game of the deadly corridor, played in real time with the tree realtime-12. Laya answered every question and the helper did the aiming. Click a recording to play it from the start.',
  frameAlt: (index: number, count: number, health: number, action: string) =>
    `The game at decision ${index + 1} of ${count}, health ${Math.round(health)}. Action: ${action}.`,
  decider: 'Laya',
  decidedBy: 'decided by Laya, in real time',
  skill: (skill: string, caller: string) =>
    `${caller}’s action uses the ${skill} skill. The helper turns toward the focus until the crosshair is on it.`,
  actGloss: 'started when Laya’s answers arrived; the helper aims first',
}

export const REALTIME_QUESTIONS: typeof QUESTIONS = {
  ...QUESTIONS,
  title: (decision: number) => `Decision ${decision}: Laya’s questions and answers`,
  intro:
    'Laya answered the questions below one after another while the game kept running. Each question was sent with the state of the game, as text, from the moment the decision started. Laya reads text only; the screen was not sent. Select a question to see the exact text Laya received and the probability it gave each option.',
  frame: 'The screen when the state was read (not sent to Laya)',
  focusNote:
    'The [focus] channel at the end was added by the previous focus question. It names the item Laya selected, which is also what the helper aimed at.',
  options: 'Options, with Laya’s probabilities',
  cached:
    'Laya had already answered this question, with the same text, earlier in the game. The earlier answer was reused and no call was made.',
  timing: (ms: number) => `answered in ${Math.round(ms)} ms`,
}

/** The rows Watch's strip adds for a real-time decision. */
export const REALTIME_STRIP = {
  /** Where the action came from: the aim skill has no turning rules of its own here, the helper turns. */
  source: (node: string, skill: { caller: string; skill: string } | null): string | null =>
    skill && node === skill.skill ? `${skill.caller}’s action, with the helper aiming` : null,
  timingLabel: 'Timing',
  timing: (d: RuleTreeDecision) => {
    const late = (d.start_tic ?? 0) - (d.observed_tic ?? 0)
    return `State read at tic ${d.observed_tic}. Action started at tic ${d.start_tic}, ${late} ${late === 1 ? 'tic' : 'tics'} (${ticsMs(late)} ms) later. Laya’s answers took ${Math.round(d.walk_ms ?? 0)} ms.`
  },
  helperLabel: 'Helper',
  helper: (d: RuleTreeDecision) =>
    d.target
      ? `Aimed at: ${d.target}.${d.after ? ` After the target is killed: ${d.after === 'F001' ? 'walk forward toward the goal and fire' : `code ${d.after}`}.` : ''}`
      : 'No target. The action’s own keys were pressed.',
  pressedLabel: 'Keys pressed until the next action',
  pressed: (d: RuleTreeDecision) =>
    d.pressed && d.pressed.length > 0 ? pressedWords(d.pressed) : 'none (the game ended)',
}

/** One step of how a decision is made and acted on in real time. */
export interface TimingStep {
  title: string
  text: string
}

export const REALTIME_TIMING = {
  title: 'How it plays in real time',
  intro:
    'In the other tabs, the game is paused at each decision until all answers are in. Here the game keeps running at 35 tics a second. Laya takes about a tenth of a second (4 to 5 tics) to answer, and a helper presses the keys at every tic in between.',
  steps: [
    {
      title: 'The state is read',
      text: 'Every 8 tics, the program writes the state of the game as text, as in the other tabs, and Laya starts walking the tree. The game keeps running.',
    },
    {
      title: 'Laya answers',
      text: 'Laya answers the questions one after another, about 30 to 50 ms each, on the same computer. By the time the last answer arrives, the game has advanced a few tics.',
    },
    {
      title: 'The action starts',
      text: 'The action of the rule that Laya’s answers lead to starts at the next tic. Until then, the keys of the previous action stay pressed.',
    },
    {
      title: 'The helper aims',
      text: 'If the action aims at an enemy or at the goal that Laya selected, the helper turns toward it at every tic, based on the target’s position on the screen, until the crosshair is on it. It then presses the action’s keys, for example fire, or walk forward and fire. When the target is killed, it performs the follow-up action given by the rule.',
    },
  ] as TimingStep[],
  helperTitle: 'What the helper does',
  helper: [
    {
      title: 'It uses only what the player can see',
      text: 'It uses the enemies visible on the screen (the same information used to write the state text), with a delay of 4 tics; the direction the player faces and how far it has turned; and the position of the armor once it has been seen. An earlier version used the true positions of all enemies, including hidden ones. That gave it information a player does not have, so those results are not used here.',
    },
    {
      title: 'It presses only the player’s keys',
      text: 'Forward, back, sidestep, turn and fire, at most once per tic.',
    },
    {
      title: 'It fires only when the crosshair is on the target',
      text: 'An earlier version fired when the target was within 3 degrees, which is wider than a distant enemy, so many shots missed.',
    },
    {
      title: 'It releases the trigger between shots at narrow targets',
      text: 'When the trigger is held, Doom’s pistol fires every 14 tics, but every shot after the first is inaccurate. When the trigger is released and pressed again, it fires every 19 tics and each shot is accurate. The helper detects its own shots from the ammunition count.',
    },
    {
      title: 'It does not reverse its turn on the next tic',
      text: 'Doom treats a turn key held in either direction as one continuous turn and doubles the turning speed after 5 tics. Alternating left and right every tic therefore made the player overshoot narrow targets repeatedly. The helper now waits one tic before reversing.',
    },
    {
      title: 'It makes no decisions',
      text: 'The target, whether to fire, advance or wait, and what to do after a kill are all set by Laya’s answers to the tree’s questions. The helper only aims and presses the keys.',
    },
  ] as TimingStep[],
  tableTitle: 'Decisions around this one',
  tableNote:
    'For each decision near the current one: when its state was read, when its action started, the delay, and how long Laya took to answer.',
  tableColumns: ['Decision', 'State read', 'Action started', 'Delay', 'Laya’s answers', 'Helper’s target'],
  settingsTitle: 'This recording',
  settingsRows: (meta: RuleTreeEpisodeMeta): Array<[string, string]> => {
    const r = meta.realtime
    if (!r) return []
    return [
      [
        'Timing',
        r.clock === 'wall'
          ? 'real time: the game was never paused'
          : `a fixed delay of ${(r.lag ?? []).join(' to ')} tics, with the game paused while Laya answered`,
      ],
      ['Length of the game', `${r.tics} tics, ${(r.tics / 35).toFixed(1)} s`],
      ['Delay from state to action (median)', `${r.lag_median} tics, about ${ticsMs(r.lag_median)} ms`],
      ['Laya’s answers per decision (median)', `${Math.round(r.walk_ms_median)} ms`],
      ['Tics the program fell behind the game', String(r.late_tics)],
      [
        'Helper',
        `${r.track === 'screen' ? 'uses what is on the screen' : (r.track ?? 'none')}, with a ${r.reflex ?? 0}-tic delay; ${r.aim === 'box' ? 'fires when the crosshair is on the target' : 'fires within 3 degrees of the target'}; ${r.fire === 'tap-narrow' ? 'releases the trigger between shots at narrow targets' : 'holds the trigger'}`,
      ],
    ]
  },
}

export const REALTIME_RESULTS = {
  title: 'Results',
  intro:
    'The same 81 benchmark seeds as in the other tabs, each played once in real time. With the rules written for the paused game, Laya cleared 9. After the changes below, it cleared 80.',
  pathColumns: ['Step', 'Change', 'Cleared, of 81'],
  path: [
    [
      'Start',
      'Rules written for the paused game (general-11), played in real time by Laya trained on Kev’s answers',
      '9',
    ],
    ['Helper', 'Laya selects the target and the action; the helper aims between Laya’s answers', '44'],
    [
      'Aiming',
      'The helper fires only when the crosshair is on the target (with the first new rule, tree realtime-6)',
      '66',
    ],
    ['Turning', 'The helper waits one tic before reversing a turn', '70'],
    ['New rules', 'Second round of rule writing on games played in real time', '69'],
    ['Firing', 'The helper releases the trigger between shots at narrow targets (after two more rounds)', '77'],
    [
      'New rules and retrained Laya',
      'Fifth round of rule writing (tree realtime-12); Kev played these rules with Laya’s delay, and Laya was trained on Kev’s answers',
      '80',
    ],
  ] as string[][],
  pathSource:
    'From docs/DOCUMENTATION.md, section 15. For comparison, the same seeds with the game paused at each decision: 76 (Laya, general-11). With random delays of 3 to 9 tics instead of real time, the final version clears 78.',
  loopsColumns: ['Round', 'Training seeds', 'Delay', 'Rules kept', 'Training seeds cleared'],
  loops: [
    ['1', '600 to 619 (answered by Kev)', '7 tics', '1', '15 → 20 of 20'],
    ['2', '600 to 659', '3 to 9 tics, random', '1', '57 → 59 of 60'],
    ['3', '600 to 719', '3 to 9 tics, random', '1', '111 → 114 of 120'],
    ['4', '600 to 719', '3 to 9 tics, random', '1', '114 → 115 of 120'],
    ['5', '600 to 839, with the new firing', '3 to 9 tics, random', '3', '231 → 236 of 240'],
  ] as string[][],
  loopsSource:
    'In each round, Codex wrote a rule from a failed game, and the rule was kept only if the training seeds cleared at least as well with it. The 81 benchmark seeds were not used to write rules. Laya answered the questions in every round except the first, where Kev did.',
  trainingColumns: ['Step', 'Number'],
  training: [
    [
      'Kev-27B played realtime-12 on seeds 500 to 599, with the game paused while it answered and Laya’s delay added',
      '95 of 100 cleared',
    ],
    ['Questions used for training (seeds 500 to 589)', '6,922'],
    ['Questions kept for checking (seeds 590 to 599)', '807'],
    ['Laya picks the same answer as Kev, before training', '95.0%'],
    ['Laya picks the same answer as Kev, after training (ruletree-rt-v2)', '98.3%'],
  ] as string[][],
  lagColumns: ['Delay (tics)', '0 (paused)', '2', '4', '7', '8', '12', '24', '40'],
  lag: [['Cleared, of 41', '39', '34', '32', '2', '2', '8', '0', '0']] as string[][],
  lagSource:
    'First measurement, before the helper: the rules written for the paused game, with each action started a fixed number of tics after its state, on 41 of the seeds. A delay of about one action (8 tics) is the worst, because the next turn is decided before the previous one is visible. Kev-27B takes about 46 tics per decision, which is too slow to play in real time.',
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
    ['Cost', 'none; all answers were computed on this computer'],
  ],
}

export const REALTIME_REFERENCE = {
  title: 'Reference: how it works, terms, and how this recording was made',
  rule: 'Laya makes every decision; the helper aims and presses the keys.',
  ruleNote:
    'Laya evaluates every condition of the tree and selects the target. The action played is the action of the rule that Laya’s answers lead to. The program writes the state as text, asks the tree’s questions and follows the answers. Between answers, the helper aims at the selected target using what is on the screen and presses the action’s keys.',
  principles: [
    {
      title: 'The game is not paused',
      text: 'The game runs at 35 tics a second while Laya answers. Each action starts at the tic after Laya’s answers arrive, a few tics after its state was read.',
    },
    {
      title: 'Laya evaluates every condition',
      text: 'The program does not test conditions itself. Laya’s answers decide which rule applies and which enemy is the focus.',
    },
    {
      title: 'The helper uses only the player’s view and keys',
      text: 'It uses what is visible on the screen and presses only the player’s keys. It aims at the focus Laya selected and presses the action’s keys once the crosshair is on it.',
    },
    {
      title: 'The rules were written for this speed',
      text: 'Codex wrote new rules from games played in real time. Kev-27B then answered those rules’ questions in games with the same delay, and Laya was trained on Kev’s answers.',
    },
    {
      title: 'What is recorded',
      text: 'Every question Laya was asked, with its options, probabilities and time; when each state was read and when its action started; the helper’s target; and every key pressed between decisions.',
    },
  ],
  provenance: {
    decider: 'Decided by',
    deciderValue: 'Laya, trained on Kev-27B’s answers in real-time games, on this computer',
    checkpoint: 'Checkpoint',
    clock: 'Timing',
  },
  keys: [
    ['1 to 6', 'switch screens, in the order of the tabs'],
    ['← →', 'previous or next decision (with Shift, ten at a time)'],
    ['Home, End', 'first or last decision'],
    ['space', 'play or pause'],
  ] as Array<[string, string]>,
}
