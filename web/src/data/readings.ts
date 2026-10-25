// The readings every screen shows, taken from a schema 2 bundle as it is: what each d1-ultra instance saw and
// answered at a tick, the configuration versions System 2 made, the relevance ledger, and the values channel.
// Nothing here ranks or scores an action; it only rearranges what the trace recorded.
import type {
  Bounds,
  Configuration,
  EpisodeMeta,
  InstanceResult,
  ReflectionTrace,
  RelevanceCounts,
  RelevanceLedger,
  System2Note,
  TickTrace,
  TrialVerdictTrace,
} from '../schema/bundle'
import type { EpisodeBundle, System2Record } from './loader'

/** The five senses, in sense order. */
export const SENSES = ['survival', 'combat', 'navigation', 'resource', 'goal'] as const
export const CENTRAL = 'central'

/** Every evidence channel, in the fixed order a state text renders them. */
export const CHANNELS = [
  'vitals',
  'threats',
  'incoming',
  'outgoing',
  'pickups',
  'geometry',
  'position',
  'progress',
  'history',
  'frame',
  'menu',
  'projections',
  'values',
  'novelty',
  'archive',
  'exploration',
  'messages',
  'relevance',
] as const

/** Only the central instance may be shown these: what the senses said, their record, and the level. */
export const CENTRAL_ONLY = ['messages', 'relevance', 'exploration']

/** An id in words: `weave_fire` reads "weave fire". */
export const words = (id: string | null | undefined): string => (id ?? '').replaceAll('_', ' ')

/** A probability as a percentage; a dash when there is none. */
export function pct(p: number | null | undefined, digits = 0): string {
  return p === null || p === undefined || Number.isNaN(p) ? '–' : `${(p * 100).toFixed(digits)}%`
}

export function fmt(x: number | null | undefined, digits = 2): string {
  return x === null || x === undefined || Number.isNaN(x) ? '–' : x.toFixed(digits)
}

/** The bounds the episode started under, with the design's defaults for anything an older file lacks. */
export function boundsOf(
  meta: EpisodeMeta,
): Required<Pick<Bounds, 'yes_at' | 'trial_decisions' | 'return_steps' | 'return_gamma'>> & Bounds {
  const b = meta.configuration_start.bounds ?? {}
  return {
    ...b,
    yes_at: b.yes_at ?? 0.5,
    trial_decisions: b.trial_decisions ?? 60,
    return_steps: b.return_steps ?? 8,
    return_gamma: b.return_gamma ?? 0.9,
  }
}

// ---------------------------------------------------------------------------------------------
// The strip: five sense rows, the central row and Act, at one tick.

export interface SenseRow {
  name: string
  /** The sense sent a message: its speak probability reached yes_at. */
  spoke: boolean
  /** The speak probability, which a message carries as its strength; null when the call missed. */
  strength: number | null
  action: string | null
  reason: string | null
  missed: boolean
  missReason: string | null
  /** The central executed the action this sense asked for. */
  followed: boolean
}

/** The senses at this tick, in sense order, as the trace lists them. */
export function senseNames(tick: TickTrace): string[] {
  return Object.values(tick.instances)
    .filter((r) => r.kind === 'sense')
    .map((r) => r.name)
}

export function senseRows(tick: TickTrace): SenseRow[] {
  return senseNames(tick).map((name) => {
    const r = tick.instances[name] as InstanceResult
    const missed = !!r.missed
    const spoke = !!r.spoke && !missed
    return {
      name,
      spoke,
      strength: missed ? null : (r.strength ?? r.speak ?? null),
      action: missed ? null : (r.action ?? null),
      reason: missed ? null : (r.reason ?? null),
      missed,
      missReason: r.miss_reason ?? null,
      followed: spoke && !!tick.executed_action && r.action === tick.executed_action,
    }
  })
}

export interface CentralRow {
  kind: 'top' | 'drawn' | 'missed'
  action: string | null
  probability: number | null
  tie: boolean
  tied: string[]
  draw: number | null
  missReason: string | null
  /** How many messages the central heard. */
  heard: number
  level: 'exploit' | 'explore'
}

