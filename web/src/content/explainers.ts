// The copy for every panel's three-layer explainer: one sentence, a paragraph, and the formula
// with the current tick's numbers substituted. Constants are the controller's own (see derive.ts).
import type { EpisodeMeta, TickTrace } from '../schema/bundle'
import {
  AIM_BAND_DEG,
  MODULES,
  MODULE_TEMPERATURE,
  NEAR_WALL,
  TRUST_COUNT,
  aimBandHalfWidth,
  contextBuckets,
  exploration,
  fmt,
  gameSeconds,
  holdFor,
  moduleVoteParts,
  pct,
  rankedActions,
  signed,
} from '../data/derive'

/** A number inside arithmetic: negatives in parentheses with a true minus sign. */
function term(value: number, digits = 2): string {
  const text = fmt(Math.abs(value), digits)
  return value < 0 && text !== fmt(0, digits) ? `(−${text})` : text
}

export type PanelId =
  | 'scrubber'
  | 'game'
  | 'world'
  | 'legal'
  | 'projection'
  | 'modules'
  | 'arbiter'
  | 'motor'
  | 'outcome'

export interface FormulaLine {
  /** What the line computes, in words. */
  label: string
  /** The arithmetic with this tick's numbers. */
  expr: string
  /** The result, highlighted. */
  result?: string
}

export interface ExplainerContext {
  tick: TickTrace
  meta: EpisodeMeta
  /** The action the viewer is pointing at, or the selected one. */
  focus: string
}

export interface Explainer {
  title: string
  /** Where this level sits in the six-beat story of one tick; side inputs have none. */
  beat?: number
  sentence: string
  paragraphs: string[]
  /** The general formula, shown above the substituted lines. */
  formula?: string
  substitute?: (ctx: ExplainerContext) => FormulaLine[]
  code: string
}

export const BEATS = [
  { n: 1, name: 'Freeze the world', panel: 'game' },
  { n: 2, name: 'Shorten the menu', panel: 'legal' },
  { n: 3, name: 'Five opinions', panel: 'modules' },
  { n: 4, name: 'One decision', panel: 'arbiter' },
  { n: 5, name: 'Act', panel: 'motor' },
  { n: 6, name: 'See and remember', panel: 'outcome' },
] as const

export const STORY = {
  sentence:
    'Every tick this controller freezes the world, shortens a menu of actions, asks five small deciders for their opinion, lets one arbiter pick, executes the pick with fixed reflexes, and files what came back.',
  invariant:
    'Each level chooses from a short menu it cannot leave. Learning changes how the menus are weighed, never their shape.',
}

