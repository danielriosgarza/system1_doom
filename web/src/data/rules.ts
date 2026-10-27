// The rule tree's recordings: what Jev was asked at each decision, the tree it walked, and how the tree was
// written. Nothing here decides anything; it reads what `python -m system1_doom.export --solution rule-tree` wrote.
import type {
  BundleIndexEntry,
  RecordedAnswer,
  RuleNode,
  RuleTree,
  RuleTreeDecision,
  RuleTreeEpisodeMeta,
  SkillCall,
  WalkStep,
} from '../schema/bundle'
import {
  BundleError,
  type Fetcher,
  checkSchemaVersion,
  defaultEpisode,
  defaultFetcher,
  fetchText,
  parseJson,
  parseJsonl,
} from './loader'

/** One rule-tree recording, as the export command wrote it. */
export interface RulesBundle {
  name: string
  /** URL of the bundle folder, without a trailing slash. */
  base: string
  meta: RuleTreeEpisodeMeta
  decisions: RuleTreeDecision[]
  tree: RuleTree
  /** The soft loop's record of how the tree was written, one line per step; empty when the tree has none. */
  build: BuildLine[]
}

/** One line of `build.jsonl`. Its fields depend on the step; `readBuild` reads them. */
export type BuildLine = { step: string } & Record<string, unknown>

/** The tree played when none is named, as in ruletree/tree.py; the site opens its recordings first. */
export const DEFAULT_TREE = 'general-11'

/** The rule-tree recording opened when nothing names one: the default tree's newest cleared. */
export function defaultRulesEpisode(entries: BundleIndexEntry[]): string | null {
  const main = entries.filter((e) => e.tree === DEFAULT_TREE)
  return defaultEpisode({ episodes: main.length > 0 ? main : entries })
}

/** The node every walk starts at. */
export const ROOT = 'root'
/** The option every rule question ends with. */
export const NONE = 'none'
/** What a focus step adds to the state for the questions after it. */
export const FOCUS_HEAD = '\n\n[focus]\n'

export async function loadRulesEpisode(
  name: string,
  root = 'episodes',
  fetcher: Fetcher = defaultFetcher,
): Promise<RulesBundle> {
  const base = `${root}/${name}`
  const settled = await Promise.allSettled([
    fetchText(`${base}/episode.json`, fetcher),
    fetchText(`${base}/decisions.jsonl`, fetcher),
    fetchText(`${base}/tree.json`, fetcher),
    fetchText(`${base}/build.jsonl`, fetcher, true),
  ])
  const [metaText = '', decisionsText = '', treeText = '', buildText = ''] = settled.map((r) => {
    if (r.status === 'rejected') throw r.reason
    return r.value
  })
  const meta = parseJson<RuleTreeEpisodeMeta>(metaText, `${name}/episode.json`)
  checkSchemaVersion(meta.schema_version, `${name}/episode.json`)
  if (meta.solution !== 'rule-tree') throw new BundleError(`${name}/episode.json is not a rule-tree recording.`)
  const decisions = parseJsonl<RuleTreeDecision>(decisionsText, `${name}/decisions.jsonl`)
  if (decisions.length === 0) throw new BundleError(`${name}/decisions.jsonl has no decisions.`)
  if (decisions.length !== meta.decision_count) {
    throw new BundleError(
      `${name}/decisions.jsonl has ${decisions.length} decisions, but episode.json says ${meta.decision_count}.`,
    )
  }
  decisions.sort((a, b) => a.decision - b.decision)
  return {
    name,
    base,
    meta,
    decisions,
    tree: parseJson<RuleTree>(treeText, `${name}/tree.json`),
    build: parseJsonl<BuildLine>(buildText, `${name}/build.jsonl`),
  }
}

/** URL of a file the bundle names by its path inside the bundle: a frame, or a cornerstone's screen. */
export const rulesFileUrl = (bundle: Pick<RulesBundle, 'base'>, path: string): string => `${bundle.base}/${path}`

/** URL of the screen after the last action, or null when the bundle has none. */
export function rulesEndFrameUrl(bundle: Pick<RulesBundle, 'base' | 'meta'>): string | null {
  const end = bundle.meta.frames.end_frame
  return end ? rulesFileUrl(bundle, end) : null
}

// ---------------------------------------------------------------------------------------------
// The walk at one decision.

