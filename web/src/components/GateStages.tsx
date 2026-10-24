import { prettyId, proposalId, slowPathAt } from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import type { TickTrace } from '../schema/bundle'

/** The five admission stages of the proposal that reached the gate this tick, as a row. */
export function GatePipeline({ tick, proposals }: { tick: TickTrace; proposals: EpisodeBundle['proposals'] }) {
  const slow = slowPathAt(tick, proposals)
  const proposal = slow.arrived[0]
  if (!proposal) {
    return slow.request ? (
      <p className="dc-note">
        <strong>{slow.request.module}</strong> asked: “{slow.request.description}”
      </p>
    ) : null
  }
  return (
    <ol className="pipeline" aria-label={`The five stages for ${prettyId(proposalId(proposal))}`}>
      {(proposal.stage_results ?? []).map((s) => (
        <li
          key={s.stage}
          className={`stage ${s.skipped ? 'skipped' : s.passed ? 'passed' : 'failed'}`}
          title={s.reason}
          data-stage={s.stage}
        >
          <span className="stage-name">{s.stage}</span>
          <span className="stage-result">{s.skipped ? 'skipped' : s.passed ? 'passed' : 'failed'}</span>
        </li>
      ))}
    </ol>
  )
}

/** Who wrote the proposal that reached the gate this tick, its plan, and each stage's reason. */
export function GateDetail({ tick, proposals }: { tick: TickTrace; proposals: EpisodeBundle['proposals'] }) {
  const slow = slowPathAt(tick, proposals)
  const proposal = slow.arrived[0]
  if (!proposal) return null
  const parsed = (proposal.parsed_proposal ?? {}) as { description?: string; primitive_expansion?: string[] }
  return (
    <div className="dc-note">
      <p>
        <strong>{prettyId(proposalId(proposal))}</strong>, written by the {proposal.source_module ?? 'unknown'} module’s
        request ({proposal.source === 'codex' ? 'Codex' : 'fallback template'}): {parsed.description}
      </p>
      {parsed.primitive_expansion && <p>Plan: {parsed.primitive_expansion.map(prettyId).join(' → ')}</p>}
      <ul className="stage-reasons">
        {(proposal.stage_results ?? []).map((s) => (
          <li key={s.stage}>
            <strong>{s.stage}</strong>: {s.reason}
          </li>
        ))}
      </ul>
    </div>
  )
}
