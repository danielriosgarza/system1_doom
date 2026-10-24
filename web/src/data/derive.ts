// Pure readings of a tick trace that more than one panel needs. Every number here is either
// copied from the trace or recomputed with the controller's own constants, named below.
import type { ActionInfo, EpisodeMeta, ProposalTrace, StateTrace, TickTrace } from '../schema/bundle'

export const MODULES = ['survival', 'combat', 'navigation', 'resource', 'goal'] as const
export type ModuleName = (typeof MODULES)[number]

/** Motor constants (motor.py): 4 steps per decision, each held for 2 game frames; Doom runs at 35 frames per second. */
export const STEPS_PER_DECISION = 4
export const FRAMES_PER_STEP = 2
export const DOOM_FPS = 35
/** The combat module counts an enemy as aimed within this angle (modules.py, CombatModule). */
export const AIM_BAND_DEG = 12
/** Angle at the screen edge in the observation's angle estimate (vizdoom_env.py). */
export const HALF_FOV_DEG = 45
/** The navigation module treats a wall closer than this as blocking (modules.py, NavigationModule). */
export const NEAR_WALL = 64
/** Trust count in λ = n / (n + 25) (learning.py, LearnerConfig.trust_count). */
export const TRUST_COUNT = 25
/** Module softmax temperature (modules.py, _softmax). */
export const MODULE_TEMPERATURE = 0.35

export interface ExplorationView {
  recent_progress?: number
  recent_failures?: number
  state_visitation_novelty?: number
  uncertainty_estimates?: number
  performance_plateau_signal?: boolean
  exploration_pressure?: number
  temperature?: number
  terms?: Record<string, number>
}

export interface LearningView {
  network_share?: number
  gate_share?: number
  module_weights?: Record<string, number>
  explored?: boolean
  exploration_floor?: number
}

export const exploration = (tick: TickTrace): ExplorationView => tick.exploration_state as ExplorationView
export const learning = (tick: TickTrace): LearningView => (tick.learning ?? {}) as LearningView

export function gameSeconds(tick: number): number {
  return (tick * STEPS_PER_DECISION * FRAMES_PER_STEP) / DOOM_FPS
}

/** Half-width of the ±12° aim band in screen pixels, inverting angle = (centre − x) / centre × 45°. */
export function aimBandHalfWidth(screenWidth: number): number {
  return (AIM_BAND_DEG / HALF_FOV_DEG) * (screenWidth / 2)
}

// ---------------------------------------------------------------------------------------------
// Context signature: five buckets, thresholds from WorldState.context_signature (state.py).

export type BucketKey = 'hp' | 'ammo' | 'enemies' | 'dmg' | 'pickup'

export interface BucketOption {
  value: string
  rule: string
}

export interface ContextBucket {
  key: BucketKey
  label: string
  value: string
  options: BucketOption[]
  /** Why this bucket has its value, in words with this tick's number. */
  because: string
}

const BUCKET_OPTIONS: Record<BucketKey, { label: string; options: BucketOption[] }> = {
  hp: {
    label: 'Health',
    options: [
      { value: 'critical', rule: '30 or less' },
      { value: 'medium', rule: '31 to 65' },
      { value: 'healthy', rule: 'above 65' },
    ],
  },
  ammo: {
    label: 'Ammo',
    options: [
      { value: 'empty', rule: 'none' },
      { value: 'low', rule: '1 to 8' },
      { value: 'stocked', rule: 'above 8' },
    ],
  },
  enemies: {
    label: 'Nearest enemy',
    options: [
      { value: 'none', rule: 'none visible' },
      { value: 'melee', rule: 'under 140 units' },
      { value: 'mid', rule: '140 to 420' },
      { value: 'far', rule: '420 or more' },
    ],
  },
  dmg: {
    label: 'Incoming fire',
    options: [
      { value: 'clear', rule: 'no recent damage' },
      { value: 'under_fire', rule: 'took damage recently' },
    ],
  },
  pickup: {
    label: 'Pickups',
    options: [
      { value: 'no_pickup', rule: 'none visible' },
      { value: 'pickup_visible', rule: 'one or more visible' },
    ],
  },
}

export function parseSignature(signature: string): Partial<Record<BucketKey, string>> & { enemyCount?: number } {
  const out: Partial<Record<BucketKey, string>> & { enemyCount?: number } = {}
  for (const part of signature.split('|')) {
    const [key, ...rest] = part.split(':')
    if (key === 'enemies' && rest.length === 2) {
      out.enemyCount = Number(rest[0])
      out.enemies = rest[1]
    } else if (key && key in BUCKET_OPTIONS) {
      out[key as BucketKey] = rest.join(':')
    }
  }
  return out
}

