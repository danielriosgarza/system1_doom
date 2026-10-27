import type { ReactNode } from 'react'
import { GLOSSARY, usedBy } from '../content/glossary'
import type { Solution } from '../store'
import { TermLink } from './TermLink'

const escape = (word: string) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * Each solution's terms and aliases, longest first, so “history test” wins over “history” and “trial judge” over
 * “trial”, with the pattern that finds them. Whole words only: no letter, digit, underscore or hyphen either side,
 * so “d1-ultra” is one word and “paid-off” is not “paid off”. The character before is matched as a group rather
 * than a lookbehind, which Safari only has from 16.4.
 */
function wordsOf(solution: Solution): { owner: Map<string, string>; pattern: RegExp } {
  const words = GLOSSARY.filter((e) => usedBy(e, solution))
    .flatMap((e) => [e.term, ...e.aliases].map((word) => ({ word: word.toLowerCase(), id: e.id })))
    .sort((a, b) => b.word.length - a.word.length)
  return {
    owner: new Map(words.map((w) => [w.word, w.id])),
    pattern: new RegExp(
      `(^|[^\\p{L}\\p{N}_-])(${words.map((w) => escape(w.word)).join('|')})(?![\\p{L}\\p{N}_-])`,
      'giu',
    ),
  }
}

const WORDS: Record<Solution, { owner: Map<string, string>; pattern: RegExp }> = {
  senses: wordsOf('senses'),
  rules: wordsOf('rules'),
}

/**
 * The text with the first mention of each glossary entry of the solution turned into a link to it. Entries
 * already in `seen` stay plain, and every entry linked is added, so paragraphs sharing a set link each term once.
 */
export function linkTerms(text: string, seen: Set<string>, solution: Solution = 'senses'): ReactNode[] {
  const { owner, pattern } = WORDS[solution]
  const out: ReactNode[] = []
  let at = 0
  for (const match of text.matchAll(pattern)) {
    const word = match[2] ?? ''
    const start = match.index + (match[1] ?? '').length
    const id = owner.get(word.toLowerCase())
    if (!id || seen.has(id)) continue
    seen.add(id)
    if (start > at) out.push(text.slice(at, start))
    out.push(<TermLink key={`${id}-${start}`} id={id} text={word} />)
    at = start + word.length
  }
  if (at < text.length) out.push(text.slice(at))
  return out
}
