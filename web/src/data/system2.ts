// System 2's records as the slow-system screen reads them: each cycle's reflectors and central, the history
// test's whole table, the trial's before-and-during table, and the configuration at the episode's start and end.
// Like readings.ts, nothing here ranks or scores; it only rearranges what reflections.jsonl recorded.
import type {
  Answer,
  Configuration,
  EpisodeMeta,
  HistoryTestResult,
  InstanceResult,
  ReflectionTrace,
  TestTick,
  TrialRow,
  TrialVerdictTrace,
} from '../schema/bundle'
import type { EpisodeBundle } from './loader'
import { CENTRAL, SENSES, type VersionEntry, isVerdict, recordTime, tickIndexAt, words } from './readings'

/** The nine reflectors, in the order System 2 calls them. */
export const REFLECTORS = [
  'survival_auditor',
  'combat_auditor',
  'navigation_auditor',
  'resource_auditor',
  'goal_auditor',
  'central_auditor',
  'menu_reflector',
  'strategy_reflector',
  'exploration_reflector',
] as const

/** What a cycle came to, in words. */
export function outcomeWords(outcome: ReflectionTrace['outcome']): string {
  switch (outcome) {
    case 'no_proposal':
      return 'no reflector proposed a change'
    case 'central_missed':
      return 'System 2’s central instance missed, so nothing changed'
    case 'none_chosen':
      return 'System 2’s central instance chose no change'
    case 'test_waiting':
      return 'the history test is waiting: too few stored decisions, or too few calls left in this cycle'
    case 'test_failed':
      return 'the history test rejected the change'
    case 'queued':
      return 'queued: it takes effect at the start of the next decision'
    case 'macro_requested':
      return 'a new macro was requested from the slow path'
    case 'macro_not_enqueued':
      return 'the slow path was busy or switched off, so no macro was requested'
  }
}

/** A change id in words: `widen:survival:pickups` reads “show survival the pickups channel”. */
export function changeWords(change: string | null | undefined): string {
  if (!change) return ''
  const [kind, a, b] = change.split(':')
  switch (kind) {
    case 'widen':
      return `show ${a} the ${b} channel`
    case 'narrow':
      return `stop showing ${a} the ${b} channel`
    case 'macro':
      return `request a new macro for the ${a} sense’s problem`
    case 'retire':
      return `retire the macro ${words(a)}`
    case 'strategy':
      return `make ${words(a)} the active strategy`
    case 'level':
      return `set the exploration level to ${a}`
    case 'revert':
      return `revert: ${changeWords(change.slice('revert:'.length))}`
    case 'none':
      return 'no change'
    case 'keep':
      return 'keep the configuration as it is'
    default:
      return words(change)
  }
}

export interface ReflectorRow {
  name: string
  /** It was called: the bounds left it at least one change. */
  called: boolean
  /** Why it was not called. */
  skipped: string | null
  /** The changes it was asked over, and those the bounds removed with the bound that removed each. */
  offered: string[]
  blocked: Array<{ change: string; bound: string }>
  speak: number | null
  /** Its speak probability reached yes_at. */
  spoke: boolean
  change: string | null
  changeP: number | null
  reason: string | null
  missed: boolean
  missReason: string | null
  /** It sent System 2’s central a proposal: it spoke, and for a change other than keep. */
  proposed: boolean
  result: InstanceResult | null
}

/** Every reflector of a cycle, in call order, called or not. */
export function reflectorRows(cycle: ReflectionTrace): ReflectorRow[] {
  const names = [
    ...REFLECTORS,
    ...Object.keys(cycle.reflectors ?? {}).filter((n) => !(REFLECTORS as readonly string[]).includes(n)),
  ]
  const proposers = new Set((cycle.messages ?? []).map((m) => m.reflector))
  return names
    .filter((name) => cycle.reflectors?.[name] || cycle.skipped?.[name] || cycle.offered?.[name])
    .map((name) => {
      const r = cycle.reflectors?.[name] ?? null
      const missed = !!r?.missed
      return {
        name,
        called: !!r,
        skipped: cycle.skipped?.[name] ?? null,
        offered: cycle.offered?.[name] ?? [],
        blocked: Object.entries(cycle.blocked?.[name] ?? {}).map(([change, bound]) => ({ change, bound })),
        speak: r?.speak ?? null,
        spoke: !!r?.spoke && !missed,
        change: missed ? null : (r?.change ?? null),
        changeP: missed || !r?.change ? null : (r.change_probabilities?.[r.change] ?? null),
        reason: missed ? null : (r?.reason ?? null),
        missed,
        missReason: r?.miss_reason ?? null,
        proposed: proposers.has(name),
        result: r,
      }
    })
}

/** The reflector whose proposal the cycle's central chose. */
export function proposerOf(cycle: ReflectionTrace | null): string | null {
  if (!cycle?.choice) return null
  return (cycle.messages ?? []).find((m) => m.change === cycle.choice)?.reflector ?? null
}

/** The verdict of the trial a cycle's change started, if it has one. */
export function verdictOf(
  bundle: Pick<EpisodeBundle, 'records'>,
  cycle: ReflectionTrace | null,
): TrialVerdictTrace | null {
  if (!cycle) return null
  return bundle.records.filter(isVerdict).find((v) => v.cycle_id === cycle.cycle_id) ?? null
}

// ---------------------------------------------------------------------------------------------
// The history test.

/** Each quality metric: its words and the stratum it is read on. */
export const METRICS: Record<string, { label: string; stratum: TestTick['stratum']; rule: string }> = {
  alarm_recall: {
    label: 'alarm recall',
    stratum: 'bad',
    rule: 'sent a message recommending an action other than the one executed',
  },
  good_agreement: {
    label: 'good agreement',
    stratum: 'good',
    rule: 'sent no message, or recommended the executed action',
  },
  quiet: { label: 'quiet', stratum: 'rest', rule: 'sent no message' },
  agreement_on_good: { label: 'agreement on good ticks', stratum: 'good', rule: 'chose the executed action' },
  disagreement_on_bad: { label: 'disagreement on bad ticks', stratum: 'bad', rule: 'chose another action' },
}

