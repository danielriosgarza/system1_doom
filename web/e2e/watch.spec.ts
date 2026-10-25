import { readFileSync } from 'node:fs'
import { type Page, expect, test } from '@playwright/test'

// Watch, the landing: the featured recording plays at the agent's own pace beside its decision chain.

interface Entry {
  name: string
  cleared: boolean
  ticks: number
}

const index = JSON.parse(readFileSync(new URL('../public/episodes/index.json', import.meta.url), 'utf8')) as {
  episodes: Entry[]
}
/** The recording a fresh visit opens: the first that cleared its level. */
const featured = (index.episodes.find((e) => e.cleared) ?? index.episodes[0]) as Entry

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

const rowValue = (page: Page, level: string) =>
  page.locator(`.chain-row[data-level="${level}"]`).getByTestId('chain-value')

test('a fresh visit lands on Watch with the cleared recording, playing within a second and a half', async ({
  page,
}) => {
  const errors = collectErrors(page)
  expect(index.episodes[0]?.name).not.toBe(featured.name)
  await page.goto('./')
  await expect(page).toHaveURL(new RegExp(`#${featured.name}/0/watch$`))
  await expect(
    page.getByRole('navigation', { name: 'Screens' }).getByRole('button', { name: 'Watch' }),
  ).toHaveAttribute('aria-current', 'page')
  await expect(page.locator('.topbar select')).toHaveValue(featured.name)
  await expect(page.locator(`.recording-card[data-recording="${featured.name}"]`)).toHaveAttribute(
    'aria-current',
    'true',
  )
  await expect(page.locator('.scrubber')).toHaveCount(0)
  await expect(counter(page)).toContainText(`of ${featured.ticks}`)
  await expect.poll(() => decisionNow(page), { timeout: 1_500, intervals: [100] }).toBeGreaterThan(1)
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
  // While it plays the counter is not announced, and the frame says what it shows.
  await expect(counter(page)).toHaveAttribute('aria-live', 'off')
  await expect(page.locator('.watch-img.top')).toHaveAttribute('alt', /^The game at decision \d+ of \d+: /)
  // Playback does not rewrite the address four times a second.
  await expect(page).toHaveURL(new RegExp(`#${featured.name}/0/watch$`))
  expect(errors).toEqual([])
})

test('six rows, and over ten decisions the bottom row changes while the top row does not', async ({ page }) => {
  await page.goto('./')
  await expect(page.locator('.chain-row')).toHaveCount(6)
  await expect(page.locator('.chain-row').first()).toHaveAttribute('data-level', 'gate')
  await expect(page.locator('.chain-row').last()).toHaveAttribute('data-level', 'motor')
  const top = new Set<string>()
  const bottom = new Set<string>()
  const pulses = new Set<string>()
  // Sampled faster than the agent decides, from the first decision to past the tenth.
  await expect
    .poll(
      async () => {
        top.add((await rowValue(page, 'gate').textContent()) ?? '')
        bottom.add((await rowValue(page, 'motor').textContent()) ?? '')
        const changed = await page
          .locator('.chain-row[data-changed]')
          .evaluateAll((rows) => rows.map((r) => r.getAttribute('data-level') ?? ''))
        changed.forEach((level) => pulses.add(level))
        return decisionNow(page)
      },
      { timeout: 6_000, intervals: [60] },
    )
    .toBeGreaterThan(10)
  expect(top.size).toBe(1)
  expect(bottom.size).toBeGreaterThan(1)
  expect(pulses.has('motor')).toBe(true)
  expect(pulses.has('gate')).toBe(false)
})

