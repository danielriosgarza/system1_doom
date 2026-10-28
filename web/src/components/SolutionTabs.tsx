import { SOLUTION_TITLES } from '../content/rules/words'
import { SOLUTIONS, entriesOf, switchSolution, useApp } from '../store'

/**
 * The side tab: which solution the screens show (the senses and central, the rule tree, the local models). A vertical
 * bar on the left edge; on a phone, a row of buttons above the top bar. It shows only when more than one solution has
 * recordings here, and lists those.
 */
export function SolutionTabs() {
  const solution = useApp((s) => s.solution)
  const index = useApp((s) => s.index)
  const shown = SOLUTIONS.filter((s) => entriesOf(s.id, index).length > 0)
  if (shown.length < 2) return null
  return (
    <nav className="solution-tabs" aria-label="Solution" data-testid="solution-tabs">
      {shown.map((s) => (
        <button
          key={s.id}
          type="button"
          data-solution={s.id}
          aria-current={solution === s.id ? 'page' : undefined}
          title={SOLUTION_TITLES[s.id]}
          onClick={() => void switchSolution(s.id)}
        >
          <span className="solution-label">{s.label}</span>
        </button>
      ))}
    </nav>
  )
}
