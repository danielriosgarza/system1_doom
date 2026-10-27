// Every word on the rule tree's screens. They follow the same way of writing as the rest of the site: each screen
// opens with one or two sentences that say what it shows, in plain words, and every number comes from the
// recording, or says where it comes from.
import type { RulesBundle } from '../../data/rules'
import type { BundleIndexEntry, RuleTreeEpisodeMeta } from '../../schema/bundle'
import type { Solution } from '../../store'

/** What each tab of the side tab shows, on hover. */
export const SOLUTION_TITLES: Record<Solution, string> = {
  senses:
    'At each decision, five calls to a decision model, the senses, each answer questions about one part of the game, and a sixth call, the central, chooses the action from their answers.',
  rules:
    'At each decision, Jev, TypeSafe’s decision model, answers a few multiple-choice questions that lead through a tree of rules to an action.',
}

/** Who wrote a tree's rules, as the tree names them. */
export function writerWords(writer: string): string {
  if (writer === 'claude') return 'Claude, Anthropic’s model'
  if (writer === 'codex') return 'Codex, OpenAI’s coding agent'
  return writer
}

/** The rule writer's short name: Claude or Codex. */
export const writerName = (writer: string): string =>
  writer === 'claude' ? 'Claude' : writer === 'codex' ? 'Codex' : writer

const placeWords = (scenario: string) => (scenario === 'deadly_corridor.cfg' ? 'the corridor' : 'the level')
const killWords = (kills: number) => `${kills} ${kills === 1 ? 'kill' : 'kills'}`

/** "cleared the corridor in 43 decisions, 6 kills", from the index line alone. */
export function rulesResultWords(
  entry: Pick<BundleIndexEntry, 'scenario' | 'cleared' | 'died' | 'ticks' | 'kills'>,
): string {
  const kills = entry.kills === undefined ? '' : `, ${killWords(entry.kills)}`
  if (entry.cleared) return `cleared ${placeWords(entry.scenario)} in ${entry.ticks} decisions${kills}`
  if (entry.died) return `died after ${entry.ticks} decisions${kills}`
  return `stopped after ${entry.ticks} decisions${kills}`
}

/** How a recording is named on its card and in the picker: its seed and its tree. */
export const rulesRecordingName = (entry: Pick<BundleIndexEntry, 'seed' | 'tree'>): string =>
  `Seed ${entry.seed}, tree ${entry.tree ?? 'unknown'}`

/** The picker's line: "seed 9, tree general-11 · cleared". The rule tree plays the deadly corridor alone. */
export function rulesRecordingLabel(entry: BundleIndexEntry): string {
  const result = entry.cleared ? 'cleared' : entry.died ? 'died' : 'stopped'
  return `${rulesRecordingName(entry).toLowerCase()} · ${result}`
}

/** The line over the end frame: "Cleared the corridor: 43 decisions, 6 kills". */
export function rulesEndLine(meta: RuleTreeEpisodeMeta): string {
  const { result } = meta
  const kills = killWords(result.kills)
  if (result.cleared) return `Cleared ${placeWords(meta.scenario)}: ${result.decisions} decisions, ${kills}`
  if (result.died) return `Died after ${result.decisions} decisions, ${kills}`
  return `Stopped after ${result.decisions} decisions (${result.outcome}), ${kills}`
}

