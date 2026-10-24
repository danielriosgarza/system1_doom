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
  moduleVoteParts,
  motorSteps,
  prunedReasonText,
  rankedActions,
  tickEvents,
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
