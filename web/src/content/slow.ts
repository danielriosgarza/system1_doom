// The words of The slow system screen.
import type { VersionStatus } from '../data/readings'
import type { System2EpisodeSummary } from '../schema/bundle'

export const SLOW = {
  title: 'The slow system: what System 2 changed, and why',
  intro:
    'System 2 runs on its own thread, reads the history of decisions and changes the configuration one change at a time. Its reflectors propose changes, its central instance chooses one or none, a scope change must first pass the history test, and every change then runs as a trial that the trial judge keeps or reverts. Each of those choices is one d1-ultra call, recorded here with the evidence it was shown.',
  off: 'System 2 was switched off for this episode, so the configuration stayed as it started.',
  noCycles:
    'System 2 ran no cycle during this episode: there were too few decisions, or a trial was in progress throughout.',
  noCyclesYet: 'No cycle yet: System 2 runs after every 20 new decisions.',
  selectCycle: 'Pick a cycle to read every reflector’s evidence and answers.',
  afterDecision: (n: number) => `after decision ${n}`,
  showDecision: 'Show that decision',
  later: 'later than the decision currently shown',
  proposedBy: (who: string) => `proposed by the ${who}`,
  choseAt: (p: string) => `chosen by System 2’s central at ${p}`,
  noProposals: 'No reflector sent a proposal, so System 2’s central instance was not called.',
  centralMissed: 'System 2’s central instance missed: nothing changed in this cycle.',
  skipped: 'not called',
  blockedTitle: 'Removed by the bounds before the call',
  offered: (n: number) => `${n} change${n === 1 ? '' : 's'} offered`,
  sawTitle: 'What it was shown, exactly as sent',
  changeTitle: 'Its change distribution',
  reasonTitle: 'Its reason distribution',
  proposalsTitle: 'The proposals it received',
  choiceTitle: 'Its choice distribution',
  notesTitle: 'Notes',
  windowsTitle: 'The time windows it read',
  test: {
    scope: 'Scope',
    oldScope: 'old scope',
    newScope: 'new scope',
    sample: (n: number, of: number | undefined) =>
      `${n} stored decisions asked again under the new scope, drawn from ${of ?? n} candidates`,
    columns: [
      'Sample',
      'Stratum',
      'Situation',
      'Return',
      'Executed',
      'Old scope’s answer',
      'New scope’s answer',
      'Old scope asked again',
      'Old',
      'New',
    ],
    metric: 'Metric',
    old: 'Old scope',
    new: 'New scope',
    composite: 'composite',
    gain: (gain: string, margin: string) => `composite gain ${gain} (needs at least +${margin})`,
    drop: (drop: string, allowed: string) => `largest metric drop ${drop} (at most ${allowed} allowed)`,
    noise: (agreement: string, n: number | undefined) =>
      `noise estimate: asked again on ${n ?? 0} decisions, the old scope repeated its stored answer ${agreement} of the time`,
    waiting: 'The test waits until the history holds enough decisions answered under the old scope.',
    hit: 'counts towards its metric',
    miss: 'does not count',
  },
  trial: {
    before: 'Before',
    during: 'During',
    inFlight: (n: number, of: number) =>
      `In progress: ${Math.min(n, of)} of ${of} decisions observed by the decision shown.`,
    noTrial: 'This cycle started no trial.',
    by: (by: string) => (by === 'no verdict' ? 'ended with no verdict: the judge never answered' : `ended by ${by}`),
    safety: 'the safety bound reverted it without asking the judge',
    judgeTitle: 'The judge’s answer',
    sawTitle: 'What the judge was shown, exactly as sent',
    revert: 'The revert restored the previous configuration as',
    attempt: (i: number) => `attempt ${i}`,
  },
  ledger: {
    totals: 'Each sense, over every situation',
    contexts: 'Each sense, per situation',
    all: 'all senses',
    showAll: (n: number) => `Show all ${n} situations`,
    showFewer: 'Show fewer',
    here: 'the situation at this decision',
    centralSaw: 'At this decision the central instance was shown this, in its relevance channel:',
    noRelevance: 'At this decision the central instance’s scope did not include the relevance channel.',
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