export const RULES_WATCH = {
  title: 'Every action in this game comes from Jev’s answers to a few questions.',
  subtitle:
    'Jev is TypeSafe’s decision model. At each decision the program asks it which rule of a tree of rules is true now, then which rule under that one, until Jev answers “none of these” or the rule has nothing under it. The game waits while Jev answers, then plays that rule’s action for 8 tics, about a quarter of a second.',
  stripTitle: 'The questions at this decision',
  stripNote:
    'One row per question, in the order Jev was asked, and then the action that was played. The bar is Jev’s probability for the answer it gave. A focus row picks the one item, such as the most dangerous enemy, that the rules after it speak about. Click a question to see exactly what Jev was sent.',
  rowTitle: 'Open this question at this decision',
  ruleQuestion: (node: string) =>
    node === 'root' ? 'Which of these is true right now?' : `Under ${node}: which of these is true right now?`,
  only: 'Not asked: it was the only one listed.',
  noItem: 'nothing listed',
  missed: 'missed',
  cached: 'same question as before',
  skill: (skill: string, caller: string) =>
    `${caller}’s action uses the ${skill} skill: the walk continues in the skill’s rules, which turn toward the focus.`,
  act: 'Act',
  actGloss: 'held for the 8 tics of this decision, about a quarter of a second',
  calls: (calls: number, ms: number, cost: number) =>
    `${calls} Jev ${calls === 1 ? 'call' : 'calls'}, ${Math.round(ms)} ms one after another, $${cost.toFixed(5)}`,
  honesty: (meta: RuleTreeEpisodeMeta) =>
    `This is a recording, one image per decision. Real time shows each decision for its 8 tics of game time, about a quarter of a second. While it was played, the game waited for Jev’s answers, ${(meta.seconds / Math.max(1, meta.decision_count)).toFixed(2)} s per decision on average.`,
  honestyLink: 'How this recording was made →',
  cardsTitle: 'The recordings',
  cardsNote:
    'Each recording is one game of the deadly corridor, played with one tree on one seed. Click a recording to play it from the start.',
  frameAlt: (index: number, count: number, health: number, action: string) =>
    `The game at decision ${index + 1} of ${count}, health ${Math.round(health)}. Jev’s answers led to: ${action}.`,
}

/**
 * Short words for the root's rules, for the timeline's legend, by their condition; a rule not listed is named by
 * its id. The full condition shows on hover.
 */
export const TOP_RULE_WORDS: Record<string, string> = {
  'The threats list shows at least one enemy.': 'an enemy in view',
  'The threats list says no enemy is visible.': 'no enemy in view',
}

export const TIMELINE = {
  none: 'none true: random code',
  missed: 'the first call missed',
  legend: [
    { kind: 'damage', label: 'damage' },
    { kind: 'kill', label: 'kill' },
    { kind: 'death', label: 'death' },
    { kind: 'miss', label: 'missed call' },
  ] as const,
}

/** Where the action came from: the rule the walk ended at, and the rule whose skill call it completed. */
export function actSource(node: string, skill: { caller: string; skill: string } | null, missed: boolean): string {
  if (missed) return `A call missed, so the walk stopped at ${node} and played its action`
  if (node === 'root') return 'None of the top rules was true: the root’s random action code'
  if (!skill) return `The action of ${node}`
  if (node === skill.skill)
    return `No rule of the ${skill.skill} skill was true: ${skill.caller}’s action, without a turn`
  return `${node}, a rule of the ${skill.skill} skill, turns toward the focus; then ${skill.caller}’s action fills the rest of the decision`
}

export const QUESTIONS = {
  title: (decision: number) => `Decision ${decision}: what Jev was asked, and what it answered`,
  intro:
    'At this decision Jev answered the questions below, one after another. Each was sent with the state of the game as text and the screen as an image. Pick a question to read the text exactly as Jev received it, and every probability it returned.',
  tabs: 'Questions at this decision',
  tab: (n: number) => `Question ${n}`,
  focusTab: 'focus',
  frame: 'The screen sent with this question',
  text: 'The state text, exactly as sent',
  focusNote:
    'The [focus] channel at the end was added by the focus question before this one. It names the item Jev picked there.',
  noFocusNote: 'This question picks the focus, so it was sent the state without a [focus] channel.',
  question: 'The question',
  options: 'Its options, with Jev’s probabilities',
  picked: 'its answer',
  onlyOne: 'Only one item was listed, so no question was asked: that item became the focus.',
  noneListed: 'Nothing was listed, so no question was asked and there is no focus.',
  miss: 'This call missed',
  missNote:
    'The walk stopped here, and the action of the rule it had reached was played. Nothing replaces a missing answer.',
  cached:
    'Jev had answered this exact question, with the same text and screen, earlier in this game. That answer was used again and no call was made.',
  timing: (ms: number, cost: number) => `answered in ${Math.round(ms)} ms · $${cost.toFixed(6)}`,
  leadsTo: 'Where the answer led',
}

