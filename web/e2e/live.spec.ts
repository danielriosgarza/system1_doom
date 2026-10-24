import { type Page, expect, test } from '@playwright/test'

// Against e2e/live-server.mjs: deadly_corridor-heuristics-9 replayed as live-1, live-2, … one tick
// every 80 ms (36 ticks, then it dies), a second apart.
test.use({ baseURL: 'http://127.0.0.1:4174/' })

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  return errors
}

const badge = (page: Page) => page.locator('.live-badge')
const picker = (page: Page) => page.locator('.topbar select')

async function tickNow(page: Page): Promise<number> {
  const text = (await page.getByTestId('tick-counter').textContent()) ?? ''
  return Number(/Tick (\d+)/.exec(text)?.[1] ?? -1)
}

/** Follow the live episode from early in its run, so a test has most of an episode before it ends. */
async function followEarly(page: Page): Promise<void> {
  await page.goto('./#live')
  await expect(badge(page)).toHaveText('LIVE', { timeout: 10_000 })
  // Following rides on into the next episode, so a late arrival only waits for that one to start. Ticks
  // 0 to 5 last under half a second, so the count is read often.
  await expect
    .poll(
      async () => {
        const tick = await tickNow(page)
        return tick >= 0 && tick < 6
      },
      { intervals: [40], timeout: 10_000 },
    )
    .toBe(true)
  await expect(badge(page)).toHaveText('LIVE')
  await expect(page.locator('.live-following')).toHaveText('following')
}

