// What was learned, as the Learning screen reads it: the relevance ledger as it grew over the recordings'
// episodes, and how much training is behind the value networks' numbers in the situation at hand.
import type { RelevanceLedger, TickTrace, TrustFile } from '../schema/bundle'
import type { EpisodeBundle } from './loader'
import { type Counts, SENSES, ledgerBeforeAfter, paidRate, senseTotals } from './readings'

export interface LedgerPoint {
  /** The ledger's episode count at this point. */
  episodes: number
  /** Where it comes from: “after corridor-11”, “before this episode”. */
  label: string
  totals: Record<string, Counts>
  /** The point belongs to the episode open now. */
  current: boolean
}

/**
 * The ledger's points, by episode count: the open episode's before and after, and every other recording's
 * ledger after its episode. Two points at one count are one ledger seen twice, so the open episode's is kept.
 */
export function ledgerPoints(
  bundle: Pick<EpisodeBundle, 'name' | 'relevance' | 'ticks' | 'meta' | 'ledgerAt'>,
  others: Array<{ name: string; ledger: RelevanceLedger | null }>,
): LedgerPoint[] {
  const points = new Map<number, LedgerPoint>()
  for (const p of ledgerBeforeAfter(bundle)) points.set(p.episodes, { ...p, current: true })
  for (const { name, ledger } of others) {
    if (!ledger || name === bundle.name) continue
    const episodes = ledger.episodes ?? 0
    if (!points.has(episodes)) {
      points.set(episodes, { episodes, label: `after ${name}`, totals: senseTotals(ledger.entries), current: false })
    }
  }
  return [...points.values()].sort((a, b) => a.episodes - b.episodes)
}

export interface SeriesPoint {
  episodes: number
  label: string
  /** The share of followed messages that paid off; null before the sense was ever followed. */
  value: number | null
  followed: number
  paid: number
  spoke: number
}

/** Each sense's paid-off share of followed messages at every point. */
export function paidSeries(points: LedgerPoint[]): Record<string, SeriesPoint[]> {
  return Object.fromEntries(
    SENSES.map((sense) => [
      sense,
      points.map((p) => {
        const c = p.totals[sense]
        return {
          episodes: p.episodes,
          label: p.label,
          value: c ? paidRate(c) : null,
          followed: c?.followed ?? 0,
          paid: c?.followed_paid ?? 0,
          spoke: c?.spoke ?? 0,
        }
      }),
    ]),
  )
}

export interface TriedRow {
  action: string
  /** How often training executed the action in this situation. */
  tried: number
  /** n / (n + trust_count), the share the old design blended by; a report here, it weighs nothing. */
  familiarity: number
}

/** The tries behind the values at this tick: each legal action's count in the tick's situation. */
export function triedHere(trust: TrustFile | null, tick: TickTrace): { seen: number; rows: TriedRow[] } | null {
  if (!trust) return null
  const context = tick.context_signature
  const k = trust.trust_count
  return {
    seen: trust.context_counts[context] ?? 0,
    rows: tick.available_actions.map((action) => {
      const tried = trust.action_counts[`${context}|${action}`] ?? 0
      return { action, tried, familiarity: tried / (tried + k) }
    }),
  }
}

/** The situations training saw most, with the tick's own marked. */
export function topContexts(trust: TrustFile | null, context: string, limit = 8) {
  if (!trust) return []
  const rows = Object.entries(trust.context_counts)
    .map(([signature, n]) => ({ signature, n, here: signature === context }))
    .sort((a, b) => b.n - a.n || a.signature.localeCompare(b.signature))
  const top = rows.slice(0, limit)
  const here = rows.find((r) => r.here)
  return here && !top.includes(here) ? [...top, here] : top
}
