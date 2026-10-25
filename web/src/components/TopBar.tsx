import { LIVE_COPY } from '../content/live'
import { fmt, gameSeconds } from '../data/derive'
import { type PickerEntry, mergedEpisodes } from '../data/live'
import type { BundleIndexEntry } from '../schema/bundle'
import { SCREENS, followLive, openDrawer, openEpisode, setScreen, setState, startTour, useApp } from '../store'

const scenarioWords = (scenario: string) => scenario.replace('.cfg', '').replaceAll('_', ' ')

/** How a recording is named in the picker. */
function recordingLabel(e: BundleIndexEntry): string {
  const brain = e.model === 'heuristics' ? 'heuristics only' : 'learned networks'
  return `${scenarioWords(e.scenario)} · ${brain} · seed ${e.seed} · ${e.cleared ? 'cleared' : e.died ? 'died' : 'survived'}`
}

function EpisodeOption({ item, scenario }: { item: PickerEntry; scenario: string }) {
  if (item.entry) {
    return (
      <option value={item.name} title={item.entry.title}>
        {recordingLabel(item.entry)}
      </option>
    )
  }
  return (
    <option value={item.name}>
      live · {scenarioWords(scenario)} · seed {item.seed} · tick {item.tick ?? 0}
    </option>
  )
}

/** The LIVE badge beside the tick counter while the open episode is live; it reads “ended” once it has. */
function LiveBadge() {
  const bundle = useApp((s) => s.bundle)
  const liveOpen = useApp((s) => s.liveOpen)
  const current = useApp((s) => s.live?.current ?? null)
  const following = useApp((s) => s.following)
  if (!bundle || liveOpen !== bundle.name) return null
  const ended = current !== bundle.name
  return (
    <span className="live-status" data-testid="live-status">
      <span
        className={`live-badge ${ended ? 'ended' : ''}`}
        data-state={ended ? 'ended' : 'live'}
        title={ended ? LIVE_COPY.endedTitle : undefined}
      >
        {!ended && <span className="live-dot" aria-hidden />}
        {ended ? LIVE_COPY.ended : LIVE_COPY.badge}
      </span>
      {!ended &&
        (following ? (
          <span className="live-following muted">{LIVE_COPY.following}</span>
        ) : (
          <button type="button" className="icon-button live-follow" onClick={followLive} title={LIVE_COPY.followTitle}>
            {LIVE_COPY.follow}
          </button>
        ))}
    </span>
  )
}

export function TopBar() {
  const index = useApp((s) => s.index)
  const bundle = useApp((s) => s.bundle)
  const tickIndex = useApp((s) => s.tickIndex)
  const screen = useApp((s) => s.screen)
  const depth = useApp((s) => s.depth)
  const theme = useApp((s) => s.theme)
  const tour = useApp((s) => s.tour)
  const live = useApp((s) => s.live)
  const following = useApp((s) => s.following)
  const liveOpen = useApp((s) => s.liveOpen)
  const tick = bundle?.ticks[tickIndex]
  const items = mergedEpisodes(index, live)
  const liveItems = items.filter((e) => e.live !== null)
  const recordings = items.filter((e) => e.live === null)
  const pick = (name: string) => {
    if (name === live?.current) followLive()
    else void openEpisode(name)
  }
  return (
    <header className={`topbar ${bundle && liveOpen === bundle.name ? 'is-live' : ''}`}>
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
        <select value={bundle?.name ?? ''} onChange={(e) => pick(e.target.value)} aria-label="Recorded episode">
          {liveItems.length > 0 ? (
            <>
              <optgroup label={LIVE_COPY.pickerGroup}>
                {liveItems.map((e) => (
                  <EpisodeOption key={e.name} item={e} scenario={live?.config.scenario ?? ''} />
                ))}
              </optgroup>
              {recordings.length > 0 && (
                <optgroup label={LIVE_COPY.recordingsGroup}>
                  {recordings.map((e) => (
                    <EpisodeOption key={e.name} item={e} scenario="" />
                  ))}
                </optgroup>
              )}
            </>
          ) : (
            recordings.map((e) => <EpisodeOption key={e.name} item={e} scenario="" />)
          )}
        </select>
      </label>
      <button
        type="button"
        className="icon-button glyph-button"
        data-opens="recording"
        aria-haspopup="dialog"
        aria-label="About this recording"
        title="About this recording (i)"
        onClick={() => openDrawer('recording')}
      >
        ⓘ
      </button>
      {bundle && tick && (
        // While following a live episode the count changes several times a second: too often to announce.
        <span className="control tick-counter" aria-live={following ? 'off' : 'polite'} data-testid="tick-counter">
          Tick {tick.tick}
          <span className="tick-last"> / {bundle.meta.last_tick}</span>
          <span className="tick-seconds"> · {fmt(gameSeconds(tick.tick), 1)} s</span>
        </span>
      )}
      <LiveBadge />
      <button
        type="button"
        className="icon-button"
        onClick={startTour}
        disabled={!bundle || tour !== null}
        title="A six-step walk through one real tick"
      >
        Tour
      </button>
      <button
        type="button"
        className="icon-button"
        data-opens="glossary"
        aria-haspopup="dialog"
        title="Every word the app uses: what it means, where to see it, where it lives in the code (g)"
        onClick={() => openDrawer('glossary')}
      >
        Glossary
      </button>
      <span className="control">
        <span className="control-label">Depth</span>
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
