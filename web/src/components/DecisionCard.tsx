import { Fragment, type ReactNode } from 'react'
import { EXPLAINERS, type ExplainerContext, type ExplainerId, type PanelId } from '../content/explainers'
import type { Candidate, LevelChip } from '../data/derive'
import { openInInspector, setState, useApp } from '../store'
import { BoundBadges, ExplainerBody, Tip } from './Panel'

export interface DecisionCardProps {
  /** The level's id; the card is `#level-<id>`. */
  id: string
  /** Position in the tower, slowest first. */
  index: number
  title: string
  explainer: ExplainerId
  bounds: string[]
  menuSize: number
  chips: LevelChip[]
  candidates: Candidate[]
  choiceLabel: string
  rule: string
  reads: string
  writes: string
  idle?: boolean
  expanded: boolean
  onToggle: () => void
  ctx: ExplainerContext
  /** The inspector panel that shows this level in detail. */
  panel?: PanelId
  /** Chips and candidates are action ids, so pointing at one highlights it everywhere. */
  actions?: boolean
  /** Replaces the bars when a level's scores are not one number per option. */
  scores?: ReactNode
  /** Shown only when the card is expanded. */
  detail?: ReactNode
}

function Bar({ c, hovered, actions }: { c: Candidate; hovered: boolean; actions: boolean }) {
  const cls = ['dc-row', c.chosen ? 'chosen' : '', c.failed ? 'failed' : '', hovered ? 'row-hover' : ''].join(' ')
  const row = (
    <div
      className={cls}
      data-candidate={c.id}
      onMouseEnter={actions ? () => setState({ hoveredAction: c.id }) : undefined}
      onMouseLeave={actions ? () => setState({ hoveredAction: null }) : undefined}
    >
      <span className="dc-label" title={c.label}>
        {c.chosen && <span className="pick-mark" aria-label="chosen" />}
        {c.label}
      </span>
      <span className="dc-track">
        <span className={`dc-fill ${c.style}`} style={{ width: `${Math.max(0, Math.min(1, c.share)) * 100}%` }} />
      </span>
      <span className="dc-value">{c.value}</span>
    </div>
  )
  return c.note ? (
    <Tip body={c.note} className="dc-tip">
      {row}
    </Tip>
  ) : (
    row
  )
}

/**
 * The one shape every level of the hierarchy takes: a short menu, a score per option, one rule that
 * chooses, and the bounds it works under.
 */
export function DecisionCard(props: DecisionCardProps) {
  const { id, index, title, explainer, chips, candidates, expanded, actions = false, ctx } = props
  const hovered = useApp((s) => s.hoveredAction)
  const sentence = EXPLAINERS[explainer].sentence
  return (
    <section
      className={`decision-card ${props.idle ? 'idle' : ''} ${expanded ? 'expanded' : ''}`}
      id={`level-${id}`}
      data-level={id}
      aria-label={title}
    >
      <header className="dc-head">
        <button type="button" className="dc-toggle" aria-expanded={expanded} onClick={props.onToggle}>
          <span className="level-num" aria-hidden>
            {index}
          </span>
          <h3>{title}</h3>
          <span className="dc-caret" aria-hidden>
            {expanded ? '▾' : '▸'}
          </span>
        </button>
        <span className="dc-menu" title="How many options this level chose from this tick">
          menu {props.menuSize}
        </span>
        <span className="dc-choice" data-testid="choice">
          → {props.choiceLabel}
        </span>
      </header>
      {expanded && <p className="sentence">{sentence}</p>}
      <BoundBadges bounds={props.bounds} />
      {chips.length > 0 && (
        <div className="chips dc-chips" aria-label="This level's menu">
          {chips.map((chip) => {
            const cls = [
              'chip',
              chip.state === 'pruned' ? 'pruned' : 'legal',
              chip.state === 'chosen' ? 'selected' : '',
              actions && chip.id === hovered ? 'hovered' : '',
            ].join(' ')
            const el = (
              <span
                className={cls}
                data-action={actions ? chip.id : undefined}
                onMouseEnter={
                  actions && chip.state !== 'pruned' ? () => setState({ hoveredAction: chip.id }) : undefined
                }
                onMouseLeave={actions ? () => setState({ hoveredAction: null }) : undefined}
              >
                {chip.label}
              </span>
            )
            return chip.note ? (
              <Tip key={chip.id} body={chip.note}>
                {el}
              </Tip>
            ) : (
              <Fragment key={chip.id}>{el}</Fragment>
            )
          })}
        </div>
      )}
      {props.scores ??
        (candidates.length > 0 && (
          <div className={`dc-bars ${expanded ? 'full' : ''}`}>
            {candidates.map((c) => (
              <Bar key={c.id} c={c} hovered={actions && c.id === hovered} actions={actions} />
            ))}
          </div>
        ))}
      <p className="dc-rule">
        <span className="dc-key">Rule</span> {props.rule}
      </p>
      <p className="dc-io">
        <span className="dc-key">Reads</span> {props.reads} <span className="dc-key">Writes</span> {props.writes}
      </p>
      {expanded && (
        <div className="dc-detail">
          {props.detail}
          <ExplainerBody id={explainer} ctx={ctx} />
          {props.panel && (
            <button type="button" className="link-button" onClick={() => openInInspector(props.panel as string)}>
              See this in the inspector →
            </button>
          )}
        </div>
      )}
    </section>
  )
}
