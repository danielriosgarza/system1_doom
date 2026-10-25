import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import type { BundleIndexEntry } from '../schema/bundle'
import {
  BundleError,
  type Fetcher,
  defaultEpisode,
  endFrameUrl,
  frameUrl,
  loadEpisode,
  loadIndex,
  parseJsonl,
} from './loader'

const FIXTURES = fileURLToPath(new URL('./__fixtures__/', import.meta.url))

/** Serves files under the fixture folder the way the dev server serves public/. */
function diskFetcher(overrides: Record<string, string | null> = {}): Fetcher {
  return async (url) => {
    if (url in overrides) {
      const body = overrides[url]
      return body === null ? new Response('missing', { status: 404 }) : new Response(body)
    }
    try {
      return new Response(await readFile(FIXTURES + url, 'utf8'))
    } catch {
      return new Response('missing', { status: 404 })
    }
  }
}

describe('loadIndex', () => {
  it('lists the fixture episode', async () => {
    const index = await loadIndex('episodes', diskFetcher())
    expect(index.episodes.map((e) => e.name)).toEqual(['mini'])
  })

  it('rejects an index written for another schema version', async () => {
    const fetcher = diskFetcher({ 'episodes/index.json': JSON.stringify({ schema_version: 2, episodes: [] }) })
    await expect(loadIndex('episodes', fetcher)).rejects.toThrow(/schema version 2.*reads version 1/)
  })
})

describe('loadEpisode', () => {
  it('reads the meta, every tick in order, and the proposals', async () => {
    const bundle = await loadEpisode('mini', 'episodes', diskFetcher())
    expect(bundle.meta.schema_version).toBe(1)
    expect(bundle.ticks.map((t) => t.tick)).toEqual([0, 2, 4, 17, 18, 22])
    expect(bundle.proposals).toHaveLength(2)
    expect(bundle.proposals.every((p) => p.admission_decision && p.source === 'template')).toBe(true)
    const tick = bundle.ticks[2]
    expect(tick?.arbiter?.pick_rule).toBe('committed')
    expect(tick?.state?.screen_width).toBe(320)
  })

  it('reads the training run files that episode.json lists, and gives null for the rest', async () => {
    const bundle = await loadEpisode('mini', 'episodes', diskFetcher())
    expect(bundle.metrics?.map((r) => r.episode)).toEqual([1, 2, 3])
    expect(bundle.evaluation?.heuristics.reward).toBe(547.98)
    expect(bundle.evaluation?.latest?.cleared).toBe(0.3)
    expect(bundle.trust?.trust_count).toBe(25)
    expect(Object.keys(bundle.trust?.context_counts ?? {})).toHaveLength(2)
    // macros.json is not listed, so it is not fetched.
    expect(bundle.macros).toBeNull()
  })

  it('treats a listed run file that is missing, or an unlisted one, as absent', async () => {
    const missing = await loadEpisode('mini', 'episodes', diskFetcher({ 'episodes/mini/trust.json': null }))
    expect(missing.trust).toBeNull()
    expect(missing.metrics).not.toBeNull()
    const meta = JSON.parse(await readFile(`${FIXTURES}episodes/mini/episode.json`, 'utf8'))
    const bare = await loadEpisode(
      'mini',
      'episodes',
      diskFetcher({ 'episodes/mini/episode.json': JSON.stringify({ ...meta, files: meta.files.slice(0, 3) }) }),
    )
    expect([bare.metrics, bare.evaluation, bare.trust, bare.macros]).toEqual([null, null, null, null])
  })

  it('names the frame of a tick by its number, and the screen after the last action', async () => {
    const bundle = await loadEpisode('mini', 'episodes', diskFetcher())
    expect(frameUrl(bundle, 17)).toBe('episodes/mini/frames/00017.jpg')
    expect(endFrameUrl(bundle)).toBe('episodes/mini/frames/end.jpg')
    expect(
      endFrameUrl({ ...bundle, meta: { ...bundle.meta, frames: { ...bundle.meta.frames, end_frame: null } } }),
    ).toBe(null)
  })

  it('treats a missing proposals file as no proposals', async () => {
    const bundle = await loadEpisode('mini', 'episodes', diskFetcher({ 'episodes/mini/proposals.jsonl': null }))
    expect(bundle.proposals).toEqual([])
  })

  it('refuses a bundle from another schema version', async () => {
    const meta = JSON.parse(await readFile(`${FIXTURES}episodes/mini/episode.json`, 'utf8'))
    const fetcher = diskFetcher({ 'episodes/mini/episode.json': JSON.stringify({ ...meta, schema_version: 0 }) })
    await expect(loadEpisode('mini', 'episodes', fetcher)).rejects.toBeInstanceOf(BundleError)
  })

  it('refuses a bundle whose tick count disagrees with its meta', async () => {
    const ticks = await readFile(`${FIXTURES}episodes/mini/ticks.jsonl`, 'utf8')
    const fetcher = diskFetcher({ 'episodes/mini/ticks.jsonl': ticks.split('\n').slice(0, 2).join('\n') })
    await expect(loadEpisode('mini', 'episodes', fetcher)).rejects.toThrow(/has 2 ticks, but episode.json says 6/)
  })

  it('reports a missing bundle by URL', async () => {
    await expect(loadEpisode('nope', 'episodes', diskFetcher())).rejects.toThrow(
      /episodes\/nope\/episode.json: HTTP 404/,
    )
  })
})

describe('defaultEpisode', () => {
  const entry = (name: string, cleared: boolean): BundleIndexEntry => ({
    name,
    title: name,
    scenario: 'deadly_corridor.cfg',
    model: 'heuristics',
    seed: 9,
    cleared,
    died: !cleared,
    reward: 0,
    ticks: 10,
  })

  it('opens the first recording that cleared its level, wherever it is listed', () => {
    const index = { episodes: [entry('a', false), entry('b', false), entry('c', true), entry('d', true)] }
    expect(defaultEpisode(index)).toBe('c')
  })

  it('opens the first recording when none cleared, and nothing when there is none', () => {
    expect(defaultEpisode({ episodes: [entry('a', false), entry('b', false)] })).toBe('a')
    expect(defaultEpisode({ episodes: [] })).toBeNull()
    expect(defaultEpisode(null)).toBeNull()
  })

  it('picks the cleared corridor among the shipped recordings', async () => {
    const shipped = JSON.parse(await readFile(new URL('../../public/episodes/index.json', import.meta.url), 'utf8'))
    expect(shipped.episodes[0].name).toBe('deadly_corridor-heuristics-9')
    expect(defaultEpisode(shipped)).toBe('deadly_corridor-learned-9')
  })
})

describe('parseJsonl', () => {
  it('skips blank lines and names the line that fails', () => {
    expect(parseJsonl<{ a: number }>('{"a":1}\n\n{"a":2}\n', 'x.jsonl')).toEqual([{ a: 1 }, { a: 2 }])
    expect(() => parseJsonl('{"a":1}\n{oops}', 'x.jsonl')).toThrow(/x.jsonl line 2/)
  })
})