test('#live follows the episode in progress: the badge, a rising count, a new frame, a longer timeline', async ({
  page,
}) => {
  const errors = collectErrors(page)
  await followEarly(page)
  await expect(page).toHaveURL(/#live\/overview$/)
  await expect(page.getByTestId('live-line')).toBeVisible()
  const slots = page.locator('.scrubber svg rect')
  const before = await slots.count()
  const first = await tickNow(page)
  await expect.poll(() => tickNow(page), { timeout: 2_000 }).toBeGreaterThan(first)
  expect(await slots.count()).toBeGreaterThan(before)

  await page.keyboard.press('2')
  await expect(page).toHaveURL(/#live\/tick$/)
  const frame = page.locator('.frame img')
  const src = await frame.getAttribute('src')
  expect(src).toMatch(/^episodes\/live-\d+\/frames\/\d{5}\.jpg$/)
  await expect.poll(() => frame.getAttribute('src'), { timeout: 2_000 }).not.toBe(src)
  expect(errors).toEqual([])
})

test('ArrowLeft stops following, and Follow returns to the newest tick', async ({ page }) => {
  await followEarly(page)
  await page.keyboard.press('ArrowLeft')
  const follow = page.getByRole('button', { name: 'Follow' })
  await expect(follow).toBeVisible()
  const held = await tickNow(page)
  await page.waitForTimeout(400)
  expect(await tickNow(page)).toBe(held)
  await expect(page).toHaveURL(new RegExp(`#live-\\d+/${held}/overview$`))

  await follow.click()
  await expect(page.locator('.live-following')).toBeVisible()
  // Five ticks arrived during the 400 ms; Follow lands on the newest and keeps moving.
  await expect.poll(() => tickNow(page), { timeout: 2_000 }).toBeGreaterThan(held + 4)
  await expect(page).toHaveURL(/#live\/overview$/)
})

test('at the end the picker lists the episode with its result, the badge reads ended, and the next is followed', async ({
  page,
}) => {
  await page.goto('./#live')
  await expect(badge(page)).toHaveText('LIVE', { timeout: 10_000 })
  const name = await picker(page).inputValue()
  expect(name).toMatch(/^live-\d+$/)
  await expect(badge(page)).toHaveText('ended', { timeout: 6_000 })
  await expect(picker(page).locator(`optgroup[label="Live"] option[value="${name}"]`)).toHaveText(
    /^deadly corridor · heuristics only · seed \d+ · died$/,
  )
  await expect(badge(page)).toHaveText('LIVE', { timeout: 3_000 })
  await expect(picker(page)).toHaveValue(`live-${Number(name.slice('live-'.length)) + 1}`)
  await expect(page.locator('.live-following')).toBeVisible()
  await expect(picker(page).locator('optgroup[label="Live"] option').first()).toHaveText(
    /^live · deadly corridor · seed \d+ · tick \d+$/,
  )
})

test('every screen renders the live episode without console errors', async ({ page }) => {
  const errors = collectErrors(page)
  await followEarly(page)
  const screens: Array<[string, string]> = [
    ['1', 'main.overview'],
    ['2', 'main.main'],
    ['3', 'main.hierarchy'],
    ['4', 'main.learning'],
    ['5', 'main.menu-screen'],
  ]
  for (const [key, main] of screens) {
    await page.keyboard.press(key)
    await expect(page.locator(main)).toBeVisible()
    await page.waitForTimeout(250)
  }
  await page.keyboard.press('i')
  const dialog = page.getByRole('dialog', { name: 'Reference' })
  await expect(dialog.getByTestId('recorded')).toHaveText(/^Running now, started /)
  await expect(dialog.locator('.command code').first()).toHaveText(
    'python -m system1_doom.serve --scenario deadly_corridor.cfg --seed 9 --model heuristics --pace 0.08',
  )
  expect(errors).toEqual([])
})

test('a visit while serve sets up its first episode, with no recordings, rides in when it starts', async ({ page }) => {
  const errors = collectErrors(page)
  // No shipped recordings, nothing played yet, and a first stream that says so before it drops; the
  // browser's reconnect reaches the stand-in, mid-episode.
  await page.route('**/episodes/index.json', (route) => route.fulfill({ status: 404, body: 'Not found' }))
  await page.route('**/live/status.json', async (route) => {
    const response = await route.fetch()
    const status = (await response.json()) as Record<string, unknown>
    await route.fulfill({ response, json: { ...status, current: null, tick: null, episodes: [] } })
  })
  let first = true
  await page.route('**/live/events', (route) => {
    if (!first) return route.continue()
    first = false
    const hello = JSON.stringify({ current: null, tick: null, episodes: [] })
    return route.fulfill({ contentType: 'text/event-stream', body: `retry: 500\nevent: hello\ndata: ${hello}\n\n` })
  })
  await page.goto('./')
  await expect(badge(page)).toHaveText('LIVE', { timeout: 10_000 })
  await expect(page.locator('.live-following')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page).toHaveURL(/#live\/overview$/)
  expect(errors.filter((e) => !e.includes('404'))).toEqual([])
})

test('a shipped recording still opens from the picker, and l comes back to the live episode', async ({ page }) => {
  await followEarly(page)
  await picker(page).selectOption('deadly_corridor-learned-9')
  await expect(page).toHaveURL(/#deadly_corridor-learned-9\/0\/overview$/)
  await expect(page.getByTestId('tick-counter')).toContainText('Tick 0 / 51')
  await expect(page.getByTestId('live-status')).toHaveCount(0)
  // The picker keeps the focus after a choice, and no key fires in a select.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('l')
  await expect(badge(page)).toHaveText('LIVE', { timeout: 5_000 })
  await expect(page.locator('.live-following')).toBeVisible()
})

test('the live bar keeps to one row at 1280 px, and fits a phone with no sideways scroll', async ({ page }) => {
  await followEarly(page)
  const tops = await page
    .locator('.topbar > *')
    .evaluateAll((items) => items.map((el) => el.getBoundingClientRect().top + el.getBoundingClientRect().height / 2))
  expect(Math.max(...tops) - Math.min(...tops)).toBeLessThan(12)

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(badge(page)).toBeVisible()
  const box = await page.getByTestId('live-status').boundingBox()
  expect(box && box.x + box.width).toBeLessThanOrEqual(390)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
