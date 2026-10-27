import { SOLUTION_TITLES } from '../content/rules/words'
import { SOLUTIONS, switchSolution, useApp } from '../store'

/**
 * The side tab: which of the two solutions the screens show. A vertical bar on the left edge; on a phone, two
 * buttons above the top bar. It shows only when both solutions have recordings here.
 */
export function SolutionTabs() {
  const solution = useApp((s) => s.solution)
  const both = useApp((s) => (s.index?.rules?.length ?? 0) > 0 && (s.index?.episodes.length ?? 0) > 0)
  if (!both) return null
  return (
    <nav className="solution-tabs" aria-label="Solution" data-testid="solution-tabs">
      {SOLUTIONS.map((s) => (
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