export function centralRow(tick: TickTrace): CentralRow {
  const central = tick.instances[CENTRAL]
  return {
    kind: tick.pick.kind,
    action: tick.pick.action ?? null,
    probability: tick.pick.probability ?? null,
    tie: !!tick.pick.tie,
    tied: tick.pick.tied ?? [],
    draw: tick.pick.draw ?? null,
    missReason: central?.miss_reason ?? null,
    heard: tick.messages?.length ?? 0,
    level: tick.exploration_level,
  }
}

/**
 * The keys held over Act's steps, in the order first pressed, each with the number of steps it was held when more
 * than one: "strafe left ×2, shoot ×4, strafe right ×2" for a weave that fires on every step.
 */
export function keysPressed(steps: string[]): string {
  const held = new Map<string, number>()
  for (const step of steps) {
    for (const key of step.split('+')) if (key && key !== 'idle') held.set(key, (held.get(key) ?? 0) + 1)
  }
  return [...held].map(([key, n]) => (n > 1 ? `${words(key)} ×${n}` : words(key))).join(', ') || 'nothing pressed'
}

export interface ActRow {
  action: string | null
  keys: string
  steps: string[]
}

export function actRow(tick: TickTrace): ActRow {
  return {
    action: tick.executed_action,
    keys: keysPressed(tick.primitive_steps_executed),
    steps: tick.primitive_steps_executed,
  }
}

// ---------------------------------------------------------------------------------------------
// The evidence an instance saw, verbatim, split at its channel headers.

export interface Section {
  /** The channel name in the header line, or '' for text before the first header. */
  channel: string
  /** The lines under the header, exactly as sent. */
  body: string
}

const HEADER = /^\[([a-z0-9_:]+)\]$/

/** The state text cut at each `[channel]` header line; nothing is dropped or reworded. */
export function sections(evidence: string): Section[] {
  const out: Section[] = []
  let current: { channel: string; lines: string[] } | null = null
  for (const line of evidence.split('\n')) {
    const match = HEADER.exec(line)
    if (match) {
      if (current) out.push({ channel: current.channel, body: current.lines.join('\n').trimEnd() })
      current = { channel: match[1] ?? '', lines: [] }
    } else if (current) {
      current.lines.push(line)
    } else if (line.trim()) {
      current = { channel: '', lines: [line] }
    }
  }
  if (current) out.push({ channel: current.channel, body: current.lines.join('\n').trimEnd() })
  return out
}

/** The channel headers in a state text, in the order they appear. */
export function shownChannels(evidence: string): string[] {
  return sections(evidence)
    .map((s) => s.channel)
    .filter(Boolean)
}

export interface Bar {
  label: string
  p: number
  /** The answer the instance gave: its top option. */
  top: boolean
}

/** A distribution as bars, highest first; the option named `chosen` is marked. */
export function bars(probs: Record<string, number> | undefined, chosen?: string | null): Bar[] {
  return Object.entries(probs ?? {})
    .map(([label, p]) => ({ label, p, top: label === chosen }))
    .sort((a, b) => b.p - a.p || a.label.localeCompare(b.label))
}

export interface InstanceView {
  name: string
  kind: InstanceResult['kind']
  scope: string[]
  /** Channels the instance was not shown at this tick. */
  hidden: string[]
  sections: Section[]
  imageRef: string | null
  speak: number | null
  spoke: boolean
  strength: number | null
  action: string | null
  actionBars: Bar[]
  reason: string | null
  reasonBars: Bar[]
  missed: boolean
  missReason: string | null
  error: string | null
  /** The raw answer as returned, when the call missed with one. */
  raw: string | null
  latency: number | null
  retries: number
  cost: number | null
}

