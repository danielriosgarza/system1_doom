// The words of the Reference screen.
export const REFERENCE = {
  title: 'Reference: how it works, the terms, and how this recording was made',
  rule: 'Every decision here is made by d1-ultra.',
  ruleNote:
    'The design has one rule: no hand-written rule may make a choice. Every choice is a d1-ultra instance, one call with its own evidence and its own fixed set of questions. The hand-written code only produces evidence and enforces limits.',
  principles: [
    {
      title: 'Every decision is a d1-ultra instance',
      text: 'The executed action is the central instance’s answer over the legal menu. A macro enters the menu only when the admit instance answers yes. Each of System 2’s choices (a reflector’s proposal, its central instance’s one change or none, the judge’s keep or revert) is an instance too.',
    },
    {
      title: 'Code produces evidence, enforces limits and presses keys',
      text: 'The channels are plain text. Every limit is defined in one place. The motor executes the chosen action’s fixed primitives, and aims and walks only at the targets the senses chose. None of this code ranks, scores or picks an action.',
    },
    {
      title: 'An instance sees only its scope',
      text: 'Its evidence text is its scope rendered and nothing else, and it receives the screen image only when the frame channel is in its scope. The survival sense is not shown the pickups channel unless System 2 widens its scope, and no sense is ever shown the other senses’ messages.',
    },
    {
      title: 'A miss is a miss',
      text: 'A sense that times out, fails or answers with an action outside the menu sends no message. A central instance that misses presses no keys. Nothing replaces a missing answer.',
    },
    {
      title: 'What is learned is evidence',
      text: 'The value networks’ predictions and the relevance ledger’s counts are channels of evidence text. Nothing learned is multiplied into a decision.',
    },
    {
      title: 'Everything is recorded',
      text: 'Every tick keeps each instance’s scope, its evidence exactly as sent, its full answers, its timing and its cost, and every System 2 cycle keeps the same for each reflector. These screens show those records.',
    },
  ],
  history: (removed: string[]) =>
    `An earlier design used a hand-written ${removed[0]} that weighed five ${removed[1]}s’ scores, with a ${removed[2]}, ${removed[3]}s, ${removed[4]}s and ${removed[5]}. None of these exist any more, and nothing on this site shows them.`,
  glossaryFilter: 'Filter the glossary',
  glossaryEmpty: 'No term matches.',
  aliases: 'also called',
  see: 'See it',
  code: 'In the code',
  provenance: {
    scenario: 'Scenario',
    decider: 'Decided by',
    seed: 'Seed',
    networks: 'Value networks',
    configuration: 'Configuration',
    slowPath: 'Slow path',
    budget: 'Call budget',
    calls: 'Calls',
    misses: 'Misses',
    result: 'Result',
    recorded: 'Recorded',
    command: 'To record one like it:',
    fromVersion: (v: number) =>
      `It starts from version ${v}: the configuration that earlier episodes in the same run folder left in runs/<scenario>/configuration.json. Every run starts from that file unless it is given --fresh-configuration.`,
    serve: 'To watch the system play live in this app:',
  },
  keys: [
    ['1 to 6', 'switch screens, in the order of the tabs'],
    ['← →', 'previous or next decision (with Shift, ten at a time)'],
    ['Home, End', 'first or last decision'],
    ['space', 'play or pause'],
    ['l', 'follow live play, when the serve command is running'],
  ] as Array<[string, string]>,
}
