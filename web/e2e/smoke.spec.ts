import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

interface Trace {
  tick: number
  selected_action: string
  available_actions: string[]
}

function ticksOf(episode: string): Trace[] {
  const url = new URL(`../public/episodes/${episode}/ticks.jsonl`, import.meta.url)
  return readFileSync(url, 'utf8')
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line) as Trace)
}

const pretty = (id: string) => id.replaceAll('_', ' ')

function collectErrors(page: import('@playwright/test').Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  return errors
}

test('scrubbing to tick 5 shows the action the trace selected', async ({ page }) => {
  const errors = collectErrors(page)

  await page.goto('./')
  await page.getByRole('navigation', { name: 'Screens' }).getByRole('button', { name: 'Tick' }).click()
  const index = JSON.parse(readFileSync(new URL('../public/episodes/index.json', import.meta.url), 'utf8')) as {
    episodes: Array<{ name: string }>
  }
  const first = index.episodes[0]?.name as string
  const trace = ticksOf(first).find((t) => t.tick === 5) as Trace

  await expect(page.locator('.tick-counter')).toContainText('Tick 0 /')
  // Scrub with the keyboard, the way the timeline's explainer says to.
  await page.locator('body').click({ position: { x: 5, y: 5 } })
  for (let i = 0; i < 5; i += 1) await page.keyboard.press('ArrowRight')
  await expect(page.locator('.tick-counter')).toContainText('Tick 5 /')
  await expect(page).toHaveURL(new RegExp(`#${first}/5$`))

  // The menu lights exactly the legal actions and marks the pick.
  await expect(page.locator('#panel-legal .chip.selected')).toHaveAttribute('data-action', trace.selected_action)
  await expect(page.locator('#panel-legal [data-state="legal"]')).toHaveCount(trace.available_actions.length)
  // The arbiter's verdict, the module matrix and the motor all name the same action.
  await expect(page.getByTestId('pick')).toContainText(pretty(trace.selected_action))
  await expect(page.locator('#panel-modules .is-selected .row-label')).toHaveText(pretty(trace.selected_action))
  await expect(page.locator('#panel-motor .plan strong')).toHaveText(pretty(trace.selected_action))
  await expect(page.locator('#panel-game img')).toHaveAttribute('src', /frames\/00005\.jpg$/)

  expect(errors).toEqual([])
})

test('a link opens the same tick of another episode, and the timeline is clickable', async ({ page }) => {
  const episode = 'deadly_corridor-learned-9'
  const ticks = ticksOf(episode)
  await page.goto(`./#${episode}/17`)
  await expect(page.locator('.tick-counter')).toContainText('Tick 17 /')
  await expect(page.locator('#panel-legal .chip.selected')).toHaveAttribute(
    'data-action',
    ticks.find((t) => t.tick === 17)?.selected_action ?? '',
  )

  const track = page.getByRole('slider', { name: 'Tick' })
  const box = await track.boundingBox()
  if (!box) throw new Error('timeline not rendered')
  await track.click({ position: { x: 8 + 0.5 * ((box.width - 16) / ticks.length), y: box.height / 2 } })
  await expect(page.locator('.tick-counter')).toContainText('Tick 0 /')

  await page.getByRole('button', { name: 'Formula' }).click()
  await page.locator('#panel-arbiter .explain-toggle').click()
  await expect(page.locator('#panel-arbiter .formula')).toContainText('score(a) =')
})

