import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { INVARIANTS, TOUR } from '../content/tour'
import type { EpisodeBundle } from '../data/loader'
import type { TickTrace } from '../schema/bundle'
import { endTour, setScreen, setTourStep } from '../store'

interface Rect {
  top: number
  left: number
  width: number
  height: number
}

const PAD = 8
const CARD_WIDTH = 360
/** Below this width the card docks under the spotlight, above the timeline. */
const NARROW = 900

function targetsOf(step: number): Element[] {
  const panels = TOUR[step]?.panels ?? []
  if (panels.length === 0) return [document.querySelector('.tower')].filter((el): el is Element => !!el)
  return panels.map((p) => document.getElementById(`panel-${p}`)).filter((el): el is HTMLElement => !!el)
}

function unionRect(elements: Element[]): Rect | null {
  if (elements.length === 0) return null
  const rects = elements.map((el) => el.getBoundingClientRect())
  const top = Math.min(...rects.map((r) => r.top))
  const left = Math.min(...rects.map((r) => r.left))
  const bottom = Math.max(...rects.map((r) => r.bottom))
  const right = Math.max(...rects.map((r) => r.right))
  return { top: top - PAD, left: left - PAD, width: right - left + 2 * PAD, height: bottom - top + 2 * PAD }
}

/** The bars that stay on screen while the page scrolls; on a phone the top bar scrolls away. */
function chromeHeights(): { top: number; bottom: number } {
  const topbar = document.querySelector('.topbar')
  const sticky = topbar && getComputedStyle(topbar).position === 'sticky'
  return {
    top: sticky ? Math.max(0, topbar.getBoundingClientRect().bottom) : 0,
    bottom: document.querySelector('.scrubber')?.getBoundingClientRect().height ?? 0,
  }
}

/** Coach marks over the featured tick: the page dims except the panel the step is about. */
export function Tour({ step, bundle, tick }: { step: number; bundle: EpisodeBundle; tick: TickTrace }) {
  const current = TOUR[step]
  const [rect, setRect] = useState<Rect | null>(null)
  const [viewport, setViewport] = useState({ w: window.innerWidth, h: window.innerHeight })
  const [cardHeight, setCardHeight] = useState(240)
  const cardRef = useRef<HTMLDivElement | null>(null)
  const nextRef = useRef<HTMLButtonElement | null>(null)

  // Bring the step's panels into view, then follow them while the page scrolls or reflows.
  useEffect(() => {
    let frame = 0
    let alive = true
    const start = window.setTimeout(() => {
      const targets = targetsOf(step)
      const box = unionRect(targets)
      if (box) {
        // Centre a target that fits; put the top of a taller one (or any, on a phone) under the top bar.
        const chrome = chromeHeights()
        const room = window.innerHeight - chrome.top - chrome.bottom
        const narrow = window.innerWidth < NARROW
        const offset =
          narrow || box.height > room ? box.top - chrome.top - 4 : box.top + box.height / 2 - (chrome.top + room / 2)
        window.scrollBy({ top: offset, behavior: 'smooth' })
      }
      const follow = () => {
        if (!alive) return
        setRect(unionRect(targetsOf(step)))
        setViewport({ w: window.innerWidth, h: window.innerHeight })
        frame = window.requestAnimationFrame(follow)
      }
      follow()
    }, 30)
    nextRef.current?.focus({ preventScroll: true })
    return () => {
      alive = false
      window.clearTimeout(start)
      window.cancelAnimationFrame(frame)
    }
  }, [step])

  useLayoutEffect(() => {
    const el = cardRef.current
    if (!el) return
    const observer = new ResizeObserver(() => setCardHeight(el.getBoundingClientRect().height))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  if (!current) return null
  const chrome = chromeHeights()
  const narrow = viewport.w < NARROW
  const width = Math.min(CARD_WIDTH, viewport.w - 24)
  let cardStyle: React.CSSProperties
  if (narrow || !rect) {
    cardStyle = { left: 12, right: 12, bottom: chrome.bottom + 10 }
  } else {
    const roomRight = viewport.w - (rect.left + rect.width) - 16
    const left =
      roomRight >= width
        ? rect.left + rect.width + 16
        : rect.left - 16 >= width
          ? rect.left - 16 - width
          : viewport.w - width - 16
    const top = Math.max(chrome.top + 10, Math.min(rect.top, viewport.h - chrome.bottom - cardHeight - 10))
    cardStyle = { left, top, width }
  }
  const last = step === TOUR.length - 1
  const ctx = { tick, meta: bundle.meta }
  return (
    <div className="tour" data-step={step}>
      {rect && (
        <>
          {/* Four blockers around the spotlight keep clicks off the dimmed page but let the panel be hovered. */}
          <div className="tour-block" style={{ top: 0, left: 0, right: 0, height: Math.max(0, rect.top) }} />
          <div className="tour-block" style={{ top: rect.top + rect.height, left: 0, right: 0, bottom: 0 }} />
          <div
            className="tour-block"
            style={{ top: rect.top, left: 0, width: Math.max(0, rect.left), height: rect.height }}
          />
          <div
            className="tour-block"
            style={{ top: rect.top, left: rect.left + rect.width, right: 0, height: rect.height }}
          />
          <div className="tour-spotlight" style={rect} aria-hidden />
        </>
      )}
      <div
        ref={cardRef}
        className={`tour-card ${narrow ? 'docked' : ''}`}
        style={cardStyle}
        role="dialog"
        aria-labelledby="tour-title"
      >
        <div className="tour-progress" aria-label={`Step ${step + 1} of ${TOUR.length}`}>
          {TOUR.map((s, i) => (
            <span key={s.title} className={`tour-dot ${i === step ? 'on' : i < step ? 'done' : ''}`} />
          ))}
          <span className="tour-count">
            {step + 1} / {TOUR.length}
          </span>
        </div>
        <h2 id="tour-title">
          {current.beat && <span className="beat-num">{current.beat}</span>} {current.title}
        </h2>
        {current.text(ctx).map((p) => (
          <p key={p.slice(0, 40)}>{p}</p>
        ))}
        {current.invariants.map((inv) => (
          <p key={inv} className="tour-invariant">
            {INVARIANTS[inv]}
          </p>
        ))}
        <div className="tour-buttons">
          <button type="button" className="link-button" onClick={endTour}>
            {last ? 'Close' : 'Skip'}
          </button>
          <span className="spacer" />
          <button type="button" className="icon-button" onClick={() => setTourStep(step - 1)} disabled={step === 0}>
            Back
          </button>
          {last ? (
            <button
              ref={nextRef}
              type="button"
              className="primary-button"
              onClick={() => {
                endTour()
                setScreen('tick')
              }}
            >
              Back to the inspector
            </button>
          ) : (
            <button ref={nextRef} type="button" className="primary-button" onClick={() => setTourStep(step + 1)}>
              Next →
            </button>
          )}
        </div>
        <p className="tour-keys">→ next · ← back · Esc leaves the tour</p>
      </div>
    </div>
  )
}