export function instanceView(tick: TickTrace, name: string): InstanceView | null {
  const r = tick.instances[name]
  if (!r) return null
  const scope = r.scope ?? []
  const raw = r.raw_answer === null || r.raw_answer === undefined ? null : JSON.stringify(r.raw_answer, null, 2)
  return {
    name,
    kind: r.kind,
    scope,
    hidden: CHANNELS.filter((c) => !scope.includes(c)),
    sections: sections(r.evidence),
    imageRef: r.image_ref ?? null,
    speak: r.speak ?? null,
    spoke: !!r.spoke && !r.missed,
    strength: r.strength ?? r.speak ?? null,
    action: r.action ?? null,
    actionBars: bars(r.action_probabilities, r.action),
    reason: r.reason ?? null,
    reasonBars: bars(r.reason_probabilities, r.reason),
    missed: !!r.missed,
    missReason: r.miss_reason ?? null,
    error: r.error ?? null,
    raw,
    latency: r.latency_ms ?? null,
    retries: r.retries ?? 0,
    cost: r.usage?.cost ?? null,
  }
}

/** The concern an instance's instructions name, from the configuration in force. */
export function concernOf(configuration: Configuration, name: string): string | null {
  if (name === CENTRAL) return configuration.central.concern
  return configuration.senses[name]?.concern ?? null
}

// ---------------------------------------------------------------------------------------------
// System 2's records, placed on the episode's ticks.

export const isCycle = (r: System2Record): r is ReflectionTrace => (r.record ?? 'cycle') === 'cycle' && 'outcome' in r
export const isVerdict = (r: System2Record): r is TrialVerdictTrace => r.record === 'verdict'
export const isNote = (r: System2Record): r is System2Note => r.record === 'note'

/** When a record was written. */
export function recordTime(r: System2Record): number {
  return Date.parse(isCycle(r) ? r.started_at : r.timestamp)
}

/** The tick a moment belongs to: the last tick decided at or before it, the first tick when none was. */
export function tickIndexAt(ticks: TickTrace[], time: number): number {
  let found = 0
  for (let i = 0; i < ticks.length; i += 1) {
    if (Date.parse((ticks[i] as TickTrace).timestamp) <= time) found = i
    else break
  }
  return found
}

export interface PlacedCycle {
  cycle: ReflectionTrace
  tickIndex: number
}

/** Every System 2 cycle of the episode, with the tick it came after. */
export function placedCycles(bundle: Pick<EpisodeBundle, 'records' | 'ticks'>): PlacedCycle[] {
  return bundle.records
    .filter(isCycle)
    .map((cycle) => ({ cycle, tickIndex: tickIndexAt(bundle.ticks, recordTime(cycle)) }))
}

export type VersionStatus = 'start' | 'in trial' | 'kept' | 'reverted' | 'queued' | 'revert' | 'outside'

/** One configuration version: what made it, and what became of it. */
export interface VersionEntry {
  version: number
  /** The first tick decided under it; null when it never took effect in this episode (queued at the end). */
  tickIndex: number | null
  /** The change id (`widen:survival:pickups`, `macro:combat`, `revert:<id>`), or what happened. */
  change: string
  /** The change in words, from the configuration diff. */
  changes: string[]
  status: VersionStatus
  /** The cycle that chose the change; for a revert, the cycle whose change it undid. */
  cycle: ReflectionTrace | null
  /** The trial's verdict, when it has one. */
  verdict: TrialVerdictTrace | null
  /** The notes about this version, in order. */
  notes: System2Note[]
}

