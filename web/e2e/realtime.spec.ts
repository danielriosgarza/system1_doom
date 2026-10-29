import { type Page, expect, test } from '@playwright/test'
import { RECORDINGS } from '../playwright.config'

// Real time's six screens, read against the shipped recordings Laya played on the real clock: what a screen shows
// must be what episode.json and decisions.jsonl say, and nothing on them is Jev's.
test.use({ baseURL: RECORDINGS })

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  return errors
}

interface Decision {
  decision: number
  steps: { kind: string }[]
  observed_tic: number
  start_tic: number
  walk_ms: number
  target: string | null
  pressed: { code: string; tics: number; words: string }[]
}

async function realtimeRecordings(page: Page): Promise<string[]> {
  const index = (await (await page.request.get(`${RECORDINGS}episodes/index.json`)).json()) as {
    episodes: { name: string; solution?: string; realtime?: boolean }[]
  }
  return index.episodes.filter((e) => e.solution === 'rule-tree' && e.realtime).map((e) => e.name)
}

async function decisions(page: Page, name: string): Promise<Decision[]> {
  const body = await (await page.request.get(`${RECORDINGS}episodes/${name}/decisions.jsonl`)).text()
  return body
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as Decision)
}

test('every real-time screen of every recording opens without an error or a word of Jev, and none scrolls sideways on a phone', async ({
  page,
}) => {
  test.setTimeout(120_000)
  const errors = collectErrors(page)
  const names = await realtimeRecordings(page)
  expect(names.length).toBeGreaterThanOrEqual(4)
  await page.setViewportSize({ width: 390, height: 844 })
  for (const name of names) {
    for (const screen of ['watch', 'questions', 'timing', 'results', 'tree', 'reference']) {
      await page.goto(`./#realtime/${name}/12/${screen}`)
      await expect(page.locator('main')).toBeVisible()
      await expect(page.locator('.topbar select')).toHaveValue(name)
      expect(await page.locator('main').innerText(), `${name} ${screen}`).not.toMatch(/\bJev\b/)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, `${name} ${screen}`).toBeLessThanOrEqual(0)
    }
  }
  expect(errors).toEqual([])
})

test('Watch shows when the state was read, when its action started, and what the helper pressed, as recorded', async ({
  page,
}) => {
  const errors = collectErrors(page)
  const name = 'realtime-corridor-9'
  const d = (await decisions(page, name))[5]!
  await page.goto(`./#realtime/${name}/${d.decision}/watch`)
  await expect(page.getByTestId('walk-row')).toHaveCount(d.steps.filter((s) => s.kind !== 'skill').length)
  await expect(page.getByTestId('walk-timing')).toContainText(`State read at tic ${d.observed_tic}`)
  await expect(page.getByTestId('walk-timing')).toContainText(`Action started at tic ${d.start_tic}`)
  await expect(page.getByTestId('walk-pressed')).toContainText(d.pressed[0]!.words)
  if (d.target) await expect(page.getByTestId('walk-helper')).toContainText(d.target.split(' at ')[0]!)
  const cards = page.locator('.recording-card')
  await expect(cards).toHaveCount((await realtimeRecordings(page)).length)
  await expect(cards.first()).toContainText('decided by Laya, in real time')
  await expect(page.locator('.topbar .brand')).toContainText('Laya, in real time')
  expect(errors).toEqual([])
})

test('How it plays in real time lists the steps, the helper and the timing around this decision', async ({ page }) => {
  const name = 'realtime-corridor-10'
  const all = await decisions(page, name)
  const d = all[10]!
  await page.goto(`./#realtime/${name}/${d.decision}/timing`)
  await expect(page.getByTestId('timing-steps').locator('li')).toHaveCount(4)
  await expect(page.getByTestId('helper-list').locator('li')).toHaveCount(6)
  const current = page.getByTestId('timing-table').locator('tr[aria-current="true"]')
  await expect(current).toHaveAttribute('data-decision', String(d.decision))
  await expect(current).toContainText(`tic ${d.observed_tic}`)
  await expect(current).toContainText(`tic ${d.start_tic}`)
  await expect(page.getByTestId('realtime-settings')).toContainText('the game was never paused')
  // A row's decision opens it.
  const other = all[8]!
  await page.getByTestId('timing-table').locator(`tr[data-decision="${other.decision}"] button`).click()
  await expect(page).toHaveURL(new RegExp(`#realtime/${name}/${other.decision}/timing$`))
})

test('Results lists the changes from 9 to 80, the loops and the retraining; Reference says who decides', async ({
  page,
}) => {
  await page.goto('./#realtime/realtime-corridor-11/0/results')
  const path = page.getByTestId('realtime-path').locator('tbody tr')
  await expect(path).toHaveCount(7)
  await expect(path.first()).toContainText('9')
  await expect(path.last()).toContainText('80')
  await expect(page.getByTestId('realtime-loops').locator('tbody tr')).toHaveCount(5)
  await expect(page.getByTestId('realtime-training')).toContainText('98.3%')
  await page.goto('./#realtime/realtime-corridor-11/0/reference')
  await expect(page.getByTestId('one-rule')).toHaveText(
    'Laya makes every decision; the helper aims and presses the keys.',
  )
  await expect(page.getByTestId('provenance')).toContainText('ruletree-rt-v2')
  await expect(page.getByTestId('provenance')).toContainText('--realtime wall')
  await expect(page.locator('#term-helper')).toBeVisible()
  await expect(page.locator('#term-tap-firing')).toBeVisible()
  await expect(page.locator('#term-jev')).toHaveCount(0)
})
