import { EXPLAINERS, type Explainer, type PanelId } from '../content/explainers'
import { LOCAL_OVERRIDES } from '../content/local/explainers'
import { REALTIME_OVERRIDES } from '../content/realtime/explainers'
import type { Solution } from '../store'

/**
 * A panel's explainer as the solution showing words it: the local models' screens say Laya where the rule tree says
 * Jev, and real time's say too that the game does not wait.
 */
export function explainerOf(id: PanelId, solution: Solution): Explainer & { formula?: string; code?: string } {
  const own = solution === 'local' ? LOCAL_OVERRIDES[id] : solution === 'realtime' ? REALTIME_OVERRIDES[id] : undefined
  return own ?? EXPLAINERS[id]
}
