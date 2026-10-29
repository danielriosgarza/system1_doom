import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { Fragment, type ReactNode, createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { linkTerms } from '../components/Terms'
import { type Solution, screensOf } from '../store'
import { EXPLAINERS } from './explainers'
import { GLOSSARY, REMOVED_TERMS, glossaryOf, shown, usedBy } from './glossary'

const REPO = new URL('../../../', import.meta.url)

/** The first column of the glossary table in docs/DOCUMENTATION.md, section 18. */
function docsTerms(): string[] {
  const docs = readFileSync(new URL('docs/DOCUMENTATION.md', REPO), 'utf8')
  const section = docs.slice(docs.indexOf('## 18. Glossary'))
  return section
    .slice(0, section.indexOf('\n---\n'))
    .split('\n')
    .filter((line) => line.startsWith('| **'))
    .map((line) => (line.split('|')[1] ?? '').replaceAll('**', '').split(' / ')[0]!.split(/[(`]/)[0]!.trim())
}

const known = () => new Set(GLOSSARY.flatMap((e) => [e.term, ...e.aliases]).map((w) => w.toLowerCase()))

describe('the glossary', () => {
  it('has every term of the documentation glossary, which has at least sixteen', () => {
    const terms = docsTerms()
    expect(terms.length).toBeGreaterThanOrEqual(16)
    const words = known()
    expect(terms.filter((t) => !words.has(t.toLowerCase()))).toEqual([])
  })

  it('has nothing the documentation glossary lacks: the two are kept together', () => {
    const terms = new Set(docsTerms().map((t) => t.toLowerCase()))
    expect(GLOSSARY.filter((e) => !terms.has(e.term.toLowerCase())).map((e) => e.term)).toEqual([])
  })

  it('names the design’s words', () => {
    const words = known()
    const design = [
      'instance',
      'sense',
      'central',
      'channel',
      'scope',
      'message',
      'strength',
      'relevance',
      'configuration',
      'miss',
      'pick',
      'reflector',
      'history test',
      'trial',
      'judge',
      'admit instance',
      'action',
      'macro',
      'context signature',
      'projection',
      'value network',
      'tick',
      'bundle',
      'live episode',
      'slow path',
    ]
    expect(design.filter((w) => !words.has(w))).toEqual([])
  })

  it('no longer has the removed architecture’s words, in the app or in the documentation', () => {
    const words = known()
    const docs = new Set(docsTerms().map((t) => t.toLowerCase()))
    for (const removed of REMOVED_TERMS) {
      expect(words.has(removed), removed).toBe(false)
      expect(docs.has(removed), removed).toBe(false)
    }
  })

  it('names the rule tree’s words, which only its screens link', () => {
    const rules = new Set(
      glossaryOf('rules')
        .flatMap((e) => [e.term, ...e.aliases])
        .map((w) => w.toLowerCase()),
    )
    const senses = new Set(
      glossaryOf('senses')
        .flatMap((e) => [e.term, ...e.aliases])
        .map((w) => w.toLowerCase()),
    )
    const design = ['rule tree', 'rule', 'condition', 'walk', 'focus', 'skill', 'soft loop', 'rule writer']
    expect(design.filter((w) => !rules.has(w))).toEqual([])
    expect(design.filter((w) => senses.has(w))).toEqual([])
    for (const shared of ['jev', 'miss', 'bundle', 'channel']) {
      expect(rules.has(shared) && senses.has(shared), shared).toBe(true)
    }
  })

  it('gives the local models the rule tree’s terms in Laya’s words, without Jev, and Laya and Kev of their own', () => {
    const local = glossaryOf('local')
    const ids = new Set(local.map((e) => e.id))
    for (const id of ['laya', 'kev', 'rule', 'walk', 'focus', 'condition']) expect(ids.has(id), id).toBe(true)
    expect(ids.has('jev')).toBe(false)
    for (const e of local) expect(`${e.meaning} ${e.see.map((l) => l.label).join(' ')}`, e.id).not.toMatch(/\bJev\b/)
    expect(glossaryOf('rules').some((e) => e.id === 'laya' || e.id === 'kev')).toBe(false)
  })

  it('gives real time the local models’ terms, without Jev, and the lag, the helper and tap firing of its own', () => {
    const realtime = glossaryOf('realtime')
    const ids = new Set(realtime.map((e) => e.id))
    for (const id of ['laya', 'rule', 'walk', 'focus', 'real-time-lag', 'helper', 'tap-firing'])
      expect(ids.has(id), id).toBe(true)
    expect(ids.has('jev')).toBe(false)
    for (const e of realtime) expect(`${e.meaning} ${e.see.map((l) => l.label).join(' ')}`, e.id).not.toMatch(/\bJev\b/)
    for (const solution of ['senses', 'rules', 'local'] as Solution[]) {
      expect(
        glossaryOf(solution).some((e) => e.id === 'helper' || e.id === 'tap-firing'),
        solution,
      ).toBe(false)
    }
  })

  it('gives a term both solutions use its rule-tree meaning, and a rule-tree term no second one', () => {
    for (const entry of GLOSSARY) {
      const solutions = entry.solutions ?? ['senses']
      expect(!!entry.rules, entry.id).toBe(solutions.includes('senses') && solutions.includes('rules'))
    }
  })

  const variants = GLOSSARY.flatMap((entry) =>
    (['senses', 'rules', 'local', 'realtime'] as Solution[])
      .filter((s) => usedBy(entry, s))
      .map((s) => ({ solution: s, ...shown(entry, s) })),
  )

  it('links only to screens and panels that exist, and names code that exists', () => {
    for (const entry of variants) {
      const screens = new Set(screensOf(entry.solution).map((s) => s.id))
      expect(entry.see.length, entry.id).toBeGreaterThan(0)
      for (const link of entry.see) {
        expect(screens.has(link.screen), `${entry.id}: ${link.screen}`).toBe(true)
        if (link.panel) expect(EXPLAINERS, `${entry.id}: ${link.panel}`).toHaveProperty(link.panel)
      }
      expect(entry.code, entry.id).toMatch(/^[a-z0-9_]+(\/[a-z0-9_]+)?\.py · [A-Za-z_][A-Za-z0-9_.]*$/)
      const file = entry.code.split(' · ')[0] ?? ''
      expect(existsSync(fileURLToPath(new URL(`src/system1_doom/${file}`, REPO))), `${entry.id}: ${file}`).toBe(true)
    }
  })

  it('names code at real symbols, defined in the file it names', () => {
    for (const entry of variants) {
      const [file = '', symbol = ''] = entry.code.split(' · ')
      const source = readFileSync(new URL(`src/system1_doom/${file}`, REPO), 'utf8')
      const name = symbol.split('.').at(-1) ?? ''
      expect(source, `${entry.id}: ${entry.code}`).toMatch(new RegExp(`^\\s*(class|def) ${name}\\b`, 'm'))
    }
  })

  it('has unique ids and unambiguous aliases, never one letter or a bare “gate”', () => {
    const ids = GLOSSARY.map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const id of ids) expect(id).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/)
    const words = GLOSSARY.flatMap((e) => [e.term, ...e.aliases]).map((w) => w.toLowerCase())
    expect(words.filter((w, i) => words.indexOf(w) !== i)).toEqual([])
    for (const word of words) {
      expect([...word].length, word).toBeGreaterThan(1)
      expect(word).not.toBe('gate')
    }
  })
})

describe('the explainers', () => {
  it('give a formula only for the n-step return and the history test’s metrics', () => {
    const withFormula = Object.entries(EXPLAINERS)
      .filter(([, e]) => 'formula' in e && e.formula)
      .map(([id]) => id)
    expect(withFormula.sort()).toEqual(['history-test', 'ledger', 'relevance-episodes'])
  })
})

describe('linkTerms', () => {
  const html = (nodes: ReactNode[]) => renderToStaticMarkup(createElement(Fragment, null, ...nodes))
  const links = (markup: string) =>
    [...markup.matchAll(/data-term="([^"]+)"[^>]*>([^<]*)</g)].map((m) => [m[1], m[2]] as const)

  it('links whole words, longest first, each entry once', () => {
    const markup = html(
      linkTerms(
        'The trial judge read the trial table; a history test is not a history; the ticket is no tick.',
        new Set(),
      ),
    )
    expect(links(markup)).toEqual([
      ['judge', 'trial judge'],
      ['trial', 'trial'],
      ['history-test', 'history test'],
      ['tick', 'tick'],
    ])
    expect(markup).toContain('the ticket is no <span')
  })

  it('keeps hyphenated words whole and links a term once across paragraphs sharing a set', () => {
    const seen = new Set<string>()
    expect(links(html(linkTerms('Every d1-ultra answer; the scope-chips are not a scope.', seen)))).toEqual([
      ['d1-ultra', 'd1-ultra'],
      ['scope', 'scope'],
    ])
    expect(links(html(linkTerms('The Scope again, and a reflector.', seen)))).toEqual([['reflector', 'reflector']])
    expect([...seen]).toEqual(['d1-ultra', 'scope', 'reflector'])
  })

  it('links each solution’s own terms: the rule tree’s focus is plain text on the senses and central’s screens', () => {
    expect(links(html(linkTerms('The focus of the walk; a scope.', new Set(), 'rules')))).toEqual([
      ['focus', 'focus'],
      ['walk', 'walk'],
    ])
    expect(links(html(linkTerms('The focus of the walk; a scope.', new Set())))).toEqual([['scope', 'scope']])
  })

  it('links a word at the very start and words one character apart', () => {
    expect(links(html(linkTerms('Tick/scope', new Set())))).toEqual([
      ['tick', 'Tick'],
      ['scope', 'scope'],
    ])
    expect(html(linkTerms('Tick/scope', new Set()))).toMatch(/<\/span>\/<span/)
  })
})
