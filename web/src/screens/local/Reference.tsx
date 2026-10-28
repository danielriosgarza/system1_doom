import { Panel } from '../../components/Panel'
import { linkTerms } from '../../components/Terms'
import { LOCAL_REFERENCE } from '../../content/local/words'
import { RULES_REFERENCE, rulesResultWords } from '../../content/rules/words'
import type { RulesBundle } from '../../data/rules'
import { Glossary } from '../Reference'

/** The local models' Reference: who makes each choice, the glossary, how this recording was made, and the keys. */
export function LocalReference({ bundle }: { bundle: RulesBundle }) {
  return (
    <main className="screen reference" aria-label="Reference">
      <header className="screen-head">
        <h2>{LOCAL_REFERENCE.title}</h2>
      </header>
      <Panel id="rt-principles">
        <p className="one-rule" data-testid="one-rule">
          {LOCAL_REFERENCE.rule}
        </p>
        <p>{LOCAL_REFERENCE.ruleNote}</p>
        <ul className="principles">
          {LOCAL_REFERENCE.principles.map((p) => {
            const seen = new Set<string>()
            return (
              <li key={p.title}>
                <strong>{p.title}.</strong> {linkTerms(p.text, seen, 'local')}
              </li>
            )
          })}
        </ul>
      </Panel>
      <Panel id="glossary">
        <Glossary />
      </Panel>
      <div className="reference-grid">
        <Panel id="rt-provenance">
          <Provenance bundle={bundle} />
        </Panel>
        <Panel id="keys">
          <dl className="keys">
            {LOCAL_REFERENCE.keys.map(([k, v]) => (
              <div key={k}>
                <dt>
                  <kbd>{k}</kbd>
                </dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      </div>
    </main>
  )
}

function Provenance({ bundle }: { bundle: RulesBundle }) {
  const m = bundle.meta
  const P = RULES_REFERENCE.provenance
  const L = LOCAL_REFERENCE.provenance
  const models = Object.entries(m.models)
  const rows: Array<[string, string]> = [
    [P.scenario, m.scenario],
    [L.decider, L.deciderValue],
    [L.checkpoint, m.model ?? 'not kept'],
    [P.models, models.map(([model, calls]) => `${model} (${calls} calls)`).join(', ') || 'none'],
    [P.tree, `${m.tree}, ${m.rules} rules`],
    [P.seed, String(m.seed)],
    [P.budget, `${m.call_budget_sec} s`],
    [
      P.decisionLength,
      `${m.decision_tics ?? 8} tics, about ${(((m.decision_tics ?? 8) / 35) * 1000).toFixed(0)} ms of game time`,
    ],
    [P.calls, String(m.calls)],
    [P.misses, String(m.misses)],
    [
      P.result,
      rulesResultWords({
        scenario: m.scenario,
        cleared: m.result.cleared,
        died: m.result.died,
        ticks: m.result.decisions,
        kills: m.result.kills,
      }),
    ],
    [
      P.recorded,
      `${m.recorded_at.slice(0, 16).replace('T', ' ')} UTC${m.package_version ? `, package ${m.package_version}` : ''}`,
    ],
  ]
  return (
    <div className="provenance" data-testid="provenance">
      <p>
        <strong>{m.title}</strong>
      </p>
      <dl className="facts-list">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <p className="chips-label">{P.command}</p>
      <pre className="command">{`python -m system1_doom.export --solution rule-tree --tree ${m.tree} --seed ${m.seed} --tree-decider ${m.decider ?? 'laya'}${m.model ? ` --tree-model ${m.model}` : ''} --out web/public/episodes/${bundle.name}`}</pre>
      <p className="chips-label">{P.play}</p>
      <pre className="command">{`python -m system1_doom.ruletree play runs/local --tree ${m.tree} --seed ${m.seed} --decider ${m.decider ?? 'laya'}${m.model ? ` --model ${m.model}` : ''}`}</pre>
    </div>
  )
}
