// The guided tour: six coach marks over one real tick, one per beat, then the hierarchy.
// Every sentence is built from the featured tick's own numbers.
import type { EpisodeMeta, TickTrace } from '../schema/bundle'
import {
  AIM_BAND_DEG,
  MODULES,
  choiceWords,
  d1Arbiter,
  d1Modules,
  d1Sync,
  explainPick,
  fmt,
  learning,
  moduleOpinions,
  motorSteps,
  pct,
  prettyId,
  prunedReasonText,
  rankedActions,
  signed,
} from '../data/derive'
import type { PanelId } from './explainers'

export type Invariant = 'finite menu' | 'bounded time' | 'advisory learning'

export const INVARIANTS: Record<Invariant, string> = {
  'finite menu': 'Finite menu: every level chooses from a short list it cannot extend.',
  'bounded time':
    'Bounded time: every step has a hard limit, and nothing waits for a slow part unless a recording asks it to wait for d1-ultra.',
  'advisory learning': 'Advisory learning: the networks re-weigh the options; they never add one or skip a level.',
}

export interface TourContext {
  tick: TickTrace
  meta: EpisodeMeta
}

export interface TourStep {
  /** The beat this step shows; the last step has none. */
  beat?: number
  title: string
  /** Panels the spotlight surrounds, on the inspector. The last step spotlights the tower instead. */
  panels: PanelId[]
  invariants: Invariant[]
  text: (ctx: TourContext) => string[]
}

function freeze({ tick }: TourContext): string[] {
  const state = tick.state
  if (!state) return [`At tick ${tick.tick} the controller takes a snapshot of the game.`]
  const enemies = [...(state.enemies ?? [])].sort((a, b) => Math.abs(a.angle_offset) - Math.abs(b.angle_offset))
  const nearest = enemies[0]
  const aim = nearest
    ? `The ${nearest.name} is ${fmt(nearest.distance, 0)} units away and ${fmt(Math.abs(nearest.angle_offset), 1)}° ${nearest.angle_offset >= 0 ? 'left' : 'right'} of the crosshair, ${Math.abs(nearest.angle_offset) <= AIM_BAND_DEG ? `inside the ±${AIM_BAND_DEG}° aim band` : `outside the ±${AIM_BAND_DEG}° aim band`}.`
    : 'No enemy is in view.'
  return [
    `At tick ${tick.tick}, ${enemies.length} ${enemies.length === 1 ? 'enemy is' : 'enemies are'} in view, with health ${fmt(state.health, 0)} and ${state.ammo} rounds. ${aim}`,
    'The controller freezes this snapshot: all five modules and the arbiter read exactly these numbers, and nothing else, for the whole tick.',
  ]
}

function menu({ tick, meta }: TourContext): string[] {
  const pruned = Object.entries(tick.pruned_actions ?? {})
  const vocabulary = tick.available_actions.length + pruned.length
  const example = pruned.find(([, reason]) => reason !== 'unsupported_by_scenario') ?? pruned[0]
  return [
    `The controller knows ${vocabulary} actions; ${tick.available_actions.length} pass their preconditions here and light up.`,
    example
      ? `${prettyId(example[0])} is out, for example: it ${prunedReasonText(example[1], meta.actions[example[0]], tick.state)}. Nothing outside the lit set can be chosen this tick.`
      : 'Every action passes this tick. Nothing outside this set can be chosen.',
  ]
}

function opinions({ tick, meta }: TourContext): string[] {
  const list = moduleOpinions(tick)
  const agree = list.filter((o) => o.agrees).length
  const named = list
    .slice()
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 2)
    .map((o) => `${o.module} puts ${prettyId(o.top ?? '–')} first at ${pct(o.topProbability)}`)
  const budget = (tick.budget_sec ?? meta.config.tick_budget_sec) * 1000
  const ran = tick.timing_ms?.modules
  const lambda = learning(tick).network_share ?? 0
  const advised = d1Modules(tick).length
  const waited = d1Sync(meta) && advised > 0
  return [
    `Five modules score the same ${tick.available_actions.length} options, each for its own question: ${named.join('; ')}. ${agree} of ${list.length} agree with what the arbiter will pick.`,
    `${ran !== undefined ? `They ran in ${fmt(ran, 1)} ms against a deadline of ${fmt(0.65 * budget, 0)} ms, 65% of the tick${waited ? ", most of it spent waiting for d1-ultra's answer" : ''}. ` : ''}${
      meta.brains.learned_networks
        ? `The hatched part of each bar is the networks' share, ${pct(lambda)} here: trust they earned by trying these actions in this kind of situation.`
        : 'No networks are loaded, so every bar is the hand-written heuristic.'
    }${advised > 0 ? ` The dotted part is d1-ultra's advice, mixed into ${advised === list.length ? 'every module' : advised === 1 ? 'one of the modules' : `${advised} of the modules`}.` : ''}`,
  ]
}

function decision({ tick, meta }: TourContext): string[] {
  const scores = tick.arbiter?.action_scores ?? {}
  const ranked = rankedActions(tick)
  const runnerUp = ranked.find((a) => a !== tick.selected_action)
  const pick = explainPick(tick)
  const g = tick.arbiter?.gate_share ?? 0
  return [
    `The arbiter adds the weighted opinions, a fifth of the simulator's expected value and a few small bonuses: ${prettyId(tick.selected_action)} scores ${fmt(scores[tick.selected_action] ?? 0, 2)}${runnerUp ? ` against ${fmt(scores[runnerUp] ?? 0, 2)} for ${prettyId(runnerUp)}` : ''}. ${pick.headline}`,
    (meta.brains.learned_networks
      ? `The gate network set ${pct(g)} of the weights given to the five modules; the hand-written table set the rest.`
      : 'The weights given to the five modules come from the hand-written table alone.') + d1Advice(tick),
  ]
}

