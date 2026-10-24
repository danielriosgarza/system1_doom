import { fmt, gameSeconds } from '../data/derive'
import { SCREENS, openEpisode, setScreen, setState, startTour, useApp } from '../store'

export function TopBar() {
  const index = useApp((s) => s.index)
  const bundle = useApp((s) => s.bundle)
  const tickIndex = useApp((s) => s.tickIndex)
  const screen = useApp((s) => s.screen)
  const depth = useApp((s) => s.depth)
  const theme = useApp((s) => s.theme)
  const tour = useApp((s) => s.tour)
  const tick = bundle?.ticks[tickIndex]
  return (
    <header className="topbar">
      <div className="brand">
        <h1>System 1 Doom</h1>
        <span>one decision at a time</span>
      </div>
      <nav className="screens" aria-label="Screens">
        {SCREENS.map((s) => (
          <button
            key={s.id}
            type="button"
            aria-current={screen === s.id ? 'page' : undefined}
            onClick={() => setScreen(s.id)}
          >
            {s.label}
          </button>
        ))}
      </nav>
      <label className="control">
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
          Tick {tick.tick} / {bundle.meta.last_tick} · {fmt(gameSeconds(tick.tick), 1)} s
        </span>
      )}
      <button
        type="button"
        className="icon-button"
        onClick={startTour}
        disabled={!bundle || tour !== null}
        title="A six-step walk through one real tick"
      >
        Tour
      </button>
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
