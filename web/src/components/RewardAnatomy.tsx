import { GAMMA, MODULES, N_STEP, fmt, nStepReturns, signed } from '../data/derive'
import type { TickTrace } from '../schema/bundle'
import { useApp } from '../store'

/** A signed bar around a centre line, scaled to `scale`. */
function SignedBar({ value, scale, color }: { value: number; scale: number; color: string }) {
  const share = Math.min(1, Math.abs(value) / (scale || 1)) * 50
  return (
    <span className="ra-track">
      <span className="ra-zero" />
      <span
        className="ra-fill"
        style={{
          left: value >= 0 ? '50%' : `${50 - share}%`,
          width: `${share}%`,
          background: color,
        }}
      />
    </span>
  )
}

/** This tick's five module rewards and the 8-step return each one becomes. */
export function RewardAnatomy({ ticks, index, learned }: { ticks: TickTrace[]; index: number; learned: boolean }) {
  const depth = useApp((s) => s.depth)
  const tick = ticks[index]
  if (!tick) return null
  const rewards = tick.outcome?.module_rewards ?? {}
  const returns = nStepReturns(ticks, index)
  const horizon = returns.survival.terms.length
  return (
    <div className="anatomy">
      <div className="ra-row ra-head">
        <span />
        <span>reward this tick</span>
        <span>return over the next {horizon === N_STEP ? N_STEP : `${horizon} (the episode ends)`} decisions</span>
      </div>
      {MODULES.map((m) => {
        const r = rewards[m] ?? 0
        const ret = returns[m]
        // Each module on its own scale: the rewards are in different units (health, kills, cells, score).
        const scale = Math.max(Math.abs(r), Math.abs(ret.total), 1e-9)
        return (
          <div key={m} className="ra-row" data-module={m}>
            <span className="ra-module">
              <span className="dot" style={{ background: `var(--${m})` }} /> {m}
            </span>
            <span className="ra-cell">
              <SignedBar value={r} scale={scale} color={`var(--${m})`} />
              <span className="ra-value">{signed(r, 2)}</span>
            </span>
            <span className="ra-cell">
              <SignedBar value={ret.total} scale={scale} color={`var(--${m})`} />
              <span className="ra-value">{signed(ret.total, 2)}</span>
            </span>
            {depth === 'formula' && (
              <span className="ra-terms mono">
                {ret.terms
                  .map((t) => {
                    const r = t.reward < 0 ? `(−${fmt(-t.reward, 2)})` : fmt(t.reward, 2)
                    return t.k === 0 ? r : `${fmt(GAMMA, 1)}^${t.k}·${r}`
                  })
                  .join(' + ')}{' '}
                = {fmt(ret.total, 3)}
              </span>
            )}
          </div>
        )
      })}
      <p className="dc-note">
        {learned
          ? 'This recording only read the networks. In training, every decision’s five returns like these are standardised with running statistics kept in the checkpoint and become the targets the module networks learn to predict; the app shows the raw return.'
          : 'Recorded, not learned from: no networks were loaded. In training these five returns would be standardised and become the targets of the five module networks.'}
      </p>
    </div>
  )
}
