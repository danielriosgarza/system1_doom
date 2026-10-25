const HEADER = /^\[[a-z0-9_:]+\]$/

/** A state text exactly as an instance was sent it, with its channel headers picked out. */
export function EvidenceText({
  text,
  name,
  testId = 'evidence-text',
}: {
  text: string
  name: string
  testId?: string
}) {
  const lines = text.split('\n')
  return (
    <pre className="evidence-text" data-testid={testId} data-instance={name} tabIndex={0}>
      {lines.map((line, i) => (
        <span key={i} className={HEADER.test(line) ? 'ev-head' : undefined}>
          {line}
          {i < lines.length - 1 ? '\n' : ''}
        </span>
      ))}
    </pre>
  )
}
