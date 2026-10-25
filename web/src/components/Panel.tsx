import { type ReactNode, useId, useState } from 'react'
import { EXPLAINERS, type PanelId } from '../content/explainers'

/** A panel: its title, the one-sentence explainer, a toggle for the rest, and its content. */
export function Panel({
  id,
  children,
  className,
  aside,
}: {
  id: PanelId
  children: ReactNode
  className?: string
  /** Something small at the right of the header: a count, a status. */
  aside?: ReactNode
}) {
  const explainer = EXPLAINERS[id]
  const [open, setOpen] = useState(false)
  const headingId = useId()
  const bodyId = useId()
  return (
    <section className={`panel ${className ?? ''}`} id={`panel-${id}`} aria-labelledby={headingId}>
      <header className="panel-head">
        <h2 id={headingId}>{explainer.title}</h2>
        <span className="spacer" />
        {aside}
        <button
          type="button"
          className="explain-toggle"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen(!open)}
          title={open ? 'Hide the explanation' : 'Explain this panel'}
        >
          {open ? 'Hide' : '?'}
        </button>
      </header>
      <p className="sentence">{explainer.sentence}</p>
      {open && <ExplainerBody id={id} bodyId={bodyId} />}
      {children}
    </section>
  )
}

/** The explanation behind a panel's "?": its paragraphs, its formula where it has one, and the code. */
export function ExplainerBody({ id, bodyId }: { id: PanelId; bodyId?: string }) {
  const explainer = EXPLAINERS[id]
  return (
    <div className="explainer" id={bodyId}>
      {explainer.paragraphs.map((p) => (
        <p key={p.slice(0, 40)}>{p}</p>
      ))}
      {'formula' in explainer && explainer.formula && <p className="formula mono">{explainer.formula}</p>}
      <p className="code-ref">
        In the code: <code>{explainer.code}</code>
      </p>
    </div>
  )
}
