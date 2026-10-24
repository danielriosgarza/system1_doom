import type { TickTrace } from '../schema/bundle'
import { fmt, pct, prettyId, rankedActions } from '../data/derive'
import { setState, useApp } from '../store'

export function ProjectionStrip({ tick }: { tick: TickTrace }) {
  const depth = useApp((s) => s.depth)
  const hovered = useApp((s) => s.hoveredAction)
  const projections = tick.projection_results_used
  const rows = rankedActions(tick)
  if (Object.keys(projections).length === 0) {
    return <p className="empty-note">No projections this tick: the budget allowed only a cached decision.</p>
  }
  const values = rows.map((a) => projections[a]?.expected_value ?? 0)
  const maxAbs = Math.max(0.001, ...values.map(Math.abs))
  const hasNeg = values.some((v) => v < 0)
  const zero = hasNeg ? 50 : 0
  const scale = hasNeg ? 50 : 100
  const formula = depth === 'formula'
  const columns = formula
    ? ['value', 'harm in', 'harm out', 'resources', 'survival', 'samples']
    : ['harm in', 'survival']
  const chain = tick.projection_chain
  return (
    <>
      <div className="scroll-x">
        <div
          className="proj-rows"
          style={{ gridTemplateColumns: `minmax(110px, 150px) minmax(60px, 1fr) repeat(${columns.length}, 62px)` }}
        >
          <span className="colhead left">action</span>
          <span className="colhead left">expected value</span>
          {columns.map((c) => (
            <span key={c} className="colhead">
              {c}
            </span>
          ))}
          {rows.map((a) => {
            const p = projections[a]
            const rowCls = `${a === tick.selected_action ? 'is-selected' : ''} ${a === hovered ? 'row-hover' : ''}`
            const enter = () => setState({ hoveredAction: a })
            const leave = () => setState({ hoveredAction: null })
            if (!p) {
              return (
                <div
                  key={a}
                  className={rowCls}
                  style={{ display: 'contents' }}
                  onMouseEnter={enter}
                  onMouseLeave={leave}
                >
                  <span className="row-label">{prettyId(a)}</span>
                  <span className="empty-note" style={{ gridColumn: `span ${columns.length + 1}` }}>
                    not projected: the 15 ms budget ran out first
                  </span>
                </div>
              )
            }
            const ev = p.expected_value ?? 0
            const width = (Math.abs(ev) / maxAbs) * scale
            const nums: Record<string, number> = {
              value: ev,
              'harm in': p.expected_damage_taken ?? 0,
              'harm out': p.expected_damage_dealt ?? 0,
              resources: p.expected_resource_gain ?? 0,
              survival: p.survival_probability ?? 0,
              samples: p.empirical_samples ?? 0,
            }
            return (
              <div key={a} className={rowCls} style={{ display: 'contents' }} onMouseEnter={enter} onMouseLeave={leave}>
                <span className="row-label" title={a}>
                  {a === tick.selected_action && <span className="pick-mark" aria-label="picked" />}
                  {prettyId(a)}
                </span>
                <span className="bar-track" style={{ background: 'var(--panel-3)' }}>
                  {hasNeg && (
                    <span
                      style={{
                        position: 'absolute',
                        left: '50%',
                        top: 0,
                        bottom: 0,
                        width: 1,
                        background: 'var(--faint)',
                      }}
                    />
                  )}
                  <span
                    style={{
                      position: 'absolute',
                      top: 0,
                      bottom: 0,
                      left: `${ev >= 0 ? zero : zero - width}%`,
                      width: `${width}%`,
                      background: ev >= 0 ? 'var(--n1)' : 'var(--neg)',
                      opacity: 0.85,
                    }}
                  />
                </span>
                {columns.map((c) => {
                  const v = nums[c] ?? 0
                  const text = c === 'survival' ? pct(v) : c === 'samples' ? String(v) : fmt(v, c === 'value' ? 2 : 1)
                  return (
                    <span key={c} className={`num ${v === 0 && c !== 'survival' ? 'zero' : ''}`}>
                      {text}
                    </span>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>
      {chain && (chain.steps ?? []).length > 0 && (
        <div className="chain" aria-label={`The simulator's rollout of ${chain.action_id}`}>
          <span className="chain-step">
            Rollout of <strong>{prettyId(chain.action_id)}</strong>
            <div className="muted">ordinary enemy branch</div>
          </span>
          {(chain.steps ?? []).map((s, i) => (
            <span key={i} style={{ display: 'contents' }}>
              <span className="chain-arrow" aria-hidden>
                →
              </span>
              <span className="chain-step">
                {prettyId(s.primitive)}
                <div className="muted">
                  health {fmt(s.health, 0)}
                  {s.damage_taken > 0 ? ` · −${fmt(s.damage_taken, 0)}` : ''}
                  {s.damage_dealt > 0 ? ` · deals ${fmt(s.damage_dealt, 0)}` : ''}
                </div>
              </span>
            </span>
          ))}
          {formula && (
            <span className="chain-step">
              branches {(chain.branch_values ?? []).map((v) => fmt(v, 2)).join(' / ')}
              <div className="muted">mean {fmt(chain.expected_value ?? 0, 2)}</div>
            </span>
          )}
        </div>
      )}
    </>
  )
}