/** The configuration versions of the episode, from the one it started from, in version order. */
export function versionTimeline(bundle: Pick<EpisodeBundle, 'records' | 'ticks' | 'meta'>): VersionEntry[] {
  const { records, ticks, meta } = bundle
  const cycles = records.filter(isCycle)
  const verdicts = records.filter(isVerdict)
  const notes = records.filter(isNote)
  const firstTick = (version: number) => {
    const i = ticks.findIndex((t) => t.configuration_version === version)
    return i < 0 ? null : i
  }
  const startVersion = meta.configuration_start.version ?? 1
  const entries = new Map<number, VersionEntry>()
  entries.set(startVersion, {
    version: startVersion,
    tickIndex: 0,
    change: startVersion === 1 ? 'the design’s initial configuration' : 'as an earlier episode left it',
    changes: [],
    status: 'start',
    cycle: null,
    verdict: null,
    notes: [],
  })
  for (const note of notes) {
    if (note.version === null || note.version === undefined) continue
    if (note.kind === 'trial_started') {
      const cycle = cycles.find((c) => c.cycle_id === note.cycle_id) ?? null
      const verdict = verdicts.find((v) => v.cycle_id === note.cycle_id && v.trial.version === note.version) ?? null
      const admitted = notes.find((n) => n.kind === 'macro_admitted' && n.cycle_id === note.cycle_id)
      const macro = admitted ? /admitted (\S+) for/.exec(admitted.detail)?.[1] : undefined
      entries.set(note.version, {
        version: note.version,
        tickIndex: firstTick(note.version),
        change: cycle?.applied?.change ?? verdict?.trial.change ?? note.detail,
        changes: cycle?.applied?.diff?.changes ?? (macro ? [`admitted macros: + ${macro}`] : []),
        status: !verdict ? 'in trial' : verdict.trial.verdict === 'keep' ? 'kept' : 'reverted',
        cycle,
        verdict,
        notes: notes.filter((n) => n.cycle_id === note.cycle_id),
      })
    } else if (note.kind === 'revert_applied') {
      const verdict = verdicts.find((v) => v.trial.revert?.new_version === note.version) ?? null
      entries.set(note.version, {
        version: note.version,
        tickIndex: firstTick(note.version),
        change: `revert:${verdict?.trial.change ?? ''}`,
        changes: verdict?.trial.revert?.changes ?? [],
        status: 'revert',
        cycle: cycles.find((c) => c.cycle_id === verdict?.cycle_id) ?? null,
        verdict,
        notes: [note],
      })
    } else if ((note.kind === 'external_change' || note.kind === 'restored') && !entries.has(note.version)) {
      entries.set(note.version, {
        version: note.version,
        tickIndex: firstTick(note.version),
        change: note.detail,
        changes: [],
        status: 'outside',
        cycle: null,
        verdict: null,
        notes: [note],
      })
    }
  }
  // A change queued by the episode's last cycle takes effect at the next tick boundary, in the next episode.
  for (const cycle of cycles) {
    const next = cycle.applied?.diff?.new_version
    if (cycle.outcome === 'queued' && next !== undefined && !entries.has(next)) {
      entries.set(next, {
        version: next,
        tickIndex: firstTick(next),
        change: cycle.applied?.change ?? '',
        changes: cycle.applied?.diff?.changes ?? [],
        status: 'queued',
        cycle,
        verdict: null,
        notes: [],
      })
    }
  }
  return [...entries.values()].sort((a, b) => a.version - b.version)
}

export interface ConfigurationAt {
  version: number
  /** The version in force and what made it. */
  entry: VersionEntry | null
  /** The trial in flight at this tick: decisions observed so far and the decisions it lasts. */
  trial: { entry: VersionEntry; decisions: number; of: number } | null
}

/** The configuration a tick was decided under, its last change, and the trial in flight. */
export function configurationAt(
  bundle: Pick<EpisodeBundle, 'ticks' | 'meta' | 'records'>,
  timeline: VersionEntry[],
  tickIndex: number,
): ConfigurationAt {
  const tick = bundle.ticks[tickIndex]
  const version = tick?.configuration_version ?? bundle.meta.configuration_start.version ?? 1
  const entry = timeline.find((e) => e.version === version) ?? null
  let trial: ConfigurationAt['trial'] = null
  if (
    entry &&
    entry.tickIndex !== null &&
    (entry.status === 'in trial' || entry.status === 'kept' || entry.status === 'reverted')
  ) {
    const judged = entry.verdict ? tickIndexAt(bundle.ticks, recordTime(entry.verdict)) : null
    if (judged === null || tickIndex < judged) {
      const started = entry.verdict?.trial
      const of = started ? started.due_decision - started.started_decision : boundsOf(bundle.meta).trial_decisions
      trial = { entry, decisions: tickIndex - entry.tickIndex, of }
    }
  }
  return { version, entry, trial }
}

// ---------------------------------------------------------------------------------------------
// The relevance ledger: each sense's record per context, and what this episode added to it.

export type Counts = Required<RelevanceCounts>

