import { type Page, expect, test } from '@playwright/test'
import { LIVE } from '../playwright.config'

// Against e2e/live-server.mjs with live mode on: the fixture recording replayed as live-1, live-2, … one tick
// every 80 ms (40 ticks), a second apart, with schema 2 ticks and each of System 2's records sent as a
// `reflection` event right after the tick it followed.
test.use({ baseURL: LIVE })

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  return errors
}

const badge = (page: Page) => page.locator('.live-badge')

/** The tick showing: Watch's counter on Watch, the timeline's on the other screens. */
async function tickNow(page: Page): Promise<number> {
  const counter = page.locator('[data-testid="watch-counter"], [data-testid="tick-counter"]').first()
  return Number((await counter.getAttribute('data-tick')) ?? -1)
}

/** Follow the live episode from early in its run, so a test sees most of an episode. */
async function followEarly(page: Page, screen = 'watch'): Promise<void> {
  await page.goto(`./#live/${screen}`)
  await expect(badge(page)).toHaveText('LIVE', { timeout: 10_000 })
  await expect
    .poll(
      async () => {
        const tick = await tickNow(page)
        return tick >= 0 && tick < 5
      },
      { intervals: [30], timeout: 10_000 },
    )
    .toBe(true)
  await expect(page.locator('.live-following')).toHaveText('following')
}

test('Watch follows live play: the strip shows each schema 2 tick as it arrives', async ({ page }) => {
  const errors = collectErrors(page)
  await followEarly(page)
  await expect(page).toHaveURL(/#live\/watch$/)
  await expect(page.locator('.watch-honesty')).toContainText('Live:')
  await expect(page.getByTestId('watch-counter')).toContainText('playing now')
  const rows = page.getByTestId('sense-row')
  await expect(rows).toHaveCount(5)
  await expect(page.getByTestId('central-row')).toBeVisible()
  const first = await tickNow(page)
  await expect.poll(() => tickNow(page), { timeout: 2_000 }).toBeGreaterThan(first)
  // The configuration line moves to version 2 once the admitted macro takes effect, and names its trial.
  await expect(page.getByTestId('config-line')).toHaveAttribute('data-version', '2', { timeout: 5_000 })
  await expect(page.getByTestId('config-line')).toContainText('trial in flight')
  expect(errors).toEqual([])
})

test('the slow system fills in as System 2’s records arrive as reflection events', async ({ page }) => {
  const errors = collectErrors(page)
  await followEarly(page, 'slow')
  await expect(page).toHaveURL(/#live\/slow$/)
  const cycles = page.getByTestId('cycle-row')
  // The first cycle comes after decision 8; the macro's trial starts at decision 11.
  await expect(cycles.first()).toBeVisible({ timeout: 5_000 })
  await expect(page.locator('[data-testid="version-card"][data-version="2"]')).toBeVisible({ timeout: 5_000 })
  // The history test arrives with the third cycle, and its table with it.
  await expect(page.getByTestId('history-test').getByTestId('test-row')).toHaveCount(12, { timeout: 8_000 })
  await expect(page.locator('[data-testid="version-card"][data-version="3"]')).toBeVisible()
  expect(await cycles.count()).toBeGreaterThanOrEqual(3)
  expect(errors).toEqual([])
})

test('The instances follows live play and shows the newest tick’s evidence', async ({ page }) => {
  await followEarly(page, 'instances')
  const panel = page.getByTestId('instance-panel')
  await expect(panel).toHaveAttribute('data-instance', 'survival')
  const text = page.getByTestId('evidence-text')
  await expect(text).toContainText('[vitals]')
  const first = await tickNow(page)
  await expect.poll(() => tickNow(page), { timeout: 2_000 }).toBeGreaterThan(first)
  expect((await text.textContent()) ?? '').not.toContain('[messages]')
})
