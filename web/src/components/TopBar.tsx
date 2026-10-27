import { deciderName } from '../content/decider'
import { LIVE_COPY } from '../content/live'
import { rulesRecordingLabel } from '../content/rules/words'
import { recordingName, resultWords, scenarioWords } from '../content/watch'
import { type PickerEntry, mergedEpisodes } from '../data/live'
import type { BundleIndexEntry } from '../schema/bundle'
import {
  followLive,
  openEpisode,
  openRecording,
  openRulesEpisode,
  screensOf,
  setScreen,
  setState,
  useApp,
} from '../store'

/** How a recording is named in the picker, in the words Watch's cards use. */
function recordingLabel(e: BundleIndexEntry): string {
  const result = e.cleared ? 'cleared' : e.died ? 'died' : 'survived'
  const before = e.senses_choose_targets ? '' : ' · before the senses chose targets'
  return `${scenarioWords(e.scenario)} · ${recordingName(e).toLowerCase()} · ${result}${before}`
}

function EpisodeOption({ item, scenario }: { item: PickerEntry; scenario: string }) {
  if (item.entry) {
    return (
      <option value={item.name} title={`${item.entry.title}: ${resultWords(item.entry)}`}>
        {recordingLabel(item.entry)}
      </option>
    )
  }
  return (
    <option value={item.name}>
      live · {scenarioWords(scenario)} · seed {item.seed} · decision {(item.tick ?? 0) + 1}
    </option>
  )
}

/** The LIVE badge beside the episode picker while the open episode is live; it reads “ended” once it has. */
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

/** Four things on every screen: the name, the screens, the episode picker and the theme. */
export function TopBar() {
  const index = useApp((s) => s.index)
  const solution = useApp((s) => s.solution)
  const sensesBundle = useApp((s) => s.bundle)
  const rules = useApp((s) => s.rules)
  const bundle = solution === 'senses' ? sensesBundle : null
  const screen = useApp((s) => s.screen)
  const theme = useApp((s) => s.theme)
  const live = useApp((s) => s.live)
  const liveOpen = useApp((s) => s.liveOpen)
  const items = mergedEpisodes(index, live)
  const liveItems = items.filter((e) => e.live !== null)
  const recordings = items.filter((e) => e.live === null)
  // On Watch a recording picked here plays from the start, as a card does; elsewhere it opens at its first decision.
  const pick = (name: string) => {
    if (solution === 'rules') {
      if (screen === 'watch') void openRecording(name)
      else void openRulesEpisode(name)
    } else if (name === live?.current) followLive()
    else if (screen === 'watch') void openRecording(name)
    else void openEpisode(name)
  }
  return (
    <header className={`topbar ${bundle && liveOpen === bundle.name ? 'is-live' : ''}`}>
      <div className="brand">
        <h1>System 1 Doom</h1>
        <span>every decision made by {deciderName(solution === 'rules' ? 'jev' : bundle?.meta.decider)}</span>
      </div>
      <nav className="screens" aria-label="Screens">
        {screensOf(solution).map((s) => (
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
      {solution === 'senses' && <LiveBadge />}
      <label className="control">
        <select
          value={(solution === 'rules' ? rules?.name : bundle?.name) ?? ''}
          onChange={(e) => pick(e.target.value)}
          aria-label="Episode"
        >
          {solution === 'rules' ? (
            (index?.rules ?? []).map((e) => (
              <option key={e.name} value={e.name} title={e.title}>
                {rulesRecordingLabel(e)}
              </option>
            ))
          ) : liveItems.length > 0 ? (
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
        className="icon-button topbar-theme"
        onClick={() => setState({ theme: theme === 'dark' ? 'light' : 'dark' })}
        aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      >
        {theme === 'dark' ? 'Light' : 'Dark'}
      </button>
    </header>
  )
}
