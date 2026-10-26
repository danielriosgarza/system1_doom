import { readFile } from 'node:fs/promises'
import { describe, expect, it } from 'vitest'
import type { BundleIndexEntry, ProposalTrace } from '../schema/bundle'
import { FIXTURE, FIXTURES, diskFetcher } from '../test/fixture'
import {
  BundleError,
  SUPPORTED_SCHEMA_VERSION,
  bundleFileUrl,
  checkSchemaVersion,
  defaultEpisode,
  endFrameUrl,
  frameUrl,
  latestProposals,
  loadEpisode,
  loadIndex,
  parseJsonl,
} from './loader'

const metaPath = `${FIXTURES}episodes/${FIXTURE}/episode.json`

describe('loadIndex', () => {
  it('lists the fixture recording, with its configuration versions', async () => {
    const index = await loadIndex('episodes', diskFetcher())
    expect(index.schema_version).toBe(SUPPORTED_SCHEMA_VERSION)
    expect(index.episodes.map((e) => [e.name, e.configuration_start, e.configuration_end])).toEqual([[FIXTURE, 1, 3]])
  })

  it('refuses a schema 1 index, saying it is the old architecture and how to record again', async () => {
    const fetcher = diskFetcher({ 'episodes/index.json': JSON.stringify({ schema_version: 1, episodes: [] }) })
    const error = await loadIndex('episodes', fetcher).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(BundleError)
    expect(String(error)).toMatch(/schema 1 recording, from the old architecture/)
    expect(String(error)).toMatch(/reads schema 2, where every decision is made by d1-ultra/)
    expect(String(error)).toMatch(/python -m system1_doom\.export/)
  })
})

describe('loadEpisode', () => {
  it('reads the meta, every tick in order with its six instances, the proposals and System 2’s records', async () => {
    const bundle = await loadEpisode(FIXTURE, 'episodes', diskFetcher())
    expect(bundle.meta.schema_version).toBe(2)
    expect(bundle.meta.decider).toBe('d1-ultra')
    expect(bundle.ticks.map((t) => t.tick)).toEqual([...Array(40).keys()])
    for (const tick of bundle.ticks) {
      expect(Object.keys(tick.instances)).toEqual(['survival', 'combat', 'navigation', 'resource', 'goal', 'central'])
    }
    expect(bundle.proposals.length).toBeGreaterThan(0)
    expect(bundle.proposals.every((p) => p.admit_instance?.kind === 'admit')).toBe(true)
    const kinds = bundle.records.map((r) => r.record)
    expect(kinds).toContain('cycle')
    expect(kinds).toContain('verdict')
    expect(kinds).toContain('note')
  })

  it('reads the relevance ledger and the training counts that episode.json lists', async () => {
    const bundle = await loadEpisode(FIXTURE, 'episodes', diskFetcher())
    expect(bundle.relevance?.episodes).toBe(3)
    expect(Object.keys(bundle.relevance?.entries ?? {}).length).toBeGreaterThan(0)
    expect(bundle.trust?.episodes).toBe(2)
  })

  it('treats an unlisted or missing extra file as absent', async () => {
    const meta = JSON.parse(await readFile(metaPath, 'utf8'))
    const files = meta.files.filter((f: string) => f !== 'trust.json')
    const bare = await loadEpisode(
      FIXTURE,
      'episodes',
      diskFetcher({
        [`episodes/${FIXTURE}/episode.json`]: JSON.stringify({ ...meta, files }),
        [`episodes/${FIXTURE}/reflections.jsonl`]: null,
      }),
    )
    expect(bare.trust).toBeNull()
    expect(bare.records).toEqual([])
    expect(bare.relevance).not.toBeNull()
  })

  it('refuses a schema 1 bundle with a clear message', async () => {
    const meta = JSON.parse(await readFile(metaPath, 'utf8'))
    const fetcher = diskFetcher({
      [`episodes/${FIXTURE}/episode.json`]: JSON.stringify({ ...meta, schema_version: 1 }),
    })
    await expect(loadEpisode(FIXTURE, 'episodes', fetcher)).rejects.toThrow(
      new RegExp(`${FIXTURE}/episode.json is a schema 1 recording`),
    )
  })

  it('refuses a bundle whose tick count disagrees with its meta, unless it is live', async () => {
    const ticks = await readFile(`${FIXTURES}episodes/${FIXTURE}/ticks.jsonl`, 'utf8')
    const two = ticks.split('\n').slice(0, 2).join('\n')
    const fetcher = diskFetcher({ [`episodes/${FIXTURE}/ticks.jsonl`]: two })
    await expect(loadEpisode(FIXTURE, 'episodes', fetcher)).rejects.toThrow(/has 2 ticks, but episode.json says 40/)
    const live = await loadEpisode(FIXTURE, 'episodes', fetcher, { live: true })
    expect(live.ticks).toHaveLength(2)
    expect(live.meta.tick_count).toBe(2)
  })

  it('names frames by tick and resolves an instance’s image reference inside the bundle', async () => {
    const bundle = await loadEpisode(FIXTURE, 'episodes', diskFetcher())
    expect(frameUrl(bundle, 17)).toBe(`episodes/${FIXTURE}/frames/00017.jpg`)
    expect(endFrameUrl(bundle)).toBe(`episodes/${FIXTURE}/frames/end.jpg`)
    const combat = bundle.ticks[3]?.instances.combat
    expect(combat?.image_ref).toBe('frames/00003.jpg')
    expect(bundleFileUrl(bundle, combat?.image_ref ?? '')).toBe(`episodes/${FIXTURE}/frames/00003.jpg`)
  })

  it('reports a missing bundle by URL', async () => {
    await expect(loadEpisode('nope', 'episodes', diskFetcher())).rejects.toThrow(
      /episodes\/nope\/episode.json: HTTP 404/,
    )
  })
})

