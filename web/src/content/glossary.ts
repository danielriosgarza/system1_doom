// The glossary: every word the explanations lean on, with where the screens show it and where the code
// keeps it. The first sixteen are the documentation's glossary (docs/DOCUMENTATION.md, section 18), and a
// test keeps the two in step.
import {
  contextWords,
  d1Words,
  explainPick,
  fmt,
  gameSeconds,
  learning,
  pct,
  PICK_RULES,
  pressureForArbiter,
  pressureReading,
  prettyId,
  requestSpans,
  trustLambda,
} from '../data/derive'
import type { DrawerSection, Screen } from '../store'
import type { ExplainerContext, PanelId } from './explainers'

/**
 * A “where to see it” link: a screen, optionally one of its panels to flash, or another tab of the drawer
 * (for the glossary, optionally at one entry). Without a label, it is named after the screen and panel.
 */
export type SeeLink = { label?: string } & ({ screen: Screen; panel?: PanelId } | { tab: DrawerSection; term?: string })

export interface GlossaryEntry {
  id: string
  term: string
  /** Other words that link here from the copy: whole words, any case. Never one letter, never a bare “gate”. */
  aliases: string[]
  meaning: string
  see: SeeLink[]
  /** `file.py · Name`, as an explainer's code line. */
  code: string
  /** This tick's value, when there is one to read. */
  now?: (ctx: ExplainerContext) => string
}

const thousands = (n: number) => n.toLocaleString('en-US')

