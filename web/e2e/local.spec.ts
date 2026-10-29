import { type Page, expect, test } from '@playwright/test'
import { RECORDINGS } from '../playwright.config'

// The local models' six screens, read against the shipped recordings Laya played: what a screen shows must be what
// decisions.jsonl and models.json say, and nothing on them is Jev's.
test.use({ baseURL: RECORDINGS })

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  return errors
}

interface Step {
  kind: 'rule' | 'focus' | 'skill'
  node: string
  options?: Record<string, string>
  answer?: { pick?: string | null; probabilities?: Record<string, number> } | null
  pick?: string | null
}

interface Decision {
  decision: number
  steps: Step[]
}

interface ModelsFile {
  models: string[]
  answers: { decision: number; step: number; kind: string; node: string; picks: Record<string, [string, number]> }[]
}

async function localRecordings(page: Page): Promise<string[]> {
  const index = (await (await page.request.get(`${RECORDINGS}episodes/index.json`)).json()) as {
    episodes: { name: string; solution?: string; decider?: string; realtime?: boolean }[]
  }
  return index.episodes
    .filter((e) => e.solution === 'rule-tree' && e.decider === 'laya' && !e.realtime)
    .map((e) => e.name)
}

async function decisions(page: Page, name: string): Promise<Decision[]> {
  const body = await (await page.request.get(`${RECORDINGS}episodes/${name}/decisions.jsonl`)).text()
  return body
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as Decision)
}

test('every local screen of every Laya recording opens without an error or a word of Jev, and none scrolls sideways on a phone', async ({
  page,
}) => {
  test.setTimeout(120_000)
  const errors = collectErrors(page)
  const names = await localRecordings(page)
  expect(names.length).toBeGreaterThanOrEqual(4)
  await page.setViewportSize({ width: 390, height: 844 })
  for (const name of names) {
    for (const screen of ['watch', 'questions', 'trained', 'results', 'tree', 'reference']) {
      await page.goto(`./#local/${name}/12/${screen}`)
      await expect(page.locator('main')).toBeVisible()
      await expect(page.locator('.topbar select')).toHaveValue(name)
      expect(await page.locator('main').innerText(), `${name} ${screen}`).not.toMatch(/\bJev\b/)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, `${name} ${screen}`).toBeLessThanOrEqual(0)
    }
  }
  expect(errors).toEqual([])
})

test('Watch shows Laya’s walk as recorded, and the recordings it lists are Laya’s', async ({ page }) => {
  const errors = collectErrors(page)
  const name = 'local-corridor-9'
  const d = (await decisions(page, name))[5]!
  await page.goto(`./#local/${name}/${d.decision}/watch`)
  const rows = page.getByTestId('walk-row')
  const asked = d.steps.filter((s) => s.kind !== 'skill')
  await expect(rows).toHaveCount(asked.length)
  for (const [k, s] of asked.entries()) {
    if (s.kind === 'rule') await expect(rows.nth(k)).toHaveAttribute('data-pick', s.answer?.pick ?? s.pick ?? '')
  }
  await expect(page.getByTestId('walk-cost')).toContainText('to Laya')
  const cards = page.locator('.recording-card')
  await expect(cards).toHaveCount((await localRecordings(page)).length)
  await expect(cards.first()).toContainText('decided by Laya')
  expect(errors).toEqual([])
})

test('Results shows this decision’s questions as Laya answered them and as its teacher and the untrained Laya did', async ({
  page,
}) => {
  const errors = collectErrors(page)
  const name = 'local-corridor-9'
  const all = await decisions(page, name)
  const models = (await (await page.request.get(`${RECORDINGS}episodes/${name}/models.json`)).json()) as ModelsFile
  expect(models.models).toEqual(['kev-27b', 'laya'])
  const d = all.find((x) => x.steps.some((s) => s.kind === 'focus' && s.answer)) ?? all[0]!
  await page.goto(`./#local/${name}/${d.decision}/results`)
  await expect(page.getByTestId('local-benchmark').locator('tbody tr')).toHaveCount(3)
  const asked = models.answers.filter((a) => a.decision === d.decision).sort((a, b) => a.step - b.step)
  const rows = page.getByTestId('decision-models').locator('tbody tr')
  await expect(rows).toHaveCount(asked.length)
  const words = (step: Step, option: string) => (step.kind === 'focus' ? (step.options?.[option] ?? option) : option)
  for (const [k, a] of asked.entries()) {
    const step = d.steps[a.step]!
    const row = rows.nth(k)
    const played = step.answer?.pick ?? step.pick ?? ''
    await expect(row.locator('td[data-model="played"]')).toContainText(words(step, played))
    for (const m of models.models) {
      const pick = a.picks[m]
      if (!pick) continue
      const cell = row.locator(`td[data-model="${m}"]`)
      await expect(cell).toContainText(words(step, pick[0]))
      await expect(cell).toHaveClass(pick[0] === played ? '' : 'differs')
    }
  }
  expect(errors).toEqual([])
})

test('How Laya was trained gives the four steps, the numbers and Kev on the Thor; Reference says Laya decides', async ({
  page,
}) => {
  await page.goto('./#local/local-corridor-11/0/trained')
  await expect(page.getByTestId('workflow').locator('li')).toHaveCount(4)
  await expect(page.getByTestId('training-facts')).toContainText('11,519')
  await expect(page.getByTestId('thor-table').locator('tbody tr')).toHaveCount(3)
  await page.goto('./#local/local-corridor-11/0/reference')
  await expect(page.getByTestId('one-rule')).toHaveText('Every decision here is made by Laya, on this computer.')
  await expect(page.getByTestId('provenance')).toContainText('ruletree-kev-v1')
  await expect(page.locator('#term-laya')).toBeVisible()
  await expect(page.locator('#term-kev')).toBeVisible()
  await expect(page.locator('#term-jev')).toHaveCount(0)
})
