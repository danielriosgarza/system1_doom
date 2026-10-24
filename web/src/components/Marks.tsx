import type { TickEventKind } from '../data/derive'

/** One event mark of the timeline, shared by every strip that draws an episode tick by tick. */
export function Mark({ kind, x, y }: { kind: TickEventKind; x: number; y: number }) {
  switch (kind) {
    case 'damage':
      return <path d={`M${x - 4},${y - 3} h8 l-4,6 z`} fill="var(--neg)" />
    case 'kill':
      return <path d={`M${x},${y - 5} l4,5 l-4,5 l-4,-5 z`} fill="var(--combat)" />
    case 'death':
      return <path d={`M${x - 4},${y - 4} l8,8 M${x + 4},${y - 4} l-8,8`} stroke="var(--neg)" strokeWidth={2} />
    case 'sampled':
      return <circle cx={x} cy={y} r={3.5} fill="none" stroke="var(--n1)" strokeWidth={1.5} />
    case 'committed':
      return <rect x={x - 3.5} y={y - 3.5} width={7} height={7} fill="var(--accent)" />
    case 'expansion':
      return <path d={`M${x - 3},${y + 5} v-10 l7,3 l-7,3`} fill="var(--goal)" stroke="var(--goal)" strokeWidth={1} />
    case 'admission':
      return <path d={`M${x - 4},${y} h8 M${x},${y - 4} v8`} stroke="var(--goal)" strokeWidth={2.5} />
    case 'strategy':
      return <rect x={x - 1} y={y - 5} width={2.5} height={10} fill="var(--navigation)" />
  }
}
