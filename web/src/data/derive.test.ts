import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import type { EpisodeMeta, ProposalTrace, TickTrace } from '../schema/bundle'
import {
  admissions,
  aimBandHalfWidth,
  contextBuckets,
  describeStep,
  explainPick,
  exploration,
  featuredTickIndex,
  moduleVoteParts,
  motorSteps,
  pressureForArbiter,
  pressureReading,
  prunedReasonText,
  rankedActions,
  tickEvents,
  towerLevels,
} from './derive'
import { parseJsonl } from './loader'

const DIR = fileURLToPath(new URL('./__fixtures__/episodes/mini/', import.meta.url))
const ticks = parseJsonl<TickTrace>(await readFile(`${DIR}ticks.jsonl`, 'utf8'), 'ticks.jsonl').sort(
  (a, b) => a.tick - b.tick,
)
const proposals = parseJsonl<ProposalTrace>(await readFile(`${DIR}proposals.jsonl`, 'utf8'), 'proposals.jsonl')
const meta = JSON.parse(await readFile(`${DIR}episode.json`, 'utf8')) as EpisodeMeta
const at = (n: number) => ticks.find((t) => t.tick === n) as TickTrace

describe('context buckets', () => {
  it('reads the five buckets of the signature with the reason for each', () => {
    const buckets = contextBuckets('hp:medium|ammo:stocked|enemies:2:mid|dmg:under_fire|pickup:no_pickup')
    expect(buckets.map((b) => [b.key, b.value])).toEqual([
      ['hp', 'medium'],
      ['ammo', 'stocked'],
      ['enemies', 'mid'],
      ['dmg', 'under_fire'],
      ['pickup', 'no_pickup'],
    ])
    const tick = at(0)
    expect(contextBuckets(tick.context_signature, tick.state).find((b) => b.key === 'hp')?.because).toBe('health 100')
  })
})

describe('arbiter readings', () => {
  it("splits every action's module votes into weight × probability parts that add up to the trace", () => {
    for (const tick of ticks) {
      for (const action of tick.available_actions) {
        const parts = moduleVoteParts(tick, action)
        const sum = parts.reduce((s, p) => s + p.value, 0)
        expect(sum).toBeCloseTo(tick.arbiter?.component_breakdown?.[action]?.module_votes ?? NaN, 2)
      }
    }
  })

  it('orders the legal actions by score, best first', () => {
    const tick = at(0)
    const scores = tick.arbiter?.action_scores ?? {}
    const ranked = rankedActions(tick)
    expect(new Set(ranked)).toEqual(new Set(tick.available_actions))
    ranked.slice(1).forEach((a, i) => expect(scores[ranked[i] as string]).toBeGreaterThanOrEqual(scores[a] ?? 0))
  })

  it('explains each pick rule in words', () => {
    expect(explainPick(at(4)).headline).toBe('The resource module committed the arbiter to approach pickup.')
    expect(explainPick(at(22)).headline).toMatch(/^Sampled strafe left, which had a \d+% chance\.$/)
    expect(explainPick(at(0)).headline).toBe('Took the top score: weave fire.')
  })
})

describe('events', () => {
  it('marks the expansion request, the admission and the sampled pick', () => {
    const admitted = admissions(proposals)
    expect(tickEvents(at(17), admitted).map((e) => e.kind)).toContain('expansion')
    expect(tickEvents(at(18), admitted).map((e) => e.label)).toContain('admitted evasive burst 1 into the menu')
    expect(tickEvents(at(22), admitted).map((e) => e.kind)).toContain('sampled')
  })
})

describe('motor steps in words', () => {
  it('names the reflex a step used', () => {
    expect(describeStep('strafe_left_shoot', ['strafe_left', 'turn_right'])).toEqual({
      words: 'strafed left while turning right onto the target, holding fire until it is centred',
      assisted: true,
    })
    expect(describeStep('strafe_left', ['strafe_left', 'turn_left']).words).toBe(
      'strafed left while turning left to track the target',
    )
    expect(describeStep('move_forward', ['move_forward', 'turn_left']).words).toBe(
      'moved forward, steering left toward the pickup',
    )
    expect(describeStep('shoot', ['shoot'])).toEqual({ words: 'fired at the locked target', assisted: false })
  })

  it('maps executed steps onto the plan, holding short plans for several steps', () => {
    const steps = motorSteps(['move_forward'], ['move_forward', 'move_forward', 'move_forward', 'move_forward'])
    expect(steps.map((s) => s.planned)).toEqual(['move_forward', 'move_forward', 'move_forward', 'move_forward'])
    const plan = meta.actions.weave_fire?.primitives ?? []
    const weave = motorSteps(plan, at(0).primitive_steps_executed)
    expect(weave.map((s) => s.planned)).toEqual([
      'strafe_left_shoot',
      'strafe_left_shoot',
      'strafe_right_shoot',
      'strafe_right_shoot',
    ])
  })
})

describe('pruning reasons', () => {
  it('names the failed precondition with its threshold and the current value', () => {
    const tick = at(0)
    expect(tick.pruned_actions?.retreat_to_cover).toBe('max_health')
    expect(prunedReasonText('max_health', meta.actions.retreat_to_cover, tick.state)).toBe(
      'only when health is 45 or less (now 100)',
    )
    expect(prunedReasonText('requires_visible_enemy', meta.actions.shoot, tick.state)).toBe('needs a visible enemy')
    expect(prunedReasonText('max_ammo', meta.actions.switch_weapon_1, tick.state)).toMatch(/^only when out of ammo/)
  })
})

