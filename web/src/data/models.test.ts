import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import type { WalkStep } from '../schema/bundle'
import type { Fetcher } from './loader'
import { agreementWithPlayed, parseModels, questionsAt } from './models'
import { loadRulesEpisode, readStep } from './rules'

// The shipped recordings' models.json, written by python -m system1_doom.ruletree.site_models.
const PUBLIC = fileURLToPath(new URL('../../public/', import.meta.url))
const fetcher: Fetcher = async (url) => {
  try {
    return new Response(await readFile(PUBLIC + url, 'utf8'))
  } catch {
    return new Response('missing', { status: 404 })
  }
}

describe('the local models’ answers', () => {
  it('are read with a recording, one per question Laya answered, in the order of each walk', async () => {
    const bundle = await loadRulesEpisode('local-corridor-9', 'episodes', fetcher)
    const models = bundle.models
    expect(models?.models).toContain('kev-27b')
    // Every question Laya was asked (a step with an answer) has an entry, at its own step, of the same kind and node.
    const asked = bundle.decisions.flatMap((d) =>
      d.steps.flatMap((s, i) => (s.kind !== 'skill' && s.answer ? [{ decision: d.decision, step: i, s }] : [])),
    )
    expect(models?.answers).toHaveLength(asked.length)
    for (const { decision, step, s } of asked) {
      const here = questionsAt(models!, decision).find((q) => q.step === step)
      expect(here?.kind).toBe(s.kind)
      expect(here?.node).toBe(s.node)
      for (const [option, p] of Object.values(here?.picks ?? {})) {
        expect(Object.keys((s as WalkStep).options ?? {})).toContain(option)
        expect(p).toBeGreaterThan(0)
        expect(p).toBeLessThanOrEqual(1)
      }
    }
  })

  it('count how often each model picked as the model that played did', async () => {
    const bundle = await loadRulesEpisode('local-corridor-9', 'episodes', fetcher)
    const tally = agreementWithPlayed(bundle.models!, (q) => {
      const step = bundle.decisions.find((d) => d.decision === q.decision)?.steps[q.step] as WalkStep | undefined
      return step ? (readStep(step).option ?? null) : null
    })
    const kev = tally['kev-27b']
    expect(kev?.of).toBe(bundle.models!.answers.length)
    expect(kev!.same).toBeGreaterThan(0.9 * kev!.of)
  })

  it('is optional, and a broken file is refused', () => {
    expect(parseModels('', 'x/models.json')).toBeNull()
    expect(() => parseModels('{"models": []}', 'x/models.json')).toThrow('has no models or answers list')
    expect(() => parseModels('{"models": [], "answers": [{"step": 1}]}', 'x/models.json')).toThrow(
      'without its decision',
    )
  })
})