export const EXPLAINERS: Record<PanelId, Explainer> = {
  scrubber: {
    title: 'Timeline',
    sentence:
      'Each slot is one decision; the controller makes one every 8 game frames, about a quarter of a second of play.',
    paragraphs: [
      'Click or drag along the line, or use the arrow keys, to move through the episode. The line under the slots is health. Marks flag the moments worth stopping at: damage taken, a kill, a pick that was sampled rather than taken greedily, a module committing the arbiter, a module asking for a new macro, a macro admitted into the menu, and a change of strategy.',
      "Every panel above is a reading of the tick under the cursor, taken from the controller's own trace.",
    ],
    formula: 'game time = tick × 4 steps × 2 frames ÷ 35 frames per second',
    substitute: ({ tick }) => [
      { label: 'game time at this tick', expr: `${tick.tick} × 8 ÷ 35`, result: `${fmt(gameSeconds(tick.tick), 1)} s` },
    ],
    code: 'controller.py · DoomDecisionController.step',
  },
  game: {
    title: 'What the controller saw',
    beat: 1,
    sentence: 'The screen at the moment of decision, with the numbers the deciders read from it drawn on top.',
    paragraphs: [
      "The boxes are not computer vision on this picture. They come from the game engine's own object labels, recorded in the trace, so every box names the numbers the modules used. An enemy's angle is how far it sits from the crosshair; positive means to the left. Inside the shaded aim band, 12 degrees either side, the combat module counts the enemy as aimed and prefers to shoot; outside it, it prefers to turn.",
      'The three arcs at the bottom are wall distances read from the depth buffer, to the left, ahead and to the right. The dashed ring marks 64 units, where the navigation module treats a wall as blocking. The strip along the bottom is what the motor actually pressed after this decision.',
    ],
    formula: 'angle = (screen centre − box centre) ÷ screen centre × 45°',
    substitute: ({ tick }) => {
      const state = tick.state
      if (!state) return []
      const centre = (state.screen_width ?? 320) / 2
      const lines: FormulaLine[] = [
        {
          label: 'aim band half-width',
          expr: `${AIM_BAND_DEG}° ÷ 45° × ${centre} px`,
          result: `±${fmt(aimBandHalfWidth(state.screen_width ?? 320), 1)} px`,
        },
      ]
      const enemies = [...(state.enemies ?? [])].sort((a, b) => Math.abs(a.angle_offset) - Math.abs(b.angle_offset))
      const nearest = enemies[0]
      if (nearest) {
        lines.push({
          label: `${nearest.name}, closest to the crosshair`,
          expr: `(${centre} − ${nearest.screen_x}) ÷ ${centre} × 45°`,
          result: `${signed(nearest.angle_offset, 1)}°, ${Math.abs(nearest.angle_offset) <= AIM_BAND_DEG ? 'aimed' : 'not aimed'}`,
        })
      } else {
        lines.push({ label: 'enemies', expr: 'none visible', result: 'nothing to aim at' })
      }
      const front = state.walls.front ?? 0
      lines.push({
        label: 'wall ahead',
        expr: `${fmt(front, 0)} ${front > NEAR_WALL ? '>' : '≤'} ${NEAR_WALL}`,
        result: front > NEAR_WALL ? 'room to advance' : 'blocked: turn or use',
      })
      return lines
    },
    code: 'vizdoom_env.py · ViZDoomBridge.acquire_world_state',
  },
  world: {
    title: 'World state',
    beat: 1,
    sentence: 'A frozen snapshot of everything the deciders are allowed to know this tick.',
    paragraphs: [
      'Nothing in the snapshot changes while the tick is being decided, so all five modules and the arbiter reason about the same world.',
      "The five buckets compress it into a context signature, a coarse name for the kind of situation. That name is the key every memory is filed under: how often each action was tried here (which sets the networks' trust), how new the situation is (novelty), which stored strategy fits, and the simulator's cache of real outcomes.",
    ],
    formula: 'context = health bucket | ammo bucket | enemies:count:range | incoming fire | pickups',
    substitute: ({ tick }) =>
      contextBuckets(tick.context_signature, tick.state).map((b) => ({
        label: b.label.toLowerCase(),
        expr: `${b.because} → ${b.options.find((o) => o.value === b.value)?.rule ?? ''}`,
        result: b.value,
      })),
    code: 'state.py · WorldState.context_signature',
  },
  legal: {
    title: 'The menu',
    beat: 2,
    sentence:
      'The whole action vocabulary; only the lit chips are legal this tick, and the arbiter can only choose a lit chip.',
    paragraphs: [
      'Every action carries preconditions: shoot needs a visible enemy and ammo, approach pickup needs a visible pickup, use needs a wall within reach. Actions that fail one, or that this scenario has no button for, are pruned before anything scores them. Hover a dimmed chip to see which condition failed.',
      'Macros are fixed sequences of at most 16 primitives. Chips marked new were written by the slow path during this episode and admitted through its gate; they are scored like any other action from the moment they join. If nothing were legal, the controller would fall back to turning or moving forward.',
    ],
    formula: 'menu = { actions whose preconditions hold and whose buttons exist }',
    substitute: ({ tick }) => {
      const pruned = Object.keys(tick.pruned_actions ?? {}).length
      const legal = tick.available_actions.length
      return [
        {
          label: 'menu size',
          expr: `${legal + pruned} in the vocabulary − ${pruned} pruned`,
          result: `${legal} legal`,
        },
      ]
    },
    code: 'actions.py · ActionVocabulary.available_actions, PreconditionSpec',
  },
  projection: {
    title: 'Bounded simulator',
    sentence:
      'A hand-written guess of what each legal action would do over its next four steps, under an ordinary and a fiercer enemy.',
    paragraphs: [
      "The simulator is not a replay of the real game. It steps a simple model of damage, pickups and movement, at most four primitives deep, two branches wide and 15 milliseconds long. Its numbers are evidence, not a decision: the modules read them, and the arbiter adds a fifth of the expected value to each action's score.",
      'When the same action has already been tried in the same context, up to 50 real outcomes from an empirical cache are blended into the guess, 40% to 60%.',
    ],
    formula:
      'branch value = 0.12·dealt + 0.14·resources + 0.18·progress − k·taken ÷ steps − cost;  EV = mean of the branches',
    substitute: ({ tick, focus }) => {
      const chain = tick.projection_chain
      const summary = tick.projection_results_used[focus]
      const lines: FormulaLine[] = []
      if (chain && chain.action_id === focus) {
        const branches = chain.branch_values ?? []
        const guess = branches.reduce((a, b) => a + b, 0) / Math.max(1, branches.length)
        const ev = chain.expected_value ?? 0
        lines.push({
          label: `${focus}: guess, enemy aggression ×1.0 and ×1.35`,
          expr: `mean(${branches.map((v) => fmt(v, 2)).join(', ')})`,
          result: fmt(guess, 2),
        })
        if ((chain.empirical_samples ?? 0) > 0) {
          lines.push({
            label: `blended with ${chain.empirical_samples} real outcome${chain.empirical_samples === 1 ? '' : 's'}`,
            expr: `0.6 × ${term(guess)} + 0.4 × ${term((ev - 0.6 * guess) / 0.4)} (cache: 0.1·reward − 0.05·damage)`,
            result: fmt(ev, 2),
          })
        }
      } else if (summary) {
        lines.push({
          label: `${focus}: expected value`,
          expr: 'mean over 2 branches',
          result: fmt(summary.expected_value ?? 0, 2),
        })
      }
      if (summary) {
        lines.push({
          label: 'what the arbiter adds to its score',
          expr: `0.2 × ${fmt(summary.expected_value ?? 0, 2)}`,
          result: fmt(0.2 * (summary.expected_value ?? 0), 2),
        })
        lines.push({
          label: 'k, the damage weight',
          expr: `health ${fmt(tick.state?.health ?? 0, 0)} ${(tick.state?.health ?? 100) <= 40 ? '≤' : '>'} 40`,
          result: (tick.state?.health ?? 100) <= 40 ? '0.18' : '0.09',
        })
      }
      return lines
    },
    code: 'simulator.py · BoundedSimulator.project_action',
  },
  modules: {
    title: 'Five opinions',
    beat: 3,
    sentence:
      'Five small deciders each answer their own question about the same menu; a bar is how strongly one of them wants that action.',
    paragraphs: [
      'Every module scores each legal action with a hand-written heuristic, turns the scores into probabilities with a softmax, and reports how sure it is: a peaked distribution is confident, a flat one is not.',
      `When trained networks are loaded, a module's score for an action is blended with its network's learned value in proportion to trust, λ = n ÷ (n + ${TRUST_COUNT}), where n counts how often that action was tried in this kind of situation. The hatched part of a bar is the share the network has earned; the heuristic keeps the rest. With no networks every bar is solid.`,
      'A module whose own memory shows a concrete, repeated failure (for example damage on four ticks in a row) can ask the slow path for a new macro. That request never waits: the tick goes on.',
    ],
    formula: `u(a) = (1 − λ)·heuristic(a) + λ·learned(a);  p(a) = softmax(u ÷ ${MODULE_TEMPERATURE});  confidence = 1 − entropy(p) ÷ log(menu size)`,
    substitute: ({ tick, focus }) =>
      MODULES.flatMap((m) => {
        const out = tick.module_outputs[m]
        if (!out) return []
        const h = out.utility_heuristic?.[focus]
        const l = out.utility_learned?.[focus]
        const lambda = out.trust?.[focus]
        const u = out.utility_blended?.[focus]
        const p = out.probabilities?.[focus] ?? 0
        if (h === undefined || u === undefined) return [{ label: m, expr: 'no utility recorded', result: pct(p, 1) }]
        const expr =
          l === undefined || lambda === undefined
            ? `u = heuristic = ${fmt(h, 2)}`
            : `u = (1 − ${fmt(lambda, 2)})·${term(h)} + ${fmt(lambda, 2)}·${term(l)} = ${fmt(u, 2)}`
        return [{ label: `${m}, for ${focus}`, expr, result: `p ${pct(p, 1)}` }]
      }),
    code: 'modules.py · DecisionModule.build_output, BatchModuleEvaluator',
  },
  arbiter: {
    title: 'One decision',
    beat: 4,
    sentence:
      'One score per legal action, built from the five opinions plus evidence and small bonuses; then one rule picks.',
    paragraphs: [
      "The coloured part of each bar is the module votes: every module's probability for the action, weighted by how much the arbiter trusts that module right now. The weights start from a hand-written table (in a fight combat counts most, otherwise navigation) scaled by each module's confidence. A learned gate network proposes its own weights, and the two are blended by the gate's trust in this situation; the rings show both.",
      "Then come a fifth of the simulator's expected value, a bonus for actions in the active strategy, small exploration and novelty bonuses, minus a risk penalty for projected damage and the action's execution cost.",
      'Four rules pick. A module that is nearly certain commits the arbiter. Otherwise the top score wins, unless the top two are within 0.08 and exploration pressure is at least 0.45; then the arbiter samples from a softmax of the scores.',
    ],
    formula:
      'score(a) = Σₘ wₘ·pₘ(a) + 0.2·EV(a) + strategy + exploration + novelty − risk − cost;  w = (1 − g)·w_table + g·w_gate',
    substitute: ({ tick, focus }) => {
      const arbiter = tick.arbiter
      const parts = arbiter?.component_breakdown?.[focus]
      if (!arbiter || !parts) return []
      const votes = moduleVoteParts(tick, focus)
      const ranked = rankedActions(tick)
      const lines: FormulaLine[] = [
        {
          label: `module votes for ${focus}`,
          expr: votes.map((v) => `${fmt(v.weight, 2)}·${fmt(v.probability, 2)}`).join(' + '),
          result: fmt(parts.module_votes ?? 0, 3),
        },
        {
          label: 'score',
          expr:
            `${fmt(parts.module_votes ?? 0, 3)} + ${fmt(parts.projection_term ?? 0, 3)} + ${fmt(parts.strategy_bonus ?? 0, 2)}` +
            `${(parts.d1_bonus ?? 0) !== 0 ? ` + ${fmt(parts.d1_bonus ?? 0, 3)}` : ''}` +
            ` + ${fmt(parts.exploration_bonus ?? 0, 3)} + ${fmt(parts.novelty_bonus ?? 0, 3)} − ${fmt(parts.risk_penalty ?? 0, 3)} − ${fmt(parts.execution_cost ?? 0, 2)}`,
          result: fmt(parts.total_score ?? 0, 3),
        },
        {
          label: 'gate share g',
          expr: arbiter.module_weights_gate ? 'trust of the gate network in this context' : 'no gate network loaded',
          result: fmt(arbiter.gate_share ?? 0, 3),
        },
      ]
      const rule = arbiter.pick_rule ?? 'greedy'
      if (rule === 'greedy' || rule === 'sampled') {
        const margin = arbiter.score_margin ?? 0
        const pressure = arbiter.exploration_pressure ?? 0
        lines.push({
          label: 'pick rule',
          expr: `margin ${fmt(margin, 3)} ${margin >= 0.08 ? '≥' : '<'} 0.08, pressure ${fmt(pressure, 2)} ${pressure >= 0.45 ? '≥' : '<'} 0.45`,
          result: rule,
        })
      } else {
        lines.push({
          label: 'pick rule',
          expr: rule === 'committed' ? `${arbiter.committed_by} p ≥ 0.9, u ≥ 5, lead ≥ 4` : rule,
          result: rule,
        })
      }
      lines.push({
        label: `P(${focus}) in the softmax`,
        expr: `exp((s − s_max) ÷ ${fmt(arbiter.temperature ?? 0, 2)}) ÷ Σ, top is ${ranked[0]}`,
        result: pct(tick.arbiter_distribution[focus] ?? 0, 1),
      })
      return lines
    },
    code: 'arbiter.py · FinalArbiter.arbitrate',
  },
  motor: {
    title: 'Act',
    beat: 5,
    sentence: "The chosen action's plan, pressed step by step with small fixed reflexes.",
    paragraphs: [
      "The arbiter chose a plan, not a trajectory. The motor presses the plan's primitives for eight game frames in total. Each primitive keeps a reflex: before firing it turns to centre the locked target, while strafing it keeps turning to track it, and when walking toward a pickup it steers onto it.",
      'Reflexes never change the plan; they only fill in the aiming. A step marked with a reflex is one where the motor pressed something the plan did not name.',
    ],
    formula: 'frames held per primitive = 2 × max(1, ⌊4 ÷ plan length⌋)',
    substitute: ({ tick, meta }) => {
      const plan = meta.actions[tick.selected_action]?.primitives ?? []
      const hold = holdFor(plan.length)
      const steps = tick.primitive_steps_executed.length
      return [
        {
          label: `${tick.selected_action}: ${plan.length} primitive${plan.length === 1 ? '' : 's'}`,
          expr: `max(1, ⌊4 ÷ ${plan.length}⌋)`,
          result: `${hold} step${hold === 1 ? '' : 's'} each`,
        },
        {
          label: 'frames pressed',
          expr: `${steps} steps × 2 frames`,
          result: `${steps * 2} frames, ${fmt((steps * 2) / 35, 2)} s`,
        },
      ]
    },
    code: 'motor.py · TacticalMotor.burst',
  },
  outcome: {
    title: 'See and remember',
    beat: 6,
    sentence: 'What came back from the game, and every memory it is filed into.',
    paragraphs: [
      "This is the only moment the world talks back; everything the system learns starts here. The outcome adds a sample to the simulator's cache of real results, updates the running averages of the active strategy, moves the exploration counters, and, during training, goes into the replay buffer the networks learn from between episodes. (Replays like this one only read the networks; they record nothing.)",
      "The outcome is also split into five rewards, one per module, so each module's network learns its own question: survival from damage and death, combat from hits and kills, navigation from new ground, resource from pickups, and goal from the scenario's own reward.",
    ],
    formula:
      'survival = −damage ÷ 25 − 3·died;  combat = 0.5·hits + 2·kills;  navigation = new cells;  resource = health ÷ 25 + armor ÷ 25 + ammo ÷ 10;  goal = reward',
    substitute: ({ tick }) => {
      const o = tick.outcome
      if (!o) return []
      const r = o.module_rewards ?? {}
      const next = exploration(tick)
      return [
        {
          label: 'survival',
          expr: `−${fmt(o.damage_taken ?? 0, 0)} ÷ 25 − 3·${o.died ? 1 : 0}`,
          result: fmt(r.survival ?? 0, 2),
        },
        {
          label: 'combat',
          expr: `0.5·${fmt(o.hits_delta ?? 0, 0)} + 2·${fmt(o.kills_delta ?? 0, 0)}`,
          result: fmt(r.combat ?? 0, 2),
        },
        {
          label: 'navigation',
          expr: `${o.new_cells ?? 0} new cell${o.new_cells === 1 ? '' : 's'}`,
          result: fmt(r.navigation ?? 0, 2),
        },
        {
          label: 'resource',
          expr: `${fmt(o.health_gain ?? 0, 0)} ÷ 25 + ${fmt(o.armor_gain ?? 0, 0)} ÷ 25 + ${fmt(o.ammo_gain ?? 0, 0)} ÷ 10`,
          result: fmt(r.resource ?? 0, 2),
        },
        { label: 'goal', expr: 'scenario reward', result: fmt(r.goal ?? 0, 2) },
        {
          label: 'exploration pressure for the next tick',
          expr: `(${Object.entries(next.terms ?? {})
            .filter(([k]) => !k.endsWith('damper') && k !== 'd1_pressure')
            .map(([, v]) => fmt(v, 3))
            .join(' + ')}) × ${Object.entries(next.terms ?? {})
            .filter(([k]) => k.endsWith('damper'))
            .map(([, v]) => fmt(v, 2))
            .join(' × ')}`,
          result: fmt(next.exploration_pressure ?? 0, 3),
        },
      ]
    },
    code: 'controller.py · step (bookkeeping), features.py · module_rewards',
  },
}

