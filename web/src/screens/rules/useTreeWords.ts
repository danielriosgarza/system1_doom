import { LOCAL_QUESTIONS, LOCAL_WATCH } from '../../content/local/words'
import { QUESTIONS, RULES_WATCH } from '../../content/rules/words'
import { useApp } from '../../store'

/** The words of the rule-tree screens the two tree solutions share, in the words of the one showing: Jev's or Laya's. */
export function useTreeWords(): { watch: typeof RULES_WATCH; questions: typeof QUESTIONS } {
  const local = useApp((s) => s.solution === 'local')
  return local ? { watch: LOCAL_WATCH, questions: LOCAL_QUESTIONS } : { watch: RULES_WATCH, questions: QUESTIONS }
}
