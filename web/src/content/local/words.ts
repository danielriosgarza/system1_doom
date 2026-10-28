// Every word on the local models' screens: the rule tree played by Laya, a small model on the computer that plays,
// trained on the answers of Kev-27B, a larger open model on the same computer. No question goes to Jev. The numbers
// that are not read from the recording are docs/DOCUMENTATION.md section 15's, measured on 2026-10-27 on a Jetson
// Thor (Blackwell GPU, 122 GB of memory).
import type { RuleTreeEpisodeMeta } from '../../schema/bundle'
import { QUESTIONS, RULES_WATCH } from '../rules/words'

export const LOCAL_WATCH: typeof RULES_WATCH = {
  ...RULES_WATCH,
  title: 'Every action in this game comes from Laya’s answers to a few questions.',
  subtitle:
    'Laya is a small AI model (421 million parameters) that runs on the same computer as the game. It reads a description of the game, written as text, and a short list of statements, and says which statement is true. The way to play is written as rules. Each rule pairs a situation with an action, such as “an enemy is in view” with “turn toward it and fire”, and some rules are exceptions to a more general one. At each decision the game pauses, and the program asks Laya which general rule applies, then which of that rule’s exceptions applies, and so on until none does. The action of the last rule that applied is played for about a quarter of a second, and the next decision begins. Laya learned to answer these questions by copying the answers of Kev-27B, a larger AI model, in other games.',
  stripNote:
    'One row per question, in the order Laya was asked, and then the action that was played. The bar is Laya’s probability for the answer it gave. A focus row picks the one item, such as the most dangerous enemy, that the rules after it speak about. Click a question to see exactly what Laya was sent.',
  calls: (calls: number, ms: number) =>
    `${calls} ${calls === 1 ? 'question' : 'questions'} to Laya, ${Math.round(ms)} ms one after another, on this computer`,
  honesty: (meta: RuleTreeEpisodeMeta) =>
    `This is a recording, one image per decision. Real time shows each decision for its 8 tics of game time, about a quarter of a second. While it was played, the game waited for Laya’s answers, ${(meta.seconds / Math.max(1, meta.decision_count)).toFixed(2)} s per decision on average, the game’s own work included.`,
  cardsNote:
    'Each recording is one game of the deadly corridor, played with the tree general-11 on one seed, every question answered by Laya. Click a recording to play it from the start.',
  frameAlt: (index: number, count: number, health: number, action: string) =>
    `The game at decision ${index + 1} of ${count}, health ${Math.round(health)}. Laya’s answers led to: ${action}.`,
  decider: 'Laya',
  decidedBy: 'decided by Laya, on this computer',
}

export const LOCAL_QUESTIONS: typeof QUESTIONS = {
  ...QUESTIONS,
  title: (decision: number) => `Decision ${decision}: what Laya was asked, and what it answered`,
  intro:
    'At this decision Laya answered the questions below, one after another. Each was sent with the state of the game as text. Laya reads text only, so the screen was not sent. Pick a question to read the text exactly as Laya received it, and every probability it returned.',
  frame: 'The screen at this decision (not sent: Laya reads the text only)',
  focusNote:
    'The [focus] channel at the end was added by the focus question before this one. It names the item Laya picked there.',
  options: 'Its options, with Laya’s probabilities',
  cached:
    'Laya had answered this exact question, with the same text, earlier in this game. That answer was used again and no call was made.',
  timing: (ms: number) => `answered in ${Math.round(ms)} ms on this computer`,
}

/** One step of how Laya was trained. */
export interface TrainingStep {
  title: string
  text: string
}

