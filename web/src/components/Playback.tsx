import type { PointerEvent } from 'react'
import { WATCH, counterText } from '../content/watch'
import type { Pace } from '../data/playback'
import { setPace, setTickIndex, togglePlay, useApp } from '../store'
import { useWidth } from './useWidth'

const BAR_HEIGHT = 26
const BAR_PAD = 2

/** A thin bar to seek with: the part played so far, the health line along it, and the decision showing. */
export function Progress({ health, index }: { health: number[]; index: number }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const n = health.length
  const slot = (width - BAR_PAD * 2) / Math.max(1, n)
  const xOf = (i: number) => BAR_PAD + slot * (i + 0.5)
  const yOf = (h: number) => BAR_HEIGHT - 4 - (Math.max(0, Math.min(100, h)) / 100) * (BAR_HEIGHT - 8)
  const line = health.map((h, i) => `${i === 0 ? 'M' : 'L'}${xOf(i)},${yOf(h)}`).join(' ')
  const seek = (e: PointerEvent<SVGSVGElement>) => {
    if (e.type === 'pointermove' && e.buttons !== 1) return
    if (e.type === 'pointerdown') e.currentTarget.setPointerCapture(e.pointerId)
    const rect = e.currentTarget.getBoundingClientRect()
    setTickIndex(Math.floor((e.clientX - rect.left - BAR_PAD) / Math.max(1, slot)))
  }
  return (
    <div className="watch-progress" ref={ref}>
      <svg
        width={width}
        height={BAR_HEIGHT}
        role="slider"
        tabIndex={0}
        aria-label={WATCH.progress}
        aria-valuemin={1}
        aria-valuemax={n}
        aria-valuenow={index + 1}
        aria-valuetext={`decision ${index + 1} of ${n}`}
        onPointerDown={seek}
        onPointerMove={seek}
      >
        <rect x={0} y={0} width={width} height={BAR_HEIGHT} rx={6} className="wp-track" />
        <rect x={0} y={0} width={BAR_PAD + slot * (index + 1)} height={BAR_HEIGHT} rx={6} className="wp-played" />
        <path d={line} className="wp-health" />
        <rect
          x={BAR_PAD + slot * index}
          y={1}
          width={Math.max(2, slot)}
          height={BAR_HEIGHT - 2}
          rx={2}
          className="wp-cursor"
        />
      </svg>
    </div>
  )
}

/** Play or pause, the pace, and where in the recording this is. */
export function Transport({
  count,
  index,
  seconds,
  live,
  tick,
}: {
  count: number
  index: number
  /** Game time when the decision showing was made. */
  seconds: number
  live: boolean
  /** The decision's own number, for the tests. */
  tick: number
}) {
  const playing = useApp((s) => s.playing)
  const pace = useApp((s) => s.pace)
  const following = useApp((s) => s.following)
  return (
    <div className="watch-transport">
      <button
        type="button"
        className="watch-play"
        onClick={togglePlay}
        aria-label={playing ? WATCH.pause : WATCH.play}
        title={`${playing ? WATCH.pause : WATCH.play} (space)`}
      >
        <span className="watch-play-icon" aria-hidden>
          {playing ? '❚❚' : '▶'}
        </span>
        {playing ? WATCH.pause : WATCH.play}
      </button>
      <span className="segmented" role="group" aria-label={WATCH.paceGroup}>
        {(['real', 'slow'] as Pace[]).map((p) => (
          <button key={p} type="button" aria-pressed={pace === p} title={WATCH.paceTitle[p]} onClick={() => setPace(p)}>
            {WATCH.pace[p]}
          </button>
        ))}
      </span>
      <span
        className="watch-counter"
        data-testid="watch-counter"
        data-tick={tick}
        // Several changes a second while playing: too often to announce.
        aria-live={playing || following ? 'off' : 'polite'}
      >
        {counterText(index, count, seconds, live)}
      </span>
    </div>
  )
}
