import { useEffect, useMemo, useState } from 'react'
import { EvidenceText } from '../components/Evidence'
import { Panel } from '../components/Panel'
import { RelevanceChart } from '../components/RelevanceChart'
import { LEARNING } from '../content/learning'
import { ledgerPoints, paidSeries, topContexts, triedHere } from '../data/learning'
import { type EpisodeBundle, loadLedger } from '../data/loader'
import { SENSES, fmt, pct, sections, valuesAt, words } from '../data/readings'
import type { RelevanceLedger, TickTrace } from '../schema/bundle'
import { useApp } from '../store'

/** The other recordings' ledgers, fetched once per recording list. */
function useLedgers(names: string[]): Array<{ name: string; ledger: RelevanceLedger | null }> {
  const [ledgers, setLedgers] = useState<Array<{ name: string; ledger: RelevanceLedger | null }>>([])
  const key = names.join('|')
  useEffect(() => {
    let alive = true
    void Promise.all(
      key
        .split('|')
        .filter(Boolean)
        .map(async (name) => ({ name, ledger: await loadLedger(name) })),
    ).then((loaded) => alive && setLedgers(loaded))
    return () => {
      alive = false
    }
  }, [key])
  return ledgers
}

export function Learning({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const index = useApp((s) => s.index)
  const others = useLedgers((index?.episodes ?? []).map((e) => e.name).filter((n) => n !== bundle.name))
  const points = useMemo(() => ledgerPoints(bundle, others), [bundle, others])
  const series = useMemo(() => paidSeries(points), [points])
  return (
    <main className="screen learning" aria-label="Learning">
      <header className="screen-head">
        <h2>{LEARNING.title}</h2>
        <p>{LEARNING.intro}</p>
      </header>
      <Panel id="relevance-episodes">
        {points.length === 0 ? (
          <p className="muted small">{LEARNING.chart.none}</p>
        ) : (
          <>
            <RelevanceChart series={series} />
            <details className="chart-table">
              <summary>{LEARNING.chart.tableTitle}</summary>
              <div className="table-wrap">
                <table className="data-table" data-testid="relevance-table">
                  <thead>
                    <tr>
                      {LEARNING.chart.columns.map((c) => (
                        <th key={c} scope="col">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {points.flatMap((p) =>
                      SENSES.map((s) => {
                        const c = p.totals[s]
                        return (
                          <tr
                            key={`${p.episodes}-${s}`}
                            className={p.current ? 'here' : undefined}
                            data-episodes={p.episodes}
                            data-sense={s}
                          >
                            <td>
                              {p.current
                                ? `${LEARNING.chart.current}, ${p.label.replace(' this episode', '')}`
                                : p.label}
                            </td>
                            <td className="num">{p.episodes}</td>
                            <td>
                              <span className={`dot sense-${s}`} aria-hidden /> {s}
                            </td>
                            <td className="num">{c?.spoke ?? 0}</td>
                            <td className="num">{c?.followed ?? 0}</td>
                            <td className="num">
                              {c?.followed_paid ?? 0}{' '}
                              <span className="muted">({pct(c?.followed ? c.followed_paid / c.followed : null)})</span>
                            </td>
                          </tr>
                        )
                      }),
                    )}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        )}
      </Panel>
      <div className="learning-grid">
        <Panel id="values">
          <Values bundle={bundle} tick={tick} />
        </Panel>
        <Panel id="trust">
          <Trust bundle={bundle} tick={tick} />
        </Panel>
      </div>
    </main>
  )
}

function Values({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const values = valuesAt(tick)
  if (!values.instance) return <p className="muted small">{LEARNING.values.none}</p>
  const holder = tick.instances[values.instance]
  const section = holder ? sections(holder.evidence).find((s) => s.channel === 'values') : undefined
  if (values.rows.length === 0) {
    return (
      <>
        <p className="small">
          {bundle.meta.value_networks === 'none'
            ? LEARNING.values.noNetworks
            : LEARNING.values.shownTo(values.instance)}
        </p>
        {section && <EvidenceText text={`[values]\n${section.body}`} name={values.instance} testId="values-text" />}
      </>
    )
  }
  const networks = [...new Set(values.rows.flatMap((r) => Object.keys(r.predictions)))]
  return (
    <div className="values">
      <p className="small">{LEARNING.values.shownTo(values.instance)}</p>
      <p className="small muted">{values.header}</p>
      <div className="table-wrap">
        <table className="data-table" data-testid="values-table">
          <thead>
            <tr>
              <th scope="col">{LEARNING.values.action}</th>
              {networks.map((n) => (
                <th key={n} scope="col">
                  <span className={`dot sense-${n}`} aria-hidden /> {n}
                </th>
              ))}
              <th scope="col">{LEARNING.values.tried}</th>
            </tr>
          </thead>
          <tbody>
            {values.rows.map((r) => (
              <tr
                key={r.action}
                className={r.action === tick.executed_action ? 'here' : undefined}
                data-action={r.action}
              >
                <th scope="row">
                  {words(r.action)}
                  {r.action === tick.executed_action && (
                    <span className="muted small"> · {LEARNING.values.executed}</span>
                  )}
                </th>
                {networks.map((n) => {
                  const v = r.predictions[n]
                  return (
                    <td key={n} className="num">
                      {v === undefined ? '–' : `${v >= 0 ? '+' : ''}${fmt(v)}`}
                    </td>
                  )
                })}
                <td className="num">{r.tried ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {section && (
        <details className="saw">
          <summary>The channel, verbatim</summary>
          <EvidenceText text={`[values]\n${section.body}`} name={values.instance} testId="values-text" />
        </details>
      )}
    </div>
  )
}

function Trust({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const cp = bundle.meta.checkpoint
  const here = triedHere(bundle.trust, tick)
  const top = topContexts(bundle.trust, tick.context_signature)
  return (
    <div className="trust">
      {cp && <p className="small">{LEARNING.trust.checkpoint(cp.episodes, cp.transitions_seen, cp.file)}</p>}
      {cp && <p className="small muted">{LEARNING.trust.share(fmt(cp.network_share))}</p>}
      {!here ? (
        <p className="muted small">{LEARNING.trust.none}</p>
      ) : (
        <>
          <p className="chips-label">
            {LEARNING.trust.here}: <span className="mono">{tick.context_signature}</span>,{' '}
            {LEARNING.trust.seen(here.seen)}
          </p>
          <div className="table-wrap">
            <table className="data-table" data-testid="tried-table">
              <thead>
                <tr>
                  <th scope="col">{LEARNING.trust.columns[0]}</th>
                  <th scope="col">{LEARNING.trust.columns[1]}</th>
                  <th scope="col">n / (n + {bundle.trust?.trust_count ?? 25})</th>
                </tr>
              </thead>
              <tbody>
                {here.rows.map((r) => (
                  <tr key={r.action} className={r.action === tick.executed_action ? 'here' : undefined}>
                    <th scope="row">{words(r.action)}</th>
                    <td className="num">{r.tried}</td>
                    <td className="num">{fmt(r.familiarity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="chips-label">{LEARNING.trust.top}</p>
          <ol className="contexts small">
            {top.map((c) => (
              <li key={c.signature} className={c.here ? 'here' : undefined}>
                <span className="mono">{c.signature}</span> <span className="muted">{c.n}</span>
                {c.here ? ' ◀' : ''}
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  )
}
