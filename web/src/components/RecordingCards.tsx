import { WATCH, recordingName, resultWords, targetsWords, versionWords } from '../content/watch'
import { defaultEpisode } from '../data/loader'
import { openPanel, openRecording, useApp } from '../store'

/** The shipped recordings, the featured one first, in plain words; a card plays its recording from the start. */
export function RecordingCards() {
  const index = useApp((s) => s.index)
  const bundle = useApp((s) => s.bundle)
  const episodes = index?.episodes ?? []
  if (episodes.length === 0) return null
  const featured = defaultEpisode(index)
  const ordered = [...episodes.filter((e) => e.name === featured), ...episodes.filter((e) => e.name !== featured)]
  return (
    <section className="recordings" aria-labelledby="recordings-title">
      <header className="recordings-head">
        <h3 id="recordings-title">{WATCH.cardsTitle}</h3>
        <p>{WATCH.cardsNote}</p>
      </header>
      <ul className="recording-cards">
        {ordered.map((entry) => {
          const open = bundle?.name === entry.name
          const start = entry.configuration_start ?? 1
          return (
            <li
              key={entry.name}
              className={`recording-card ${open ? 'open' : ''}`}
              data-recording={entry.name}
              aria-current={open ? 'true' : undefined}
            >
              <button type="button" className="recording-main" onClick={() => void openRecording(entry.name)}>
                {open && <span className="recording-now">{WATCH.nowShowing}</span>}
                <span className="recording-name">{recordingName(entry)}</span>
                <span className="recording-gloss">
                  {versionWords(start, entry.configuration_end ?? start)} · value networks: {entry.value_networks}
                </span>
                <span
                  className="recording-gloss recording-targets"
                  data-targets={entry.senses_choose_targets ? 'senses' : 'motor'}
                >
                  {targetsWords(entry)}
                </span>
                <span className="recording-result">{resultWords(entry)}</span>
              </button>
              {open && (
                <button
                  type="button"
                  className="link-button recording-made"
                  onClick={() => openPanel('reference', 'provenance')}
                >
                  {WATCH.made}
                </button>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
