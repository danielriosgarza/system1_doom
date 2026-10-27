import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import type { BundleIndexEntry, RuleTreeDecision, WalkStep } from '../schema/bundle'
import type { Fetcher } from './loader'
import {
  FOCUS_HEAD,
  ROOT,
  actionWords,
  defaultRulesEpisode,
  loadRulesEpisode,
  readBuild,
  ruleIds,
  ruleUses,
  skillIds,
  textSent,
} from './rules'

// The rule tree's shipped recordings: `general-11` on seeds 9 to 12, and `codex-11` on seed 9.
const PUBLIC = fileURLToPath(new URL('../../public/', import.meta.url))

function publicFetcher(overrides: Record<string, string> = {}): Fetcher {
  return async (url) => {
    if (url in overrides) return new Response(overrides[url])
    try {
      return new Response(await readFile(PUBLIC + url, 'utf8'))
    } catch {
      return new Response('missing', { status: 404 })
    }
  }
}

const load = (name: string) => loadRulesEpisode(name, 'episodes', publicFetcher())

describe('loadRulesEpisode', () => {
  it('reads a recording: its decisions in order, the tree as played and how it was written', async () => {
    const bundle = await load('rules-corridor-9')
    expect(bundle.meta.solution).toBe('rule-tree')
    expect(bundle.meta.tree).toBe('general-11')
    expect(bundle.decisions).toHaveLength(bundle.meta.decision_count)
    expect(bundle.decisions.map((d) => d.decision)).toEqual(bundle.decisions.map((_, i) => i))
    expect(ruleIds(bundle.tree)).toHaveLength(bundle.meta.rules)
    expect(skillIds(bundle.tree)).toEqual(['aim'])
    expect(bundle.build.length).toBeGreaterThan(0)
  })

  it('refuses a recording whose decisions disagree with episode.json', async () => {
    const text = await readFile(`${PUBLIC}episodes/rules-corridor-9/decisions.jsonl`, 'utf8')
    const fewer = text.split('\n').slice(1).join('\n')
    const fetcher = publicFetcher({ 'episodes/rules-corridor-9/decisions.jsonl': fewer })
    await expect(loadRulesEpisode('rules-corridor-9', 'episodes', fetcher)).rejects.toThrow(/but episode.json says/)
  })

  it('refuses a senses-and-central recording', async () => {
    const meta = JSON.parse(await readFile(`${PUBLIC}episodes/rules-corridor-9/episode.json`, 'utf8')) as object
    const fetcher = publicFetcher({
      'episodes/rules-corridor-9/episode.json': JSON.stringify({ ...meta, solution: 'senses-and-central' }),
    })
    await expect(loadRulesEpisode('rules-corridor-9', 'episodes', fetcher)).rejects.toThrow(/not a rule-tree/)
  })
})

describe('textSent', () => {
  const step = (kind: WalkStep['kind'], extra: Partial<WalkStep> = {}): WalkStep =>
    ({ kind, node: 'r1', question: null, options: {}, answer: null, pick: null, ...extra }) as WalkStep
  const decision: Pick<RuleTreeDecision, 'state_text' | 'steps'> = {
    state_text: '[vitals]\nhealth 100',
    steps: [
      step('rule'),
      step('focus', { focus_line: 'Imp at distance 300 (from the threats list)' }),
      step('rule'),
      step('skill', { skill: 'aim' }),
      step('rule', { node: 'aim' }),
    ],
  }

  it('sends the state text, with the focus line under [focus] after a focus', () => {
    expect(textSent(decision, 0)).toBe('[vitals]\nhealth 100')
    expect(textSent(decision, 1)).toBe('[vitals]\nhealth 100')
    expect(textSent(decision, 2)).toBe(`[vitals]\nhealth 100${FOCUS_HEAD}Imp at distance 300 (from the threats list)`)
    expect(textSent(decision, 4)).toBe(textSent(decision, 2))
  })

  it('has no text for a skill step, which asks nothing', () => {
    expect(textSent(decision, 3)).toBeNull()
  })

  it('starts every recorded walk from the state text', async () => {
    const bundle = await load('rules-corridor-10')
    for (const d of bundle.decisions) expect(textSent(d, 0)).toBe(d.state_text.split(FOCUS_HEAD)[0])
  })
})

