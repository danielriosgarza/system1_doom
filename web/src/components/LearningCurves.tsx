import { type PointerEvent, useState } from 'react'
import { FLOOR_SCHEDULE, MODULES, ROLLING_WINDOW, fmt, pct, rolling, stillPlaying, survived } from '../data/derive'
import type { EpisodeMeta, MetricsRow } from '../schema/bundle'

const W = 300
const H = 128
const M = { left: 36, right: 10, top: 10, bottom: 20 }
const PLOT_W = W - M.left - M.right
const PLOT_H = H - M.top - M.bottom

interface Line {
  label: string
  values: number[]
  color: string
  dashed?: boolean
}

interface Series {
  key: string
  title: string
  /** Faint per-episode points under the lines. */
  points?: number[]
  lines: Line[]
  max: number
  format: (v: number) => string
  /** This recording's own value, drawn dashed across the chart. */
  recording?: number
  note?: string
}

/** A round upper bound for an axis. */
function niceMax(value: number): number {
  if (value <= 0) return 1
  const step = 10 ** Math.floor(Math.log10(value))
  return Math.ceil(value / step) * step
}

function buildSeries(metrics: MetricsRow[], meta: EpisodeMeta): Series[] {
  const reward = metrics.map((r) => r.reward)
  const kills = metrics.map((r) => r.kills)
  const health = metrics.map((r) => r.health)
  const ticks = metrics.map((r) => r.ticks)
  const mean = (values: number[], color = 'var(--accent)'): Line => ({
    label: `rolling ${ROLLING_WINDOW}`,
    values: rolling(values),
    color,
  })
  const hasLosses = metrics.some((r) => r.losses && Object.keys(r.losses).length > 0)
  const losses: Line[] = [...MODULES, 'gate'].map((m) => ({
    label: m,
    // An episode trained before the buffer held a batch has no losses; carry the last one forward.
    values: rolling(metrics.reduce<number[]>((out, r) => [...out, r.losses?.[m] ?? out[out.length - 1] ?? 0], [])),
    color: m === 'gate' ? 'var(--n1)' : `var(--${m})`,
    dashed: m === 'gate',
  }))
  const series: Series[] = [
    {
      key: 'reward',
      title: 'Reward',
      points: reward,
      lines: [mean(reward)],
      max: niceMax(Math.max(...reward, meta.result.reward)),
      format: (v) => fmt(v, 0),
      recording: stillPlaying(meta) ? undefined : meta.result.reward,
    },
    {
      key: 'ticks',
      title: 'Decisions per episode',
      points: ticks,
      lines: [mean(ticks)],
      max: niceMax(Math.max(...ticks, meta.result.ticks)),
      format: (v) => fmt(v, 0),
      recording: stillPlaying(meta) ? undefined : meta.result.ticks,
    },
    {
      key: 'kills',
      title: 'Kills',
      points: kills,
      lines: [mean(kills)],
      max: niceMax(Math.max(...kills)),
      format: (v) => fmt(v, 1),
    },
    {
      key: 'health',
      title: 'Health left at the end',
      points: health,
      lines: [mean(health)],
      max: niceMax(Math.max(...health)),
      format: (v) => fmt(v, 0),
    },
    {
      key: 'rates',
      title: `Cleared and survived, rolling ${ROLLING_WINDOW}`,
      lines: [
        { label: 'cleared', values: rolling(metrics.map((r) => (r.cleared ? 1 : 0))), color: 'var(--pos)' },
        {
          label: 'survived',
          values: rolling(metrics.map((r) => (survived(r) ? 1 : 0))),
          color: 'var(--navigation)',
          dashed: true,
        },
      ],
      max: 1,
      format: (v) => pct(v),
    },
    {
      key: 'network_share',
      title: 'Network share',
      lines: [{ label: 'share', values: metrics.map((r) => r.network_share), color: 'var(--accent)' }],
      max: 1,
      format: (v) => pct(v),
      note: 'how much of play the networks steered',
    },
    {
      key: 'exploration_floor',
      title: 'Exploration floor',
      lines: [{ label: 'floor', values: metrics.map((r) => r.exploration_floor), color: 'var(--n1)' }],
      max: 1,
      format: (v) => fmt(v, 2),
      note: `${FLOOR_SCHEDULE.start} → ${FLOOR_SCHEDULE.end} over ${FLOOR_SCHEDULE.episodes} episodes`,
    },
  ]
  if (hasLosses) {
    series.push({
      key: 'losses',
      title: `Training loss, rolling ${ROLLING_WINDOW}`,
      lines: losses,
      max: niceMax(Math.max(...losses.flatMap((l) => l.values).filter(Number.isFinite))),
      format: (v) => fmt(v, 2),
    })
  }
  return series
}

