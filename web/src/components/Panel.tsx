import { type ReactNode, useId, useState } from 'react'
import { BOUNDS, EXPLAINERS, type ExplainerContext, type ExplainerId, type PanelId } from '../content/explainers'
import { useApp } from '../store'
import { linkTerms } from './Terms'

interface PanelProps {
  id: PanelId
  ctx: ExplainerContext | null
  bounds?: string[]
  children: ReactNode
}

/** A panel: beat number, title, bound badges, the one-sentence explainer, and a toggle for the rest. */
export function Panel({ id, ctx, bounds = [], children }: PanelProps) {
  const explainer = EXPLAINERS[id]
  const [open, setOpen] = useState(false)
  const headingId = useId()
  const bodyId = useId()
  return (
    <section className="panel" id={`panel-${id}`} aria-labelledby={headingId}>
      <header className="panel-head">
        {explainer.beat ? (
          <span className="beat-num" title={`Step ${explainer.beat} of a tick`}>
            {explainer.beat}
          </span>
        ) : (
          <span className="beat-num side" title="A side input, not a level of the tower">
            ↳
          </span>
        )}
        <h2 id={headingId}>{explainer.title}</h2>
        <span className="spacer" />
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
      <BoundBadges bounds={bounds} />
      {open && <ExplainerBody id={id} bodyId={bodyId} ctx={ctx} />}
      {children}
    </section>
  )
}

/** Bound badges; clicking one says why that limit exists. */
export function BoundBadges({ bounds }: { bounds: string[] }) {
  const [bound, setBound] = useState<string | null>(null)
  if (bounds.length === 0) return null
  return (
    <>
      <div className="bounds" aria-label="Hard limits on this level">
        <span className="bounds-label">Bounds</span>
        {bounds.map((b) => (
          <button
            key={b}
            type="button"
            className="bound"
            aria-expanded={bound === b}
            title="A hard limit; click for why it exists"
            onClick={() => setBound(bound === b ? null : b)}
          >
            {b}
          </button>
        ))}
      </div>
      {bound && <p className="bound-note">{BOUNDS[bound] ?? bound}</p>}
    </>
  )
}

export function ExplainerBody({ id, bodyId, ctx }: { id: ExplainerId; bodyId?: string; ctx: ExplainerContext | null }) {
  const explainer = EXPLAINERS[id]
  const depth = useApp((s) => s.depth)
  const lines = depth === 'formula' && ctx && explainer.substitute ? explainer.substitute(ctx) : []
  // Each glossary word is linked once per explanation, at its first mention.
  const seen = new Set<string>()
  return (
    <div className="explainer" id={bodyId}>
      {explainer.paragraphs.map((p) => (
        <p key={p.slice(0, 32)}>{linkTerms(p, seen)}</p>
      ))}
      {depth === 'formula' && explainer.formula && (
        <div className="formula">
          <div className="formula-general mono">{explainer.formula}</div>
          {lines.length > 0 && (
            <div className="formula-lines">
              {lines.map((line, i) => (
                <FormulaRow key={`${line.label}-${i}`} {...line} />
              ))}
            </div>
          )}
        </div>
      )}
      {depth === 'plain' && explainer.formula && (
        <p className="hint">Switch the top bar to Formula to see this tick&apos;s arithmetic.</p>
      )}
      <p className="code-ref">
        In the code: <code>{explainer.code}</code>
      </p>
    </div>
  )
}

function FormulaRow({ label, expr, result }: { label: string; expr: string; result?: string }) {
  return (
    <div className="formula-line">
      <div className="label">{label}</div>
      <div>
        <span className="mono">{expr}</span>
        {result !== undefined && (
          <>
            {' '}
            <span className="arrow" aria-hidden>
              →
            </span>{' '}
            <span className="mono result">{result}</span>
          </>
        )}
      </div>
    </div>
  )
}

/** A hover and focus card around any inline element. */
export function Tip({ children, body, className }: { children: ReactNode; body: ReactNode; className?: string }) {
  return (
    <span className={`tip ${className ?? ''}`} tabIndex={0}>
      {children}
      <span className="tip-body" role="tooltip">
        {body}
      </span>
    </span>
  )
}
