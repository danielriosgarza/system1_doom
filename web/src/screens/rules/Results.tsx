import { useMemo } from 'react'
import { Panel } from '../../components/Panel'
import { BENCHMARK, RESULTS, WRITTEN } from '../../content/rules/words'
import { pct } from '../../data/readings'
import { type BuildEntry, type RulesBundle, ROOT, readBuild, ruleUses, skillIds } from '../../data/rules'
import { openRule } from '../../store'

/** Which seeds a pass played: training or held out, and their range, from the record. */
function seedsWords(e: Extract<BuildEntry, { kind: 'pass' | 'held-out' }>): string {
  const kind = e.kind === 'pass' ? RESULTS.training : RESULTS.heldOut
  const seeds = e.games.map((g) => g.seed)
  const range =
    seeds.length > 0
      ? RESULTS.seedRange(Math.min(...seeds), Math.max(...seeds))
      : e.kind === 'held-out' && e.seeds
        ? e.seeds.replace('-', ' to ')
        : ''
  return range ? `${kind}, ${range}` : kind
}

/** How well the tree plays: seeds cleared as rules were added, the benchmark, and which rules decided here. */
export function Results({ bundle }: { bundle: RulesBundle }) {
  const passes = useMemo(
    () => readBuild(bundle.build).filter((e) => e.kind === 'pass' || e.kind === 'held-out'),
    [bundle],
  )
  const uses = useMemo(() => ruleUses(bundle), [bundle])
  const skills = useMemo(() => skillIds(bundle.tree), [bundle])
  const benchmark = BENCHMARK[bundle.meta.tree]
  const n = bundle.decisions.length
  return (
    <main className="screen results" aria-label="Results">
      <header className="screen-head">
        <h2>{RESULTS.title}</h2>
        <p>{RESULTS.intro}</p>
      </header>
      <div className="results-grid">
        <Panel id="rt-passes">
          {passes.length === 0 ? (
            <p className="muted small">{WRITTEN.none}</p>
          ) : (
            <div className="table-wrap">
              <table className="data-table" data-testid="passes">
                <thead>
                  <tr>
                    {RESULTS.passColumns.map((c) => (
                      <th key={c} scope="col">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {passes.map((e, i) =>
                    e.kind === 'pass' || e.kind === 'held-out' ? (
                      <tr key={i} data-kind={e.kind}>
                        <th scope="row">
                          {e.label ?? (e.kind === 'pass' ? WRITTEN.pass(e.round, e.again) : WRITTEN.heldOut)}
                        </th>
                        <td className="seeds-cell">{seedsWords(e)}</td>
                        <td className="cleared-cell">
                          <span className="cleared-bar" aria-hidden>
                            <span style={{ width: `${(e.cleared / Math.max(1, e.of)) * 100}%` }} />
                          </span>
                          {WRITTEN.cleared(e.cleared, e.of)}
                        </td>
                      </tr>
                    ) : null,
                  )}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        {benchmark && (
          <Panel id="rt-benchmark">
            <div className="table-wrap">
              <table className="data-table" data-testid="benchmark">
                <thead>
                  <tr>
                    {RESULTS.benchmarkColumns.map((c, i) => (
                      <th key={c} scope="col">
                        {i === 1 ? `${c}, ${bundle.meta.tree}` : c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {benchmark.map((row) => (
                    <tr key={row.seeds}>
                      <th scope="row">{row.seeds}</th>
                      <td>{row.tree}</td>
                      <td className={row.senses ? '' : 'faint'}>{row.senses ?? 'not played'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="faint small">{RESULTS.benchmarkSource}</p>
          </Panel>
        )}
      </div>
      <Panel id="rt-uses" aside={<span className="panel-aside">{RESULTS.usesTotal(n)}</span>}>
        <div className="table-wrap">
          <table className="data-table rule-uses" data-testid="rule-uses">
            <thead>
              <tr>
                {RESULTS.usesColumns.map((c) => (
                  <th key={c} scope="col">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {uses.map((u) => {
                const node = bundle.tree.nodes[u.id]
                const condition =
                  u.id === ROOT ? RESULTS.root : skills.includes(u.id) ? RESULTS.skill(u.id) : (node?.condition ?? '')
                return (
                  <tr key={u.id} data-rule={u.id}>
                    <th scope="row">
                      <button type="button" className="link mono" onClick={() => openRule(u.id)}>
                        {u.id}
                      </button>
                    </th>
                    <td className="context">{condition}</td>
                    <td className="num uses-cell">
                      <span className="cleared-bar" aria-hidden>
                        <span style={{ width: `${(u.reached / Math.max(1, n)) * 100}%` }} />
                      </span>
                      {u.reached}
                    </td>
                    <td className="num" title={pct(u.ended / Math.max(1, n))}>
                      {u.ended}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel id="rt-totals">
        <dl className="facts-list" data-testid="totals">
          {RESULTS.totalsRows(bundle.meta).map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </Panel>
    </main>
  )
}
