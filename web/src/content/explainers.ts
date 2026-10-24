// The copy for every panel's three-layer explainer: one sentence, a paragraph, and the formula
// with the current tick's numbers substituted. Constants are the controller's own (see derive.ts).
import type { EpisodeMeta, ProposalTrace, TickTrace } from '../schema/bundle'
import {
  AIM_BAND_DEG,
  ARCHIVE_ALPHA,
  ARCHIVE_SLOTS,
  BASE_TEMPERATURE,
  MODULES,
  MODULE_TEMPERATURE,
  NEAR_WALL,
  PRESSURE_FLOOR,
  SAMPLE_MARGIN,
  SAMPLE_PRESSURE,
  STEERING_CHOICES,
  STRATEGY_BONUS,
  TRUST_COUNT,
  aimBandHalfWidth,
  contextBuckets,
  exploration,
  fmt,
  gameSeconds,
  holdFor,
  learning,
  moduleVoteParts,
  pct,
  pressureReading,
  prettyId,
  rankedActions,
  signed,
  slowPathAt,
} from '../data/derive'

/** A number inside arithmetic: negatives in parentheses with a true minus sign. */
function term(value: number, digits = 2): string {
  const text = fmt(Math.abs(value), digits)
  return value < 0 && text !== fmt(0, digits) ? `(−${text})` : text
}

/** The inspector's panels; each is also an element id, `#panel-<id>`. */
export type PanelId =
  'scrubber' | 'game' | 'world' | 'legal' | 'projection' | 'modules' | 'arbiter' | 'motor' | 'outcome'

/** Everything with an explainer: the panels, plus the boxes of the overview and the hierarchy. */
export type ExplainerId =
  | PanelId
  | 'request'
  | 'worker'
  | 'gate'
  | 'rewards'
  | 'replay'
  | 'networks'
  | 'trust'
  | 'steering'
  | 'exploration'
  | 'd1'

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
  /** The tick before, whose closing exploration state this tick's arbiter used; null on the first. */
  prev: TickTrace | null
  proposals: ProposalTrace[]
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
  howto:
    'Step through the episode with ← and → (Shift for ten) or press play; hover any bar or chip for its numbers; press ? on a panel for the full explanation; switch Depth to Formula for this tick\u2019s arithmetic.',
}