describe('actionWords', () => {
  it('says a rule’s action in words', () => {
    expect(actionWords({ skill: 'aim', then: '0001' })).toBe('the aim skill, then fire')
    expect(actionWords({ skill: 'aim', then: 'F001' })).toBe('the aim skill, then walk forward + fire')
    expect(actionWords('random')).toBe('a random action code')
    expect(actionWords('then')).toBe('what the calling rule asks')
    expect(actionWords('0000')).toBe('stand still')
    expect(actionWords('00R0:3')).toBe('turn right for 3 tics, then what the calling rule asks')
    expect(actionWords('00R0:3+0001:5')).toBe('turn right for 3 tics, then fire for 5 tics')
  })
})

describe('ruleUses', () => {
  it('counts every walk at the top of the tree, and each decision once where it ended', async () => {
    const bundle = await load('rules-corridor-11')
    const uses = ruleUses(bundle)
    expect(uses.find((u) => u.id === ROOT)?.reached).toBe(bundle.decisions.length)
    expect(uses.reduce((sum, u) => sum + u.ended, 0)).toBe(bundle.decisions.length)
  })
})

describe('readBuild', () => {
  it('reads general-11’s record: passes, proposals with their check and gate, and the held-out runs', async () => {
    const entries = readBuild((await load('rules-corridor-9')).build)
    expect(entries[0]).toMatchObject({ kind: 'start' })
    const added = entries.filter((e) => e.kind === 'proposal' && e.outcome === 'added')
    expect(added.length).toBeGreaterThan(0)
    const heldOut = entries.filter((e) => e.kind === 'held-out')
    expect(heldOut.map((e) => (e.kind === 'held-out' ? [e.cleared, e.of] : []))).toEqual([
      [20, 20],
      [18, 20],
      [19, 20],
    ])
  })

  it('reads codex-11’s record, written in the soft loop’s own format', async () => {
    const entries = readBuild((await load('rules-codex-corridor-9')).build)
    const outcomes = entries.flatMap((e) => (e.kind === 'proposal' ? [[e.name, e.outcome]] : []))
    expect(outcomes).toEqual([
      ['f01-trace-s12-00-a1', 'rejected by the check'],
      ['f01-trace-s12-00-a2', 'check stopped'],
      ['f01-trace-s12-00-a3', 'check stopped'],
      ['f01-trace-s12-01-a1', 'rejected by the check'],
      ['f01-trace-s12-01-a2', 'rejected by the gate'],
      ['f01-trace-s12-01-a3', 'added'],
    ])
    const last = entries.find((e) => e.kind === 'proposal' && e.outcome === 'added')
    expect(last?.kind === 'proposal' && last.added).toEqual({ rule: 'r11+r12', attachTo: 'r2' })
    // Round 1 was played twice: once before the checks that stopped, once after.
    const passes = entries.flatMap((e) => (e.kind === 'pass' ? [[e.round, e.again, e.cleared]] : []))
    expect(passes).toEqual([
      [1, false, 8],
      [1, true, 9],
      [2, false, 11],
    ])
  })
})

describe('defaultRulesEpisode', () => {
  const entry = (name: string, tree: string, recorded_at: string, cleared = true) =>
    ({ name, tree, recorded_at, cleared, seed: 9, solution: 'rule-tree' }) as BundleIndexEntry

  it('opens the default tree’s newest cleared recording, even when another tree’s is newer', () => {
    const entries = [
      entry('rules-corridor-9', 'general-11', '2026-10-27T09:00'),
      entry('rules-corridor-10', 'general-11', '2026-10-27T09:01'),
      entry('rules-codex-corridor-9', 'codex-11', '2026-10-27T10:00'),
    ]
    expect(defaultRulesEpisode(entries)).toBe('rules-corridor-10')
    expect(defaultRulesEpisode(entries.slice(2))).toBe('rules-codex-corridor-9')
    expect(defaultRulesEpisode([])).toBeNull()
  })
})
