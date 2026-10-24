import type { KeyboardEvent } from 'react'
import { BOXES, type BoxId } from '../content/architecture'
import {
  MODULES,
  fmt,
  learning,
  moduleOpinions,
  motorSteps,
  pct,
  prettyId,
  proposalId,
  signed,
  slowPathAt,
  strategyName,
} from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import type { TickTrace } from '../schema/bundle'

// The grid: the fast path down the middle, learning on the left, the slow path on the right.
const ROW = [56, 146, 236, 326, 416, 506]
const BOX_H = 60
const CHAIN = { x: 440, w: 240 }
const LEFT = { x: 20, w: 150 }
const SIM = { x: 230, w: 170 }
const SLOW_1 = { x: 730, w: 160 }
const SLOW_2 = { x: 940, w: 160 }

const RULE_WORDS: Record<string, string> = {
  committed: 'committed',
  explored: 'explored',
  greedy: 'top score',
  sampled: 'sampled',
  critical_cached: 'cached',
}

interface BoxGeometry {
  x: number
  y: number
  w: number
  h: number
}

const at = (col: { x: number; w: number }, row: number, h = BOX_H): BoxGeometry => ({
  x: col.x,
  y: (ROW[row] ?? 0) - h / 2,
  w: col.w,
  h,
})

const GEOMETRY: Partial<Record<BoxId, BoxGeometry>> = {
  freeze: at(CHAIN, 0),
  menu: at(CHAIN, 1),
  opinions: at(CHAIN, 2),
  decision: at(CHAIN, 3),
  act: at(CHAIN, 4),
  remember: at(CHAIN, 5),
  join: at(SLOW_1, 1),
  gate: at(SLOW_2, 1),
  request: at(SLOW_1, 2),
  worker: at(SLOW_2, 2),
  archive: at(SLOW_1, 3),
  d1: at(SLOW_2, 4),
  simulator: { x: SIM.x, y: 206, w: SIM.w, h: 150 },
  rewards: at(SIM, 5),
  replay: at(LEFT, 5),
  networks: { x: LEFT.x, y: 241, w: LEFT.w, h: 80 },
}

/** This tick's number for every box, read from the trace. */
function readings(bundle: EpisodeBundle, tick: TickTrace, tickIndex: number): Partial<Record<BoxId, string>> {
  const meta = bundle.meta
  const state = tick.state
  const legal = tick.available_actions.length
  const vocabulary = legal + Object.keys(tick.pruned_actions ?? {}).length
  const opinions = moduleOpinions(tick)
  const agree = opinions.filter((o) => o.agrees).length
  const plan = meta.actions[tick.selected_action]?.primitives ?? []
  const steps = motorSteps(plan, tick.primitive_steps_executed)
  const reflexes = steps.filter((s) => s.assisted).length
  const outcome = tick.outcome
  const rewards = outcome?.module_rewards ?? {}
  const loudest = [...MODULES].sort((a, b) => Math.abs(rewards[b] ?? 0) - Math.abs(rewards[a] ?? 0))[0]
  const slow = slowPathAt(tick, bundle.proposals)
  const arrived = slow.arrived[0]
  const flight = inFlight(bundle, tickIndex)
  const view = learning(tick)
  const enemies = state?.enemies?.length ?? 0
  return {
    freeze: state ? `health ${fmt(state.health, 0)} · ${enemies} ${enemies === 1 ? 'enemy' : 'enemies'} in view` : '',
    menu: `${legal} of ${vocabulary} legal`,
    opinions: `${agree} of ${opinions.length} agree with the pick`,
    decision: `${prettyId(tick.selected_action)} · ${RULE_WORDS[tick.arbiter?.pick_rule ?? 'greedy'] ?? ''}`,
    act: `${steps.length} steps · ${reflexes} ${reflexes === 1 ? 'reflex' : 'reflexes'}`,
    remember: `reward ${signed(outcome?.reward ?? 0, 1)} · damage ${fmt(outcome?.damage_taken ?? 0, 0)}`,
    request: slow.request ? `${slow.request.module} asked` : 'no request',
    worker:
      meta.brains.slow_path === 'off'
        ? 'off'
        : flight
          ? `writing (asked at t${flight})`
          : meta.brains.slow_path === 'codex'
            ? 'Codex, idle'
            : 'templates, idle',
    gate: arrived
      ? arrived.admission_decision
        ? 'admitted'
        : `rejected at ${(arrived.stage_results ?? []).find((s) => !s.passed)?.stage ?? 'parse'}`
      : 'nothing to check',
    join:
      arrived?.admission_decision === true
        ? `+ ${prettyId(proposalId(arrived))}`
        : `${slow.admittedSoFar.length} added so far`,
    rewards: loudest ? `${loudest} ${signed(rewards[loudest] ?? 0, 2)}` : '',
    replay: 'not in the trace',
    networks: meta.brains.learned_networks
      ? `λ ${pct(view.network_share ?? 0)} · g ${pct(view.gate_share ?? 0)}`
      : 'off',
    simulator: `${Object.keys(tick.projection_results_used).length} actions projected`,
    archive: strategyName(tick.steering?.active_before ?? tick.active_strategy),
    d1: meta.brains.d1_ultra ? (tick.used_d1_ultra ? 'advised' : 'no answer') : 'off',
  }
}

