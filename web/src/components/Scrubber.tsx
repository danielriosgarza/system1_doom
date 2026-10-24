import { type PointerEvent, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { TickTrace } from '../schema/bundle'
import { type Admission, type TickEvent, type TickEventKind, fmt, tickEvents } from '../data/derive'
import { setState, setTickIndex, step, useApp } from '../store'
import { ExplainerBody } from './Panel'
import { EXPLAINERS, type ExplainerContext } from '../content/explainers'

const HEIGHT = 64
const LANE_TOP = 7
const SLOT_TOP = 16
const SLOT_BOTTOM = 42
const LANE_BOTTOM = 54
const PAD = 8

const KIND_LANE: Record<TickEventKind, 'top' | 'bottom'> = {
  damage: 'top',
  kill: 'top',
  death: 'top',
  sampled: 'bottom',
  committed: 'bottom',
  expansion: 'bottom',
  admission: 'bottom',
  strategy: 'bottom',
}

const MARK_LEGEND: Array<{ kind: TickEventKind; label: string }> = [
  { kind: 'damage', label: 'damage' },
  { kind: 'kill', label: 'kill' },
  { kind: 'death', label: 'death' },
  { kind: 'sampled', label: 'sampled pick' },
  { kind: 'committed', label: 'module committed' },
  { kind: 'expansion', label: 'asked for a macro' },
  { kind: 'admission', label: 'macro admitted' },
  { kind: 'strategy', label: 'strategy switch' },
]

function Mark({ kind, x, y }: { kind: TickEventKind; x: number; y: number }) {
  switch (kind) {
    case 'damage':
      return <path d={`M${x - 4},${y - 3} h8 l-4,6 z`} fill="var(--neg)" />
    case 'kill':
      return <path d={`M${x},${y - 5} l4,5 l-4,5 l-4,-5 z`} fill="var(--combat)" />
    case 'death':
      return <path d={`M${x - 4},${y - 4} l8,8 M${x + 4},${y - 4} l-8,8`} stroke="var(--neg)" strokeWidth={2} />
    case 'sampled':
      return <circle cx={x} cy={y} r={3.5} fill="none" stroke="var(--n1)" strokeWidth={1.5} />
    case 'committed':
      return <rect x={x - 3.5} y={y - 3.5} width={7} height={7} fill="var(--accent)" />
    case 'expansion':
      return <path d={`M${x - 3},${y + 5} v-10 l7,3 l-7,3`} fill="var(--goal)" stroke="var(--goal)" strokeWidth={1} />
    case 'admission':
      return <path d={`M${x - 4},${y} h8 M${x},${y - 4} v8`} stroke="var(--goal)" strokeWidth={2.5} />
    case 'strategy':
      return <rect x={x - 1} y={y - 5} width={2.5} height={10} fill="var(--navigation)" />
  }
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(800)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => entry && setWidth(entry.contentRect.width))
    observer.observe(el)
    setWidth(el.getBoundingClientRect().width)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

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

  useEffect(() => {
    if (!playing) return
    const timer = window.setInterval(() => step(1), 450)
    return () => window.clearInterval(timer)
  }, [playing])

  useEffect(() => {
    if (playing && tickIndex >= n - 1) setState({ playing: false })
  }, [playing, tickIndex, n])

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
    <footer className="scrubber">
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
            onClick={() => {
              if (!playing && tickIndex >= n - 1) setTickIndex(0)
              setState({ playing: !playing })
            }}
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
        <span />
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
        <span />
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
