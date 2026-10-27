// The Local models screen's words and numbers. The numbers are docs/DOCUMENTATION.md section 15's: measured on
// 2026-10-27 on a Jetson Thor (Blackwell GPU, 122 GB of memory), not read from the recording.

/** The models the page compares, by the ids `models.json` uses. Jev is the recording's own. */
export const MODEL_NAMES: Record<string, string> = {
  jev: 'Jev',
  'kev-27b': 'Kev-27B',
  laya: 'Laya',
  'laya-jev': 'Laya trained on Jev',
  'laya-kev': 'Laya trained on Kev',
}

export const MODELS = {
  title: 'Local models: answering without Jev',
  intro:
    'Jev is a paid service on the internet. Two open-weight models answer the same questions, in the same format, on the computer that plays the game: Kev-27B as it is, and Laya after training on answers. This screen shows how Laya was trained, how each model did, and what each answered at this decision.',
  workflow: [
    {
      title: 'Kev plays new games',
      text: 'Kev-27B, a 27-billion-parameter model with open weights, walked this tree in 100 games on seeds 500 to 599, seeds not used to write the rules or for the benchmark. It cleared 89 of them and answered every question the walks asked: 13,598 questions.',
    },
    {
      title: 'Every question becomes an example',
      text: 'Each question is kept as it was sent: the state text, with the [focus] channel when there was one, the question and its options, and Kev’s probability for every option. A question asked again with the same text is kept once. Seeds 500 to 589 gave 11,519 examples to train on; seeds 590 to 599 gave 1,258 more, kept apart to check the training. On those, Laya picked as Kev did 44% of the time before training and 99% after.',
    },
    {
      title: 'Laya learns Kev’s answers',
      text: 'Laya, a 421-million-parameter model, read every example four times and was adjusted to give the same probabilities as Kev (soft cross-entropy), with the options shuffled each time so that it cannot learn their order. This took about 2 hours 20 minutes on the computer’s GPU. No answer of Jev’s was used.',
    },
    {
      title: 'The trained Laya is checked',
      text: 'It answered the questions Jev answered in these recordings, with the same text, and played the 81 benchmark seeds with this tree. The table below has the results.',
    },
  ],
  columns: [
    'Model',
    'Where it runs',
    'Trained on',
    'Right, of 561 questions the text settles',
    'Same answer as Jev, of 709',
    'Games cleared, of 81',
    'Time per question',
    'Cost per game',
  ],
  modelsSource:
    'Questions: the 709 questions Jev answered in the five recordings, asked again with the same text and options. For 561 of them the state text settles the answer, such as whether the threats list names an enemy or which angle band the target is in. Games: the 81 benchmark seeds with this tree. From docs/DOCUMENTATION.md, section 15.',
  decisionLead: (n: number) => `The ${n} questions asked at this decision, and each model’s answer.`,
  decisionNone: 'This recording has no answers from the local models.',
  question: 'Question',
  jevColumn: 'Jev (played)',
  differs: 'differs from Jev',
  focusAt: (node: string) => `focus of ${node}`,
  ruleAt: (node: string) => `at ${node}`,
  agreement: (same: number, of: number) => `${same} of ${of} as Jev in this recording`,
  thorLead:
    'Kev-27B needs a large GPU. On this computer it was first slow; serving it in the way its GPU works best made it more than twice as fast, with the same answers.',
  thorColumns: ['Setup', 'Question about a new state', 'Another question about the same state', 'Weights'],
}

/** One row of the results table. */
export interface ModelRow {
  id: string
  where: string
  trained: string
  settled: string
  sameAsJev: string
  cleared: string
  time: string
  cost: string
}

export const MODEL_ROWS: ModelRow[] = [
  {
    id: 'jev',
    where: 'TypeSafe’s service',
    trained: 'not known',
    settled: '559',
    sameAsJev: '',
    cleared: '77 and 79',
    time: 'about 300 ms',
    cost: '$0.0125',
  },
  {
    id: 'kev-27b',
    where: 'this computer, 20 GB',
    trained: 'nothing from this game',
    settled: '560',
    sameAsJev: '697',
    cleared: '77',
    time: '464 ms',
    cost: '$0',
  },
  {
    id: 'laya',
    where: 'this computer, under 2 GB',
    trained: 'nothing from this game',
    settled: '242',
    sameAsJev: '322',
    cleared: '0',
    time: '51 ms',
    cost: '$0',
  },
  {
    id: 'laya-jev',
    where: 'this computer, under 2 GB',
    trained: '3,212 of Jev’s answers ($0.34)',
    settled: '561',
    sameAsJev: '698',
    cleared: '75',
    time: '51 ms',
    cost: '$0',
  },
  {
    id: 'laya-kev',
    where: 'this computer, under 2 GB',
    trained: '11,519 of Kev’s answers',
    settled: '561',
    sameAsJev: '696',
    cleared: '76',
    time: '50 ms',
    cost: '$0',
  },
]

/** Kev-27B served on the Thor, step by step (tools/kev_thor/README.md). */
export const THOR_ROWS: Array<[setup: string, fresh: string, again: string, weights: string]> = [
  ['As installed', '1,093 ms', '339 ms', '51 GB'],
  ['Its fused kernels, and 8-bit (FP8) arithmetic', '498 ms', '170 ms', '27 GB'],
  ['The same, with 4-bit (NVFP4) arithmetic in the largest layers', '462 ms', '151 ms', '20 GB'],
]
