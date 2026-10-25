import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import type { EpisodeMeta, MetricsRow, ProposalTrace, TickTrace, TrustFile } from '../schema/bundle'
import {
  D1_WEIGHT,
  MODULES,
  MODULE_TEMPERATURE,
  admissions,
  aimBandHalfWidth,
  closestToAsking,
  contextBuckets,
  contextWords,
  d1Arbiter,
  d1GateWords,
  d1Modules,
  d1Pressure,
  d1Words,
  describeStep,
  encodeAction,
  explainPick,
  exportCommand,
  exploration,
  featuredTickIndex,
  floorAt,
  followUp,
  gateBlend,
  gateLevel,
  moduleVoteParts,
  moduleD1Part,
  motorSteps,
  nStepReturns,
  pressureForArbiter,
  pressureReading,
  preconditionWords,
  proposalShown,
  prunedReasonText,
  rankedActions,
  requestContext,
  requestSpans,
  rolling,
  tickEvents,
  tickRange,
  towerLevels,
  triggerAt,
  trustActions,
  trustLambda,
  serveCommand,
  stillPlaying,
  stoppedEarly,
  trustRows,
  utcStamp,
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
  const BUNDLES = [
    'deadly_corridor-heuristics-9',
    'deadly_corridor-learned-9',
    'deadly_corridor-heuristics-11',
    'deadly_corridor-learned-d1-11',
  ]
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

describe('learning across episodes', async () => {
  const LEARNED = fileURLToPath(new URL('../../public/episodes/deadly_corridor-learned-9/', import.meta.url))
  const learned = parseJsonl<TickTrace>(await readFile(`${LEARNED}ticks.jsonl`, 'utf8'), 'ticks.jsonl')
  const trust = JSON.parse(await readFile(`${LEARNED}trust.json`, 'utf8')) as TrustFile
  const learnedMeta = JSON.parse(await readFile(`${LEARNED}episode.json`, 'utf8')) as EpisodeMeta
  const metrics = parseJsonl<MetricsRow>(await readFile(`${LEARNED}metrics.jsonl`, 'utf8'), 'metrics.jsonl')

  it('sums the next eight rewards discounted by 0.9, truncated at the last tick', () => {
    const last = learned.length - 1
    expect(learned[last]?.tick).toBe(51)
    for (const tick of [0, 17, 40, 48, 51]) {
      const index = learned.findIndex((t) => t.tick === tick)
      const returns = nStepReturns(learned, index)
      for (const m of ['survival', 'combat', 'navigation', 'resource', 'goal'] as const) {
        let expected = 0
        for (let k = 0; k < 8 && index + k <= last; k += 1) {
          expected += 0.9 ** k * (learned[index + k]?.outcome?.module_rewards?.[m] ?? 0)
        }
        expect(returns[m].total).toBeCloseTo(expected, 9)
        expect(returns[m].terms).toHaveLength(Math.min(8, last - index + 1))
      }
    }
  })

  it('gives every legal action the trust its training count implies, as the modules recorded it', () => {
    let checked = 0
    for (const tick of learned) {
      for (const action of tick.available_actions) {
        const n = trust.action_counts[`${tick.context_signature}|${action}`] ?? 0
        for (const m of Object.keys(tick.module_outputs)) {
          expect(trustLambda(n)).toBeCloseTo(tick.module_outputs[m]?.trust?.[action] ?? NaN, 3)
        }
        checked += 1
      }
      const contextN = trust.context_counts[tick.context_signature] ?? 0
      expect(trustLambda(contextN)).toBeCloseTo(tick.arbiter?.gate_share ?? NaN, 3)
    }
    expect(checked).toBeGreaterThan(400)
  })

  it("recomputes the arbiter's module weights from the table, the gate and g on every tick", () => {
    let checked = 0
    for (const tick of learned) {
      const blend = gateBlend(tick)
      if (!blend) continue
      for (const [m, w] of Object.entries(blend.used)) expect(blend.recomputed[m]).toBeCloseTo(w, 3)
      checked += 1
    }
    expect(checked).toBe(learned.length)
    expect(gateBlend(at(0))).toBeNull()
  })

  it('lays out the trust map: the actions ever tried, contexts by experience', () => {
    const actions = trustActions(trust, learnedMeta)
    expect(actions).toHaveLength(15)
    expect(actions).not.toContain('use')
    const rows = trustRows(trust, actions)
    expect(rows).toHaveLength(121)
    expect(rows[0]?.n).toBe(4668)
    expect(rows.reduce((s, r) => s + r.n, 0)).toBe(25204)
    expect(contextWords('hp:healthy|ammo:stocked|enemies:2:mid|dmg:clear|pickup:pickup_visible')).toBe(
      'healthy · stocked · 2 enemies mid · clear · pickup visible',
    )
    expect(contextWords('hp:medium|ammo:low|enemies:0:none|dmg:under_fire|pickup:no_pickup')).toBe(
      'medium · low · no enemies · under fire · no pickup',
    )
  })

  it('reproduces the exploration floor of every training episode and rolls means over 20', () => {
    for (const row of metrics) expect(floorAt(row.episode)).toBeCloseTo(row.exploration_floor, 4)
    expect(rolling([2, 4, 6], 2)).toEqual([2, 3, 5])
  })

  it('encodes an action by its composition, as the networks see it', () => {
    for (const id of ['weave_fire', 'circle_strafe_left', 'move_forward', 'retreat_to_cover']) {
      const action = learnedMeta.actions[id]
      if (!action) throw new Error(id)
      expect(encodeAction(action.primitives, action.is_macro)).toEqual(action.encoding.map((v) => expect.closeTo(v, 4)))
    }
    // An admitted macro is described the same way, the moment it joins the vocabulary.
    const burst = meta.actions.evasive_burst_1
    if (!burst) throw new Error('evasive_burst_1')
    expect(encodeAction(burst.primitives, burst.is_macro)).toEqual([0, 0.25, 0.25, 0.25, 0, 0, 0.25, 0, 0, 0.25, 1, 0])
    expect(burst.encoding).toEqual([0, 0.25, 0.25, 0.25, 0, 0, 0.25, 0, 0, 0.25, 1, 0])
  })
})

describe('growing the menu across the episode', async () => {
  const dir = (name: string) => fileURLToPath(new URL(`../../public/episodes/${name}/`, import.meta.url))
  const read = async (name: string) => ({
    ticks: parseJsonl<TickTrace>(await readFile(`${dir(name)}ticks.jsonl`, 'utf8'), 'ticks.jsonl'),
    proposals: parseJsonl<ProposalTrace>(await readFile(`${dir(name)}proposals.jsonl`, 'utf8'), 'proposals.jsonl'),
    meta: JSON.parse(await readFile(`${dir(name)}episode.json`, 'utf8')) as EpisodeMeta,
  })
  const heuristics = await read('deadly_corridor-heuristics-9')
  const learned = await read('deadly_corridor-learned-9')

  it('pairs each request with the proposal that answered it', () => {
    const spans = requestSpans(heuristics.ticks, heuristics.proposals)
    expect(spans.map((s) => [s.module, s.asked, s.arrived, s.proposal?.admitted_action_id])).toEqual([
      ['survival', 17, 18, 'evasive_burst_1'],
      ['survival', 28, 29, 'evasive_burst_2'],
    ])
    expect(requestSpans(learned.ticks, learned.proposals)).toEqual([])
  })

  it('reads each request from a rule that holds on that tick', () => {
    for (const { ticks } of [heuristics, learned]) {
      for (const tick of ticks) {
        const request = tick.slow_path_request
        if (request) expect(triggerAt(request.module as (typeof MODULES)[number], tick).asks).toBe(true)
      }
    }
    // Survival asked on health under 35 under heavy fire; its damage streak never reached 4.
    const t17 = heuristics.ticks.find((t) => t.tick === 17) as TickTrace
    expect(triggerAt('survival', t17)).toEqual({ value: 0, threshold: 4, other: true, asks: true })
    // No rule ever held in the learned recording.
    expect(learned.ticks.some((t) => MODULES.some((m) => triggerAt(m, t).asks))).toBe(false)
    expect(closestToAsking(learned.ticks)).toEqual({
      module: 'combat',
      tick: 2,
      counter: 'repeated_failures',
      value: 1,
      threshold: 3,
    })
  })

  it('splits the request context around the situation, which has colons of its own', () => {
    const first = heuristics.proposals[0] as ProposalTrace
    expect(requestContext(first)).toEqual({
      module: 'survival',
      signature: 'hp:medium|ammo:stocked|enemies:0:none|dmg:under_fire|pickup:no_pickup',
      description:
        'Existing evasion macros failed to prevent heavy incoming damage (health=34, recent_dmg=30, enemies=0).',
    })
    expect(preconditionWords(first.parsed_proposal?.preconditions as Record<string, unknown>)).toEqual([
      'ammo at least 1',
      'an enemy in view',
    ])
  })

  it('shows the proposal of this tick, or the last one before it', () => {
    const at = (tick: number) =>
      proposalShown(heuristics.ticks.find((t) => t.tick === tick) as TickTrace, heuristics.proposals)
    expect(at(17)).toBeNull()
    expect(at(18)).toMatchObject({ current: true, proposal: { admitted_action_id: 'evasive_burst_1' } })
    expect(at(27)).toMatchObject({ current: false, proposal: { admitted_action_id: 'evasive_burst_1' } })
    expect(at(29)).toMatchObject({ current: true, proposal: { admitted_action_id: 'evasive_burst_2' } })
    const level = gateLevel(heuristics.ticks.find((t) => t.tick === 18) as TickTrace, heuristics.proposals)
    expect(level.candidates.map((c) => c.value)).toEqual(['passed', 'passed', 'passed', 'skipped', 'passed'])
  })

  it('follows each admitted macro: never legal, never picked, its strategy adopted for eight ticks', () => {
    const [first, second] = heuristics.proposals.map((p) => followUp(p, heuristics.ticks))
    expect(first).toMatchObject({
      id: 'evasive_burst_1',
      joined: 18,
      ticksAfter: 18,
      legal: [],
      picked: [],
      rewards: [],
    })
    expect(first?.pruned).toEqual([{ reason: 'requires_visible_enemy', ticks: 18 }])
    expect(first?.adopted).toEqual([27, 28, 29, 30, 31, 32, 33, 34])
    // Steering decides after the action, so the arbiter used the strategy on the tick after each.
    expect(first?.bonus.map((b) => b.tick)).toEqual([28, 29, 30, 31, 32, 33, 34, 35])
    expect(new Set(first?.bonus.flatMap((b) => b.actions))).toEqual(new Set(['strafe_right']))
    expect(first?.bonus.filter((b) => b.actions.includes(b.selected)).map((b) => b.tick)).toEqual([28, 32])
    expect(second).toMatchObject({ id: 'evasive_burst_2', joined: 29, legal: [], picked: [], adopted: [] })
    expect(tickRange(first?.adopted ?? [])).toBe('27 to 34')
    expect(tickRange([28, 32])).toBe('28 and 32')
  })

  it('encodes the admitted macro like the built-in ones', () => {
    for (const id of ['evasive_burst_1', 'evasive_burst_2', 'weave_fire']) {
      const action = heuristics.meta.actions[id]
      expect(action).toBeDefined()
      expect(encodeAction(action?.primitives ?? [], action?.is_macro ?? false)).toEqual(action?.encoding)
    }
  })
})

describe('the command that makes a recording again', async () => {
  const meta = async (name: string) =>
    JSON.parse(
      await readFile(fileURLToPath(new URL(`../../public/episodes/${name}/episode.json`, import.meta.url)), 'utf8'),
    ) as EpisodeMeta

  it('gives the shipped recordings their export commands', async () => {
    expect(exportCommand(await meta('deadly_corridor-heuristics-9'))).toBe(
      'python -m system1_doom.export --scenario deadly_corridor.cfg --seed 9 --model heuristics --out web/public/episodes/deadly_corridor-heuristics-9',
    )
    expect(exportCommand(await meta('deadly_corridor-learned-9'))).toBe(
      'python -m system1_doom.export --scenario deadly_corridor.cfg --seed 9 --model latest --out web/public/episodes/deadly_corridor-learned-9',
    )
    expect(exportCommand(await meta('deadly_corridor-learned-d1-11'))).toBe(
      'python -m system1_doom.export --scenario deadly_corridor.cfg --seed 11 --model latest --out web/public/episodes/deadly_corridor-learned-d1-11 --d1 --d1-sync',
    )
  })

  it('adds only the flags that differ from the defaults', async () => {
    const base = await meta('deadly_corridor-learned-9')
    const changed: EpisodeMeta = {
      ...base,
      brains: { ...base.brains, d1_ultra: true, slow_path: 'codex' },
      config: { ...base.config, deterministic_arbiter: true, max_ticks: 200 },
    }
    expect(exportCommand(changed)).toBe(`${exportCommand(base)} --deterministic --d1 --codex --max-ticks 200`)
    const quiet = { ...base, brains: { ...base.brains, slow_path: 'off' as const } }
    expect(exportCommand(quiet)).toBe(`${exportCommand(base)} --no-slow-path`)
  })

  it('records a live episode under export’s own folder name, since live-<k> belongs to serve', async () => {
    const base = await meta('deadly_corridor-heuristics-9')
    expect(exportCommand({ ...base, name: 'live-4', seed: 12 })).toBe(
      'python -m system1_doom.export --scenario deadly_corridor.cfg --seed 12 --model heuristics --out web/public/episodes/deadly_corridor-heuristics-12',
    )
  })

  it('names the serve command with the flags that differ from its defaults', () => {
    const config = {
      scenario: 'deadly_corridor.cfg',
      seed: 7,
      model: 'latest' as const,
      d1: false,
      codex: false,
      slow_path: true,
      deterministic: false,
      max_ticks: 500,
      pace_sec: 0.23,
      episodes: null,
    }
    const plain = 'python -m system1_doom.serve --scenario deadly_corridor.cfg --seed 7 --model latest'
    expect(serveCommand(config)).toBe(plain)
    expect(
      serveCommand({
        ...config,
        d1: true,
        slow_path: false,
        deterministic: true,
        pace_sec: 0,
        episodes: 3,
        max_ticks: 90,
      }),
    ).toBe(`${plain} --deterministic --d1 --no-slow-path --max-ticks 90 --pace 0 --episodes 3`)
    expect(serveCommand({ ...config, d1: true, d1_sync: true })).toBe(`${plain} --d1 --d1-sync`)
    // serve refuses --d1-sync without --d1, so a status that says so has no flag to show.
    expect(serveCommand({ ...config, d1_sync: true })).toBe(plain)
  })

  it('tells an episode still being played from a finished one', async () => {
    const base = await meta('deadly_corridor-heuristics-9')
    expect(stillPlaying(base)).toBe(false)
    expect(stillPlaying({ ...base, result: { ...base.result, ticks: 0 } })).toBe(true)
  })

  it('tells an episode serve stopped by hand from one that ended, died or reached the cap', async () => {
    const base = await meta('deadly_corridor-heuristics-9')
    expect(stoppedEarly(base)).toBe(false)
    const open = { ...base.result, finished: false, cleared: false, died: false }
    expect(stoppedEarly({ ...base, result: { ...open, ticks: 7 }, tick_count: 7 })).toBe(true)
    // Still playing: serve's zero result, not a stop.
    expect(stoppedEarly({ ...base, result: { ...open, ticks: 0 }, tick_count: 7 })).toBe(false)
    const cap = base.config.max_ticks
    expect(stoppedEarly({ ...base, result: { ...open, ticks: cap }, tick_count: cap })).toBe(false)
    expect(stoppedEarly({ ...base, result: { ...open, ticks: 7, died: true }, tick_count: 7 })).toBe(false)
  })

  it('shows the recording time in UTC', () => {
    expect(utcStamp('2026-10-24T11:52:30.200613+00:00')).toBe('24 Oct 2026, 11:52 UTC')
    expect(utcStamp('not a time')).toBe('not a time')
  })
})

describe("d1-ultra's advice", async () => {
  const D1 = fileURLToPath(new URL('../../public/episodes/deadly_corridor-learned-d1-11/', import.meta.url))
  const d1Ticks = parseJsonl<TickTrace>(await readFile(`${D1}ticks.jsonl`, 'utf8'), 'ticks.jsonl')
  const d1Proposals = parseJsonl<ProposalTrace>(await readFile(`${D1}proposals.jsonl`, 'utf8'), 'proposals.jsonl')
  const d1Meta = JSON.parse(await readFile(`${D1}episode.json`, 'utf8')) as EpisodeMeta
  const d1At = (n: number) => d1Ticks.find((t) => t.tick === n) as TickTrace

  it("splits each module's bar into d1's part and the module's own softmax, which its utilities reproduce", () => {
    let checked = 0
    for (const tick of d1Ticks) {
      for (const m of d1Modules(tick)) {
        const out = tick.module_outputs[m]
        if (!out) continue
        const u = out.utility_blended ?? {}
        const top = Math.max(...Object.values(u))
        const exps = Object.fromEntries(
          Object.entries(u).map(([a, v]) => [a, Math.exp((v - top) / MODULE_TEMPERATURE)]),
        )
        const sum = Object.values(exps).reduce((s, v) => s + v, 0)
        for (const action of tick.available_actions) {
          const part = moduleD1Part(out, action)
          expect(part.fromD1 + part.local).toBeCloseTo(out.probabilities?.[action] ?? NaN, 6)
          expect(part.own).toBeCloseTo((exps[action] ?? NaN) / sum, 3)
        }
        // The weight follows the gap between the module's own two best utilities.
        const [first = 0, second = 0] = Object.values(u).sort((a, b) => b - a)
        expect(out.d1_weight).toBe(first - second >= D1_WEIGHT.gap ? D1_WEIGHT.settled : D1_WEIGHT.open)
        checked += 1
      }
    }
    expect(checked).toBeGreaterThan(100)
    // Without an answer the bar is the module's own.
    const own = moduleD1Part(at(0).module_outputs.survival as TickTrace['module_outputs'][string], 'shoot')
    expect(own).toMatchObject({ fromD1: 0, w: 0 })
  })

  it("ranks d1's answer to the arbiter and adds the bonus the trace recorded", () => {
    const answered = d1Ticks.filter((t) => d1Arbiter(t))
    expect(answered.length).toBeGreaterThan(30)
    for (const tick of answered) {
      const reading = d1Arbiter(tick)
      if (!reading) continue
      reading.ranked.slice(1).forEach((r, i) => expect(reading.ranked[i]?.p).toBeGreaterThanOrEqual(r.p))
      expect(reading.ranked[reading.pickRank]?.action).toBe(tick.selected_action)
      for (const r of reading.ranked) {
        const recorded = tick.arbiter?.component_breakdown?.[r.action]?.d1_bonus
        if (recorded !== undefined) expect(r.bonus).toBeCloseTo(recorded, 3)
      }
    }
    expect(d1Arbiter(at(0))).toBeNull()
  })

  it('says what d1 advised in words, and why a tick had no answer', () => {
    const tick = d1At(5)
    const words = d1Words(tick, d1Meta)
    expect(words).toContain(
      `For the arbiter it favoured ${(d1Arbiter(tick)?.ranked[0]?.action ?? '').replaceAll('_', ' ')}`,
    )
    expect(words).toContain('All five modules mixed its answer in.')
    expect(words).toContain(`After the action it put exploration at ${(d1Pressure(tick) ?? NaN).toFixed(2)}.`)
    expect(d1Words(at(0), meta)).toBe('Off in this recording.')
    const silent: TickTrace = { ...tick, d1_arbiter_distribution: {}, module_outputs: at(0).module_outputs }
    expect(d1Words(silent, d1Meta)).toMatch(/^No answer this tick: the call failed or ran out of time/)
  })

  it('explains the d1 stage of the gate from the probability and the rule', () => {
    expect(d1GateWords(0.62, true)).toBe('0.62 is at least 0.4, so this stage passed.')
    expect(d1GateWords(0.3, true)).toMatch(/but d1 rated its tactics at least 0\.85/)
    const [first, second] = d1Proposals
    expect(first?.admission_decision).toBe(false)
    expect(d1GateWords(first?.d1_admission_probability ?? NaN, false)).toMatch(/^0\.38 is under 0\.4, .* rejected/)
    expect(d1GateWords(second?.d1_admission_probability ?? NaN, false)).toBe(
      '0.15 is under 0.2, which rejects a macro whatever else d1 says.',
    )
  })

  it('marks a macro the gate turned away on the timeline and in the hierarchy', () => {
    const events = tickEvents(d1At(41), admissions(d1Proposals))
    expect(events.filter((e) => e.kind === 'rejection').map((e) => e.label)).toEqual([
      expect.stringMatching(/^rejected .* at the gate$/),
    ])
    expect(events.map((e) => e.kind)).not.toContain('admission')
    // The hierarchy stops the gate at the stage that failed.
    const gate = towerLevels(d1At(41), d1Meta, d1Proposals).find((l) => l.id === 'gate')
    expect(gate).toMatchObject({ choice: 'rejected', choiceLabel: 'rejected evasive burst 1 at d1' })
    expect(gate?.candidates.map((c) => c.id)).toEqual(['parse', 'legality', 'sandbox', 'd1'])
  })
})