export const EXPLAINERS: Record<ExplainerId, Explainer> = {
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
  request: {
    title: 'A module asks',
    sentence:
      "When a module's own memory shows a concrete, repeated failure, it asks the slow path for a new macro; the tick does not wait for an answer.",
    paragraphs: [
      'Each module keeps a few counters: damage streaks, failed steps, stalls, ticks without progress. Crossing its threshold (for survival, damage on 4 ticks in a row, or health under 35 under heavy fire) makes the module describe its problem in one sentence and hand it to the slow worker.',
      'Only one request can be in flight. While the worker is busy, further requests are dropped and the module asks again on a later tick.',
    ],
    substitute: ({ tick }) => {
      const request = tick.slow_path_request
      return request
        ? [{ label: `${request.module} asked`, expr: request.description, result: 'sent to the worker' }]
        : [
            {
              label: 'this tick',
              expr: 'no module crossed its threshold, or the worker was busy',
              result: 'no request',
            },
          ]
    },
    code: 'modules.py · check_expansion_needed; controller.py · step',
  },
  worker: {
    title: 'The slow worker',
    sentence:
      'Outside the real-time loop, a worker turns the problem into a proposed macro: a named, fixed sequence of primitives with preconditions.',
    paragraphs: [
      'In these recordings the worker uses its fallback templates, hand-written macro patterns filled in for the module that asked. With Codex switched on, a language model writes the proposal instead. Either way the result is only text until the admission gate accepts it.',
      'The worker has 20 seconds per proposal and works on one at a time. The controller keeps deciding every tick meanwhile; the finished proposal is picked up at the start of a later tick.',
    ],
    code: 'llm_worker.py · AsyncLLMWorker',
  },
  gate: {
    title: 'The admission gate',
    sentence: 'Five checks decide whether a proposed macro may join the menu: parse, legality, sandbox, d1 and admit.',
    paragraphs: [
      'Parse: the text must be a well-formed proposal. Legality: a new id, known primitives only, at most 16 steps and no more than its own maximum duration. Sandbox: the bounded simulator rolls the macro out, and it fails if the rollout predicts death from a state that was not already critical. d1: when d1-ultra is on it is asked whether the macro is worth adding; it is off here, so the stage is skipped. Admit: the macro is registered in the vocabulary and a matching strategy is added to the archive.',
      'A failed stage stops the proposal and nothing changes. An admitted macro is scored like any other action from then on, and the only way it is used is by winning the same arbiter as everything else.',
    ],
    formula: 'admitted = parse ∧ legality ∧ sandbox ∧ (d1 or skipped) → admit',
    substitute: ({ tick, proposals }) => {
      const arrived = slowPathAt(tick, proposals).arrived
      if (arrived.length === 0) return [{ label: 'this tick', expr: 'no proposal reached the gate', result: 'idle' }]
      return arrived.flatMap((p) =>
        (p.stage_results ?? []).map((s) => ({
          label: s.stage,
          expr: s.reason ?? '',
          result: s.skipped ? 'skipped' : s.passed ? 'passed' : 'failed',
        })),
      )
    },
    code: 'admission.py · ProposalAdmissionPipeline.evaluate_and_admit',
  },
  rewards: {
    title: 'Five rewards',
    sentence:
      "Every outcome is split into five rewards, one per module, so each module's network learns its own question.",
    paragraphs: [
      'Survival is paid for avoiding damage and death, combat for hits and kills, navigation for new ground, resource for pickups, and goal is the scenario’s own reward. A module is never trained on another module’s question.',
    ],
    formula:
      'survival = −damage ÷ 25 − 3·died;  combat = 0.5·hits + 2·kills;  navigation = new cells;  resource = health ÷ 25 + armor ÷ 25 + ammo ÷ 10;  goal = reward',
    substitute: ({ tick }) =>
      MODULES.map((m) => ({ label: m, expr: 'this tick', result: fmt(tick.outcome?.module_rewards?.[m] ?? 0, 2) })),
    code: 'features.py · module_rewards',
  },
  replay: {
    title: 'Replay buffer',
    sentence:
      'During training every decision is stored with its five rewards; the networks learn from this buffer between episodes, never inside a tick.',
    paragraphs: [
      'The buffer keeps the latest 100,000 decisions. Because training happens only between episodes, the time a tick takes never depends on learning.',
      'Replays like the ones in this app only read the trained networks; they add nothing to the buffer.',
    ],
    code: 'learning.py · ReplayBuffer, Learner.train',
  },
  networks: {
    title: 'Learned networks',
    sentence:
      "Small networks learn each module's value for each action, and a gate network learns how far to trust each module; both only re-weigh what is already on the menu.",
    paragraphs: [
      `A module's learned value is blended with its heuristic score in proportion to trust, λ = n ÷ (n + ${TRUST_COUNT}), where n counts how often the action was tried in this kind of situation. The gate network proposes module weights for the arbiter; they are blended with the hand-written table by the gate's own trust, g.`,
      'Neither network can add an action, remove one or skip a level. With no checkpoint loaded every bar is heuristic, and the controller plays exactly as it did before learning existed.',
    ],
    formula: `λ = n ÷ (n + ${TRUST_COUNT});  w = (1 − g)·w_table + g·w_gate`,
    substitute: ({ tick, meta }) => {
      if (!meta.brains.learned_networks) return [{ label: 'this episode', expr: 'no checkpoint loaded', result: 'off' }]
      const view = learning(tick)
      const lambda = view.network_share ?? 0
      return [
        {
          label: `trust in the networks for ${prettyId(tick.selected_action)}`,
          expr:
            lambda < 1 ? `n ≈ ${fmt((TRUST_COUNT * lambda) / (1 - lambda), 0)}, so λ = n ÷ (n + ${TRUST_COUNT})` : 'λ',
          result: fmt(lambda, 3),
        },
        { label: 'gate share g', expr: 'trust of the gate network here', result: fmt(view.gate_share ?? 0, 3) },
      ]
    },
    code: 'learning.py · Learner',
  },
  trust: {
    title: 'Trust λ',
    sentence:
      "Trust is how much of a module's score its network may set, earned by experience in this kind of situation.",
    paragraphs: [
      `λ = n ÷ (n + ${TRUST_COUNT}): an action tried ${TRUST_COUNT} times in this context gives the network half the say; ${3 * TRUST_COUNT} times, three quarters. A situation the networks have never met is decided by the heuristics alone.`,
      'Trust is kept per situation and action, so the networks can be sure of themselves in a familiar corridor and silent in a new room.',
    ],
    formula: `λ = n ÷ (n + ${TRUST_COUNT})`,
    substitute: ({ tick, meta }) => {
      if (!meta.brains.learned_networks)
        return [{ label: 'this episode', expr: 'no checkpoint loaded', result: 'λ = 0' }]
      const lambda = learning(tick).network_share ?? 0
      const n = lambda < 1 ? (TRUST_COUNT * lambda) / (1 - lambda) : Infinity
      return [
        {
          label: prettyId(tick.selected_action),
          expr: `${fmt(n, 0)} ÷ (${fmt(n, 0)} + ${TRUST_COUNT})`,
          result: fmt(lambda, 3),
        },
      ]
    },
    code: 'learning.py · Learner.action_trust',
  },
  steering: {
    title: 'Steering',
    sentence:
      'After each action, a four-way choice about strategy: keep the current one, switch to a stored one, vary it, or ask for a new one.',
    paragraphs: [
      `The strategy archive holds at most ${ARCHIVE_SLOTS} strategies, each a short sequence of actions with a running reward and success rate, both updated as ${fmt(1 - ARCHIVE_ALPHA, 1)} × old + ${fmt(ARCHIVE_ALPHA, 1)} × this outcome. A step counts as a failure when it costs more than 8 health or the player dies. Actions in the active strategy's sequence get a ${STRATEGY_BONUS} bonus in the arbiter's score.`,
      "The choice is made after the action has run, with the exploration pressure that tick produced, so the strategy it settles on applies to the next tick's arbiter. When the archive is full, a new strategy evicts the stored one that is not active and has the lowest observed reward + 5 × success rate.",
    ],
    formula: STEERING_CHOICES.map((c) => `${c.label} = ${c.formula}`).join(';  '),
    substitute: ({ tick }) => {
      const s = tick.steering
      if (!s) return []
      const next = exploration(tick)
      const entry = s.entries?.find((e) => e.strategy_id === s.active_before)
      const failures = next.recent_failures ?? 0
      const pressure = next.exploration_pressure ?? 0
      const values: Record<string, string> = {
        continue_current_strategy: `1.2 × ${fmt(entry?.success_rate ?? 0, 3)} − 0.35 × ${failures}`,
        switch_to_archived_strategy: `0.4 + 0.25 × ${failures} + 0.3 × ${fmt(pressure, 3)}`,
        explore_variation: `0.3 + 0.7 × ${fmt(pressure, 3)}`,
        request_new_strategy_proposal: `0.2 + ${failures >= 3 ? '0.9' : '0'} + 0.4 × ${fmt(pressure, 3)}`,
      }
      return STEERING_CHOICES.map((c) => ({
        label: `${c.label}${c.id === s.choice ? ' (chosen)' : ''}`,
        expr: `${values[c.id]} = ${fmt(s.scores?.[c.id] ?? 0, 3)}`,
        result: pct(s.probabilities?.[c.id] ?? 0, 1),
      }))
    },
    code: 'archive.py · StrategyArchive.decide_strategy_action, admit_strategy',
  },
  exploration: {
    title: 'Exploration pressure',
    sentence:
      'One number between 0.02 and 1 that says how far the arbiter may stray from its best guess, recomputed after every action.',
    paragraphs: [
      'Four quarter-terms add up: uncertainty (how unsure the modules were), failures (recent failed steps), plateau (no progress for a while) and novelty (how new this situation is). Each is at most 0.25.',
      'Three dampers can cut the sum: steady progress multiplies it by 0.55, a risky moment (health 30 or less, or heavy fire with an enemy in view) by 0.35, and a kill or full armor just now by 0.25. The result is clamped to [0.02, 1].',
      `Pressure sets the arbiter's softmax temperature, ${fmt(BASE_TEMPERATURE, 2)} + pressure, and scales its exploration and novelty bonuses. It also gates sampling: the arbiter draws from the softmax instead of taking the top score only when the top two are within ${SAMPLE_MARGIN} and pressure is at least ${SAMPLE_PRESSURE}. Because it is computed after each action, a tick's arbiter uses the value from the end of the tick before.`,
    ],
    formula: `pressure = clamp((uncertainty + failures + plateau + novelty) × dampers, ${PRESSURE_FLOOR}, 1);  temperature = ${fmt(BASE_TEMPERATURE, 2)} + pressure`,
    substitute: ({ prev }) => {
      const r = pressureReading(prev ? exploration(prev) : null)
      if (r.initial) {
        return [{ label: 'first tick', expr: 'no outcome yet: the starting values', result: fmt(r.pressure, 2) }]
      }
      return [
        {
          label: 'the four terms',
          expr: r.terms.map((t) => fmt(t.value, 3)).join(' + '),
          result: fmt(r.sum, 3),
        },
        {
          label: 'times the dampers',
          expr: `${fmt(r.sum, 3)} × ${r.dampers.map((d) => fmt(d.value, 2)).join(' × ')}`,
          result: fmt(r.product, 3),
        },
        {
          label: `clamped to [${PRESSURE_FLOOR}, 1]`,
          expr: r.d1 === null ? fmt(r.product, 3) : `0.5 × ${fmt(r.product, 3)} + 0.5 × d1 ${fmt(r.d1, 3)}`,
          result: fmt(r.pressure, 3),
        },
        {
          label: 'temperature',
          expr: `${fmt(BASE_TEMPERATURE, 2)} + ${fmt(r.pressure, 3)}`,
          result: fmt(r.temperature, 3),
        },
      ]
    },
    code: 'exploration.py · ExplorationController.update_and_decide',
  },
  d1: {
    title: 'd1-ultra advice',
    sentence:
      'An optional outside model that can advise the modules, the arbiter and the admission gate; off in these recordings.',
    paragraphs: [
      "When on, d1-ultra answers small multiple-choice questions: which actions a module should favour, which action the arbiter should pick, and whether a proposed macro is worth admitting. Its advice enters as a dotted share of a module's bar and as a bonus of 0.3 × its probability in the arbiter's score. In the synchronous mode it can also pull the exploration pressure halfway toward its own estimate.",
      'It never adds an action or lifts a bound. It needs an API key and answers asynchronously, so a tick never waits for it; an unanswered question is simply skipped.',
    ],
    code: 'd1_client.py · D1UltraClient',
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
  '≤ 16 primitives per macro':
    'Every action, built in or admitted, is a fixed list of at most 16 primitives, so the menu can be checked before anything runs.',
  'five stages':
    'A proposal passes parse, legality, sandbox, d1 and admit in order; the first failure stops it, so nothing half-checked joins the menu.',
  'fixed reflexes':
    'The motor may turn to aim or steer onto a pickup, but never changes the plan; the same plan in the same situation presses the same keys.',
  'each term ≤ 0.25':
    'Each of the four reasons to explore can add at most a quarter, so no single signal can push the arbiter into random play.',
  'pressure 0.02 to 1':
    'Pressure is clamped: never quite zero, so the arbiter can still notice a close call, and never above 1, so the temperature stays at most 1.10.',
  'trains between episodes':
    'The networks only learn between episodes, from the replay buffer; inside a tick they are read, never trained.',
  'advice only':
    "d1-ultra's answers are mixed into scores that already exist; it cannot add an action or pick outside the menu.",
  'one proposal in flight':
    'The slow path works on one macro proposal at a time with a 20-second timeout, and the real-time loop never waits for it.',
}
