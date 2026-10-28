import { Panel } from '../../components/Panel'
import { LOCAL_TRAINED } from '../../content/local/words'

/** How Laya was trained: Kev plays new games, every question becomes an example, Laya learns Kev's answers. */
export function Trained() {
  return (
    <main className="screen trained" aria-label="How Laya was trained">
      <header className="screen-head">
        <h2>{LOCAL_TRAINED.title}</h2>
        <p>{LOCAL_TRAINED.intro}</p>
      </header>
      <Panel id="lm-workflow">
        <ol className="workflow" data-testid="workflow">
          {LOCAL_TRAINED.steps.map((s, i) => (
            <li key={s.title} data-step={i + 1}>
              <h3>{s.title}</h3>
              <p className="small">{s.text}</p>
            </li>
          ))}
        </ol>
      </Panel>
      <Panel id="lm-facts">
        <dl className="facts-list" data-testid="training-facts">
          {LOCAL_TRAINED.facts.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </Panel>
      <Panel id="lm-thor">
        <p className="small">{LOCAL_TRAINED.thorLead}</p>
        <div className="table-wrap">
          <table className="data-table" data-testid="thor-table">
            <thead>
              <tr>
                {LOCAL_TRAINED.thorColumns.map((c) => (
                  <th key={c} scope="col">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {LOCAL_TRAINED.thorRows.map(([setup, fresh, again, weights]) => (
                <tr key={setup}>
                  <th scope="row">{setup}</th>
                  <td className="num">{fresh}</td>
                  <td className="num">{again}</td>
                  <td className="num">{weights}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </main>
  )
}