export const LOCAL_TRAINED = {
  title: 'How Laya was trained: from Kev’s answers',
  intro:
    'Kev-27B answers this tree’s questions well without any training on them, but it is large: about half a second a question on this computer. Laya is small and fast, about 50 ms a question, but untrained it answers close to chance. So Kev played new games, every question it answered became an example, and Laya was trained to answer as Kev does.',
  steps: [
    {
      title: 'Kev plays new games',
      text: 'Kev-27B, a 27-billion-parameter model with open weights, walked this tree in 100 games on seeds 500 to 599, seeds not used for the games on this site or for the benchmark. It cleared 89 of them and answered every question the walks asked: 13,598 questions.',
    },
    {
      title: 'Every question becomes an example',
      text: 'Each question is kept as it was sent: the state text, with the [focus] channel when there was one, the question and its options, and Kev’s probability for every option. A question asked again with the same text is kept once. Seeds 500 to 589 gave 11,519 examples to train on; seeds 590 to 599 gave 1,258 more, kept apart to check the training.',
    },
    {
      title: 'Laya learns Kev’s answers',
      text: 'Laya read every example four times and was adjusted to give the same probabilities as Kev (soft cross-entropy), with the options shuffled each time so that it cannot learn their order. This took about 2 hours 20 minutes on the computer’s GPU.',
    },
    {
      title: 'The trained Laya is checked',
      text: 'On the 1,258 examples kept apart, Laya picked as Kev did 44% of the time before training and 99% after. It then played the 81 benchmark seeds and the games on this site.',
    },
  ] as TrainingStep[],
  facts: [
    ['Teacher', 'Kev-27B (jaredpalmer/kev-27b, tag v1.0), served on this computer'],
    ['Student', 'Laya (convaiinnovations/laya, English checkpoint, 421 million parameters)'],
    ['Teacher’s games', '100, seeds 500 to 599; 89 cleared'],
    ['Questions answered', '13,598, none missed'],
    ['Training examples', '11,519 from seeds 500 to 589, 400 of them kept to fit the probabilities’ scale'],
    ['Check examples', '1,258 from seeds 590 to 599'],
    ['Training', 'four passes, soft cross-entropy against Kev’s probabilities, options shuffled; about 2 h 20 min'],
    ['Same pick as Kev on the check examples', '44% before training, 99% after'],
    ['The trained checkpoint', 'ruletree-kev-v1, served by laya-serve on this computer'],
  ] as Array<[string, string]>,
  thorLead:
    'Kev-27B needs a large GPU, and on this computer it was first slow. Serving it in the way this GPU works best made it more than twice as fast, with the same answers, which made its 13,598 answers a matter of hours.',
  thorColumns: ['Setup', 'Question about a new state', 'Another question about the same state', 'Weights'],
  thorRows: [
    ['As installed', '1,093 ms', '339 ms', '51 GB'],
    ['Its fused kernels, and 8-bit (FP8) arithmetic', '498 ms', '170 ms', '27 GB'],
    ['The same, with 4-bit (NVFP4) arithmetic in the largest layers', '462 ms', '151 ms', '20 GB'],
  ] as Array<[string, string, string, string]>,
}

/** The models the Results screen compares, by the ids `models.json` uses; the recording's own is Laya trained on Kev. */
export const LOCAL_MODEL_NAMES: Record<string, string> = {
  played: 'Laya (played)',
  'kev-27b': 'Kev-27B, its teacher',
  laya: 'Laya, untrained',
}

