import { GateView } from '../components/GateView'
import { HeadToHead } from '../components/HeadToHead'
import { LearningCurves } from '../components/LearningCurves'
import { Panel } from '../components/Panel'
import { RewardAnatomy } from '../components/RewardAnatomy'
import { TrustHere, TrustMap } from '../components/TrustMap'
import { useFocusPanel } from '../components/flash'
import type { ExplainerContext } from '../content/explainers'
import type { EpisodeBundle } from '../data/loader'
import type { TickTrace } from '../schema/bundle'
import { openEpisode, useApp } from '../store'

/** "No networks in this recording", with a link to the recording of the same seed that has them. */
function NoNetworks({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const index = useApp((s) => s.index)
  const pair = index?.episodes.find(
    (e) => e.model !== 'heuristics' && e.scenario === bundle.meta.scenario && e.seed === bundle.meta.seed,
  )
  return (
    <p className="empty-note" data-testid="no-networks">
      No networks in this recording: it was played by the heuristics alone.{' '}
      {pair && (
        <button
          type="button"
          className="link-button"
          onClick={() => void openEpisode(pair.name, Math.min(tick.tick, pair.ticks - 1))}
        >
          See the recording with the networks at tick {Math.min(tick.tick, pair.ticks - 1)} →
        </button>
      )}
    </p>
  )
}

/** Learning across episodes: how the networks earned their say, and what they do with it at this tick. */
export function Learning({ bundle, tick, ctx }: { bundle: EpisodeBundle; tick: TickTrace; ctx: ExplainerContext }) {
  const tickIndex = useApp((s) => s.tickIndex)
  useFocusPanel()
  const { meta, metrics, evaluation, trust } = bundle
  const learned = meta.brains.learned_networks && trust !== null
  return (
    <main className="learning" aria-label="Learning across episodes">
      <header className="screen-head">
        <h2>Learning: how the networks earned their say</h2>
        <p>
          The networks never change the menu or the levels. They learn between episodes how to weigh what each level
          already offers: trust per situation and action for the five modules, and a gate that re-weighs the modules for
          the arbiter.{' '}
          {learned
            ? `This recording loaded the checkpoint saved after ${meta.checkpoint?.episodes ?? '?'} training episodes.`
            : 'This recording was played by the heuristics alone; the training run below is the one the other recording of this seed used.'}
        </p>
      </header>

      <h3 className="section-head">Across episodes</h3>
      <div className="learning-grid">
        <Panel id="headtohead" ctx={ctx} bounds={['same seed, same menu']}>
          <HeadToHead bundle={bundle} evaluation={evaluation} />
        </Panel>
        <Panel id="curves" ctx={ctx} bounds={['trains between episodes', '≤ 100k transitions']}>
          {metrics && metrics.length > 0 ? (
            <>
              {!learned && (
                <p className="empty-note">This recording did not use these networks; it was played without them.</p>
              )}
              <LearningCurves metrics={metrics} meta={meta} trainedEpisodes={evaluation?.trained_episodes ?? null} />
            </>
          ) : (
            <p className="empty-note">This bundle carries no training run.</p>
          )}
        </Panel>
      </div>

      <h3 className="section-head">At tick {tick.tick}</h3>
      <div className="learning-grid tick">
        <Panel id="trustmap" ctx={ctx} bounds={['λ < 1']}>
          {learned && trust ? (
            <div className="trust-wrap">
              <TrustMap trust={trust} meta={meta} tick={tick} />
              <TrustHere trust={trust} tick={tick} />
            </div>
          ) : (
            <NoNetworks bundle={bundle} tick={tick} />
          )}
        </Panel>
        <Panel id="gateview" ctx={ctx} bounds={['five weights, sum 1']}>
          {learned && trust && tick.arbiter?.module_weights_gate ? (
            <GateView tick={tick} contextN={trust.context_counts[tick.context_signature] ?? 0} />
          ) : learned ? (
            <p className="empty-note">The gate was not consulted on this tick.</p>
          ) : (
            <NoNetworks bundle={bundle} tick={tick} />
          )}
        </Panel>
        <Panel id="anatomy" ctx={ctx} bounds={['8 steps · γ 0.9']}>
          <RewardAnatomy ticks={bundle.ticks} index={tickIndex} learned={learned} />
        </Panel>
      </div>
    </main>
  )
}
