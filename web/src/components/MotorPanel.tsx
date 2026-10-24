import type { EpisodeMeta, TickTrace } from '../schema/bundle'
import { motorSteps, prettyId } from '../data/derive'

export function MotorPanel({ tick, meta }: { tick: TickTrace; meta: EpisodeMeta }) {
  const action = meta.actions[tick.selected_action]
  const plan = action?.primitives ?? []
  const steps = motorSteps(plan, tick.primitive_steps_executed)
  return (
    <>
      <div className="plan">
        <strong>{prettyId(tick.selected_action)}</strong>
        <span style={{ color: 'var(--muted)' }}>{action?.description}</span>
      </div>
      <div className="plan" aria-label="The plan">
        <span style={{ color: 'var(--muted)', fontSize: 12.5 }}>Plan:</span>
        {plan.map((p, i) => (
          <span key={i} className="prim">
            {prettyId(p)}
          </span>
        ))}
      </div>
      <ol className="steps" aria-label="What the motor pressed, step by step">
        {steps.map((s) => {
          const planned = new Set((s.planned ?? '').replace('_shoot', '+shoot').split('+'))
          return (
            <li key={s.index}>
              <span className="step-num">{s.index + 1}</span>
              <span>
                <span className="keys">
                  {s.pressed.map((k) => (
                    <span
                      key={k}
                      className={`keycap ${planned.has(k) ? '' : 'extra'}`}
                      title={planned.has(k) ? 'named by the plan' : 'added by a reflex'}
                    >
                      {prettyId(k)}
                    </span>
                  ))}
                </span>
                {s.words}
                {s.assisted && <span className="reflex">reflex</span>}
              </span>
            </li>
          )
        })}
      </ol>
    </>
  )
}
