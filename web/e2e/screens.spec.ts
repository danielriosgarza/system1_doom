import { type Page, expect, test } from '@playwright/test'

// The slow system, Learning, Growing the menu and Reference, on the fixture recording played by the fake
// d1-ultra. Its System 2 admits a macro (version 2, kept) and widens the survival scope to pickups after a
// passed history test (version 3, kept).

const FIXTURE = 'fixture-corridor'

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  return errors
}

test('the slow system lists every configuration version with what made it and what became of it', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto(`./#${FIXTURE}/39/slow`)
  const cards = page.getByTestId('version-card')
  await expect(cards).toHaveCount(3)
  const read = await cards.evaluateAll((els) => els.map((el) => [el.dataset.version, el.dataset.status]))
  expect(read).toEqual([
    ['1', 'start'],
    ['2', 'kept'],
    ['3', 'kept'],
  ])
  await expect(cards.nth(1)).toContainText('admitted macros: + evasive_burst_1')
  await expect(cards.nth(1)).toContainText('proposed by the menu reflector')
  await expect(cards.nth(2)).toContainText('show survival the pickups channel')
  await expect(cards.nth(2)).toContainText('chosen by System 2’s central at 80%')
  await expect(page.getByTestId('system2-summary')).toContainText('1 history test, 1 passed')
  expect(errors).toEqual([])
})

test('the history test’s table: every sampled tick, its stratum, the old and new answers, the metrics, the verdict', async ({
  page,
}) => {
  await page.goto(`./#${FIXTURE}/39/slow`)
  const test_ = page.getByTestId('history-test')
  await expect(test_.getByTestId('test-verdict')).toHaveAttribute('data-status', 'passed')
  await expect(test_).toContainText('composite +0.33 (needs +0.05)')
  const rows = test_.getByTestId('test-row')
  await expect(rows).toHaveCount(12)
  const strata = await rows.evaluateAll((els) => els.map((el) => el.dataset.stratum))
  expect(strata).toEqual([...Array(4).fill('bad'), ...Array(4).fill('good'), ...Array(4).fill('rest')])
  await expect(rows.first()).toContainText('spoke · weave fire (0.90)')
  await expect(rows.first()).toContainText('silent (0.15)')
  const metrics = test_.getByTestId('test-metrics')
  await expect(metrics.locator('[data-metric="quiet"]')).toContainText('0.00')
  await expect(metrics.locator('[data-metric="quiet"]')).toContainText('1.00')
  await expect(metrics.locator('[data-metric="composite"]')).toContainText('0.33')
  await expect(metrics.locator('[data-metric="composite"]')).toContainText('0.67')
  await expect(test_.locator('.scope-line .chip.added')).toHaveText('pickups')
  // The trial that followed, with the judge's answer.
  const trial = page.getByTestId('trial')
  await expect(trial.getByTestId('trial-verdict')).toHaveAttribute('data-verdict', 'keep')
  await expect(trial.getByTestId('trial-table')).toContainText('reward per decision')
  await trial.getByText('What the judge was shown, exactly as sent').click()
  await expect(trial.getByTestId('judge-evidence')).toContainText('[trial]')
})

test('a sampled tick of this episode opens The instances at that decision', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/39/slow`)
  const sample = page.getByTestId('test-row').first().getByRole('button')
  const label = (await sample.textContent()) ?? ''
  const decision = Number(/decision (\d+)/.exec(label)?.[1])
  await sample.click()
  await expect(page).toHaveURL(new RegExp(`#${FIXTURE}/${decision - 1}/instances$`))
  await expect(page.getByTestId('instance-panel')).toHaveAttribute('data-instance', 'survival')
})

test('a cycle shows every reflector’s answers, and what each was shown, verbatim', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/39/slow`)
  await page.locator('[data-testid="cycle-row"][data-cycle="cycle-1"]').click()
  await expect(page.getByTestId('cycle-head')).toHaveAttribute('data-cycle', 'cycle-1')
  const menu = page.locator('[data-reflector="menu_reflector"]')
  await expect(menu.locator('.reflector-state')).toHaveText('proposed')
  await menu.getByRole('button').first().click()
  await expect(menu.getByTestId('reflector-evidence')).toContainText('[h_actions]')
  await expect(page.getByTestId('system2-central')).toContainText('the menu reflector proposes macro:combat')
  // A cycle where the bounds left the survival auditor nothing to propose.
  await page.locator('[data-testid="cycle-row"][data-cycle="cycle-4"]').click()
  await expect(page.locator('[data-reflector="survival_auditor"] .reflector-state')).toHaveText('not called')
})

test('the relevance ledger per sense and situation, with what the central was shown of it', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/12/slow`)
  await expect(page.getByTestId('ledger-totals').locator('[data-sense="survival"]')).toBeVisible()
  await expect(page.getByTestId('ledger-row').first()).toBeVisible()
  await expect(page.getByTestId('central-relevance')).toContainText('[relevance]')
  await expect(page.getByTestId('configuration-changes').locator('[data-instance="survival"]')).toContainText(
    '+ pickups',
  )
})

