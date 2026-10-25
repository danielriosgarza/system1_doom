import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import type { BundleIndexEntry, EpisodeMeta, ProposalTrace, TickTrace } from '../schema/bundle'
import { type LiveStatus, applyLiveEvent, fetchLiveStatus, mergedEpisodes } from './live'
import { type EpisodeBundle, type Fetcher, loadEpisode, parseJsonl } from './loader'

const FIXTURES = fileURLToPath(new URL('./__fixtures__/', import.meta.url))
const DIR = `${FIXTURES}episodes/mini/`
const meta = JSON.parse(await readFile(`${DIR}episode.json`, 'utf8')) as EpisodeMeta
const ticks = parseJsonl<TickTrace>(await readFile(`${DIR}ticks.jsonl`, 'utf8'), 'ticks.jsonl').sort(
  (a, b) => a.tick - b.tick,
)
const proposals = parseJsonl<ProposalTrace>(await readFile(`${DIR}proposals.jsonl`, 'utf8'), 'proposals.jsonl')

/** The fixture as an episode in progress: its first `n` ticks, its meta counting them, no proposals yet. */
function inProgress(n: number): EpisodeBundle {
  const held = ticks.slice(0, n)
  return {
    name: 'live-1',
    base: 'episodes/live-1',
    meta: { ...meta, name: 'live-1', tick_count: n, last_tick: held[n - 1]?.tick ?? 0 },
    ticks: held,
    proposals: [],
    metrics: null,
    evaluation: null,
    trust: null,
    macros: null,
  }
}

const entry = (name: string, seed: number): BundleIndexEntry => ({
  name,
  title: name,
  scenario: 'deadly_corridor.cfg',
  model: 'heuristics',
  seed,
  cleared: false,
  died: true,
  reward: 1,
  ticks: 3,
})

function status(patch: Partial<LiveStatus> = {}): LiveStatus {
  return {
    schema_version: 1,
    running: true,
    current: 'live-3',
    tick: 41,
    episodes: [entry('live-2', 8), entry('live-1', 7)],
    config: {
      scenario: 'deadly_corridor.cfg',
      seed: 7,
      model: 'heuristics',
      d1: false,
      codex: false,
      slow_path: true,
      deterministic: false,
      max_ticks: 500,
      pace_sec: 0.23,
      episodes: null,
    },
    started_at: '2026-10-24T20:00:00+00:00',
    ...patch,
  }
}

describe('applyLiveEvent', () => {
  it('appends a newer tick and moves the counts with it', () => {
    const bundle = inProgress(3)
    const next = applyLiveEvent(bundle, { type: 'tick', name: 'live-1', trace: ticks[3] as TickTrace })
    expect(next.ticks.map((t) => t.tick)).toEqual([0, 2, 4, 17])
    expect([next.meta.tick_count, next.meta.last_tick, next.meta.first_tick]).toEqual([4, 17, 0])
    expect(bundle.ticks).toHaveLength(3)
  })

  it('ignores a tick it already holds or an older one, and events for another episode', () => {
    const bundle = inProgress(3)
    expect(applyLiveEvent(bundle, { type: 'tick', name: 'live-1', trace: ticks[2] as TickTrace })).toBe(bundle)
    expect(applyLiveEvent(bundle, { type: 'tick', name: 'live-1', trace: ticks[0] as TickTrace })).toBe(bundle)
    expect(applyLiveEvent(bundle, { type: 'tick', name: 'live-2', trace: ticks[5] as TickTrace })).toBe(bundle)
    expect(applyLiveEvent(bundle, { type: 'stopped' })).toBe(bundle)
  })

  it('replaces the proposals, and the action catalog when the event carries one', () => {
    const bundle = inProgress(3)
    const listed = applyLiveEvent(bundle, { type: 'proposals', name: 'live-1', proposals })
    expect(listed.proposals).toBe(proposals)
    expect(listed.meta.actions).toBe(bundle.meta.actions)
    const actions = { ...meta.actions, evasive_burst_9: Object.values(meta.actions)[0]! }
    const grown = applyLiveEvent(listed, { type: 'proposals', name: 'live-1', proposals: [], actions })
    expect(grown.proposals).toEqual([])
    expect(Object.keys(grown.meta.actions)).toContain('evasive_burst_9')
  })

  it('takes the final meta at the end', () => {
    const final = { ...meta, name: 'live-1', title: 'the end' }
    const ended = applyLiveEvent(inProgress(6), { type: 'end', name: 'live-1', meta: final, entry: entry('live-1', 7) })
    expect(ended.meta).toBe(final)
    expect(ended.ticks).toHaveLength(6)
  })
})

