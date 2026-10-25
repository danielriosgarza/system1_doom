import { WATCH, brainOf, resultWords } from '../content/watch'
import { defaultEpisode } from '../data/loader'
import { openDrawer, openEpisode, openRecording, useApp } from '../store'

/** The shipped recordings, the featured one first, in plain words; a card plays its recording from the start. */
export function RecordingCards() {
  const index = useApp((s) => s.index)
  const bundle = useApp((s) => s.bundle)
  const episodes = index?.episodes ?? []
  if (episodes.length === 0) return null
  const featured = defaultEpisode(index)
  const ordered = [...episodes.filter((e) => e.name === featured), ...episodes.filter((e) => e.name !== featured)]
  const howMade = async (name: string) => {
    if (bundle?.name !== name) await openEpisode(name, null)
    openDrawer('recording')
  }
  return (
    <section className="recordings" aria-labelledby="recordings-title">
      <header className="recordings-head">
        <h3 id="recordings-title">{WATCH.cardsTitle}</h3>
        <p>{WATCH.cardsNote}</p>
      </header>
      <ul className="recording-cards">
        {ordered.map((entry) => {
          const brain = brainOf(entry, bundle?.meta ?? null)
          const open = bundle?.name === entry.name
          return (
            <li
              key={entry.name}
              className={`recording-card ${open ? 'open' : ''}`}
              data-recording={entry.name}
              aria-current={open ? 'true' : undefined}
            >
              <button type="button" className="recording-main" onClick={() => void openRecording(entry.name)}>
                {open && <span className="recording-now">{WATCH.nowShowing}</span>}
                <span className="recording-brain">{brain.name}</span>
                <span className="recording-gloss">{brain.gloss}</span>
                <span className="recording-result">
                  run {entry.seed} · {resultWords(entry)}
                </span>
              </button>
              <button
                type="button"
                className="link-button recording-made"
                data-opens="recording"
                aria-haspopup="dialog"
                onClick={() => void howMade(entry.name)}
              >
                {WATCH.made}
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
