import { WATCH, chainRows } from '../content/watch'
import type { EpisodeBundle } from '../data/loader'
import type { TickTrace } from '../schema/bundle'
import { openLevel } from '../store'

/**
 * The six levels of the decision chain at this decision, slowest at the top, each in plain words. A row pulses
 * when its choice differs from the decision before: the top rows rarely, the bottom ones nearly every time.
 */
export function ChainStrip({ bundle, tick, tickIndex }: { bundle: EpisodeBundle; tick: TickTrace; tickIndex: number }) {
  const prev = bundle.ticks[tickIndex - 1] ?? null
  const rows = chainRows(tick, prev, bundle.meta, bundle.proposals)
  return (
    <section className="chain-strip" aria-labelledby="chain-title">
      <header className="chain-head">
        <h3 id="chain-title">{WATCH.chainTitle}</h3>
        <p>{WATCH.chainNote}</p>
      </header>
      <ol className="chain-rows">
        {rows.map((row, i) => (
          <li key={row.id}>
            <button
              type="button"
              className={`chain-row ${row.idle ? 'idle' : ''}`}
              data-level={row.id}
              data-changed={row.changed ? 'true' : undefined}
              aria-label={`${row.name}: ${row.value}`}
              title={WATCH.rowTitle}
              onClick={() => openLevel(row.id)}
            >
              {/* Mounted afresh on each change, so the highlight runs again even on two changes in a row. */}
              {row.changed && <span key={tickIndex} className="chain-pulse" aria-hidden />}
              <span className="chain-num" aria-hidden>
                {i + 1}
              </span>
              <span className="chain-label">
                <span className="chain-name">{row.name}</span>
                <span className="chain-gloss">{row.gloss}</span>
              </span>
              <span className="chain-choice">
                <span className="chain-value" data-testid="chain-value">
                  {row.value}
                </span>
                <span className="chain-bar" title={row.shareLabel || undefined} aria-hidden>
                  {row.share !== null && <span style={{ width: `${Math.max(0, Math.min(1, row.share)) * 100}%` }} />}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  )
}