export const ZERO: Counts = {
  spoke: 0,
  followed: 0,
  followed_paid: 0,
  overruled: 0,
  overruled_paid: 0,
  strength_paid_sum: 0,
  strength_paid_n: 0,
  strength_unpaid_sum: 0,
  strength_unpaid_n: 0,
}

const KEYS = Object.keys(ZERO) as Array<keyof Counts>

export function addCounts(a: RelevanceCounts, b: RelevanceCounts, sign = 1): Counts {
  const out = { ...ZERO }
  for (const k of KEYS) out[k] = (a[k] ?? 0) + sign * (b[k] ?? 0)
  return out
}

/** The share of followed messages that paid off; null when the sense was never followed. */
export function paidRate(c: RelevanceCounts): number | null {
  return c.followed ? (c.followed_paid ?? 0) / c.followed : null
}

/** The share of overruled messages whose chosen action paid off; null when never overruled. */
export function overruledRate(c: RelevanceCounts): number | null {
  return c.overruled ? (c.overruled_paid ?? 0) / c.overruled : null
}

export const meanStrength = (sum: number | undefined, n: number | undefined): number | null =>
  n ? (sum ?? 0) / n : null

export interface LedgerRow {
  sense: string
  context: string
  counts: Counts
}

/** The ledger's entries as rows, sense by sense in sense order, contexts by how often the sense spoke there. */
export function ledgerRows(entries: Record<string, RelevanceCounts> | undefined): LedgerRow[] {
  const rows = Object.entries(entries ?? {}).map(([key, counts]) => {
    const at = key.indexOf('|')
    return { sense: key.slice(0, at), context: key.slice(at + 1), counts: addCounts(ZERO, counts) }
  })
  const order = (s: string) => {
    const i = (SENSES as readonly string[]).indexOf(s)
    return i < 0 ? SENSES.length : i
  }
  return rows.sort((a, b) => order(a.sense) - order(b.sense) || b.counts.spoke - a.counts.spoke)
}

/** Each sense's record summed over every context. */
export function senseTotals(entries: Record<string, RelevanceCounts> | undefined): Record<string, Counts> {
  const out: Record<string, Counts> = Object.fromEntries(SENSES.map((s) => [s, { ...ZERO }]))
  for (const row of ledgerRows(entries)) out[row.sense] = addCounts(out[row.sense] ?? ZERO, row.counts)
  return out
}

/** The n-step discounted return of every decision, truncated at the episode's end (features.n_step_returns). */
export function nStepReturns(rewards: number[], steps: number, gamma: number): number[] {
  return rewards.map((_, t) => {
    let sum = 0
    for (let k = 0; k < steps && t + k < rewards.length; k += 1) sum += gamma ** k * (rewards[t + k] as number)
    return sum
  })
}

/**
 * What this episode added to the ledger, as `update_ledger` adds it: for every tick whose central answered, each
 * message is followed or overruled, and paid off when the decision's n-step return was positive.
 */
export function episodeEntries(ticks: TickTrace[], steps: number, gamma: number): Record<string, Counts> {
  const returns = nStepReturns(
    ticks.map((t) => t.reward_outcome),
    steps,
    gamma,
  )
  const entries: Record<string, Counts> = {}
  ticks.forEach((tick, i) => {
    if (!tick.executed_action) return
    const paid = (returns[i] ?? 0) > 0
    for (const msg of tick.messages ?? []) {
      const key = `${msg.sense}|${tick.context_signature}`
      const rec = (entries[key] ??= { ...ZERO })
      rec.spoke += 1
      if (msg.action === tick.executed_action) {
        rec.followed += 1
        if (paid) rec.followed_paid += 1
      } else {
        rec.overruled += 1
        if (paid) rec.overruled_paid += 1
      }
      if (paid) {
        rec.strength_paid_sum += msg.strength
        rec.strength_paid_n += 1
      } else {
        rec.strength_unpaid_sum += msg.strength
        rec.strength_unpaid_n += 1
      }
    }
  })
  return entries
}

export interface RelevancePoint {
  /** The ledger's episode count at this point. */
  episodes: number
  /** Where the point comes from: a recording's name, or this episode before or after. */
  label: string
  totals: Record<string, Counts>
}

