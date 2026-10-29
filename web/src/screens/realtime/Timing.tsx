import { Panel } from '../../components/Panel'
import { linkTerms } from '../../components/Terms'
import { REALTIME_TIMING, ticsMs } from '../../content/realtime/words'
import type { RulesBundle } from '../../data/rules'
import type { RuleTreeDecision } from '../../schema/bundle'
import { setTickIndex } from '../../store'

const AROUND = 4 // decisions shown either side of the one showing

/** How it plays in real time: from a state to its action, the helper, the decisions around this one, this recording. */
export function Timing({ bundle, index }: { bundle: RulesBundle; decision: RuleTreeDecision; index: number }) {
  const T = REALTIME_TIMING
  const from = Math.max(0, index - AROUND)
  const near = bundle.decisions.slice(from, index + AROUND + 1)
  const seen = new Set<string>()
  return (
    <main className="screen timing" aria-label="How it plays in real time">
      <header className="screen-head">
        <h2>{T.title}</h2>
        <p>{linkTerms(T.intro, seen, 'realtime')}</p>
      </header>
      <Panel id="rtm-steps">
        <ol className="workflow" data-testid="timing-steps">
          {T.steps.map((s, i) => (
            <li key={s.title} data-step={i + 1}>
              <h3>{s.title}</h3>
              <p className="small">{linkTerms(s.text, seen, 'realtime')}</p>
            </li>
          ))}
        </ol>
      </Panel>
      <Panel id="rtm-helper">
        <ul className="principles" data-testid="helper-list">
          {T.helper.map((h) => (
            <li key={h.title}>
              <strong>{h.title}.</strong> {linkTerms(h.text, seen, 'realtime')}
            </li>
          ))}
        </ul>
      </Panel>
      <Panel id="rtm-around">
        <p className="small">{T.tableNote}</p>
        <div className="table-wrap">
          <table className="data-table" data-testid="timing-table">
            <thead>
              <tr>
                {T.tableColumns.map((c) => (
                  <th key={c} scope="col">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {near.map((d, k) => {
                const late = (d.start_tic ?? 0) - (d.observed_tic ?? 0)
                const at = from + k
                return (
                  <tr key={d.decision} aria-current={at === index ? 'true' : undefined} data-decision={d.decision}>
                    <th scope="row">
                      <button type="button" className="link-button" onClick={() => setTickIndex(at)}>
                        {d.decision}
                      </button>
                    </th>
                    <td className="num">tic {d.observed_tic ?? '–'}</td>
                    <td className="num">tic {d.start_tic ?? '–'}</td>
                    <td className="num">
                      {late} {late === 1 ? 'tic' : 'tics'} ({ticsMs(late)} ms)
                    </td>
                    <td className="num">{Math.round(d.walk_ms ?? 0)} ms</td>
                    <td>{d.target ?? '–'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel id="rtm-settings">
        <dl className="facts-list" data-testid="realtime-settings">
          {T.settingsRows(bundle.meta).map(([k, v]) => (
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