export function contextBuckets(signature: string, state?: StateTrace | null): ContextBucket[] {
  const parsed = parseSignature(signature)
  const nearest = state?.enemies?.length ? Math.min(...state.enemies.map((e) => e.distance)) : null
  const because: Record<BucketKey, string> = {
    hp: state ? `health ${fmt(state.health, 0)}` : '',
    ammo: state ? `${state.ammo} rounds` : '',
    enemies:
      nearest === null
        ? 'no enemy in view'
        : `${parsed.enemyCount ?? state?.enemies?.length} in view, nearest ${fmt(nearest, 0)} units away`,
    dmg: state ? `recent damage ${fmt(state.recent_incoming_damage ?? 0, 0)}` : '',
    pickup: state ? `${state.pickups?.length ?? 0} in view` : '',
  }
  return (Object.keys(BUCKET_OPTIONS) as BucketKey[]).map((key) => ({
    key,
    label: BUCKET_OPTIONS[key].label,
    options: BUCKET_OPTIONS[key].options,
    value: parsed[key] ?? '?',
    because: because[key],
  }))
}

// ---------------------------------------------------------------------------------------------
// Pruning: why an action is not on this tick's menu (PreconditionSpec.failing_condition, actions.py).

export function prunedReasonText(reason: string, action: ActionInfo | undefined, state?: StateTrace | null): string {
  const pre = (action?.preconditions ?? {}) as Record<string, unknown>
  const num = (key: string) => (typeof pre[key] === 'number' ? (pre[key] as number) : undefined)
  switch (reason) {
    case 'min_ammo':
      return `needs at least ${num('min_ammo')} ammo${state ? ` (has ${state.ammo})` : ''}`
    case 'max_ammo':
      return num('max_ammo') === 0
        ? `only when out of ammo${state ? ` (has ${state.ammo})` : ''}`
        : `only with ${num('max_ammo')} ammo or less${state ? ` (has ${state.ammo})` : ''}`
    case 'min_health':
      return `needs health of at least ${num('min_health')}${state ? ` (now ${fmt(state.health, 0)})` : ''}`
    case 'max_health':
      return `only when health is ${num('max_health')} or less${state ? ` (now ${fmt(state.health, 0)})` : ''}`
    case 'requires_visible_enemy':
      return 'needs a visible enemy'
    case 'requires_visible_pickup':
      return 'needs a visible pickup'
    case 'min_wall_distance_front':
      return `needs ${num('min_wall_distance_front')} units of room ahead${state ? ` (wall at ${fmt(state.walls.front ?? 0, 0)})` : ''}`
    case 'max_wall_distance_front':
      return `only with a wall within ${num('max_wall_distance_front')} units ahead${state ? ` (nearest ${fmt(state.walls.front ?? 0, 0)})` : ''}`
    case 'excluded_weapons':
      return `not while holding the ${state?.weapon ?? 'current weapon'}`
    case 'unsupported_by_scenario':
      return 'this scenario has no button for it'
    default:
      return 'not offered this tick'
  }
}

// ---------------------------------------------------------------------------------------------
// The slow path: proposals and which tick they joined the menu.

export interface Admission {
  actionId: string | null
  tick: number | null
  module: string | null
  admitted: boolean
  source: string | null
  proposal: ProposalTrace
}

export function admissions(proposals: ProposalTrace[]): Admission[] {
  return proposals.map((p) => ({
    actionId: p.admitted_action_id ?? null,
    tick: p.tick ?? null,
    module: p.source_module ?? null,
    admitted: p.admission_decision,
    source: p.source ?? null,
    proposal: p,
  }))
}

// ---------------------------------------------------------------------------------------------
// Events marked on the scrubber.

export type TickEventKind =
  'damage' | 'kill' | 'sampled' | 'committed' | 'expansion' | 'admission' | 'strategy' | 'death'

export interface TickEvent {
  kind: TickEventKind
  label: string
}

export function tickEvents(tick: TickTrace, admitted: Admission[]): TickEvent[] {
  const events: TickEvent[] = []
  const outcome = tick.outcome
  const rule = tick.arbiter?.pick_rule
  if (outcome?.died) events.push({ kind: 'death', label: 'the player died' })
  if ((outcome?.damage_taken ?? 0) > 0)
    events.push({ kind: 'damage', label: `took ${fmt(outcome?.damage_taken ?? 0, 0)} damage` })
  if ((outcome?.kills_delta ?? 0) > 0) {
    const n = outcome?.kills_delta ?? 0
    events.push({ kind: 'kill', label: `killed ${n === 1 ? 'an enemy' : `${n} enemies`}` })
  }
  if (rule === 'sampled' || rule === 'explored') {
    events.push({ kind: 'sampled', label: `${rule} ${prettyId(tick.selected_action)} instead of taking the top score` })
  }
  if (rule === 'committed') {
    events.push({
      kind: 'committed',
      label: `${tick.arbiter?.committed_by ?? 'a module'} committed the arbiter to ${prettyId(tick.selected_action)}`,
    })
  }
  if (tick.slow_path_request) {
    events.push({ kind: 'expansion', label: `${tick.slow_path_request.module} asked the slow path for a new macro` })
  }
  for (const a of admitted) {
    if (a.tick !== tick.tick) continue
    events.push({
      kind: 'admission',
      label: a.admitted
        ? `admitted ${prettyId(a.actionId ?? 'a macro')} into the menu`
        : 'rejected a proposed macro at the gate',
    })
  }
  const steering = tick.steering
  if (steering && steering.active_before && steering.active_before !== steering.active_after) {
    events.push({
      kind: 'strategy',
      label: `strategy ${prettyId(steering.active_before)} → ${prettyId(steering.active_after)}`,
    })
  }
  return events
}

