import { type PointerEvent, type ReactNode, useId, useMemo, useState } from 'react'
import { EXPLAINERS, type PanelId } from '../content/explainers'
import { WATCH } from '../content/watch'
import type { EpisodeBundle } from '../data/loader'
import { type Pace, gameSeconds } from '../data/playback'
import { type MarkKind, fmt, tickMarks, words } from '../data/readings'
import { setPace, setTickIndex, step, togglePlay, useApp } from '../store'
import { ExplainerBody } from './Panel'
import { useWidth } from './useWidth'

const HEIGHT = 64
const LANE_TOP = 7
const SLOT_TOP = 16
const SLOT_BOTTOM = 42
const LANE_BOTTOM = 54
const PAD = 8

type Lane = 'top' | 'bottom'

/** Which lane each mark sits in: what the game did above, what the instances and System 2 did below. */
const LANE: Record<MarkKind, Lane> = {
  damage: 'top',
  kill: 'top',
  death: 'top',
  miss: 'bottom',
  drawn: 'bottom',
  change: 'bottom',
  cycle: 'bottom',
}

const MARK_LEGEND: Array<{ kind: MarkKind; label: string }> = [
  { kind: 'damage', label: 'damage' },
  { kind: 'kill', label: 'kill' },
  { kind: 'death', label: 'death' },
  { kind: 'miss', label: 'missed call' },
  { kind: 'drawn', label: 'action drawn under explore' },
  { kind: 'change', label: 'new configuration version' },
  { kind: 'cycle', label: 'System 2 cycle' },
]

/** One mark of the timeline. */
export function Mark({ kind, x, y }: { kind: MarkKind; x: number; y: number }) {
  switch (kind) {
    case 'damage':
      return <path d={`M${x - 4},${y - 3} h8 l-4,6 z`} fill="var(--neg)" />
    case 'kill':
      return <path d={`M${x},${y - 5} l4,5 l-4,5 l-4,-5 z`} fill="var(--combat)" />
    case 'death':
      return <path d={`M${x - 4},${y - 4} l8,8 M${x + 4},${y - 4} l-8,8`} stroke="var(--neg)" strokeWidth={2} />
    case 'miss':
      return <circle cx={x} cy={y} r={3.5} fill="none" stroke="var(--n2)" strokeWidth={1.5} />
    case 'drawn':
      return <rect x={x - 3} y={y - 3} width={6} height={6} fill="none" stroke="var(--navigation)" strokeWidth={1.5} />
    case 'change':
      return <rect x={x - 3.5} y={y - 3.5} width={7} height={7} fill="var(--accent)" />
    case 'cycle':
      return <path d={`M${x - 4},${y} h8 M${x},${y - 4} v8`} stroke="var(--goal)" strokeWidth={2.2} />
  }
}

/** The timeline at the bottom of every screen but Watch: play, step, seek, and what happened where. */
export function Scrubber({ bundle }: { bundle: EpisodeBundle }) {
  const { ticks } = bundle
  const marks = useMemo(() => tickMarks(bundle), [bundle])
  const health = useMemo(() => ticks.map((t) => t.state?.health ?? 0), [ticks])
  return (
    <Timeline
      health={health}
      marks={marks}
      lane={LANE}
      legend={MARK_LEGEND}
      explainer="scrubber"
      tick={(i) => ticks[i]?.tick ?? i}
      seconds={(i) => gameSeconds(ticks[i]?.tick ?? i)}
      words={(i) => words(ticks[i]?.executed_action) || 'missed'}
    />
  )
}

/** A colour band under each decision's slot, with its legend: the rule tree's top-level rule. */
export interface Bands {
  /** Each decision's band key; null leaves it without one. */
  keys: Array<string | null>
  legend: Array<{ key: string; label: string; title?: string }>
}

/**
 * The timeline itself, for either solution: one slot per decision, the health line, the marks of what happened,
 * optional bands, the transport, the counter and the pace.
 */
