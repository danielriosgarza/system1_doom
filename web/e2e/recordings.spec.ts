import { type Page, expect, test } from '@playwright/test'
import { RECORDINGS } from '../playwright.config'

// The site as GitHub Pages serves it, with the shipped recordings: the landing plays the most recently recorded
// one that cleared at the agent's own pace, and every screen reads every recording.
test.use({ baseURL: RECORDINGS })

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  return errors
}

const counter = (page: Page) => page.getByTestId('watch-counter')

async function decisionNow(page: Page): Promise<number> {
  return Number(/decision (\d+)/.exec((await counter(page).textContent()) ?? '')?.[1] ?? -1)
}

interface Shipped {
  name: string
  ticks: number
  cleared: boolean
  recorded_at?: string
  senses_choose_targets?: boolean
  solution?: string
}

// The recordings of the senses and central: the index also lists the rule tree's, which these screens do not read.
async function shipped(page: Page): Promise<Shipped[]> {
  const response = await page.request.get(`${RECORDINGS}episodes/index.json`)
  const index = (await response.json()) as { episodes: Shipped[] }
  return index.episodes.filter((e) => (e.solution ?? 'senses-and-central') === 'senses-and-central')
}

const newestCleared = (episodes: Shipped[]): Shipped | undefined =>
  episodes
    .filter((e) => e.cleared)
    .reduce<Shipped | undefined>(
      (best, e) => (!best || (e.recorded_at ?? '') > (best.recorded_at ?? '') ? e : best),
      undefined,
    )

test('a first-time visitor lands on Watch and sees the newest cleared recording playing', async ({ page }) => {
  const errors = collectErrors(page)
  const episodes = await shipped(page)
  const featured = newestCleared(episodes) ?? episodes[0]
  if (!featured) throw new Error('no shipped recording')
  await page.goto('./')
  await expect(page).toHaveURL(new RegExp(`#${featured.name}/0/watch$`))
  await expect(counter(page)).toContainText(`of ${featured.ticks}`)
  await expect.poll(() => decisionNow(page), { timeout: 4_000, intervals: [100] }).toBeGreaterThan(1)
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
  await expect(page.getByTestId('sense-row')).toHaveCount(5)
  await expect(page.getByTestId('central-row')).toBeVisible()
  await expect(page.getByTestId('config-line')).toBeVisible()
  await expect(page.locator('.recording-card')).toHaveCount(episodes.length)
  const before = episodes.filter((e) => !e.senses_choose_targets).length
  await expect(page.locator('.recording-targets[data-targets="motor"]')).toHaveCount(before)
  expect(errors).toEqual([])
})

test('in a recording where the senses choose targets, Act names them and the combat sense shows its target answer', async ({
  page,
}) => {
  const errors = collectErrors(page)
  const featured = newestCleared(await shipped(page))
  if (!featured?.senses_choose_targets) throw new Error('the newest cleared recording should have sense-chosen targets')
  await page.goto(`./#${featured.name}/1/watch`)
  await expect(page.getByTestId('act-targets')).toContainText(/aim: .+, (by combat|the only one)/)
  await page.goto(`./#${featured.name}/1/instances`)
  await page.getByRole('tab').and(page.locator('[data-instance="combat"]')).click()
  const target = page.getByTestId('target-answer')
  await expect(target).toHaveAttribute('data-kind', 'enemy')
  await expect(target).toContainText('Target')
  await expect(target).toContainText('aim locks onto')
  expect(errors).toEqual([])
})

test('every shipped recording opens on every screen without an error, and none scrolls sideways on a phone', async ({
  page,
}) => {
  const errors = collectErrors(page)
  await page.setViewportSize({ width: 390, height: 844 })
  for (const { name } of await shipped(page)) {
    for (const screen of ['instances', 'slow', 'learning', 'menu', 'reference']) {
      await page.goto(`./#${name}/30/${screen}`)
      await expect(page.locator('main.screen')).toBeVisible()
      await expect(page.locator('.topbar select')).toHaveValue(name)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, `${name} ${screen}`).toBeLessThanOrEqual(0)
    }
  }
  expect(errors).toEqual([])
})

test('on a phone the landing does not scroll sideways, and at 1280 the top bar is one row', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./')
  await expect(counter(page)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
  await page.setViewportSize({ width: 1280, height: 900 })
  const tops = await page
    .locator('.topbar > *')
    .evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().top)))
  expect(Math.max(...tops) - Math.min(...tops)).toBeLessThan(12)
})
