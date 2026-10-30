import { useMemo } from 'react'
import { Panel } from '../../components/Panel'
import { WRITTEN, writerName } from '../../content/rules/words'
import {
  type BuildEntry,
  type BuildGame,
  type CheckView,
  type ProposedRule,
  type RulesBundle,
  actionWords,
  addedIds,
  readBuild,
  seedOfGame,
} from '../../data/rules'
import { openRule, setState, useApp } from '../../store'

type ProposalEntry = Extract<BuildEntry, { kind: 'proposal' }>

/** The soft loop's record for this tree, step by step: passes, proposals with their check and gate, held-out seeds. */
export function HowWritten({ bundle }: { bundle: RulesBundle }) {
  const entries = useMemo(() => readBuild(bundle.build), [bundle])
  const round = useApp((s) => s.round)
  const first = entries.findIndex((e) => e.kind === 'proposal')
  const at = round !== null && round < entries.length ? round : Math.max(0, first)
  const entry = entries[at]
  return (
    <main className="screen written" aria-label="How the rules were written">
      <header className="screen-head">
        <h2>{WRITTEN.title}</h2>
        <p>{WRITTEN.intro}</p>
      </header>
      {entries.length === 0 ? (
        <p className="note">{WRITTEN.none}</p>
      ) : (
        <div className="slow-grid">
          <Panel id="rt-rounds" aside={<span className="panel-aside">{entries.length} steps</span>}>
            <ol className="cycle-list build-list" data-testid="build-list">
              {entries.map((e, i) => (
                <li key={i}>
                  <button
                    type="button"
                    className={`cycle-row ${i === at ? 'selected' : ''}`}
                    data-testid="build-row"
                    data-kind={e.kind}
                    aria-current={i === at ? 'true' : undefined}
                    onClick={() => setState({ round: i })}
                  >
                    <EntryLine entry={e} />
                  </button>
                </li>
              ))}
            </ol>
          </Panel>
          <div className="slow-detail">
            <Panel id="rt-round">{entry && <EntryDetail entry={entry} bundle={bundle} />}</Panel>
          </div>
        </div>
      )}
    </main>
  )
}

const outcomeClass = (e: ProposalEntry) =>
  e.outcome === 'added' ? 'passed' : e.outcome === 'not checked' || e.outcome === 'check stopped' ? 'waiting' : 'failed'

/** One line of the list: what the step was and how it ended. */
function EntryLine({ entry: e }: { entry: BuildEntry }) {
  switch (e.kind) {
    case 'start':
      return <span className="outcome">{WRITTEN.start(e.tree)}</span>
    case 'pass':
    case 'held-out':
      return (
        <>
          <span className="outcome">
            {e.kind === 'pass' ? WRITTEN.pass(e.round, e.again) : WRITTEN.heldOut}: {WRITTEN.cleared(e.cleared, e.of)}
          </span>
          {e.label && <span className="cycle-at">{e.label}</span>}
        </>
      )
    case 'representation':
      return (
        <>
          <span className="outcome">{WRITTEN.representation}</span>
          <span className="cycle-choice small">{e.change}</span>
        </>
      )
    case 'proposal':
      return (
        <>
          <span>
            <span className="outcome">{WRITTEN.proposal(e.name)}</span>{' '}
            <span className={`status-chip ${outcomeClass(e)}`}>
              {WRITTEN.outcome[e.outcome]}
              {e.added ? `: ${e.added.rule.replaceAll('+', ', ')}` : ''}
            </span>
          </span>
          <span className="cycle-choice small">{e.proposal?.rules[0]?.condition ?? e.error ?? ''}</span>
        </>
      )
    case 'stop':
      return <span className="outcome">{WRITTEN.stop}</span>
  }
}

