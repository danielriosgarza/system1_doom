import { beforeAll, describe, expect, it } from 'vitest'
import { loadFixture } from '../test/fixture'
import type { EpisodeBundle } from './loader'
import {
  CHANNELS,
  actRow,
  bars,
  centralRow,
  configurationAt,
  episodeEntries,
  instanceView,
  keysPressed,
  ledgerBeforeAfter,
  nStepReturns,
  placedCycles,
  sections,
  senseRows,
  shownChannels,
  tickMarks,
  valuesAt,
  versionTimeline,
} from './readings'

let bundle: EpisodeBundle

beforeAll(async () => {
  bundle = await loadFixture()
})

const tick = (i: number) => {
  const t = bundle.ticks[i]
  if (!t) throw new Error(`no tick ${i}`)
  return t
}

describe('the strip at one tick', () => {
  it('has a row for each of the five senses, in sense order, with spoke or silent, strength, action and reason', () => {
    const rows = senseRows(tick(0))
    expect(rows.map((r) => r.name)).toEqual(['survival', 'combat', 'navigation', 'resource', 'goal'])
    expect(rows.map((r) => r.spoke)).toEqual([true, true, false, false, false])
    expect(rows[0]).toMatchObject({ strength: 0.9, action: 'weave_fire', reason: 'enemy_too_close', followed: true })
    // Combat spoke for turn left; the central executed weave fire, so combat was overruled.
    expect(rows[1]).toMatchObject({ action: 'turn_left', spoke: true, followed: false })
    expect(rows[2]).toMatchObject({ spoke: false, missed: false })
  })

  it('shows a missed sense as missed, with its reason and no answer', () => {
    const nav = senseRows(tick(3)).find((r) => r.name === 'navigation')
    expect(nav).toMatchObject({ missed: true, missReason: 'error', spoke: false, action: null, strength: null })
  })

  it('reads the central row from the pick: kind, action, probability and the messages heard', () => {
    expect(centralRow(tick(0))).toMatchObject({ kind: 'top', action: 'weave_fire', probability: 0.7, heard: 2 })
    expect(centralRow(tick(5))).toMatchObject({ kind: 'missed', action: null, missReason: 'off_menu' })
  })

  it('reads Act as the keys held over the eight frames', () => {
    const act = actRow(tick(0))
    expect(act.action).toBe('weave_fire')
    expect(act.keys).toBe('strafe left ×2, turn left ×4, strafe right ×2')
    expect(keysPressed(['idle', 'idle'])).toBe('nothing pressed')
  })
})

describe('an instance at one tick', () => {
  it('keeps the evidence verbatim: the sections put back together are the text that was sent', () => {
    const r = tick(0).instances.survival
    if (!r) throw new Error('no survival')
    const rebuilt = sections(r.evidence)
      .map((s) => (s.channel ? `[${s.channel}]\n${s.body}` : s.body))
      .join('\n\n')
    expect(rebuilt).toBe(r.evidence.trimEnd())
  })

  it('shows the survival sense only its scope: its text has no [pickups] before System 2 widened it', () => {
    const view = instanceView(tick(0), 'survival')
    expect(view?.scope).toEqual(['vitals', 'threats', 'incoming', 'menu', 'projections'])
    expect(shownChannels(tick(0).instances.survival?.evidence ?? '')).not.toContain('pickups')
    expect(tick(0).instances.survival?.evidence).not.toContain('[pickups]')
    expect(view?.hidden).toContain('pickups')
    expect(view?.hidden).toHaveLength(CHANNELS.length - 5)
  })

  it('shows the survival sense [pickups] once version 3 widened its scope', () => {
    expect(tick(30).configuration_version).toBe(3)
    expect(shownChannels(tick(30).instances.survival?.evidence ?? '')).toContain('pickups')
    expect(instanceView(tick(30), 'survival')?.hidden).not.toContain('pickups')
  })

  it('never shows a sense the central-only channels: combat has no [messages]', () => {
    for (const t of bundle.ticks) {
      expect(t.instances.combat?.evidence).not.toContain('[messages]')
      expect(t.instances.combat?.evidence).not.toContain('[relevance]')
    }
    expect(shownChannels(tick(0).instances.central?.evidence ?? '')).toEqual(
      expect.arrayContaining(['messages', 'relevance', 'exploration']),
    )
  })

  it('gives the frame only to an instance whose scope holds it', () => {
    expect(instanceView(tick(3), 'combat')?.imageRef).toBe('frames/00003.jpg')
    expect(instanceView(tick(3), 'survival')?.imageRef).toBeNull()
  })

  it('shows the answers as bars, highest first, the instance’s answer marked', () => {
    const view = instanceView(tick(0), 'survival')
    expect(view?.speak).toBeGreaterThanOrEqual(0.5)
    expect(view?.actionBars[0]).toMatchObject({ label: 'weave_fire', top: true })
    const ps = view?.actionBars.map((b) => b.p) ?? []
    expect(ps).toEqual([...ps].sort((a, b) => b - a))
    expect(bars({ a: 0.2, b: 0.8 }, 'b')).toEqual([
      { label: 'b', p: 0.8, top: true },
      { label: 'a', p: 0.2, top: false },
    ])
  })

  it('shows a miss with its reason and the raw answer as returned', () => {
    const central = instanceView(tick(5), 'central')
    expect(central).toMatchObject({ missed: true, missReason: 'off_menu' })
    expect(central?.error).toMatch(/teleport_hack is not among the options/)
    expect(central?.raw).toContain('"choice": "teleport_hack"')
    const nav = instanceView(tick(3), 'navigation')
    expect(nav).toMatchObject({ missed: true, missReason: 'error', raw: null })
  })
})