/**
 * The state text Jev was sent with question `index` of the decision, exactly as sent: the decision's state, and
 * after a focus step the `[focus]` channel that step added. A new focus replaces the one before it. A skill step
 * asks nothing, so it has no text (null).
 */
export function textSent(decision: Pick<RuleTreeDecision, 'state_text' | 'steps'>, index: number): string | null {
  let text = decision.state_text.split(FOCUS_HEAD)[0] ?? ''
  for (let i = 0; i <= index && i < decision.steps.length; i += 1) {
    const step = decision.steps[i] as WalkStep
    if (step.kind === 'skill') {
      if (i === index) return null
      continue
    }
    if (step.kind === 'focus') text = text.split(FOCUS_HEAD)[0] ?? ''
    if (i === index) return text
    if (step.kind === 'focus' && step.focus_line && !step.answer?.miss) text += FOCUS_HEAD + step.focus_line
  }
  return null
}

/** What one step of the walk came to, in the recording's own words. */
export interface StepReading {
  kind: WalkStep['kind']
  node: string
  /** The option it picked: a child rule's id or `none` for a rule question, `i0`, `i1`… for a focus question. */
  option: string | null
  /** The picked option's text: a condition, "None of these is true right now.", or a listed item. */
  text: string | null
  /** Jev's probability for the pick; null when no question was asked or the call missed. */
  p: number | null
  /** False for a focus with one item or none, which is taken without a question, and for a skill step. */
  asked: boolean
  /** The call failed: the walk stopped here. */
  miss: string | null
  /** Answered from an identical earlier question of this game, so no call was made. */
  cached: boolean
}

export function readStep(step: WalkStep): StepReading {
  const answer: RecordedAnswer | null = step.answer ?? null
  const asked = !!answer
  const miss = answer?.miss ?? null
  const options = step.options ?? {}
  let option: string | null = null
  if (step.kind === 'rule') option = step.pick ?? answer?.pick ?? null
  if (step.kind === 'focus') {
    option = answer?.pick ?? null
    if (!asked && step.pick) option = Object.keys(options).find((k) => options[k] === step.pick) ?? null
  }
  const text = step.kind === 'skill' ? null : option ? (options[option] ?? step.pick ?? null) : (step.pick ?? null)
  const p = option && answer?.probabilities ? (answer.probabilities[option] ?? null) : null
  return { kind: step.kind, node: step.node, option, text, p, asked, miss, cached: !!answer?.cached }
}

/** The steps that asked or could have asked Jev something: every rule and focus step, not the skill steps. */
export function questionIndexes(decision: Pick<RuleTreeDecision, 'steps'>): number[] {
  return decision.steps.flatMap((s, i) => (s.kind === 'skill' ? [] : [i]))
}

/** A question's options with Jev's probabilities, highest first; the pick is marked. */
export interface OptionBar {
  option: string
  text: string
  p: number
  picked: boolean
}

export function optionBars(step: WalkStep): OptionBar[] {
  const { option } = readStep(step)
  const probabilities = step.answer?.probabilities ?? {}
  return Object.entries(step.options ?? {})
    .map(([id, text]) => ({ option: id, text, p: probabilities[id] ?? 0, picked: id === option }))
    .sort((a, b) => b.p - a.p || a.option.localeCompare(b.option, undefined, { numeric: true }))
}

/** Every node the walk went into, the root first: what The rule tree highlights. */
export function routeNodes(decision: Pick<RuleTreeDecision, 'route' | 'node'>): string[] {
  const ids = decision.route.split('/').filter(Boolean)
  return [ROOT, ...ids.filter((id) => id !== ROOT), ...(ids.includes(decision.node) ? [] : [decision.node])]
}

/**
 * Which of the root's rules the decision went into: its id, `none` when Jev answered that none was true (the
 * root's random code), or `missed` when the first question missed.
 */
export function topRule(decision: Pick<RuleTreeDecision, 'steps'>): string {
  const first = decision.steps[0]
  if (!first || first.kind !== 'rule' || first.node !== ROOT) return NONE
  if (first.answer?.miss) return 'missed'
  return first.pick ?? NONE
}

/** The rule that used a skill in this walk, and the skill: the last skill step; null when no skill was used. */
export function skillOf(decision: Pick<RuleTreeDecision, 'steps'>): { caller: string; skill: string } | null {
  const step = [...decision.steps].reverse().find((s) => s.kind === 'skill')
  return step?.skill ? { caller: step.node, skill: step.skill } : null
}

// ---------------------------------------------------------------------------------------------
// The tree.

