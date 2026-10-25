import { type Page, expect, test } from '@playwright/test'
import { RECORDINGS } from '../playwright.config'

// The site as GitHub Pages serves it, with the shipped recordings played by d1-ultra: the landing plays the
// first cleared one at the agent's own pace, and every screen reads every recording.
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

async function shipped(page: Page): Promise<Array<{ name: string; ticks: number; cleared: boolean }>> {
  const response = await page.request.get(`${RECORDINGS}episodes/index.json`)
  const index = (await response.json()) as { episodes: Array<{ name: string; ticks: number; cleared: boolean }> }
  return index.episodes
}

test('a first-time visitor lands on Watch and sees the first cleared recording playing', async ({ page }) => {
  const errors = collectErrors(page)
  const episodes = await shipped(page)
  const featured = episodes.find((e) => e.cleared) ?? episodes[0]
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
