import { useId } from 'react'
import type { TickTrace } from '../schema/bundle'
import {
  MODULES,
  type ModuleName,
  explainPick,
  fmt,
  moduleVoteParts,
  pct,
  prettyId,
  rankedActions,
} from '../data/derive'
import { setState, useApp } from '../store'
import { Tip } from './Panel'

interface Segment {
  key: string
  value: number
  color: string
  style: 'solid' | 'hatched' | 'dotted'
  label: string
}

const OTHER_PARTS: Array<{ key: string; label: string; color: string; style: Segment['style'] }> = [
  { key: 'projection_term', label: 'simulator evidence (0.2 × EV)', color: 'var(--n1)', style: 'solid' },
  { key: 'strategy_bonus', label: 'active strategy bonus', color: 'var(--accent)', style: 'solid' },
  { key: 'd1_bonus', label: 'd1-ultra advice', color: 'var(--n1)', style: 'dotted' },
  { key: 'exploration_bonus', label: 'exploration bonus', color: 'var(--n2)', style: 'hatched' },
  { key: 'novelty_bonus', label: 'novelty bonus', color: 'var(--n3)', style: 'hatched' },
]

function segments(tick: TickTrace, action: string): { pos: Segment[]; neg: Segment[] } {
  const parts = tick.arbiter?.component_breakdown?.[action] ?? {}
  const pos: Segment[] = moduleVoteParts(tick, action).map((v) => ({
    key: v.module,
    value: v.value,
    color: `var(--${v.module})`,
    style: 'solid',
    label: `${v.module} vote: weight ${fmt(v.weight, 2)} × probability ${fmt(v.probability, 2)}`,
  }))
  const neg: Segment[] = []
  for (const part of OTHER_PARTS) {
    const value = parts[part.key] ?? 0
    if (value === 0) continue
    const seg = { key: part.key, value: Math.abs(value), color: part.color, style: part.style, label: part.label }
    if (value > 0) pos.push(seg)
    else neg.push(seg)
  }
  if ((parts.risk_penalty ?? 0) > 0) {
    neg.push({
      key: 'risk',
      value: parts.risk_penalty ?? 0,
      color: 'var(--risk)',
      style: 'solid',
      label: 'risk penalty for projected damage',
    })
  }
  if ((parts.execution_cost ?? 0) > 0) {
    neg.push({
      key: 'cost',
      value: parts.execution_cost ?? 0,
      color: 'var(--n3)',
      style: 'solid',
      label: 'execution cost',
    })
  }
  return { pos, neg }
}

function segStyle(seg: Segment, left: number, width: number) {
  return {
    left: `${left}%`,
    width: `${width}%`,
    ['--c' as string]: seg.color,
  }
}

