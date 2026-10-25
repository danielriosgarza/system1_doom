// The decision model a recording was played by, named as the site names it: every decision in a recording is
// one of its answers, and a bundle written before the decider was recorded is d1-ultra's.
import type { EpisodeMeta } from '../schema/bundle'

export type Decider = NonNullable<EpisodeMeta['decider']>

export const DEFAULT_DECIDER: Decider = 'd1-ultra'

export const DECIDERS: Record<Decider, { name: string; maker: string }> = {
  'd1-ultra': { name: 'd1-ultra', maker: 'Liquid AI' },
  jev: { name: 'Jev', maker: 'TypeSafe' },
}

/** The decider a bundle or an index line names, d1-ultra when it names none. */
export const deciderOf = (named?: { decider?: Decider } | null): Decider => named?.decider ?? DEFAULT_DECIDER

/** "d1-ultra" or "Jev". */
export const deciderName = (decider?: Decider | null): string => DECIDERS[decider ?? DEFAULT_DECIDER].name

/** "d1-ultra, Liquid AI’s decision model". */
export function deciderWords(decider?: Decider | null): string {
  const d = DECIDERS[decider ?? DEFAULT_DECIDER]
  return `${d.name}, ${d.maker}’s decision model`
}
