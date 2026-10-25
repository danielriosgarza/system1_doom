import { type PointerEvent, useEffect, useRef } from 'react'
import { RecordingCards } from '../components/RecordingCards'
import { Stage } from '../components/Stage'
import { Strip } from '../components/Strip'
import { useWidth } from '../components/useWidth'
import { deciderOf } from '../content/decider'
import { WATCH, counterText } from '../content/watch'
import type { EpisodeBundle } from '../data/loader'
import { type Pace, gameSeconds } from '../data/playback'
import type { TickTrace } from '../schema/bundle'
import { openPanel, setPace, setTickIndex, togglePlay, useApp } from '../store'

const BAR_HEIGHT = 26
const BAR_PAD = 2

/** A thin bar to seek with: the part played so far, the health line along it, and the decision showing. */
function Progress({ ticks, tickIndex }: { ticks: TickTrace[]; tickIndex: number }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const n = ticks.length
  const slot = (width - BAR_PAD * 2) / Math.max(1, n)
  const xOf = (i: number) => BAR_PAD + slot * (i + 0.5)
  const yOf = (health: number) => BAR_HEIGHT - 4 - (Math.max(0, Math.min(100, health)) / 100) * (BAR_HEIGHT - 8)
  const health = ticks.map((t, i) => `${i === 0 ? 'M' : 'L'}${xOf(i)},${yOf(t.state?.health ?? 0)}`).join(' ')
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
        aria-valuenow={tickIndex + 1}
        aria-valuetext={`decision ${tickIndex + 1} of ${n}`}
        onPointerDown={seek}
        onPointerMove={seek}
      >
        <rect x={0} y={0} width={width} height={BAR_HEIGHT} rx={6} className="wp-track" />
        <rect x={0} y={0} width={BAR_PAD + slot * (tickIndex + 1)} height={BAR_HEIGHT} rx={6} className="wp-played" />
        <path d={health} className="wp-health" />
        <rect
          x={BAR_PAD + slot * tickIndex}
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
function Transport({ bundle, tick, tickIndex }: { bundle: EpisodeBundle; tick: TickTrace; tickIndex: number }) {
  const playing = useApp((s) => s.playing)
  const pace = useApp((s) => s.pace)
  const following = useApp((s) => s.following)
  const live = useApp((s) => s.live?.current === bundle.name)
  const count = bundle.ticks.length
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
        data-tick={tick.tick}
        // Several changes a second while playing: too often to announce.
        aria-live={playing || following ? 'off' : 'polite'}
      >
        {counterText(tickIndex, count, gameSeconds(tick.tick), live)}
      </span>
    </div>
  )
}

/** The landing: the recording plays at the agent's own pace. */
export function Watch({ bundle, tick, tickIndex }: { bundle: EpisodeBundle; tick: TickTrace; tickIndex: number }) {
  const live = useApp((s) => s.live?.current === bundle.name)
  const top = useRef<HTMLElement | null>(null)
  // A recording opened from a card lower down plays at the top of the page.
  const name = bundle.name
  useEffect(() => {
    const el = top.current
    if (el && el.getBoundingClientRect().top < 0) window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [name])
  return (
    <main className="watch" aria-label="Watch the agent play" ref={top}>
      <header className="watch-head">
        <h2>{WATCH.title(deciderOf(bundle.meta))}</h2>
        <p>{WATCH.subtitle}</p>
      </header>
      <div className="watch-grid">
        <section className="watch-left" aria-label="The game">
          <Stage bundle={bundle} tick={tick} tickIndex={tickIndex} />
          <Progress ticks={bundle.ticks} tickIndex={tickIndex} />
          <Transport bundle={bundle} tick={tick} tickIndex={tickIndex} />
          <p className="watch-honesty">
            {live ? WATCH.liveHonesty(deciderOf(bundle.meta)) : WATCH.honesty}{' '}
            {!live && (
              <button type="button" className="link-button" onClick={() => openPanel('reference', 'provenance')}>
                {WATCH.honestyLink}
              </button>
            )}
          </p>
        </section>
        <div className="watch-right">
          <Strip bundle={bundle} tick={tick} tickIndex={tickIndex} />
        </div>
      </div>
      <RecordingCards />
    </main>
  )
}
