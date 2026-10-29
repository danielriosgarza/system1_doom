import { LOCAL_QUESTIONS, LOCAL_WATCH } from '../../content/local/words'
import { REALTIME_QUESTIONS, REALTIME_WATCH } from '../../content/realtime/words'
import { QUESTIONS, RULES_WATCH } from '../../content/rules/words'
import { useApp } from '../../store'

/** The words of the rule-tree screens the tree solutions share, in the words of the one showing: Jev's or Laya's. */
export function useTreeWords(): { watch: typeof RULES_WATCH; questions: typeof QUESTIONS } {
  const solution = useApp((s) => s.solution)
  if (solution === 'local') return { watch: LOCAL_WATCH, questions: LOCAL_QUESTIONS }
  if (solution === 'realtime') return { watch: REALTIME_WATCH, questions: REALTIME_QUESTIONS }
  return { watch: RULES_WATCH, questions: QUESTIONS }
}
