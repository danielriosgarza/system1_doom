// The words of the Learning screen.
export const LEARNING = {
  title: 'Learning: what the agent keeps between episodes',
  intro:
    'Two things are learned, and both are only ever evidence: the relevance ledger, each sense’s record per situation, which the central is shown; and the value networks, whose predicted returns one instance is shown in its values channel. Nothing learned is multiplied into a decision.',
  chart: {
    title: 'Followed messages that paid off, by sense',
    x: 'episodes in the ledger',
    y: 'paid off',
    none: 'Not enough points yet: the ledger needs at least one episode with followed messages.',
    tableTitle: 'The numbers',
    columns: ['Point', 'Episodes', 'Sense', 'Spoke', 'Followed', 'Paid off'],
    current: 'this episode',
  },
  values: {
    shownTo: (name: string) => `Shown to the ${name} sense at this decision, under its values channel:`,
    none: 'No instance’s scope holds the values channel at this decision, so no instance saw these numbers.',
    noNetworks: 'This recording was played without value networks, so the values channel said so.',
    tried: 'tried here',
    action: 'Action',
    executed: 'executed',
  },
  trust: {
    checkpoint: (episodes: number, transitions: number, file: string) =>
      `The networks behind this recording: ${file}, trained on ${episodes} episode${episodes === 1 ? '' : 's'} and ${transitions.toLocaleString('en-US')} decisions.`,
    share: (share: string) => `Network share ${share}: how familiar play has become to the networks.`,
    here: 'This decision’s situation',
    seen: (n: number) => `seen ${n} time${n === 1 ? '' : 's'} in training`,
    columns: ['Action', 'Tried here in training', 'n / (n + 25)'],
    top: 'The situations training saw most',
    none: 'This recording carries no training counts (trust.json).',
  },
}
