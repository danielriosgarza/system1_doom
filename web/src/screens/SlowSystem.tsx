import { useMemo, useState } from 'react'
import { BarList, Meter } from '../components/Bars'
import { EvidenceText } from '../components/Evidence'
import { Panel } from '../components/Panel'
import { TermLink } from '../components/TermLink'
import { missWords } from '../content/instances'
import { SLOW, STATUS_WORDS, summaryWords } from '../content/slow'
import type { EpisodeBundle } from '../data/loader'
import {
  CENTRAL,
  type Counts,
  type PlacedCycle,
  SENSES,
  type VersionEntry,
  bars,
  boundsOf,
  configurationAt,
  episodeEntries,
  fmt,
  isNote,
  ledgerRows,
  meanStrength,
  paidRate,
  overruledRate,
  pct,
  placedCycles,
  sections,
  senseTotals,
  versionTimeline,
  words,
} from '../data/readings'
import {
  type ReflectorRow,
  TRIAL_ROWS,
  answerWords,
  changeWords,
  configurationChanges,
  defaultCycle,
  outcomeWords,
  proposerOf,
  reflectorRows,
  testSummary,
  verdictOf,
} from '../data/system2'
import type { HistoryTestResult, ReflectionTrace, TickTrace, TrialVerdictTrace } from '../schema/bundle'
import { openInstance, setTickIndex } from '../store'

