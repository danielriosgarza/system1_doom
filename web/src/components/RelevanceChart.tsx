import { type KeyboardEvent, type PointerEvent, useState } from 'react'
import { LEARNING } from '../content/learning'
import type { SeriesPoint } from '../data/learning'
import { SENSES, pct } from '../data/readings'
import { useWidth } from './useWidth'

const HEIGHT = 230
const M = { left: 44, right: 16, top: 14, bottom: 34 }
const TICKS = [0, 0.25, 0.5, 0.75, 1]

/**
 * Each sense's paid-off share of followed messages as the ledger grew: one line per sense in its own colour,
 * a legend above (five series), a crosshair and tooltip on hover or arrow keys, and the numbers as a table.
 */
export function RelevanceChart({ series }: { series: Record<string, SeriesPoint[]> }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const points = series[SENSES[0]] ?? []
  const xs = points.map((p) => p.episodes)
  const lo = Math.min(...xs)
  const hi = Math.max(...xs)
  const span = hi - lo || 1
  const plotW = Math.max(10, width - M.left - M.right)
  const plotH = HEIGHT - M.top - M.bottom
  const x = (e: number) => M.left + (hi === lo ? plotW / 2 : ((e - lo) / span) * plotW)
  const y = (v: number) => M.top + (1 - v) * plotH
  const nearest = (px: number) => {
    let best = 0
    points.forEach((p, i) => {
      if (Math.abs(x(p.episodes) - px) < Math.abs(x(points[best]?.episodes ?? 0) - px)) best = i
    })
    return best
  }
  const onPointer = (e: PointerEvent<SVGRectElement>) => {
    const rect = e.currentTarget.ownerSVGElement?.getBoundingClientRect()
    if (rect) setHover(nearest(e.clientX - rect.left))
  }
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    e.stopPropagation()
    const at = hover ?? (e.key === 'ArrowRight' ? -1 : points.length)
    setHover(Math.max(0, Math.min(points.length - 1, at + (e.key === 'ArrowRight' ? 1 : -1))))
  }
  const xTicks = [...new Set(xs)]
  const hovered = hover === null ? null : points[hover]
  return (
    <figure className="chart" data-testid="relevance-chart">
      <figcaption className="chart-title">{LEARNING.chart.title}</figcaption>
      <ul className="legend" aria-label="Senses">
        {SENSES.map((s) => (
          <li key={s}>
            <span className={`legend-mark sense-${s}`} aria-hidden />
            {s}
          </li>
        ))}
      </ul>
      <div className="chart-box" ref={ref}>
        {width > 0 && (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={`${LEARNING.chart.title}, at ${xTicks.length} points; the numbers are in the table below.`}
            tabIndex={0}
            onKeyDown={onKey}
            onBlur={() => setHover(null)}
          >
            {TICKS.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={M.left + plotW} y1={y(t)} y2={y(t)} className="grid" />
                <text x={M.left - 8} y={y(t)} className="axis-label" textAnchor="end" dominantBaseline="middle">
                  {pct(t)}
                </text>
              </g>
            ))}
            {xTicks.map((e) => (
              <text key={e} x={x(e)} y={HEIGHT - M.bottom + 16} className="axis-label" textAnchor="middle">
                {e}
              </text>
            ))}
            <text x={M.left + plotW / 2} y={HEIGHT - 4} className="axis-title" textAnchor="middle">
              {LEARNING.chart.x}
            </text>
            {hovered && (
              <line
                x1={x(hovered.episodes)}
                x2={x(hovered.episodes)}
                y1={M.top}
                y2={M.top + plotH}
                className="crosshair"
              />
            )}
            {SENSES.map((s) => {
              const pts = series[s] ?? []
              // A sense never followed yet has no share: the line breaks there rather than dropping to zero.
              const d = pts
                .map((p, i) => {
                  if (p.value === null) return ''
                  const prev = pts[i - 1]
                  return `${i === 0 || !prev || prev.value === null ? 'M' : 'L'}${x(p.episodes)},${y(p.value)}`
                })
                .join(' ')
              return (
                <g key={s} className={`series sense-${s}`} data-sense={s}>
                  <path d={d} className="series-line" />
                  {pts.map((p) =>
                    p.value === null ? null : (
                      <circle key={p.episodes} cx={x(p.episodes)} cy={y(p.value)} r={4} className="series-dot" />
                    ),
                  )}
                </g>
              )
            })}
            <rect
              x={M.left - 12}
              y={M.top}
              width={plotW + 24}
              height={plotH}
              fill="transparent"
              onPointerMove={onPointer}
              onPointerDown={onPointer}
              onPointerLeave={() => setHover(null)}
            />
          </svg>
        )}
        {hovered && hover !== null && (
          <div
            className="chart-tip"
            role="status"
            style={{ left: Math.min(Math.max(x(hovered.episodes), 110), Math.max(110, width - 110)) }}
          >
            <strong>
              {hovered.episodes} episode{hovered.episodes === 1 ? '' : 's'}
            </strong>{' '}
            <span className="muted">{hovered.label}</span>
            <ul>
              {SENSES.map((s) => {
                const p = series[s]?.[hover]
                return (
                  <li key={s}>
                    <span className={`legend-mark sense-${s}`} aria-hidden /> {s}: {pct(p?.value)}{' '}
                    <span className="muted">
                      ({p?.paid ?? 0} of {p?.followed ?? 0})
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </figure>
  )
}