// ---------------------------------------------------------------------------------------------
// Motor: each executed step in words (TacticalMotor.burst and _assisted_flags, motor.py).

export interface MotorStep {
  index: number
  planned: string | null
  pressed: string[]
  words: string
  assisted: boolean
}

export function holdFor(planLength: number): number {
  return Math.max(1, Math.floor(STEPS_PER_DECISION / Math.max(1, planLength)))
}

function side(primitive: string): string {
  return primitive.includes('left') ? 'left' : 'right'
}

export function describeStep(planned: string | null, pressed: string[]): { words: string; assisted: boolean } {
  const has = (p: string) => pressed.includes(p)
  const turn = has('turn_left') ? 'left' : has('turn_right') ? 'right' : null
  const strafe = has('strafe_left') ? 'left' : has('strafe_right') ? 'right' : null
  if (pressed.length === 0 || (pressed.length === 1 && pressed[0] === 'idle')) {
    return { words: 'pressed nothing: the episode had ended', assisted: false }
  }
  switch (planned) {
    case 'shoot':
      if (has('shoot')) return { words: 'fired at the locked target', assisted: false }
      if (turn) return { words: `turned ${turn} to centre the target before firing`, assisted: true }
      if (strafe) return { words: `strafed ${strafe} to line up the target before firing`, assisted: true }
      break
    case 'strafe_left_shoot':
    case 'strafe_right_shoot':
      if (has('shoot')) return { words: `strafed ${side(planned)} and fired: the target was centred`, assisted: false }
      if (turn) {
        return {
          words: `strafed ${side(planned)} while turning ${turn} onto the target, holding fire until it is centred`,
          assisted: true,
        }
      }
      break
    case 'strafe_left':
    case 'strafe_right':
      if (turn) return { words: `strafed ${side(planned)} while turning ${turn} to track the target`, assisted: true }
      return { words: `strafed ${side(planned)}`, assisted: false }
    case 'move_forward':
      if (turn) return { words: `moved forward, steering ${turn} toward the pickup`, assisted: true }
      return { words: 'moved forward', assisted: false }
    case 'move_backward':
      return { words: 'backed up', assisted: false }
    case 'turn_left':
    case 'turn_right':
      return { words: `turned ${side(planned)}`, assisted: false }
    case 'use':
      return { words: 'pressed use (doors and switches)', assisted: false }
  }
  return { words: pressed.map((p) => p.replaceAll('_', ' ')).join(' + '), assisted: false }
}

export function motorSteps(plan: string[], executed: string[]): MotorStep[] {
  const hold = holdFor(plan.length)
  return executed.map((step, index) => {
    const planned = plan[Math.floor(index / hold)] ?? null
    const pressed = step.split('+')
    return { index, planned, pressed, ...describeStep(planned, pressed) }
  })
}

// ---------------------------------------------------------------------------------------------
// Arbiter readings.

/** Legal actions, best arbiter score first: the one row order every panel shares. */
export function rankedActions(tick: TickTrace): string[] {
  const scores = tick.arbiter?.action_scores ?? {}
  const fallback = tick.arbiter_distribution
  return [...tick.available_actions].sort(
    (a, b) => (scores[b] ?? fallback[b] ?? 0) - (scores[a] ?? fallback[a] ?? 0) || a.localeCompare(b),
  )
}

export interface VotePart {
  module: ModuleName
  weight: number
  probability: number
  value: number
}

/** The module-votes term of an action's score, split by module: weight × that module's probability. */
export function moduleVoteParts(tick: TickTrace, actionId: string): VotePart[] {
  const weights = tick.arbiter?.module_weights ?? {}
  return MODULES.filter((m) => tick.module_outputs[m]).map((module) => {
    const weight = weights[module] ?? 0
    const probability = tick.module_outputs[module]?.probabilities?.[actionId] ?? 0
    return { module, weight, probability, value: weight * probability }
  })
}

export interface PickExplanation {
  headline: string
  detail: string
}

