import {
  type FollowUp as FollowUpReading,
  STRATEGY_BONUS,
  fmt,
  followUp,
  prettyId,
  prunedReasonText,
  strategyName,
  tickRange,
} from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import type { TickTrace } from '../schema/bundle'
import { setScreen, setTickIndex, useApp } from '../store'

/** The bet in one sentence, from the readings. */
function verdict(readings: FollowUpReading[]): string {
  const picks = readings.reduce((n, f) => n + f.picked.length, 0)
  const legal = readings.some((f) => f.legal.length > 0)
  const adopted = readings.some((f) => f.adopted.length > 0)
  if (picks > 0) return `The bet reached play: admitted macros were picked ${picks} time${picks === 1 ? '' : 's'}.`
  if (adopted)
    return `The bet changed steering, not the actions: ${legal ? 'no admitted macro was picked' : 'no admitted macro was ever legal'}, but an adopted strategy tilted the choice between the actions around it.`
  return `The bet has not paid: ${legal ? 'no admitted macro was picked' : 'no admitted macro was ever legal'}, and steering never adopted their strategies.`
}

function openHierarchyAt(ticks: TickTrace[], tick: number): void {
  setTickIndex(ticks.findIndex((t) => t.tick === tick))
  setScreen('hierarchy')
}

/** For each admitted macro: legal, picked, rewarded, and what adopting its strategy changed. */
export function FollowUp({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const tickIndex = useApp((s) => s.tickIndex)
  const readings = bundle.proposals.flatMap((p) => {
    const f = followUp(p, bundle.ticks)
    return f ? [f] : []
  })
  if (readings.length === 0)
    return <p className="empty-note">No macro was admitted in this recording, so there is nothing to follow up.</p>
  return (
    <div className="followup">
      {readings.map((f) => {
        const action = bundle.meta.actions[f.id]
        const joinedYet = tick.tick >= f.joined
        const bonusActions = [...new Set(f.bonus.flatMap((b) => b.actions))]
        const chosenWithBonus = f.bonus.filter((b) => b.actions.includes(b.selected))
        const sequence =
          bundle.ticks.flatMap((t) => t.steering?.entries ?? []).find((e) => e.strategy_id === f.strategy)
            ?.action_sequence ?? []
        const after = bundle.ticks.filter((t) => t.tick >= f.joined)
        return (
          <section key={f.id} className={`fu-macro ${joinedYet ? '' : 'later'}`} data-macro={f.id}>
            <h4>
              {prettyId(f.id)}{' '}
              <span className="muted">
                joined the menu at tick {f.joined}
                {joinedYet ? '' : ', after this tick'}
              </span>
            </h4>
            <dl className="fu-stats">
              <div>
                <dt>legal</dt>
                <dd>
                  {f.legal.length} of {f.ticksAfter} ticks
                </dd>
              </div>
              <div>
                <dt>picked</dt>
                <dd>{f.picked.length === 0 ? 'never' : `${f.picked.length} times`}</dd>
              </div>
              <div>
                <dt>reward each time it ran</dt>
                <dd>{f.rewards.length === 0 ? 'it never ran' : f.rewards.map((r) => fmt(r, 2)).join(', ')}</dd>
              </div>
            </dl>
            <div className="fu-strip" aria-label="Ticks after it joined">
              {after.map((t) => {
                const bonus = f.bonus.find((b) => b.tick === t.tick)
                const cls = [
                  'fu-cell',
                  f.legal.includes(t.tick) ? 'legal' : '',
                  f.picked.includes(t.tick) ? 'picked' : '',
                  bonus ? 'bonus' : '',
                  bonus && bonus.actions.includes(bonus.selected) ? 'chose-bonus' : '',
                  bundle.ticks[tickIndex]?.tick === t.tick ? 'here' : '',
                ].join(' ')
                return (
                  <button
                    key={t.tick}
                    type="button"
                    className={cls}
                    title={`Tick ${t.tick}: ${f.legal.includes(t.tick) ? 'legal' : 'not legal'}${bonus ? `; strategy bonus on ${bonus.actions.map(prettyId).join(', ')}; chose ${prettyId(bonus.selected)}` : ''}`}
                    onClick={() => setTickIndex(bundle.ticks.indexOf(t))}
                  >
                    {t.tick}
                  </button>
                )
              })}
            </div>
            <p className="fu-key muted" aria-hidden>
              <span className="fu-cell legal">t</span> legal <span className="fu-cell picked">t</span> picked{' '}
              <span className="fu-cell bonus">t</span> its strategy&apos;s bonus{' '}
              <span className="fu-cell bonus chose-bonus">t</span> a bonus action was chosen
            </p>
            <p className="dc-note">
              {f.legal.length === 0
                ? `Never legal: on every tick after it joined it ${f.pruned.map((r) => prunedReasonText(r.reason, action)).join(' or ')}, so the arbiter never saw it.`
                : `Legal on ticks ${tickRange(f.legal)}; ${f.picked.length === 0 ? 'the arbiter never picked it' : `picked on ${tickRange(f.picked)}`}.`}
            </p>
            {f.strategy && (
              <p className="dc-note fu-steering">
                {f.adopted.length === 0 ? (
                  `Its strategy, ${strategyName(f.strategy)}, joined the archive but steering never adopted it.`
                ) : (
                  <>
                    Steering adopted its strategy, {strategyName(f.strategy)}, after tick {f.adopted[0]} and kept it
                    through tick {f.adopted[f.adopted.length - 1]}. Steering decides after the action, so on ticks{' '}
                    {tickRange(f.bonus.map((b) => b.tick))} the arbiter added +{STRATEGY_BONUS} to the legal actions of
                    its sequence ({sequence.map(prettyId).join(', ')}):{' '}
                    {bonusActions.length === 0 ? 'none was legal' : bonusActions.map(prettyId).join(' and ')}.{' '}
                    {chosenWithBonus.length === 0
                      ? 'None of them was chosen.'
                      : `${chosenWithBonus.length === 1 ? 'It was' : 'They were'} chosen on ${chosenWithBonus.length} of those ${f.bonus.length} ticks (${tickRange(chosenWithBonus.map((b) => b.tick))}).`}{' '}
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => openHierarchyAt(bundle.ticks, f.adopted[0] as number)}
                    >
                      See the switch in the hierarchy at tick {f.adopted[0]} →
                    </button>
                  </>
                )}
              </p>
            )}
          </section>
        )
      })}
      <p className="dc-note fu-verdict">{verdict(readings)}</p>
    </div>
  )
}
