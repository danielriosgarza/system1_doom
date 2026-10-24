import { AdmissionGate } from '../components/AdmissionGate'
import { FollowUp } from '../components/FollowUp'
import { Panel } from '../components/Panel'
import { ProposalCard } from '../components/ProposalCard'
import { RequestTimeline } from '../components/RequestTimeline'
import { VocabularyDiff } from '../components/VocabularyDiff'
import { useFocusPanel } from '../components/flash'
import { useEpisode } from '../components/useEpisode'
import type { ExplainerContext } from '../content/explainers'
import { MEMORY_LABELS, closestToAsking, requestSpans } from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import type { TickTrace } from '../schema/bundle'
import { openEpisode, useApp } from '../store'

/** No request in this recording: the closest call, and the other recording of this seed if one asked. */
function NoRequests({ bundle }: { bundle: EpisodeBundle }) {
  const index = useApp((s) => s.index)
  const closest = closestToAsking(bundle.ticks)
  const pairEntry = index?.episodes.find(
    (e) => e.name !== bundle.name && e.scenario === bundle.meta.scenario && e.seed === bundle.meta.seed,
  )
  const pair = useEpisode(pairEntry?.name ?? null)
  const first = pair ? requestSpans(pair.ticks, pair.proposals)[0] : undefined
  return (
    <p className="empty-note" data-testid="no-requests">
      No module crossed its threshold in this recording
      {closest
        ? `; the closest was ${closest.module} at tick ${closest.tick}, ${MEMORY_LABELS[closest.counter] ?? closest.counter} ${closest.value} of ${closest.threshold}.`
        : '.'}{' '}
      {pair && first && (
        <button type="button" className="link-button" onClick={() => void openEpisode(pair.name, first.asked)}>
          See {first.module} ask in the {pair.meta.model === 'heuristics' ? 'heuristics' : 'networks'} recording of this
          seed, at tick {first.asked} →
        </button>
      )}
    </p>
  )
}

/** Growing the menu: from a module's complaint to a new chip, the gate in between, and what it paid. */
export function Menu({ bundle, tick, ctx }: { bundle: EpisodeBundle; tick: TickTrace; ctx: ExplainerContext }) {
  useFocusPanel()
  const spans = requestSpans(bundle.ticks, bundle.proposals)
  return (
    <main className="menu-screen" aria-label="Growing the menu">
      <header className="screen-head">
        <h2>Growing the menu: the one part that writes something new</h2>
        <p>
          Everything else in the controller chooses from a menu it cannot change. This path is the exception: a module
          names a repeated failure in one sentence, a slow worker outside the real-time loop writes a macro, five checks
          decide whether it joins the menu, and from then on it competes like every other action.
        </p>
      </header>

      <Panel id="requests" ctx={ctx} bounds={['one counter, one threshold', 'one proposal in flight']}>
        {spans.length === 0 && <NoRequests bundle={bundle} />}
        <RequestTimeline ticks={bundle.ticks} spans={spans} />
      </Panel>

      <div className="menu-grid">
        <Panel id="proposal" ctx={ctx} bounds={['≤ 16 primitives, known ones only']}>
          <ProposalCard tick={tick} proposals={bundle.proposals} spans={spans} />
        </Panel>
        <Panel id="gate" ctx={ctx} bounds={['five stages']}>
          <AdmissionGate ticks={bundle.ticks} tick={tick} proposals={bundle.proposals} spans={spans} ctx={ctx} />
        </Panel>
        <Panel id="encoding" ctx={ctx} bounds={['12 numbers per action']}>
          <VocabularyDiff bundle={bundle} tick={tick} />
        </Panel>
        <Panel id="followup" ctx={ctx} bounds={['+0.15 per strategy action']}>
          <FollowUp bundle={bundle} tick={tick} />
        </Panel>
      </div>
    </main>
  )
}
