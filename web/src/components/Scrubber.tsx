import { type PointerEvent, useId, useState } from 'react'
import type { TickTrace } from '../schema/bundle'
import { WATCH } from '../content/watch'
import { type Admission, type TickEvent, fmt, gameSeconds, tickEvents } from '../data/derive'
import type { Pace } from '../data/playback'
import { setPace, setTickIndex, step, togglePlay, useApp } from '../store'
import { Mark } from './Marks'
import { KIND_LANE, MARK_LEGEND } from './markKinds'
import { ExplainerBody } from './Panel'
import { useWidth } from './useWidth'
import { EXPLAINERS, type ExplainerContext } from '../content/explainers'

const HEIGHT = 64
const LANE_TOP = 7
const SLOT_TOP = 16
const SLOT_BOTTOM = 42
const LANE_BOTTOM = 54
const PAD = 8

export function Scrubber({
  ticks,
  admitted,
  ctx,
}: {
  ticks: TickTrace[]
  admitted: Admission[]
  ctx: ExplainerContext | null
}) {
  const tickIndex = useApp((s) => s.tickIndex)
  const playing = useApp((s) => s.playing)
  const pace = useApp((s) => s.pace)
  const following = useApp((s) => s.following)
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const bodyId = useId()
  const n = ticks.length
  const slot = (width - PAD * 2) / Math.max(1, n)
  const xOf = (i: number) => PAD + slot * (i + 0.5)
  const indexAt = (clientX: number, rect: DOMRect) =>
    Math.max(0, Math.min(n - 1, Math.floor((clientX - rect.left - PAD) / Math.max(1, slot))))
  const events: TickEvent[][] = ticks.map((t) => tickEvents(t, admitted))
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
  const hoverEvents = hover === null ? [] : (events[hover] ?? [])
  const current = ticks[tickIndex]
  return (
    <footer className="scrubber" id="panel-scrubber">
      <div className="scrubber-inner">
        <div className="transport" role="group" aria-label="Playback">
          <button type="button" onClick={() => setTickIndex(0)} aria-label="First tick" title="First tick (Home)">
            ⏮
          </button>
          <button type="button" onClick={() => step(-1)} aria-label="Previous tick" title="Previous tick (←)">
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
          <button type="button" onClick={() => step(1)} aria-label="Next tick" title="Next tick (→)">
            ▶︎
          </button>
          <button type="button" onClick={() => setTickIndex(n - 1)} aria-label="Last tick" title="Last tick (End)">
            ⏭
          </button>
        </div>
        <div className="track" ref={ref}>
          {hoverTick && (
            <div className="track-tip" style={{ left: Math.min(Math.max(xOf(hover ?? 0), 120), width - 120) }}>
              <strong>Tick {hoverTick.tick}</strong>: {hoverTick.selected_action.replaceAll('_', ' ')}, health{' '}
              {fmt(hoverTick.state?.health ?? 0, 0)}
              {hoverEvents.length > 0 && <> · {hoverEvents.map((e) => e.label).join(' · ')}</>}
            </div>
          )}
          <svg
            width={width}
            height={HEIGHT}
            role="slider"
            tabIndex={0}
            aria-label="Tick"
            aria-valuemin={ticks[0]?.tick ?? 0}
            aria-valuemax={ticks[n - 1]?.tick ?? 0}
            aria-valuenow={current?.tick ?? 0}
            aria-valuetext={`Tick ${current?.tick ?? 0}: ${current?.selected_action ?? ''}`}
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
            {events.map((list, i) =>
              list.map((e, j) => {
                const lane = KIND_LANE[e.kind]
                const sameLane = list.filter((x) => KIND_LANE[x.kind] === lane)
                const k = sameLane.indexOf(e)
                const offset = (k - (sameLane.length - 1) / 2) * Math.min(9, slot)
                return (
                  <Mark
                    key={`${i}-${j}`}
                    kind={e.kind}
                    x={xOf(i) + offset}
                    y={lane === 'top' ? LANE_TOP : LANE_BOTTOM}
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
        {current && (
          // While playing, or following a live episode, the count changes several times a second: too often to announce.
          <span
            className="tick-counter"
            data-testid="tick-counter"
            data-tick={current.tick}
            aria-live={playing || following ? 'off' : 'polite'}
          >
            Tick {current.tick}
            <span className="tick-last"> / {ticks[n - 1]?.tick ?? current.tick}</span>
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
        <div className="track-legend">
          <span className="scrub-sentence">{EXPLAINERS.scrubber.sentence}</span>
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
        {open && (
          <div className="scrub-explainer">
            <ExplainerBody id="scrubber" bodyId={bodyId} ctx={ctx} />
          </div>
        )}
      </div>
    </footer>
  )
}
