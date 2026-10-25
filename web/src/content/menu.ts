// The words of the Growing the menu screen.
export const MENU = {
  title: 'Growing the menu: new macros, admitted by d1-ultra',
  intro:
    'The menu is the only thing that can be executed. System 2’s menu reflector may ask for a new macro for one sense’s problem; the slow path then writes one bounded macro, which must parse, use only legal primitives and survive the sandbox before the admit instance, one more d1-ultra call, answers yes or no.',
  columns: ['Action', 'Kind', 'Primitives', 'Legal now', 'Executed', 'What it does'],
  kind: { primitive: 'primitive', builtin: 'built-in macro', admitted: 'admitted macro' },
  executedNow: 'executed at this decision',
  reflectorColumns: ['Cycle', 'Speak', 'Change', 'Reason', 'What came of it'],
  notCalled: (why: string) => `not called: ${why}`,
  noCycles: 'System 2 made no cycle during this episode.',
  none: 'No proposal in this episode: System 2 did not ask the slow path for a macro.',
  proposal: (tick: number | null | undefined) =>
    tick === null || tick === undefined ? 'A proposal' : `Proposal after decision ${tick + 1}`,
  admitted: (id: string) => `admitted as ${id}`,
  rejected: 'not admitted',
  askedBy: (who: string, source: string) => `asked for the ${who} sense’s problem; written by the ${source}`,
  request: 'The request, verbatim',
  raw: 'The proposal, verbatim',
  stages: 'The bounds it passed through',
  sandbox: 'The sandbox’s rough projection',
  skipped: 'skipped',
  admitTitle: (n: number) => `The admit instance’s answer to proposal ${n}`,
  admitSaw: 'What the admit instance saw, verbatim',
  admitNone: 'This proposal stopped before the admit instance was asked.',
  yes: 'yes: it joins the menu at the next tick boundary',
  no: 'no: it stays out',
  pick: 'Show its admit instance',
}
