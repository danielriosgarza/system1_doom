import {
  MAX_MACRO_STEPS,
  type RequestSpan,
  preconditionWords,
  prettyId,
  proposalId,
  proposalShown,
  requestContext,
} from '../data/derive'
import type { ProposalTrace, TickTrace } from '../schema/bundle'

interface ParsedMacro {
  id?: string
  description?: string
  primitive_expansion?: string[]
  preconditions?: Record<string, unknown>
  maximum_duration?: number
  termination_condition?: string
  strategy_id?: string
}

function pretty(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

function sourceWords(p: ProposalTrace): string {
  return p.source === 'codex' ? 'Codex' : p.source === 'template' ? 'the fallback template' : 'a custom generator'
}

/** The proposal that reached the gate at this tick, or the last one before it: the ask, the text, the macro. */
export function ProposalCard({
  tick,
  proposals,
  spans,
}: {
  tick: TickTrace
  proposals: ProposalTrace[]
  spans: RequestSpan[]
}) {
  const shown = proposalShown(tick, proposals)
  if (!shown) {
    const pending = spans.find((s) => s.asked <= tick.tick && (s.arrived === null || s.arrived > tick.tick))
    return (
      <p className="empty-note">
        {pending
          ? `${pending.module} asked at tick ${pending.asked}: “${pending.description}” The worker is writing; ${pending.arrived === null ? 'no answer reached the gate in this recording' : `the proposal reaches the gate at tick ${pending.arrived}`}.`
          : spans.length > 0
            ? `No proposal has reached the gate yet; the first request comes at tick ${spans[0]?.asked}.`
            : 'No module asked for a macro in this recording, so no proposal was written.'}
      </p>
    )
  }
  const { proposal: p, current } = shown
  const ask = requestContext(p)
  const span = spans.find((s) => s.proposal === p)
  const parsed = (p.parsed_proposal ?? null) as ParsedMacro | null
  const plan = parsed?.primitive_expansion ?? []
  const conditions = preconditionWords(parsed?.preconditions)
  return (
    <article className={`proposal-card ${current ? '' : 'earlier'}`} data-proposal={proposalId(p)}>
      {!current && <p className="pc-when">Arrived at tick {p.tick}; nothing new has reached the gate since.</p>}
      <blockquote className="pc-ask">
        “{ask.description}”
        <footer>
          the {ask.module} module{span ? `, at tick ${span.asked}` : ''}
        </footer>
      </blockquote>
      <p className="pc-source">
        Written by <strong data-testid="proposal-source">{sourceWords(p)}</strong> for the{' '}
        <strong>{p.source_module ?? ask.module}</strong> module; it reached the gate at tick {p.tick}.
      </p>
      <details className="pc-raw">
        <summary>The text as the worker returned it</summary>
        <pre>{pretty(p.raw_proposal)}</pre>
      </details>
      {parsed ? (
        <dl className="pc-fields">
          <dt>id</dt>
          <dd className="mono">{parsed.id}</dd>
          <dt>does</dt>
          <dd>{parsed.description}</dd>
          <dt>presses</dt>
          <dd className="pc-plan">
            {plan.map((prim, i) => (
              <span key={`${prim}-${i}`} className="chip legal">
                {prettyId(prim)}
              </span>
            ))}
            <span className="muted">
              {' '}
              {plan.length} of at most {MAX_MACRO_STEPS} steps
            </span>
          </dd>
          <dt>legal only with</dt>
          <dd>{conditions.length > 0 ? conditions.join(', ') : 'no preconditions beyond the defaults'}</dd>
          <dt>lasts at most</dt>
          <dd>{parsed.maximum_duration} steps</dd>
          <dt>stops when</dt>
          <dd>{prettyId(parsed.termination_condition ?? '')}</dd>
          <dt>strategy</dt>
          <dd className="mono">{parsed.strategy_id}</dd>
        </dl>
      ) : (
        <p className="empty-note">The text did not parse into a macro, so nothing else was read from it.</p>
      )}
    </article>
  )
}
