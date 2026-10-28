import { type Page, expect, test } from '@playwright/test'
import { RECORDINGS } from '../playwright.config'

// The rule tree's six screens, read against the shipped recordings' own files: what a screen shows must be what
// decisions.jsonl says, character for character where it shows text Jev was sent.
test.use({ baseURL: RECORDINGS })

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  return errors
}

interface Step {
  kind: 'rule' | 'focus' | 'skill'
  node: string
  question?: string | null
  answer?: { pick?: string | null; miss?: string | null } | null
  pick?: string | null
  focus_line?: string | null
}

interface Decision {
  decision: number
  state_text: string
  steps: Step[]
  node: string
  route: string
  action_words: string
}

const FOCUS_HEAD = '\n\n[focus]\n'

async function rulesRecordings(page: Page): Promise<string[]> {
  const index = (await (await page.request.get(`${RECORDINGS}episodes/index.json`)).json()) as {
    episodes: { name: string; solution?: string; decider?: string }[]
  }
  // The rule tree's tab shows the recordings Jev played; Laya's are the local models' (local.spec.ts).
  return index.episodes.filter((e) => e.solution === 'rule-tree' && e.decider === 'jev').map((e) => e.name)
}

async function decisions(page: Page, name: string): Promise<Decision[]> {
  const body = await (await page.request.get(`${RECORDINGS}episodes/${name}/decisions.jsonl`)).text()
  return body
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as Decision)
}

/**
 * The text each question of a decision was sent, by step index, as bundle.py documents it: the state text, and for
 * the questions after a focus, '\n\n[focus]\n' and that focus's line appended. A new focus starts from the state text.
 */
function textsSent(d: Decision): Map<number, string> {
  const base = d.state_text.split(FOCUS_HEAD)[0] ?? ''
  const out = new Map<number, string>()
  let text = base
  d.steps.forEach((step, i) => {
    if (step.kind === 'skill') return
    if (step.kind === 'focus') text = base
    out.set(i, text)
    if (step.kind === 'focus' && step.focus_line && !step.answer?.miss) text = base + FOCUS_HEAD + step.focus_line
  })
  return out
}

const questionSteps = (d: Decision) => d.steps.flatMap((s, i) => (s.kind === 'skill' ? [] : [i]))

test('Watch shows one row per question of the walk, its pick, and the action played', async ({ page }) => {
  const errors = collectErrors(page)
  const all = await decisions(page, 'rules-corridor-9')
  for (const at of [0, 5, all.length - 1]) {
    const d = all[at] as Decision
    await page.goto(`./#rules/rules-corridor-9/${at}/watch`)
    const rows = page.getByTestId('walk-row')
    await expect(rows).toHaveCount(questionSteps(d).length)
    for (const [k, i] of questionSteps(d).entries()) {
      const step = d.steps[i] as Step
      await expect(rows.nth(k)).toHaveAttribute('data-kind', step.kind)
      await expect(rows.nth(k)).toHaveAttribute('data-node', step.node)
      if (step.kind === 'rule') await expect(rows.nth(k)).toHaveAttribute('data-pick', step.answer?.pick ?? '')
    }
    await expect(page.getByTestId('walk-skill')).toHaveCount(d.steps.filter((s) => s.kind === 'skill').length)
    await expect(page.getByTestId('walk-action')).toHaveText(d.action_words)
    await expect(page.getByTestId('walk-act')).toHaveAttribute('data-node', d.node)
  }
  expect(errors).toEqual([])
})

