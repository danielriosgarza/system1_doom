import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

interface Trace {
  tick: number
  selected_action: string
  available_actions: string[]
  context_signature: string
  arbiter?: { gate_share?: number | null } | null
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

test('the learning screen shows the evaluation, the training run, trust and the gate at a tick', async ({ page }) => {
  const errors = collectErrors(page)
  const episode = 'deadly_corridor-learned-9'
  const trace = ticksOf(episode).find((t) => t.tick === 17) as Trace
  await page.goto(`./#${episode}/17/learning`)

  const h2h = page.locator('#panel-headtohead')
  await expect(h2h.locator('[data-brain]')).toHaveCount(3)
  await expect(h2h.locator('.h2h-strip')).toHaveCount(2)
  await expect(h2h).toContainText('the heuristics alone died after 36 decisions')
  await expect(page.locator('#panel-curves')).toContainText('300 training episodes')
  await expect(page.locator('#panel-curves .curve')).toHaveCount(8)
  await expect(page.locator('#panel-trustmap tr.pinned')).toHaveAttribute('data-context', trace.context_signature)
  await expect(page.locator('#panel-trustmap .th-table tbody tr')).toHaveCount(trace.available_actions.length)
  const g = (trace.arbiter?.gate_share ?? NaN).toFixed(3)
  await expect(page.locator('#panel-gateview')).toContainText(`× g = ${g}`)
  await expect(page.locator('#panel-anatomy [data-module]')).toHaveCount(5)
  expect(errors).toEqual([])
})

test('without networks the learning screen says so and links to the recording that has them', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./#deadly_corridor-heuristics-9/17/learning')
  await expect(page.getByTestId('no-networks')).toHaveCount(2)
  await expect(page.locator('#panel-curves .curve').first()).toBeVisible()
  await page.getByTestId('no-networks').first().getByRole('button').click()
  await expect(page).toHaveURL(/#deadly_corridor-learned-9\/17\/learning$/)
  await expect(page.locator('#panel-trustmap tr.pinned')).toBeVisible()
  expect(errors).toEqual([])
})

test('the replay buffer on the overview opens the training curves', async ({ page }) => {
  await page.goto('./#deadly_corridor-learned-9/17/overview')
  await page.locator('[data-box="replay"]').click()
  await page
    .locator('.arch-card')
    .getByRole('button', { name: /Open in Learning/ })
    .click()
  await expect(page).toHaveURL(/\/17\/learning$/)
  await expect(page.locator('#panel-curves')).toBeInViewport()
})

test('the learning screen fits a phone screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./#deadly_corridor-learned-9/17/learning')
  await expect(page.locator('#panel-trustmap tr.pinned')).toBeVisible()
  await expect(page.locator('#panel-headtohead .h2h-strip')).toHaveCount(2)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('growing the menu follows the proposal that arrived at tick 18 from the ask to the new chip', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./#deadly_corridor-heuristics-9/18/menu')

  const timeline = page.locator('#panel-requests')
  await expect(timeline.locator('.rt-row')).toHaveCount(5)
  await expect(timeline.locator('.rt-row[data-module="survival"] svg')).toHaveAttribute(
    'aria-label',
    'survival: asked at tick 17 and 28',
  )
  const card = page.locator('#panel-proposal .proposal-card')
  await expect(card).toHaveAttribute('data-proposal', 'evasive_burst_1')
  await expect(card.getByTestId('proposal-source')).toHaveText('the fallback template')
  await expect(card).toContainText('the survival module')
  await expect(card.locator('.pc-raw pre')).toBeHidden()
  await card.locator('.pc-raw summary').click()
  await expect(card.locator('.pc-raw pre')).toContainText('"primitive_expansion"')
  await expect(page.locator('#panel-gate .pipeline .stage')).toHaveCount(5)
  await expect(page.locator('#panel-gate .gate-reasons li')).toHaveCount(5)
  await expect(page.locator('#panel-gate')).toContainText('survival was 0.31, so it passed')
  const arrived = page.locator('#panel-encoding .vd-row[data-tick="18"]')
  await expect(arrived.locator('.chip.highlight')).toHaveAttribute('data-action', 'evasive_burst_1')
  await expect(page.locator('#panel-encoding .vd-row[data-tick="17"] .chip.highlight')).toHaveCount(0)
  await expect(page.locator('#panel-encoding tr[data-action="evasive_burst_1"] td')).toHaveCount(12)
  await expect(page.locator('#panel-encoding tr[data-action="weave_fire"] td')).toHaveCount(12)
  expect(errors).toEqual([])
})

