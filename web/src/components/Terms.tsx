import type { ReactNode } from 'react'
import { GLOSSARY } from '../content/glossary'
import { TermLink } from './TermLink'

const escape = (word: string) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Every term and alias, longest first, so “history test” wins over “history” and “trial judge” over “trial”. */
const WORDS = GLOSSARY.flatMap((e) =>
  [e.term, ...e.aliases].map((word) => ({ word: word.toLowerCase(), id: e.id })),
).sort((a, b) => b.word.length - a.word.length)
const OWNER = new Map(WORDS.map((w) => [w.word, w.id]))
/**
 * Whole words only: no letter, digit, underscore or hyphen either side, so “d1-ultra” is one word and
 * “paid-off” is not “paid off”. The character before is matched as a group rather than a lookbehind, which
 * Safari only has from 16.4.
 */
const PATTERN = new RegExp(
  `(^|[^\\p{L}\\p{N}_-])(${WORDS.map((w) => escape(w.word)).join('|')})(?![\\p{L}\\p{N}_-])`,
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
    const word = match[2] ?? ''
    const start = match.index + (match[1] ?? '').length
    const id = OWNER.get(word.toLowerCase())
    if (!id || seen.has(id)) continue
    seen.add(id)
    if (start > at) out.push(text.slice(at, start))
    out.push(<TermLink key={`${id}-${start}`} id={id} text={word} />)
    at = start + word.length
  }
  if (at < text.length) out.push(text.slice(at))
  return out
}