/** d1-ultra's bonus in the arbiter's score, when it answered the arbiter's question. */
function d1Advice(tick: TickTrace): string {
  const d1 = d1Arbiter(tick)
  const top = d1?.ranked[0]
  if (!d1 || !top) return ''
  return top.action === tick.selected_action
    ? ` d1-ultra favoured the same action at ${pct(top.p)}, adding ${fmt(top.bonus, 2)} to its score.`
    : ` d1-ultra favoured ${prettyId(top.action)} at ${pct(top.p)}, adding ${fmt(top.bonus, 2)} to its score; the pick was ${choiceWords(d1.pickRank)}.`
}

function act({ tick, meta }: TourContext): string[] {
  const plan = meta.actions[tick.selected_action]?.primitives ?? []
  const steps = motorSteps(plan, tick.primitive_steps_executed)
  const assisted = steps.filter((s) => s.assisted)
  return [
    `${prettyId(tick.selected_action)} is a plan of ${plan.length} primitive${plan.length === 1 ? '' : 's'}: ${plan.map(prettyId).join(' → ')}. The motor pressed it in ${steps.length} steps of 2 frames, about a quarter of a second, then the next tick began.`,
    assisted.length > 0
      ? `${assisted.length} step${assisted.length === 1 ? '' : 's'} used a reflex: step ${(assisted[0]?.index ?? 0) + 1} ${assisted[0]?.words}. Reflexes only aim; they never change the plan.`
      : 'No reflex was needed: every key pressed was named by the plan.',
  ]
}

function remember({ tick }: TourContext): string[] {
  const o = tick.outcome
  if (!o) return ['This trace has no outcome detail.']
  const rewards = o.module_rewards ?? {}
  const nonzero = MODULES.filter((m) => Math.abs(rewards[m] ?? 0) >= 0.005).map(
    (m) => `${m} ${signed(rewards[m] ?? 0, 2)}`,
  )
  const events = [
    (o.kills_delta ?? 0) > 0 ? `${o.kills_delta === 1 ? 'a kill' : `${o.kills_delta} kills`}` : '',
    `reward ${signed(o.reward ?? 0, 2)}`,
    `${fmt(o.damage_taken ?? 0, 0)} damage taken`,
  ].filter(Boolean)
  return [
    `What came back: ${events.join(', ')}. Split into five rewards, one per module: ${nonzero.length > 0 ? nonzero.join(', ') : 'all zero'}.`,
    "It is filed into the simulator's cache of real outcomes, the active strategy's record and the exploration counters. During training it would also go to the replay buffer the networks learn from between episodes.",
  ]
}

export const TOUR: TourStep[] = [
  { beat: 1, title: 'Freeze the world', panels: ['game', 'world'], invariants: [], text: freeze },
  { beat: 2, title: 'Shorten the menu', panels: ['legal'], invariants: ['finite menu'], text: menu },
  {
    beat: 3,
    title: 'Five opinions',
    panels: ['modules'],
    invariants: ['bounded time', 'advisory learning'],
    text: opinions,
  },
  {
    beat: 4,
    title: 'One decision',
    panels: ['arbiter'],
    invariants: ['finite menu', 'advisory learning'],
    text: decision,
  },
  { beat: 5, title: 'Act', panels: ['motor'], invariants: ['bounded time'], text: act },
  { beat: 6, title: 'See and remember', panels: ['outcome'], invariants: ['advisory learning'], text: remember },
  {
    title: 'Every level is the same shape',
    panels: [],
    invariants: [],
    text: () => [
      'Every level you just saw is the same kind of decision: a short menu, a score for each option, one rule that picks, and a bound it cannot exceed.',
      'Two slower levels sit on top: the gate that can add a macro to the menu, and steering, which picks the strategy whose actions get a bonus. Neither can reach past the menu below it.',
    ],
  },
]