export const WRITTEN = {
  title: 'How the rules were written',
  intro:
    'The soft loop is the part of the program that adds rules to a tree between games. This is its record for this tree: the tree it started from, each pass over the training seeds, and every rule it proposed, with what became of it.',
  none: 'This tree has no record of how it was written.',
  list: 'The record, step by step',
  pick: 'Pick a step to read it.',
  start: (tree: string) => `Started from ${tree}`,
  startNote: (tree: string, writer: string | null) =>
    `The soft loop started from the tree ${tree}, whose rules were written before the loop ran${writer ? `. ${writerName(writer)} was the rule writer` : ''}. Every step below changed the tree, or tried to.`,
  pass: (n: number | null, again = false) =>
    `${n === null ? 'Pass over the training seeds' : `Pass ${n} over the training seeds`}${again ? ', played again' : ''}`,
  heldOut: 'Held-out seeds',
  cleared: (cleared: number, of: number) => `${cleared} of ${of} cleared`,
  representation: 'The state text changed',
  representationNote:
    'A change to what Jev is shown, made by hand by the people running the soft loop, because a failure could not be told apart in the state text. It changes no rule.',
  proposal: (name: string) => `Proposal ${name}`,
  outcome: {
    added: 'added',
    'rejected by the check': 'rejected by the check',
    'rejected by the gate': 'rejected by the gate',
    'check stopped': 'the check stopped',
    'not checked': 'not checked',
  },
  addedAs: (rule: string, under: string | null) =>
    `Added as ${rule.replaceAll('+', ' and ')}${under ? `, under ${under}` : ''}.`,
  writtenFor: (game: string | null, frame: number | null, seed: number | null) =>
    `Written for decision ${frame ?? '?'} of the game ${game ?? 'unknown'}${seed === null ? '' : ` (seed ${seed})`}.`,
  under: (node: string) => `To be attached under ${node}.`,
  condition: 'Condition',
  action: 'Action',
  why: 'The writer’s reason',
  group: 'A group of rules, proposed together',
  check: 'The check',
  checkPassed: 'passed',
  checkFailed: 'failed',
  checkError: (error: string) =>
    `This check did not finish when the soft loop ran it: ${error.replace(/^the check stopped: /, '')}. The rule was neither added nor rejected. This happened while the tree was being written; it is part of the record, not a problem with this page.`,
  checkNoTests: 'The record keeps the check’s result, not its three tests.',
  tests: {
    sees: 'Reaches the rule: at the decision it was written for, the walk now goes into the new rule',
    unchanged:
      'Earlier rules unchanged: the decisions earlier rules were written for still reach them, or end no worse',
    avoids: 'Ends better: replayed from that decision, the game ends better with the rule than without it',
  },
  standing: (s: number[]) =>
    `${s[0] ? 'alive' : 'dead'}, ${s[1] ? 'goal reached' : 'goal not reached'}, health ${s[2]}, furthest point ${s[3]}`,
  without: 'Without the rule',
  with: 'With the rule',
  gate: 'The gate',
  gateBoth: (current: number, withRule: number, of: number) =>
    `The current tree cleared ${current} of ${of} training seeds; the tree with the rule cleared ${withRule}.`,
  gateCurrent: (current: number, of: number) =>
    `In its gate games the current tree cleared ${current} of ${of} training seeds. This step comes from the notes of an earlier run of the soft loop, which kept the current tree’s result but not the result with the rule.`,
  gatePassed: 'The gate passed.',
  gateFailed: 'The gate failed: the tree with the rule cleared fewer seeds.',
  note: 'Note',
  writerError: (error: string) => `The writer’s answer could not be read: ${error}`,
  games: 'The games',
  gameColumns: ['Seed', 'Game', 'Ended', 'Decisions', 'Furthest point', 'Health'],
  failures: 'The games that did not clear',
  stop: 'The loop stopped',
  seeds: (seeds: string) => `seeds ${seeds.replace('-', ' to ')}`,
  ruleLink: (id: string) => `Show ${id} in the tree →`,
  dossier:
    'The writer was shown a dossier: the decisions before the failure, each with its state text, the questions Jev answered and the screen. The dossier is not in this recording. The state and screen of the decision a rule was written for are kept with the rule, on The rule tree.',
}