test('Learning draws relevance over episodes and shows the value networks as evidence', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/0/learning`)
  const chart = page.getByTestId('relevance-chart')
  await expect(chart.locator('g.series')).toHaveCount(5)
  await expect(chart.locator('.legend li')).toHaveCount(5)
  await chart.locator('svg').hover()
  await expect(chart.locator('.chart-tip')).toContainText('survival')
  await page.getByText('The numbers', { exact: true }).click()
  const table = page.getByTestId('relevance-table')
  await expect(table.locator('[data-episodes="2"][data-sense="survival"]')).toContainText('this episode, before')
  // After the episode: survival spoke 42 times, was followed 42 times, and 34 of those paid off.
  await expect(table.locator('[data-episodes="3"][data-sense="survival"]')).toContainText('34 (81%)')
  const values = page.getByTestId('values-table')
  await expect(values.locator('[data-action="move_forward"]')).toContainText('+0.05')
  await expect(page.getByTestId('tried-table')).toBeVisible()
})

test('Growing the menu shows the proposal, its stages, and the admit instance’s answer and evidence', async ({
  page,
}) => {
  await page.goto(`./#${FIXTURE}/12/menu`)
  await expect(page.getByTestId('menu-table').locator('[data-action="evasive_burst_1"]')).toContainText(
    'admitted macro',
  )
  await expect(page.getByTestId('menu-reflector').locator('[data-cycle="cycle-1"]')).toContainText('macro:combat')
  const proposal = page.getByTestId('proposal')
  await expect(proposal).toHaveCount(1)
  await expect(proposal).toHaveAttribute('data-admitted', 'true')
  await expect(proposal.getByTestId('raw-proposal')).toContainText('"id": "evasive_burst_1"')
  await expect(proposal.locator('[data-stage="d1"]')).toContainText('The admit instance said yes')
  const admit = page.getByTestId('admit-instance')
  await expect(admit).toContainText('0.80 · yes')
  await expect(admit.getByTestId('admit-evidence')).toContainText('[proposal]')
})

test('Reference: the one rule, the drawing, the glossary, and how this recording was made', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/0/reference`)
  await expect(page.getByTestId('one-rule')).toHaveText('Every decision here is made by d1-ultra.')
  await expect(page.getByTestId('two-systems').locator('.node.d1')).not.toHaveCount(0)
  expect(await page.getByTestId('glossary-entry').count()).toBeGreaterThanOrEqual(16)
  await expect(page.getByTestId('removed-terms')).toContainText('arbiter')
  await expect(page.getByTestId('provenance')).toContainText('python -m system1_doom.export')
})

test('a linked word opens its glossary entry on Reference', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/3/instances`)
  await page.locator('#panel-evidence .explain-toggle').click()
  const term = page.locator('#panel-evidence .explainer .term[data-term="scope"]')
  await term.click()
  await expect(page).toHaveURL(new RegExp(`#${FIXTURE}/3/reference$`))
  await expect(page.locator('[data-testid="glossary-entry"][data-term="scope"]')).toHaveClass(/marked/)
  // Its "see it" link goes back to the panel that shows it.
  await page.locator('[data-term="scope"] .link').first().click()
  await expect(page).toHaveURL(new RegExp(`#${FIXTURE}/3/instances$`))
})

test('Watch links to how the recording was made', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/3/watch`)
  await page.getByRole('button', { name: /To watch it decide live/ }).click()
  await expect(page).toHaveURL(new RegExp(`#${FIXTURE}/3/reference$`))
  await expect(page.getByTestId('provenance')).toBeInViewport()
})

test('on a phone nothing scrolls sideways, on any screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const screen of ['watch', 'instances', 'slow', 'learning', 'menu', 'reference']) {
    await page.goto(`./#${FIXTURE}/12/${screen}`)
    await expect(page.locator('main')).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, screen).toBeLessThanOrEqual(0)
  }
})

test('at 1280 the top bar is one row with all six screens', async ({ page }) => {
  await page.goto(`./#${FIXTURE}/0/reference`)
  const tabs = page.locator('.topbar .screens button, .topbar .screens a')
  await expect(tabs).toHaveCount(6)
  const box = await page.locator('.topbar').boundingBox()
  expect(box?.height ?? 999).toBeLessThan(70)
  const tops = await page
    .locator('.topbar > *')
    .evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().top)))
  expect(Math.max(...tops) - Math.min(...tops)).toBeLessThan(12)
})