describe('game view geometry', () => {
  it('puts the ±12° aim band 42.7 px either side of the centre of a 320 px screen', () => {
    expect(aimBandHalfWidth(320)).toBeCloseTo(42.67, 2)
  })
})

describe('the featured tick', () => {
  it('is the first kill with an enemy in view', () => {
    expect(ticks[featuredTickIndex(ticks)]?.tick).toBe(2)
  })

  it('falls back to the first enemy in view, then to the first tick', () => {
    const noKills = ticks.map((t) => ({ ...t, outcome: t.outcome && { ...t.outcome, kills_delta: 0 } }))
    expect(featuredTickIndex(noKills)).toBe(0)
    const noEnemies = ticks.map((t) => ({ ...t, state: t.state && { ...t.state, enemies: [] } }))
    expect(featuredTickIndex(noEnemies)).toBe(0)
  })
})

describe('the hierarchy', () => {
  const levels = (n: number) => towerLevels(at(n), meta, proposals)
  const level = (n: number, id: string) => levels(n).find((l) => l.id === id)

  it('has the same six levels on every tick, slowest first', () => {
    for (const tick of ticks) {
      expect(towerLevels(tick, meta, proposals).map((l) => l.id)).toEqual([
        'gate',
        'steering',
        'menu',
        'opinions',
        'arbiter',
        'motor',
      ])
    }
  })

  it('sizes each menu from the trace and chooses what the trace chose', () => {
    for (const tick of ticks) {
      const n = tick.tick
      expect(level(n, 'menu')?.menuSize).toBe(
        tick.available_actions.length + Object.keys(tick.pruned_actions ?? {}).length,
      )
      expect(level(n, 'menu')?.choice).toBe(String(tick.available_actions.length))
      expect(level(n, 'opinions')?.menuSize).toBe(tick.available_actions.length)
      expect(level(n, 'arbiter')?.menuSize).toBe(tick.available_actions.length)
      expect(level(n, 'arbiter')?.choice).toBe(tick.selected_action)
      expect(
        level(n, 'arbiter')
          ?.candidates.filter((c) => c.chosen)
          .map((c) => c.id),
      ).toEqual([tick.selected_action])
      expect(level(n, 'steering')?.choice).toBe(tick.steering?.choice)
      expect(level(n, 'steering')?.menuSize).toBe(4)
    }
  })

  it('names the pick rule the arbiter used', () => {
    expect(level(0, 'arbiter')?.rule).toMatch(/^greedy/)
    expect(level(4, 'arbiter')?.rule).toMatch(/^committed/)
    expect(level(22, 'arbiter')?.rule).toMatch(/^sampled/)
  })

  it('lights the gate when a module asks and when a proposal arrives', () => {
    expect(level(0, 'gate')).toMatchObject({ choice: 'none', idle: true, menuSize: 0 })
    expect(level(17, 'gate')).toMatchObject({ choice: 'requested', idle: false })
    const admitted = level(18, 'gate')
    expect(admitted).toMatchObject({ choice: 'admitted', menuSize: 1, choiceLabel: 'admitted evasive burst 1' })
    expect(admitted?.candidates.map((c) => c.id)).toEqual(['parse', 'legality', 'sandbox', 'd1', 'admit'])
    expect(admitted?.candidates.find((c) => c.id === 'd1')?.style).toBe('dotted')
    // After the admission the gate is quiet again but remembers what it let in.
    expect(level(22, 'gate')?.menu.map((c) => c.id)).toEqual(['evasive_burst_1'])
  })
})

describe('exploration pressure', () => {
  const EPISODES = fileURLToPath(new URL('../../public/episodes/', import.meta.url))
  const BUNDLES = ['deadly_corridor-heuristics-9', 'deadly_corridor-learned-9']
  const read = async (name: string) =>
    parseJsonl<TickTrace>(await readFile(`${EPISODES}${name}/ticks.jsonl`, 'utf8'), name)

  it.each(BUNDLES)('recomputes the recorded pressure from its terms on every tick of %s', async (name) => {
    const all = await read(name)
    expect(all.length).toBeGreaterThan(30)
    for (const tick of all) {
      const reading = pressureReading(exploration(tick))
      expect(reading.initial).toBe(false)
      // The trace rounds to four decimals.
      expect(reading.pressure).toBeCloseTo(tick.exploration_state?.exploration_pressure as number, 3)
      expect(reading.temperature).toBeCloseTo(tick.exploration_state?.temperature as number, 3)
    }
  })

  it.each(BUNDLES)("gives each tick's arbiter the pressure left by the tick before in %s", async (name) => {
    const all = await read(name)
    expect(pressureReading(pressureForArbiter(all, 0))).toMatchObject({ initial: true, pressure: 0.25 })
    all.forEach((tick, index) => {
      const used = pressureReading(pressureForArbiter(all, index))
      expect(used.pressure).toBeCloseTo(tick.arbiter?.exploration_pressure ?? NaN, 3)
    })
  })
})