export function Timeline<K extends MarkKind>({
  health,
  marks,
  lane,
  legend,
  explainer,
  tick,
  seconds,
  words: wordsAt,
  bands,
}: {
  health: number[]
  marks: K[][]
  lane: Record<K, Lane>
  legend: Array<{ kind: K; label: string }>
  explainer: PanelId
  /** The decision's own number, for the tests and the URL. */
  tick: (i: number) => number
  seconds: (i: number) => number
  /** The action of decision i in words, for the hover line. */
  words: (i: number) => string
  bands?: Bands
}) {
  const tickIndex = useApp((s) => s.tickIndex)
  const playing = useApp((s) => s.playing)
  const pace = useApp((s) => s.pace)
  const following = useApp((s) => s.following)
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const bodyId = useId()
  const n = health.length
  const slot = (width - PAD * 2) / Math.max(1, n)
  const xOf = (i: number) => PAD + slot * (i + 0.5)
  const indexAt = (clientX: number, rect: DOMRect) =>
    Math.max(0, Math.min(n - 1, Math.floor((clientX - rect.left - PAD) / Math.max(1, slot))))
  const healthY = (h: number) => SLOT_BOTTOM - (Math.max(0, Math.min(100, h)) / 100) * (SLOT_BOTTOM - SLOT_TOP)
  const healthPath = health.map((h, i) => `${i === 0 ? 'M' : 'L'}${xOf(i)},${healthY(h)}`).join(' ')

  const onPointer = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const i = indexAt(e.clientX, rect)
    setHover(i)
    if (e.type === 'pointerdown') {
      e.currentTarget.setPointerCapture(e.pointerId)
      setTickIndex(i)
    } else if (e.buttons === 1) {
      setTickIndex(i)
    }
  }

  const hoverMarks = hover === null ? [] : (marks[hover] ?? [])
  const bandLabel = (i: number) => bands?.legend.find((b) => b.key === bands.keys[i])?.label
  const tip: ReactNode =
    hover === null ? null : (
      <>
        <strong>Decision {hover + 1}</strong>: {wordsAt(hover)}, health {fmt(health[hover] ?? 0, 0)}
        {bands && bandLabel(hover) && <> · {bandLabel(hover)}</>}
        {hoverMarks.length > 0 && <> · {hoverMarks.map((m) => legend.find((l) => l.kind === m)?.label).join(' · ')}</>}
      </>
    )
  return (
    <footer className="scrubber" id="panel-scrubber">
      <div className="scrubber-inner">
        <div className="transport" role="group" aria-label="Playback">
          <button
            type="button"
            onClick={() => setTickIndex(0)}
            aria-label="First decision"
            title="First decision (Home)"
          >
            ⏮
          </button>
          <button type="button" onClick={() => step(-1)} aria-label="Previous decision" title="Previous decision (←)">
            ◀
          </button>
          <button
            type="button"
            onClick={togglePlay}
            aria-label={playing ? 'Pause' : 'Play'}
            title="Play or pause (space)"
          >
            {playing ? '⏸' : '▶'}
          </button>
          <button type="button" onClick={() => step(1)} aria-label="Next decision" title="Next decision (→)">
            ▶︎
          </button>
          <button
            type="button"
            onClick={() => setTickIndex(n - 1)}
            aria-label="Last decision"
            title="Last decision (End)"
          >
            ⏭
          </button>
        </div>
        <div className="track" ref={ref}>
          {tip && (
            <div className="track-tip" style={{ left: Math.min(Math.max(xOf(hover ?? 0), 120), width - 120) }}>
              {tip}
            </div>
          )}
          <svg
            width={width}
            height={HEIGHT}
            role="slider"
            tabIndex={0}
            aria-label="Decision"
            aria-valuemin={1}
            aria-valuemax={n}
            aria-valuenow={tickIndex + 1}
            aria-valuetext={`Decision ${tickIndex + 1}: ${wordsAt(tickIndex)}`}
            onPointerDown={onPointer}
            onPointerMove={onPointer}
            onPointerLeave={() => setHover(null)}
          >
            {health.map((_, i) => (
              <rect
                key={i}
                x={PAD + slot * i + 0.5}
                y={SLOT_TOP}
                width={Math.max(1, slot - 1)}
                height={SLOT_BOTTOM - SLOT_TOP}
                rx={2}
                fill={i === tickIndex ? 'var(--accent)' : i === hover ? 'var(--panel-3)' : 'var(--panel-2)'}
                opacity={i === tickIndex ? 0.35 : 1}
              />
            ))}
            {bands?.keys.map((key, i) =>
              key === null ? null : (
                <rect
                  key={`band-${i}`}
                  className={`band band-${key}`}
                  x={PAD + slot * i + 0.5}
                  y={SLOT_BOTTOM + 1}
                  width={Math.max(1, slot - 1)}
                  height={3}
                />
              ),
            )}
            <path d={healthPath} fill="none" stroke="var(--pos)" strokeWidth={1.5} opacity={0.9} />
            {marks.map((list, i) =>
              list.map((kind, j) => {
                const where = lane[kind]
                const same = list.filter((x) => lane[x] === where)
                const k = same.indexOf(kind)
                const offset = (k - (same.length - 1) / 2) * Math.min(9, slot)
                return (
                  <Mark
                    key={`${i}-${j}`}
                    kind={kind}
                    x={xOf(i) + offset}
                    y={where === 'top' ? LANE_TOP : LANE_BOTTOM + (bands ? 2 : 0)}
                  />
                )
              }),
            )}
            <rect
              x={PAD + slot * tickIndex}
              y={SLOT_TOP - 2}
              width={Math.max(2, slot)}
              height={SLOT_BOTTOM - SLOT_TOP + 4}
              rx={3}
              fill="none"
              stroke="var(--accent)"
              strokeWidth={2}
            />
          </svg>
        </div>
        {n > 0 && (
          // While playing, or following a live episode, the count changes several times a second: too often to announce.
          <span
            className="tick-counter"
            data-testid="tick-counter"
            data-tick={tick(tickIndex)}
            aria-live={playing || following ? 'off' : 'polite'}
          >
            Decision {tickIndex + 1}
            <span className="tick-last"> / {n}</span>
            <span className="tick-seconds"> · {fmt(seconds(tickIndex), 1)} s</span>
          </span>
        )}
        <div className="track-legend" aria-label="Mark legend">
          <span>
            <svg width={14} height={10} aria-hidden>
              <path d="M0,8 L14,2" stroke="var(--pos)" strokeWidth={1.5} />
            </svg>{' '}
            health
          </span>
          {bands?.legend.map((b) => (
            <span key={b.key} title={b.title}>
              <svg width={14} height={10} aria-hidden>
                <rect className={`band band-${b.key}`} x={0} y={3} width={14} height={4} />
              </svg>{' '}
              {b.label}
            </span>
          ))}
          {legend.map((m) => (
            <span key={m.kind}>
              <svg width={12} height={12} aria-hidden style={{ verticalAlign: -1 }}>
                <Mark kind={m.kind} x={6} y={6} />
              </svg>{' '}
              {m.label}
            </span>
          ))}
          <button
            type="button"
            className="explain-toggle"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen(!open)}
            title={open ? 'Hide the explanation' : 'Explain the timeline'}
          >
            {open ? 'Hide' : '?'}
          </button>
        </div>
        <span className="segmented scrub-pace" role="group" aria-label={WATCH.paceGroup}>
          {(['real', 'slow'] as Pace[]).map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={pace === p}
              title={WATCH.paceTitle[p]}
              onClick={() => setPace(p)}
            >
              {WATCH.pace[p]}
            </button>
          ))}
        </span>
        {open && (
          <div className="scrub-explainer">
            <p className="sentence">{EXPLAINERS[explainer].sentence}</p>
            <ExplainerBody id={explainer} bodyId={bodyId} />
          </div>
        )}
      </div>
    </footer>
  )
}