function ScoreRows({ tick }: { tick: TickTrace }) {
  const depth = useApp((s) => s.depth)
  const hovered = useApp((s) => s.hoveredAction)
  const rows = rankedActions(tick)
  const all = rows.map((a) => ({ a, ...segments(tick, a) }))
  const maxPos = Math.max(0.001, ...all.map((r) => r.pos.reduce((s, x) => s + x.value, 0)))
  const maxNeg = Math.max(0, ...all.map((r) => r.neg.reduce((s, x) => s + x.value, 0)))
  const span = maxPos + maxNeg
  const toPct = (v: number) => ((v + maxNeg) / span) * 100
  const scores = tick.arbiter?.action_scores ?? {}
  return (
    <div className="score-rows">
      <span className="colhead">action</span>
      <span className="colhead">what the score is made of</span>
      <span className="colhead" style={{ textAlign: 'right' }}>
        score
      </span>
      <span className="colhead" style={{ textAlign: 'right' }}>
        chance
      </span>
      {all.map(({ a, pos, neg }) => {
        const rowCls = `${a === tick.selected_action ? 'is-selected' : ''} ${a === hovered ? 'row-hover' : ''}`
        let cursor = 0
        const posSegs = pos.map((seg) => {
          const left = toPct(cursor)
          cursor += seg.value
          return { seg, left, width: toPct(cursor) - left }
        })
        cursor = 0
        const negSegs = neg.map((seg) => {
          const right = toPct(-cursor)
          cursor += seg.value
          const left = toPct(-cursor)
          return { seg, left, width: right - left }
        })
        const total = scores[a] ?? 0
        const tip = (
          <>
            <strong>
              {prettyId(a)}: score {fmt(total, 3)}
            </strong>
            {[...pos, ...neg].map((s) => (
              <div key={s.key}>
                {neg.includes(s) ? '−' : '+'} {fmt(s.value, 3)} <span className="muted">{s.label}</span>
              </div>
            ))}
          </>
        )
        return (
          <div
            key={a}
            style={{ display: 'contents' }}
            data-action={a}
            onMouseEnter={() => setState({ hoveredAction: a })}
            onMouseLeave={() => setState({ hoveredAction: null })}
          >
            <span className={`row-label ${rowCls}`} title={a}>
              {a === tick.selected_action && <span className="pick-mark" aria-label="picked" />}
              {prettyId(a)}
            </span>
            <Tip body={tip} className={rowCls}>
              <span className="score-bar" style={{ width: '100%', display: 'block' }}>
                {[...posSegs, ...negSegs].map(({ seg, left, width }) => (
                  <span key={seg.key} className={`seg ${seg.style}`} style={segStyle(seg, left, width)} />
                ))}
                <span className="zero" style={{ left: `${toPct(0)}%` }} />
                <span className="total" style={{ left: `calc(${toPct(total)}% - 1px)` }} title="net score" />
              </span>
            </Tip>
            <span className={`num ${rowCls}`}>{depth === 'formula' ? fmt(total, 3) : fmt(total, 2)}</span>
            <span className={`num ${rowCls}`}>{pct(tick.arbiter_distribution[a] ?? 0, 0)}</span>
          </div>
        )
      })}
    </div>
  )
}

function arcPath(cx: number, cy: number, r: number, start: number, end: number): string {
  const sweep = Math.min(end - start, Math.PI * 2 - 1e-4)
  const x1 = cx + r * Math.sin(start)
  const y1 = cy - r * Math.cos(start)
  const x2 = cx + r * Math.sin(start + sweep)
  const y2 = cy - r * Math.cos(start + sweep)
  return `M${x1},${y1} A${r},${r} 0 ${sweep > Math.PI ? 1 : 0} 1 ${x2},${y2}`
}

function Ring({
  weights,
  r,
  width,
  fill,
}: {
  weights: Record<string, number>
  r: number
  width: number
  fill: (m: ModuleName) => string
}) {
  const total = MODULES.reduce((s, m) => s + (weights[m] ?? 0), 0) || 1
  const shares = MODULES.map((m) => (weights[m] ?? 0) / total)
  const starts = shares.map((_, i) => shares.slice(0, i).reduce((s, x) => s + x, 0) * Math.PI * 2)
  return (
    <>
      {MODULES.map((m, i) => {
        const share = shares[i] ?? 0
        const start = starts[i] ?? 0
        if (share <= 0) return null
        return (
          <path
            key={m}
            d={arcPath(100, 100, r, start, start + share * Math.PI * 2)}
            stroke={fill(m)}
            strokeWidth={width}
            fill="none"
          >
            <title>{`${m}: ${pct(share, 1)}`}</title>
          </path>
        )
      })}
    </>
  )
}

