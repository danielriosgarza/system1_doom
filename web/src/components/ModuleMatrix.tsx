import type { EpisodeMeta, ModuleTrace, TickTrace } from '../schema/bundle'
import {
  D1_WEIGHT,
  EXPANSION_TRIGGERS,
  MEMORY_LABELS,
  MODULES,
  type ModuleName,
  TRUST_COUNT,
  fmt,
  moduleD1Part,
  pct,
  prettyId,
  rankedActions,
} from '../data/derive'
import { setState, useApp } from '../store'
import { Tip } from './Panel'

const color = (m: ModuleName) => `var(--${m})`

function ProbabilityBar({ module, out, action }: { module: ModuleName; out: ModuleTrace; action: string }) {
  const p = out.probabilities?.[action] ?? 0
  const lambda = out.trust?.[action] ?? 0
  // d1's part differs per action: its answer for this action against the module's own softmax.
  const d1 = p > 0 ? moduleD1Part(out, action).fromD1 / p : 0
  return (
    <span className="bar-track" style={{ ['--c' as string]: color(module) }}>
      <span className="bar-fill" style={{ width: `${p * 100}%` }}>
        <span className="solid" style={{ width: `${(1 - lambda) * (1 - d1) * 100}%` }} />
        <span className="hatched" style={{ width: `${lambda * (1 - d1) * 100}%` }} />
        <span className="dotted" style={{ width: `${d1 * 100}%` }} />
      </span>
    </span>
  )
}

function CellTip({ module, out, action }: { module: ModuleName; out: ModuleTrace; action: string }) {
  const h = out.utility_heuristic?.[action]
  const l = out.utility_learned?.[action]
  const lambda = out.trust?.[action]
  const u = out.utility_blended?.[action]
  const p = out.probabilities?.[action] ?? 0
  const d1 = moduleD1Part(out, action)
  const n = lambda !== undefined && lambda < 1 ? (TRUST_COUNT * lambda) / (1 - lambda) : undefined
  return (
    <>
      <strong>
        {module} on {prettyId(action)}: {pct(p, 1)}
      </strong>
      {h !== undefined && <div>Heuristic score {fmt(h, 2)}</div>}
      {l !== undefined && lambda !== undefined ? (
        <>
          <div>Network&apos;s learned value {fmt(l, 2)}</div>
          <div>
            Trust λ {fmt(lambda, 2)}
            {n !== undefined && <span className="muted"> (tried about {fmt(n, 0)} times in this situation)</span>}
          </div>
          {u !== undefined && <div>Blended score {fmt(u, 2)}</div>}
        </>
      ) : (
        <div className="muted">No network loaded: the heuristic score is used as is.</div>
      )}
      {out.used_d1_ultra && (
        <div>
          d1-ultra gave it {pct(d1.d1, 1)}, mixed in at weight {fmt(out.d1_weight ?? 0, 2)}: {pct(d1.fromD1, 1)} of the{' '}
          {pct(p, 1)} came from d1.
        </div>
      )}
      {out.top_action === action && <div>This is the module&apos;s first choice.</div>}
    </>
  )
}

/** What d1-ultra answered this module's question with, under the column's heading. */
function D1Line({ out }: { out: ModuleTrace }) {
  const top = out.d1_top_action
  if (!out.used_d1_ultra || !top) return null
  return (
    <div className="d1-line" data-testid="module-d1">
      <span className="key dotted" aria-hidden />
      d1: {prettyId(top)} {pct(out.d1_probabilities?.[top] ?? 0)}, weight {fmt(out.d1_weight ?? 0, 2)}
    </div>
  )
}

