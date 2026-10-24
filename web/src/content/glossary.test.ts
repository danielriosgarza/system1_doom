import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { EXPLAINERS } from './explainers'
import { GLOSSARY } from './glossary'

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

describe('the glossary', () => {
  it('has every term of the documentation glossary', () => {
    const terms = docsTerms()
    expect(terms.length).toBeGreaterThanOrEqual(16)
    const known = new Set(GLOSSARY.flatMap((e) => [e.term, ...e.aliases]).map((w) => w.toLowerCase()))
    expect(terms.filter((t) => !known.has(t.toLowerCase()))).toEqual([])
  })

  it('links only to panels that exist and code that exists', () => {
    for (const entry of GLOSSARY) {
      for (const link of entry.see) if ('panel' in link && link.panel) expect(EXPLAINERS).toHaveProperty(link.panel)
      const files = entry.code.match(/[a-z0-9_]+\.py/g) ?? []
      expect(files.length, entry.id).toBeGreaterThan(0)
      for (const file of files) {
        expect(existsSync(fileURLToPath(new URL(`src/system1_doom/${file}`, REPO))), `${entry.id}: ${file}`).toBe(true)
      }
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
