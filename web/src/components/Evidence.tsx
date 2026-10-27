const HEADER = /^\[[a-z0-9_:]+\]$/

/** The channel each line belongs to: the name of the last header at or above it. */
function channelOfLines(lines: string[]): string[] {
  const out: string[] = []
  let channel = ''
  for (const line of lines) {
    if (HEADER.test(line)) channel = line.slice(1, -1)
    out.push(channel)
  }
  return out
}

/**
 * A state text exactly as an instance was sent it, with its channel headers picked out. With `highlight`, the
 * lines of that channel are marked too.
 */
export function EvidenceText({
  text,
  name,
  testId = 'evidence-text',
  highlight,
}: {
  text: string
  name: string
  testId?: string
  /** A channel's name, without brackets. */
  highlight?: string
}) {
  const lines = text.split('\n')
  const channels = channelOfLines(lines)
  return (
    <pre className="evidence-text" data-testid={testId} data-instance={name} tabIndex={0}>
      {lines.map((line, i) => {
        const head = HEADER.test(line)
        const marked = highlight !== undefined && channels[i] === highlight
        const className = [head ? 'ev-head' : '', marked ? 'ev-mark' : ''].filter(Boolean).join(' ')
        return (
          <span key={i} className={className || undefined}>
            {line}
            {i < lines.length - 1 ? '\n' : ''}
          </span>
        )
      })}
    </pre>
  )
}
