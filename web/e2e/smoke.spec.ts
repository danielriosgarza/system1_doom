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

test('scrubbing to tick 5 shows the action the trace selected', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

  await page.goto('./')
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