/** The tick a still-unanswered request was made at, if the slow worker is busy at this tick. */
function inFlight(bundle: EpisodeBundle, tickIndex: number): number | null {
  for (let i = tickIndex; i >= 0; i -= 1) {
    const t = bundle.ticks[i]
    if (!t) continue
    if (i < tickIndex && bundle.proposals.some((p) => p.tick === t.tick)) return null
    if (t.slow_path_request) {
      const asked = t.tick
      const current = bundle.ticks[tickIndex]?.tick ?? asked
      const answered = bundle.proposals.some((p) => (p.tick ?? -1) > asked && (p.tick ?? Infinity) <= current)
      return answered ? null : asked
    }
  }
  return null
}

function Box({
  id,
  value,
  lit,
  off,
  selected,
  onSelect,
}: {
  id: BoxId
  value: string
  lit?: boolean
  off?: boolean
  selected: boolean
  onSelect: (id: BoxId) => void
}) {
  const g = GEOMETRY[id]
  if (!g) return null
  const box = BOXES[id]
  const onKey = (e: KeyboardEvent<SVGGElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onSelect(id)
    }
  }
  const midY = g.y + g.h / 2
  return (
    <g
      className={`arch-box ${box.beat ? 'beat' : ''} ${lit ? 'lit' : ''} ${off ? 'off' : ''} ${selected ? 'selected' : ''}`}
      data-box={id}
      role="button"
      tabIndex={0}
      aria-label={`${box.title}: ${value}`}
      aria-pressed={selected}
      onClick={() => onSelect(id)}
      onKeyDown={onKey}
    >
      <rect x={g.x} y={g.y} width={g.w} height={g.h} rx={10} />
      {box.beat && (
        <>
          <circle cx={g.x + 18} cy={g.y + 18} r={10} className="arch-beat" />
          <text x={g.x + 18} y={g.y + 22} textAnchor="middle" className="arch-beat-num">
            {box.beat}
          </text>
        </>
      )}
      <text x={g.x + g.w / 2} y={midY - 4} textAnchor="middle" className="arch-title">
        {box.title}
      </text>
      <text x={g.x + g.w / 2} y={midY + 15} textAnchor="middle" className="arch-value">
        {value}
      </text>
    </g>
  )
}

function Label({
  id,
  x,
  y,
  text,
  off,
  selected,
  onSelect,
}: {
  id: BoxId
  x: number
  y: number
  text: string
  off?: boolean
  selected: boolean
  onSelect: (id: BoxId) => void
}) {
  const w = text.length * 7.5 + 18
  return (
    <g
      className={`arch-label ${off ? 'off' : ''} ${selected ? 'selected' : ''}`}
      data-box={id}
      role="button"
      tabIndex={0}
      aria-label={`${BOXES[id].title}: open its explanation`}
      onClick={() => onSelect(id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect(id)
        }
      }}
    >
      <rect x={x - w / 2} y={y - 11} width={w} height={22} rx={11} />
      <text x={x} y={y + 4} textAnchor="middle">
        {text}
      </text>
    </g>
  )
}

/**
 * The whole controller on one page: the six-beat fast path, the slow path that grows the menu, the
 * learning that re-weighs it between episodes, and the side inputs. Every box shows this tick.
 */