export const RESULTS = {
  title: 'Results: how well the tree plays',
  intro:
    'How many games the tree cleared as its rules were added, on the seeds it was written from and on seeds it had not seen, and which of its rules the walks of this recording reached.',
  passColumns: ['Step', 'Seeds', 'Cleared'],
  training: 'training',
  heldOut: 'held out',
  seedRange: (low: number, high: number) => (low === high ? `${low}` : `${low} to ${high}`),
  benchmarkSource:
    'From the benchmark of 2026-10-27 (docs/DOCUMENTATION.md, section 15), not from this recording. Every answer was Jev’s, model jev-1.14.0.',
  benchmarkColumns: ['Seeds', 'This tree', 'Senses and central'],
  usesColumns: ['Rule', 'Condition', 'Walk went into it', 'Walk ended here'],
  usesTotal: (n: number) => `${n} decisions in this recording`,
  root: 'The top of the tree. When none of its rules is true, a random action code is played.',
  skill: (id: string) =>
    `The ${id} skill. When none of its rules is true, the walk ends here, and the action of the rule that used the skill is played without a turn.`,
  totals: 'This recording',
  totalsRows: (meta: RuleTreeEpisodeMeta) => [
    [
      'Result',
      `${meta.result.outcome}, ${meta.result.decisions} decisions, ${meta.result.kills} kills, health ${meta.result.health}`,
    ],
    ['Jev calls', `${meta.calls}, about ${(meta.calls / Math.max(1, meta.decision_count)).toFixed(1)} per decision`],
    ['Cost', `$${meta.cost.toFixed(4)}`],
    ['Misses', String(meta.misses)],
    [
      'Time to play',
      `${meta.seconds} s, about ${(meta.seconds / Math.max(1, meta.decision_count)).toFixed(2)} s per decision`,
    ],
  ],
}

/**
 * The benchmark: each tree on the same seeds, played twice; only the trees that have recordings here are shown. The
 * numbers are docs/DOCUMENTATION.md section 15's.
 */
export const BENCHMARK: Record<string, Array<{ seeds: string; tree: string; senses: string | null }>> = {
  'general-11': [
    { seeds: '201 to 215', tree: '15 and 14 of 15', senses: '10 and 11 of 15' },
    { seeds: '301 to 315', tree: '14 and 14 of 15', senses: '10 and 11 of 15' },
    { seeds: '9 to 19 (training)', tree: '11 and 11 of 11', senses: null },
    { seeds: '20 to 39 (held out)', tree: '19 and 20 of 20', senses: null },
    { seeds: '40 to 59 (held out, new)', tree: '18 and 20 of 20', senses: null },
    { seeds: 'all', tree: '77 and 79 of 81', senses: null },
  ],
  'codex-11': [
    { seeds: '201 to 215', tree: '15 and 14 of 15', senses: '10 and 11 of 15' },
    { seeds: '301 to 315', tree: '15 and 15 of 15', senses: '10 and 11 of 15' },
    { seeds: '9 to 19 (training)', tree: '11 and 11 of 11', senses: null },
    { seeds: '20 to 39 (held out)', tree: '18 and 18 of 20', senses: null },
    { seeds: '40 to 59 (held out, new)', tree: '19 and 19 of 20', senses: null },
    { seeds: 'all', tree: '78 and 77 of 81', senses: null },
  ],
}

