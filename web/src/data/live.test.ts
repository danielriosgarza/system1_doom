import { describe, expect, it } from 'vitest'
import type { BundleIndexEntry, ReflectionTrace, System2Note } from '../schema/bundle'
import { FIXTURE, diskFetcher, loadFixture } from '../test/fixture'
import { type LiveStatus, applyLiveEvent, fetchLiveStatus, mergedEpisodes, recordKey } from './live'
import { type EpisodeBundle, loadEpisode } from './loader'

const fixture = await loadFixture()
const { meta, ticks, proposals, records } = fixture

/** The fixture as an episode in progress: its first `n` ticks and records, its meta counting them, no proposals. */
function inProgress(n: number, held = 0): EpisodeBundle {
  const shown = ticks.slice(0, n)
  return {
    ...fixture,
    name: 'live-1',
    base: 'episodes/live-1',
    meta: { ...meta, name: 'live-1', tick_count: n, last_tick: shown[n - 1]?.tick ?? 0 },
    ticks: shown,
    proposals: [],
    records: records.slice(0, held),
  }
}

const entry = (name: string, seed: number): BundleIndexEntry => ({
  name,
  title: name,
  scenario: 'deadly_corridor.cfg',
  value_networks: 'best',
  seed,
  cleared: false,
  died: true,
  reward: 1,
  ticks: 3,
  kills: 0,
  configuration_start: 1,
  configuration_end: 1,
})

function status(patch: Partial<LiveStatus> = {}): LiveStatus {
  return {
    schema_version: 2,
    running: true,
    current: 'live-3',
    tick: 41,
    episodes: [entry('live-2', 8), entry('live-1', 7)],
    config: {
      scenario: 'deadly_corridor.cfg',
      seed: 7,
      decider: 'd1-ultra',
      networks: 'best',
      call_budget_sec: null,
      exploration_level: null,
      codex: false,
      slow_path: true,
      system2: true,
      max_ticks: 500,
      pace_sec: 0.23,
      episodes: null,
    },
    started_at: '2026-10-25T20:00:00+00:00',
    ...patch,
  }
}

describe('applyLiveEvent', () => {
  it('appends a newer tick and moves the counts with it', () => {
    const bundle = inProgress(3)
    const next = applyLiveEvent(bundle, { type: 'tick', name: 'live-1', trace: ticks[3]! })
    expect(next.ticks.map((t) => t.tick)).toEqual([0, 1, 2, 3])
    expect([next.meta.tick_count, next.meta.last_tick, next.meta.first_tick]).toEqual([4, 3, 0])
    expect(bundle.ticks).toHaveLength(3)
  })

  it('ignores a tick it already holds or an older one, and events for another episode', () => {
    const bundle = inProgress(3)
    expect(applyLiveEvent(bundle, { type: 'tick', name: 'live-1', trace: ticks[2]! })).toBe(bundle)
    expect(applyLiveEvent(bundle, { type: 'tick', name: 'live-1', trace: ticks[0]! })).toBe(bundle)
    expect(applyLiveEvent(bundle, { type: 'tick', name: 'live-2', trace: ticks[5]! })).toBe(bundle)
    expect(applyLiveEvent(bundle, { type: 'stopped' })).toBe(bundle)
  })

  it('appends each of System 2’s records once, in the order they arrive', () => {
    const bundle = inProgress(10)
    const first = applyLiveEvent(bundle, { type: 'reflection', name: 'live-1', record: records[0]! })
    expect(first.records).toEqual([records[0]])
    expect(applyLiveEvent(first, { type: 'reflection', name: 'live-1', record: records[0]! })).toBe(first)
    const second = applyLiveEvent(first, { type: 'reflection', name: 'live-1', record: records[1]! })
    expect(second.records).toEqual([records[0], records[1]])
    // A record written between two episodes, or for another, is not this episode's.
    expect(applyLiveEvent(second, { type: 'reflection', name: null, record: records[2]! })).toBe(second)
    expect(applyLiveEvent(second, { type: 'reflection', name: 'live-2', record: records[2]! })).toBe(second)
  })

  it('tells records apart by kind, cycle and time', () => {
    const cycle = records.find((r) => r.record === 'cycle') as ReflectionTrace
    const note = records.find((r) => r.record === 'note') as System2Note
    expect(recordKey(cycle)).toBe(`cycle|${cycle.cycle_id}|${cycle.started_at}|`)
    expect(recordKey(note)).toBe(`note|${note.cycle_id}|${note.timestamp}|${note.kind}`)
    expect(new Set(records.map(recordKey)).size).toBe(records.length)
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
  const index = { schema_version: 2, episodes: [entry('corridor-9', 9)] }

  it('lists the episode in progress, then finished live episodes newest first, then the recordings', () => {
    const items = mergedEpisodes(index, status())
    expect(items.map((e) => [e.name, e.live])).toEqual([
      ['live-3', 'current'],
      ['live-2', 'finished'],
      ['live-1', 'finished'],
      ['corridor-9', null],
    ])
    // serve gives episode k the seed config.seed + k - 1.
    expect(items[0]).toMatchObject({ seed: 9, tick: 41, entry: null })
  })

  it('is the index alone without live mode, and has no current line between episodes', () => {
    expect(mergedEpisodes(index, null).map((e) => e.name)).toEqual(['corridor-9'])
    expect(mergedEpisodes(index, status({ current: null })).map((e) => e.live)).toEqual(['finished', 'finished', null])
  })
})

describe('loadEpisode for an episode in progress', () => {
  const opening = JSON.stringify({ ...meta, tick_count: 0, last_tick: 0 })
  const path = `episodes/${FIXTURE}`

  it('accepts zero ticks and no records yet', async () => {
    const files = {
      [`${path}/episode.json`]: opening,
      [`${path}/ticks.jsonl`]: '',
      [`${path}/reflections.jsonl`]: '',
    }
    const bundle = await loadEpisode(FIXTURE, 'episodes', diskFetcher(files), { live: true })
    expect(bundle.ticks).toEqual([])
    expect(bundle.records).toEqual([])
    expect(bundle.meta.tick_count).toBe(0)
    await expect(loadEpisode(FIXTURE, 'episodes', diskFetcher(files))).rejects.toThrow(/no ticks/)
  })

  it('takes the count from the ticks when the meta was read a moment earlier', async () => {
    const files = { [`${path}/episode.json`]: opening }
    const bundle = await loadEpisode(FIXTURE, 'episodes', diskFetcher(files), { live: true })
    expect([bundle.meta.tick_count, bundle.meta.last_tick]).toEqual([40, 39])
  })

  it('reads the ledger the episode started from, which serve writes before the first tick', async () => {
    const meta0 = JSON.stringify({ ...meta, tick_count: 0, last_tick: 0, files: [] })
    const bundle = await loadEpisode(FIXTURE, 'episodes', diskFetcher({ [`${path}/episode.json`]: meta0 }), {
      live: true,
    })
    expect(bundle.relevance?.episodes).toBe(3)
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

  it('reads the status serve writes, and ignores a serve of the old schema', async () => {
    const live = await fetchLiveStatus(async (url) => {
      expect(url).toBe('live/status.json')
      return new Response(JSON.stringify(status()))
    })
    expect(live?.current).toBe('live-3')
    expect(live?.config.decider).toBe('d1-ultra')
    const old = await fetchLiveStatus(async () => new Response(JSON.stringify(status({ schema_version: 1 }))))
    expect(old).toBeNull()
  })
})
