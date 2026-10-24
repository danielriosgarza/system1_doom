import {
  ENCODING_LABELS,
  admissions,
  encodeAction,
  fmt,
  prettyId,
  proposalShown,
  prunedReasonText,
} from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import type { TickTrace } from '../schema/bundle'
import { useApp } from '../store'
import { LegalActions } from './LegalActions'

/** The built-in macro the new one is set beside: both are the same kind of thing. */
const REFERENCE = 'weave_fire'

/** The menu on the tick before the proposal arrived and on the tick it arrived, then the 12 numbers. */
export function VocabularyDiff({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const depth = useApp((s) => s.depth)
  const shown = proposalShown(tick, bundle.proposals)
  if (!shown)
    return (
      <p className="empty-note">
        {bundle.proposals.length === 0
          ? 'No proposal reached the gate in this recording, so the menu never changed.'
          : `No proposal has reached the gate yet; the first arrives at tick ${bundle.proposals[0]?.tick ?? '?'}.`}
      </p>
    )
  const p = shown.proposal
  const index = bundle.ticks.findIndex((t) => t.tick === p.tick)
  const before = bundle.ticks[index - 1]
  const at = bundle.ticks[index]
  const id = p.admission_decision ? (p.admitted_action_id ?? null) : null
  const admitted = admissions(bundle.proposals)
  const rows = [
    { label: `Tick ${before?.tick ?? '?'}, before`, trace: before, ring: undefined },
    { label: `Tick ${at?.tick ?? '?'}, it arrived`, trace: at, ring: id ?? undefined },
  ]
  const sameLegal =
    !!before &&
    !!at &&
    before.available_actions.length === at.available_actions.length &&
    before.available_actions.every((a) => at.available_actions.includes(a))
  const compared = [id, REFERENCE].flatMap((a) => {
    const action = a ? bundle.meta.actions[a] : undefined
    return a && action ? [{ id: a, action }] : []
  })
  const reason = id && at ? at.pruned_actions?.[id] : undefined
  return (
    <div className="vocab-diff">
      {rows.map(({ label, trace, ring }) =>
        trace ? (
          <div key={label} className="vd-row" data-tick={trace.tick}>
            <p className="vd-label">{label}</p>
            <LegalActions bundle={bundle} tick={trace} admitted={admitted} highlight={ring} />
          </div>
        ) : null,
      )}
      <p className="dc-note">
        {id
          ? `One chip more: ${prettyId(id)} joined the vocabulary at tick ${p.tick}${reason ? `, but was not legal on that tick: it ${prunedReasonText(reason, bundle.meta.actions[id], at?.state).replace(/^only /, 'is only legal ')}` : ''}. ${sameLegal ? 'The legal actions are the same on both ticks.' : 'The legal actions also changed with the situation.'}`
          : 'The gate rejected this proposal, so the menu did not change.'}
      </p>
      {compared.length > 0 && (
        <div className="encoding-wrap">
          <table className="encoding-table">
            <caption>
              The 12 numbers the networks know an action by. Actions are described by what they press, not by their
              name, so the networks can score a macro the moment it is admitted.
            </caption>
            <thead>
              <tr>
                <th scope="col">action</th>
                {ENCODING_LABELS.map((l) => (
                  <th key={l} scope="col">
                    <span>{l}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {compared.map(({ id: a, action }) => {
                const numbers = action.encoding ?? encodeAction(action.primitives, action.is_macro)
                return (
                  <tr key={a} data-action={a} className={a === id ? 'is-new' : ''}>
                    <th scope="row">
                      {prettyId(a)}
                      <span className="muted">{action.builtin ? 'built in' : `new at tick ${p.tick}`}</span>
                    </th>
                    {numbers.map((v, i) => (
                      <td key={i} className={`num ${v === 0 ? 'zero' : ''}`}>
                        {fmt(v, 2)}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {depth === 'formula' &&
        compared.map(({ id: a, action }) => (
          <p key={a} className="mono dc-note">
            {prettyId(a)}: {action.primitives.map(prettyId).join(', ')} → {action.primitives.length} steps;{' '}
            {encodeAction(action.primitives, action.is_macro)
              .slice(0, 8)
              .map((v, i) =>
                v > 0
                  ? `${ENCODING_LABELS[i]} ${fmt(v * action.primitives.length, 0)}/${action.primitives.length}`
                  : null,
              )
              .filter(Boolean)
              .join(', ')}
            ; length {action.primitives.length} ÷ 16 = {fmt(action.primitives.length / 16, 2)}; macro{' '}
            {action.is_macro ? 1 : 0}
          </p>
        ))}
    </div>
  )
}