/** System 2's whole record of the episode: versions, cycles, the history test, the trial, the ledger. */
export function SlowSystem({ bundle, tick, tickIndex }: { bundle: EpisodeBundle; tick: TickTrace; tickIndex: number }) {
  const timeline = useMemo(() => versionTimeline(bundle), [bundle])
  const cycles = useMemo(() => placedCycles(bundle), [bundle])
  const [picked, setPicked] = useState<string | null>(null)
  const selected = cycles.find((c) => c.cycle.cycle_id === picked)?.cycle ?? defaultCycle(cycles, tickIndex)
  const placed = cycles.find((c) => c.cycle === selected) ?? null
  const verdict = verdictOf(bundle, selected)
  const enabled = bundle.meta.system2?.enabled !== false
  return (
    <main className="screen slow" aria-label="The slow system">
      <header className="screen-head">
        <h2>{SLOW.title}</h2>
        <p>{SLOW.intro}</p>
        {bundle.meta.system2 && (
          <ul className="facts" data-testid="system2-summary">
            {summaryWords(bundle.meta.system2).map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
      </header>
      {!enabled && <p className="note">{SLOW.off}</p>}
      <Panel id="versions">
        <Versions timeline={timeline} selected={selected} onPick={setPicked} tickIndex={tickIndex} />
      </Panel>
      <div className="slow-grid">
        <Panel id="cycles" className="slow-cycles">
          <CycleList cycles={cycles} selected={selected} onPick={setPicked} tickIndex={tickIndex} enabled={enabled} />
        </Panel>
        <div className="slow-detail">
          {selected && placed ? (
            <>
              <Panel
                id="reflectors"
                aside={<span className="panel-aside">{SLOW.afterDecision(placed.tickIndex + 1)}</span>}
              >
                <CycleHead
                  cycle={selected}
                  tickIndex={placed.tickIndex}
                  cadence={boundsOf(bundle.meta).system2_cadence ?? 20}
                />
                <Reflectors cycle={selected} yesAt={boundsOf(bundle.meta).yes_at} />
              </Panel>
              <Panel id="system2-central">
                <System2Central cycle={selected} />
              </Panel>
            </>
          ) : (
            <p className="note">{cycles.length ? SLOW.selectCycle : SLOW.noCyclesYet}</p>
          )}
        </div>
      </div>
      {selected?.history_test && (
        <Panel id="history-test" testId="history-test">
          <HistoryTest test={selected.history_test} bundle={bundle} />
        </Panel>
      )}
      {selected && (verdict || selected.applied) && (
        <Panel id="trial" testId="trial">
          <Trial bundle={bundle} cycle={selected} verdict={verdict} timeline={timeline} tickIndex={tickIndex} />
        </Panel>
      )}
      <Panel id="ledger">
        <Ledger bundle={bundle} tick={tick} />
      </Panel>
      <Panel id="configuration-changes">
        <ConfigurationChanges bundle={bundle} />
      </Panel>
    </main>
  )
}

// ---------------------------------------------------------------------------------------------

function Versions({
  timeline,
  selected,
  onPick,
  tickIndex,
}: {
  timeline: VersionEntry[]
  selected: ReflectionTrace | null
  onPick: (id: string) => void
  tickIndex: number
}) {
  return (
    <ol className="versions" aria-label="Configuration versions">
      {timeline.map((entry) => {
        const proposer = proposerOf(entry.cycle)
        const choice = entry.cycle?.central?.change_probabilities?.[entry.cycle.choice ?? '']
        const current = entry.tickIndex !== null && entry.tickIndex <= tickIndex
        return (
          <li key={entry.version}>
            <button
              type="button"
              className={`version-card status-${entry.status.replace(' ', '-')} ${
                entry.cycle && entry.cycle === selected ? 'selected' : ''
              } ${current ? '' : 'later'}`}
              data-testid="version-card"
              data-version={entry.version}
              data-status={entry.status}
              disabled={!entry.cycle}
              aria-pressed={!!entry.cycle && entry.cycle === selected}
              onClick={() => entry.cycle && onPick(entry.cycle.cycle_id)}
            >
              <span className="version-num">Version {entry.version}</span>
              <span className={`status-chip ${entry.status.replace(' ', '-')}`}>{STATUS_WORDS[entry.status]}</span>
              <span className="version-change">
                {entry.status === 'start' ? entry.change : changeWords(entry.change)}
              </span>
              {entry.changes.length > 0 && <span className="version-diff mono">{entry.changes.join('; ')}</span>}
              <span className="version-meta">
                {entry.tickIndex !== null
                  ? `from decision ${entry.tickIndex + 1}`
                  : entry.status === 'queued'
                    ? 'takes effect at the start of the next episode'
                    : ''}
                {proposer ? ` · ${SLOW.proposedBy(words(proposer))}` : ''}
                {choice !== undefined ? ` · ${SLOW.choseAt(pct(choice))}` : ''}
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

function CycleList({
  cycles,
  selected,
  onPick,
  tickIndex,
  enabled,
}: {
  cycles: PlacedCycle[]
  selected: ReflectionTrace | null
  onPick: (id: string) => void
  tickIndex: number
  enabled: boolean
}) {
  if (!cycles.length) return <p className="muted small">{enabled ? SLOW.noCycles : SLOW.off}</p>
  return (
    <ol className="cycle-list">
      {cycles.map(({ cycle, tickIndex: at }) => (
        <li key={cycle.cycle_id}>
          <button
            type="button"
            className={`cycle-row ${cycle === selected ? 'selected' : ''} ${at > tickIndex ? 'later' : ''}`}
            data-testid="cycle-row"
            data-cycle={cycle.cycle_id}
            data-outcome={cycle.outcome}
            aria-pressed={cycle === selected}
            title={at > tickIndex ? SLOW.later : undefined}
            onClick={() => onPick(cycle.cycle_id)}
          >
            <span className="cycle-at">{SLOW.afterDecision(at + 1)}</span>
            <span className={`outcome outcome-${cycle.outcome}`}>{outcomeWords(cycle.outcome)}</span>
            {cycle.choice && cycle.choice !== 'none' && <span className="cycle-choice mono">{cycle.choice}</span>}
          </button>
        </li>
      ))}
    </ol>
  )
}

function CycleHead({ cycle, tickIndex, cadence }: { cycle: ReflectionTrace; tickIndex: number; cadence: number }) {
  const started =
    cycle.trigger === 'episode_end' ? 'started because the episode ended' : `started after ${cadence} new decisions`
  return (
    <div className="cycle-head" data-testid="cycle-head" data-cycle={cycle.cycle_id}>
      <p>
        <strong>{words(cycle.cycle_id)}</strong>, {started}, when System 2 had counted {cycle.decision} decisions, on
        configuration version {cycle.configuration_version}. Outcome:{' '}
        <span className={`outcome outcome-${cycle.outcome}`}>{outcomeWords(cycle.outcome)}</span>.{' '}
        <button type="button" className="link" onClick={() => setTickIndex(tickIndex)}>
          {SLOW.showDecision}
        </button>
      </p>
      {(cycle.windows ?? []).length > 0 && (
        <p className="small muted">
          {SLOW.windowsTitle}:{' '}
          {(cycle.windows ?? []).map((w) => `${w.label} (${w.decisions} decisions held)`).join(' · ')}
          {cycle.calls !== undefined && ` · ${cycle.calls} d1-ultra calls`}
          {cycle.usage?.cost !== undefined && `, $${cycle.usage.cost.toFixed(5)}`}
        </p>
      )}
      {(cycle.notes ?? []).length > 0 && (
        <ul className="notes small">
          {(cycle.notes ?? []).map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function reflectorState(r: ReflectorRow): string {
  if (!r.called) return 'skipped'
  if (r.missed) return 'missed'
  if (r.proposed) return 'proposed'
  return r.spoke ? 'spoke' : 'silent'
}

function Reflectors({ cycle, yesAt }: { cycle: ReflectionTrace; yesAt: number }) {
  const rows = reflectorRows(cycle)
  const [open, setOpen] = useState<string | null>(null)
  return (
    <ul className="reflectors">
      {rows.map((r) => {
        const state = reflectorState(r)
        const isOpen = open === r.name
        return (
          <li key={r.name} className={`reflector ${state}`} data-testid="reflector-row" data-reflector={r.name}>
            <button
              type="button"
              className="reflector-row"
              aria-expanded={isOpen}
              disabled={!r.called && r.blocked.length === 0}
              onClick={() => setOpen(isOpen ? null : r.name)}
            >
              <span className="reflector-name">{words(r.name)}</span>
              <span className="reflector-state" data-state={state}>
                {state === 'skipped' ? SLOW.skipped : state}
              </span>
              <Meter value={r.called ? r.speak : null} mark={yesAt} label={`${r.name} speak`} className="strip-meter" />
              <span className="reflector-answer">
                {!r.called
                  ? r.skipped
                  : r.missed
                    ? missWords(r.missReason)
                    : `${fmt(r.speak)} · ${r.change ? r.change : '–'}${r.changeP !== null ? ` (${pct(r.changeP)})` : ''} · ${words(r.reason)}`}
              </span>
            </button>
            {isOpen && (
              <div className="reflector-body">
                <p className="small muted">{SLOW.offered(r.offered.length)}</p>
                {r.blocked.length > 0 && (
                  <>
                    <p className="chips-label">{SLOW.blockedTitle}</p>
                    <ul className="blocked small">
                      {r.blocked.map((b) => (
                        <li key={b.change}>
                          <span className="mono">{b.change}</span>: {b.bound}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {r.result && (
                  <div className="reflector-grid">
                    <div>
                      <p className="chips-label">{SLOW.sawTitle}</p>
                      <EvidenceText text={r.result.evidence} name={r.name} testId="reflector-evidence" />
                    </div>
                    <div>
                      {r.missed && (
                        <div className="miss-box">
                          <p>
                            <strong>Missed:</strong> {missWords(r.missReason)}
                            {r.result.error ? ` (${r.result.error})` : ''}.
                          </p>
                          {r.result.raw_answer !== null && r.result.raw_answer !== undefined && (
                            <pre className="raw-answer">{JSON.stringify(r.result.raw_answer, null, 2)}</pre>
                          )}
                        </div>
                      )}
                      <p className="chips-label">{SLOW.changeTitle}</p>
                      <BarList
                        bars={bars(r.result.change_probabilities, r.result.change)}
                        label={`${r.name} change distribution`}
                        limit={8}
                        floor={0.03}
                      />
                      <p className="chips-label">{SLOW.reasonTitle}</p>
                      <BarList
                        bars={bars(r.result.reason_probabilities, r.result.reason)}
                        label={`${r.name} reason distribution`}
                      />
                    </div>
                  </div>
                )}
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function System2Central({ cycle }: { cycle: ReflectionTrace }) {
  const central = cycle.central
  const messages = cycle.messages ?? []
  return (
    <div className="system2-central" data-testid="system2-central">
      <p className="chips-label">{SLOW.proposalsTitle}</p>
      {messages.length === 0 ? (
        <p className="small muted">{SLOW.noProposals}</p>
      ) : (
        <ul className="heard">
          {messages.map((m) => (
            <li key={`${m.reflector}-${m.change}`}>
              the {words(m.reflector)} proposes <span className="mono">{m.change}</span> ({changeWords(m.change)}),
              strength {fmt(m.strength)}, reason {words(m.reason)}
            </li>
          ))}
        </ul>
      )}
      {central && (
        <>
          {central.missed ? (
            <div className="miss-box">
              <p>
                <strong>{SLOW.centralMissed}</strong> {missWords(central.miss_reason ?? null)}
                {central.error ? ` (${central.error})` : ''}
              </p>
              {central.raw_answer !== null && central.raw_answer !== undefined && (
                <pre className="raw-answer">{JSON.stringify(central.raw_answer, null, 2)}</pre>
              )}
            </div>
          ) : (
            <>
              <p className="chips-label">
                {SLOW.choiceTitle}: <span className="mono">{cycle.choice}</span>
                {cycle.tie ? ` (a tie with ${(cycle.tied ?? []).join(', ')}, broken by taking the first option)` : ''}
              </p>
              <BarList
                bars={bars(central.change_probabilities, central.change)}
                label="System 2’s central choice distribution"
              />
            </>
          )}
          <details className="saw">
            <summary>{SLOW.sawTitle}</summary>
            <EvidenceText text={central.evidence} name="system2_central" testId="system2-central-evidence" />
          </details>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------------------------

function ScopeLine({ scope, other, label, mark }: { scope: string[]; other: string[]; label: string; mark: string }) {
  return (
    <p className="scope-line">
      <span className="chips-label">{label}</span>{' '}
      {scope.map((c) => (
        <span key={c} className={`chip ${other.includes(c) ? 'on' : mark}`} data-channel={c}>
          {c}
        </span>
      ))}
    </p>
  )
}

const hitMark = (hit: boolean | null | undefined) => (hit === null || hit === undefined ? '–' : hit ? '✓' : '✗')

function HistoryTest({ test, bundle }: { test: HistoryTestResult; bundle: EpisodeBundle }) {
  const summary = testSummary(test)
  const episode = bundle.ticks[0]?.episode_id
  const openTick = (tick: number) => {
    const i = bundle.ticks.findIndex((t) => t.tick === tick)
    if (i < 0) return
    setTickIndex(i)
    openInstance(test.instance)
  }
  return (
    <div className="history-test">
      <p>
        <strong>{changeWords(test.change)}</strong> <span className="mono small">({test.change})</span>:{' '}
        <span className={`status-chip ${test.status}`} data-testid="test-verdict" data-status={test.status}>
          {test.status}
        </span>{' '}
        {test.reason}
      </p>
      <ScopeLine scope={test.old_scope} other={test.new_scope} label={SLOW.test.oldScope} mark="diff" />
      <ScopeLine scope={test.new_scope} other={test.old_scope} label={SLOW.test.newScope} mark="added" />
      {summary.ticks.length === 0 ? (
        <p className="small muted">{SLOW.test.waiting}</p>
      ) : (
        <>
          <p className="small muted">
            {SLOW.test.sample(summary.ticks.length, test.candidates)}: {summary.counts.bad} bad, {summary.counts.good}{' '}
            good, {summary.counts.rest} rest (seed {test.seed}).
          </p>
          <div className="table-wrap">
            <table className="data-table test-table" data-testid="test-table">
              <thead>
                <tr>
                  {SLOW.test.columns.map((c) => (
                    <th key={c} scope="col">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {summary.ticks.map((t) => (
                  <tr key={t.key} data-testid="test-row" data-stratum={t.stratum} className={`stratum-${t.stratum}`}>
                    <td>
                      {t.episode_id === episode ? (
                        <button type="button" className="link" onClick={() => openTick(t.tick)}>
                          decision {t.tick + 1}
                        </button>
                      ) : (
                        <span title={t.key}>
                          episode {t.episode_id.slice(0, 6)}, decision {t.tick + 1}
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={`stratum ${t.stratum}`}>{t.stratum}</span>
                    </td>
                    <td className="mono small context">{t.context}</td>
                    <td className="num">{fmt(t.n_step_return)}</td>
                    <td>{words(t.executed_action)}</td>
                    <td>{answerWords(t.old, test.kind)}</td>
                    <td>{answerWords(t.new, test.kind)}</td>
                    <td className="muted">{t.noise ? answerWords(t.noise, test.kind) : ''}</td>
                    <td className="num" title={t.old_hit ? SLOW.test.hit : SLOW.test.miss}>
                      {hitMark(t.old_hit)}
                    </td>
                    <td className="num" title={t.new_hit ? SLOW.test.hit : SLOW.test.miss}>
                      {hitMark(t.new_hit)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-wrap">
            <table className="data-table metrics-table" data-testid="test-metrics">
              <thead>
                <tr>
                  <th scope="col">{SLOW.test.metric}</th>
                  <th scope="col">{SLOW.test.old}</th>
                  <th scope="col">{SLOW.test.new}</th>
                </tr>
              </thead>
              <tbody>
                {summary.metrics.map((m) => (
                  <tr key={m.id} data-metric={m.id}>
                    <td>
                      <strong>{m.label}</strong>{' '}
                      <span className="small muted">
                        on {m.stratum} decisions: {m.rule}
                      </span>
                    </td>
                    <td className="num">{fmt(m.old)}</td>
                    <td className="num">{fmt(m.new)}</td>
                  </tr>
                ))}
                <tr className="total" data-metric="composite">
                  <td>
                    <strong>{SLOW.test.composite}</strong> <span className="small muted">the mean of the metrics</span>
                  </td>
                  <td className="num">{fmt(test.old?.composite)}</td>
                  <td className="num">{fmt(test.new?.composite)}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <ul className="facts small">
            <li>
              {SLOW.test.gain(
                test.composite_gain === null || test.composite_gain === undefined
                  ? '–'
                  : `${test.composite_gain >= 0 ? '+' : ''}${fmt(test.composite_gain)}`,
                fmt(test.margin),
              )}
            </li>
            <li>{SLOW.test.drop(fmt(test.worst_drop), fmt(test.worst_allowed))}</li>
            {test.noise_agreement !== null && test.noise_agreement !== undefined && (
              <li>{SLOW.test.noise(pct(test.noise_agreement), test.noise_ticks)}</li>
            )}
            {test.calls !== undefined && (
              <li>
                {test.calls} d1-ultra calls{test.usage?.cost !== undefined ? `, $${test.usage.cost.toFixed(5)}` : ''}
              </li>
            )}
          </ul>
        </>
      )}
      {test.limits && <p className="small muted">{test.limits}</p>}
    </div>
  )
}

function Trial({
  bundle,
  cycle,
  verdict,
  timeline,
  tickIndex,
}: {
  bundle: EpisodeBundle
  cycle: ReflectionTrace
  verdict: TrialVerdictTrace | null
  timeline: VersionEntry[]
  tickIndex: number
}) {
  if (!verdict) {
    const started = bundle.records
      .filter(isNote)
      .find((n) => n.kind === 'trial_started' && n.cycle_id === cycle.cycle_id)
    const entry = timeline.find((e) => e.cycle === cycle)
    const at = configurationAt(bundle, timeline, tickIndex)
    return (
      <p className="small" data-testid="trial-in-flight">
        {started
          ? at.trial && at.trial.entry === entry
            ? SLOW.trial.inFlight(at.trial.decisions, at.trial.of)
            : started.detail
          : cycle.applied?.queued
            ? `${changeWords(cycle.applied.change)}: queued. Its trial starts when the change takes effect.`
            : SLOW.trial.noTrial}
      </p>
    )
  }
  const trial = verdict.trial
  const table = trial.table
  return (
    <div className="trial-view">
      <p>
        <strong>{changeWords(trial.change)}</strong>, version {trial.previous_version} → {trial.version}, in effect from
        decision {trial.started_tick + 1}:{' '}
        <span className={`status-chip ${trial.verdict ?? ''}`} data-testid="trial-verdict" data-verdict={trial.verdict}>
          {trial.verdict ?? 'no verdict'}
        </span>{' '}
        {trial.by && SLOW.trial.by(trial.by)}
        {trial.safety_revert ? `: ${SLOW.trial.safety}` : ''}.
      </p>
      {table && (
        <div className="table-wrap">
          <table className="data-table trial-table" data-testid="trial-table">
            <thead>
              <tr>
                <th scope="col" />
                <th scope="col">{SLOW.trial.before}</th>
                <th scope="col">{SLOW.trial.during}</th>
              </tr>
            </thead>
            <tbody>
              {TRIAL_ROWS.filter((r) => table.before[r.key] !== undefined || table.during[r.key] !== undefined).map(
                (r) => (
                  <tr key={r.key}>
                    <th scope="row">{r.label}</th>
                    <td className="num">{fmt(table.before[r.key], r.digits)}</td>
                    <td className="num">{fmt(table.during[r.key], r.digits)}</td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
      {table?.prediction && <p className="small muted">The history test predicted: {table.prediction}</p>}
      {(trial.judge ?? []).map((j, i) => (
        <div key={i} className="judge">
          <p className="chips-label">
            {SLOW.trial.judgeTitle}
            {(trial.judge ?? []).length > 1 ? `, ${SLOW.trial.attempt(i + 1)}` : ''}
          </p>
          {j.missed ? (
            <p className="miss-box">
              <strong>Missed:</strong> {missWords(j.miss_reason ?? null)}
            </p>
          ) : (
            <BarList bars={bars(j.verdict_probabilities, j.verdict)} label="The judge’s verdict distribution" />
          )}
          <details className="saw">
            <summary>{SLOW.trial.sawTitle}</summary>
            <EvidenceText text={j.evidence} name="trial_judge" testId="judge-evidence" />
          </details>
        </div>
      ))}
      {trial.revert && (
        <p className="small">
          {SLOW.trial.revert} version {trial.revert.new_version}: {(trial.revert.changes ?? []).join('; ')}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------------------------

const LEDGER_ROWS = 12

function Ledger({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const [sense, setSense] = useState<string>('all')
  const [all, setAll] = useState(false)
  const ledger = bundle.relevance
  const { return_steps, return_gamma } = boundsOf(bundle.meta)
  const added = useMemo(
    () => episodeEntries(bundle.ticks, ledger?.return_steps ?? return_steps, ledger?.return_gamma ?? return_gamma),
    [bundle.ticks, ledger, return_steps, return_gamma],
  )
  if (!ledger) return <p className="muted small">{SLOW.ledger.none}</p>
  const totals = senseTotals(ledger.entries)
  const rows = ledgerRows(ledger.entries).filter((r) => sense === 'all' || r.sense === sense)
  const shown = all ? rows : rows.slice(0, LEDGER_ROWS)
  const central = tick.instances[CENTRAL]
  const relevance = central ? sections(central.evidence).find((s) => s.channel === 'relevance') : undefined
  return (
    <div className="ledger">
      <p className="small muted">
        The ledger after {ledger.episodes ?? 0} episode{ledger.episodes === 1 ? '' : 's'} in this run folder. Paid off
        means the decision’s {ledger.return_steps ?? return_steps}-step return (discount{' '}
        {ledger.return_gamma ?? return_gamma}) was positive.
      </p>
      <div className="table-wrap">
        <table className="data-table" data-testid="ledger-totals">
          <caption>{SLOW.ledger.totals}</caption>
          <thead>
            <tr>
              {SLOW.ledger.columns
                .filter((c) => c !== 'Situation')
                .map((c) => (
                  <th key={c} scope="col">
                    {c}
                  </th>
                ))}
            </tr>
          </thead>
          <tbody>
            {SENSES.map((s) => {
              const c = totals[s]
              if (!c) return null
              return (
                <tr key={s} data-sense={s}>
                  <th scope="row">
                    <span className={`dot sense-${s}`} aria-hidden /> {s}
                  </th>
                  <CountCells c={c} />
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="ledger-filter segmented" role="group" aria-label="Sense">
        {['all', ...SENSES].map((s) => (
          <button key={s} type="button" aria-pressed={sense === s} onClick={() => setSense(s)}>
            {s === 'all' ? SLOW.ledger.all : s}
          </button>
        ))}
      </div>
      <div className="table-wrap">
        <table className="data-table ledger-table">
          <caption>{SLOW.ledger.contexts}</caption>
          <thead>
            <tr>
              {SLOW.ledger.columns.map((c) => (
                <th key={c} scope="col">
                  {c}
                </th>
              ))}
              <th scope="col">{SLOW.ledger.added}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const here = r.context === tick.context_signature
              const plus = added[`${r.sense}|${r.context}`]
              return (
                <tr
                  key={`${r.sense}|${r.context}`}
                  data-testid="ledger-row"
                  data-sense={r.sense}
                  className={here ? 'here' : undefined}
                  title={here ? SLOW.ledger.here : undefined}
                >
                  <th scope="row">
                    <span className={`dot sense-${r.sense}`} aria-hidden /> {r.sense}
                  </th>
                  <td className="mono small context">
                    {r.context}
                    {here ? ' ◀' : ''}
                  </td>
                  <CountCells c={r.counts} />
                  <td className="num muted">{plus ? `+${plus.spoke}` : ''}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {rows.length > LEDGER_ROWS && (
        <button type="button" className="link" onClick={() => setAll(!all)}>
          {all ? SLOW.ledger.showFewer : SLOW.ledger.showAll(rows.length)}
        </button>
      )}
      <p className="chips-label">{relevance ? SLOW.ledger.centralSaw : SLOW.ledger.noRelevance}</p>
      {relevance && <EvidenceText text={`[relevance]\n${relevance.body}`} name={CENTRAL} testId="central-relevance" />}
    </div>
  )
}

function CountCells({ c }: { c: Counts }) {
  const paid = paidRate(c)
  const over = overruledRate(c)
  const strong = meanStrength(c.strength_paid_sum, c.strength_paid_n)
  const weak = meanStrength(c.strength_unpaid_sum, c.strength_unpaid_n)
  return (
    <>
      <td className="num">{c.spoke}</td>
      <td className="num">{c.followed}</td>
      <td className="num">
        {c.followed_paid} {paid !== null && <span className="muted">({pct(paid)})</span>}
      </td>
      <td className="num">{c.overruled}</td>
      <td className="num">
        {c.overruled_paid} {over !== null && <span className="muted">({pct(over)})</span>}
      </td>
      <td className="num" title="mean strength on decisions that paid off / on decisions that did not">
        {fmt(strong)} / {fmt(weak)}
      </td>
    </>
  )
}

function ConfigurationChanges({ bundle }: { bundle: EpisodeBundle }) {
  const ch = configurationChanges(bundle.meta)
  const a = bundle.meta.configuration_start.version ?? 1
  const b = bundle.meta.configuration_end.version ?? a
  const list = (xs: string[]) => (xs.length ? xs.map(words).join(', ') : SLOW.changes.none)
  return (
    <div className="config-changes">
      <p className="small muted">
        Version {a} at the start, version {b} at the end.
      </p>
      <div className="table-wrap">
        <table className="data-table" data-testid="configuration-changes">
          <thead>
            <tr>
              <th scope="col">{SLOW.changes.instance}</th>
              <th scope="col">{SLOW.changes.start}</th>
              <th scope="col">{SLOW.changes.end}</th>
            </tr>
          </thead>
          <tbody>
            {ch.scopes.map((s) => (
              <tr key={s.instance} data-instance={s.instance}>
                <th scope="row">
                  <span className={`dot sense-${s.instance}`} aria-hidden />{' '}
                  <TermLink id={s.instance === CENTRAL ? 'central' : 'sense'} text={s.instance} />
                </th>
                <td>
                  {s.start.map((c) => (
                    <span key={c} className={`chip ${s.removed.includes(c) ? 'diff' : 'on'}`}>
                      {c}
                    </span>
                  ))}
                </td>
                <td>
                  {s.end.map((c) => (
                    <span key={c} className={`chip ${s.added.includes(c) ? 'added' : 'on'}`}>
                      {s.added.includes(c) ? `+ ${c}` : c}
                    </span>
                  ))}
                  {s.removed.map((c) => (
                    <span key={c} className="chip diff">
                      − {c}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
            <tr>
              <th scope="row">{SLOW.changes.macros}</th>
              <td>{list(ch.macrosStart)}</td>
              <td>{list(ch.macrosEnd)}</td>
            </tr>
            <tr>
              <th scope="row">{SLOW.changes.strategy}</th>
              <td>{words(ch.strategy[0]) || SLOW.changes.none}</td>
              <td>{words(ch.strategy[1]) || SLOW.changes.none}</td>
            </tr>
            <tr>
              <th scope="row">{SLOW.changes.level}</th>
              <td>{ch.level[0]}</td>
              <td>{ch.level[1]}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
