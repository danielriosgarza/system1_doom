// Live mode: `python -m system1_doom.serve` plays episodes and streams each tick as it is decided, and each of
// System 2's records as it is written. A static deployment has no `live/status.json`, and then none of this shows.
import type { BundleIndexEntry, EpisodeMeta, ProposalTrace, TickTrace } from '../schema/bundle'
import {
  type EpisodeBundle,
  type EpisodeIndex,
  type Fetcher,
  SUPPORTED_SCHEMA_VERSION,
  type System2Record,
} from './loader'

/** The settings serve was started with; the app builds the serve command from them. */
export interface LiveConfig {
  scenario: string
  seed: number
  decider: 'd1-ultra'
  networks: EpisodeMeta['value_networks']
  call_budget_sec: number | null
  exploration_level: 'exploit' | 'explore' | null
  codex: boolean
  slow_path: boolean
  system2: boolean
  max_ticks: number
  pace_sec: number
  episodes: number | null
}

/** `live/status.json`: what is playing and what has been played. */
export interface LiveStatus {
  schema_version: number
  /** False once serve has stopped playing; it may still be serving the episodes. */
  running: boolean
  /** The episode in progress, or null between episodes and after the last. */
  current: string | null
  /** The newest tick of the episode in progress. */
  tick: number | null
  /** Finished live episodes, newest first. */
  episodes: BundleIndexEntry[]
  config: LiveConfig
  started_at: string
}

/** One server-sent event from `live/events`, named by `type`. */
export type LiveEvent =
  | { type: 'hello'; current: string | null; tick: number | null; episodes: BundleIndexEntry[] }
  | { type: 'start'; name: string; meta: EpisodeMeta }
  | { type: 'tick'; name: string; trace: TickTrace }
  /** The whole proposal list whenever it changes, and the action catalog with any macro it admitted. */
  | { type: 'proposals'; name: string; proposals: ProposalTrace[]; actions?: EpisodeMeta['actions'] }
  /** One of System 2's records; `name` is null when it was written between two episodes. */
  | { type: 'reflection'; name: string | null; record: System2Record }
  | { type: 'end'; name: string; meta: EpisodeMeta; entry: BundleIndexEntry }
  | { type: 'stopped' }

const EVENT_TYPES = ['hello', 'start', 'tick', 'proposals', 'reflection', 'end', 'stopped'] as const

/** A live episode's name, `live-<k>`; serve owns that pattern under `episodes/`. */
export const LIVE_NAME = /^live-(\d+)$/

/** The live status, or null when there is no live mode here: a 404, a network error or anything unexpected. */
export async function fetchLiveStatus(fetcher: Fetcher = (url) => fetch(url)): Promise<LiveStatus | null> {
  try {
    const response = await fetcher('live/status.json')
    if (!response.ok) return null
    const status = (await response.json()) as LiveStatus
    return status && status.schema_version === SUPPORTED_SCHEMA_VERSION ? status : null
  } catch {
    return null
  }
}

/**
 * Listen to `live/events`; returns the function that stops listening. The browser reconnects on its
 * own after a drop, and each connection starts with `hello`; events missed in between are not replayed.
 */
export function subscribeLive(onEvent: (event: LiveEvent) => void, onOpen?: () => void): () => void {
  const source = new EventSource('live/events')
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (message) => {
      let data: unknown
      try {
        data = JSON.parse((message as MessageEvent<string>).data)
      } catch {
        return
      }
      onEvent({ ...(data as object), type } as LiveEvent)
    })
  }
  if (onOpen) source.addEventListener('open', onOpen)
  return () => source.close()
}

/** What tells two of System 2's records apart: its kind, its cycle, and when it was written. */
export function recordKey(record: System2Record): string {
  const when = 'started_at' in record ? record.started_at : record.timestamp
  const kind = 'kind' in record && record.record === 'note' ? record.kind : ''
  return `${record.record ?? 'cycle'}|${record.cycle_id ?? ''}|${when}|${kind}`
}

/**
 * The bundle with one live event applied. A tick is appended only when it is newer than the last one
 * held, and a record only when it is not held yet, so events that repeat what the files already had change
 * nothing. Events for another episode, and events that carry no episode data, return the bundle as it was.
 */
export function applyLiveEvent(bundle: EpisodeBundle, event: LiveEvent): EpisodeBundle {
  if (!('name' in event) || event.name !== bundle.name) return bundle
  if (event.type === 'tick') {
    const last = bundle.ticks[bundle.ticks.length - 1]
    if (last && event.trace.tick <= last.tick) return bundle
    const ticks = [...bundle.ticks, event.trace]
    return {
      ...bundle,
      ticks,
      meta: { ...bundle.meta, tick_count: ticks.length, first_tick: ticks[0]?.tick ?? 0, last_tick: event.trace.tick },
    }
  }
  if (event.type === 'proposals') {
    return {
      ...bundle,
      proposals: event.proposals,
      meta: event.actions ? { ...bundle.meta, actions: event.actions } : bundle.meta,
    }
  }
  if (event.type === 'reflection') {
    const key = recordKey(event.record)
    if (bundle.records.some((r) => recordKey(r) === key)) return bundle
    return { ...bundle, records: [...bundle.records, event.record] }
  }
  if (event.type === 'end') return { ...bundle, meta: event.meta }
  return bundle
}

/** One line of the episode picker. */
export interface PickerEntry {
  name: string
  /** `current` is the episode in progress, `finished` a live episode that has ended, null a shipped recording. */
  live: 'current' | 'finished' | null
  /** The index line; the episode in progress has none yet. */
  entry: BundleIndexEntry | null
  /** The episode in progress: its seed (serve gives episode k the seed `config.seed + k - 1`) and newest tick. */
  seed: number
  tick: number | null
}

/** The picker's list: the episode in progress, then finished live episodes newest first, then the recordings. */
export function mergedEpisodes(index: EpisodeIndex | null, status: LiveStatus | null): PickerEntry[] {
  const out: PickerEntry[] = []
  if (status?.current) {
    const k = Number(LIVE_NAME.exec(status.current)?.[1] ?? 1)
    out.push({
      name: status.current,
      live: 'current',
      entry: null,
      seed: status.config.seed + k - 1,
      tick: status.tick,
    })
  }
  for (const entry of status?.episodes ?? []) {
    if (entry.name !== status?.current)
      out.push({ name: entry.name, live: 'finished', entry, seed: entry.seed, tick: null })
  }
  for (const entry of index?.episodes ?? []) {
    out.push({ name: entry.name, live: null, entry, seed: entry.seed, tick: null })
  }
  return out
}