export const GLOSSARY: GlossaryEntry[] = [
  // The documentation's glossary.
  {
    id: 'action',
    term: 'action',
    aliases: ['actions', 'ActionSpec'],
    meaning:
      'The only thing the controller can execute: a named plan of one or more primitives, with preconditions, at most 16 steps and a termination condition. Primitives are one step long; macros are longer.',
    see: [{ screen: 'tick', panel: 'legal' }],
    code: 'actions.py · ActionSpec',
    now: ({ tick, meta }) =>
      `${tick.available_actions.length} of the ${Object.keys(meta.actions).length} actions in this recording are legal.`,
  },
  {
    id: 'arbiter',
    term: 'arbiter',
    aliases: ['arbiters'],
    meaning:
      'The one decider per tick. It turns the five opinions, the projections, exploration, the archive’s strategy and d1-ultra’s advice into one pick, with every term of the score written down.',
    see: [{ screen: 'tick', panel: 'arbiter' }, { screen: 'hierarchy' }],
    code: 'arbiter.py · FinalArbiter.arbitrate',
    now: ({ tick }) => explainPick(tick).headline,
  },
  {
    id: 'budget-mode',
    term: 'budget mode',
    aliases: ['budget modes'],
    meaning:
      'How much time the tick’s budget allows: 40 ms by default, 5 s in a recording that waits for d1-ultra. Full runs everything, reduced drops the projections, and critical repeats the cached action with stand-in module outputs.',
    see: [{ screen: 'tick', panel: 'arbiter', label: 'Tick → One decision (the “out of time” rule)' }],
    code: 'controller.py · DoomDecisionController._select_budget_mode',
    now: ({ tick }) => `This tick ran in ${tick.budget_mode} mode.`,
  },
  {
    id: 'committed-pick',
    term: 'committed pick',
    aliases: ['committed', 'commits the arbiter'],
    meaning:
      'The arbiter’s shortcut: when one module is nearly certain (probability at least 0.9, utility at least 5, a lead of at least 4), its choice stands without the full comparison.',
    see: [{ screen: 'tick', panel: 'arbiter' }],
    code: 'arbiter.py · FinalArbiter.arbitrate',
    now: ({ tick }) =>
      tick.arbiter?.pick_rule === 'committed'
        ? `Committed this tick, by the ${tick.arbiter.committed_by} module.`
        : `Not this tick: the pick was ${tick.arbiter?.pick_rule === 'critical_cached' ? 'out of time' : (tick.arbiter?.pick_rule ?? 'greedy')}.`,
  },
  {
    id: 'context-signature',
    term: 'context signature',
    aliases: ['context', 'contexts', 'situation', 'situations', 'context buckets', 'buckets'],
    meaning:
      'A coarse key for the situation: health, ammo, enemies in view, recent damage and pickups, each put in one of a few buckets. Trust, novelty, the d1 cache and the archive all look things up by it.',
    see: [{ screen: 'tick', panel: 'world' }],
    code: 'state.py · WorldState.context_signature',
    now: ({ tick }) => contextWords(tick.context_signature),
  },
  {
    id: 'd1-ultra',
    term: 'd1-ultra',
    aliases: ['d1'],
    meaning:
      'Liquid AI’s decision model, asked small multiple-choice questions by the modules, the arbiter, exploration and the admission gate. Advisory everywhere it appears, and switched on recording by recording.',
    see: [
      { screen: 'tick', panel: 'modules', label: 'Tick → Five opinions (the dotted share)' },
      { screen: 'tick', panel: 'arbiter' },
      { screen: 'hierarchy', label: 'Hierarchy (its side card)' },
      { screen: 'overview' },
    ],
    code: 'd1_client.py · D1UltraClient',
    now: ({ tick, meta }) =>
      meta.brains.d1_ultra ? `On in this recording. ${d1Words(tick, meta)}` : 'Off in this recording.',
  },
  {
    id: 'exploration-floor',
    term: 'exploration floor',
    aliases: ['floor'],
    meaning:
      'A flat chance, used only in training, that the arbiter takes a random legal action instead of its pick: 0.6 at the first episode, falling in a straight line to 0.05 by episode 100, then flat. Zero in a recording.',
    see: [{ screen: 'learning', panel: 'curves' }],
    code: 'train.py · exploration_schedule',
    now: ({ meta }) =>
      meta.config.exploration_floor > 0
        ? `${fmt(meta.config.exploration_floor, 2)} in this recording.`
        : '0 in this recording: the arbiter never draws at random.',
  },
  {
    id: 'exploration-pressure',
    term: 'exploration pressure',
    aliases: ['pressure'],
    meaning:
      'How inclined the arbiter is to try something other than its best guess: four readings of the situation, each worth up to 0.25, damped after success and clamped between 0.02 and 1. Temperature = 0.10 + pressure sets how flat its draw is. The arbiter of a tick uses the pressure left by the tick before.',
    see: [{ screen: 'hierarchy', label: 'Hierarchy (the gauge)' }],
    code: 'exploration.py · ExplorationController',
    now: ({ ticks, index }) => {
      const reading = pressureReading(pressureForArbiter(ticks, index))
      return `This tick’s arbiter read pressure ${fmt(reading.recorded, 2)}, so temperature ${fmt(reading.temperature, 2)}.`
    },
  },
  {
    id: 'gate-network',
    term: 'gate network',
    aliases: ['gate share', 'gate net', 'learned gate', 'learned gate network'],
    meaning:
      'A small network (hidden 32) that estimates from the state how much following each module pays off. The arbiter blends its proposal with the hand-written module weights: used = normalise((1 − g) · table + g · gate), where g is the gate share.',
    see: [{ screen: 'learning', panel: 'gateview' }],
    code: 'learning.py · Learner.gate_weights, arbiter.py · FinalArbiter._module_context_weights',
    now: ({ tick, meta }) =>
      meta.brains.learned_networks
        ? `g = ${fmt(tick.arbiter?.gate_share ?? 0, 2)} this tick: the gate’s weights have ${pct(tick.arbiter?.gate_share ?? 0)} of the say.`
        : 'No networks in this recording, so the table alone sets the weights.',
  },
  {
    id: 'macro',
    term: 'macro',
    aliases: ['macros'],
    meaning:
      'An action made of several primitives and run as one plan: built in (weave fire, peek and fire, circle strafe, retreat to cover, approach pickup) or proposed by the slow path and admitted (evasive burst 1 and 2 in the heuristics recording).',
    see: [
      { screen: 'menu', panel: 'encoding' },
      { screen: 'tick', panel: 'legal' },
    ],
    code: 'actions.py · ActionSpec.is_macro',
    now: ({ tick, meta }) => {
      const n = tick.available_actions.filter((a) => meta.actions[a]?.is_macro).length
      return `${n} ${n === 1 ? 'macro is' : 'macros are'} legal this tick.`
    },
  },
  {
    id: 'module',
    term: 'module',
    aliases: ['modules', 'decider', 'deciders'],
    meaning:
      'One of five small deciders, survival, combat, navigation, resource and goal, each answering its own question over the same menu, with its own memory and its own reward.',
    see: [{ screen: 'tick', panel: 'modules' }],
    code: 'modules.py · DecisionModule',
  },
  {
    id: 'network-share',
    term: 'network share',
    aliases: [],
    meaning:
      'How much of play the learned networks steer: the experience-weighted mean of trust λ over the actions tried, Σ n · λ(n) ÷ Σ n. 0.89 for this checkpoint after 300 episodes.',
    see: [{ screen: 'learning', panel: 'curves' }],
    code: 'learning.py · Learner.network_share',
    now: ({ tick, meta }) =>
      meta.brains.learned_networks
        ? `On the action picked this tick, the networks had ${pct(learning(tick).network_share ?? 0)} of the say.`
        : 'No networks in this recording: the heuristics have all of the say.',
  },
  {
    id: 'projection',
    term: 'projection',
    aliases: ['projections', 'rollout', 'rollouts'],
    meaning:
      'A bounded analytic rollout of one candidate action in the simulator: expected value, damage taken and dealt, resources, progress and survival. At most 16 candidates, depth 4, branching 2, 15 ms each.',
    see: [{ screen: 'tick', panel: 'projection' }],
    code: 'simulator.py · ProjectedOutcome',
    now: ({ tick }) => {
      const n = Object.keys(tick.projection_results_used).length
      return n > 0
        ? `${n} candidates were projected this tick.`
        : `None this tick: the budget mode was ${tick.budget_mode}.`
    },
  },
  {
    id: 'slow-path',
    term: 'slow path',
    aliases: [],
    meaning:
      'The only part that can add to the menu: a module asks, a slow worker writes a macro (Codex, or a template when Codex is off), the admission gate checks it, and it joins the menu. One request in flight, a 20 s timeout, and a tick never waits for it.',
    see: [{ screen: 'menu', panel: 'requests' }],
    code: 'llm_worker.py · SlowLLMWorker',
    now: ({ tick, ticks, proposals }) => {
      const spans = requestSpans(ticks, proposals)
      const arrived = spans.find((s) => s.arrived === tick.tick)
      if (arrived) return `A proposal from the ${arrived.module} module reached the gate this tick.`
      const busy = spans.find((s) => s.asked <= tick.tick && (s.arrived === null || s.arrived > tick.tick))
      if (busy) return `Busy since tick ${busy.asked}, writing for the ${busy.module} module.`
      return 'Idle this tick: no request is in flight.'
    },
  },
  {
    id: 'trust-lambda',
    term: 'trust λ',
    aliases: ['trust', 'lambda'],
    meaning:
      'The weight a learned network’s opinion gets for an action tried n times in this situation: λ = n ÷ (n + 25). Tried 25 times means half the say; never tried means the heuristic alone.',
    see: [{ screen: 'learning', panel: 'trustmap' }],
    code: 'learning.py · Learner.action_trust',
    now: ({ tick, meta, trust }) => {
      if (!meta.brains.learned_networks || !trust) return 'No networks in this recording, so no trust.'
      const lambdas = tick.available_actions.map((a) =>
        trustLambda(trust.action_counts[`${tick.context_signature}|${a}`] ?? 0),
      )
      const mean = lambdas.reduce((s, l) => s + l, 0) / Math.max(1, lambdas.length)
      return `Mean λ over this tick’s ${lambdas.length} legal actions: ${fmt(mean, 2)}.`
    },
  },
  {
    id: 'tick',
    term: 'tick',
    aliases: ['ticks'],
    meaning:
      'One decision: freeze the state, choose, press the plan for 8 game frames, about 0.23 s at 35 frames per second. Not one game frame.',
    see: [{ screen: 'tick', panel: 'scrubber', label: 'The timeline at the bottom' }],
    code: 'controller.py · DoomDecisionController.step',
    now: ({ tick, meta }) =>
      `Tick ${tick.tick} of ${meta.last_tick}, ${fmt(gameSeconds(tick.tick), 1)} s into the game.`,
  },

  // The app's own words.
  {
    id: 'admission-gate',
    term: 'admission gate',
    aliases: ['admission', 'admitted', 'admit', 'admits', 'stages'],
    meaning:
      'The five stages between a proposal and the menu: parse, legality, sandbox, d1 when it is on, admit. Any failure leaves the menu unchanged and is written to proposals.jsonl.',
    see: [{ screen: 'menu', panel: 'gate' }, { screen: 'hierarchy' }],
    code: 'admission.py · ProposalAdmissionPipeline.evaluate_and_admit',
  },
  {
    id: 'checkpoint',
    term: 'checkpoint',
    aliases: ['checkpoints'],
    meaning:
      'The learner’s saved state: the five value networks, the gate network, the running statistics and the trust counts. The learned recording loaded checkpoint.pt after 300 episodes and 25,204 transitions; its best evaluation score was 1,842.',
    see: [
      { screen: 'learning', panel: 'headtohead' },
      { tab: 'recording', label: 'This recording' },
    ],
    code: 'learning.py · Learner.save, Learner.load',
    now: ({ meta }) =>
      meta.checkpoint
        ? `${meta.checkpoint.file}, after ${thousands(meta.checkpoint.episodes)} episodes and ${thousands(meta.checkpoint.transitions_seen)} transitions.`
        : 'None: the heuristics played alone.',
  },
  {
    id: 'codex',
    term: 'Codex',
    aliases: [],
    meaning:
      'The command-line LLM the slow worker can call when recording with --codex; it writes the proposal text. Off in both recordings, so templates answered.',
    see: [{ screen: 'menu', panel: 'proposal' }],
    code: 'llm_worker.py · SlowLLMWorker',
  },
  {
    id: 'encoding',
    term: 'encoding',
    aliases: ['12-number encoding', 'encoded', 'encodings'],
    meaning:
      'How the networks see an action: twelve numbers, the share of the plan in each of eight primitives, the share of weapon switches, length ÷ 16, 1 for a macro and 1 when it targets a pickup. So an admitted macro can be scored at once.',
    see: [{ screen: 'menu', panel: 'encoding' }],
    code: 'features.py · encode_action',
  },
  {
    id: 'evaluation',
    term: 'evaluation',
    aliases: ['evaluate', 'evaluated', 'held-out'],
    meaning:
      'The fair comparison: each brain plays the same 30 held-out seeded episodes greedily, with no learning and no exploration. Heuristics 548 reward and 13% cleared; the latest checkpoint 997 and 30%; the best 987 and 30%.',
    see: [{ screen: 'learning', panel: 'headtohead' }],
    code: 'train.py · evaluate',
  },
  {
    id: 'frame',
    term: 'frame',
    aliases: ['frames', 'game frame', 'game frames'],
    meaning:
      'One picture of the game: Doom runs at 35 frames per second, and a tick lasts 8 of them. The recording keeps one 320 × 240 frame per tick, the screen the controller saw when it decided, captured at the moment the state was read so the overlays line up.',
    see: [{ screen: 'tick', panel: 'game' }],
    code: 'export.py · RecordingBridge',
  },
  {
    id: 'gate-mask',
    term: 'gate mask',
    aliases: ['trains the gate'],
    meaning:
      'The gate network learns only from the modules whose own top pick was the action actually executed; the other modules’ rows are masked out of its loss.',
    see: [{ screen: 'learning', panel: 'gateview' }],
    code: 'learning.py · Learner.record_step, Learner.train',
  },
  {
    id: 'heuristics',
    term: 'heuristics',
    aliases: ['heuristic', 'hand-written'],
    meaning:
      'The rules each module and the arbiter use with no training: the module weight table, the utilities, the preconditions. The heuristics-only recording is these alone.',
    see: [{ screen: 'learning', panel: 'headtohead' }],
    code: 'modules.py · DecisionModule',
  },
  {
    id: 'learned-networks',
    term: 'learned networks',
    aliases: ['networks', 'value network', 'value networks'],
    meaning:
      'Five value networks, one per module (hidden 64), plus the gate network (hidden 32), trained between episodes on the replay buffer with learning rate 0.001. They re-weigh the options by trust λ and g; they never add an option or skip a level.',
    see: [{ screen: 'learning', panel: 'trustmap' }, { screen: 'overview' }],
    code: 'learning.py · Learner',
  },
  {
    id: 'legality',
    term: 'legality',
    aliases: ['legality check'],
    meaning:
      'What a parsed proposal must satisfy: an id of 2 to 63 lowercase letters, digits and underscores, starting with a letter and not a primitive’s name; only known primitives; at most 16 steps; a maximum duration no longer than the cap.',
    see: [{ screen: 'menu', panel: 'gate' }],
    code: 'admission.py · ProposalAdmissionPipeline.evaluate_and_admit',
  },
  {
    id: 'live-episode',
    term: 'live episode',
    aliases: ['live episodes', 'live mode'],
    meaning:
      'An episode being played right now by python -m system1_doom.serve: the same deciders, the same records as a recording, arriving one tick at a time; when it ends it becomes a recording.',
    see: [
      { tab: 'recording', label: 'This recording' },
      { tab: 'keys', label: 'the l key' },
    ],
    code: 'serve.py · play_live_episode',
  },
  {
    id: 'menu',
    term: 'menu',
    aliases: ['legal actions', 'legal', 'pruned', 'precondition', 'preconditions'],
    meaning:
      'The actions available this tick. An action is legal when every precondition in its spec holds (an enemy in view, enough ammo, a pickup in view); otherwise it is pruned and the failed condition is named. The arbiter only sees legal actions.',
    see: [{ screen: 'tick', panel: 'legal' }],
    code: 'actions.py · ActionVocabulary.available_actions, PreconditionSpec.failing_condition',
    now: ({ tick }) =>
      `${tick.available_actions.length} legal, ${Object.keys(tick.pruned_actions ?? {}).length} pruned this tick.`,
  },
  {
    id: 'motor',
    term: 'motor',
    aliases: [],
    meaning:
      'Presses the chosen plan’s primitives, eight game frames in total, each primitive held for its share, with reflexes filling in the aiming.',
    see: [{ screen: 'tick', panel: 'motor' }],
    code: 'motor.py · TacticalMotor.burst',
  },
  {
    id: 'n-step-return',
    term: 'n-step return',
    aliases: ['8-step return', 'standardised return', 'n-step returns'],
    meaning:
      'What a module’s network learns to predict: its own rewards over the next 8 ticks, each discounted by 0.9 per step, then standardised with running statistics kept in the checkpoint.',
    see: [{ screen: 'learning', panel: 'anatomy' }],
    code: 'learning.py · n_step_returns, RunningStats',
  },
  {
    id: 'pick-rule',
    term: 'pick rule',
    aliases: ['greedy', 'sampled', 'explored'],
    meaning:
      'How the arbiter settled: greedy (the top score wins), sampled (the top two within 0.08 and pressure at least 0.45, so it drew from the softmax at the temperature), committed, explored (the floor), or out of time (the cached action repeated).',
    see: [{ screen: 'tick', panel: 'arbiter' }],
    code: 'arbiter.py · FinalArbiter.arbitrate',
    now: ({ tick }) => {
      const rule = tick.arbiter?.pick_rule
      return rule ? `This tick the rule was ${PICK_RULES[rule] ?? rule}.` : 'This trace has no pick rule.'
    },
  },
  {
    id: 'primitive',
    term: 'primitive',
    aliases: ['primitives'],
    meaning:
      'A one-step action the motor can press directly: the moves, turns, shoot, use, the weapon switches and the two strafe-and-shoot combinations, thirteen in all. Every macro is a sequence of them, and the 12-number encoding counts them.',
    see: [
      { screen: 'tick', panel: 'motor' },
      { screen: 'menu', panel: 'encoding' },
    ],
    code: 'actions.py · PRIMITIVE_ACTION_IDS',
  },
  {
    id: 'proposal',
    term: 'proposal',
    aliases: ['proposals', 'proposed'],
    meaning:
      'What the slow worker returns: a JSON macro with id, description, primitives, preconditions, maximum duration and termination condition. It is text until it parses and passes the admission gate.',
    see: [{ screen: 'menu', panel: 'proposal' }],
    code: 'admission.py · MacroActionProposal',
  },
  {
    id: 'recording',
    term: 'recording',
    aliases: ['recordings', 'bundle', 'episode bundle'],
    meaning:
      'One folder per episode that the app reads: episode.json, ticks.jsonl, proposals.jsonl, the frames, and the training run’s metrics, evaluation, macros and trust when present. Written by python -m system1_doom.export.',
    see: [{ tab: 'recording', label: 'This recording' }],
    code: 'export.py · record_bundle',
  },
  {
    id: 'reflex',
    term: 'reflex',
    aliases: ['reflexes'],
    meaning:
      'A fixed aiming correction the motor adds while pressing a plan: turning to centre the target before firing, tracking it while strafing, steering onto a pickup. Reflexes never change the plan.',
    see: [{ screen: 'tick', panel: 'motor' }],
    code: 'motor.py · TacticalMotor.burst',
  },
  {
    id: 'replay-buffer',
    term: 'replay buffer',
    aliases: ['replay', 'transitions', 'transition'],
    meaning:
      'Where every tick’s transition is filed for the learner, up to 100,000. Training draws batches of 256 between episodes, 200 gradient steps each time.',
    see: [{ screen: 'learning', panel: 'curves' }, { screen: 'overview' }],
    code: 'learning.py · ReplayBuffer',
  },
  {
    id: 'reward',
    term: 'reward',
    aliases: ['rewards', 'module reward', 'module rewards'],
    meaning:
      'The game’s score for a tick (the episode reward sums them) and, for learning, each module’s own reward by the formula the Five rewards explanation states: five module rewards, never one shared.',
    see: [
      { screen: 'tick', panel: 'outcome' },
      { screen: 'learning', panel: 'anatomy' },
    ],
    code: 'features.py · module_rewards',
  },
  {
    id: 'sandbox',
    term: 'sandbox',
    aliases: ['sandbox rollout'],
    meaning:
      'The admission gate’s bounded rollout of the proposed macro from the state at the request. It fails only a predicted death (survival probability 0) from a state above 25 health.',
    see: [{ screen: 'menu', panel: 'gate' }],
    code: 'admission.py · ProposalAdmissionPipeline.evaluate_and_admit',
  },
  {
    id: 'scenario-and-seed',
    term: 'scenario and seed',
    aliases: ['scenario', 'seed', 'seeded', 'seeds'],
    meaning:
      'The scenario is the ViZDoom level, deadly corridor in both recordings; the seed fixes its randomness, so two brains with the same seed face the same episode.',
    see: [
      { tab: 'recording', label: 'This recording' },
      { screen: 'learning', panel: 'headtohead' },
    ],
    code: 'vizdoom_env.py · ViZDoomBridge.restart_episode',
    now: ({ meta }) => `${prettyId(meta.scenario.replace('.cfg', ''))}, seed ${meta.seed}.`,
  },
  {
    id: 'strategy-archive',
    term: 'strategy archive',
    aliases: ['archive', 'strategy', 'strategies', 'steering'],
    meaning:
      'Twelve slots of remembered action sequences, each with a running reward (α 0.3) and a success count; when it is full, the slot with the lowest reward + 5 × successes among those not active is evicted. After each tick, steering chooses among its four options with that tick’s pressure, and from the next tick the legal actions of the active strategy’s sequence get +0.15 in the arbiter’s score.',
    see: [
      { screen: 'hierarchy', label: 'Hierarchy (the steering level)' },
      { screen: 'tick', panel: 'outcome' },
    ],
    code: 'archive.py · StrategyArchive',
  },
  {
    id: 'template',
    term: 'template',
    aliases: ['templates', 'fallback template'],
    meaning:
      'The slow worker’s fallback when Codex is off or times out: a deterministic macro written from the request. Both recordings used templates.',
    see: [{ screen: 'menu', panel: 'proposal' }],
    code: 'llm_worker.py · SlowLLMWorker._fallback_template_proposal',
  },
]

/** Entries by id. */
export const GLOSSARY_BY_ID: Record<string, GlossaryEntry> = Object.fromEntries(GLOSSARY.map((e) => [e.id, e]))