export const LOCAL_RESULTS = {
  title: 'Results: how well Laya plays',
  intro:
    'The 81 benchmark seeds played with this tree by Laya, by its teacher Kev-27B, and by Laya before training; the questions of these recordings asked again of the other two; and this recording’s own numbers.',
  benchmarkColumns: [
    'Model',
    'Games cleared, of 81',
    '201 to 215',
    '301 to 315',
    '9 to 19',
    '20 to 39',
    '40 to 59',
    'Time per question',
    'Weights',
  ],
  benchmark: [
    ['Laya, trained on Kev', '76', '15', '13', '11', '19', '18', '50 ms', 'under 2 GB'],
    ['Kev-27B', '77', '15', '15', '11', '18', '18', '464 ms (151 ms again on the same state)', '20 GB'],
    ['Laya, untrained', '0', '0', '0', '0', '0', '0', '51 ms', 'under 2 GB'],
  ] as string[][],
  benchmarkSource:
    'The benchmark of 2026-10-27 (docs/DOCUMENTATION.md, section 15), not from this recording. Every losing game of the trained Laya was a death: four in the last fights, and seed 40 at the first pair of enemies, where Kev died too.',
  questionsColumns: ['Model', 'Right, of 477 questions the text settles', 'Same pick as the trained Laya, of 566'],
  questions: [
    ['Laya, trained on Kev (played)', '477', ''],
    ['Kev-27B', '477', '562'],
    ['Laya, untrained', '210', '259'],
  ] as string[][],
  questionsSource:
    'Every question asked in the four recordings here (seeds 9 to 12), asked again of Kev-27B and of the untrained Laya with the same text and options. For 477 of them the state text settles the answer, such as whether the threats list names an enemy or which angle band the target is in.',
  decisionLead: (n: number) =>
    `The ${n} questions asked at this decision: what Laya answered in play, and what its teacher and the untrained Laya answered when asked the same question.`,
  decisionNone: 'This recording has no answers from the other models.',
  question: 'Question',
  differs: 'differs from the trained Laya',
  focusAt: (node: string) => `focus of ${node}`,
  ruleAt: (node: string) => `at ${node}`,
  agreement: (same: number, of: number) => `${same} of ${of} as the trained Laya in this recording`,
  totalsRows: (meta: RuleTreeEpisodeMeta) => [
    [
      'Result',
      `${meta.result.outcome}, ${meta.result.decisions} decisions, ${meta.result.kills} kills, health ${meta.result.health}`,
    ],
    [
      'Questions to Laya',
      `${meta.calls}, about ${(meta.calls / Math.max(1, meta.decision_count)).toFixed(1)} per decision`,
    ],
    ['Misses', String(meta.misses)],
    ['Cost', 'nothing: every answer was computed on this computer'],
    [
      'Time to play',
      `${meta.seconds} s, about ${(meta.seconds / Math.max(1, meta.decision_count)).toFixed(2)} s per decision, the game included`,
    ],
  ],
}

export const LOCAL_REFERENCE = {
  title: 'Reference: how it works, the terms, and how this recording was made',
  rule: 'Every decision here is made by Laya, on this computer.',
  ruleNote:
    'No code written by hand chooses an action, and nothing is asked of a service outside this computer. Laya judges every condition, and the action played is the action of the rule that Laya’s answers lead to. The program walks the tree: it writes the state as text, asks Laya each question the tree defines, follows the answer and presses the keys.',
  principles: [
    {
      title: 'Every condition is judged by Laya',
      text: 'The program never tests a condition itself. A condition such as “The focus channel says the enemy is more than 400 units away” is an option of a question, and Laya’s answer decides whether the walk goes there.',
    },
    {
      title: 'Laya learned from Kev, not from rules written for it',
      text: 'Laya was trained on Kev-27B’s answers to the same kind of questions, in games on other seeds. Nothing in its training says what the right answer is; it learned to answer as Kev does.',
    },
    {
      title: 'The program describes, walks and presses keys',
      text: 'It writes the state as text from the game, asks the questions of the tree in order, follows Laya’s answers, and holds the action’s keys for 8 tics. It ranks and picks nothing. The one exception: when no rule at the top of the tree is true, it plays a random action code, drawn from the seed and the decision number.',
    },
    {
      title: 'A missed call is not replaced',
      text: 'When a call fails, the walk stops at the rule it has reached, and that rule’s action is played. The program does not answer in Laya’s place. In the recordings here no call missed.',
    },
    {
      title: 'The tree is the rule tree’s',
      text: 'The tree is general-11, the same tree as on the Rule tree tab, where How the rules were written tells how its rules came about. Here it is used as it is; only who answers its questions changes.',
    },
    {
      title: 'What is recorded',
      text: 'Every question Laya was asked is recorded, with its options, the probabilities, the answer and the time. These screens show those records.',
    },
  ],
  provenance: {
    decider: 'Decided by',
    deciderValue: 'Laya, trained on Kev-27B’s answers, on this computer',
    checkpoint: 'Checkpoint',
  },
  keys: [
    ['1 to 6', 'switch screens, in the order of the tabs'],
    ['← →', 'previous or next decision (with Shift, ten at a time)'],
    ['Home, End', 'first or last decision'],
    ['space', 'play or pause'],
  ] as Array<[string, string]>,
}
