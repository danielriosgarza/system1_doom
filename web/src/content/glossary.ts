// The glossary: every word the screens lean on, with where to see it and where the code keeps it. It carries
// exactly the terms of the documentation's glossary (docs/DOCUMENTATION.md, section 18), and a test keeps the
// two in step.
import type { Screen } from '../store'
import type { PanelId } from './explainers'

/** Where to see a term: a screen, and the panel on it to flash. */
export interface SeeLink {
  screen: Screen
  panel?: PanelId
  label: string
}

export interface GlossaryEntry {
  id: string
  term: string
  /** Other words that link here from the copy: whole words, any case. Never one letter, never a bare “gate”. */
  aliases: string[]
  meaning: string
  see: SeeLink[]
  /** `file.py · Name`: where in the package it lives. */
  code: string
}

export const GLOSSARY: GlossaryEntry[] = [
  {
    id: 'd1-ultra',
    term: 'd1-ultra',
    aliases: [],
    meaning:
      'Liquid AI’s decision model. It answers typed questions with distributions: a probability (noul) or a choice over a finite list. Every decision here is one of its answers: the senses, the central, the admit instance, System 2’s reflectors and central, and the trial judge are each one call.',
    see: [{ screen: 'instances', panel: 'answers', label: 'its answers at this decision' }],
    code: 'd1_client.py · D1UltraClient',
  },
  {
    id: 'system-1',
    term: 'System 1',
    aliases: [],
    meaning:
      'The fast system that decides every action: five senses, then the central, then Act, once per tick. It never waits for System 2.',
    see: [{ screen: 'watch', panel: 'strip', label: 'the strip on Watch' }],
    code: 'system1.py · System1',
  },
  {
    id: 'system-2',
    term: 'System 2',
    aliases: ['slow system'],
    meaning:
      'The slow system, on its own thread: it reads the history and changes the configuration one change at a time. Its reflectors propose, its central chooses one change or none, a scope change must pass the history test, and every change is a trial that the judge keeps or reverts.',
    see: [{ screen: 'slow', panel: 'versions', label: 'the slow system' }],
    code: 'system2.py · System2',
  },
  {
    id: 'instance',
    term: 'instance',
    aliases: ['instances'],
    meaning:
      'One d1-ultra call with its own scope and its own finite questions. Its instructions name its concern and say it sees only the evidence given; they never say how to weigh anything.',
    see: [{ screen: 'instances', panel: 'evidence', label: 'The instances' }],
    code: 'instance.py · run_instance',
  },
  {
    id: 'sense',
    term: 'sense',
    aliases: ['senses'],
    meaning:
      'One of the five System 1 instances (survival, combat, navigation, resource, goal). Each sees only its scope and answers three questions: speak (a probability), action (over the legal menu) and reason (over its own reasons).',
    see: [{ screen: 'watch', panel: 'strip', label: 'the five sense rows' }],
    code: 'senses.py · run_senses',
  },
  {
    id: 'central',
    term: 'central',
    aliases: ['central instance'],
    meaning:
      'The instance that chooses the action the agent executes: one choice over the legal menu, after hearing the messages, each sense’s relevance record and the exploration level. System 2 has a central of its own, which chooses one configuration change or none.',
    see: [{ screen: 'instances', panel: 'answers', label: 'its choice distribution' }],
    code: 'system1.py · System1.tick',
  },
  {
    id: 'channel',
    term: 'channel',
    aliases: ['channels', 'evidence channel'],
    meaning:
      'One named piece of evidence rendered as plain text under a [name] header: vitals, threats, pickups, projections, values and so on, eighteen in all. Messages, relevance and exploration are for the central only.',
    see: [{ screen: 'instances', panel: 'evidence', label: 'the state text, verbatim' }],
    code: 'evidence.py · render_scope',
  },
  {
    id: 'scope',
    term: 'scope',
    aliases: ['scopes'],
    meaning:
      'The channels an instance is shown, at most seven, always with the menu. Whatever a scope leaves out never reaches the instance. System 2 widens or narrows a scope one channel at a time.',
    see: [
      { screen: 'instances', panel: 'evidence', label: 'the scope chips' },
      { screen: 'slow', panel: 'configuration-changes', label: 'scopes at start and end' },
    ],
    code: 'configuration.py · SenseConfig',
  },
  {
    id: 'message',
    term: 'message',
    aliases: ['messages'],
    meaning:
      'What a sense that spoke sends the central: its action, its reason and its strength, one line in the central’s messages channel. A silent or missed sense sends nothing.',
    see: [{ screen: 'instances', panel: 'answers', label: 'the messages the central heard' }],
    code: 'evidence.py · Message',
  },
  {
    id: 'strength',
    term: 'strength',
    aliases: [],
    meaning:
      'A message’s strength: the sense’s speak probability, unscaled. A sense speaks when it is 0.5 or more, d1-ultra’s own yes, not a tuned threshold.',
    see: [{ screen: 'watch', panel: 'strip', label: 'the strength bars' }],
    code: 'senses.py · message_of',
  },
  {
    id: 'relevance',
    term: 'relevance',
    aliases: ['relevance ledger', 'ledger', 'relevance record'],
    meaning:
      'Each sense’s track record per situation: how often it spoke, was followed and paid off, was overruled and whether the chosen action paid off, and its mean strength either way. The central is shown it as counts; nothing in it is multiplied into a decision.',
    see: [
      { screen: 'slow', panel: 'ledger', label: 'the ledger per sense and situation' },
      { screen: 'learning', panel: 'relevance-episodes', label: 'over episodes' },
    ],
    code: 'relevance.py · update_ledger',
  },
  {
    id: 'paid-off',
    term: 'paid off',
    aliases: ['n-step return', 'paid-off', 'pays off'],
    meaning:
      'A decision paid off when its n-step return was positive: the game reward of it and the next seven decisions, discounted by 0.9 a step, cut at the episode’s end. The ledger, the history test and the trials all use it.',
    see: [{ screen: 'slow', panel: 'ledger', label: 'the ledger’s formula' }],
    code: 'features.py · n_step_returns',
  },
  {
    id: 'configuration',
    term: 'configuration',
    aliases: ['configurations', 'configuration version'],
    meaning:
      'Everything System 2 may change, as versioned data: each instance’s scope, the exploration level, the active strategy and the admitted macros. Version 1 is the design’s; each change makes the next version, taking effect only at a tick boundary.',
    see: [
      { screen: 'watch', panel: 'config-line', label: 'the configuration line' },
      { screen: 'slow', panel: 'versions', label: 'every version' },
    ],
    code: 'configuration.py · Configuration',
  },
  {
    id: 'miss',
    term: 'miss',
    aliases: ['missed', 'misses'],
    meaning:
      'An answer that did not come or could not be read: a timeout, a failed call, rate limits outlasting the budget, an option off the menu, or malformed probabilities. Nothing stands in for it: a missed sense is silent, a missed central holds no keys.',
    see: [{ screen: 'instances', panel: 'answers', label: 'a miss and its raw answer' }],
    code: 'instance.py · run_instance',
  },
  {
    id: 'pick',
    term: 'pick',
    aliases: ['picks'],
    meaning:
      'How the central’s answer becomes the action: top under the exploit level (its highest probability, a tie to the first in menu order), drawn under explore (from its own distribution, with a seeded generator), or missed (no keys).',
    see: [{ screen: 'watch', panel: 'strip', label: 'the central row' }],
    code: 'system1.py · pick_action',
  },
  {
    id: 'exploration-level',
    term: 'exploration level',
    aliases: ['exploit level', 'explore level'],
    meaning:
      'Part of the configuration: exploit or explore. The central is told the level in its exploration channel; under explore its action is drawn from its own distribution. There is no temperature and no bonus.',
    see: [{ screen: 'watch', panel: 'strip', label: 'the central row' }],
    code: 'configuration.py · Configuration',
  },
  {
    id: 'reflector',
    term: 'reflector',
    aliases: ['reflectors'],
    meaning:
      'One of System 2’s nine instances: five sense auditors, a central auditor, the menu, strategy and exploration reflectors. Each reads history channels over three windows and may propose one change from a finite menu the bounds have filtered.',
    see: [{ screen: 'slow', panel: 'reflectors', label: 'each reflector’s evidence and answers' }],
    code: 'reflectors.py · ReflectorSpec',
  },
  {
    id: 'cycle',
    term: 'cycle',
    aliases: ['cycles'],
    meaning:
      'One round of System 2: every few decisions, or at an episode’s end, and only while no trial is in flight. Its reflectors are asked, its central chooses, and the cycle’s record keeps everything each of them saw and answered.',
    see: [{ screen: 'slow', panel: 'cycles', label: 'every cycle' }],
    code: 'reflection.py · ReflectionTrace',
  },
  {
    id: 'history-test',
    term: 'history test',
    aliases: ['history tests'],
    meaning:
      'What stands between a scope change and play: the instance is asked again, under the new scope, on stored ticks it already answered, drawn by outcome (bad, good, rest). The change passes when its composite is 0.05 above the old and no metric falls by more than 0.10.',
    see: [{ screen: 'slow', panel: 'history-test', label: 'the test’s whole table' }],
    code: 'history_test.py · run_history_test',
  },
  {
    id: 'trial',
    term: 'trial',
    aliases: ['trials'],
    meaning:
      'Every change that takes effect is a trial, one at a time: observed for a set number of decisions against the same number before it, then kept or reverted. A revert restores the previous configuration with the version bumped.',
    see: [
      { screen: 'slow', panel: 'trial', label: 'the before-and-during table' },
      { screen: 'watch', panel: 'config-line', label: 'the trial in flight' },
    ],
    code: 'system2.py · trial_table',
  },
  {
    id: 'judge',
    term: 'judge',
    aliases: ['trial judge'],
    meaning:
      'The instance that ends a trial: shown the before-and-during table, it answers keep or revert. A missed judge extends the trial; the safety bound may revert first without asking it.',
    see: [{ screen: 'slow', panel: 'trial', label: 'its answer' }],
    code: 'reflection.py · TrialRecord',
  },
  {
    id: 'cooling',
    term: 'cooling',
    aliases: [],
    meaning:
      'The rest after a verdict: no change to the changed instance is offered for a set number of decisions; after a menu, strategy or level change, System 2 as a whole rests.',
    see: [{ screen: 'slow', panel: 'reflectors', label: 'skipped and blocked reflectors' }],
    code: 'reflectors.py · BoundsState',
  },
  {
    id: 'admit-instance',
    term: 'admit instance',
    aliases: ['admit'],
    meaning:
      'The instance that decides whether a proposed macro enters the menu, after it has parsed, used only legal primitives and survived the sandbox: one probability, yes at 0.5 or more.',
    see: [{ screen: 'menu', panel: 'admit', label: 'its evidence and answer' }],
    code: 'instance.py · run_admit',
  },
  {
    id: 'action',
    term: 'action',
    aliases: ['actions', 'ActionSpec', 'legal menu'],
    meaning:
      'The only thing that can be executed: a named, bounded plan of primitives with preconditions and a duration cap. The legal menu of a tick is the actions whose preconditions hold; every choice among actions is over exactly that menu.',
    see: [{ screen: 'menu', panel: 'menu-now', label: 'the menu' }],
    code: 'actions.py · ActionSpec',
  },
  {
    id: 'macro',
    term: 'macro',
    aliases: ['macros', 'macro-action'],
    meaning:
      'An action of several primitives. Some are built in; the slow path can propose new ones when System 2 asks, and the admit instance decides whether each enters the configuration.',
    see: [{ screen: 'menu', panel: 'proposals', label: 'proposals' }],
    code: 'actions.py · ActionSpec',
  },
  {
    id: 'context-signature',
    term: 'context signature',
    aliases: ['context signatures', 'situation'],
    meaning:
      'A coarse key for the situation, like hp:healthy|ammo:stocked|enemies:2:mid|dmg:clear|pickup:pickup_visible. It keys the relevance ledger, the novelty counts and the value networks’ tried counts.',
    see: [{ screen: 'slow', panel: 'ledger', label: 'the ledger by situation' }],
    code: 'state.py · WorldState.context_signature',
  },
  {
    id: 'projection',
    term: 'projection',
    aliases: ['projections'],
    meaning:
      'A rough rollout of one legal action by a hand-written simulator: expected value, damage in and out, survival, progress. Shown in the projections channel and labelled as a projection, not the game.',
    see: [{ screen: 'instances', panel: 'evidence', label: 'the projections channel' }],
    code: 'simulator.py · ProjectedOutcome',
  },
  {
    id: 'value-network',
    term: 'value network',
    aliases: ['value networks'],
    meaning:
      'Five small networks trained between episodes on the agent’s own play, one per sense’s reward. Their predicted returns are evidence in the values channel, with how often each action was tried in that situation; they decide nothing.',
    see: [{ screen: 'learning', panel: 'values', label: 'the values at this decision' }],
    code: 'learning.py · Learner',
  },
  {
    id: 'network-share',
    term: 'network share',
    aliases: [],
    meaning:
      'How familiar play has become to the value networks: the mean of n / (n + 25) over the tries seen in training. A report only; it weighs nothing.',
    see: [{ screen: 'learning', panel: 'trust', label: 'the tries behind the values' }],
    code: 'learning.py · Learner.network_share',
  },
  {
    id: 'tick',
    term: 'tick',
    aliases: ['ticks'],
    meaning:
      'One decision: the state, the evidence, five senses, the central, and the action’s primitives over 8 game frames. Not one ViZDoom game tic.',
    see: [{ screen: 'watch', label: 'Watch' }],
    code: 'controller.py · DoomDecisionController.step',
  },
  {
    id: 'bundle',
    term: 'bundle',
    aliases: ['bundles', 'recording', 'recordings'],
    meaning:
      'One recorded episode as this site reads it: episode.json, every tick in ticks.jsonl, System 2’s records in reflections.jsonl, the proposals, the relevance ledger, the frames.',
    see: [{ screen: 'reference', panel: 'provenance', label: 'how this recording was made' }],
    code: 'export.py · record_bundle',
  },
  {
    id: 'live-episode',
    term: 'live episode',
    aliases: ['live mode'],
    meaning:
      'An episode played right now by python -m system1_doom.serve and streamed tick by tick, with System 2’s records as they happen; when it ends it is a bundle like any recording.',
    see: [{ screen: 'watch', label: 'Watch, following live play' }],
    code: 'serve.py · LiveHub',
  },
  {
    id: 'slow-path',
    term: 'slow path',
    aliases: [],
    meaning:
      'The worker that writes a new macro when System 2 asks (from templates, or Codex), and the bounds and admit instance it must pass. It never blocks a tick, and a macro joins the menu only at a tick boundary.',
    see: [{ screen: 'menu', panel: 'proposals', label: 'proposals and their stages' }],
    code: 'llm_worker.py · SlowLLMWorker',
  },
]

export const GLOSSARY_BY_ID: Record<string, GlossaryEntry> = Object.fromEntries(GLOSSARY.map((e) => [e.id, e]))

/** The words the old architecture used, which no screen shows any more: one line on the Reference screen. */
export const REMOVED_TERMS = [
  'arbiter',
  'module',
  'gate network',
  'budget mode',
  'committed pick',
  'exploration pressure',
]
