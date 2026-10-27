import { type Page, expect, test } from '@playwright/test'
import { RECORDINGS } from '../playwright.config'

// The side tab between the two solutions, on the site as GitHub Pages serves it: the shipped recordings include both
// the senses and central's and the rule tree's.
test.use({ baseURL: RECORDINGS })

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  return errors
}

interface Entry {
  name: string
  seed: number
  solution?: string
}

async function entries(page: Page): Promise<{ senses: Entry[]; rules: Entry[] }> {
  const index = (await (await page.request.get(`${RECORDINGS}episodes/index.json`)).json()) as { episodes: Entry[] }
  const rules = index.episodes.filter((e) => e.solution === 'rule-tree')
  return { senses: index.episodes.filter((e) => !rules.includes(e)), rules }
}

const tab = (page: Page, solution: 'senses' | 'rules') =>
  page.getByTestId('solution-tabs').locator(`button[data-solution="${solution}"]`)

test('the side tab switches solution at the same screen position, opening the recording of the same seed', async ({
  page,
}) => {
  const errors = collectErrors(page)
  await page.goto('./#jev-corridor-11/30/slow')
  await expect(page.locator('main.screen')).toBeVisible()
  await expect(tab(page, 'senses')).toHaveAttribute('aria-current', 'page')
  await expect(tab(page, 'rules')).toHaveText('Rule tree')

  // The slow system is the senses and central's third screen; the rule tree's third is How the rules were written.
  await tab(page, 'rules').click()
  await expect(page).toHaveURL(/#rules\/rules-corridor-11\/0\/written$/)
  await expect(tab(page, 'rules')).toHaveAttribute('aria-current', 'page')
  await expect(page.getByTestId('build-list')).toBeVisible()
  await expect(page.locator('.topbar select')).toHaveValue('rules-corridor-11')

  // Back on the senses and central: the recording it had open, at its first decision.
  await tab(page, 'senses').click()
  await expect(page).toHaveURL(/#jev-corridor-11\/0\/slow$/)
  await expect(page.locator('.topbar select')).toHaveValue('jev-corridor-11')

  // The browser's Back crosses between the solutions too.
  await page.goBack()
  await expect(page).toHaveURL(/#rules\/rules-corridor-11\/0\/written$/)
  await expect(page.getByTestId('build-list')).toBeVisible()
  expect(errors).toEqual([])
})

test('the picker lists only the recordings of the solution shown', async ({ page }) => {
  const { senses, rules } = await entries(page)
  await page.goto('./#corridor-9/3/instances')
  const options = page.locator('.topbar select option')
  await expect(options).toHaveCount(senses.length)
  await tab(page, 'rules').click()
  await expect(page).toHaveURL(/#rules\/rules-corridor-9\/0\/questions$/)
  await expect(options).toHaveCount(rules.length)
  expect(await options.evaluateAll((els) => els.map((el) => (el as HTMLOptionElement).value).sort())).toEqual(
    rules.map((e) => e.name).sort(),
  )
})

test('the choice of solution is remembered, and a link to either solution still opens it', async ({ page }) => {
  await page.goto('./')
  await expect(tab(page, 'senses')).toHaveAttribute('aria-current', 'page')
  await tab(page, 'rules').click()
  await expect(page).toHaveURL(/#rules\/rules-corridor-\d+\/0\/watch$/)

  // A visit without a link opens the rule tree's Watch now.
  await page.goto('about:blank')
  await page.goto('./')
  await expect(page).toHaveURL(/#rules\/rules-corridor-\d+\/0\/watch$/)
  await expect(tab(page, 'rules')).toHaveAttribute('aria-current', 'page')
  await expect(page.getByTestId('walk-strip')).toBeVisible()

  // An old link to the senses and central still opens it, at the decision and screen it names.
  await page.goto('about:blank')
  await page.goto('./#corridor-9/12/instances')
  await expect(page).toHaveURL(/#corridor-9\/12\/instances$/)
  await expect(tab(page, 'senses')).toHaveAttribute('aria-current', 'page')
  await expect(page.locator('.topbar select')).toHaveValue('corridor-9')

  // And a link to the rule tree opens its recording, decision and screen.
  await page.goto('about:blank')
  await page.goto('./#rules/rules-corridor-10/7/tree')
  await expect(page).toHaveURL(/#rules\/rules-corridor-10\/7\/tree$/)
  await expect(page.locator('.topbar select')).toHaveValue('rules-corridor-10')
  await expect(page.getByTestId('rule-detail')).toBeVisible()
  await expect(page.getByTestId('tick-counter')).toContainText('Decision 8 /')
})

test('at 1280 the rule tree’s top bar is one row with all seven screens, beside the side tab', async ({ page }) => {
  await page.goto('./#rules/rules-corridor-9/0/reference')
  const tabs = page.locator('.topbar .screens button, .topbar .screens a')
  await expect(tabs).toHaveCount(7)
  const box = await page.locator('.topbar').boundingBox()
  expect(box?.height ?? 999).toBeLessThan(70)
  const side = await page.getByTestId('solution-tabs').boundingBox()
  expect((side?.x ?? 999) + (side?.width ?? 999)).toBeLessThanOrEqual(box?.x ?? 0)
})

test('on a phone the side tab is a row of two buttons above the top bar', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./#rules/rules-corridor-9/0/watch')
  const side = await page.getByTestId('solution-tabs').boundingBox()
  const bar = await page.locator('.topbar').boundingBox()
  expect((side?.y ?? 999) + (side?.height ?? 999)).toBeLessThanOrEqual((bar?.y ?? 0) + 1)
  const senses = await tab(page, 'senses').boundingBox()
  const rules = await tab(page, 'rules').boundingBox()
  expect(Math.abs((senses?.y ?? 0) - (rules?.y ?? 999))).toBeLessThan(2)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})
