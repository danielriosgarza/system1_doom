import { MODULES, fmt, gateBlend, pct } from '../data/derive'
import type { TickTrace } from '../schema/bundle'
import { useApp } from '../store'

function Row({ label, weights, note }: { label: string; weights: Record<string, number>; note?: string }) {
  return (
    <div className="gv-row">
      <div className="gv-label">
        {label}
        {note && <span className="muted"> {note}</span>}
      </div>
      {MODULES.map((m) => (
        <div key={m} className="gv-cell" data-module={m}>
          <span className="gv-track">
            <span className="gv-fill" style={{ width: `${(weights[m] ?? 0) * 100}%`, background: `var(--${m})` }} />
          </span>
          <span className="gv-value">{pct(weights[m] ?? 0)}</span>
        </div>
      ))}
    </div>
  )
}

/** The hand-written module weights, the gate's proposal, and the blend the arbiter used, with g between. */
export function GateView({ tick, contextN }: { tick: TickTrace; contextN: number }) {
  const depth = useApp((s) => s.depth)
  const blend = gateBlend(tick)
  if (!blend) return null
  return (
    <div className="gateview">
      <div className="gv-row gv-head">
        <div className="gv-label" />
        {MODULES.map((m) => (
          <div key={m} className="gv-cell gv-module">
            <span className="dot" style={{ background: `var(--${m})` }} /> {m}
            {blend.trainers.includes(m) && (
              <span
                className="gv-trains"
                title="its own top pick was the action taken, so this tick would train the gate"
              >
                trains the gate
              </span>
            )}
          </div>
        ))}
      </div>
      <Row label="Hand-written table" weights={blend.table} note="(scaled by confidence)" />
      <div className="gv-mix">× (1 − g) = {fmt(1 - blend.g, 3)}</div>
      <Row label="Gate network" weights={blend.gate} note="(softmax at 0.5)" />
      <div className="gv-mix">× g = {fmt(blend.g, 3)}, then normalised</div>
      <Row label="Used by the arbiter" weights={blend.used} />
      {depth === 'formula' && (
        <p className="mono dc-note">
          {MODULES.map(
            (m) =>
              `${m}: (${fmt(1 - blend.g, 3)}·${fmt(blend.table[m] ?? 0, 3)} + ${fmt(blend.g, 3)}·${fmt(blend.gate[m] ?? 0, 3)}) ÷ Σ = ${fmt(blend.recomputed[m] ?? 0, 3)}`,
          ).join('; ')}
        </p>
      )}
      <p className="dc-note">
        This situation came up {contextN.toLocaleString('en')} times in training, so g = {contextN} ÷ ({contextN} + 25)
        = {fmt(blend.g, 3)}: the gate&apos;s proposal carries {pct(blend.g)} of the weight.{' '}
        {blend.trainers.length > 0
          ? `${blend.trainers.length === MODULES.length ? 'All five modules' : blend.trainers.join(', ')} put the chosen action first, so in training ${blend.trainers.length === 1 ? 'only its gate output' : 'only their gate outputs'} would learn from this decision.`
          : 'No module put the chosen action first, so in training this decision would teach the gate nothing.'}
      </p>
    </div>
  )
}