export const TREE = {
  title: 'The rule tree',
  intro:
    'Every rule of the tree. A rule under another rule is an exception to it: when both are true, the lower rule’s action is played. Click a rule to see where it came from.',
  root: 'The start of every walk',
  rootAction: 'If none of its rules is true: a random action code.',
  skillTitle: (id: string) => `The ${id} skill`,
  skillNote: (id: string) =>
    `A rule whose action uses the ${id} skill continues the walk here. If none of these is true, the action that rule asks for is played.`,
  focus: 'First asks',
  focusFrom: (channels: string[]) => `from the ${channels.join(' and ')} list${channels.length === 1 ? '' : 's'}`,
  then: 'Action',
  onRoute: 'on this decision’s walk',
  ended: 'played at this decision',
  detailNone: 'Click a rule to see where it came from.',
  condition: 'Condition',
  action: 'Action',
  parent: 'An exception to',
  partOf: 'Part of',
  children: 'Exceptions to it',
  writer: 'Written by',
  why: 'Why',
  start: (tree: string | null, writer: string | null) =>
    `This rule was already in the tree the soft loop started from${tree ? ` (${tree})` : ''}${writer ? `, which ${writerName(writer)} wrote before the loop ran` : ''}. No proposal, check or gate added it.`,
  cornerstone: 'The decision it was written for',
  cornerstoneNote: (seed: number, decision: number, expect: string) =>
    `Seed ${seed}, decision ${decision}. The check makes sure every later rule leaves this decision on the route ${expect}, or ends the game no worse.`,
  cornerstoneText: 'The state text at that decision',
  record: 'Its record',
  recordLink: 'Read the whole step in How the rules were written →',
  uses: (reached: number, ended: number, n: number) =>
    `In this recording the walk went into it at ${reached} of ${n} decisions, and ended there at ${ended}.`,
}

export const RULES_REFERENCE = {
  title: 'Reference: how it works, the terms, and how this recording was made',
  rule: 'Every decision here is made by Jev.',
  ruleNote:
    'No code written by hand chooses an action. Jev judges every condition, and the action played is the action of the rule that Jev’s answers lead to. The program walks the tree: it writes the state as text, asks Jev each question the tree defines, follows the answer and presses the keys.',
  principles: [
    {
      title: 'Every condition is judged by Jev',
      text: 'The program never tests a condition itself. A condition such as “The focus channel says the enemy is more than 400 units away” is an option of a question, and Jev’s answer decides whether the walk goes there.',
    },
    {
      title: 'The program describes, walks and presses keys',
      text: 'It writes the state as text from the game, asks the questions of the tree in order, follows Jev’s answers, and holds the action’s keys for 8 tics. It ranks and picks nothing. The one exception: when no rule at the top of the tree is true, it plays a random action code, drawn from the seed and the decision number. In the recordings here that never happened.',
    },
    {
      title: 'A missed call is not replaced',
      text: 'When a call fails, the walk stops at the rule it has reached, and that rule’s action is played. The program does not answer in Jev’s place.',
    },
    {
      title: 'Rules describe the player’s own situation',
      text: 'A condition says what the state shows about the focus (its angle, distance and size on screen), health, damage taken, shots that missed, or the goal. It does not name a monster type, an item or a place on the map.',
    },
    {
      title: 'A rule is added only after a check and a gate',
      text: 'A rule writer proposes each rule for one moment where a game went wrong. The program checks it by replaying that game, then plays every training seed with and without it. It adds the rule only if the replay ends better with it and the tree with it clears at least as many training seeds as the tree without it. The program grades the games; it never tells Jev what to answer.',
    },
    {
      title: 'What is recorded',
      text: 'Every question Jev was asked is recorded, with its options, the probabilities, the answer, the time and the cost. So is each step of the soft loop, though the steps taken from an earlier run’s notes keep only their results. These screens show those records.',
    },
  ],
  provenance: {
    scenario: 'Scenario',
    decider: 'Decided by',
    tree: 'Tree',
    writer: 'Rules written by',
    seed: 'Seed',
    models: 'Model',
    budget: 'Time limit per call',
    decisionLength: 'Decision length',
    calls: 'Calls',
    misses: 'Misses',
    result: 'Result',
    recorded: 'Recorded',
    command: 'To record one like it:',
    play: 'To play the tree without recording:',
  },
  keys: [
    ['1 to 6', 'switch screens, in the order of the tabs'],
    ['← →', 'previous or next decision (with Shift, ten at a time)'],
    ['Home, End', 'first or last decision'],
    ['space', 'play or pause'],
  ] as Array<[string, string]>,
}

/** How many rules a recording's tree has, as its meta says. */
export const ruleCount = (bundle: Pick<RulesBundle, 'meta'>): number => bundle.meta.rules