describe('checkSchemaVersion', () => {
  it('accepts version 2 and refuses anything else', () => {
    expect(() => checkSchemaVersion(2, 'x')).not.toThrow()
    expect(() => checkSchemaVersion(3, 'x')).toThrow(/schema version 3, but this app reads version 2/)
    expect(() => checkSchemaVersion(undefined, 'x')).toThrow(/version none/)
  })
})

describe('latestProposals', () => {
  it('keeps the newest line of each proposal, in the order proposals first came', () => {
    const p = (timestamp: string, raw: string, performance: number[]) =>
      ({ timestamp, raw_proposal: raw, subsequent_performance: performance }) as ProposalTrace
    const kept = latestProposals([p('t1', 'a', []), p('t2', 'b', []), p('t1', 'a', [1, 2])])
    expect(kept.map((x) => [x.raw_proposal, x.subsequent_performance])).toEqual([
      ['a', [1, 2]],
      ['b', []],
    ])
  })
})

describe('defaultEpisode', () => {
  const entry = (name: string, cleared: boolean): BundleIndexEntry => ({
    name,
    title: name,
    scenario: 'deadly_corridor.cfg',
    value_networks: 'best',
    seed: 9,
    cleared,
    died: !cleared,
    reward: 0,
    ticks: 10,
  })

  it('opens the first recording that cleared its level, wherever it is listed, when none says when it was recorded', () => {
    const index = { episodes: [entry('a', false), entry('b', false), entry('c', true), entry('d', true)] }
    expect(defaultEpisode(index)).toBe('c')
  })

  it('opens the most recently recorded recording that cleared, so the landing shows the agent as it is now', () => {
    const at = (e: BundleIndexEntry, recorded_at: string): BundleIndexEntry => ({ ...e, recorded_at })
    const index = {
      episodes: [
        at(entry('new-died', false), '2026-10-26T07:14:00Z'),
        at(entry('new-cleared', true), '2026-10-26T07:15:00Z'),
        at(entry('old-cleared', true), '2026-10-25T14:40:00Z'),
        entry('undated', true),
      ],
    }
    expect(defaultEpisode(index)).toBe('new-cleared')
  })

  it('opens the first recording when none cleared, and nothing when there is none', () => {
    expect(defaultEpisode({ episodes: [entry('a', false), entry('b', false)] })).toBe('a')
    expect(defaultEpisode({ episodes: [] })).toBeNull()
    expect(defaultEpisode(null)).toBeNull()
  })
})

describe('parseJsonl', () => {
  it('skips blank lines and names the line that fails', () => {
    expect(parseJsonl<{ a: number }>('{"a":1}\n\n{"a":2}\n', 'x.jsonl')).toEqual([{ a: 1 }, { a: 2 }])
    expect(() => parseJsonl('{"a":1}\n{oops}', 'x.jsonl')).toThrow(/x.jsonl line 2/)
  })
})
