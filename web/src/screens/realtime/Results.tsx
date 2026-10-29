import { Panel } from '../../components/Panel'
import { REALTIME_RESULTS } from '../../content/realtime/words'
import type { RulesBundle } from '../../data/rules'

/** A small table of rows of words, with the first column as row headings. */
function Table({ columns, rows, testId }: { columns: string[]; rows: string[][]; testId: string }) {
  return (
    <div className="table-wrap">
      <table className="data-table" data-testid={testId}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([head, ...cells]) => (
            <tr key={head}>
              <th scope="row">{head}</th>
              {cells.map((c, i) => (
                <td key={i} className={i === cells.length - 1 ? 'num' : undefined}>
                  {c || '–'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** How well Laya plays in real time: the path from 9 to 80, the loops, Laya retrained, a late answer, this recording. */
export function RealtimeResults({ bundle }: { bundle: RulesBundle }) {
  const R = REALTIME_RESULTS
  return (
    <main className="screen results realtime-results" aria-label="Results">
      <header className="screen-head">
        <h2>{R.title}</h2>
        <p>{R.intro}</p>
      </header>
      <Panel id="rtm-path">
        <Table columns={R.pathColumns} rows={R.path} testId="realtime-path" />
        <p className="faint small">{R.pathSource}</p>
      </Panel>
      <Panel id="rtm-loops">
        <Table columns={R.loopsColumns} rows={R.loops} testId="realtime-loops" />
        <p className="faint small">{R.loopsSource}</p>
      </Panel>
      <Panel id="rtm-training">
        <Table columns={R.trainingColumns} rows={R.training} testId="realtime-training" />
      </Panel>
      <Panel id="rtm-lag">
        <Table columns={R.lagColumns} rows={R.lag} testId="realtime-lag" />
        <p className="faint small">{R.lagSource}</p>
      </Panel>
      <Panel id="rtm-totals">
        <dl className="facts-list" data-testid="totals">
          {R.totalsRows(bundle.meta).map(([k, v]) => (
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
