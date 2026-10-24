import { useEffect, useRef, useState } from 'react'
import { Architecture } from '../components/Architecture'
import { BOXES, type BoxId } from '../content/architecture'
import { ExplainerBody } from '../components/Panel'
import { EXPLAINERS, type ExplainerContext, STORY } from '../content/explainers'
import { fmt, pct } from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import type { EpisodeMeta, TickTrace } from '../schema/bundle'
import { type Screen, openInInspector, openPanel, setScreen, startTour, useApp } from '../store'

/** Which deciders were switched on for this recording. */
function Brains({ meta }: { meta: EpisodeMeta }) {
  const checkpoint = meta.checkpoint
  return (
    <div className="brains" aria-label="Which deciders were switched on">
      <span className="brain on">
        <span className="dot" /> Hand-written heuristics
      </span>
      <span className={`brain ${meta.brains.learned_networks ? 'on' : ''}`}>
        <span className="dot" />
        {meta.brains.learned_networks && checkpoint
          ? `Learned networks: ${checkpoint.episodes} training episodes, earned ${pct(checkpoint.network_share)} of the say`
          : 'Learned networks: off'}
      </span>
      <span className={`brain ${meta.brains.d1_ultra ? 'on' : ''}`}>
        <span className="dot" /> d1-ultra advice: {meta.brains.d1_ultra ? 'on' : 'off'}
      </span>
      <span className={`brain ${meta.brains.slow_path !== 'off' ? 'on' : ''}`}>
        <span className="dot" /> Slow path:{' '}
        {meta.brains.slow_path === 'templates'
          ? 'fallback templates'
          : meta.brains.slow_path === 'codex'
            ? 'Codex'
            : 'off'}
      </span>
      <span className="brain">
        {meta.scenario.replace('.cfg', '').replaceAll('_', ' ')}, seed {meta.seed}:{' '}
        {meta.result.cleared ? 'cleared' : meta.result.died ? 'died' : 'survived'} after {meta.tick_count} ticks, reward{' '}
        {fmt(meta.result.reward, 0)}
      </span>
    </div>
  )
}

/** Where the fast path sits across the diagram, as a fraction of its width. */
const FAST_PATH_CENTRE = 560 / 1130

const SCREEN_LINES: Array<{ id: Screen; name: string; line: string }> = [
  {
    id: 'overview',
    name: 'Overview',
    line: 'this page: the whole controller on one diagram, every box showing the current tick.',
  },
  {
    id: 'tick',
    name: 'Tick',
    line: 'one decision in full: what was seen, what was legal, five opinions, the score sheet, the keys pressed, the outcome.',
  },
  {
    id: 'hierarchy',
    name: 'Hierarchy',
    line: 'the same tick as a tower of six levels, from growing the menu down to the motor, each drawn as the same card.',
  },
]

export function Overview({ bundle, tick, ctx }: { bundle: EpisodeBundle; tick: TickTrace; ctx: ExplainerContext }) {
  const tickIndex = useApp((s) => s.tickIndex)
  const playing = useApp((s) => s.playing)
  const tourSeen = useApp((s) => s.tourSeen)
  const [selected, setSelected] = useState<BoxId | null>(null)
  const box = selected ? BOXES[selected] : null
  const figureRef = useRef<HTMLDivElement | null>(null)
  const cardRef = useRef<HTMLElement | null>(null)

  // On a phone the diagram scrolls sideways; start it on the fast path, the part every tick runs.
  useEffect(() => {
    const figure = figureRef.current
    if (!figure || figure.scrollWidth <= figure.clientWidth) return
    figure.scrollLeft = figure.scrollWidth * FAST_PATH_CENTRE - figure.clientWidth / 2
  }, [])

  const select = (id: BoxId) => {
    const next = selected === id ? null : id
    setSelected(next)
    // When the explanation sits below the diagram, bring it up.
    if (next && window.matchMedia('(max-width: 1100px)').matches) {
      window.requestAnimationFrame(() => cardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    }
  }
  return (
    <main className="overview">
      <section className="intro" aria-label="What this app shows">
        <p className="story-line">
          <strong>{STORY.sentence}</strong> {STORY.invariant}
        </p>
        <Brains meta={bundle.meta} />
        <div className="intro-actions">
          <button type="button" className="primary-button" onClick={startTour}>
            {tourSeen ? 'Take the tour again' : 'Take the tour'}
          </button>
          <span className="muted">six steps through one real tick, then the hierarchy; → to advance, Esc to leave</span>
        </div>
      </section>
      <section className="arch-wrap" aria-label="Architecture">
        <div className="arch-figure">
          <div className="arch-scroll" ref={figureRef}>
            <Architecture
              bundle={bundle}
              tick={tick}
              tickIndex={tickIndex}
              playing={playing}
              selected={selected}
              onSelect={select}
            />
          </div>
          <p className="arch-legend">
            <span>
              <span className="key solid" style={{ ['--c' as string]: 'var(--n2)' }} /> hand-written
            </span>
            <span>
              <span className="key hatched" style={{ ['--c' as string]: 'var(--n2)' }} /> learned (dashed arrows)
            </span>
            <span>
              <span className="key dotted" style={{ ['--c' as string]: 'var(--n2)' }} /> d1-ultra (dotted arrows)
            </span>
            <span>
              <span className="key solid" style={{ ['--c' as string]: 'var(--goal)' }} /> lit: the slow path is busy
              this tick
            </span>
            <span>Press play to watch each tick run down the chain.</span>
            <span className="phone-only">Swipe the diagram sideways for the slow path and the learning.</span>
          </p>
        </div>
        <aside className="arch-card" aria-live="polite" ref={cardRef}>
          {box && selected ? (
            <>
              <header className="panel-head">
                {box.beat ? (
                  <span className="beat-num">{box.beat}</span>
                ) : (
                  <span className="beat-num side" aria-hidden>
                    ↳
                  </span>
                )}
                <h2>{box.title}</h2>
              </header>
              <p className="sentence">{EXPLAINERS[box.explainer].sentence}</p>
              <ExplainerBody id={box.explainer} ctx={ctx} />
              <p className="arch-links">
                {box.panel && (
                  <button type="button" className="link-button" onClick={() => openInInspector(box.panel as string)}>
                    Open in the inspector →
                  </button>
                )}
                {box.learning && (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => openPanel('learning', box.learning as string)}
                  >
                    Open in Learning →
                  </button>
                )}
              </p>
            </>
          ) : (
            <>
              <h2>Click any box</h2>
              <p className="sentence">
                Each box is one part of the controller, showing what it did at tick {tick.tick}. Click one for what it
                does, why, and where it lives in the code. The numbered boxes are the six beats of every tick.
              </p>
              <h3 className="arch-card-sub">Three ways to look</h3>
              <ul className="screen-lines">
                {SCREEN_LINES.map((s) => (
                  <li key={s.id}>
                    <button type="button" className="link-button" onClick={() => setScreen(s.id)}>
                      {s.name}
                    </button>
                    : {s.line}
                  </li>
                ))}
              </ul>
            </>
          )}
        </aside>
      </section>
    </main>
  )
}
