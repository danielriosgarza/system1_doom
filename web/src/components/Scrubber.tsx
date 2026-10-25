import { type PointerEvent, useId, useMemo, useState } from 'react'
import { EXPLAINERS } from '../content/explainers'
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

/** Which lane each mark sits in: what the game did above, what the instances and System 2 did below. */
const LANE: Record<MarkKind, 'top' | 'bottom'> = {
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
  { kind: 'miss', label: 'a call missed' },
  { kind: 'drawn', label: 'drawn under explore' },
  { kind: 'change', label: 'new configuration' },
  { kind: 'cycle', label: 'slow-system cycle' },
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
  const tickIndex = useApp((s) => s.tickIndex)
  const playing = useApp((s) => s.playing)
  const pace = useApp((s) => s.pace)
  const following = useApp((s) => s.following)
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const bodyId = useId()
  const marks = useMemo(() => tickMarks(bundle), [bundle])
  const n = ticks.length
  const slot = (width - PAD * 2) / Math.max(1, n)
  const xOf = (i: number) => PAD + slot * (i + 0.5)
  const indexAt = (clientX: number, rect: DOMRect) =>
    Math.max(0, Math.min(n - 1, Math.floor((clientX - rect.left - PAD) / Math.max(1, slot))))
  const healthY = (h: number) => SLOT_BOTTOM - (Math.max(0, Math.min(100, h)) / 100) * (SLOT_BOTTOM - SLOT_TOP)
  const healthPath = ticks.map((t, i) => `${i === 0 ? 'M' : 'L'}${xOf(i)},${healthY(t.state?.health ?? 0)}`).join(' ')

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

  const hoverTick = hover === null ? null : ticks[hover]
  const hoverMarks = hover === null ? [] : (marks[hover] ?? [])
  const current = ticks[tickIndex]
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
          {hoverTick && (
            <div className="track-tip" style={{ left: Math.min(Math.max(xOf(hover ?? 0), 120), width - 120) }}>
              <strong>Decision {(hover ?? 0) + 1}</strong>: {words(hoverTick.executed_action) || 'missed'}, health{' '}
              {fmt(hoverTick.state?.health ?? 0, 0)}
              {hoverMarks.length > 0 && (
                <> · {hoverMarks.map((m) => MARK_LEGEND.find((l) => l.kind === m)?.label).join(' · ')}</>
              )}
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
            aria-valuetext={`Decision ${tickIndex + 1}: ${words(current?.executed_action) || 'missed'}`}
            onPointerDown={onPointer}
            onPointerMove={onPointer}
            onPointerLeave={() => setHover(null)}
          >
            {ticks.map((t, i) => (
              <rect
                key={t.tick}
                x={PAD + slot * i + 0.5}
                y={SLOT_TOP}
                width={Math.max(1, slot - 1)}
                height={SLOT_BOTTOM - SLOT_TOP}
                rx={2}
                fill={i === tickIndex ? 'var(--accent)' : i === hover ? 'var(--panel-3)' : 'var(--panel-2)'}
                opacity={i === tickIndex ? 0.35 : 1}
              />
            ))}
            <path d={healthPath} fill="none" stroke="var(--pos)" strokeWidth={1.5} opacity={0.9} />
            {marks.map((list, i) =>
              list.map((kind, j) => {
                const lane = LANE[kind]
                const same = list.filter((x) => LANE[x] === lane)
                const k = same.indexOf(kind)
                const offset = (k - (same.length - 1) / 2) * Math.min(9, slot)
                return (
                  <Mark key={`${i}-${j}`} kind={kind} x={xOf(i) + offset} y={lane === 'top' ? LANE_TOP : LANE_BOTTOM} />
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
        {current && (
          // While playing, or following a live episode, the count changes several times a second: too often to announce.
          <span
            className="tick-counter"
            data-testid="tick-counter"
            data-tick={current.tick}
            aria-live={playing || following ? 'off' : 'polite'}
          >
            Decision {tickIndex + 1}
            <span className="tick-last"> / {n}</span>
            <span className="tick-seconds"> · {fmt(gameSeconds(current.tick), 1)} s</span>
          </span>
        )}
        <div className="track-legend" aria-label="Mark legend">
          <span>
            <svg width={14} height={10} aria-hidden>
              <path d="M0,8 L14,2" stroke="var(--pos)" strokeWidth={1.5} />
            </svg>{' '}
            health
          </span>
          {MARK_LEGEND.map((m) => (
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
            <p className="sentence">{EXPLAINERS.scrubber.sentence}</p>
            <ExplainerBody id="scrubber" bodyId={bodyId} />
          </div>
        )}
      </div>
    </footer>
  )
}
