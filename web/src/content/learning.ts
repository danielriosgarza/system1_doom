// The words of the Learning screen.
export const LEARNING = {
  title: 'Learning: what the agent keeps between episodes',
  intro:
    'Two things are learned, and both are used only as evidence. The relevance ledger is each sense’s track record per situation, which the central instance is shown. The value networks predict the return of each action, and one instance is shown their predictions in its values channel. Nothing learned is multiplied into a decision.',
  chart: {
    title: 'Share of followed messages that paid off, by sense',
    x: 'episodes in the ledger',
    y: 'paid off',
    none: 'Not enough data yet: the ledger needs at least one episode in which a message was followed.',
    tableTitle: 'The numbers',
    columns: ['Point', 'Episodes', 'Sense', 'Spoke', 'Followed', 'Paid off'],
    current: 'this episode',
  },
  values: {
    shownTo: (name: string) => `Shown to the ${name} sense at this decision, in its values channel:`,
    none: 'At this decision no instance’s scope includes the values channel, so no instance was shown these numbers.',
    noNetworks: 'This recording was played without value networks, and the values channel said so.',
    tried: 'tried here in training',
    action: 'Action',
    executed: 'executed',
  },
  trust: {
    checkpoint: (episodes: number, transitions: number, file: string) =>
      `The networks behind this recording: ${file}, trained on ${episodes} episode${episodes === 1 ? '' : 's'} and ${transitions.toLocaleString('en-US')} decisions.`,
    share: (share: string) =>
      `Network share ${share}: how familiar play has become to the networks, on a scale from 0 (nothing seen) to 1.`,
    here: 'The situation at this decision',
    seen: (n: number) => `seen ${n} time${n === 1 ? '' : 's'} in training`,
    columns: ['Action', 'Tried here in training', 'n / (n + 25)'],
    top: 'The situations training saw most often',
    none: 'This recording carries no training counts (no trust.json file).',
  },
}
