// Pure readings of a tick trace that more than one panel needs. Every number here is either
// copied from the trace or recomputed with the controller's own constants, named below.
import type { ActionInfo, ProposalTrace, StateTrace, TickTrace } from '../schema/bundle'

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
  | 'damage'
  | 'kill'
  | 'sampled'
  | 'committed'
  | 'expansion'
  | 'admission'
  | 'strategy'
  | 'death'

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
      const why = arbiter.deterministic
        ? 'the arbiter runs deterministically in this recording'
        : margin >= 0.08
          ? `it led by ${fmt(margin, 2)}, at least the 0.08 needed to skip sampling`
          : `exploration pressure was low (${fmt(pressure, 2)}, under 0.45)`
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
