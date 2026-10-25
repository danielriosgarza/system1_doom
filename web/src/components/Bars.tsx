import { type Bar, pct, words } from '../data/readings'

/** A probability as a bar, with an optional mark where it becomes a yes (a sense speaks at 0.5). */
export function Meter({
  value,
  mark,
  label,
  className,
}: {
  value: number | null
  mark?: number
  label: string
  className?: string
}) {
  const width = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100
  return (
    <span
      className={`meter ${className ?? ''}`}
      role="img"
      aria-label={`${label}: ${value === null ? 'no answer' : pct(value)}`}
    >
      <span className="meter-fill" style={{ width: `${width}%` }} />
      {mark !== undefined && <span className="meter-mark" style={{ left: `${mark * 100}%` }} aria-hidden />}
    </span>
  )
}

/**
 * A distribution as rows of bars, highest first; the instance's own answer is marked. Options under `floor` are
 * folded into one line, so a thirteen-action menu stays readable; `limit` caps the rows shown.
 */
export function BarList({
  bars,
  label,
  limit,
  floor = 0,
  mark,
}: {
  bars: Bar[]
  label: string
  limit?: number
  floor?: number
  /** The option the trace says was executed or picked, marked with its word. */
  mark?: { option: string | null; word: string }
}) {
  const shown = bars.filter((b, i) => (limit === undefined || i < limit) && (b.p >= floor || b.top))
  const rest = bars.filter((b) => !shown.includes(b))
  const restP = rest.reduce((sum, b) => sum + b.p, 0)
  return (
    <ul className="bar-list" aria-label={label}>
      {shown.map((b) => (
        <li key={b.label} className={`bar-row ${b.top ? 'top' : ''}`} data-option={b.label}>
          <span className="bar-label">{words(b.label)}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${Math.max(0, Math.min(1, b.p)) * 100}%` }} />
          </span>
          <span className="bar-value">{pct(b.p, b.p < 0.1 ? 1 : 0)}</span>
          <span className="bar-note">
            {b.top ? 'its answer' : ''}
            {mark && mark.option === b.label ? `${b.top ? ' · ' : ''}${mark.word}` : ''}
          </span>
        </li>
      ))}
      {rest.length > 0 && (
        <li className="bar-row rest">
          <span className="bar-label">
            {rest.length} other{rest.length === 1 ? '' : 's'}
          </span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${Math.min(1, restP) * 100}%` }} />
          </span>
          <span className="bar-value">{pct(restP, restP < 0.1 ? 1 : 0)}</span>
          <span className="bar-note" />
        </li>
      )}
    </ul>
  )
}
