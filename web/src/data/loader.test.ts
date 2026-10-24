import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { BundleError, type Fetcher, frameUrl, loadEpisode, loadIndex, parseJsonl } from './loader'

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
    expect(bundle.ticks.map((t) => t.tick)).toEqual([0, 4, 17, 18, 22])
    expect(bundle.proposals).toHaveLength(2)
    expect(bundle.proposals.every((p) => p.admission_decision && p.source === 'template')).toBe(true)
    const tick = bundle.ticks[1]
    expect(tick?.arbiter?.pick_rule).toBe('committed')
    expect(tick?.state?.screen_width).toBe(320)
  })

  it('names the frame of a tick by its number', async () => {
    const bundle = await loadEpisode('mini', 'episodes', diskFetcher())
    expect(frameUrl(bundle, 17)).toBe('episodes/mini/frames/00017.jpg')
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
    await expect(loadEpisode('mini', 'episodes', fetcher)).rejects.toThrow(/has 2 ticks, but episode.json says 5/)
  })

  it('reports a missing bundle by URL', async () => {
    await expect(loadEpisode('nope', 'episodes', diskFetcher())).rejects.toThrow(
      /episodes\/nope\/episode.json: HTTP 404/,
    )
  })
})

describe('parseJsonl', () => {
  it('skips blank lines and names the line that fails', () => {
    expect(parseJsonl<{ a: number }>('{"a":1}\n\n{"a":2}\n', 'x.jsonl')).toEqual([{ a: 1 }, { a: 2 }])
    expect(() => parseJsonl('{"a":1}\n{oops}', 'x.jsonl')).toThrow(/x.jsonl line 2/)
  })
})
