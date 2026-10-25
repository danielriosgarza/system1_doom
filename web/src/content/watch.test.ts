import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { parseJsonl } from '../data/loader'
import type { BundleIndexEntry, EpisodeMeta, ProposalTrace, TickTrace } from '../schema/bundle'
import { brainOf, chainRows, counterText, endLine, frameAlt, keysPressed, resultWords } from './watch'

// The landing plays the shipped recordings, so these read them rather than the fixture.
const EPISODES = fileURLToPath(new URL('../../public/episodes/', import.meta.url))

async function shipped(name: string) {
  const dir = `${EPISODES}${name}/`
  const ticks = parseJsonl<TickTrace>(await readFile(`${dir}ticks.jsonl`, 'utf8'), 'ticks.jsonl').sort(
    (a, b) => a.tick - b.tick,
  )
  const proposals = parseJsonl<ProposalTrace>(await readFile(`${dir}proposals.jsonl`, 'utf8'), 'proposals.jsonl')
  const meta = JSON.parse(await readFile(`${dir}episode.json`, 'utf8')) as EpisodeMeta
  return { ticks, proposals, meta }
}

const index = JSON.parse(await readFile(`${EPISODES}index.json`, 'utf8')) as { episodes: BundleIndexEntry[] }
const entry = (name: string) => index.episodes.find((e) => e.name === name) as BundleIndexEntry

const learned = await shipped('deadly_corridor-learned-9')
const heuristics = await shipped('deadly_corridor-heuristics-9')

const rowsAt = (rec: typeof learned, i: number) =>
  chainRows(rec.ticks[i] as TickTrace, rec.ticks[i - 1] ?? null, rec.meta, rec.proposals)
const value = (rec: typeof learned, tick: number, id: string) => {
  const i = rec.ticks.findIndex((t) => t.tick === tick)
  return rowsAt(rec, i).find((r) => r.id === id)
}

describe('the chain strip', () => {
  it('reads six levels, slowest first, and the first decision marks nothing as changed', () => {
    const rows = rowsAt(learned, 0)
    expect(rows.map((r) => r.id)).toEqual(['gate', 'steering', 'menu', 'opinions', 'arbiter', 'motor'])
    expect(rows.map((r) => r.value)).toEqual([
      'nothing proposed',
      'continue: tactical combat',
      '13 of 19 allowed',
      '2 of 5 agree with the pick',
      'weave fire · top score',
      'strafe left ×2, turn left ×4, strafe right ×2',
    ])
    expect(rows.some((r) => r.changed)).toBe(false)
  })

  it('marks a row changed when its words differ from the decision before', () => {
    const rows = rowsAt(learned, 1)
    const changed = Object.fromEntries(rows.map((r) => [r.id, r.changed]))
    expect(rows.find((r) => r.id === 'steering')?.value).toBe('switch to corridor advance')
    expect(changed).toEqual({
      gate: false,
      steering: true,
      menu: false,
      opinions: true,
      arbiter: true,
      motor: true,
    })
  })

  it('over the cleared recording the top row never changes and the bottom row changes most', () => {
    const changes = new Map<string, number>()
    learned.ticks.forEach((_, i) => {
      for (const row of rowsAt(learned, i)) if (row.changed) changes.set(row.id, (changes.get(row.id) ?? 0) + 1)
    })
    expect(changes.get('gate') ?? 0).toBe(0)
    expect(changes.get('motor')).toBe(40)
    const counts = ['steering', 'menu', 'opinions', 'arbiter'].map((id) => changes.get(id) ?? 0)
    expect(Math.max(...counts)).toBeLessThan(changes.get('motor') ?? 0)
  })

  it('names the ask at tick 17 and the admission at tick 18 of heuristics seed 9', () => {
    expect(value(heuristics, 17, 'gate')).toMatchObject({ value: 'survival asked for a new move', changed: true })
    expect(value(heuristics, 18, 'gate')).toMatchObject({ value: 'added evasive burst 1 to the menu', changed: true })
    // The admitted macro is one more move the agent knows.
    expect(value(heuristics, 17, 'menu')?.value).toBe('5 of 19 allowed')
    expect(value(heuristics, 18, 'menu')?.value).toBe('5 of 20 allowed')
  })

  it('draws bars only where a level has one share: steering, the menu and the opinions', () => {
    const rows = rowsAt(learned, 0)
    const bars = rows.filter((r) => r.share !== null).map((r) => r.id)
    expect(bars).toEqual(['steering', 'menu', 'opinions'])
    for (const row of rows) if (row.share !== null) expect(row.share).toBeGreaterThanOrEqual(0)
    expect(rows.find((r) => r.id === 'menu')?.share).toBeCloseTo(13 / 19, 5)
    expect(rows.find((r) => r.id === 'opinions')?.share).toBeCloseTo(2 / 5, 5)
  })
})

describe('the keys pressed', () => {
  it('counts each key over the steps, in the order first pressed', () => {
    expect(keysPressed(['strafe_left+shoot', 'strafe_left+shoot', 'strafe_right+shoot', 'strafe_right+shoot'])).toBe(
      'strafe left ×2, shoot ×4, strafe right ×2',
    )
    expect(keysPressed(['move_forward'])).toBe('move forward')
  })

  it('says so when nothing was pressed', () => {
    expect(keysPressed([])).toBe('nothing pressed')
    expect(keysPressed(['idle', 'idle'])).toBe('nothing pressed')
  })
})

describe('the recordings', () => {
  it('names who played each shipped recording', () => {
    expect(brainOf(entry('deadly_corridor-heuristics-9'), null).name).toBe('Heuristics only')
    expect(brainOf(entry('deadly_corridor-learned-9'), null).name).toBe('Trained networks')
    expect(brainOf(entry('deadly_corridor-learned-d1-11'), null).name).toBe('Trained networks with d1-ultra’s advice')
    // The open recording's own meta wins over its title.
    expect(brainOf(entry('deadly_corridor-learned-9'), learned.meta).name).toBe('Trained networks')
  })

  it('says how each one ended from the index line alone', () => {
    expect(resultWords(entry('deadly_corridor-learned-9'))).toBe('cleared the corridor in 52 decisions')
    expect(resultWords(entry('deadly_corridor-heuristics-9'))).toBe('died after 36 decisions')
    expect(resultWords({ scenario: 'basic.cfg', cleared: false, died: false, ticks: 300 })).toBe(
      'survived 300 decisions',
    )
  })

  it('writes the line over the end frame with the kills', () => {
    expect(endLine(learned.meta)).toBe('Cleared the corridor: 52 decisions, 6 kills')
    expect(endLine(heuristics.meta)).toBe('Died after 36 decisions, 1 kill')
  })
})

describe('the counter and the stage text', () => {
  it('counts decisions from 1 with the game time', () => {
    expect(counterText(0, 52, 0, false)).toBe('decision 1 of 52 · 0.0 s of play')
    expect(counterText(51, 52, 11.657, false)).toBe('decision 52 of 52 · 11.7 s of play')
    expect(counterText(9, 10, 2.06, true)).toBe('decision 10 · 2.1 s of play, playing now')
  })

  it('describes the frame at each decision', () => {
    expect(frameAlt(learned.ticks[0] as TickTrace, 0, 52)).toBe(
      'The game at decision 1 of 52: 2 enemies in view, health 100; the agent picks weave fire.',
    )
    const alts = new Set(learned.ticks.map((t, i) => frameAlt(t, i, learned.ticks.length)))
    expect(alts.size).toBe(learned.ticks.length)
  })
})
