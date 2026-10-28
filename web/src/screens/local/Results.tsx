import { useMemo } from 'react'
import { Panel } from '../../components/Panel'
import { LOCAL_MODEL_NAMES, LOCAL_RESULTS } from '../../content/local/words'
import { type ModelQuestion, agreementWithPlayed, questionsAt } from '../../data/models'
import { pct } from '../../data/readings'
import { type RulesBundle, NONE, readStep } from '../../data/rules'
import type { RuleTreeDecision, WalkStep } from '../../schema/bundle'

/** The option the recording's model picked at a recorded question, or null when it has no answer there. */
function playedPick(bundle: RulesBundle, q: Pick<ModelQuestion, 'decision' | 'step'>): string | null {
  const decision = bundle.decisions.find((d) => d.decision === q.decision)
  const step = decision?.steps[q.step] as WalkStep | undefined
  return step ? (readStep(step).option ?? null) : null
}

/** An option in words: a rule's id, none, or a focus item's text. */
function optionWords(step: WalkStep | undefined, option: string): string {
  if (!step || option === NONE || step.kind === 'rule') return option
  return step.options?.[option] ?? option
}

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
                <td key={i} className="num">
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

/** How well Laya plays: the benchmark, the questions of these recordings, this decision by each model, this recording. */
export function LocalResults({ bundle, decision }: { bundle: RulesBundle; decision: RuleTreeDecision }) {
  const models = bundle.models ?? null
  const asked = useMemo(() => (models ? questionsAt(models, decision.decision) : []), [models, decision])
  const agreement = useMemo(
    () => (models ? agreementWithPlayed(models, (q) => playedPick(bundle, q)) : {}),
    [models, bundle],
  )
  return (
    <main className="screen results local-results" aria-label="Results">
      <header className="screen-head">
        <h2>{LOCAL_RESULTS.title}</h2>
        <p>{LOCAL_RESULTS.intro}</p>
      </header>
      <Panel id="lm-benchmark">
        <Table columns={LOCAL_RESULTS.benchmarkColumns} rows={LOCAL_RESULTS.benchmark} testId="local-benchmark" />
        <p className="faint small">{LOCAL_RESULTS.benchmarkSource}</p>
      </Panel>
      <Panel id="lm-questions">
        <Table columns={LOCAL_RESULTS.questionsColumns} rows={LOCAL_RESULTS.questions} testId="local-questions" />
        <p className="faint small">{LOCAL_RESULTS.questionsSource}</p>
      </Panel>
      <Panel id="lm-totals">
        <dl className="facts-list" data-testid="totals">
          {LOCAL_RESULTS.totalsRows(bundle.meta).map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </Panel>
      <Panel id="lm-decision">
        {!models ? (
          <p className="muted small">{LOCAL_RESULTS.decisionNone}</p>
        ) : (
          <>
            <p className="small">{LOCAL_RESULTS.decisionLead(asked.length)}</p>
            <div className="table-wrap">
              <table className="data-table model-picks" data-testid="decision-models">
                <thead>
                  <tr>
                    <th scope="col">{LOCAL_RESULTS.question}</th>
                    <th scope="col">{LOCAL_MODEL_NAMES.played}</th>
                    {models.models.map((m) => (
                      <th key={m} scope="col">
                        {LOCAL_MODEL_NAMES[m] ?? m}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {asked.map((q, k) => {
                    const step = decision.steps[q.step] as WalkStep | undefined
                    const played = playedPick(bundle, q)
                    const playedP = step?.answer?.probabilities?.[played ?? ''] ?? null
                    return (
                      <tr key={q.step} data-step={q.step}>
                        <th scope="row">
                          {k + 1}{' '}
                          <span className="faint">
                            {q.kind === 'focus' ? LOCAL_RESULTS.focusAt(q.node) : LOCAL_RESULTS.ruleAt(q.node)}
                          </span>
                        </th>
                        <td data-model="played">
                          {played ? optionWords(step, played) : '–'}
                          {playedP !== null && <span className="faint"> {pct(playedP)}</span>}
                        </td>
                        {models.models.map((m) => {
                          const pick = q.picks[m]
                          const differs = !!pick && played !== null && pick[0] !== played
                          return (
                            <td
                              key={m}
                              data-model={m}
                              className={differs ? 'differs' : ''}
                              title={differs ? LOCAL_RESULTS.differs : undefined}
                            >
                              {pick ? optionWords(step, pick[0]) : '–'}
                              {pick && <span className="faint"> {pct(pick[1])}</span>}
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="faint small" data-testid="models-agreement">
              {models.models
                .map(
                  (m) =>
                    `${LOCAL_MODEL_NAMES[m] ?? m}: ${LOCAL_RESULTS.agreement(agreement[m]?.same ?? 0, agreement[m]?.of ?? 0)}`,
                )
                .join('. ')}
              .
            </p>
          </>
        )}
      </Panel>
    </main>
  )
}