describe('mergedEpisodes', () => {
  const index = { schema_version: 1, episodes: [entry('deadly_corridor-heuristics-9', 9)] }

  it('lists the episode in progress, then finished live episodes newest first, then the recordings', () => {
    const items = mergedEpisodes(index, status())
    expect(items.map((e) => [e.name, e.live])).toEqual([
      ['live-3', 'current'],
      ['live-2', 'finished'],
      ['live-1', 'finished'],
      ['deadly_corridor-heuristics-9', null],
    ])
    // serve gives episode k the seed config.seed + k - 1.
    expect(items[0]).toMatchObject({ seed: 9, tick: 41, entry: null })
  })

  it('is the index alone without live mode, and has no current line between episodes', () => {
    expect(mergedEpisodes(index, null).map((e) => e.name)).toEqual(['deadly_corridor-heuristics-9'])
    expect(mergedEpisodes(index, status({ current: null })).map((e) => e.live)).toEqual(['finished', 'finished', null])
  })
})

describe('loadEpisode for an episode in progress', () => {
  const fetcher =
    (overrides: Record<string, string>): Fetcher =>
    async (url) => {
      if (url in overrides) return new Response(overrides[url])
      try {
        return new Response(await readFile(FIXTURES + url, 'utf8'))
      } catch {
        return new Response('missing', { status: 404 })
      }
    }
  const opening = JSON.stringify({ ...meta, tick_count: 0, last_tick: 0 })

  it('accepts zero ticks', async () => {
    const files = { 'episodes/mini/episode.json': opening, 'episodes/mini/ticks.jsonl': '' }
    const bundle = await loadEpisode('mini', 'episodes', fetcher(files), { live: true })
    expect(bundle.ticks).toEqual([])
    expect(bundle.meta.tick_count).toBe(0)
    await expect(loadEpisode('mini', 'episodes', fetcher(files))).rejects.toThrow(/no ticks/)
  })

  it('takes the count from the ticks when the meta was read a moment earlier', async () => {
    const files = { 'episodes/mini/episode.json': opening }
    const bundle = await loadEpisode('mini', 'episodes', fetcher(files), { live: true })
    expect([bundle.meta.tick_count, bundle.meta.last_tick]).toEqual([6, 22])
    await expect(loadEpisode('mini', 'episodes', fetcher(files))).rejects.toThrow(
      /has 6 ticks, but episode.json says 0/,
    )
  })
})

describe('fetchLiveStatus', () => {
  it('is null when there is no live mode: a 404, a page instead of JSON, or no server', async () => {
    expect(await fetchLiveStatus(async () => new Response('missing', { status: 404 }))).toBeNull()
    expect(await fetchLiveStatus(async () => new Response('<!doctype html><title>app</title>'))).toBeNull()
    expect(
      await fetchLiveStatus(async () => {
        throw new TypeError('Failed to fetch')
      }),
    ).toBeNull()
  })

  it('reads the status serve writes', async () => {
    const live = await fetchLiveStatus(async (url) => {
      expect(url).toBe('live/status.json')
      return new Response(JSON.stringify(status()))
    })
    expect(live?.current).toBe('live-3')
  })
})