test('pause, then a row opens the chain at the same decision with that level expanded', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./')
  await expect.poll(() => decisionNow(page), { timeout: 3_000 }).toBeGreaterThan(3)
  await page.getByRole('button', { name: 'Pause', exact: true }).click()
  const held = await decisionNow(page)
  await page.waitForTimeout(500)
  expect(await decisionNow(page)).toBe(held)
  // The paused decision is now in the address; tick numbers start at 0.
  await expect(page).toHaveURL(new RegExp(`#${featured.name}/${held - 1}/watch$`))
  await expect(counter(page)).toHaveAttribute('aria-live', 'polite')

  await page.getByRole('button', { name: /^Steering: / }).click()
  await expect(page).toHaveURL(new RegExp(`#${featured.name}/${held - 1}/hierarchy$`))
  await expect(page.locator('#level-steering .dc-toggle')).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('#level-arbiter .dc-toggle')).toHaveAttribute('aria-expanded', 'false')
  await expect(page.locator('#level-steering')).toHaveClass(/flash/)
  await expect(page.getByTestId('tick-counter')).toContainText(`Tick ${held - 1} /`)
  // The chain keeps the frame the agent saw at this decision.
  await expect(page.locator('.saw-card img')).toHaveAttribute(
    'src',
    new RegExp(`frames/${String(held - 1).padStart(5, '0')}\\.jpg$`),
  )
  await expect(page.locator('.saw-card')).toContainText(`Decision ${held} of ${featured.ticks}`)
  // Back returns to Watch at the same decision, paused.
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`#${featured.name}/${held - 1}/watch$`))
  await expect(counter(page)).toContainText(`decision ${held} of`)
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('a card opens another recording, playing from its first decision', async ({ page }) => {
  const errors = collectErrors(page)
  const other = index.episodes.find((e) => e.name !== featured.name) as Entry
  await page.goto('./')
  await expect.poll(() => decisionNow(page), { timeout: 3_000 }).toBeGreaterThan(3)
  const card = page.locator(`.recording-card[data-recording="${other.name}"]`)
  await card.locator('.recording-main').click()
  await expect(page).toHaveURL(new RegExp(`#${other.name}/0/watch$`))
  await expect(card).toHaveAttribute('aria-current', 'true')
  await expect(counter(page)).toContainText(`of ${other.ticks}`)
  await expect.poll(() => decisionNow(page), { timeout: 2_500, intervals: [100] }).toBeGreaterThan(1)
  await expect(page.locator('.topbar select')).toHaveValue(other.name)

  // Its other link says how the recording was made.
  await card.getByRole('button', { name: /How this recording was made/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Reference' })
  await expect(dialog.getByRole('tab', { name: 'This recording' })).toHaveAttribute('aria-selected', 'true')
  await expect(dialog.locator('.prov-title')).toContainText(`seed ${other.name.split('-').pop()}`)
  expect(errors).toEqual([])
})

test('the end shows the result over the last screen, then the landing starts again', async ({ page }) => {
  test.slow()
  await page.goto('./')
  const result = page.getByTestId('watch-end')
  await expect(result).toHaveText(/^Cleared the corridor: \d+ decisions, \d+ kills/, { timeout: 20_000 })
  await expect(page.locator('.watch-img.top')).toHaveAttribute('src', /frames\/end\.jpg$/)
  await expect(page.getByTestId('watch-end')).toContainText('Starting again')
  // After the hold, it plays again from the first decision.
  await expect(result).toHaveCount(0, { timeout: 4_000 })
  await expect.poll(() => decisionNow(page), { timeout: 2_000 }).toBeLessThan(10)
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
})

test('a link to a later decision waits for Play, and plays to the end once', async ({ page }) => {
  await page.goto(`./#${featured.name}/${featured.ticks - 4}/watch`)
  await expect(counter(page)).toContainText(`decision ${featured.ticks - 3} of ${featured.ticks}`)
  await page.waitForTimeout(600)
  expect(await decisionNow(page)).toBe(featured.ticks - 3)
  await page.getByRole('button', { name: 'Play the recording' }).click()
  await expect(page.getByTestId('watch-end')).toBeVisible({ timeout: 3_000 })
  await expect(page.getByTestId('watch-end')).not.toContainText('Starting again')
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`#${featured.name}/${featured.ticks - 1}/watch$`))
  // Play at the end starts from the first decision.
  await page.getByRole('button', { name: 'Play', exact: true }).click()
  await expect(page.getByTestId('watch-end')).toHaveCount(0)
  await expect.poll(() => decisionNow(page), { timeout: 2_000 }).toBeLessThan(10)
})