export function ModuleMatrix({ tick, meta }: { tick: TickTrace; meta: EpisodeMeta }) {
  const depth = useApp((s) => s.depth)
  const hovered = useApp((s) => s.hoveredAction)
  const rows = rankedActions(tick)
  const modules = MODULES.filter((m) => tick.module_outputs[m])
  if (modules.length === 0) {
    return <p className="empty-note">No module opinions this tick: the budget allowed only a cached decision.</p>
  }
  const learned = modules.some((m) => Object.keys(tick.module_outputs[m]?.utility_learned ?? {}).length > 0)
  const d1 = modules.some((m) => tick.module_outputs[m]?.used_d1_ultra)
  return (
    <>
      <div className="scroll-x">
        <div className="matrix" role="table" aria-label="Each module's probability for each legal action">
          <div className="rowband" role="row">
            <div className="cell head" role="columnheader">
              <span className="question">Legal actions, best final score first</span>
            </div>
            {modules.map((m) => {
              const out = tick.module_outputs[m] as ModuleTrace
              return (
                <div key={m} className="cell head" role="columnheader" style={{ ['--c' as string]: color(m) }}>
                  <div className="module-name">{m}</div>
                  <div className="question">{meta.modules[m] ?? ''}</div>
                  <div className="confidence">
                    sure {pct(out.confidence ?? 0)}
                    <div className="meter">
                      <div style={{ width: `${(out.confidence ?? 0) * 100}%`, background: color(m) }} />
                    </div>
                  </div>
                  <D1Line out={out} />
                </div>
              )
            })}
          </div>
          {rows.map((a) => {
            const rowCls = `${a === tick.selected_action ? 'is-selected' : ''} ${a === hovered ? 'row-hover' : ''}`
            return (
              <div
                key={a}
                className="rowband"
                role="row"
                data-action={a}
                onMouseEnter={() => setState({ hoveredAction: a })}
                onMouseLeave={() => setState({ hoveredAction: null })}
              >
                <div className={`cell ${rowCls}`} role="rowheader">
                  <div className="row-label" title={a}>
                    {a === tick.selected_action && <span className="pick-mark" aria-label="picked" />}
                    {prettyId(a)}
                  </div>
                </div>
                {modules.map((m) => {
                  const out = tick.module_outputs[m] as ModuleTrace
                  const p = out.probabilities?.[a] ?? 0
                  return (
                    <div key={m} className={`cell ${rowCls}`} role="cell" style={{ ['--c' as string]: color(m) }}>
                      <Tip body={<CellTip module={m} out={out} action={a} />} className="module-cell-wrap">
                        <span className={`module-cell ${out.top_action === a ? 'top' : ''}`} style={{ width: '100%' }}>
                          <ProbabilityBar module={m} out={out} action={a} />
                          {depth === 'formula' && <span className="num">{pct(p, 0)}</span>}
                        </span>
                      </Tip>
                    </div>
                  )
                })}
              </div>
            )
          })}
          <div className="rowband" role="row">
            <div className="cell foot" role="rowheader">
              Memory and trigger
            </div>
            {modules.map((m) => {
              const out = tick.module_outputs[m] as ModuleTrace
              const trigger = EXPANSION_TRIGGERS[m]
              const memory = out.memory ?? {}
              const counter = trigger.counter ? memory[trigger.counter] : undefined
              const sent = tick.slow_path_request?.module === m
              return (
                <div key={m} className="cell foot" role="cell" style={{ ['--c' as string]: color(m) }}>
                  {trigger.counter && (
                    <div>
                      {MEMORY_LABELS[trigger.counter]} {counter ?? 0} of {trigger.threshold}
                    </div>
                  )}
                  <div className="question">Asks for a new macro after {trigger.rule}.</div>
                  {out.request_action_expansion && (
                    <div className="flag">
                      <strong>Asked for a new macro{sent ? '' : ' (not sent: the slow path was busy)'}.</strong>{' '}
                      {out.expansion_problem}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
      <div className="legend">
        <span>
          <span className="key solid" style={{ ['--c' as string]: 'var(--n2)' }} />
          from the hand-written heuristic
        </span>
        <span>
          <span className="key hatched" style={{ ['--c' as string]: 'var(--n2)' }} />
          from the learned network (its share is trust λ)
        </span>
        <span>
          <span className="key dotted" style={{ ['--c' as string]: 'var(--n2)' }} />
          from d1-ultra advice (mixed in at {D1_WEIGHT.open}, or {D1_WEIGHT.settled} when the module&apos;s own top
          leads by {D1_WEIGHT.gap})
        </span>
        <span>A ringed bar is that module&apos;s first choice.</span>
        {!learned && !d1 && <span>No networks in this episode, so every bar is solid.</span>}
        {!learned && d1 && <span>No networks in this episode: the rest of every bar is the heuristic.</span>}
      </div>
    </>
  )
}
