import { useState } from 'react'
import type { ExplainerContext } from '../content/explainers'
import {
  MAX_MACRO_STEPS,
  type RequestSpan,
  SANDBOX_CRITICAL_HEALTH,
  fmt,
  gateLevel,
  proposalShown,
} from '../data/derive'
import type { ProposalTrace, TickTrace } from '../schema/bundle'
import { DecisionCard } from './DecisionCard'
import { GatePipeline } from './GateStages'

const SANDBOX_ROWS: Array<{ key: string; label: string; digits: number }> = [
  { key: 'survival_probability', label: 'survival probability', digits: 2 },
  { key: 'expected_value', label: 'expected value', digits: 2 },
  { key: 'expected_damage_taken', label: 'expected damage taken', digits: 1 },
  { key: 'expected_damage_dealt', label: 'expected damage dealt', digits: 1 },
  { key: 'depth_reached', label: 'depth reached', digits: 0 },
  { key: 'empirical_samples', label: 'real outcomes used', digits: 0 },
]

/** The hierarchy's gate card for the proposal shown, with the sandbox's numbers and the rule they met. */
export function AdmissionGate({
  ticks,
  tick,
  proposals,
  spans,
  ctx,
}: {
  ticks: TickTrace[]
  tick: TickTrace
  proposals: ProposalTrace[]
  spans: RequestSpan[]
  ctx: ExplainerContext
}) {
  const [expanded, setExpanded] = useState(false)
  const shown = proposalShown(tick, proposals)
  const at = shown ? ticks.find((t) => t.tick === shown.proposal.tick) : undefined
  if (!shown || !at)
    return (
      <p className="empty-note">
        {proposals.length === 0
          ? 'No proposal reached the gate in this recording.'
          : `No proposal has reached the gate yet; the first arrives at tick ${proposals[0]?.tick ?? '?'}.`}
      </p>
    )
  const p = shown.proposal
  const level = gateLevel(at, proposals)
  const sandbox = p.sandbox_summary ?? null
  const span = spans.find((s) => s.proposal === p)
  const asked = span ? ticks.find((t) => t.tick === span.asked) : undefined
  const health = asked?.state?.health ?? null
  const survival = sandbox?.survival_probability ?? null
  return (
    <div className={`admission-gate ${shown.current ? '' : 'earlier'}`}>
      <DecisionCard
        id="gate"
        index={1}
        title={`The gate at tick ${at.tick}`}
        explainer="gate"
        bounds={level.bounds}
        menuSize={level.menuSize}
        chips={level.menu}
        candidates={level.candidates}
        choiceLabel={level.choiceLabel}
        rule={level.rule}
        reads={level.reads}
        writes={level.writes}
        expanded={expanded}
        onToggle={() => setExpanded(!expanded)}
        ctx={ctx}
        scores={<GatePipeline tick={at} proposals={proposals} />}
      />
      <ol className="stage-reasons gate-reasons">
        {(p.stage_results ?? []).map((s) => (
          <li key={s.stage} data-stage={s.stage}>
            <strong>{s.stage}</strong>{' '}
            <span className="muted">{s.skipped ? 'skipped' : s.passed ? 'passed' : 'failed'}</span>: {s.reason}
            {s.stage === 'legality' && (
              <span className="muted">
                {' '}
                Bounds: a well-formed id that is not a primitive’s, known primitives only, at most {
                  MAX_MACRO_STEPS
                }{' '}
                steps, and no more than its own maximum duration.
              </span>
            )}
          </li>
        ))}
      </ol>
      {sandbox && (
        <div className="sandbox">
          <p className="sandbox-head">
            The sandbox rollout: the bounded simulator plays the macro from the state in which it was asked for.
          </p>
          <table className="sandbox-table">
            <tbody>
              {SANDBOX_ROWS.filter((r) => r.key in sandbox).map((r) => (
                <tr key={r.key}>
                  <th scope="row">{r.label}</th>
                  <td className="num">{fmt(sandbox[r.key] ?? 0, r.digits)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="dc-note">
            The sandbox fails a macro only when the rollout predicts death (survival 0) from a state that was not
            already critical, above {SANDBOX_CRITICAL_HEALTH} health.{' '}
            {health !== null && survival !== null && (
              <>
                Health when {span?.module ?? 'the module'} asked was {fmt(health, 0)}
                {health > SANDBOX_CRITICAL_HEALTH
                  ? `, so a predicted death would have failed it; survival was ${fmt(survival, 2)}, so ${survival > 0 ? 'it passed' : 'it failed'}.`
                  : `, already critical, so the sandbox could not fail it whatever it predicted (survival ${fmt(survival, 2)}).`}
              </>
            )}
          </p>
        </div>
      )}
    </div>
  )
}