test('a row of the walk opens The questions at that question', async ({ page }) => {
  const d = (await decisions(page, 'rules-corridor-9'))[5] as Decision
  await page.goto('./#rules/rules-corridor-9/5/watch')
  await page.getByTestId('walk-row').nth(1).click()
  await expect(page).toHaveURL(/#rules\/rules-corridor-9\/5\/questions$/)
  await expect(page.getByTestId('question-panel')).toHaveAttribute('data-step', String(questionSteps(d)[1]))
})

test('The questions shows the text of every question exactly as Jev was sent it', async ({ page }) => {
  test.setTimeout(180_000)
  const errors = collectErrors(page)
  const names = await rulesRecordings(page)
  expect(names.length).toBeGreaterThan(0)
  let compared = 0
  let withFocus = 0
  for (const name of names) {
    const all = await decisions(page, name)
    // Every decision of the first recording; a spread of decisions of the others.
    const picked = name === names[0] ? all : all.filter((_, i) => i % 7 === 0)
    await page.goto(`./#rules/${name}/${picked[0]?.decision ?? 0}/questions`)
    for (const d of picked) {
      const at = all.indexOf(d)
      await page.evaluate((hash) => (window.location.hash = hash), `#rules/${name}/${at}/questions`)
      await expect(page.getByTestId('tick-counter')).toContainText(`Decision ${at + 1} /`)
      const texts = textsSent(d)
      const tabs = page.getByRole('tab')
      await expect(tabs).toHaveCount(texts.size)
      for (const [i, text] of texts) {
        await page.locator(`[role="tab"][data-step="${i}"]`).click()
        await expect(page.getByTestId('question-panel')).toHaveAttribute('data-step', String(i))
        expect(await page.getByTestId('state-text').textContent(), `${name} decision ${at} step ${i}`).toBe(text)
        compared += 1
        if (text.includes(FOCUS_HEAD)) withFocus += 1
      }
    }
  }
  // The comparison covered the questions asked under a focus line, not only the first question of each walk.
  expect(compared).toBeGreaterThan(100)
  expect(withFocus).toBeGreaterThan(20)
  expect(errors).toEqual([])
})

test('How the rules were written: a rule added by the soft loop links to it in the tree', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('./#rules/rules-corridor-9/0/written')
  await expect(page.getByTestId('build-list')).toBeVisible()
  expect(await page.getByTestId('build-row').count()).toBeGreaterThan(3)
  await expect(page.locator('[data-testid="build-row"][data-kind="pass"]').first()).toBeVisible()
  const added = page.locator('[data-testid="build-row"][data-kind="proposal"]', { hasText: 'added' }).first()
  await added.click()
  const detail = page.getByTestId('build-detail')
  await expect(detail).toHaveAttribute('data-outcome', 'added')
  const link = detail.locator('.build-added button').first()
  const id = /\b(r\d+)\b/.exec((await link.textContent()) ?? '')?.[1]
  expect(id).toBeTruthy()
  await link.click()
  await expect(page).toHaveURL(/#rules\/rules-corridor-9\/0\/tree$/)
  await expect(page.getByTestId('rule-detail')).toHaveAttribute('data-node', id ?? '')
  // The rule's record links back to the step that added it.
  await page
    .getByTestId('rule-detail')
    .getByRole('button', { name: /How the rules were written/ })
    .click()
  await expect(page).toHaveURL(/#rules\/rules-corridor-9\/0\/written$/)
  await expect(page.getByTestId('build-detail')).toHaveAttribute('data-outcome', 'added')
  expect(errors).toEqual([])
})

test('Results: the rules each decision ended at add up to the recording’s decisions', async ({ page }) => {
  const all = await decisions(page, 'rules-corridor-11')
  await page.goto('./#rules/rules-corridor-11/0/results')
  await expect(page.getByTestId('passes')).toBeVisible()
  await expect(page.getByTestId('benchmark')).toBeVisible()
  await expect(page.getByTestId('totals')).toBeVisible()
  const ended = new Map<string, number>()
  for (const d of all) ended.set(d.node, (ended.get(d.node) ?? 0) + 1)
  const rows = page.locator('[data-testid="rule-uses"] tbody tr')
  const shown = await rows.evaluateAll((trs) =>
    trs.map((tr) => [tr.getAttribute('data-rule') ?? '', Number(tr.querySelectorAll('td')[2]?.textContent ?? 0)]),
  )
  for (const [id, n] of shown) expect(n, `${id}`).toBe(ended.get(id as string) ?? 0)
  expect(shown.reduce((sum, [, n]) => sum + (n as number), 0)).toBe(all.length)
  // Every walk starts at the top of the tree.
  await expect(rows.and(page.locator('[data-rule="root"]')).locator('td').nth(1)).toHaveText(String(all.length))
})

test('The rule tree marks the walk of the decision shown and the rule it ended at', async ({ page }) => {
  const all = await decisions(page, 'rules-corridor-12')
  const at = all.findIndex((d) => d.steps.some((s) => s.kind === 'skill'))
  const d = all[Math.max(0, at)] as Decision
  await page.goto(`./#rules/rules-corridor-12/${Math.max(0, at)}/tree`)
  const outline = page.getByTestId('tree-outline')
  await expect(outline.locator('.tree-node.ended')).toHaveCount(1)
  await expect(outline.locator('.tree-node.ended')).toHaveAttribute('data-node', d.node)
  for (const id of ['root', ...d.route.split('/').filter((s) => s !== 'root')]) {
    await expect(outline.locator(`.tree-node[data-node="${id}"]`)).toHaveClass(/on-route/)
  }
  await expect(page.getByTestId('rule-detail')).toHaveAttribute('data-node', d.node)
  await outline.locator('.tree-node[data-node="root"] > .tree-rule').click()
  await expect(page.getByTestId('rule-detail')).toHaveAttribute('data-node', 'root')
})

test('Reference: the rule tree’s drawing and glossary, and how this recording was made', async ({ page }) => {
  await page.goto('./#rules/rules-corridor-9/0/reference')
  await expect(page.getByTestId('rules-drawing')).toBeVisible()
  await expect(page.getByTestId('provenance')).toContainText('--solution rule-tree --tree general-11 --seed 9')
  await expect(page.locator('#term-rule-tree')).toBeVisible()
  await expect(page.locator('#term-cornerstone')).toBeVisible()
  // The senses and central's own words are not in the rule tree's glossary.
  await expect(page.locator('#term-reflector')).toHaveCount(0)
  // A linked word opens its entry.
  await page.getByTestId('rules-drawing').getByRole('button', { name: 'Focus', exact: true }).click()
  await expect(page.locator('#term-focus')).toBeInViewport()
})

test('every rule-tree screen of every shipped recording opens without an error, and none scrolls sideways on a phone', async ({
  page,
}) => {
  test.setTimeout(120_000)
  const errors = collectErrors(page)
  await page.setViewportSize({ width: 390, height: 844 })
  for (const name of await rulesRecordings(page)) {
    for (const screen of ['watch', 'questions', 'written', 'results', 'tree', 'reference']) {
      await page.goto(`./#rules/${name}/12/${screen}`)
      await expect(page.locator('main')).toBeVisible()
      await expect(page.locator('.topbar select')).toHaveValue(name)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, `${name} ${screen}`).toBeLessThanOrEqual(0)
    }
  }
  expect(errors).toEqual([])
})
