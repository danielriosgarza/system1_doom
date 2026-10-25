import { beforeAll, describe, expect, it } from 'vitest'
import { loadFixture } from '../test/fixture'
import { ledgerPoints, paidSeries, topContexts, triedHere } from './learning'
import type { EpisodeBundle } from './loader'
import { isCycle, placedCycles } from './readings'
import {
  REFLECTORS,
  answerWords,
  changeWords,
  configurationChanges,
  defaultCycle,
  outcomeWords,
  proposerOf,
  reflectorRows,
  testSummary,
  verdictOf,
} from './system2'

let bundle: EpisodeBundle

beforeAll(async () => {
  bundle = await loadFixture()
})

const cycle = (id: string) => {
  const c = bundle.records.filter(isCycle).find((r) => r.cycle_id === id)
  if (!c) throw new Error(`no ${id}`)
  return c
}

describe('a System 2 cycle', () => {
  it('lists the nine reflectors in call order, with who proposed what', () => {
    const rows = reflectorRows(cycle('cycle-3'))
    expect(rows.map((r) => r.name)).toEqual([...REFLECTORS])
    const survival = rows[0]
    expect(survival).toMatchObject({ called: true, spoke: true, proposed: true, change: 'widen:survival:pickups' })
    expect(survival?.changeP).toBeCloseTo(0.7)
    expect(rows.filter((r) => r.proposed).map((r) => r.name)).toEqual(['survival_auditor'])
    expect(proposerOf(cycle('cycle-3'))).toBe('survival_auditor')
    expect(proposerOf(cycle('cycle-1'))).toBe('menu_reflector')
  })

  it('says which reflectors were not called, and why', () => {
    const rows = reflectorRows(cycle('cycle-4'))
    const survival = rows.find((r) => r.name === 'survival_auditor')
    expect(survival?.called).toBe(false)
    expect(survival?.skipped).toBeTruthy()
    expect(rows.filter((r) => r.called).length).toBe(8)
  })

  it('opens on the last cycle by the decision showing that tested or changed something', () => {
    const placed = placedCycles(bundle)
    expect(defaultCycle(placed, 39)?.cycle_id).toBe('cycle-3')
    expect(defaultCycle(placed, 20)?.cycle_id).toBe('cycle-1')
    expect(defaultCycle(placed, 0)?.cycle_id).toBe('cycle-1')
  })

  it('finds the verdict of the trial a cycle started', () => {
    expect(verdictOf(bundle, cycle('cycle-3'))?.trial.verdict).toBe('keep')
    expect(verdictOf(bundle, cycle('cycle-2'))).toBeNull()
  })

  it('puts outcomes and changes in words', () => {
    expect(outcomeWords('test_failed')).toBe('the history test rejected the change')
    expect(changeWords('widen:survival:pickups')).toBe('show survival the pickups channel')
    expect(changeWords('narrow:central:relevance')).toBe('stop showing central the relevance channel')
    expect(changeWords('revert:strategy:strat_tactical_combat')).toBe(
      'revert: make strat tactical combat the active strategy',
    )
    expect(changeWords('level:explore')).toBe('set the exploration level to explore')
  })
})

describe('the history test', () => {
  it('reads every sampled tick, bad first, with the old and new answers, and each metric old and new', () => {
    const test = cycle('cycle-3').history_test
    if (!test) throw new Error('no test')
    const summary = testSummary(test)
    expect(summary.status).toBe('passed')
    expect(summary.ticks).toHaveLength(12)
    expect(summary.counts).toEqual({ bad: 4, good: 4, rest: 4 })
    expect(summary.ticks.map((t) => t.stratum)).toEqual([
      ...Array(4).fill('bad'),
      ...Array(4).fill('good'),
      ...Array(4).fill('rest'),
    ])
    expect(summary.metrics.map((m) => [m.id, m.old, m.new])).toEqual([
      ['alarm_recall', 0, 0],
      ['good_agreement', 1, 1],
      ['quiet', 0, 1],
    ])
    const first = summary.ticks[0]
    expect(answerWords(first?.old, 'sense')).toBe('spoke · weave fire (0.90)')
    expect(answerWords(first?.new, 'sense')).toBe('silent (0.15)')
    expect(answerWords({ spoke: false, missed: true, miss_reason: 'timeout' }, 'sense')).toBe('missed (timeout)')
  })
})

describe('the configuration at the start and end', () => {
  it('shows the survival scope widened to pickups and the admitted macro', () => {
    const ch = configurationChanges(bundle.meta)
    const survival = ch.scopes.find((s) => s.instance === 'survival')
    expect(survival?.added).toEqual(['pickups'])
    expect(survival?.removed).toEqual([])
    expect(ch.scopes.filter((s) => s.instance !== 'survival').every((s) => s.added.length === 0)).toBe(true)
    expect(ch.macrosStart).toEqual([])
    expect(ch.macrosEnd).toEqual(['evasive_burst_1'])
  })
})

describe('learning', () => {
  it('puts the open episode’s ledger before and after on one line with the other recordings’ ledgers', () => {
    const others = [
      {
        name: 'another',
        ledger: { episodes: 7, entries: { 'survival|x': { spoke: 4, followed: 2, followed_paid: 1 } } },
      },
    ]
    const points = ledgerPoints(bundle, others)
    expect(points.map((p) => [p.episodes, p.current])).toEqual([
      [(bundle.relevance?.episodes ?? 0) - 1, true],
      [bundle.relevance?.episodes ?? 0, true],
      [7, false],
    ])
    const series = paidSeries(points)
    expect(series.survival?.at(-1)).toMatchObject({ episodes: 7, value: 0.5, followed: 2, paid: 1 })
    expect(series.navigation?.at(-1)?.value).toBeNull()
  })

  it('reads the training counts behind the values in this tick’s situation', () => {
    const tick = bundle.ticks[0]
    if (!tick) throw new Error('no tick')
    const here = triedHere(bundle.trust, tick)
    expect(here?.rows.map((r) => r.action)).toEqual(tick.available_actions)
    for (const r of here?.rows ?? [])
      expect(r.familiarity).toBeCloseTo(r.tried / (r.tried + (bundle.trust?.trust_count ?? 25)))
    const top = topContexts(bundle.trust, tick.context_signature, 3)
    expect(top.length).toBeGreaterThan(0)
    expect(top.map((c) => c.n)).toEqual([...top.map((c) => c.n)].sort((a, b) => b - a).slice(0, top.length))
  })
})
