import { type Page, expect, test } from '@playwright/test'

// Watch, the landing, on the fixture recording: it plays at the agent's own pace from a fresh visit.

const FIXTURE = 'fixture-corridor'

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  return errors
}

const counter = (page: Page) => page.getByTestId('watch-counter')

/** The decision showing, counted from 1, as the counter reads it. */
async function decisionNow(page: Page): Promise<number> {
  return Number(/decision (\d+)/.exec((await counter(page).textContent()) ?? '')?.[1] ?? -1)
}

test('a fresh visit lands on Watch and plays the recording within a second and a half', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./')
  await expect(page).toHaveURL(new RegExp(`#${FIXTURE}/0/watch$`))
  await expect(page.locator('.topbar select')).toHaveValue(FIXTURE)
  await expect(counter(page)).toContainText('of 40')
  await expect.poll(() => decisionNow(page), { timeout: 1_500, intervals: [100] }).toBeGreaterThan(1)
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
  await expect(counter(page)).toHaveAttribute('aria-live', 'off')
  await expect(page.locator('.watch-img.top')).toHaveAttribute('alt', /^The game at decision \d+ of 40: /)
  // Playback does not rewrite the address four times a second.
  await expect(page).toHaveURL(new RegExp(`#${FIXTURE}/0/watch$`))
  expect(errors).toEqual([])
})

test('pausing holds the decision, and the address names it', async ({ page }) => {
  await page.goto('./')
  await expect.poll(() => decisionNow(page), { timeout: 2_000 }).toBeGreaterThan(2)
  await page.getByRole('button', { name: 'Pause', exact: true }).click()
  const held = await decisionNow(page)
  await page.waitForTimeout(600)
  expect(await decisionNow(page)).toBe(held)
  await expect(page).toHaveURL(new RegExp(`#${FIXTURE}/${held - 1}/watch$`))
})

test('on a phone nothing scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./')
  await expect(counter(page)).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
