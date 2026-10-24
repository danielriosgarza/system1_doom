import type { ReactNode } from 'react'
import { GLOSSARY } from '../content/glossary'
import { TermLink } from './TermLink'

const escape = (word: string) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Every term and alias, longest first, so “trust λ” wins over “trust” and “legal actions” over “legal”. */
const WORDS = GLOSSARY.flatMap((e) =>
  [e.term, ...e.aliases].map((word) => ({ word: word.toLowerCase(), id: e.id })),
).sort((a, b) => b.word.length - a.word.length)
const OWNER = new Map(WORDS.map((w) => [w.word, w.id]))
/** Whole words only: no letter, digit or underscore either side. Unicode-aware, since λ is not a \w to \b. */
const PATTERN = new RegExp(
  `(?<![\\p{L}\\p{N}_])(?:${WORDS.map((w) => escape(w.word)).join('|')})(?![\\p{L}\\p{N}_])`,
  'giu',
)

/**
 * The text with the first mention of each glossary entry turned into a link to it. Entries already in
 * `seen` stay plain, and every entry linked is added, so paragraphs sharing a set link each term once.
 */
export function linkTerms(text: string, seen: Set<string>): ReactNode[] {
  const out: ReactNode[] = []
  let at = 0
  for (const match of text.matchAll(PATTERN)) {
    const id = OWNER.get(match[0].toLowerCase())
    if (!id || seen.has(id)) continue
    seen.add(id)
    if (match.index > at) out.push(text.slice(at, match.index))
    out.push(<TermLink key={`${id}-${match.index}`} id={id} text={match[0]} />)
    at = match.index + match[0].length
  }
  if (at < text.length) out.push(text.slice(at))
  return out
}
