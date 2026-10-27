import { useEffect, useMemo, useState } from 'react'
import { WATCH, endLine, frameAlt } from '../content/watch'
import { type EpisodeBundle, endFrameUrl, frameUrl } from '../data/loader'
import { READY_FRAMES, READY_TIMEOUT_MS } from '../data/playback'
import type { TickTrace } from '../schema/bundle'
import { playWhenReady, togglePlay, useApp } from '../store'
import { usePreloadedFrames } from './useFrames'

type Layer = 'a' | 'b'

/**
 * Two stacked images: a new frame goes into the one underneath, which comes to the top and fades in over the
 * frame before it. With one frame per decision, the fade is what keeps play from looking like a slide show.
 */
function useLayers(src: string): { a: string; b: string; top: Layer } {
  const [layers, setLayers] = useState<{ a: string; b: string; top: Layer }>({ a: src, b: src, top: 'a' })
  const shown = layers.top === 'a' ? layers.a : layers.b
  if (shown !== src) {
    const next =
      layers.top === 'a' ? { ...layers, b: src, top: 'b' as const } : { ...layers, a: src, top: 'a' as const }
    setLayers(next)
    return next
  }
  return layers
}

/** The game as large as the page allows: the frame the instances saw at this decision. */
export function Stage({ bundle, tick, tickIndex }: { bundle: EpisodeBundle; tick: TickTrace; tickIndex: number }) {
  const end = endFrameUrl(bundle)
  const frames = useMemo(
    () => [...bundle.ticks.map((t) => frameUrl(bundle, t.tick)), ...(end ? [end] : [])],
    [bundle, end],
  )
  return (
    <FrameStage
      name={bundle.name}
      frames={frames}
      src={frameUrl(bundle, tick.tick)}
      end={end}
      endText={endLine(bundle.meta)}
      alt={frameAlt(tick, tickIndex, bundle.ticks.length)}
      width={bundle.meta.frames.width ?? 320}
      height={bundle.meta.frames.height ?? 240}
    />
  )
}

/**
 * The stage of either solution: the frame of the decision showing, the end frame with the result once playback
 * has run past the last decision, and a large Play button before the first play.
 */
export function FrameStage({
  name,
  frames,
  src,
  end,
  endText,
  alt,
  width,
  height,
}: {
  /** The recording's name: a new one waits for its own first frames. */
  name: string
  /** Every frame of the recording, the end frame last, decoded in order. */
  frames: string[]
  src: string
  end: string | null
  /** The line over the end frame. */
  endText: string
  alt: string
  width: number
  height: number
}) {
  const ended = useApp((s) => s.ended)
  const playing = useApp((s) => s.playing)
  const played = useApp((s) => s.played)
  const waiting = useApp((s) => s.playWhenReady)
  const following = useApp((s) => s.following)
  const loop = useApp((s) => s.loop)

  // Every frame of the open recording is fetched and decoded once, in order; playback that waits for them
  // starts when the first few are ready, or after a few seconds whatever happened.
  const ready = usePreloadedFrames(frames)
  const need = Math.min(READY_FRAMES, frames.length)
  useEffect(() => {
    if (waiting && ready >= need) playWhenReady()
  }, [waiting, ready, need])
  useEffect(() => {
    if (!waiting) return
    const timer = window.setTimeout(playWhenReady, READY_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [waiting, name])

  const atEnd = ended && end !== null
  const layers = useLayers(atEnd && end ? end : src)
  const shownAlt = atEnd ? `The game after the last decision. ${endText}.` : alt
  const offerPlay = !playing && !played && !waiting && !following
  return (
    <div className="watch-stage" data-testid="stage" data-ended={atEnd ? 'true' : undefined}>
      <div className="frame watch-frame">
        {(['a', 'b'] as const).map((layer) => (
          <img
            key={layer}
            className={`watch-img ${layers.top === layer ? 'top' : ''}`}
            src={layers[layer]}
            alt={layers.top === layer ? shownAlt : ''}
            aria-hidden={layers.top === layer ? undefined : true}
            width={width}
            height={height}
            decoding="async"
          />
        ))}
        {atEnd && (
          <div className="watch-end" data-testid="watch-end">
            <p>{endText}</p>
            {loop && playing && <p className="watch-again">{WATCH.again}</p>}
          </div>
        )}
        {offerPlay && (
          <button type="button" className="watch-bigplay" onClick={togglePlay} aria-label={WATCH.playLarge}>
            <span className="watch-bigplay-icon" aria-hidden>
              ▶
            </span>
            {WATCH.play}
          </button>
        )}
      </div>
    </div>
  )
}
