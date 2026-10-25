import type { ReactNode } from 'react'
import { d1Sync, fmt, pct, stillPlaying, stoppedEarly } from '../data/derive'
import type { EpisodeMeta } from '../schema/bundle'

/** Which deciders were switched on for this recording. */
export function Brains({ meta, children }: { meta: EpisodeMeta; children?: ReactNode }) {
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
        <span className="dot" /> d1-ultra advice:{' '}
        {meta.brains.d1_ultra ? (d1Sync(meta) ? 'on, waited for every tick' : 'on, from a cache') : 'off'}
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
        {stillPlaying(meta) ? (
          <>
            playing now, {meta.tick_count} {meta.tick_count === 1 ? 'tick' : 'ticks'} so far
          </>
        ) : (
          <>
            {meta.result.cleared ? 'cleared' : meta.result.died ? 'died' : stoppedEarly(meta) ? 'stopped' : 'survived'}{' '}
            after {meta.tick_count} ticks, reward {fmt(meta.result.reward, 0)}
          </>
        )}
      </span>
      {children}
    </div>
  )
}
