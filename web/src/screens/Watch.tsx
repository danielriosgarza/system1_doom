import { useEffect, useRef } from 'react'
import { Progress, Transport } from '../components/Playback'
import { RecordingCards } from '../components/RecordingCards'
import { Stage } from '../components/Stage'
import { Strip } from '../components/Strip'
import { deciderOf } from '../content/decider'
import { WATCH } from '../content/watch'
import type { EpisodeBundle } from '../data/loader'
import { gameSeconds } from '../data/playback'
import type { TickTrace } from '../schema/bundle'
import { openPanel, useApp } from '../store'

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
          <Progress health={bundle.ticks.map((t) => t.state?.health ?? 0)} index={tickIndex} />
          <Transport
            count={bundle.ticks.length}
            index={tickIndex}
            seconds={gameSeconds(tick.tick)}
            live={live}
            tick={tick.tick}
          />
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