/** One answer of the test table in words: “spoke · weave fire (0.85)”, “silent (0.15)”, “missed (timeout)”. */
export function answerWords(answer: Answer | null | undefined, kind: HistoryTestResult['kind']): string {
  if (!answer) return '–'
  if (answer.missed) return `missed (${words(answer.miss_reason) || 'no answer'})`
  if (kind === 'central') return words(answer.action) || '–'
  const p = answer.speak === null || answer.speak === undefined ? '' : ` (${answer.speak.toFixed(2)})`
  return answer.spoke ? `spoke · ${words(answer.action)}${p}` : `silent${p}`
}

export interface TestSummary {
  status: HistoryTestResult['status']
  metrics: Array<{ id: string; label: string; stratum: string; rule: string; old: number | null; new: number | null }>
  /** The test's ticks, bad first, then good, then the rest, each in sample order. */
  ticks: TestTick[]
  counts: Record<TestTick['stratum'], number>
}

const STRATA: TestTick['stratum'][] = ['bad', 'good', 'rest']

export function testSummary(test: HistoryTestResult): TestSummary {
  const ids = [...new Set([...Object.keys(test.old?.quality ?? {}), ...Object.keys(test.new?.quality ?? {})])]
  const ticks = [...(test.ticks ?? [])].sort((a, b) => STRATA.indexOf(a.stratum) - STRATA.indexOf(b.stratum))
  const counts = { bad: 0, good: 0, rest: 0 }
  for (const t of ticks) counts[t.stratum] += 1
  return {
    status: test.status,
    metrics: ids.map((id) => ({
      id,
      label: METRICS[id]?.label ?? words(id),
      stratum: METRICS[id]?.stratum ?? '',
      rule: METRICS[id]?.rule ?? '',
      old: test.old?.quality[id] ?? null,
      new: test.new?.quality[id] ?? null,
    })),
    ticks,
    counts,
  }
}

// ---------------------------------------------------------------------------------------------
// The trial.

/** The trial table's rows, as the judge was shown them, with the keys of `TrialRow`. */
export const TRIAL_ROWS: Array<{ key: keyof TrialRow; label: string; digits: number }> = [
  { key: 'decisions', label: 'decisions', digits: 0 },
  { key: 'reward_per_decision', label: 'reward per decision', digits: 2 },
  { key: 'damage_per_decision', label: 'damage taken per decision', digits: 2 },
  { key: 'kills', label: 'kills', digits: 0 },
  { key: 'deaths', label: 'deaths', digits: 0 },
  { key: 'missed_ticks', label: 'missed decisions (no keys pressed)', digits: 0 },
  { key: 'followed', label: 'followed messages', digits: 0 },
  { key: 'paid_off', label: 'of which paid off', digits: 0 },
  { key: 'paid_off_rate', label: 'paid-off rate', digits: 2 },
]

export interface TrialInFlight {
  entry: VersionEntry
  /** Decisions observed by the tick showing, and the decisions the trial lasts. */
  decisions: number
  of: number
}

/** The tick a verdict came after. */
export function verdictTickIndex(bundle: Pick<EpisodeBundle, 'ticks'>, verdict: TrialVerdictTrace): number {
  return tickIndexAt(bundle.ticks, recordTime(verdict))
}

// ---------------------------------------------------------------------------------------------
// The configuration at the episode's start and end.

export interface ScopeChange {
  instance: string
  start: string[]
  end: string[]
  added: string[]
  removed: string[]
}

export interface ConfigurationChanges {
  scopes: ScopeChange[]
  macrosStart: string[]
  macrosEnd: string[]
  strategy: [string, string]
  level: [string, string]
}

const scopeOf = (c: Configuration, name: string) => (name === CENTRAL ? c.central.scope : c.senses[name]?.scope) ?? []

/** Each instance's scope, the admitted macros, the strategy and the level, at the episode's start and end. */
export function configurationChanges(meta: Pick<EpisodeMeta, 'configuration_start' | 'configuration_end'>) {
  const a = meta.configuration_start
  const b = meta.configuration_end
  const scopes = [...SENSES, CENTRAL].map((instance) => {
    const start = scopeOf(a, instance)
    const end = scopeOf(b, instance)
    return {
      instance,
      start,
      end,
      added: end.filter((c) => !start.includes(c)),
      removed: start.filter((c) => !end.includes(c)),
    }
  })
  return {
    scopes,
    macrosStart: (a.admitted_macros ?? []).map((m) => m.id),
    macrosEnd: (b.admitted_macros ?? []).map((m) => m.id),
    strategy: [a.active_strategy ?? '', b.active_strategy ?? ''],
    level: [a.exploration_level ?? 'exploit', b.exploration_level ?? 'exploit'],
  } satisfies ConfigurationChanges
}

/**
 * The cycle a screen opens on: the last one by this tick that changed or tested something, else the last one by
 * this tick; before the first cycle, the first one to come.
 */
export function defaultCycle(cycles: Array<{ cycle: ReflectionTrace; tickIndex: number }>, tickIndex: number) {
  const before = cycles.filter((c) => c.tickIndex <= tickIndex)
  if (!before.length) return cycles[0]?.cycle ?? null
  const busy = before.filter((c) => c.cycle.history_test || c.cycle.applied || c.cycle.outcome !== 'no_proposal')
  return (busy.at(-1) ?? before.at(-1))?.cycle ?? null
}
