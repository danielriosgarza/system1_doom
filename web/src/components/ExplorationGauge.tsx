import {
  BASE_TEMPERATURE,
  PRESSURE_FLOOR,
  type PressureReading,
  SAMPLE_MARGIN,
  SAMPLE_PRESSURE,
  fmt,
} from '../data/derive'
import { useApp } from '../store'
import { Tip } from './Panel'

const TERM_COLOURS = ['var(--n1)', 'var(--n2)', 'var(--n3)', 'var(--accent)']

/**
 * The exploration pressure a tick's arbiter used: four quarter-terms, three dampers, a clamp, and
 * where the number goes. `next` is the pressure computed after this tick's outcome.
 */
export function ExplorationGauge({
  reading,
  next,
  margin,
  rule,
}: {
  reading: PressureReading
  next: PressureReading
  margin: number
  rule: string
}) {
  const depth = useApp((s) => s.depth)
  const sampled = margin < SAMPLE_MARGIN && reading.pressure >= SAMPLE_PRESSURE
  // The controller's own pressure, after the dampers; d1-ultra, when it answered, then pulls it halfway to its level.
  const own = reading.d1 === null ? reading.pressure : Math.min(1, Math.max(0, reading.product))
  const pulled = reading.d1 !== null && Math.abs(reading.pressure - own) > 1e-4
  return (
    <div className="gauge">
      <div className="gauge-figure">
        <span className="gauge-number">{fmt(reading.pressure, 2)}</span>
        <span className="gauge-caption">
          {reading.initial
            ? 'the starting value: no outcome has happened yet'
            : "pressure this tick's arbiter used, from the end of the tick before"}
        </span>
      </div>
      <div
        className={`gauge-bar ${pulled ? 'with-d1' : ''}`}
        role="img"
        aria-label={`Pressure ${fmt(reading.pressure, 2)} on a scale from 0 to 1`}
      >
        {reading.initial ? (
          <span className="gauge-seg" style={{ width: `${reading.pressure * 100}%`, background: 'var(--n2)' }} />
        ) : (
          reading.terms.map((t, i) => (
            <Tip key={t.key} body={`${t.label} ${fmt(t.value, 3)} of at most 0.25: ${t.words}`} className="gauge-tip">
              <span
                className="gauge-seg"
                style={{ width: `${t.value * 100}%`, background: TERM_COLOURS[i] }}
                aria-label={`${t.label} ${fmt(t.value, 3)}`}
              />
            </Tip>
          ))
        )}
        {[0.25, 0.5, 0.75].map((q) => (
          <span key={q} className="gauge-quarter" style={{ left: `${q * 100}%` }} aria-hidden />
        ))}
        {!reading.initial && reading.sum > own && (
          <span
            className="gauge-cut"
            style={{
              left: `${own * 100}%`,
              width: `${(Math.min(1, reading.sum) - own) * 100}%`,
            }}
            title="cut by the dampers"
          />
        )}
        {pulled && reading.d1 !== null && (
          <Tip
            body={`d1-ultra's own level ${fmt(reading.d1, 3)} gets half the say: ½ × ${fmt(reading.product, 3)} + ½ × ${fmt(reading.d1, 3)}, clamped, is ${fmt(reading.pressure, 3)}`}
            className="gauge-d1-tip"
          >
            <span
              className="gauge-d1 dotted"
              data-testid="gauge-d1"
              style={{
                ['--c' as string]: 'var(--n1)',
                left: `${Math.min(own, reading.pressure) * 100}%`,
                width: `${Math.abs(reading.pressure - own) * 100}%`,
              }}
              aria-label={`pulled by d1-ultra from ${fmt(own, 2)} to ${fmt(reading.pressure, 2)}`}
            />
          </Tip>
        )}
        <span
          className="gauge-result"
          style={{ left: `${reading.pressure * 100}%` }}
          title={reading.d1 === null ? 'after dampers and clamp' : 'after dampers, d1-ultra and clamp'}
        />
      </div>
      {!reading.initial && (
        <div className="gauge-legend">
          {reading.terms.map((t, i) => (
            <span key={t.key}>
              <span className="key solid" style={{ ['--c' as string]: TERM_COLOURS[i] }} />
              {t.label} {fmt(t.value, 2)}
            </span>
          ))}
          {reading.d1 !== null && (
            <span>
              <span className="key dotted" style={{ ['--c' as string]: 'var(--n1)' }} />
              d1-ultra {fmt(reading.d1, 2)}, half the say
            </span>
          )}
        </div>
      )}
      {!reading.initial && (
        <div className="gauge-dampers" aria-label="Dampers">
          {reading.dampers.map((d) => (
            <Tip key={d.key} body={`×${fmt(d.factor, 2)} when ${d.words}`}>
              <span className={`damper ${d.applied ? 'on' : ''}`}>
                ×{fmt(d.value, 2)} {d.label}
              </span>
            </Tip>
          ))}
          {reading.d1 !== null && (
            <Tip
              body={`d1-ultra was asked how much to explore; its answer, ${fmt(reading.d1, 3)}, is averaged with the controller's own ${fmt(reading.product, 3)}`}
            >
              <span className="damper on d1">½ with d1-ultra {fmt(reading.d1, 2)}</span>
            </Tip>
          )}
          <span className="damper clamp">clamp [{PRESSURE_FLOOR}, 1]</span>
        </div>
      )}
      <ul className="gauge-uses" aria-label="Where the pressure goes">
        <li>
          <strong>Temperature</strong> {fmt(BASE_TEMPERATURE, 2)} + {fmt(reading.pressure, 2)} ={' '}
          {fmt(reading.temperature, 2)} for the arbiter&apos;s softmax.
        </li>
        <li>
          <strong>Sampling</strong> only when the top two are within {SAMPLE_MARGIN} and pressure is at least{' '}
          {SAMPLE_PRESSURE}: margin {fmt(margin, 3)}, pressure {fmt(reading.pressure, 2)}, so{' '}
          {rule === 'committed' || rule === 'explored' || rule === 'critical_cached'
            ? `the ${rule} rule decided instead`
            : sampled
              ? 'the arbiter sampled'
              : 'the top score was taken'}
          .
        </li>
        <li>
          <strong>After this tick</strong> {fmt(next.pressure, 2)}: steering used it at once, and the next tick&apos;s
          arbiter will.
        </li>
      </ul>
      {depth === 'formula' && !reading.initial && (
        <div className="formula gauge-formula mono">
          ({reading.terms.map((t) => fmt(t.value, 3)).join(' + ')}) ×{' '}
          {reading.dampers.map((d) => fmt(d.value, 2)).join(' × ')} = {fmt(reading.product, 4)}
          {reading.d1 !== null && <> · half with d1 {fmt(reading.d1, 3)}</>} → clamp → {fmt(reading.pressure, 4)}; the
          trace recorded {fmt(reading.recorded, 4)}
        </div>
      )}
    </div>
  )
}