/**
 * The open episode's ledger before and after it: the file holds the ledger after the episode, and the ticks
 * hold what the episode added, so the ledger before is the one minus the other. A live episode read while it
 * played holds the ledger as it started (`ledgerAt`), so there the file is the ledger before.
 */
export function ledgerBeforeAfter(
  bundle: Pick<EpisodeBundle, 'relevance' | 'ticks' | 'meta' | 'ledgerAt'>,
): RelevancePoint[] {
  const ledger: RelevanceLedger | null = bundle.relevance
  const live = bundle.ledgerAt === 'start'
  if (!ledger) return []
  const { return_steps, return_gamma } = boundsOf(bundle.meta)
  const added = episodeEntries(bundle.ticks, ledger.return_steps ?? return_steps, ledger.return_gamma ?? return_gamma)
  const file = ledger.entries ?? {}
  const keys = new Set([...Object.keys(file), ...Object.keys(added)])
  const other: Record<string, Counts> = {}
  for (const key of keys) other[key] = addCounts(file[key] ?? ZERO, added[key] ?? ZERO, live ? 1 : -1)
  const episodes = ledger.episodes ?? 0
  const before = live ? file : other
  const after = live ? other : file
  return [
    { episodes: live ? episodes : episodes - 1, label: 'before this episode', totals: senseTotals(before) },
    { episodes: live ? episodes + 1 : episodes, label: 'after this episode', totals: senseTotals(after) },
  ]
}

// ---------------------------------------------------------------------------------------------
// The values channel: the value networks' numbers as an instance was shown them.

export interface ValueRow {
  action: string
  predictions: Record<string, number>
  tried: number | null
}

export interface ValuesReading {
  /** The instance whose scope holds the values channel at this tick; null when none does. */
  instance: string | null
  /** The channel's first line, verbatim. */
  header: string
  rows: ValueRow[]
}

const VALUE_LINE = /^- (\S+): (.*?)(?:; tried (\d+) here)?$/

/** The values channel at a tick, parsed from the text an instance was sent. */
export function valuesAt(tick: TickTrace): ValuesReading {
  const holder = Object.values(tick.instances).find((r) => (r.scope ?? []).includes('values'))
  if (!holder) return { instance: null, header: '', rows: [] }
  const section = sections(holder.evidence).find((s) => s.channel === 'values')
  const lines = (section?.body ?? '').split('\n')
  const rows: ValueRow[] = []
  for (const line of lines.slice(1)) {
    const match = VALUE_LINE.exec(line)
    if (!match) continue
    const predictions: Record<string, number> = {}
    for (const part of (match[2] ?? '').split(', ')) {
      const [network, value] = part.split(' ')
      if (network && value !== undefined && !Number.isNaN(Number(value))) predictions[network] = Number(value)
    }
    rows.push({ action: match[1] ?? '', predictions, tried: match[3] === undefined ? null : Number(match[3]) })
  }
  return { instance: holder.name, header: lines[0] ?? '', rows }
}

// ---------------------------------------------------------------------------------------------
// The timeline's marks.

export type MarkKind = 'damage' | 'kill' | 'death' | 'miss' | 'drawn' | 'change' | 'cycle'

/** What happened at each tick that the timeline marks. */
export function tickMarks(bundle: Pick<EpisodeBundle, 'ticks' | 'records'>): MarkKind[][] {
  const marks: MarkKind[][] = bundle.ticks.map((t) => {
    const out: MarkKind[] = []
    if ((t.outcome.damage_taken ?? 0) > 0) out.push('damage')
    if ((t.outcome.kills_delta ?? 0) > 0) out.push('kill')
    if (t.outcome.died) out.push('death')
    if (Object.values(t.instances).some((r) => r.missed)) out.push('miss')
    if (t.pick.kind === 'drawn') out.push('drawn')
    if (t.configuration_changed) out.push('change')
    return out
  })
  for (const { tickIndex } of placedCycles(bundle)) marks[tickIndex]?.push('cycle')
  return marks
}