/** The rules of a tree: every node but the root and the skills' own entry nodes. */
export function ruleIds(tree: RuleTree): string[] {
  const skills = new Set(skillIds(tree))
  return Object.keys(tree.nodes).filter((id) => id !== ROOT && !skills.has(id))
}

/** The skills: nodes with no parent other than the root. */
export function skillIds(tree: RuleTree): string[] {
  return Object.values(tree.nodes)
    .filter((n) => n.parent === null && n.id !== ROOT)
    .map((n) => n.id)
}

/** The root, or the skill, a node belongs to. */
export function topOf(tree: RuleTree, id: string): string {
  let node = tree.nodes[id]
  while (node && node.parent !== null) node = tree.nodes[node.parent]
  return node?.id ?? id
}

const AXES: Array<Record<string, string>> = [
  { F: 'walk forward', B: 'walk backward' },
  { L: 'sidestep left', R: 'sidestep right' },
  { L: 'turn left', R: 'turn right' },
  { 1: 'fire' },
]

/** One action code in words: `F001` is "walk forward + fire", `0000` is "stand still". */
export function codeWords(code: string): string {
  const parts = [...code].map((c, i) => AXES[i]?.[c]).filter((w): w is string => !!w)
  return parts.length ? parts.join(' + ') : 'stand still'
}

export const isSkillCall = (action: RuleNode['action']): action is SkillCall => typeof action !== 'string'

/** A rule's action in words, as written in the tree: a code, a sequence, a skill call, or the root's random code. */
export function actionWords(action: RuleNode['action']): string {
  if (isSkillCall(action)) return `the ${action.skill} skill, then ${codeWords(action.then)}`
  if (action === 'random') return 'a random action code'
  if (action === 'then') return 'what the calling rule asks'
  const parts = action.split('+').map((part) => {
    const [code = '', tics] = part.split(':')
    return { code, tics: tics === undefined ? 8 : Number(tics) }
  })
  if (parts.length === 1 && parts[0]?.tics === 8) return codeWords(parts[0].code)
  const text = parts.map((p) => `${codeWords(p.code)} for ${p.tics} ${p.tics === 1 ? 'tic' : 'tics'}`).join(', then ')
  return parts.reduce((sum, p) => sum + p.tics, 0) === 8 ? text : `${text}, then what the calling rule asks`
}

// ---------------------------------------------------------------------------------------------
// The recording as a whole.

export type RulesMarkKind = 'damage' | 'kill' | 'death' | 'miss'

/** What happened at each decision that the timeline marks. */
export function decisionMarks(decisions: RuleTreeDecision[]): RulesMarkKind[][] {
  let kills = 0
  return decisions.map((d) => {
    const out: RulesMarkKind[] = []
    if (d.health_after < d.health_before) out.push('damage')
    if (d.kills !== null && d.kills !== undefined) {
      if (d.kills > kills) out.push('kill')
      kills = d.kills
    }
    if (d.died) out.push('death')
    if (d.missed || d.steps.some((s) => s.answer?.miss)) out.push('miss')
    return out
  })
}

/** For each rule: how many decisions went into it, and at how many the walk ended there and played its action. */
export interface RuleUse {
  id: string
  reached: number
  ended: number
}

export function ruleUses(bundle: Pick<RulesBundle, 'tree' | 'decisions'>): RuleUse[] {
  const ids = [ROOT, ...ruleIds(bundle.tree), ...skillIds(bundle.tree)]
  const uses = new Map(ids.map((id) => [id, { id, reached: 0, ended: 0 }]))
  for (const d of bundle.decisions) {
    for (const id of new Set(routeNodes(d))) {
      const use = uses.get(id)
      if (use) use.reached += 1
    }
    const end = uses.get(d.node)
    if (end) end.ended += 1
  }
  return [...uses.values()]
}

// ---------------------------------------------------------------------------------------------
// How the tree was written: `build.jsonl`, read into the entries of How the rules were written.

export interface BuildGame {
  seed: number
  game: string | null
  /** cleared, died, stalled, timed out. */
  event: string
  decisions: number | null
  maxX: number | null
  health: number | null
}

/** A proposed rule, or one member of a proposed group, as the writer wrote it. */
export interface ProposedRule {
  condition: string
  action: RuleNode['action']
  under: string | number | null
}

export interface ProposalBody {
  /** The game it was written from, and the decision of that game. */
  trace: string | null
  frame: number | null
  /** The node the writer asked to attach it to. */
  under: string | null
  rules: ProposedRule[]
  why: string | null
}

