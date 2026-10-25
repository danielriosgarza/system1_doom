import { useMemo, useState } from 'react'
import { Meter } from '../components/Bars'
import { EvidenceText } from '../components/Evidence'
import { Panel } from '../components/Panel'
import { missWords } from '../content/instances'
import { MENU } from '../content/menu'
import type { EpisodeBundle } from '../data/loader'
import { boundsOf, fmt, pct, placedCycles, words } from '../data/readings'
import { outcomeWords, reflectorRows } from '../data/system2'
import type { ProposalTrace, TickTrace } from '../schema/bundle'

export function Menu({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const proposals = bundle.proposals
  const [picked, setPicked] = useState<number | null>(null)
  const shown = picked ?? (proposals.length ? proposals.length - 1 : null)
  const proposal = shown === null ? null : (proposals[shown] ?? null)
  return (
    <main className="screen menu-screen" aria-label="Growing the menu">
      <header className="screen-head">
        <h2>{MENU.title}</h2>
        <p>{MENU.intro}</p>
      </header>
      <Panel id="menu-now">
        <MenuTable bundle={bundle} tick={tick} />
      </Panel>
      <Panel id="menu-reflector">
        <MenuReflector bundle={bundle} />
      </Panel>
      <div className="menu-grid">
        <Panel id="proposals" aside={<span className="panel-aside">{proposals.length}</span>}>
          {proposals.length === 0 ? (
            <p className="muted small">{MENU.none}</p>
          ) : (
            <ol className="proposals">
              {proposals.map((p, i) => (
                <li key={`${p.timestamp}-${i}`}>
                  <ProposalCard proposal={p} index={i} selected={i === shown} onPick={() => setPicked(i)} />
                </li>
              ))}
            </ol>
          )}
        </Panel>
        {proposal && shown !== null && (
          <Panel id="admit">
            <Admit proposal={proposal} index={shown} yesAt={boundsOf(bundle.meta).yes_at} />
          </Panel>
        )}
      </div>
    </main>
  )
}

function MenuTable({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const counts = useMemo(() => {
    const out = new Map<string, number>()
    for (const t of bundle.ticks)
      if (t.executed_action) out.set(t.executed_action, (out.get(t.executed_action) ?? 0) + 1)
    return out
  }, [bundle.ticks])
  const legal = new Set(tick.available_actions)
  return (
    <div className="table-wrap">
      <table className="data-table" data-testid="menu-table">
        <thead>
          <tr>
            {MENU.columns.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Object.entries(bundle.meta.actions).map(([id, a]) => {
            const kind = !a.builtin ? MENU.kind.admitted : a.is_macro ? MENU.kind.builtin : MENU.kind.primitive
            const now = id === tick.executed_action
            return (
              <tr
                key={id}
                data-action={id}
                data-legal={legal.has(id)}
                className={`${now ? 'here' : ''} ${legal.has(id) ? '' : 'faint-row'}`}
                title={now ? MENU.executedNow : undefined}
              >
                <th scope="row">{words(id)}</th>
                <td className={a.builtin ? '' : 'accent-text'}>{kind}</td>
                <td className="mono small">{a.primitives.map(words).join(', ')}</td>
                <td className="num">{legal.has(id) ? '✓' : ''}</td>
                <td className="num">{counts.get(id) ?? 0}</td>
                <td className="small">{a.description}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function MenuReflector({ bundle }: { bundle: EpisodeBundle }) {
  const cycles = placedCycles(bundle)
  if (!cycles.length) return <p className="muted small">{MENU.noCycles}</p>
  return (
    <div className="table-wrap">
      <table className="data-table" data-testid="menu-reflector">
        <thead>
          <tr>
            {MENU.reflectorColumns.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cycles.map(({ cycle, tickIndex }) => {
            const r = reflectorRows(cycle).find((row) => row.name === 'menu_reflector')
            const chosen = !!r?.proposed && cycle.choice === r.change
            return (
              <tr key={cycle.cycle_id} data-cycle={cycle.cycle_id}>
                <th scope="row">after decision {tickIndex + 1}</th>
                {!r || !r.called ? (
                  <td colSpan={4} className="muted small">
                    {MENU.notCalled(r?.skipped ?? 'not in this cycle')}
                  </td>
                ) : r.missed ? (
                  <td colSpan={4} className="small">
                    missed: {missWords(r.missReason)}
                  </td>
                ) : (
                  <>
                    <td className="num">
                      {fmt(r.speak)} {r.spoke ? 'spoke' : 'silent'}
                    </td>
                    <td className="mono small">
                      {r.change} {r.changeP !== null && <span className="muted">({pct(r.changeP)})</span>}
                    </td>
                    <td>{words(r.reason)}</td>
                    <td className="small">
                      {r.proposed
                        ? chosen
                          ? outcomeWords(cycle.outcome)
                          : 'proposed; another change was chosen'
                        : '–'}
                    </td>
                  </>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ProposalCard({
  proposal,
  index,
  selected,
  onPick,
}: {
  proposal: ProposalTrace
  index: number
  selected: boolean
  onPick: () => void
}) {
  const who = proposal.source_module ?? 'a'
  return (
    <article
      className={`proposal ${selected ? 'selected' : ''}`}
      data-testid="proposal"
      data-admitted={proposal.admission_decision}
    >
      <header className="proposal-head">
        <strong>{MENU.proposal(proposal.tick)}</strong>
        <span className={`status-chip ${proposal.admission_decision ? 'kept' : 'reverted'}`}>
          {proposal.admission_decision && proposal.admitted_action_id
            ? MENU.admitted(proposal.admitted_action_id)
            : MENU.rejected}
        </span>
      </header>
      <p className="small muted">{MENU.askedBy(who, proposal.source ?? 'slow path')}</p>
      <p className="chips-label">{MENU.request}</p>
      <pre className="evidence-text small-pre">{proposal.request_context}</pre>
      <p className="chips-label">{MENU.raw}</p>
      <pre className="evidence-text small-pre" data-testid="raw-proposal">
        {proposal.raw_proposal}
      </pre>
      <p className="chips-label">{MENU.stages}</p>
      <ol className="stages">
        {(proposal.stage_results ?? []).map((s) => (
          <li key={s.stage} className={s.skipped ? 'skipped' : s.passed ? 'passed' : 'failed'} data-stage={s.stage}>
            <strong>{s.stage}</strong> {s.skipped ? MENU.skipped : s.passed ? '✓' : '✗'}{' '}
            <span className="small muted">{s.reason}</span>
          </li>
        ))}
      </ol>
      {proposal.sandbox_summary && (
        <>
          <p className="chips-label">{MENU.sandbox}</p>
          <p className="small mono">
            {Object.entries(proposal.sandbox_summary)
              .map(([k, v]) => `${words(k)} ${fmt(v)}`)
              .join(' · ')}
          </p>
        </>
      )}
      {!selected && proposal.admit_instance && (
        <button type="button" className="link" onClick={onPick}>
          {MENU.pick} ({index + 1})
        </button>
      )}
    </article>
  )
}

function Admit({ proposal, index, yesAt }: { proposal: ProposalTrace; index: number; yesAt: number }) {
  const a = proposal.admit_instance
  if (!a) return <p className="muted small">{MENU.admitNone}</p>
  const p = a.admit ?? proposal.d1_admission_probability ?? null
  return (
    <div className="admit" data-testid="admit-instance">
      <p className="chips-label">{MENU.admitTitle(index + 1)}</p>
      {a.missed ? (
        <p className="miss-box">
          <strong>Missed:</strong> {missWords(a.miss_reason ?? null)}
          {a.error ? ` (${a.error})` : ''}
        </p>
      ) : (
        <>
          <p>
            <strong>{fmt(p)}</strong> · {p !== null && p >= yesAt ? MENU.yes : MENU.no}
          </p>
          <Meter value={p} mark={yesAt} label="admit" className="answer-meter" />
        </>
      )}
      <p className="chips-label">{MENU.admitSaw}</p>
      <EvidenceText text={a.evidence} name="admit" testId="admit-evidence" />
    </div>
  )
}