test('a fresh visit opens the overview, and the tour walks six beats to the hierarchy', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./')
  await expect(page.locator('svg.architecture')).toBeVisible()
  await expect(page).toHaveURL(/\/0\/overview$/)

  await page.getByRole('button', { name: 'Take the tour' }).click()
  const card = page.getByRole('dialog')
  // The tour runs on the featured tick: the first kill with an enemy in view.
  await expect(page.locator('.tick-counter')).toContainText('Tick 2 /')
  const beats = ['Freeze the world', 'Shorten the menu', 'Five opinions', 'One decision', 'Act', 'See and remember']
  for (const [i, beat] of beats.entries()) {
    await expect(card).toContainText(`${i + 1} / 7`)
    await expect(card.locator('h2')).toContainText(beat)
    await expect(page).toHaveURL(/\/2$/)
    await page.keyboard.press('ArrowRight')
  }
  // The seventh card is on the hierarchy, over the tower.
  await expect(card).toContainText('7 / 7')
  await expect(page).toHaveURL(/\/2\/hierarchy$/)
  await expect(page.locator('.tower')).toBeVisible()
  await page.keyboard.press('ArrowLeft')
  await expect(card).toContainText('6 / 7')
  await page.keyboard.press('Escape')
  await expect(card).toHaveCount(0)

  await page.getByRole('navigation', { name: 'Screens' }).getByRole('button', { name: 'Overview' }).click()
  await expect(page.getByRole('button', { name: 'Take the tour again' })).toBeVisible()
  expect(errors).toEqual([])
})

test('the hierarchy shows the admission and the pick of the linked tick', async ({ page }) => {
  const errors = collectErrors(page)
  const episode = 'deadly_corridor-heuristics-9'
  const trace = ticksOf(episode).find((t) => t.tick === 18) as Trace
  await page.goto(`./#${episode}/18/hierarchy`)

  const gate = page.locator('#level-gate')
  await expect(gate.getByTestId('choice')).toContainText('admitted evasive burst 1')
  await expect(gate.locator('[data-stage="sandbox"]')).toContainText('passed')
  await expect(gate.locator('[data-stage="d1"]')).toContainText('skipped')
  const arbiter = page.locator('#level-arbiter')
  await expect(arbiter.getByTestId('choice')).toContainText(pretty(trace.selected_action))
  await expect(arbiter.locator('[data-candidate].chosen')).toHaveAttribute('data-candidate', trace.selected_action)

  // A level opens in place, and its link leads to the same tick in the inspector.
  const toggle = page.locator('#level-steering .dc-toggle')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await page.locator('#level-arbiter .dc-toggle').click()
  await page
    .locator('#level-arbiter')
    .getByRole('button', { name: /See this in the inspector/ })
    .click()
  await expect(page).toHaveURL(new RegExp(`#${episode}/18$`))
  await expect(page.locator('#panel-arbiter')).toBeVisible()
  // Back returns to the hierarchy.
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`#${episode}/18/hierarchy$`))
  await expect(page.locator('#level-gate')).toBeVisible()
  expect(errors).toEqual([])
})

test('a box on the overview explains itself and opens its inspector panel', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./#deadly_corridor-heuristics-9/18/overview')
  await page.locator('[data-box="gate"]').click()
  const card = page.locator('.arch-card')
  await expect(card.locator('h2')).toHaveText('Admission gate')
  await card.getByRole('button', { name: /Open in the inspector/ }).click()
  await expect(page).toHaveURL(/#deadly_corridor-heuristics-9\/18$/)
  await expect(page.locator('#panel-legal')).toBeVisible()
  expect(errors).toEqual([])
})

test('the tour fits a phone screen', async ({ page }) => {
  const errors = collectErrors(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./')
  await page.getByRole('button', { name: 'Take the tour' }).click()
  const card = page.getByRole('dialog')
  for (let step = 1; step <= 7; step += 1) {
    await expect(card).toContainText(`${step} / 7`)
    const box = await card.boundingBox()
    if (!box) throw new Error('tour card not rendered')
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(390)
    expect(box.y).toBeGreaterThanOrEqual(0)
    expect(box.y + box.height).toBeLessThanOrEqual(844)
    await expect(card.getByRole('button', { name: /Next|Back to the inspector/ })).toBeInViewport()
    await page.keyboard.press('ArrowRight')
  }
  await expect(card).toHaveCount(0)
  expect(errors).toEqual([])
})