describe('the configuration versions System 2 made', () => {
  it('reads version 1 from the start, version 2 a kept macro, version 3 the widened survival scope, kept', () => {
    const timeline = versionTimeline(bundle)
    expect(timeline.map((e) => [e.version, e.status, e.change])).toEqual([
      [1, 'start', 'the design’s initial configuration'],
      [2, 'kept', 'macro:combat'],
      [3, 'kept', 'widen:survival:pickups'],
    ])
    expect(timeline.map((e) => e.tickIndex)).toEqual([0, 10, 27])
    expect(timeline[1]?.changes.join(' ')).toMatch(/admitted macros/)
    expect(timeline[2]?.cycle?.history_test?.status).toBe('passed')
    expect(timeline[2]?.verdict?.trial.verdict).toBe('keep')
  })

  it('says which trial is in flight at a tick, and none once the verdict is in', () => {
    const timeline = versionTimeline(bundle)
    const during = configurationAt(bundle, timeline, 12)
    expect(during.version).toBe(2)
    expect(during.trial).toMatchObject({ decisions: 2 })
    expect(during.trial?.of).toBeGreaterThan(0)
    expect(configurationAt(bundle, timeline, 0)).toMatchObject({ version: 1, trial: null })
    expect(configurationAt(bundle, timeline, 22)).toMatchObject({ version: 2, trial: null })
    expect(configurationAt(bundle, timeline, 39).trial).toBeNull()
  })

  it('places every cycle on the tick it came after, in order', () => {
    const placed = placedCycles(bundle)
    expect(placed.map((p) => p.cycle.outcome)).toEqual([
      'macro_requested',
      'no_proposal',
      'queued',
      'no_proposal',
      'no_proposal',
    ])
    const at = placed.map((p) => p.tickIndex)
    expect(at).toEqual([...at].sort((a, b) => a - b))
  })

  it('marks the timeline with damage, kills, misses, changes and cycles', () => {
    const marks = tickMarks(bundle)
    expect(marks).toHaveLength(bundle.ticks.length)
    expect(marks[1]).toContain('damage')
    expect(marks[2]).toContain('kill')
    expect(marks[3]).toContain('miss')
    expect(marks[5]).toContain('miss')
    expect(marks[10]).toContain('change')
    expect(marks[27]).toContain('change')
    expect(marks.flat().filter((m) => m === 'cycle')).toHaveLength(5)
  })
})

describe('the relevance ledger', () => {
  it('computes the n-step return truncated at the episode end', () => {
    expect(nStepReturns([1, 0, 1], 2, 0.5)).toEqual([1, 0.5, 1])
  })

  it('counts each message once, followed or overruled', () => {
    const entries = episodeEntries(bundle.ticks, 8, 0.9)
    const spoke = Object.values(entries).reduce((n, c) => n + c.spoke, 0)
    const messages = bundle.ticks.filter((t) => t.executed_action).reduce((n, t) => n + (t.messages?.length ?? 0), 0)
    expect(spoke).toBe(messages)
    for (const c of Object.values(entries)) expect(c.followed + c.overruled).toBe(c.spoke)
  })

  it('reads the ledger before and after the episode, never below zero', () => {
    const [before, after] = ledgerBeforeAfter(bundle)
    expect(before?.episodes).toBe((bundle.relevance?.episodes ?? 0) - 1)
    expect(after?.episodes).toBe(bundle.relevance?.episodes)
    for (const point of [before, after]) {
      for (const c of Object.values(point?.totals ?? {})) {
        for (const v of Object.values(c)) expect(v).toBeGreaterThanOrEqual(0)
      }
    }
    expect(after?.totals.survival?.spoke).toBeGreaterThan(before?.totals.survival?.spoke ?? 0)
  })
})

describe('the values channel', () => {
  it('reads each value network’s number and the tried count, per legal action, from the text the goal sense saw', () => {
    const values = valuesAt(tick(0))
    expect(values.instance).toBe('goal')
    expect(values.header).toMatch(/^learned from past play/)
    expect(values.rows[0]).toEqual({
      action: 'move_forward',
      predictions: { survival: -0.04, combat: -0.02, navigation: 0.02, resource: -0.04, goal: 0.05 },
      tried: 0,
    })
  })
})