function Rings({ tick }: { tick: TickTrace }) {
  const id = useId().replaceAll(':', '')
  const arbiter = tick.arbiter
  const depth = useApp((s) => s.depth)
  if (!arbiter) return null
  const table = arbiter.module_weights_heuristic ?? {}
  const gate = arbiter.module_weights_gate ?? null
  const used = arbiter.module_weights ?? {}
  const g = arbiter.gate_share ?? 0
  return (
    <div className="rings">
      <figure>
        <svg
          viewBox="0 0 200 200"
          width="100%"
          style={{ maxWidth: 210 }}
          role="img"
          aria-label="Module weights: table ring outside, gate ring inside"
        >
          <defs>
            {MODULES.map((m) => (
              <pattern
                key={m}
                id={`${id}-${m}`}
                patternUnits="userSpaceOnUse"
                width="5"
                height="5"
                patternTransform="rotate(45)"
              >
                <rect width="5" height="5" fill={`var(--${m})`} opacity="0.3" />
                <rect width="2" height="5" fill={`var(--${m})`} />
              </pattern>
            ))}
          </defs>
          <circle cx={100} cy={100} r={84} stroke="var(--panel-3)" strokeWidth={16} fill="none" />
          <Ring weights={table} r={84} width={16} fill={(m) => `var(--${m})`} />
          <circle cx={100} cy={100} r={62} stroke="var(--panel-3)" strokeWidth={16} fill="none" />
          {gate && <Ring weights={gate} r={62} width={16} fill={(m) => `url(#${id}-${m})`} />}
          <text x={100} y={96} textAnchor="middle" fontSize={13} fill="var(--muted)">
            gate share
          </text>
          <text x={100} y={116} textAnchor="middle" fontSize={20} fontWeight={700} fill="var(--text)">
            {pct(g)}
          </text>
        </svg>
        <figcaption>
          Outer ring: the hand-written weight table. Inner ring: the learned gate
          {gate ? '' : ' (no gate in this episode)'}. The arbiter uses {pct(1 - g)} of the first and {pct(g)} of the
          second.
        </figcaption>
      </figure>
      {depth === 'formula' && (
        <div className="weights-table">
          <span />
          <span className="h">table</span>
          <span className="h">gate</span>
          <span className="h">used</span>
          {MODULES.map((m) => (
            <span key={m} style={{ display: 'contents' }}>
              <span style={{ color: `var(--${m})`, textTransform: 'capitalize' }}>{m}</span>
              <span className="r">{fmt(table[m] ?? 0, 2)}</span>
              <span className="r">{gate ? fmt(gate[m] ?? 0, 2) : '–'}</span>
              <span className="r">{fmt(used[m] ?? 0, 2)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

const RULES = [
  ['committed', 'a module commits'],
  ['explored', 'forced exploration'],
  ['greedy', 'top score'],
  ['sampled', 'sample when close'],
  ['critical_cached', 'out of time'],
] as const

export function ArbiterPanel({ tick }: { tick: TickTrace }) {
  const depth = useApp((s) => s.depth)
  const arbiter = tick.arbiter
  if (!arbiter || Object.keys(arbiter.action_scores ?? {}).length === 0) {
    const pick = explainPick(tick)
    return (
      <div className="pick-box">
        <strong>{pick.headline}</strong>
        <p>{pick.detail}</p>
      </div>
    )
  }
  const pick = explainPick(tick)
  return (
    <div className="arbiter-grid">
      <div>
        <ScoreRows tick={tick} />
        <div className="legend">
          {MODULES.map((m) => (
            <span key={m}>
              <span className="key solid" style={{ ['--c' as string]: `var(--${m})` }} />
              {m} vote
            </span>
          ))}
          {OTHER_PARTS.filter((p) => p.key !== 'd1_bonus' || tick.used_d1_ultra).map((p) => (
            <span key={p.key}>
              <span className={`key ${p.style}`} style={{ ['--c' as string]: p.color }} />
              {p.label}
            </span>
          ))}
          <span>
            <span className="key solid" style={{ ['--c' as string]: 'var(--risk)' }} />
            risk (left of zero)
          </span>
          <span>
            <span className="key solid" style={{ ['--c' as string]: 'var(--n3)' }} />
            cost (left of zero)
          </span>
        </div>
        <div className="pick-box" data-testid="pick">
          <strong>{pick.headline}</strong>
          <p>{pick.detail}</p>
          <div className="rule-chips" aria-label="The four picking rules">
            {RULES.map(([rule, words]) => (
              <span key={rule} className={`rule-chip ${arbiter.pick_rule === rule ? 'on' : ''}`}>
                {words}
              </span>
            ))}
          </div>
          {depth === 'formula' && (
            <p style={{ marginTop: 8 }}>
              Exploration pressure {fmt(arbiter.exploration_pressure ?? 0, 3)}, temperature{' '}
              {fmt(arbiter.temperature ?? 0, 3)}, score margin {fmt(arbiter.score_margin ?? 0, 3)}.
            </p>
          )}
        </div>
      </div>
      <Rings tick={tick} />
    </div>
  )
}
