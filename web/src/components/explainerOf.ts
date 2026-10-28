import { EXPLAINERS, type Explainer, type PanelId } from '../content/explainers'
import { LOCAL_OVERRIDES } from '../content/local/explainers'
import type { Solution } from '../store'

/** A panel's explainer as the solution showing words it: the local models' screens say Laya where the rule tree says Jev. */
export function explainerOf(id: PanelId, solution: Solution): Explainer & { formula?: string; code?: string } {
  return (solution === 'local' ? LOCAL_OVERRIDES[id] : undefined) ?? EXPLAINERS[id]
}