/** The arbiter's pick rules in one line each, as the hierarchy's decision card states them. */
export const PICK_RULES: Record<string, string> = {
  greedy: 'greedy: the top score wins, since the race was not close or pressure was low',
  sampled: 'sampled: the top two were within 0.08 and pressure was at least 0.45, so it drew from the softmax',
  committed: 'committed: a module nearly certain of one action overrides the comparison',
  explored: 'explored: the exploration floor forced a random draw',
  critical_cached: 'out of time: the cached action is repeated',
}

/** Why the greedy rule held this tick: a clear lead, or a close race with too little pressure to sample. */
function greedyWhy(arbiter: NonNullable<TickTrace['arbiter']>): string {
  const margin = arbiter.score_margin ?? 0
  const pressure = arbiter.exploration_pressure ?? 0
  if (arbiter.deterministic) return 'the arbiter runs deterministically in this recording'
  if (margin >= 0.08) return `it led by ${fmt(margin, 2)}, at least the 0.08 needed to skip sampling`
  return `the top two were only ${fmt(margin, 3)} apart, but exploration pressure was low (${fmt(pressure, 2)}, under 0.45)`
}

export function explainPick(tick: TickTrace): PickExplanation {
  const arbiter = tick.arbiter
  const selected = prettyId(tick.selected_action)
  if (!arbiter) return { headline: `Picked ${selected}.`, detail: 'This trace has no arbiter detail.' }
  const ranked = rankedActions(tick)
  const runnerUp = ranked.find((a) => a !== tick.selected_action)
  const scores = arbiter.action_scores ?? {}
  const pressure = arbiter.exploration_pressure ?? 0
  const margin = arbiter.score_margin ?? 0
  const prob = tick.arbiter_distribution[tick.selected_action] ?? 0
  switch (arbiter.pick_rule) {
    case 'committed':
      return {
        headline: `The ${arbiter.committed_by} module committed the arbiter to ${selected}.`,
        detail:
          `It was nearly certain: probability at least 0.9, utility at least 5 and at least 4 ahead of its next option. ` +
          `A module that sure overrides the score comparison; this is how an admitted macro gets reused.`,
      }
    case 'explored':
      return {
        headline: `Explored: drew ${selected} at random.`,
        detail: `The exploration floor (${fmt(arbiter.exploration_floor ?? 0, 2)}) forced a random draw this tick, at temperature ${fmt(Math.max(0.5, arbiter.temperature ?? 0), 2)}.`,
      }
    case 'sampled':
      return {
        headline: `Sampled ${selected}, which had a ${pct(prob)} chance.`,
        detail:
          `The top two scores were close (margin ${fmt(margin, 3)}, under 0.08) and exploration pressure was high ` +
          `(${fmt(pressure, 2)}, at least 0.45), so the arbiter drew from the softmax of the scores at temperature ${fmt(arbiter.temperature ?? 0, 2)}.`,
      }
    case 'critical_cached':
      return {
        headline: `Out of time: reused the cached action ${selected}.`,
        detail: 'The tick budget was too short to score the menu, so the last good action was repeated.',
      }
    default: {
      const why = greedyWhy(arbiter)
      return {
        headline: `Took the top score: ${selected}.`,
        detail:
          runnerUp !== undefined
            ? `It scored ${fmt(scores[tick.selected_action] ?? 0, 2)} against ${fmt(scores[runnerUp] ?? 0, 2)} for ${prettyId(runnerUp)}; greedy because ${why}.`
            : `It was the only legal action.`,
      }
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Module expansion triggers (check_expansion_needed in modules.py), shown next to each module's memory.

export interface ExpansionTrigger {
  rule: string
  counter: string | null
  threshold: number | null
}

export const EXPANSION_TRIGGERS: Record<ModuleName, ExpansionTrigger> = {
  survival: {
    rule: 'damage on 4 ticks in a row, or health under 35 with 15+ recent damage',
    counter: 'consecutive_damage_ticks',
    threshold: 4,
  },
  combat: {
    rule: '3 failures in a row, or 4 damage ticks against 2+ enemies',
    counter: 'repeated_failures',
    threshold: 3,
  },
  navigation: { rule: 'stalled for 4 ticks in a row', counter: 'consecutive_stalls', threshold: 4 },
  resource: { rule: 'ammo 2 or less and health 35 or less with a pickup in view', counter: null, threshold: null },
  goal: { rule: 'no progress for 6 ticks', counter: 'plateau_ticks', threshold: 6 },
}

export const MEMORY_LABELS: Record<string, string> = {
  consecutive_damage_ticks: 'damage streak',
  repeated_failures: 'failures',
  consecutive_stalls: 'stalls',
  plateau_ticks: 'plateau',
}

// ---------------------------------------------------------------------------------------------
// Formatting.

export function fmt(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return '–'
  const fixed = value.toFixed(digits)
  return fixed === `-${(0).toFixed(digits)}` ? (0).toFixed(digits) : fixed
}

export function signed(value: number, digits = 2): string {
  const text = fmt(value, digits)
  return value > 0 && text !== fmt(0, digits) ? `+${text}` : text
}

export function pct(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`
}

export function prettyId(id: string): string {
  return id.replaceAll('_', ' ')
}

// ---------------------------------------------------------------------------------------------
// The guided tour's featured tick.

/** The first tick whose outcome records a kill while an enemy was in view; else the first with an enemy in view. */
export function featuredTickIndex(ticks: TickTrace[]): number {
  const enemyInView = (t: TickTrace) => (t.state?.enemies?.length ?? 0) > 0
  const kill = ticks.findIndex((t) => enemyInView(t) && (t.outcome?.kills_delta ?? 0) > 0)
  if (kill >= 0) return kill
  return Math.max(0, ticks.findIndex(enemyInView))
}

// ---------------------------------------------------------------------------------------------
// Exploration pressure (ExplorationController.update_and_decide, exploration.py) and how the
// arbiter uses it (FinalArbiter.arbitrate, arbiter.py).

/** Each quarter-term is at most 0.25 of the pressure. */
export const PRESSURE_TERMS = [
  { key: 'uncertainty', label: 'uncertainty', words: 'how unsure the modules were' },
  { key: 'failures', label: 'failures', words: 'recent failed steps, saturating at 4' },
  { key: 'plateau', label: 'plateau', words: 'stalled for 3 ticks or 3 failures' },
  { key: 'novelty', label: 'novelty', words: 'how new this situation is' },
] as const
export const DAMPERS = [
  { key: 'progress_damper', label: 'progress', factor: 0.55, words: 'steady progress' },
  { key: 'risk_damper', label: 'risk', factor: 0.35, words: 'health 30 or less, or heavy fire with an enemy in view' },
  { key: 'winning_damper', label: 'winning', factor: 0.25, words: 'a kill, or full armor, just now' },
] as const
export const PRESSURE_FLOOR = 0.02
/** Sampler temperature = 0.10 + pressure. */
export const BASE_TEMPERATURE = 0.1
/** The controller's state before the first outcome (ExplorationState defaults). */
export const INITIAL_PRESSURE = 0.25
export const INITIAL_TEMPERATURE = 0.35
/** The arbiter samples only when the top two scores are within this margin... */
export const SAMPLE_MARGIN = 0.08
/** ...and the pressure is at least this. */
export const SAMPLE_PRESSURE = 0.45

export interface PressureReading {
  /** No outcome yet: the controller's starting values, without terms. */
  initial: boolean
  terms: Array<{ key: string; label: string; words: string; value: number }>
  sum: number
  dampers: Array<{ key: string; label: string; words: string; factor: number; applied: boolean; value: number }>
  /** Sum × dampers, before any d1 blend and the clamp. */
  product: number
  /** d1-ultra's own pressure, blended half and half when it answered (sync mode only). */
  d1: number | null
  /** The recomputed pressure, clamped to [0.02, 1]. */
  pressure: number
  temperature: number
  /** exploration_pressure as the trace recorded it. */
  recorded: number
}

export function pressureReading(view: ExplorationView | null): PressureReading {
  if (!view?.terms) {
    return {
      initial: true,
      terms: [],
      sum: 0,
      dampers: [],
      product: INITIAL_PRESSURE,
      d1: null,
      pressure: view?.exploration_pressure ?? INITIAL_PRESSURE,
      temperature: view?.temperature ?? INITIAL_TEMPERATURE,
      recorded: view?.exploration_pressure ?? INITIAL_PRESSURE,
    }
  }
  const raw = view.terms
  const terms = PRESSURE_TERMS.map((t) => ({ ...t, value: raw[t.key] ?? 0 }))
  const dampers = DAMPERS.map((d) => {
    const value = raw[d.key] ?? 1
    return { ...d, value, applied: value < 1 }
  })
  const sum = terms.reduce((s, t) => s + t.value, 0)
  const product = dampers.reduce((p, d) => p * d.value, sum)
  const d1 = raw.d1_pressure ?? null
  const blended = d1 === null ? product : 0.5 * product + 0.5 * d1
  const pressure = Math.min(1, Math.max(PRESSURE_FLOOR, blended))
  return {
    initial: false,
    terms,
    sum,
    dampers,
    product,
    d1,
    pressure,
    temperature: BASE_TEMPERATURE + pressure,
    recorded: view.exploration_pressure ?? pressure,
  }
}

/**
 * The exploration state a tick's arbiter used. Pressure is updated after each action, so the arbiter
 * of tick t reads the state recorded at the end of tick t − 1; the first tick reads the starting values.
 */
export function pressureForArbiter(ticks: TickTrace[], index: number): ExplorationView | null {
  const previous = index > 0 ? ticks[index - 1] : undefined
  return previous ? exploration(previous) : null
}

// ---------------------------------------------------------------------------------------------
// The strategy archive (archive.py).

export const STRATEGY_BONUS = 0.15
export const ARCHIVE_SLOTS = 12
/** Running averages: new = (1 − α)·old + α·this outcome. */
export const ARCHIVE_ALPHA = 0.3
/** A step fails when it takes more than 8 damage or the player dies (controller.py). */
export const FAILED_STEP_DAMAGE = 8

export const STEERING_CHOICES = [
  { id: 'continue_current_strategy', label: 'continue current', formula: '1.2·success − 0.35·failures' },
  { id: 'switch_to_archived_strategy', label: 'switch to a stored one', formula: '0.4 + 0.25·failures + 0.3·pressure' },
  { id: 'explore_variation', label: 'explore a variation', formula: '0.3 + 0.7·pressure' },
  {
    id: 'request_new_strategy_proposal',
    label: 'ask for a new one',
    formula: '0.2 + 0.9·[failures ≥ 3] + 0.4·pressure',
  },
] as const

/** Strategy ids carry a `strat_` prefix that says nothing to a reader. */
export function strategyName(id: string): string {
  return prettyId(id.replace(/^strat_/, ''))
}

/** The eviction score: when the archive is full, the non-active entry with the lowest one goes. */
export function evictionScore(entry: { observed_reward: number; success_rate: number }): number {
  return entry.observed_reward + 5 * entry.success_rate
}

// ---------------------------------------------------------------------------------------------
// The slow path at one tick: what arrived at the gate, and what was asked.

export interface SlowPathAtTick {
  /** Proposals that reached the gate this tick. */
  arrived: ProposalTrace[]
  /** Macros admitted on earlier ticks (and this one), in order. */
  admittedSoFar: ProposalTrace[]
  request: TickTrace['slow_path_request']
}

export function slowPathAt(tick: TickTrace, proposals: ProposalTrace[]): SlowPathAtTick {
  return {
    arrived: proposals.filter((p) => p.tick === tick.tick),
    admittedSoFar: proposals.filter((p) => p.admission_decision && (p.tick ?? Infinity) <= tick.tick),
    request: tick.slow_path_request ?? null,
  }
}

export function proposalId(p: ProposalTrace): string {
  const parsed = p.parsed_proposal as { id?: unknown } | null | undefined
  return p.admitted_action_id ?? (typeof parsed?.id === 'string' ? parsed.id : 'unnamed proposal')
}

// ---------------------------------------------------------------------------------------------
// The hierarchy: six levels, slowest first, each read as the same decision.

export type LevelId = 'gate' | 'steering' | 'menu' | 'opinions' | 'arbiter' | 'motor'
export type LineStyle = 'solid' | 'hatched' | 'dotted'

export interface LevelChip {
  id: string
  label: string
  state: 'legal' | 'pruned' | 'chosen'
  note?: string
}

export interface Candidate {
  id: string
  label: string
  /** Bar length in [0, 1]. */
  share: number
  /** The number or word printed beside the bar. */
  value: string
  chosen: boolean
  style: LineStyle
  failed?: boolean
  note?: string
}

export interface TowerLevel {
  id: LevelId
  title: string
  bounds: string[]
  /** How many options this level chose from this tick. */
  menuSize: number
  menu: LevelChip[]
  candidates: Candidate[]
  /** The choice, as an id or a short code ('admitted', 'requested', 'none', the legal count). */
  choice: string
  choiceLabel: string
  /** How the choice was made, in one line. */
  rule: string
  reads: string
  writes: string
  /** Nothing happened at this level this tick. */
  idle: boolean
}

function stageValue(stage: { passed: boolean; skipped?: boolean }): string {
  return stage.skipped ? 'skipped' : stage.passed ? 'passed' : 'failed'
}

function gateLevel(tick: TickTrace, proposals: ProposalTrace[]): TowerLevel {
  const slow = slowPathAt(tick, proposals)
  const proposal = slow.arrived[0]
  const sofar = slow.admittedSoFar.map((p) => prettyId(proposalId(p)))
  const base = {
    id: 'gate' as const,
    title: 'Growing the menu',
    bounds: ['one proposal in flight', 'five stages'],
    reads: 'a proposed macro from the slow worker',
    writes: 'one more action in the vocabulary, and a strategy in the archive',
  }
  if (proposal) {
    const stages = proposal.stage_results ?? []
    const failed = stages.find((s) => !s.passed)
    const id = proposalId(proposal)
    return {
      ...base,
      menuSize: slow.arrived.length,
      menu: slow.arrived.map((p) => ({
        id: proposalId(p),
        label: prettyId(proposalId(p)),
        state: p.admission_decision ? 'chosen' : 'pruned',
        note: (p.parsed_proposal as { description?: string } | null)?.description,
      })),
      candidates: stages.map((s) => ({
        id: s.stage,
        label: s.stage,
        share: s.passed ? 1 : 0,
        value: stageValue(s),
        chosen: s.stage === 'admit' && s.passed,
        style: s.skipped ? 'dotted' : 'solid',
        failed: !s.passed,
        note: s.reason,
      })),
      choice: proposal.admission_decision ? 'admitted' : 'rejected',
      choiceLabel: proposal.admission_decision
        ? `admitted ${prettyId(id)}`
        : `rejected ${prettyId(id)}${failed ? ` at ${failed.stage}` : ''}`,
      rule: proposal.admission_decision
        ? `every stage passed${stages.some((s) => s.skipped) ? ' or was skipped' : ''}, so it joins the menu`
        : `the ${failed?.stage ?? 'first'} stage failed, so nothing changes`,
      idle: false,
    }
  }
  const chips: LevelChip[] = slow.admittedSoFar.map((p) => ({
    id: proposalId(p),
    label: `${prettyId(proposalId(p))} · t${p.tick ?? '?'}`,
    state: 'legal',
    note: 'admitted on an earlier tick',
  }))
  if (slow.request) {
    return {
      ...base,
      menuSize: 0,
      menu: chips,
      candidates: [],
      choice: 'requested',
      choiceLabel: `${slow.request.module} asked for a new macro`,
      rule: 'the slow worker is writing it; it reaches the gate on a later tick',
      idle: false,
    }
  }
  return {
    ...base,
    menuSize: 0,
    menu: chips,
    candidates: [],
    choice: 'none',
    choiceLabel: 'nothing proposed',
    rule:
      sofar.length > 0
        ? `${sofar.length} macro${sofar.length === 1 ? '' : 's'} admitted so far`
        : 'no macro has been proposed yet',
    idle: true,
  }
}

function steeringLevel(tick: TickTrace): TowerLevel {
  const s = tick.steering
  const probabilities = s?.probabilities ?? {}
  const scores = s?.scores ?? {}
  const switched = !!s?.active_before && s.active_before !== s.active_after
  return {
    id: 'steering',
    title: 'Steering',
    bounds: ['≤ 12 strategies'],
    menuSize: STEERING_CHOICES.length,
    menu: STEERING_CHOICES.map((c) => ({
      id: c.id,
      label: c.label,
      state: c.id === s?.choice ? 'chosen' : 'legal',
    })),
    candidates: STEERING_CHOICES.map((c) => ({
      id: c.id,
      label: c.label,
      share: probabilities[c.id] ?? 0,
      value: pct(probabilities[c.id] ?? 0),
      chosen: c.id === s?.choice,
      style: 'solid',
      note: `utility ${fmt(scores[c.id] ?? 0, 2)} = ${c.formula}`,
    })),
    choice: s?.choice ?? 'none',
    choiceLabel: s
      ? `${prettyId(s.choice)}${switched ? `: ${strategyName(s.active_before ?? '')} → ${strategyName(s.active_after)}` : `, ${strategyName(s.active_after)} stays`}`
      : 'not recorded',
    rule: 'the most probable choice wins; decided after the action, for the next tick',
    reads: "the active strategy's record, recent failures, exploration pressure",
    writes: `which strategy's actions get the +${STRATEGY_BONUS} bonus next tick`,
    idle: !s,
  }
}

function menuLevel(tick: TickTrace, meta: EpisodeMeta): TowerLevel {
  const legal = new Set(tick.available_actions)
  const pruned = tick.pruned_actions ?? {}
  const vocabulary = Object.keys(meta.actions).filter((id) => legal.has(id) || id in pruned)
  return {
    id: 'menu',
    title: 'The menu',
    bounds: ['≤ 16 primitives per macro'],
    menuSize: vocabulary.length,
    menu: vocabulary.map((id) => ({
      id,
      label: prettyId(id),
      state: legal.has(id) ? 'legal' : 'pruned',
      note:
        pruned[id] !== undefined ? prunedReasonText(pruned[id] ?? '', meta.actions[id], tick.state) : 'legal this tick',
    })),
    candidates: [],
    choice: String(legal.size),
    choiceLabel: `${legal.size} of ${vocabulary.length} legal`,
    rule: 'each action passes its preconditions or is pruned; nothing is scored here',
    reads: 'the frozen world state',
    writes: 'the legal set every level below chooses from',
    idle: false,
  }
}

export interface ModuleOpinion {
  module: ModuleName
  top: string | null
  topProbability: number
  confidence: number
  /** Share of the top bar set by the learned network (trust λ). */
  learned: number
  agrees: boolean
}

export function moduleOpinions(tick: TickTrace): ModuleOpinion[] {
  return MODULES.filter((m) => tick.module_outputs[m]).map((module) => {
    const out = tick.module_outputs[module]
    const top = out?.top_action ?? null
    return {
      module,
      top,
      topProbability: top ? (out?.probabilities?.[top] ?? 0) : 0,
      confidence: out?.confidence ?? 0,
      learned: top ? (out?.trust?.[top] ?? 0) : 0,
      agrees: top === tick.selected_action,
    }
  })
}

function opinionsLevel(tick: TickTrace): TowerLevel {
  const opinions = moduleOpinions(tick)
  const counts = new Map<string, number>()
  for (const o of opinions) if (o.top) counts.set(o.top, (counts.get(o.top) ?? 0) + 1)
  const [favourite, votes] = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0] ?? ['', 0]
  return {
    id: 'opinions',
    title: 'Five opinions',
    bounds: ['deadline 65% of tick'],
    menuSize: tick.available_actions.length,
    menu: tick.available_actions.map((id) => ({ id, label: prettyId(id), state: 'legal' })),
    candidates: opinions.map((o) => ({
      id: o.module,
      label: o.module,
      share: o.topProbability,
      value: `${prettyId(o.top ?? '–')} ${pct(o.topProbability)}`,
      chosen: o.agrees,
      style: o.learned > 0 ? 'hatched' : 'solid',
    })),
    choice: favourite,
    choiceLabel:
      opinions.length === 0
        ? 'no opinions: a cached decision'
        : `${votes} of ${opinions.length} put ${prettyId(favourite)} first`,
    rule: 'each module ranks the menu with its own softmax; none of them decides',
    reads: "the legal set, the world state, the simulator's projections, trust λ",
    writes: 'five probability lists for the arbiter',
    idle: opinions.length === 0,
  }
}

function arbiterLevel(tick: TickTrace, meta: EpisodeMeta): TowerLevel {
  const scores = tick.arbiter?.action_scores ?? {}
  const legal = new Set(tick.available_actions)
  const order = Object.keys(meta.actions).filter((id) => legal.has(id))
  const values = order.map((id) => scores[id] ?? 0)
  const lo = Math.min(0, ...values)
  const hi = Math.max(...values, lo + 1e-6)
  const rule = tick.arbiter?.pick_rule ?? 'greedy'
  // The greedy line names this tick's reason, as the inspector does; the other rules read the same every tick.
  const ruleLine =
    rule === 'greedy' && tick.arbiter
      ? `greedy: the top score wins, since ${greedyWhy(tick.arbiter)}`
      : (PICK_RULES[rule] ?? rule)
  return {
    id: 'arbiter',
    title: 'One decision',
    bounds: ['one pick from the menu'],
    menuSize: legal.size,
    menu: order.map((id) => ({ id, label: prettyId(id), state: id === tick.selected_action ? 'chosen' : 'legal' })),
    candidates: order.map((id) => ({
      id,
      label: prettyId(id),
      share: ((scores[id] ?? 0) - lo) / (hi - lo),
      value: fmt(scores[id] ?? 0, 2),
      chosen: id === tick.selected_action,
      style: 'solid',
      note: `chance ${pct(tick.arbiter_distribution[id] ?? 0)}`,
    })),
    choice: tick.selected_action,
    choiceLabel: prettyId(tick.selected_action),
    rule: ruleLine,
    reads: 'five opinions, simulator evidence, the strategy bonus, exploration pressure',
    writes: 'one action for the motor',
    idle: false,
  }
}

function motorLevel(tick: TickTrace, meta: EpisodeMeta): TowerLevel {
  const plan = meta.actions[tick.selected_action]?.primitives ?? []
  const steps = motorSteps(plan, tick.primitive_steps_executed)
  const reflexes = steps.filter((s) => s.assisted).length
  return {
    id: 'motor',
    title: 'Act',
    bounds: ['8 frames', 'fixed reflexes'],
    menuSize: plan.length,
    menu: plan.map((p, i) => ({ id: `${p}-${i}`, label: prettyId(p), state: 'legal' })),
    candidates: steps.map((s) => ({
      id: `step-${s.index}`,
      label: `step ${s.index + 1}`,
      share: 1,
      value: s.pressed.map(prettyId).join(' + '),
      chosen: true,
      style: 'solid',
      note: s.words,
    })),
    choice: tick.primitive_steps_executed.join(' | '),
    choiceLabel: `${steps.length} step${steps.length === 1 ? '' : 's'}, ${reflexes} with a reflex`,
    rule: `each primitive held for ${holdFor(plan.length)} step${holdFor(plan.length) === 1 ? '' : 's'}; reflexes only aim`,
    reads: 'the chosen plan and the locked target',
    writes: 'keys pressed in the game for 8 frames',
    idle: false,
  }
}

export function towerLevels(tick: TickTrace, meta: EpisodeMeta, proposals: ProposalTrace[]): TowerLevel[] {
  return [
    gateLevel(tick, proposals),
    steeringLevel(tick),
    menuLevel(tick, meta),
    opinionsLevel(tick),
    arbiterLevel(tick, meta),
    motorLevel(tick, meta),
  ]
}