export function Architecture({
  bundle,
  tick,
  tickIndex,
  playing,
  selected,
  onSelect,
}: {
  bundle: EpisodeBundle
  tick: TickTrace
  tickIndex: number
  playing: boolean
  selected: BoxId | null
  onSelect: (id: BoxId) => void
}) {
  const meta = bundle.meta
  const values = readings(bundle, tick, tickIndex)
  const slow = slowPathAt(tick, bundle.proposals)
  const learned = meta.brains.learned_networks
  const d1 = meta.brains.d1_ultra
  const box = (id: BoxId, extra: { lit?: boolean; off?: boolean } = {}) => (
    <Box key={id} id={id} value={values[id] ?? ''} selected={selected === id} onSelect={onSelect} {...extra} />
  )
  const chainX = CHAIN.x + CHAIN.w / 2
  return (
    <svg
      className="architecture"
      viewBox="0 0 1130 580"
      role="group"
      aria-label="The controller's architecture at this tick; every box opens its explanation"
    >
      <defs>
        <marker id="arch-head" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" className="arch-head" />
        </marker>
      </defs>

      {/* Region labels. */}
      <text x={CHAIN.x + CHAIN.w / 2} y={14} textAnchor="middle" className="arch-region">
        THE FAST PATH · EVERY TICK
      </text>
      <text x={SLOW_1.x + 185} y={96} textAnchor="middle" className="arch-region">
        THE SLOW PATH · GROWS THE MENU
      </text>
      <text x={LEFT.x} y={566} className="arch-region">
        LEARNING · BETWEEN EPISODES
      </text>

      {/* The fast path. */}
      {ROW.slice(0, -1).map((y) => (
        <line
          key={y}
          x1={chainX}
          y1={y + BOX_H / 2}
          x2={chainX}
          y2={y + 90 - BOX_H / 2 - 2}
          className="arch-edge"
          markerEnd="url(#arch-head)"
        />
      ))}

      {/* The slow path loop: opinions → request → worker → gate → joins the menu → menu. */}
      <g className={`arch-flow ${slow.request || slow.arrived.length > 0 ? 'lit' : ''}`}>
        <path d="M680,226 H728" className="arch-edge" markerEnd="url(#arch-head)" />
        <path d="M890,236 H938" className="arch-edge" markerEnd="url(#arch-head)" />
        <path d="M1020,206 V178" className="arch-edge" markerEnd="url(#arch-head)" />
        <path d="M940,146 H892" className="arch-edge" markerEnd="url(#arch-head)" />
        <path d="M730,146 H682" className="arch-edge" markerEnd="url(#arch-head)" />
      </g>

      {/* Learning: outcome → five rewards → replay → networks → trust λ and the gate share. */}
      <path d="M440,506 H402" className="arch-edge" markerEnd="url(#arch-head)" />
      <path d="M230,506 H172" className="arch-edge" markerEnd="url(#arch-head)" />
      <path d="M95,476 V323" className="arch-edge learned" markerEnd="url(#arch-head)" />
      <path
        d="M170,256 H200 V191 H420 V216 H438"
        className={`arch-edge learned ${learned ? '' : 'off'}`}
        markerEnd="url(#arch-head)"
      />
      <path
        d="M170,306 H200 V371 H420 V346 H438"
        className={`arch-edge learned ${learned ? '' : 'off'}`}
        markerEnd="url(#arch-head)"
      />

      {/* The simulator's evidence, read by the opinions and the arbiter. */}
      <path d="M400,246 H438" className="arch-edge" markerEnd="url(#arch-head)" />
      <path d="M400,316 H438" className="arch-edge" markerEnd="url(#arch-head)" />

      {/* Steering: decided after the action, its strategy's bonus applies to the next arbiter. */}
      <path d="M680,496 H810 V358" className="arch-edge" markerEnd="url(#arch-head)" />
      <path d="M730,326 H682" className="arch-edge" markerEnd="url(#arch-head)" />
      <text x={818} y={470} className="arch-note">
        steering, after the action
      </text>
      <text x={684} y={344} className="arch-note">
        +0.15
      </text>

      {/* d1-ultra: dotted, into the opinions, the arbiter and the gate's d1 stage. */}
      <g className={`arch-d1 ${d1 ? '' : 'off'}`}>
        <path d="M1020,386 V281 H700 V251 H682" className="arch-edge dotted" markerEnd="url(#arch-head)" />
        <path d="M700,281 V306 H682" className="arch-edge dotted" markerEnd="url(#arch-head)" />
        <path d="M1100,416 H1115 V146 H1102" className="arch-edge dotted" markerEnd="url(#arch-head)" />
      </g>

      {box('freeze')}
      {box('menu', { lit: slow.arrived.some((p) => p.admission_decision) })}
      {box('opinions')}
      {box('decision')}
      {box('act')}
      {box('remember')}
      {box('request', { lit: !!slow.request })}
      {box('worker', { lit: !!slow.request || values.worker?.startsWith('writing') })}
      {box('gate', { lit: slow.arrived.length > 0 })}
      {box('join', { lit: slow.arrived.some((p) => p.admission_decision) })}
      {box('archive')}
      {box('d1', { off: !d1 })}
      {box('simulator')}
      {box('rewards')}
      {box('replay')}
      {box('networks', { off: !learned })}
      <Label
        id="trust"
        x={310}
        y={191}
        text="trust λ"
        off={!learned}
        selected={selected === 'trust'}
        onSelect={onSelect}
      />
      <Label
        id="gateShare"
        x={310}
        y={371}
        text="gate share g"
        off={!learned}
        selected={selected === 'gateShare'}
        onSelect={onSelect}
      />

      {playing && <circle key={tickIndex} className="pulse" cx={chainX} cy={ROW[0]} r={7} />}
    </svg>
  )
}