/** The check's three tests and the standing it compared, where the record has them. */
export interface CheckView {
  passed: boolean | null
  error: string | null
  rule: string | null
  attachTo: string | null
  sees: boolean | null
  unchanged: boolean | null
  avoids: boolean | null
  /** (alive, cleared, health, furthest point) at the end of the replay, without and with the rule. */
  oldTree: number[] | null
  newTree: number[] | null
}

export interface GateView {
  passed: boolean | null
  /** Training seeds cleared by the current tree, and by the tree with the rule, of `of`. */
  current: number | null
  withRule: number | null
  of: number | null
  note: string | null
  games: BuildGame[]
}

export type ProposalOutcome =
  'added' | 'rejected by the check' | 'rejected by the gate' | 'check stopped' | 'not checked'

export type BuildEntry =
  | { kind: 'start'; tree: string; writer: string | null }
  | {
      kind: 'pass'
      label: string | null
      round: number | null
      /** An earlier pass of the record has the same round: the round was played again. */
      again: boolean
      cleared: number
      of: number
      games: BuildGame[]
      failures: string[]
    }
  | {
      kind: 'held-out'
      label: string | null
      cleared: number
      of: number
      seeds: string | null
      games: BuildGame[]
      failures: string[]
    }
  | { kind: 'representation'; change: string; why: string | null }
  | {
      kind: 'proposal'
      name: string
      writer: string | null
      seconds: number | null
      proposal: ProposalBody | null
      /** The writer's answer could not be read. */
      error: string | null
      check: CheckView | null
      gate: GateView | null
      /** The rule ids it was added as, and under which node. */
      added: { rule: string; attachTo: string | null } | null
      outcome: ProposalOutcome
      note: string | null
    }
  | { kind: 'stop'; reason: string }

const str = (x: unknown): string | null => (typeof x === 'string' ? x : null)
const num = (x: unknown): number | null => (typeof x === 'number' ? x : null)
const bool = (x: unknown): boolean | null => (typeof x === 'boolean' ? x : null)
const nums = (x: unknown): number[] | null =>
  Array.isArray(x) && x.every((v) => typeof v === 'number') ? (x as number[]) : null

function readGames(x: unknown): BuildGame[] {
  if (!Array.isArray(x)) return []
  return x.map((raw) => {
    const g = (raw ?? {}) as Record<string, unknown>
    return {
      seed: num(g.seed) ?? 0,
      game: str(g.game),
      event: str(g.event) ?? 'none',
      decisions: num(g.decisions),
      maxX: num(g.max_x),
      health: num(g.health),
    }
  })
}

function readProposal(x: unknown): ProposalBody | null {
  if (!x || typeof x !== 'object') return null
  const p = x as Record<string, unknown>
  const group = Array.isArray(p.group) ? (p.group as Array<Record<string, unknown>>) : null
  const rules: ProposedRule[] = group
    ? group.map((r) => ({
        condition: str(r.condition) ?? '',
        action: r.action as RuleNode['action'],
        under: typeof r.under === 'number' || typeof r.under === 'string' ? r.under : null,
      }))
    : p.condition
      ? [{ condition: str(p.condition) ?? '', action: p.action as RuleNode['action'], under: null }]
      : []
  return { trace: str(p.trace), frame: num(p.frame), under: str(p.under), rules, why: str(p.why) }
}

const NO_CHECK: CheckView = {
  passed: null,
  error: null,
  rule: null,
  attachTo: null,
  sees: null,
  unchanged: null,
  avoids: null,
  oldTree: null,
  newTree: null,
}

/** The check of a proposal: a line of its own, or (in records converted from the first soft loop) inside it. */
function readCheck(line: Record<string, unknown>): CheckView {
  const test = (x: unknown) =>
    bool(x) ?? (x && typeof x === 'object' ? bool((x as Record<string, unknown>).pass) : null)
  return {
    passed: bool(line.passed) ?? bool(line.pass),
    error: str(line.error),
    rule: str(line.rule),
    attachTo: str(line.attach_to),
    sees: test(line.sees),
    unchanged: test(line.unchanged),
    avoids: test(line.avoids),
    oldTree: nums(line.old_tree),
    newTree: nums(line.new_tree),
  }
}

/**
 * The record as entries: each proposal gathers its check, its gate and its commit, which follow it under the same
 * name; every other line is an entry of its own. The record of a converted run says some outcomes in words, and
 * then they are taken as written.
 */
