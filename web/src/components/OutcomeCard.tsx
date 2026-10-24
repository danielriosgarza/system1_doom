import type { EpisodeMeta, TickTrace } from '../schema/bundle'
import { MODULES, exploration, fmt, prettyId } from '../data/derive'
import { useApp } from '../store'

function Field({ k, v, zero }: { k: string; v: string; zero: boolean }) {
  return (
    <div className={`vital ${zero ? 'zero' : ''}`}>
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  )
}

function pickedUp(health: number, armor: number, ammo: number): string {
  const parts = [
    health > 0 ? `+${fmt(health, 0)} health` : '',
    armor > 0 ? `+${fmt(armor, 0)} armor` : '',
    ammo > 0 ? `+${fmt(ammo, 0)} ammo` : '',
  ].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : 'nothing'
}

export function OutcomeCard({ tick, meta }: { tick: TickTrace; meta: EpisodeMeta }) {
  const depth = useApp((s) => s.depth)
  const o = tick.outcome
  if (!o) return <p className="empty-note">This trace was recorded without outcome detail.</p>
  const rewards = o.module_rewards ?? {}
  const maxAbs = Math.max(1, ...MODULES.map((m) => Math.abs(rewards[m] ?? 0)))
  const steering = tick.steering
  const active = steering?.entries?.find((e) => e.strategy_id === steering.active_before)
  const next = exploration(tick)
  const failed = (o.damage_taken ?? 0) > 8 || o.died
  const status = o.died ? 'died' : o.episode_finished ? 'episode over' : 'alive'
  return (
    <>
      <div className="outcome-grid">
        <Field k="Reward" v={fmt(o.reward ?? 0, 1)} zero={(o.reward ?? 0) === 0} />
        <Field k="Damage taken" v={fmt(o.damage_taken ?? 0, 0)} zero={(o.damage_taken ?? 0) === 0} />
        <Field
          k="Hits · kills"
          v={`${fmt(o.hits_delta ?? 0, 0)} · ${fmt(o.kills_delta ?? 0, 0)}`}
          zero={!(o.hits_delta || o.kills_delta)}
        />
        <Field
          k="Picked up"
          v={pickedUp(o.health_gain ?? 0, o.armor_gain ?? 0, o.ammo_gain ?? 0)}
          zero={!(o.health_gain || o.armor_gain || o.ammo_gain)}
        />
        <Field
          k="Moved"
          v={`${fmt(o.displacement ?? 0, 0)} u${o.new_cells ? ' · new ground' : ''}`}
          zero={(o.displacement ?? 0) === 0}
        />
        <Field k="After" v={`${fmt(o.health_after ?? 0, 0)} hp · ${status}`} zero={false} />
      </div>
      <div className="reward-rows" aria-label="The outcome split into one reward per module">
        {MODULES.map((m) => {
          const v = rewards[m] ?? 0
          const w = (Math.abs(v) / maxAbs) * 50
          return (
            <span key={m} style={{ display: 'contents' }}>
              <span style={{ color: `var(--${m})`, textTransform: 'capitalize' }}>{m}</span>
              <span className="diverge" style={{ ['--c' as string]: `var(--${m})` }}>
                <span className="mid" />
                <span className="fill" style={{ left: `${v >= 0 ? 50 : 50 - w}%`, width: `${w}%` }} />
              </span>
              <span className="num">{fmt(v, 2)}</span>
            </span>
          )
        })}
      </div>
      <ul className="filing" aria-label="Where this outcome is filed">
        <li>
          <span>
            <strong>Simulator cache:</strong>{' '}
            <span className="muted">
              one more real result for {prettyId(tick.selected_action)} in this situation, blended into future
              projections.
            </span>
          </span>
        </li>
        {active && (
          <li>
            <span>
              <strong>Strategy archive:</strong>{' '}
              <span className="muted">
                {prettyId(active.strategy_id)} counted a {failed ? 'failure' : 'success'}; its running reward is now{' '}
                {fmt(active.observed_reward, 2)} and success rate {fmt(active.success_rate, 2)}.
                {depth === 'formula' && ' (new = 0.7 × old + 0.3 × this outcome)'}
              </span>
            </span>
          </li>
        )}
        {steering && (
          <li>
            <span>
              <strong>Steering:</strong>{' '}
              <span className="muted">
                chose to {steering.choice.replaceAll('_', ' ')}
                {steering.active_before !== steering.active_after
                  ? `, switching to ${prettyId(steering.active_after)}`
                  : `; ${prettyId(steering.active_after)} stays active`}
                .
              </span>
            </span>
          </li>
        )}
        <li>
          <span>
            <strong>Exploration:</strong>{' '}
            <span className="muted">
              this situation has been seen{' '}
              {next.state_visitation_novelty !== undefined && next.state_visitation_novelty < 1
                ? 'before'
                : 'for the first time'}
              ; pressure for the next tick is {fmt(next.exploration_pressure ?? 0, 2)}.
            </span>
          </span>
        </li>
        <li>
          <span>
            <strong>Replay buffer:</strong>{' '}
            <span className="muted">
              {meta.brains.learned_networks
                ? 'during training this decision and its five rewards would be stored for the networks; this replay only reads them.'
                : 'no networks in this episode; during training this decision and its five rewards would be stored.'}
            </span>
          </span>
        </li>
      </ul>
    </>
  )
}
