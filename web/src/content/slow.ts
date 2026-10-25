// The words of The slow system screen.
import type { VersionStatus } from '../data/readings'
import type { System2EpisodeSummary } from '../schema/bundle'

export const SLOW = {
  title: 'The slow system: what System 2 changed, and why',
  intro:
    'System 2 reads the history on its own thread and changes the configuration one change at a time. Its reflectors propose, its central chooses one change or none, a scope change must first pass the history test, and every change is then a trial that the judge keeps or reverts. Each of those choices is one d1-ultra call, recorded here with what it saw.',
  off: 'System 2 was switched off for this episode, so the configuration stayed as it started.',
  noCycles: 'System 2 made no cycle during this episode: too few decisions, or a trial was in flight throughout.',
  noCyclesYet: 'No cycle yet: System 2 reflects every few decisions.',
  selectCycle: 'Pick a cycle to read every reflector’s evidence and answers.',
  afterDecision: (n: number) => `after decision ${n}`,
  showDecision: 'Show that decision',
  later: 'later than the decision showing',
  proposedBy: (who: string) => `proposed by the ${who}`,
  choseAt: (p: string) => `chosen by System 2’s central at ${p}`,
  noProposals: 'No reflector sent a proposal, so System 2’s central was not called.',
  centralMissed: 'System 2’s central missed: nothing changed this cycle.',
  skipped: 'not called',
  blockedTitle: 'Removed by the bounds before the call',
  offered: (n: number) => `${n} change${n === 1 ? '' : 's'} offered`,
  sawTitle: 'What it saw, verbatim',
  changeTitle: 'Its change distribution',
  reasonTitle: 'Its reason distribution',
  proposalsTitle: 'The proposals it heard',
  choiceTitle: 'Its choice distribution',
  notesTitle: 'Notes',
  windowsTitle: 'The windows it read',
  test: {
    scope: 'Scope',
    oldScope: 'old scope',
    newScope: 'new scope',
    sample: (n: number, of: number | undefined) =>
      `${n} stored ticks re-asked under the new scope, drawn from ${of ?? n} candidates`,
    columns: [
      'Sample',
      'Stratum',
      'Situation',
      'Return',
      'Executed',
      'Old scope’s answer',
      'New scope’s answer',
      'Noise re-ask',
      'Old',
      'New',
    ],
    metric: 'Metric',
    old: 'Old scope',
    new: 'New scope',
    composite: 'composite',
    gain: (gain: string, margin: string) => `composite gain ${gain} (needs at least +${margin})`,
    drop: (drop: string, allowed: string) => `worst metric drop ${drop} (at most ${allowed})`,
    noise: (agreement: string, n: number | undefined) =>
      `noise: the old scope re-asked on ${n ?? 0} ticks agreed with its stored answer ${agreement} of the time`,
    waiting: 'The test waits until the history holds enough ticks answered under the old scope.',
    hit: 'counts for its metric',
    miss: 'does not count',
  },
  trial: {
    before: 'Before',
    during: 'During',
    inFlight: (n: number, of: number) => `In flight: ${Math.min(n, of)} of ${of} decisions observed by this decision.`,
    noTrial: 'This cycle started no trial.',
    by: (by: string) => `ended by ${by}`,
    safety: 'the safety bound reverted it without asking the judge',
    judgeTitle: 'The judge’s answer',
    sawTitle: 'What the judge saw, verbatim',
    revert: 'The revert restores the previous configuration:',
    attempt: (i: number) => `attempt ${i}`,
  },
  ledger: {
    totals: 'Each sense over every situation',
    contexts: 'Each sense per situation',
    all: 'all senses',
    showAll: (n: number) => `Show all ${n} situations`,
    showFewer: 'Show fewer',
    here: 'the situation at this decision',
    centralSaw: 'At this decision the central was shown, in its relevance channel:',
    noRelevance: 'The central’s scope did not hold the relevance channel at this decision.',
    none: 'This recording carries no relevance ledger.',
    columns: ['Sense', 'Situation', 'Spoke', 'Followed', 'Paid off', 'Overruled', 'Overruled, paid off', 'Strength'],
    added: 'this episode',
  },
  changes: {
    instance: 'Instance',
    start: 'At the start',
    end: 'At the end',
    macros: 'Admitted macros',
    strategy: 'Active strategy',
    level: 'Exploration level',
    none: 'none',
    same: 'unchanged',
  },
}

export const STATUS_WORDS: Record<VersionStatus, string> = {
  start: 'the episode started here',
  'in trial': 'in trial',
  kept: 'kept',
  reverted: 'reverted',
  queued: 'queued for the next episode',
  revert: 'a revert',
  outside: 'changed outside System 2',
}

/** The episode's System 2 counts in one line. */
export function summaryWords(s: System2EpisodeSummary | null | undefined): string[] {
  if (!s) return []
  const n = (k: number | undefined, one: string, many = `${one}s`) => `${k ?? 0} ${(k ?? 0) === 1 ? one : many}`
  return [
    n(s.cycles, 'cycle'),
    `${n(s.tests, 'history test')}, ${s.tests_passed ?? 0} passed`,
    `${n(s.trials_started, 'trial')} started, ${s.kept ?? 0} kept, ${s.reverted ?? 0} reverted`,
    `${n(s.calls, 'd1-ultra call')}, $${(s.usd ?? 0).toFixed(4)}`,
  ]
}
