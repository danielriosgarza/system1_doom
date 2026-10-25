// The words of the Growing the menu screen.
export const MENU = {
  title: 'Growing the menu: new macros, admitted by d1-ultra',
  intro:
    'The menu is the set of actions the agent can execute. System 2’s menu reflector may propose requesting a new macro for one sense’s problem. The slow path then writes one macro, which must parse, use only known primitives and pass the sandbox simulation. Then the admit instance, one more d1-ultra call, answers yes or no.',
  columns: ['Action', 'Kind', 'Primitives', 'Legal now', 'Executed', 'What it does'],
  kind: { primitive: 'primitive', builtin: 'built-in macro', admitted: 'admitted macro' },
  executedNow: 'executed at this decision',
  reflectorColumns: ['Cycle', 'Speak', 'Change', 'Reason', 'Outcome'],
  notCalled: (why: string) => `not called: ${why}`,
  noCycles: 'System 2 ran no cycle during this episode.',
  none: 'No proposal in this episode: System 2 did not request a macro from the slow path.',
  proposal: (tick: number | null | undefined) =>
    tick === null || tick === undefined ? 'A proposal' : `Proposal after decision ${tick + 1}`,
  admitted: (id: string) => `admitted as ${id}`,
  rejected: 'not admitted',
  askedBy: (who: string, source: string) => `requested for the ${who} sense’s problem; written by the ${source}`,
  request: 'The request, exactly as sent',
  raw: 'The proposal, exactly as written',
  stages: 'The checks it went through',
  sandbox: 'The sandbox’s rough simulation',
  skipped: 'skipped',
  admitTitle: (n: number) => `The admit instance’s answer to proposal ${n}`,
  admitSaw: 'What the admit instance was shown, exactly as sent',
  admitNone: 'This proposal failed a check before the admit instance was asked.',
  yes: 'yes: it joins the menu at the start of the next decision',
  no: 'no: it stays out of the menu',
  pick: 'Show its admit instance',
}
