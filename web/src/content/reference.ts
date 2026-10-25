// The words of the Reference screen.
export const REFERENCE = {
  title: 'Reference: how it works, the words, and how this recording was made',
  rule: 'Every decision here is made by d1-ultra.',
  ruleNote:
    'Hand-written rules that choose are cheating. Every choice is a d1-ultra instance: one call with its own evidence and its own finite questions. What stays hand-written is evidence and bounds.',
  principles: [
    {
      title: 'Every decision is a d1-ultra instance',
      text: 'The executed action is the central’s answer over the legal menu; a macro enters the menu only on the admit instance’s yes; and each of System 2’s choices (a reflector’s proposal, its central’s one change or none, the judge’s keep or revert) is an instance too.',
    },
    {
      title: 'Code renders evidence, keeps bounds and presses keys',
      text: 'The channels are plain text; every limit sits in one place; the motor executes the chosen action’s fixed primitives. None of it ranks, scores or picks.',
    },
    {
      title: 'An instance sees only its scope',
      text: 'Its state text is its scope rendered and nothing else, and it gets the frame only when frame is in scope. The survival sense never sees the pickups unless System 2 widens its scope, and a sense never sees the messages.',
    },
    {
      title: 'A miss is a miss',
      text: 'A sense that times out, fails or answers off the menu is silent; a central miss holds no keys. Nothing stands in for a missing answer.',
    },
    {
      title: 'What is learned is evidence',
      text: 'The value networks’ predictions and the relevance ledger’s counts are channels; nothing learned is multiplied into a decision.',
    },
    {
      title: 'Everything is traceable',
      text: 'Every tick keeps each instance’s scope, verbatim evidence, full answers, timing and cost, and every System 2 cycle keeps each reflector’s; that is what these screens show.',
    },
  ],
  history: (removed: string[]) =>
    `Before this design, a hand-written ${removed[0]} weighed five ${removed[1]}s’ scores, with a ${removed[2]}, ${removed[3]}s, ${removed[4]}s and ${removed[5]}; none of them exist any more, and nothing here shows them.`,
  glossaryFilter: 'Filter the glossary',
  glossaryEmpty: 'No term matches.',
  aliases: 'also',
  see: 'See it',
  code: 'In the code',
  provenance: {
    scenario: 'Scenario',
    seed: 'Seed',
    networks: 'Value networks',
    configuration: 'Configuration',
    slowPath: 'Slow path',
    budget: 'Call budget',
    calls: 'd1-ultra calls',
    misses: 'Misses',
    result: 'Result',
    recorded: 'Recorded',
    command: 'To record one like it:',
    fromVersion: (v: number) =>
      `It starts from version ${v}: the configuration earlier episodes on the same run folder left in runs/<scenario>/configuration.json, which every run starts from unless told --fresh-configuration.`,
    serve: 'To watch the system play live in this app:',
  },
  keys: [
    ['1 to 6', 'the screens, in the order of the tabs'],
    ['← →', 'the previous or next decision (with shift, ten)'],
    ['Home, End', 'the first or last decision'],
    ['space', 'play or pause'],
    ['l', 'follow live play, when serve is running'],
  ] as Array<[string, string]>,
}
