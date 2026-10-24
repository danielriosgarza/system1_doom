import type { TickTrace } from '../schema/bundle'
import { type Admission, fmt, prettyId, prunedReasonText } from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import { setState, useApp } from '../store'
import { Tip } from './Panel'

function stageWord(stage: { passed: boolean; skipped?: boolean }): string {
  return stage.skipped ? 'skipped' : stage.passed ? 'passed' : 'failed'
}

export function LegalActions({
  bundle,
  tick,
  admitted,
}: {
  bundle: EpisodeBundle
  tick: TickTrace
  admitted: Admission[]
}) {
  const hovered = useApp((s) => s.hoveredAction)
  const depth = useApp((s) => s.depth)
  const legal = new Set(tick.available_actions)
  const pruned = tick.pruned_actions ?? {}
  const entries = Object.entries(bundle.meta.actions)
  const groups = [
    { label: 'Primitives: one button each', items: entries.filter(([, a]) => !a.is_macro && a.builtin) },
    { label: 'Built-in macros: fixed sequences', items: entries.filter(([, a]) => a.is_macro && a.builtin) },
    { label: 'Written by the slow path during this episode', items: entries.filter(([, a]) => !a.builtin) },
  ].filter((g) => g.items.length > 0)

  return (
    <div className="chips" role="list" aria-label="Action vocabulary">
      {groups.map((group) => (
        <div key={group.label} style={{ display: 'contents' }}>
          <p className="chip-group-label">{group.label}</p>
          {group.items.map(([id, action]) => {
            const admission = admitted.find((a) => a.actionId === id && a.admitted)
            const stages = admission?.proposal.stage_results ?? []
            const isLegal = legal.has(id)
            const reason = pruned[id]
            const future = !isLegal && reason === undefined
            const cls = [
              'chip',
              isLegal ? 'legal' : future ? 'future' : 'pruned',
              id === tick.selected_action ? 'selected' : '',
              id === hovered ? 'hovered' : '',
            ].join(' ')
            const body = (
              <>
                <strong>{prettyId(id)}</strong>
                <div className="muted">{action.description}</div>
                <div>
                  Plan: {action.primitives.map(prettyId).join(' → ')}
                  {depth === 'formula' && (
                    <span className="muted"> · execution cost {fmt(action.execution_cost, 2)}</span>
                  )}
                </div>
                {isLegal && <div>Legal this tick.</div>}
                {reason !== undefined && <div>Pruned: {prunedReasonText(reason, action, tick.state)}.</div>}
                {admission && (
                  <div>
                    Written by the slow path ({admission.source === 'codex' ? 'Codex' : 'fallback template'}) for the{' '}
                    {admission.module ?? 'unknown'} module; joined the menu at tick {admission.tick ?? '?'}.
                  </div>
                )}
                {admission && stages.length > 0 && (
                  <div>
                    Gate: {stages.map((s) => `${s.stage} ${stageWord(s)}`).join(' → ')}
                    {depth === 'formula' &&
                      stages.map((s) => (
                        <div key={s.stage} className="muted">
                          {s.stage}: {s.reason}
                        </div>
                      ))}
                  </div>
                )}
                {future && <div>Not in the vocabulary yet at this tick.</div>}
              </>
            )
            return (
              <Tip key={id} body={body}>
                <span
                  role="listitem"
                  className={cls}
                  data-action={id}
                  data-state={isLegal ? 'legal' : future ? 'future' : 'pruned'}
                  onMouseEnter={() => isLegal && setState({ hoveredAction: id })}
                  onMouseLeave={() => setState({ hoveredAction: null })}
                >
                  {prettyId(id)}
                  {admission && <span className="badge">new · t{admission.tick ?? '?'}</span>}
                </span>
              </Tip>
            )
          })}
        </div>
      ))}
    </div>
  )
}
