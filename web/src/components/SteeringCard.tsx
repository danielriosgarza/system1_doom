import type { TickTrace } from '../schema/bundle'
import {
  ARCHIVE_ALPHA,
  ARCHIVE_SLOTS,
  FAILED_STEP_DAMAGE,
  STRATEGY_BONUS,
  evictionScore,
  fmt,
  pct,
  prettyId,
  strategyName,
} from '../data/derive'
import { setState, useApp } from '../store'

/** The strategy archive behind the steering level: the active entry, the slots, and the bonus. */
export function SteeringCard({ tick }: { tick: TickTrace }) {
  const depth = useApp((s) => s.depth)
  const hovered = useApp((s) => s.hoveredAction)
  const steering = tick.steering
  if (!steering) return <p className="empty-note">This trace has no steering detail.</p>
  const entries = steering.entries ?? []
  const active = entries.find((e) => e.strategy_id === steering.active_before)
  const outcome = tick.outcome
  const failed = (outcome?.damage_taken ?? 0) > FAILED_STEP_DAMAGE || !!outcome?.died
  const bonus = tick.arbiter?.component_breakdown ?? {}
  const slots = Array.from({ length: ARCHIVE_SLOTS }, (_, i) => entries[i] ?? null)
  return (
    <div className="steering-card">
      {active && (
        <div className="steering-active">
          <strong>{strategyName(active.strategy_id)}</strong> was active this tick and counted a{' '}
          {failed ? 'failure' : 'success'}. Its running reward is now {fmt(active.observed_reward, 2)} and its success
          rate {pct(active.success_rate)}, each updated as {fmt(1 - ARCHIVE_ALPHA, 1)} × old + {fmt(ARCHIVE_ALPHA, 1)} ×
          this outcome.
          {steering.active_before !== steering.active_after && (
            <> From the next tick, {strategyName(steering.active_after)} takes over.</>
          )}
        </div>
      )}
      {active && (
        <div className="steering-bonus">
          <span className="dc-key">+{STRATEGY_BONUS} in the arbiter</span>
          {active.action_sequence.map((a, i) => {
            const legal = tick.available_actions.includes(a)
            return (
              <span
                key={`${a}-${i}`}
                className={`chip ${legal ? 'legal' : 'pruned'} ${a === tick.selected_action ? 'selected' : ''} ${a === hovered ? 'hovered' : ''}`}
                title={
                  legal
                    ? `received ${fmt(bonus[a]?.strategy_bonus ?? 0, 2)} in this tick's score`
                    : 'not on the menu this tick, so no bonus to receive'
                }
                onMouseEnter={() => legal && setState({ hoveredAction: a })}
                onMouseLeave={() => setState({ hoveredAction: null })}
              >
                {prettyId(a)}
              </span>
            )
          })}
        </div>
      )}
      <div className="slots" aria-label={`The strategy archive: ${entries.length} of ${ARCHIVE_SLOTS} slots filled`}>
        {slots.map((entry, i) =>
          entry ? (
            <div
              key={entry.strategy_id}
              className={`slot ${entry.strategy_id === steering.active_before ? 'active' : ''} ${entry.strategy_id === steering.active_after && steering.active_after !== steering.active_before ? 'next' : ''}`}
              title={`${entry.action_sequence.map(prettyId).join(' → ')}`}
            >
              <span className="slot-name">{strategyName(entry.strategy_id)}</span>
              <span className="slot-stats">
                used {entry.usage_count} · {pct(entry.success_rate)}
              </span>
              {depth === 'formula' && (
                <span className="slot-stats mono" title="eviction score: reward + 5 × success rate">
                  keep {fmt(evictionScore(entry), 2)}
                </span>
              )}
            </div>
          ) : (
            <div key={`empty-${i}`} className="slot empty" aria-hidden />
          ),
        )}
      </div>
      <p className="slots-note">
        {entries.length} of {ARCHIVE_SLOTS} slots filled. The outlined slot is the strategy active this tick
        {steering.active_before !== steering.active_after ? '; the dashed one takes over next tick' : ''}. When all{' '}
        {ARCHIVE_SLOTS} are full, a new strategy evicts the inactive one with the lowest reward + 5 × success rate.
      </p>
    </div>
  )
}
