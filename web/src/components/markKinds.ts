import type { TickEventKind } from '../data/derive'

/** Which lane of a timeline strip each event mark sits in: outcomes above, decisions below. */
export const KIND_LANE: Record<TickEventKind, 'top' | 'bottom'> = {
  damage: 'top',
  kill: 'top',
  death: 'top',
  sampled: 'bottom',
  committed: 'bottom',
  expansion: 'bottom',
  admission: 'bottom',
  rejection: 'bottom',
  strategy: 'bottom',
}

/** The marks in legend order, with their words. */
export const MARK_LEGEND: Array<{ kind: TickEventKind; label: string }> = [
  { kind: 'damage', label: 'damage' },
  { kind: 'kill', label: 'kill' },
  { kind: 'death', label: 'death' },
  { kind: 'sampled', label: 'sampled pick' },
  { kind: 'committed', label: 'module committed' },
  { kind: 'expansion', label: 'asked for a macro' },
  { kind: 'admission', label: 'macro admitted' },
  { kind: 'rejection', label: 'macro rejected' },
  { kind: 'strategy', label: 'strategy switch' },
]
