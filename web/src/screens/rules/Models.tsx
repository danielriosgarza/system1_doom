import { useMemo } from 'react'
import { Panel } from '../../components/Panel'
import { MODELS, MODEL_NAMES, MODEL_ROWS, THOR_ROWS } from '../../content/rules/models'
import { pct } from '../../data/readings'
import { type ModelQuestion, agreementWithJev, questionsAt } from '../../data/models'
import { type RulesBundle, NONE, readStep } from '../../data/rules'
import type { RuleTreeDecision, WalkStep } from '../../schema/bundle'

/** The option Jev picked at a recorded question, or null when it has no answer there. */
function jevPick(bundle: RulesBundle, q: Pick<ModelQuestion, 'decision' | 'step'>): string | null {
  const decision = bundle.decisions.find((d) => d.decision === q.decision)
  const step = decision?.steps[q.step] as WalkStep | undefined
  return step ? (readStep(step).option ?? null) : null
}

/** An option in words: a rule's id, none, or a focus item's text. */
function optionWords(step: WalkStep | undefined, option: string): string {
  if (!step || option === NONE || step.kind === 'rule') return option
  return step.options?.[option] ?? option
}

/** Answering without Jev: how Laya was trained on Kev's answers, how every model did, and this decision by each. */
export function Models({ bundle, decision }: { bundle: RulesBundle; decision: RuleTreeDecision }) {
  const models = bundle.models ?? null
  const asked = useMemo(() => (models ? questionsAt(models, decision.decision) : []), [models, decision])
  const agreement = useMemo(() => (models ? agreementWithJev(models, (q) => jevPick(bundle, q)) : {}), [models, bundle])
  return (
    <main className="screen models" aria-label="Local models">
      <header className="screen-head">
        <h2>{MODELS.title}</h2>
        <p>{MODELS.intro}</p>
      </header>
      <Panel id="rt-workflow">
        <ol className="workflow" data-testid="workflow">
          {MODELS.workflow.map((s, i) => (
            <li key={s.title} data-step={i + 1}>
              <h3>{s.title}</h3>
              <p className="small">{s.text}</p>
            </li>
          ))}
        </ol>
      </Panel>
      <Panel id="rt-models">
        <div className="table-wrap">
          <table className="data-table" data-testid="models-table">
            <thead>
              <tr>
                {MODELS.columns.map((c) => (
                  <th key={c} scope="col">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MODEL_ROWS.map((r) => (
                <tr key={r.id} data-model={r.id}>
                  <th scope="row">{MODEL_NAMES[r.id] ?? r.id}</th>
                  <td>{r.where}</td>
                  <td>{r.trained}</td>
                  <td className="num">{r.settled}</td>
                  <td className="num">{r.sameAsJev || '–'}</td>
                  <td className="num">{r.cleared}</td>
                  <td className="num">{r.time}</td>
                  <td className="num">{r.cost}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="faint small">{MODELS.modelsSource}</p>
      </Panel>
      <Panel id="rt-decision-models">
        {!models ? (
          <p className="muted small">{MODELS.decisionNone}</p>
        ) : (
          <>
            <p className="small">{MODELS.decisionLead(asked.length)}</p>
            <div className="table-wrap">
              <table className="data-table model-picks" data-testid="decision-models">
                <thead>
                  <tr>
                    <th scope="col">{MODELS.question}</th>
                    <th scope="col">{MODELS.jevColumn}</th>
                    {models.models.map((m) => (
                      <th
                        key={m}
                        scope="col"
                        title={agreement[m] ? MODELS.agreement(agreement[m].same, agreement[m].of) : ''}
                      >
                        {MODEL_NAMES[m] ?? m}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {asked.map((q, k) => {
                    const step = decision.steps[q.step] as WalkStep | undefined
                    const jev = jevPick(bundle, q)
                    const jevP = step?.answer?.probabilities?.[jev ?? ''] ?? null
                    return (
                      <tr key={q.step} data-step={q.step}>
                        <th scope="row">
                          {k + 1}{' '}
                          <span className="faint">
                            {q.kind === 'focus' ? MODELS.focusAt(q.node) : MODELS.ruleAt(q.node)}
                          </span>
                        </th>
                        <td data-model="jev">
                          {jev ? optionWords(step, jev) : '–'}
                          {jevP !== null && <span className="faint"> {pct(jevP)}</span>}
                        </td>
                        {models.models.map((m) => {
                          const pick = q.picks[m]
                          const differs = !!pick && jev !== null && pick[0] !== jev
                          return (
                            <td
                              key={m}
                              data-model={m}
                              className={differs ? 'differs' : ''}
                              title={differs ? MODELS.differs : undefined}
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
                  (m) => `${MODEL_NAMES[m] ?? m}: ${MODELS.agreement(agreement[m]?.same ?? 0, agreement[m]?.of ?? 0)}`,
                )
                .join('. ')}
              .
            </p>
          </>
        )}
      </Panel>
      <Panel id="rt-thor">
        <p className="small">{MODELS.thorLead}</p>
        <div className="table-wrap">
          <table className="data-table" data-testid="thor-table">
            <thead>
              <tr>
                {MODELS.thorColumns.map((c) => (
                  <th key={c} scope="col">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {THOR_ROWS.map(([setup, fresh, again, weights]) => (
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
