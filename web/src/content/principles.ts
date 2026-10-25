// The one invariant and the seven design principles (docs/DOCUMENTATION.md, section 1), each with
// how the code enforces it and where the app shows it.
import { D1_SYNC_FLAG } from '../data/derive'
import type { SeeLink } from './glossary'

export const INVARIANT =
  'Generative systems may propose possibilities; bounded decision systems decide what enters the controller and what is executed.'

export interface Principle {
  principle: string
  enforced: string
  see: SeeLink[]
}

export const PRINCIPLES: Principle[] = [
  {
    principle: 'Every behaviour terminates in a finite decision over a finite set.',
    enforced:
      'Only an action from the legal set, chosen by the arbiter, is ever executed; the modules, the simulator, exploration, the archive, d1-ultra and Codex never press a key themselves.',
    see: [
      { screen: 'hierarchy', label: 'Hierarchy (the tower)' },
      { screen: 'tick', panel: 'legal' },
    ],
  },
  {
    principle: 'The real-time loop never blocks.',
    enforced: `No LLM call, network, disk search or unbounded planning on the fast path: d1-ultra is read from a cache, the slow worker runs on one background thread, and learning trains between episodes. The one exception is chosen by hand: a recording made with ${D1_SYNC_FLAG} waits for d1-ultra at every tick, with a 5 s tick budget, so its advice can be shown at every tick.`,
    see: [
      { screen: 'menu', panel: 'requests', label: 'Growing the menu → the busy span' },
      { tab: 'glossary', term: 'budget-mode', label: 'Glossary → budget mode' },
    ],
  },
  {
    principle: 'LLM output cannot execute.',
    enforced:
      'A proposal must parse into the typed schema, use only known primitives, meet the duration bounds, survive the sandbox and, when it is on, the d1 gate, before it joins the menu; free text never reaches the motor.',
    see: [{ screen: 'menu', panel: 'gate' }],
  },
  {
    principle: 'Boundedness everywhere.',
    enforced:
      'Macros at most 16 primitives; projections at most 16 candidates × depth 4 × branching 2 × 15 ms; archive 12; replay 100,000; the empirical cache 50 samples per context and action; module evaluation inside a deadline.',
    see: [{ screen: 'hierarchy', label: 'Hierarchy (the bound badges on every level)' }],
  },
  {
    principle: 'Modules are replaceable.',
    enforced:
      'All five implement the same contract, DecisionInput → DecisionOutput, so one can be swapped without touching the rest; an acceptance test does exactly that.',
    see: [{ screen: 'tick', panel: 'modules' }],
  },
  {
    principle: 'Everything is traceable.',
    enforced:
      'Every tick writes one trace line with the state hash, the context, all module outputs, the projections, the arbiter’s breakdown, the pick, exploration and the learning shares; every proposal writes one too.',
    see: [
      { tab: 'recording', label: 'This recording (the files)' },
      { screen: 'tick', panel: 'scrubber', label: 'The timeline' },
    ],
  },
  {
    principle: 'Learning is advisory and data-gated.',
    enforced:
      'The networks override a heuristic only in proportion to how often that action in that situation was tried, λ = n ÷ (n + 25); an untried action stays heuristic, so learning cannot take over on extrapolation alone.',
    see: [{ screen: 'learning', panel: 'trustmap' }],
  },
]

export const CLOSING =
  'There is deliberately no end-to-end policy, no chain of thought in the loop, no self-modifying code and no single network: the five modules learn independently, each against its own reward.'
