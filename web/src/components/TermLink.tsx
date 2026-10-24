import { useId } from 'react'
import { GLOSSARY_BY_ID } from '../content/glossary'
import { openDrawer } from '../store'

/** A linked word: its meaning on hover and focus, the glossary entry on click. */
export function TermLink({ id, text }: { id: string; text: string }) {
  const tipId = useId()
  const entry = GLOSSARY_BY_ID[id]
  return (
    <span className="tip term-tip">
      <button
        type="button"
        className="term"
        data-term={id}
        aria-describedby={tipId}
        onClick={() => openDrawer('glossary', id)}
      >
        {text}
      </button>
      <span className="tip-body" role="tooltip" id={tipId}>
        <strong>{entry?.term}</strong>: {entry?.meaning} <span className="muted">Click for the glossary.</span>
      </span>
    </span>
  )
}