test('with reduced motion nothing plays until Play is pressed', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('./')
  await expect(page).toHaveURL(new RegExp(`#${featured.name}/0/watch$`))
  const play = page.getByRole('button', { name: 'Play the recording' })
  await expect(play).toBeVisible()
  await page.waitForTimeout(1_500)
  expect(await decisionNow(page)).toBe(1)
  await play.click()
  await expect.poll(() => decisionNow(page), { timeout: 2_000 }).toBeGreaterThan(1)
  await expect(play).toHaveCount(0)
})

test('the pace switches to one decision a second, and is kept on the next visit', async ({ page }) => {
  await page.goto('./')
  await page.getByRole('group', { name: 'Pace' }).getByRole('button', { name: 'Slow' }).click()
  await expect(page.getByRole('group', { name: 'Pace' }).getByRole('button', { name: 'Slow' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  const at = await decisionNow(page)
  await page.waitForTimeout(1_600)
  const later = await decisionNow(page)
  expect(later - at).toBeGreaterThanOrEqual(1)
  expect(later - at).toBeLessThanOrEqual(2)
  await page.reload()
  await expect(page.getByRole('group', { name: 'Pace' }).getByRole('button', { name: 'Slow' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
})

test('the help card goes away when dismissed and stays away', async ({ page }) => {
  await page.goto('./')
  const help = page.getByRole('complementary', { name: 'How to read this' })
  await expect(help).toContainText('four decisions a second')
  await help.getByRole('button', { name: 'Got it' }).click()
  await expect(help).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.chain-row')).toHaveCount(6)
  await expect(page.getByRole('complementary', { name: 'How to read this' })).toHaveCount(0)
})

test('the honesty line opens This recording at the serve command', async ({ page }) => {
  await page.goto('./')
  await page.getByRole('button', { name: /run it on your machine/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Reference' })
  await expect(dialog.getByRole('tab', { name: 'This recording' })).toHaveAttribute('aria-selected', 'true')
  const section = dialog.locator('#prov-live')
  await expect(section).toBeInViewport()
  await expect(section.locator('.command code')).toHaveText(
    `python -m system1_doom.serve --scenario deadly_corridor.cfg --seed 9 --model latest`,
  )
})

test('a screen change ends the landing’s playback, and old links open what they opened', async ({ page }) => {
  await page.goto('./')
  await expect.poll(() => decisionNow(page), { timeout: 3_000 }).toBeGreaterThan(2)
  await page.keyboard.press('3')
  await expect(page).toHaveURL(new RegExp(`#${featured.name}/\\d+$`))
  await expect(page.locator('#panel-arbiter')).toBeVisible()
  const tick = await page.getByTestId('tick-counter').getAttribute('data-tick')
  await page.waitForTimeout(600)
  expect(await page.getByTestId('tick-counter').getAttribute('data-tick')).toBe(tick)

  await page.goto('./#deadly_corridor-heuristics-9/18')
  await expect(page.locator('#panel-legal')).toBeVisible()
  await page.goto('./#deadly_corridor-heuristics-9/18/overview')
  await expect(page.locator('svg.architecture')).toBeVisible()
  await expect(
    page.getByRole('navigation', { name: 'Screens' }).getByRole('button', { name: 'The diagram' }),
  ).toHaveAttribute('aria-current', 'page')
})

test('on a phone the frame is in the first screen and nothing scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./')
  const frame = page.locator('.watch-frame')
  await expect(frame).toBeVisible()
  const box = await frame.boundingBox()
  if (!box) throw new Error('frame not rendered')
  expect(box.y).toBeGreaterThanOrEqual(0)
  expect(box.y + box.height).toBeLessThanOrEqual(844)
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(390)
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  // The screens scroll sideways in one row of the bar.
  const tops = await page
    .getByRole('navigation', { name: 'Screens' })
    .getByRole('button')
    .evaluateAll((items) => items.map((el) => Math.round(el.getBoundingClientRect().top)))
  expect(new Set(tops).size).toBe(1)
})