export function readBuild(lines: BuildLine[]): BuildEntry[] {
  const entries: BuildEntry[] = []
  const proposals = new Map<string, Extract<BuildEntry, { kind: 'proposal' }>>()
  for (const line of lines) {
    const name = str(line.name)
    const open = name ? proposals.get(name) : undefined
    switch (line.step) {
      case 'start':
        entries.push({ kind: 'start', tree: str(line.tree) ?? '', writer: str(line.writer) })
        break
      case 'pass':
      case 'held-out': {
        const common = {
          label: str(line.label),
          cleared: num(line.cleared) ?? 0,
          of: num(line.of) ?? 0,
          games: readGames(line.games),
          failures: Array.isArray(line.failures) ? line.failures.filter((f): f is string => typeof f === 'string') : [],
        }
        if (line.step === 'pass') {
          const round = num(line.round)
          const again = round !== null && entries.some((e) => e.kind === 'pass' && e.round === round)
          entries.push({ kind: 'pass', round, again, ...common })
        } else entries.push({ kind: 'held-out', seeds: str(line.seeds), ...common })
        break
      }
      case 'representation':
        entries.push({ kind: 'representation', change: str(line.change) ?? '', why: str(line.why) })
        break
      case 'proposal':
      case 'needs_representation': {
        const embedded =
          line.check && typeof line.check === 'object' ? readCheck(line.check as Record<string, unknown>) : null
        const outcome = str(line.outcome)
        const entry: Extract<BuildEntry, { kind: 'proposal' }> = {
          kind: 'proposal',
          name: name ?? '',
          writer: str(line.writer),
          seconds: num(line.seconds),
          proposal: readProposal(line.proposal),
          error: str(line.error),
          check: embedded,
          gate: null,
          added: null,
          outcome:
            outcome === 'rejected by the check'
              ? 'rejected by the check'
              : outcome?.endsWith('rejected by the gate')
                ? 'rejected by the gate'
                : 'not checked',
          note: str(line.note),
        }
        if (embedded && embedded.passed === null && embedded.avoids === false)
          entry.check = { ...embedded, passed: false }
        if (!embedded && outcome?.startsWith('passed its check')) entry.check = { ...NO_CHECK, passed: true }
        if (name) proposals.set(name, entry)
        entries.push(entry)
        break
      }
      case 'check':
        if (open) {
          open.check = readCheck(line)
          // A check that stopped (an API error) rejected nothing: the record says why it stopped.
          if (open.check.error) open.outcome = 'check stopped'
          else if (open.check.passed === false) open.outcome = 'rejected by the check'
        }
        break
      case 'gate':
        if (open) {
          const passed = bool(line.passed) ?? bool(line.pass)
          const note = str(line.note)
          open.gate = {
            passed: passed ?? (note?.includes('the gate passed') ? true : null),
            current: num(line.current) ?? num(line.cleared),
            withRule: num(line.with_rule),
            of: num(line.of),
            note,
            games: readGames(line.games),
          }
          if (open.gate.passed === false) open.outcome = 'rejected by the gate'
        }
        break
      case 'commit':
        if (open) {
          open.added = { rule: str(line.rule) ?? '', attachTo: str(line.attach_to) ?? open.check?.attachTo ?? null }
          open.outcome = 'added'
          if (open.check && !open.check.oldTree)
            open.check = { ...open.check, oldTree: nums(line.old_tree), newTree: nums(line.new_tree) }
        }
        break
      case 'stop':
        entries.push({ kind: 'stop', reason: str(line.reason) ?? '' })
        break
      default:
        break
    }
  }
  return entries
}

/** The rule ids a commit added: `r11`, or `r11+r12` for a group. */
export const addedIds = (rule: string): string[] => rule.split('+').filter(Boolean)

/** The proposal that added a rule, from the record of how the tree was written; null for the starting rules. */
export function proposalOf(entries: BuildEntry[], id: string): Extract<BuildEntry, { kind: 'proposal' }> | null {
  for (const e of entries) if (e.kind === 'proposal' && e.added && addedIds(e.added.rule).includes(id)) return e
  return null
}

/** The seed a game name like `trace-s14-01` was played on, or null for another name. */
export function seedOfGame(game: string | null): number | null {
  const m = /^trace-s(\d+)-/.exec(game ?? '')
  return m ? Number(m[1]) : null
}
