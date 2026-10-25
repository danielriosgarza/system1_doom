import { type Page, expect, test } from '@playwright/test'

// The strip on Watch and The instances screen, on the fixture recording played by the fake d1-ultra: what each
// instance saw, verbatim, and what it answered. The fixture's survival sense is widened to [pickups] at version 3.

const FIXTURE = 'fixture-corridor'

const strip = (page: Page) => page.getByTestId('strip')
const panel = (page: Page) => page.getByTestId('instance-panel')
const evidence = (page: Page) => page.getByTestId('evidence-text')

test('the strip shows five sense rows, spoke, silent or missed, and the central row with its pick', async ({
  page,
}) => {
  await page.goto(`./#${FIXTURE}/3/watch`)
  const rows = strip(page).getByTestId('sense-row')
  await expect(rows).toHaveCount(5)
  await expect(rows.nth(0)).toHaveAttribute('data-sense', 'survival')
  const states = await rows.evaluateAll((els) => els.map((el) => [el.dataset.sense, el.dataset.state]))
  expect(states).toEqual([
    ['survival', 'spoke'],
    ['combat', 'spoke'],
    ['navigation', 'missed'],
    ['resource', 'silent'],
    ['goal', 'silent'],
  ])
  await expect(rows.nth(0)).toContainText('weave fire')
  await expect(rows.nth(0)).toContainText('followed')
  await expect(rows.nth(2)).toContainText('the call failed')
  const central = strip(page).getByTestId('central-row')
  await expect(central).toHaveAttribute('data-kind', 'top')
  await expect(central.getByTestId('central-pick')).toHaveText('weave fire')
  await expect(central).toContainText('its top answer, 70%')
  await expect(central).toContainText('received 2 messages')
  await expect(strip(page).getByTestId('act-row')).toContainText('strafe left')
  await expect(strip(page).getByTestId('config-line')).toHaveAttribute('data-version', '1')
  await expect(strip(page).getByTestId('config-line')).toContainText('no trial in progress')
})

test('the strip says when the central missed, and the configuration line names the trial in progress', async ({
  page,
}) => {
  await page.goto(`./#${FIXTURE}/5/watch`)
  const central = strip(page).getByTestId('central-row')
  await expect(central).toHaveAttribute('data-kind', 'missed')
  await expect(central).toContainText('it answered with something off the menu')
  await page.goto(`./#${FIXTURE}/12/watch`)
  const line = strip(page).getByTestId('config-line')
  await expect(line).toHaveAttribute('data-version', '2')
  await expect(line).toContainText('admitted macros')
  await expect(line).toContainText(/trial in progress: 2 of \d+ decisions observed/)
})

test('clicking a row opens that instance at that decision', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/3/watch`)
  await strip(page).locator('[data-sense="navigation"]').click()
  await expect(page).toHaveURL(new RegExp(`#${FIXTURE}/3/instances$`))
  await expect(panel(page)).toHaveAttribute('data-instance', 'navigation')
  await expect(page.getByRole('tab', { selected: true })).toHaveAttribute('data-instance', 'navigation')
  const miss = panel(page).getByTestId('miss-box')
  await expect(miss).toContainText('the call failed')
  await expect(miss).toContainText('fake d1-ultra outage')
})

test('the survival sense’s evidence is verbatim and never shows a channel outside its scope', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/0/instances`)
  await expect(panel(page)).toHaveAttribute('data-instance', 'survival')
  const text = (await evidence(page).textContent()) ?? ''
  expect(text.startsWith('[vitals]\nhealth 100')).toBe(true)
  expect(text).toContain('[threats]')
  expect(text).not.toContain('[pickups]')
  await expect(panel(page).getByTestId('scope-chips').locator('[data-channel]')).toHaveText([
    'vitals',
    'threats',
    'incoming',
    'menu',
    'projections',
  ])
  await expect(panel(page).getByTestId('hidden-chips').locator('[data-channel="pickups"]')).toBeVisible()
  await expect(panel(page)).toContainText('No screen image: the frame channel is not in its scope.')
})

test('the evidence the browser shows is the text in the trace, character for character', async ({ page, request }) => {
  const ticks = await (await request.get(`episodes/${FIXTURE}/ticks.jsonl`)).text()
  const first = JSON.parse(ticks.split('\n')[0] ?? '{}') as { instances: Record<string, { evidence: string }> }
  await page.goto(`./#${FIXTURE}/0/instances`)
  for (const name of ['survival', 'combat', 'central']) {
    await page.getByRole('tab', { name: new RegExp(`^${name}`) }).click()
    await expect(evidence(page)).toHaveAttribute('data-instance', name)
    expect(await evidence(page).textContent()).toBe(first.instances[name]?.evidence)
  }
})

test('the combat sense never sees the messages; it is sent the screen', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/3/instances`)
  await page.getByRole('tab', { name: /^combat/ }).click()
  await expect(panel(page)).toHaveAttribute('data-instance', 'combat')
  const text = (await evidence(page).textContent()) ?? ''
  expect(text).toContain('[frame]')
  expect(text).not.toContain('[messages]')
  await expect(panel(page).getByTestId('hidden-chips').locator('[data-channel="messages"]')).toBeVisible()
  await expect(panel(page).locator('.instance-frame img')).toHaveAttribute('src', /frames\/00003\.jpg$/)
})

test('after System 2 widened its scope, the survival sense is shown [pickups]', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/30/instances`)
  await page.getByRole('tab', { name: /^survival/ }).click()
  await expect(evidence(page)).toContainText('[pickups]')
  await expect(panel(page).getByTestId('scope-chips').locator('[data-channel="pickups"]')).toBeVisible()
})

test('a central miss shows its reason and the raw answer as returned', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/5/instances`)
  await page.getByRole('tab', { name: /^central/ }).click()
  const miss = panel(page).getByTestId('miss-box')
  await expect(miss).toContainText('it answered with something off the menu')
  await expect(miss).toContainText('No keys were pressed for this decision.')
  await expect(miss.locator('.raw-answer')).toContainText('"choice": "teleport_hack"')
})

test('the answers are bars: the speak strength, the action and reason distributions', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/0/instances`)
  const answers = panel(page).getByTestId('answers')
  await expect(answers).toContainText('Speak')
  await expect(answers.getByRole('list', { name: 'Action distribution' })).toBeVisible()
  await expect(answers.getByRole('list', { name: 'Reason distribution' })).toBeVisible()
  await page.getByRole('tab', { name: /^central/ }).click()
  await expect(answers.getByRole('list', { name: 'The central’s choice distribution' })).toBeVisible()
  await expect(answers).toContainText('survival recommends weave fire, strength 0.90')
})