test('the follow-up names the strategy adoption, and links to it in the hierarchy', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./#deadly_corridor-heuristics-9/27/menu')
  const first = page.locator('#panel-followup [data-macro="evasive_burst_1"]')
  await expect(first).toContainText('0 of 18 ticks')
  await expect(first).toContainText('after tick 27 and kept it through tick 34')
  await expect(first).toContainText('on ticks 28 to 35 the arbiter added +0.15')
  await expect(page.locator('#panel-proposal .proposal-card.earlier')).toContainText('Arrived at tick 18')
  await first.getByRole('button', { name: /See the switch in the hierarchy at tick 27/ }).click()
  await expect(page).toHaveURL(/#deadly_corridor-heuristics-9\/27\/hierarchy$/)
  await expect(page.locator('#level-steering [data-testid="choice"]')).toContainText('evasive burst 1')
  expect(errors).toEqual([])
})

test('without a request the menu screen names the closest call and links to the recording that asked', async ({
  page,
}) => {
  const errors = collectErrors(page)
  await page.goto('./#deadly_corridor-learned-9/17/menu')
  const note = page.getByTestId('no-requests')
  await expect(note).toContainText('the closest was combat at tick 2, failures 1 of 3')
  await expect(page.locator('#panel-requests .rt-row')).toHaveCount(5)
  await note.getByRole('button', { name: /at tick 17/ }).click()
  await expect(page).toHaveURL(/#deadly_corridor-heuristics-9\/17\/menu$/)
  await expect(page.locator('#panel-proposal')).toContainText('survival asked at tick 17')
  expect(errors).toEqual([])
})

test('the admission gate on the overview opens Growing the menu, and the screen fits a phone', async ({ page }) => {
  await page.goto('./#deadly_corridor-heuristics-9/18/overview')
  await page.locator('[data-box="gate"]').click()
  await page
    .locator('.arch-card')
    .getByRole('button', { name: /Open in Growing the menu/ })
    .click()
  await expect(page).toHaveURL(/\/18\/menu$/)
  await expect(page.locator('#panel-gate')).toBeInViewport()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./#deadly_corridor-heuristics-9/27/menu')
  await expect(page.locator('#panel-followup [data-macro]')).toHaveCount(2)
  // The charts take the new width a frame or two after the follow-up renders, later on a busy machine.
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('the glossary filters, and a “where to see it” link flashes the panel', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./#deadly_corridor-learned-9/17/learning')
  await page.getByRole('button', { name: 'Glossary' }).click()
  const dialog = page.getByRole('dialog', { name: 'Reference' })
  await expect(dialog.getByRole('tab', { name: 'Glossary' })).toHaveAttribute('aria-selected', 'true')
  const entries = dialog.locator('.gloss-entry')
  const all = await entries.count()
  await dialog.getByRole('searchbox', { name: 'Filter the glossary' }).fill('trust')
  await expect(entries).not.toHaveCount(all)
  for (const text of await entries.allInnerTexts()) expect(text.toLowerCase()).toContain('trust')
  const trust = dialog.locator('[data-entry="trust-lambda"]')
  await expect(trust).toContainText('λ = n ÷ (n + 25)')
  await trust.getByRole('button', { name: /Trust, situation by situation/ }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('#panel-trustmap')).toHaveClass(/flash/)
  await expect(page).toHaveURL(/\/learning$/)
  expect(errors).toEqual([])
})

test('a linked word in an explanation opens its glossary entry', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./#deadly_corridor-learned-9/17')
  const arbiter = page.locator('#panel-arbiter')
  await arbiter.locator('.explain-toggle').click()
  await expect(arbiter.locator('.term').first()).toBeVisible()
  await arbiter.locator('.term[data-term="trust-lambda"]').click()
  const entry = page.getByRole('dialog').locator('#term-trust-lambda')
  await expect(entry).toHaveAttribute('aria-current', 'true')
  await expect(entry).toBeInViewport()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(arbiter.locator('.term[data-term="trust-lambda"]')).toBeFocused()
  expect(errors).toEqual([])
})

test('the principles tab lists seven, and the last one opens the trust map', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./#deadly_corridor-learned-9/17')
  await page.getByRole('button', { name: 'Glossary' }).click()
  const dialog = page.getByRole('dialog', { name: 'Reference' })
  await dialog.getByRole('tab', { name: 'Principles' }).click()
  await expect(dialog.locator('.invariant')).toContainText('bounded decision systems decide')
  const rows = dialog.locator('[data-principle]')
  await expect(rows).toHaveCount(7)
  await rows
    .nth(6)
    .getByRole('button', { name: /Trust, situation by situation/ })
    .click()
  await expect(dialog).toHaveCount(0)
  await expect(page).toHaveURL(/\/17\/learning$/)
  await expect(page.locator('#panel-trustmap')).toHaveClass(/flash/)
  expect(errors).toEqual([])
})

