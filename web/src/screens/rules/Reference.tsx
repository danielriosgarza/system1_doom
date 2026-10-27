import type { ReactNode } from 'react'
import { Panel } from '../../components/Panel'
import { TermLink } from '../../components/TermLink'
import { linkTerms } from '../../components/Terms'
import { RULES_REFERENCE, rulesResultWords, writerWords } from '../../content/rules/words'
import type { RulesBundle } from '../../data/rules'
import { Glossary } from '../Reference'

/** The rule tree's Reference: the one rule, the drawing, the glossary, how this recording was made, and the keys. */
export function RulesReference({ bundle }: { bundle: RulesBundle }) {
  return (
    <main className="screen reference" aria-label="Reference">
      <header className="screen-head">
        <h2>{RULES_REFERENCE.title}</h2>
      </header>
      <Panel id="rt-principles">
        <p className="one-rule" data-testid="one-rule">
          {RULES_REFERENCE.rule}
        </p>
        <p>{RULES_REFERENCE.ruleNote}</p>
        <ul className="principles">
          {RULES_REFERENCE.principles.map((p) => {
            const seen = new Set<string>()
            return (
              <li key={p.title}>
                <strong>{p.title}.</strong> {linkTerms(p.text, seen, 'rules')}
              </li>
            )
          })}
        </ul>
      </Panel>
      <Panel id="rt-drawing">
        <RulesDrawing />
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
            {RULES_REFERENCE.keys.map(([k, v]) => (
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

/** A box of the drawing: a Jev call (it decides), the rule writer (it proposes) or the program (it never chooses). */
function Node({ by, children, className }: { by: 'jev' | 'writer' | 'code'; children: ReactNode; className?: string }) {
  return (
    <div className={`node ${by === 'code' ? 'code' : 'd1'} ${by === 'writer' ? 'writer' : ''} ${className ?? ''}`}>
      {by === 'jev' && <span className="node-badge">Jev</span>}
      {by === 'writer' && <span className="node-badge">rule writer</span>}
      {children}
    </div>
  )
}

function Arrow({ children }: { children?: ReactNode }) {
  return (
    <div className="flow" aria-hidden={children ? undefined : true}>
      <span className="flow-line" aria-hidden />
      {children && <span className="flow-label">{children}</span>}
    </div>
  )
}

/** The rule tree's two systems, drawn: Jev walking the tree at every decision; the soft loop between games. */
function RulesDrawing() {
  return (
    <figure className="drawing" data-testid="rules-drawing">
      <div className="drawing-cols">
        <section className="sys sys1" aria-label="Every decision">
          <h3>
            <TermLink id="walk" text="The walk" /> <span className="muted">every decision</span>
          </h3>
          <Node by="code">
            <strong>The state</strong>: the game written as plain text in <TermLink id="channel" text="channels" />, and
            the screen as an image
          </Node>
          <Arrow>the same state goes with every question of the decision</Arrow>
          <Node by="jev">
            <strong>At the top of the tree</strong>: “Which of these is true right now?” An enemy is in view; no enemy
            is in view; none of these
          </Node>
          <Arrow>into the rule Jev picks</Arrow>
          <Node by="jev">
            <strong>
              <TermLink id="focus" text="Focus" />
            </strong>
            : “Which of these enemies is the biggest danger to me right now?” The pick is added to the state as a
            [focus] channel
          </Node>
          <Arrow>the rules under it, then the aim skill</Arrow>
          <Node by="jev">
            <strong>
              <TermLink id="rule" text="Rules" /> and <TermLink id="skill" text="skills" />
            </strong>
            : one question per level, until Jev picks none or reaches a rule with nothing under it
          </Node>
          <Arrow>that rule’s action; after a miss, the action of the rule reached</Arrow>
          <Node by="code">
            <strong>Act</strong>: the <TermLink id="action-code" text="action code" />
            ’s keys, held for 8 <TermLink id="tic" text="tics" />
          </Node>
          <Arrow>the game moves on to the next decision</Arrow>
          <Node by="code">
            <strong>Recorded</strong>: every question, its options, Jev’s probabilities, the answer, the time and the
            cost
          </Node>
        </section>
        <section className="sys sys2" aria-label="Between games">
          <h3>
            <TermLink id="soft-loop" text="The soft loop" /> <span className="muted">between games</span>
          </h3>
          <Node by="code">
            <strong>Play</strong> every <TermLink id="training-seed" text="training seed" /> with the tree as it is
          </Node>
          <Arrow>a game dies, or stops making progress</Arrow>
          <Node by="writer">
            <strong>
              <TermLink id="rule-writer" text="Rule writer" />
            </strong>
            : reads the decisions before the failure and proposes one rule, in plain words, for the moment it went wrong
          </Node>
          <Arrow>the program replays that game, with Jev answering</Arrow>
          <Node by="code">
            <strong>The check</strong>: the walk reaches the rule there; earlier rules’ decisions end no worse; the game
            ends better with the rule
          </Node>
          <Arrow>then every training seed, with and without the rule</Arrow>
          <Node by="code">
            <strong>The gate</strong>: the tree with the rule must clear at least as many seeds
          </Node>
          <Arrow>
            added, with its decision kept as a <TermLink id="cornerstone" text="cornerstone" />
          </Arrow>
          <Node by="code">
            <strong>
              <TermLink id="rule-tree" text="The tree" />
            </strong>
            , one rule larger; a rejected rule goes back to the writer with the reason
          </Node>
        </section>
      </div>
      <p className="drawing-loop">
        <span aria-hidden>↺</span> The next games are played with the new tree. The soft loop never runs during a game,
        and the program never answers a question in Jev’s place.
      </p>
      <figcaption className="drawing-legend">
        <span className="node d1 legend-node">
          <span className="node-badge">Jev</span>
        </span>{' '}
        a Jev call: it decides · <span className="node d1 writer legend-node">rule writer</span> the rule writer: it
        proposes rules between games · <span className="node code legend-node">code</span> the program: it writes the
        state, asks, follows the answers, presses keys and grades replays; it never chooses
      </figcaption>
    </figure>
  )
}

function Provenance({ bundle }: { bundle: RulesBundle }) {
  const m = bundle.meta
  const P = RULES_REFERENCE.provenance
  const models = Object.entries(m.models)
  const rows: Array<[string, string]> = [
    [P.scenario, m.scenario],
    [P.decider, 'Jev, TypeSafe’s decision model'],
    [P.models, models.map(([model, calls]) => `${model} (${calls} calls)`).join(', ') || 'none'],
    [P.tree, `${m.tree}, ${m.rules} rules`],
    [P.writer, writerWords(m.tree_writer)],
    [P.seed, String(m.seed)],
    [P.budget, `${m.call_budget_sec} s per call, ${m.decision_tics ?? 8} tics per decision`],
    [P.calls, `${m.calls}, $${m.cost.toFixed(4)}`],
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
      <pre className="command">{`python -m system1_doom.export --solution rule-tree --tree ${m.tree} --seed ${m.seed} --out web/public/episodes/${bundle.name} --name ${bundle.name}`}</pre>
      <p className="chips-label">{P.play}</p>
      <pre className="command">{`python -m system1_doom.ruletree play runs/rule-tree --tree ${m.tree} --seed ${m.seed}`}</pre>
    </div>
  )
}