function Multiple({
  series,
  meta,
  count,
  checkpoint,
  hover,
  onHover,
}: {
  series: Series
  meta: EpisodeMeta
  count: number
  checkpoint: number | null
  hover: number | null
  onHover: (i: number | null) => void
}) {
  const x = (i: number) => M.left + (count <= 1 ? 0 : (i / (count - 1)) * PLOT_W)
  const y = (v: number) => M.top + PLOT_H - (Math.max(0, Math.min(series.max, v)) / series.max) * PLOT_H
  const path = (values: number[]) => values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(v)}`).join(' ')
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    const i = Math.round(((px - M.left) / PLOT_W) * (count - 1))
    onHover(i < 0 || i >= count ? null : i)
  }
  return (
    <figure className="curve" data-series={series.key}>
      <figcaption>
        {series.title}
        {series.note && <span className="muted"> · {series.note}</span>}
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} onPointerMove={onMove} onPointerLeave={() => onHover(null)} role="img">
        <title>{`${series.title} over ${count} training episodes`}</title>
        <line x1={M.left} x2={W - M.right} y1={y(0)} y2={y(0)} className="curve-axis" />
        <line x1={M.left} x2={W - M.right} y1={y(series.max)} y2={y(series.max)} className="curve-grid" />
        <text x={M.left - 4} y={y(series.max) + 4} textAnchor="end" className="curve-tick">
          {series.format(series.max)}
        </text>
        <text x={M.left - 4} y={y(0) + 4} textAnchor="end" className="curve-tick">
          {series.format(0)}
        </text>
        <text x={M.left} y={H - 4} className="curve-tick">
          1
        </text>
        <text x={W - M.right} y={H - 4} textAnchor="end" className="curve-tick">
          {count}
        </text>
        {checkpoint !== null && checkpoint <= count && (
          <line x1={x(checkpoint - 1)} x2={x(checkpoint - 1)} y1={M.top} y2={y(0)} className="curve-checkpoint" />
        )}
        {series.points?.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r={1.5} className="curve-point" />
        ))}
        {series.lines.map((line) => (
          <path
            key={line.label}
            d={path(line.values)}
            className={`curve-line ${line.dashed ? 'dashed' : ''}`}
            style={{ stroke: line.color }}
          />
        ))}
        {series.recording !== undefined && (
          <g className="curve-recording">
            <line x1={M.left} x2={W - M.right} y1={y(series.recording)} y2={y(series.recording)} />
            <text x={M.left + 4} y={y(series.recording) - 4}>
              this recording{meta.brains.learned_networks ? '' : ', no networks'} {series.format(series.recording)}
            </text>
          </g>
        )}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={y(0)} className="curve-hover" />}
      </svg>
      {series.lines.length > 1 && (
        <p className="curve-legend">
          {series.lines.map((l) => (
            <span key={l.label}>
              <span className={`key-line ${l.dashed ? 'dashed' : ''}`} style={{ borderColor: l.color }} /> {l.label}
            </span>
          ))}
        </p>
      )}
    </figure>
  )
}

/** Small multiples of the training run: one chart per measure, x = training episode. */
export function LearningCurves({
  metrics,
  meta,
  trainedEpisodes,
}: {
  metrics: MetricsRow[]
  meta: EpisodeMeta
  trainedEpisodes: number | null
}) {
  const [hover, setHover] = useState<number | null>(null)
  const series = buildSeries(metrics, meta)
  const row = hover === null ? null : metrics[hover]
  const checkpoint = meta.checkpoint?.episodes ?? trainedEpisodes
  return (
    <div className="curves">
      <p className="curve-readout" aria-live="polite">
        {row ? (
          <>
            <strong>Episode {row.episode}</strong>: reward {fmt(row.reward, 0)} · {row.kills} kills · health{' '}
            {fmt(row.health, 0)} · {row.ticks} decisions · {row.cleared ? 'cleared' : row.died ? 'died' : 'ran out'} ·
            network share {pct(row.network_share)} · floor {fmt(row.exploration_floor, 2)} · replay{' '}
            {row.replay_size.toLocaleString('en')}
          </>
        ) : (
          <>
            {metrics.length} training episodes
            {checkpoint !== null && <>; the checkpoint was saved after episode {checkpoint} (the vertical line)</>}.
            Hover a chart for one episode.
          </>
        )}
      </p>
      <div className="curve-grid-wrap">
        {series.map((s) => (
          <Multiple
            key={s.key}
            series={s}
            meta={meta}
            count={metrics.length}
            checkpoint={checkpoint}
            hover={hover}
            onHover={setHover}
          />
        ))}
      </div>
    </div>
  )
}