test('the ⓘ button says how each recording was made and how to make it again', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./#deadly_corridor-learned-9/17')
  await page.getByRole('button', { name: 'About this recording' }).click()
  const dialog = page.getByRole('dialog', { name: 'Reference' })
  await expect(dialog.getByRole('tab', { name: 'This recording' })).toHaveAttribute('aria-selected', 'true')
  await expect(dialog).toContainText('seed 9')
  const checkpoint = dialog.getByTestId('checkpoint')
  await expect(checkpoint).toContainText('300')
  await expect(checkpoint).toContainText('25,204')
  await expect(dialog.locator('.command code').first()).toContainText('--model latest')
  await expect(dialog.locator('[data-module]')).toHaveCount(5)

  await dialog.getByRole('button', { name: /heuristics only, seed 9, at tick 17/ }).click()
  await expect(page).toHaveURL(/#deadly_corridor-heuristics-9\/17$/)
  await expect(dialog.getByTestId('checkpoint')).toContainText('the heuristics played alone')
  await expect(dialog.locator('.command code').first()).toContainText('--model heuristics')
  expect(errors).toEqual([])
})

test('keys switch screens and open the reference, but not while typing', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./#deadly_corridor-learned-9/17')
  await expect(page.locator('#panel-arbiter')).toBeVisible()
  await page.keyboard.press('3')
  await expect(page).toHaveURL(/\/17\/hierarchy$/)

  await page.keyboard.press('g')
  const dialog = page.getByRole('dialog', { name: 'Reference' })
  await expect(dialog.getByRole('tab', { name: 'Glossary' })).toHaveAttribute('aria-selected', 'true')
  const filter = dialog.getByRole('searchbox', { name: 'Filter the glossary' })
  await filter.click()
  await page.keyboard.type('3')
  await expect(filter).toHaveValue('3')
  await expect(page).toHaveURL(/\/17\/hierarchy$/)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Glossary' })).toBeFocused()

  await page.keyboard.press('?')
  await expect(dialog.getByRole('tab', { name: 'Keyboard' })).toHaveAttribute('aria-selected', 'true')
  await expect(dialog.locator('.key-row')).not.toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.keyboard.press('f')
  await expect(page.getByRole('button', { name: 'Formula' })).toHaveAttribute('aria-pressed', 'true')
  await page.keyboard.press('f')
  expect(errors).toEqual([])
})

test('on a phone the reference fills the screen and leaves no sideways scroll', async ({ page }) => {
  const errors = collectErrors(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./#deadly_corridor-learned-9/17')
  await page.getByRole('button', { name: 'Glossary' }).click()
  const dialog = page.getByRole('dialog', { name: 'Reference' })
  // Measured once the slide-in has finished.
  await expect
    .poll(async () => {
      const box = await dialog.boundingBox()
      return box ? [box.x, box.y, box.width, box.height].map(Math.round) : null
    })
    .toEqual([0, 0, 390, 844])
  for (const tab of ['Principles', 'This recording', 'Keyboard']) {
    await dialog.getByRole('tab', { name: tab }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  }
  await dialog.getByRole('button', { name: 'Close the reference' }).click()
  await expect(dialog).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  expect(errors).toEqual([])
})

test('the top bar keeps to one row at 1280 px', async ({ page }) => {
  await page.goto('./#deadly_corridor-learned-9/17')
  await expect(page.locator('.tick-counter')).toBeVisible()
  const tops = await page
    .locator('.topbar > *')
    .evaluateAll((items) => items.map((el) => el.getBoundingClientRect().top + el.getBoundingClientRect().height / 2))
  expect(Math.max(...tops) - Math.min(...tops)).toBeLessThan(12)
})
