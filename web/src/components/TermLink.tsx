import { useId } from 'react'
import { GLOSSARY_BY_ID, shown } from '../content/glossary'
import { openTerm, useApp } from '../store'

/** A linked word: its meaning on hover and focus, its glossary entry on the Reference screen on click. */
export function TermLink({ id, text }: { id: string; text?: string }) {
  const tipId = useId()
  const solution = useApp((s) => s.solution)
  const found = GLOSSARY_BY_ID[id]
  const entry = found ? shown(found, solution) : undefined
  return (
    <span className="tip term-tip">
      <button type="button" className="term" data-term={id} aria-describedby={tipId} onClick={() => openTerm(id)}>
        {text ?? entry?.term ?? id}
      </button>
      <span className="tip-body" role="tooltip" id={tipId}>
        <strong>{entry?.term}</strong>: {entry?.meaning}{' '}
        <span className="muted">Click to open the glossary entry.</span>
      </span>
    </span>
  )
}
