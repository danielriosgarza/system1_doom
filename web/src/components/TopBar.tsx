import { BEATS, STORY } from '../content/explainers'
import { fmt, gameSeconds, pct } from '../data/derive'
import { openEpisode, setState, useApp } from '../store'

export function TopBar() {
  const index = useApp((s) => s.index)
  const bundle = useApp((s) => s.bundle)
  const tickIndex = useApp((s) => s.tickIndex)
  const depth = useApp((s) => s.depth)
  const theme = useApp((s) => s.theme)
  const tick = bundle?.ticks[tickIndex]
  return (
    <header className="topbar">
      <div className="brand">
        <h1>System 1 Doom</h1>
        <span>one decision at a time</span>
      </div>
      <label className="control">
        Episode
        <select
          value={bundle?.name ?? ''}
          onChange={(e) => void openEpisode(e.target.value)}
          aria-label="Recorded episode"
        >
          {index?.episodes.map((e) => (
            <option key={e.name} value={e.name} title={e.title}>
              {e.scenario.replace('.cfg', '').replaceAll('_', ' ')} ·{' '}
              {e.model === 'heuristics' ? 'heuristics only' : 'learned networks'} · seed {e.seed} ·{' '}
              {e.cleared ? 'cleared' : e.died ? 'died' : 'survived'}
            </option>
          ))}
        </select>
      </label>
      {bundle && tick && (
        <span className="control tick-counter" aria-live="polite">
          Tick {tick.tick} / {bundle.meta.last_tick} · {fmt(gameSeconds(tick.tick), 1)} s of play
        </span>
      )}
      <span className="control">
        Depth
        <span className="segmented" role="group" aria-label="Explanation depth">
          <button type="button" aria-pressed={depth === 'plain'} onClick={() => setState({ depth: 'plain' })}>
            Plain
          </button>
          <button type="button" aria-pressed={depth === 'formula'} onClick={() => setState({ depth: 'formula' })}>
            Formula
          </button>
        </span>
      </span>
      <button
        type="button"
        className="icon-button"
        onClick={() => setState({ theme: theme === 'dark' ? 'light' : 'dark' })}
        aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      >
        {theme === 'dark' ? 'Light' : 'Dark'}
      </button>
    </header>
  )
}

function flash(panel: string) {
  const el = document.getElementById(`panel-${panel}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  el.classList.remove('flash')
  void el.offsetWidth
  el.classList.add('flash')
}

export function Story() {
  const bundle = useApp((s) => s.bundle)
  const meta = bundle?.meta
  const checkpoint = meta?.checkpoint
  return (
    <section className="story" aria-label="What this page shows">
      <p>
        <strong>{STORY.sentence}</strong> {STORY.invariant}
      </p>
      {meta && (
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
            {meta.result.cleared ? 'cleared' : meta.result.died ? 'died' : 'survived'} after {meta.tick_count} ticks,
            reward {fmt(meta.result.reward, 0)}
          </span>
        </div>
      )}
      <p className="howto">{STORY.howto}</p>
      <ol className="beats" aria-label="The six steps of one tick">
        {BEATS.map((beat, i) => (
          <li key={beat.n} style={{ display: 'contents' }}>
            <a
              href={`#panel-${beat.panel}`}
              onClick={(e) => {
                e.preventDefault()
                flash(beat.panel)
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
    </section>
  )
}
