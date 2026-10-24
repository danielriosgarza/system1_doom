import { ArbiterPanel } from '../components/ArbiterPanel'
import { GameView } from '../components/GameView'
import { LegalActions } from '../components/LegalActions'
import { ModuleMatrix } from '../components/ModuleMatrix'
import { MotorPanel } from '../components/MotorPanel'
import { OutcomeCard } from '../components/OutcomeCard'
import { Panel } from '../components/Panel'
import { ProjectionStrip } from '../components/ProjectionStrip'
import { WorldState } from '../components/WorldState'
import { flashPanel, useFocusPanel } from '../components/flash'
import { BEATS, type ExplainerContext, STORY } from '../content/explainers'
import type { Admission } from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import type { TickTrace } from '../schema/bundle'
import { useApp } from '../store'

/** The inspector's compact header: how to use it, and the six beats as links into its panels. */
function InspectorHeader() {
  return (
    <section className="inspector-head" aria-label="How to read this screen">
      <ol className="beats" aria-label="The six steps of one tick">
        {BEATS.map((beat, i) => (
          <li key={beat.n} style={{ display: 'contents' }}>
            <a
              href={`#panel-${beat.panel}`}
              onClick={(e) => {
                e.preventDefault()
                flashPanel(beat.panel)
              }}
            >
              <span className="beat-num">{beat.n}</span>
              {beat.name}
            </a>
            {i < BEATS.length - 1 && (
              <span className="arrow" aria-hidden>
                →
              </span>
            )}
          </li>
        ))}
      </ol>
      <p className="howto">{STORY.howto}</p>
    </section>
  )
}

/** The tick inspector: every panel is a reading of the tick under the cursor. */
export function Inspector({
  bundle,
  tick,
  admitted,
  ctx,
}: {
  bundle: EpisodeBundle
  tick: TickTrace
  admitted: Admission[]
  ctx: ExplainerContext
}) {
  const loading = useApp((s) => s.loading)
  useFocusPanel()

  return (
    <>
      <InspectorHeader />
      <main className="main" aria-busy={loading}>
        <div className="column">
          <Panel id="game" ctx={ctx}>
            <GameView bundle={bundle} tick={tick} />
          </Panel>
          <Panel id="world" ctx={ctx}>
            <WorldState tick={tick} />
          </Panel>
          <Panel id="outcome" ctx={ctx} bounds={['≤ 12 strategies', '≤ 100k transitions']}>
            <OutcomeCard tick={tick} meta={bundle.meta} />
          </Panel>
        </div>
        <div className="column">
          <Panel id="legal" ctx={ctx} bounds={['menu ≤ 16 steps per macro', 'one proposal in flight']}>
            <LegalActions bundle={bundle} tick={tick} admitted={admitted} />
          </Panel>
          <Panel id="projection" ctx={ctx} bounds={['16 candidates', 'depth 4 · 2 branches', '15 ms', '≤ 50 samples']}>
            <ProjectionStrip tick={tick} />
          </Panel>
          <Panel id="modules" ctx={ctx} bounds={['deadline 65% of tick']}>
            <ModuleMatrix tick={tick} meta={bundle.meta} />
          </Panel>
          <Panel id="arbiter" ctx={ctx} bounds={['one pick from the menu']}>
            <ArbiterPanel tick={tick} />
          </Panel>
          <Panel id="motor" ctx={ctx} bounds={['8 frames']}>
            <MotorPanel tick={tick} meta={bundle.meta} />
          </Panel>
        </div>
      </main>
    </>
  )
}