/** Why each bound exists, shown when a bound badge is clicked. */
export const BOUNDS: Record<string, string> = {
  'menu ≤ 16 steps per macro':
    'Every macro is a fixed list of at most 16 primitives, so the slowest action still finishes in bounded time and can be checked before it runs.',
  '16 candidates': 'The simulator projects at most 16 actions per tick, so its cost never grows with the vocabulary.',
  'depth 4 · 2 branches':
    'Each projection looks four primitives ahead under two enemy moods: enough to compare actions, too short to plan.',
  '15 ms':
    "Projection stops at 15 milliseconds of wall-clock time; unprojected actions are still scored, without the simulator's evidence.",
  '≤ 50 samples':
    'The empirical cache keeps at most 50 real outcomes per situation and action, so old experience fades and memory stays small.',
  'deadline 65% of tick':
    'Modules run in parallel with a deadline at 65% of the tick budget; a late module is recomputed locally, so the tick never waits.',
  'one pick from the menu': 'The arbiter returns exactly one legal action. It cannot invent an action or combine two.',
  '8 frames':
    'Each decision is executed for at most 4 steps of 2 game frames, then the controller decides again with a fresh snapshot.',
  '≤ 12 strategies':
    'The strategy archive holds at most 12 entries; when full, the weakest one that is not active is evicted.',
  '≤ 100k transitions':
    'The replay buffer the networks train on keeps the latest 100,000 decisions, and training only happens between episodes, never inside a tick.',
  'one proposal in flight':
    'The slow path works on one macro proposal at a time with a 20-second timeout, and the real-time loop never waits for it.',
}