function EntryDetail({ entry: e, bundle }: { entry: BuildEntry; bundle: RulesBundle }) {
  switch (e.kind) {
    case 'start':
      return (
        <div className="build-detail" data-testid="build-detail">
          <h3>{WRITTEN.start(e.tree)}</h3>
          <p>{WRITTEN.startNote(e.tree, e.writer ?? bundle.meta.tree_writer)}</p>
        </div>
      )
    case 'pass':
    case 'held-out':
      return (
        <div className="build-detail" data-testid="build-detail">
          <h3>
            {e.kind === 'pass' ? WRITTEN.pass(e.round, e.again) : WRITTEN.heldOut}: {WRITTEN.cleared(e.cleared, e.of)}
            {e.kind === 'held-out' && e.seeds ? `, ${WRITTEN.seeds(e.seeds)}` : ''}
          </h3>
          {e.label && <p className="muted">{e.label}</p>}
          {e.games.length > 0 && <Games games={e.games} />}
          {e.games.length === 0 && e.failures.length > 0 && (
            <>
              <p className="chips-label">{WRITTEN.failures}</p>
              <ul className="notes">
                {e.failures.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )
    case 'representation':
      return (
        <div className="build-detail" data-testid="build-detail">
          <h3>{WRITTEN.representation}</h3>
          <p>{e.change}</p>
          {e.why && <p className="muted">{e.why}</p>}
          <p className="faint small">{WRITTEN.representationNote}</p>
        </div>
      )
    case 'proposal':
      return <ProposalDetail entry={e} />
    case 'stop':
      return (
        <div className="build-detail" data-testid="build-detail">
          <h3>{WRITTEN.stop}</h3>
          <p>{e.reason}</p>
        </div>
      )
  }
}

function ProposalDetail({ entry: e }: { entry: ProposalEntry }) {
  const p = e.proposal
  return (
    <div className="build-detail" data-testid="build-detail" data-outcome={e.outcome}>
      <h3>
        {WRITTEN.proposal(e.name)}{' '}
        <span className={`status-chip ${outcomeClass(e)}`}>{WRITTEN.outcome[e.outcome]}</span>
      </h3>
      {e.writer && <p className="muted small">by {writerName(e.writer)}</p>}
      {e.error && <p className="miss-box">{WRITTEN.writerError(e.error)}</p>}
      {p && (
        <>
          <p className="small">
            {WRITTEN.writtenFor(p.trace, p.frame, seedOfGame(p.trace))} {p.under ? WRITTEN.under(p.under) : ''}
          </p>
          {p.rules.length > 1 && <p className="chips-label">{WRITTEN.group}</p>}
          {p.rules.map((r, i) => (
            <ProposedRuleView key={i} rule={r} />
          ))}
          {p.why && (
            <>
              <p className="chips-label">{WRITTEN.why}</p>
              <p className="writer-why">{p.why}</p>
            </>
          )}
        </>
      )}
      {e.check && <CheckDetail check={e.check} />}
      {e.gate && (
        <>
          <p className="chips-label">{WRITTEN.gate}</p>
          <p>
            {e.gate.withRule !== null && e.gate.current !== null && e.gate.of !== null
              ? WRITTEN.gateBoth(e.gate.current, e.gate.withRule, e.gate.of)
              : e.gate.current !== null && e.gate.of !== null
                ? WRITTEN.gateCurrent(e.gate.current, e.gate.of)
                : ''}{' '}
            {e.gate.passed === true ? WRITTEN.gatePassed : e.gate.passed === false ? WRITTEN.gateFailed : ''}
          </p>
        </>
      )}
      {e.note && (
        <>
          <p className="chips-label">{WRITTEN.note}</p>
          <p className="muted">{e.note}</p>
        </>
      )}
      {e.added && (
        <p className="build-added">
          <strong>{WRITTEN.addedAs(e.added.rule, e.added.attachTo)}</strong>{' '}
          {addedIds(e.added.rule).map((id) => (
            <button key={id} type="button" className="link-button" onClick={() => openRule(id)}>
              {WRITTEN.ruleLink(id)}
            </button>
          ))}
        </p>
      )}
      <p className="faint small">{WRITTEN.dossier}</p>
    </div>
  )
}

function ProposedRuleView({ rule }: { rule: ProposedRule }) {
  return (
    <dl className="facts-list proposed-rule">
      <div>
        <dt>{WRITTEN.condition}</dt>
        <dd>{rule.condition}</dd>
      </div>
      <div>
        <dt>{WRITTEN.action}</dt>
        <dd>{rule.action ? actionWords(rule.action) : '–'}</dd>
      </div>
    </dl>
  )
}

const mark = (x: boolean | null) => (x === null ? '–' : x ? WRITTEN.checkPassed : WRITTEN.checkFailed)

function CheckDetail({ check }: { check: CheckView }) {
  const tests = check.sees !== null || check.unchanged !== null || check.avoids !== null
  return (
    <>
      <p className="chips-label">
        {WRITTEN.check}
        {check.passed !== null && (
          <>
            {' '}
            <span className={`status-chip ${check.passed ? 'passed' : 'failed'}`}>{mark(check.passed)}</span>
          </>
        )}
      </p>
      {check.error && (
        <p className="note" data-testid="check-error">
          {WRITTEN.checkError(check.error)}
        </p>
      )}
      {tests ? (
        <ul className="check-tests">
          {(['sees', 'unchanged', 'avoids'] as const).map((t) => (
            <li key={t} data-test={t} data-passed={String(check[t])}>
              <span className={`status-chip ${check[t] === null ? 'waiting' : check[t] ? 'passed' : 'failed'}`}>
                {mark(check[t])}
              </span>{' '}
              {WRITTEN.tests[t]}
            </li>
          ))}
        </ul>
      ) : (
        !check.error && check.passed !== null && <p className="faint small">{WRITTEN.checkNoTests}</p>
      )}
      {check.oldTree && check.newTree && (
        <dl className="facts-list">
          <div>
            <dt>{WRITTEN.without}</dt>
            <dd>{WRITTEN.standing(check.oldTree)}</dd>
          </div>
          <div>
            <dt>{WRITTEN.with}</dt>
            <dd>{WRITTEN.standing(check.newTree)}</dd>
          </div>
        </dl>
      )}
    </>
  )
}

function Games({ games }: { games: BuildGame[] }) {
  return (
    <div className="table-wrap">
      <table className="data-table build-games">
        <caption>{WRITTEN.games}</caption>
        <thead>
          <tr>
            {WRITTEN.gameColumns.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {games.map((g) => (
            <tr key={`${g.seed}-${g.game}`} data-event={g.event}>
              <th scope="row">{g.seed}</th>
              <td className="mono small">{g.game ?? ''}</td>
              <td>
                <span className={`status-chip ${g.event === 'cleared' ? 'passed' : 'failed'}`}>{g.event}</span>
              </td>
              <td className="num">{g.decisions ?? ''}</td>
              <td className="num">{g.maxX ?? ''}</td>
              <td className="num">{g.health ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
