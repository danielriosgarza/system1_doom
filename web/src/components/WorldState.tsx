import type { TickTrace } from '../schema/bundle'
import { contextBuckets, fmt } from '../data/derive'
import { useApp } from '../store'

function Vital({ k, v, meter, color }: { k: string; v: string; meter?: number; color?: string }) {
  return (
    <div className="vital">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      {meter !== undefined && (
        <div className="meter">
          <div style={{ width: `${Math.max(0, Math.min(1, meter)) * 100}%`, background: color ?? 'var(--n2)' }} />
        </div>
      )}
    </div>
  )
}

export function WorldState({ tick }: { tick: TickTrace }) {
  const depth = useApp((s) => s.depth)
  const state = tick.state
  if (!state) return <p className="empty-note">This trace was recorded without a state snapshot.</p>
  const buckets = contextBuckets(tick.context_signature, state)
  const healthColor = state.health <= 30 ? 'var(--neg)' : state.health <= 65 ? 'var(--combat)' : 'var(--pos)'
  return (
    <>
      <div className="vitals">
        <Vital k="Health" v={fmt(state.health, 0)} meter={state.health / 100} color={healthColor} />
        <Vital k="Armor" v={fmt(state.armor, 0)} meter={state.armor / 100} color="var(--navigation)" />
        <Vital k="Ammo" v={String(state.ammo)} meter={state.ammo / 50} color="var(--combat)" />
        <Vital k="Weapon" v={state.weapon} />
        <Vital k="Moving" v={state.movement} />
        <Vital
          k="Recent fire"
          v={`${fmt(state.recent_incoming_damage ?? 0, 0)} in · ${fmt(state.recent_outgoing_damage ?? 0, 0)} out`}
        />
      </div>
      <div className="buckets" aria-label="Context signature buckets">
        {buckets.map((b) => (
          <div className="bucket" key={b.key}>
            <span className="name">{b.label}</span>
            <span className="opts">
              {b.options.map((o) => (
                <span key={o.value} className={`opt ${o.value === b.value ? 'on' : ''}`} title={o.rule}>
                  {o.value.replace('_', ' ')}
                  {depth === 'formula' && <span> ({o.rule})</span>}
                </span>
              ))}
            </span>
            <span className="because">{b.because}</span>
          </div>
        ))}
      </div>
      {depth === 'formula' && (
        <div className="signature mono" title="The context signature, the key every memory is filed under">
          {tick.context_signature}
        </div>
      )}
      <div className="recent">
        Position ({fmt(state.position.x ?? 0, 0)}, {fmt(state.position.y ?? 0, 0)}), facing{' '}
        {fmt(state.position.angle ?? 0, 0)}°.{' '}
        {(state.recent_actions ?? []).length > 0 && (
          <>
            Last steps pressed:{' '}
            {(state.recent_actions ?? [])
              .slice(-4)
              .map((a) => a.replaceAll('_', ' '))
              .join(', ')}
            .
          </>
        )}
      </div>
    </>
  )
}
