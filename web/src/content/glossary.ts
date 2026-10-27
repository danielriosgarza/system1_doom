// The glossary: every term the screens use, with where to see it and where the code keeps it. It carries
// exactly the terms of the documentation's glossary (docs/DOCUMENTATION.md, section 18), and a test keeps the
// two in step. Each entry belongs to one solution's screens or to both; a term both use in different senses has
// its rule-tree meaning beside the senses and central's.
import type { Screen, Solution } from '../store'
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
  /** The solutions whose screens use the term; the senses and central's alone when not given. */
  solutions?: Solution[]
  /** What the term means on the rule tree's screens, where that differs. */
  rules?: Pick<GlossaryEntry, 'meaning' | 'see' | 'code'>
}

/** An entry as one solution's screens show it. */
export interface ShownEntry {
  id: string
  term: string
  aliases: string[]
  meaning: string
  see: SeeLink[]
  code: string
}

/** Whether a solution's screens use an entry. */
export const usedBy = (entry: GlossaryEntry, solution: Solution): boolean =>
  (entry.solutions ?? ['senses']).includes(solution)

/** An entry in the words of one solution. */
export function shown(entry: GlossaryEntry, solution: Solution): ShownEntry {
  const own = solution === 'rules' && entry.rules ? entry.rules : entry
  return { id: entry.id, term: entry.term, aliases: entry.aliases, meaning: own.meaning, see: own.see, code: own.code }
}

/** The glossary of one solution's screens, in order. */
export const glossaryOf = (solution: Solution): ShownEntry[] =>
  GLOSSARY.filter((e) => usedBy(e, solution)).map((e) => shown(e, solution))

export const GLOSSARY: GlossaryEntry[] = [
  {
    id: 'd1-ultra',
    term: 'd1-ultra',
    aliases: [],
    meaning:
      'Liquid AI’s decision model. It is asked typed questions and answers each with a probability distribution: a single probability for a yes-or-no question (called a noul), or probabilities over a fixed list of options (a choice). Every decision on this site is one of its answers. The five senses, the central instance, the admit instance, System 2’s reflectors and central instance, and the trial judge are each one call to it.',
    see: [{ screen: 'instances', panel: 'answers', label: 'its answers at this decision' }],
    code: 'd1_client.py · D1UltraClient',
  },
  {
    id: 'jev',
    term: 'Jev',
    aliases: [],
    meaning:
      'TypeSafe’s decision model. It answers the same typed questions as d1-ultra in the same form, so a recording can be played by it instead: every instance of both systems then makes its calls to Jev, with the same evidence and the same questions. The screen goes to it as an image asset, and its cost is counted at its published price per input token, since its usage report names none. Each recording’s card, the top bar and How this recording was made say which model played it.',
    see: [{ screen: 'reference', panel: 'provenance', label: 'which model played this recording' }],
    code: 'd1_client.py · Decider',
    solutions: ['senses', 'rules'],
    rules: {
      meaning:
        'TypeSafe’s decision model. Each question of the rule tree is one call to it: a multiple-choice question sent with the state as text and the screen as an image, answered with a probability for each option. The option with the highest probability is its answer. When a focus list has only one item, there is nothing to choose and Jev is not asked.',
      see: [{ screen: 'questions', panel: 'rt-answer', label: 'its answers at this decision' }],
      code: 'ruletree/walk.py · Jev',
    },
  },
  {
    id: 'system-1',
    term: 'System 1',
    aliases: [],
    meaning:
      'The fast system that makes every decision, once per tick: the five senses, then the central instance, then Act. It never waits for System 2.',
    see: [{ screen: 'watch', panel: 'strip', label: 'the strip on Watch' }],
    code: 'system1.py · System1',
  },
  {
    id: 'system-2',
    term: 'System 2',
    aliases: ['slow system'],
    meaning:
      'The slow system. It runs on its own thread, reads the history of decisions and changes the configuration one change at a time. Its reflectors propose changes, its central instance chooses one or none, a scope change must pass the history test, and every change runs as a trial that the trial judge keeps or reverts.',
    see: [{ screen: 'slow', panel: 'versions', label: 'the slow system' }],
    code: 'system2.py · System2',
  },
  {
    id: 'instance',
    term: 'instance',
    aliases: ['instances'],
    meaning:
      'One d1-ultra call with its own scope of evidence and its own fixed set of questions. Its instructions name its concern and state that it sees only the evidence given. They never say how to weigh anything.',
    see: [{ screen: 'instances', panel: 'evidence', label: 'The instances' }],
    code: 'instance.py · run_instance',
  },
  {
    id: 'sense',
    term: 'sense',
    aliases: ['senses'],
    meaning:
      'One of the five System 1 instances: survival, combat, navigation, resource and goal. Each is shown only its own scope and answers three questions: speak (a probability), action (a choice over the legal menu) and reason (a choice over its own list of reasons).',
    see: [{ screen: 'watch', panel: 'strip', label: 'the five sense rows' }],
    code: 'senses.py · run_senses',
  },
  {
    id: 'central',
    term: 'central',
    aliases: ['central instance'],
    meaning:
      'The instance that chooses the action the agent executes: one choice over the legal menu, after receiving the senses’ messages, each sense’s relevance record and the exploration level. System 2 has a central instance of its own, which chooses one configuration change or none.',
    see: [{ screen: 'instances', panel: 'answers', label: 'its choice distribution' }],
    code: 'system1.py · System1.tick',
  },
  {
    id: 'channel',
    term: 'channel',
    aliases: ['channels', 'evidence channel'],
    meaning:
      'One named piece of evidence, rendered as plain text under a [name] header: vitals, threats, pickups, projections, values and so on, eighteen in all. Three of them, messages, relevance and exploration, can be shown only to the central instance.',
    see: [{ screen: 'instances', panel: 'evidence', label: 'the evidence text, exactly as sent' }],
    code: 'evidence.py · render_scope',
    solutions: ['senses', 'rules'],
    rules: {
      meaning:
        'One named part of the state text, under a [name] header, always in the same order: goal, vitals, threats, incoming, outgoing, pickups, landmarks, geometry, position, progress and history, and focus after a focus question.',
      see: [{ screen: 'questions', panel: 'rt-sent', label: 'the state text, exactly as sent' }],
      code: 'ruletree/game.py · Game.observe',
    },
  },
  {
    id: 'scope',
    term: 'scope',
    aliases: ['scopes'],
    meaning:
      'The channels an instance is shown: at most seven, always including the menu. Whatever a scope leaves out never reaches the instance. System 2 can widen or narrow a scope by one channel at a time.',
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
      'What a sense that spoke sends to the central instance: its recommended action, its reason and its strength, as one line in the central instance’s messages channel. A silent or missed sense sends nothing.',
    see: [{ screen: 'instances', panel: 'answers', label: 'the messages the central instance received' }],
    code: 'evidence.py · Message',
  },
  {
    id: 'target',
    term: 'target',
    aliases: ['targets'],
    meaning:
      'What the motor aims or walks at, chosen by a sense: the combat sense answers which visible enemy the aim locks onto, the resource sense which remembered pickup a walk goes to, each as a choice over the candidates its evidence shows. With one candidate no question is asked and that one is the target. A sense that missed leaves its target empty, and the motor then has nothing to aim at; it never picks one of its own.',
    see: [
      { screen: 'instances', panel: 'answers', label: 'a sense’s target answer' },
      { screen: 'watch', panel: 'strip', label: 'the targets on the Act row' },
    ],
    code: 'system1.py · targets_of',
  },
  {
    id: 'strength',
    term: 'strength',
    aliases: [],
    meaning:
      'A message’s strength: the sense’s speak probability, unchanged. A sense sends a message when that probability is 0.5 or more. That is d1-ultra’s own answer, not a tuned threshold.',
    see: [{ screen: 'watch', panel: 'strip', label: 'the strength bars' }],
    code: 'senses.py · message_of',
  },
  {
    id: 'relevance',
    term: 'relevance',
    aliases: ['relevance ledger', 'ledger', 'relevance record'],
    meaning:
      'Each sense’s track record per situation: how often it sent a message, how often the central instance followed it and whether that paid off, how often it was overruled and whether the chosen action paid off, and its mean strength in each case. The central instance is shown these as plain counts. Nothing in them is multiplied into a decision.',
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
      'A decision paid off when its n-step return was positive: the game reward for that decision and the next seven, each discounted by 0.9 per step, cut off at the end of the episode. The ledger, the history test and the trials all use this measure.',
    see: [{ screen: 'slow', panel: 'ledger', label: 'the ledger’s formula' }],
    code: 'features.py · n_step_returns',
  },
  {
    id: 'configuration',
    term: 'configuration',
    aliases: ['configurations', 'configuration version'],
    meaning:
      'Everything System 2 may change, stored as versioned data: each instance’s scope, the exploration level, the active strategy and the admitted macros. Version 1 is the design’s starting point. Each change produces the next version and takes effect only between two decisions.',
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
      'An answer that did not arrive or could not be read: a timeout, a failed call, rate limits that outlasted the retries, an option outside the menu, or malformed probabilities. Nothing replaces it. A missed sense sends no message; a missed central instance presses no keys.',
    see: [{ screen: 'instances', panel: 'answers', label: 'a miss and its raw answer' }],
    code: 'instance.py · run_instance',
    solutions: ['senses', 'rules'],
    rules: {
      meaning:
        'A call that failed, ran out of time, or answered with an option that was not offered. The walk stops at the rule it has reached and that rule’s action is played. Nothing replaces the missing answer.',
      see: [{ screen: 'questions', panel: 'rt-answer', label: 'Jev’s answers at this decision' }],
      code: 'ruletree/walk.py · decide',
    },
  },
  {
    id: 'pick',
    term: 'pick',
    aliases: ['picks'],
    meaning:
      'How the central instance’s answer becomes the executed action. Under the exploit level, the action with the highest probability is taken (a tie goes to the first in menu order). Under the explore level, an action is drawn at random from the instance’s own distribution with a seeded generator. When the call missed, no keys are pressed.',
    see: [{ screen: 'watch', panel: 'strip', label: 'the central row' }],
    code: 'system1.py · pick_action',
  },
  {
    id: 'exploration-level',
    term: 'exploration level',
    aliases: ['exploit level', 'explore level'],
    meaning:
      'Part of the configuration: exploit or explore. The central instance is told the level in its exploration channel. Under explore, the executed action is drawn at random from the central instance’s own distribution instead of taking the top one. There is no temperature setting and no exploration bonus.',
    see: [{ screen: 'watch', panel: 'strip', label: 'the central row' }],
    code: 'configuration.py · Configuration',
  },
  {
    id: 'reflector',
    term: 'reflector',
    aliases: ['reflectors'],
    meaning:
      'One of System 2’s nine instances: an auditor for each of the five senses, an auditor for the central instance, and the menu, strategy and exploration reflectors. Each reads history channels over three time windows and may propose one change from a fixed list that the bounds have filtered first.',
    see: [{ screen: 'slow', panel: 'reflectors', label: 'each reflector’s evidence and answers' }],
    code: 'reflectors.py · ReflectorSpec',
  },
  {
    id: 'cycle',
    term: 'cycle',
    aliases: ['cycles'],
    meaning:
      'One round of System 2: after every 20 new decisions, or at the end of an episode, and only while no trial is in progress. Its reflectors are called, its central instance chooses, and the cycle’s record keeps everything each of them was shown and answered.',
    see: [{ screen: 'slow', panel: 'cycles', label: 'every cycle' }],
    code: 'reflection.py · ReflectionTrace',
  },
  {
    id: 'history-test',
    term: 'history test',
    aliases: ['history tests'],
    meaning:
      'The check between a scope change and play: the instance is asked again, under the new scope, on 24 stored decisions it already answered, chosen by outcome (bad, good and the rest). The change passes when its composite score is at least 0.05 above the old one and no single metric falls by more than 0.10.',
    see: [{ screen: 'slow', panel: 'history-test', label: 'the test’s whole table' }],
    code: 'history_test.py · run_history_test',
  },
  {
    id: 'trial',
    term: 'trial',
    aliases: ['trials'],
    meaning:
      'Every change that takes effect is a trial, one at a time: it is observed for a set number of decisions (60 by default) and compared with the same number of decisions before it, then kept or reverted. A revert restores the previous configuration under a new version number.',
    see: [
      { screen: 'slow', panel: 'trial', label: 'the before-and-during table' },
      { screen: 'watch', panel: 'config-line', label: 'the trial in progress' },
    ],
    code: 'system2.py · trial_table',
  },
  {
    id: 'judge',
    term: 'judge',
    aliases: ['trial judge'],
    meaning:
      'The instance that ends a trial. It is shown the before-and-during table and answers keep or revert. If it misses, the trial is extended and the judge is asked again; the safety bound may revert a scope change earlier without asking it.',
    see: [{ screen: 'slow', panel: 'trial', label: 'its answer' }],
    code: 'reflection.py · TrialRecord',
  },
  {
    id: 'cooling',
    term: 'cooling',
    aliases: [],
    meaning:
      'The rest period after a verdict: for a set number of decisions (60 by default), no change to the instance that was changed is offered. After a menu, strategy or level change, System 2 as a whole rests.',
    see: [{ screen: 'slow', panel: 'reflectors', label: 'skipped and blocked reflectors' }],
    code: 'reflectors.py · BoundsState',
  },
  {
    id: 'admit-instance',
    term: 'admit instance',
    aliases: ['admit'],
    meaning:
      'The instance that decides whether a proposed macro enters the menu, after the macro has parsed, used only known primitives and passed the sandbox simulation. It answers one probability; 0.5 or more is a yes.',
    see: [{ screen: 'menu', panel: 'admit', label: 'its evidence and answer' }],
    code: 'instance.py · run_admit',
  },
  {
    id: 'action',
    term: 'action',
    aliases: ['actions', 'ActionSpec', 'legal menu'],
    meaning:
      'The only thing that can be executed: a named, bounded sequence of primitive moves with preconditions and a duration cap. The legal menu at a tick is the set of actions whose preconditions hold, and every choice among actions is over exactly that menu.',
    see: [{ screen: 'menu', panel: 'menu-now', label: 'the menu' }],
    code: 'actions.py · ActionSpec',
  },
  {
    id: 'macro',
    term: 'macro',
    aliases: ['macros', 'macro-action'],
    meaning:
      'An action made of several primitive moves. Some are built in. The slow path can propose new ones when System 2 requests them, and the admit instance decides whether each one enters the configuration.',
    see: [{ screen: 'menu', panel: 'proposals', label: 'proposals' }],
    code: 'actions.py · ActionSpec',
  },
  {
    id: 'context-signature',
    term: 'context signature',
    aliases: ['context signatures', 'situation'],
    meaning:
      'A coarse description of the situation, such as hp:healthy|ammo:stocked|enemies:2:mid|dmg:clear|pickup:pickup_visible. It is the key for the relevance ledger, the novelty counts and the value networks’ tried counts.',
    see: [{ screen: 'slow', panel: 'ledger', label: 'the ledger by situation' }],
    code: 'state.py · WorldState.context_signature',
  },
  {
    id: 'projection',
    term: 'projection',
    aliases: ['projections'],
    meaning:
      'A rough simulation of one legal action by a hand-written simulator: expected value, damage taken and dealt, survival, progress. It is shown in the projections channel and labelled as a projection, not the game.',
    see: [{ screen: 'instances', panel: 'evidence', label: 'the projections channel' }],
    code: 'simulator.py · ProjectedOutcome',
  },
  {
    id: 'value-network',
    term: 'value network',
    aliases: ['value networks'],
    meaning:
      'One of five small neural networks trained between episodes on the agent’s own play, one per sense’s reward. Their predicted returns are evidence in the values channel, together with how often each action was tried in that situation. They decide nothing.',
    see: [{ screen: 'learning', panel: 'values', label: 'the values at this decision' }],
    code: 'learning.py · Learner',
  },
  {
    id: 'network-share',
    term: 'network share',
    aliases: [],
    meaning:
      'A measure of how familiar play has become to the value networks: the mean of n / (n + 25) over the action tries seen in training. It is reported only; it weighs nothing.',
    see: [{ screen: 'learning', panel: 'trust', label: 'the tries behind the values' }],
    code: 'learning.py · Learner.network_share',
  },
  {
    id: 'tick',
    term: 'tick',
    aliases: ['ticks'],
    meaning:
      'One decision: the game state, the evidence, the five senses, the central instance, and the chosen action’s primitives executed over 8 game frames. Not the same as one ViZDoom game tic.',
    see: [{ screen: 'watch', label: 'Watch' }],
    code: 'controller.py · DoomDecisionController.step',
  },
  {
    id: 'bundle',
    term: 'bundle',
    aliases: ['bundles', 'recording', 'recordings'],
    meaning:
      'One recorded episode in the form this site reads: episode.json, every tick in ticks.jsonl, System 2’s records in reflections.jsonl, the slow path’s proposals, the relevance ledger and the video frames.',
    see: [{ screen: 'reference', panel: 'provenance', label: 'how this recording was made' }],
    code: 'export.py · record_bundle',
    solutions: ['senses', 'rules'],
    rules: {
      meaning:
        'One recorded game in the form this site reads. A rule-tree recording holds episode.json, every decision in decisions.jsonl with each question, its options and Jev’s answer, the tree it was played with, the record of how that tree was written, and the video frames.',
      see: [{ screen: 'reference', panel: 'rt-provenance', label: 'how this recording was made' }],
      code: 'ruletree/bundle.py · record_episode',
    },
  },
  {
    id: 'live-episode',
    term: 'live episode',
    aliases: ['live mode'],
    meaning:
      'An episode being played right now by python -m system1_doom.serve and streamed to this app one tick at a time, with System 2’s records as they are written. When it ends it becomes a recording like any other.',
    see: [{ screen: 'watch', label: 'Watch, following live play' }],
    code: 'serve.py · LiveHub',
  },
  {
    id: 'slow-path',
    term: 'slow path',
    aliases: [],
    meaning:
      'The background worker that writes a new macro when System 2 requests one (from templates, or with the Codex CLI), together with the checks and the admit instance the macro must pass. It never delays a decision, and a macro joins the menu only between two decisions.',
    see: [{ screen: 'menu', panel: 'proposals', label: 'proposals and their stages' }],
    code: 'llm_worker.py · SlowLLMWorker',
  },
  // The rule tree's own terms.
  {
    id: 'rule-tree',
    term: 'rule tree',
    aliases: ['tree of rules'],
    meaning:
      'The second way this package plays: a tree of rules. At every decision the program walks it, asking Jev at each level which rule is true. A tree is a file: its rules, the questions that pick a focus, its skills, and for each rule the soft loop added, the decision it was written for.',
    see: [{ screen: 'tree', panel: 'rt-outline', label: 'the whole tree' }],
    code: 'ruletree/tree.py · RuleTree',
    solutions: ['rules'],
  },
  {
    id: 'rule',
    term: 'rule',
    aliases: ['rules', 'exception', 'exceptions'],
    meaning:
      'A condition and an action. The walk goes into a rule when Jev picks its condition as true. A rule under another rule is an exception to it: when its condition is true as well, its action is played instead.',
    see: [{ screen: 'tree', panel: 'rt-rule', label: 'one rule and where it came from' }],
    code: 'ruletree/tree.py · RuleNode',
    solutions: ['rules'],
  },
  {
    id: 'condition',
    term: 'condition',
    aliases: ['conditions'],
    meaning:
      'A sentence about what the state shows, such as “The focus channel says the enemy is more than 400 units away.” Jev judges it, as one option of a question; the program never tests it.',
    see: [{ screen: 'questions', panel: 'rt-answer', label: 'the options of a question' }],
    code: 'ruletree/tree.py · RuleNode',
    solutions: ['rules'],
  },
  {
    id: 'walk',
    term: 'walk',
    aliases: [],
    meaning:
      'How the rule tree makes one decision. From the top of the tree, at each rule with rules under it, Jev is asked “Which of these is true right now?” and the walk moves into the rule it picks, until it picks none or reaches a rule with nothing under it. That rule’s action is played.',
    see: [{ screen: 'watch', panel: 'rt-walk', label: 'the questions at this decision' }],
    code: 'ruletree/walk.py · decide',
    solutions: ['rules'],
  },
  {
    id: 'focus',
    term: 'focus',
    aliases: [],
    meaning:
      'What the rules under a rule speak about: one item Jev picked from a list in the state, such as the visible enemy that is the biggest danger, or the landmark that is the goal. The questions after it are sent a [focus] channel that names it.',
    see: [{ screen: 'questions', panel: 'rt-sent', label: 'the [focus] channel' }],
    code: 'ruletree/walk.py · with_focus',
    solutions: ['rules'],
  },
  {
    id: 'skill',
    term: 'skill',
    aliases: ['skills'],
    meaning:
      'A set of rules any rule can use as its action. The aim skill’s rules each turn toward the focus by an amount that fits its angle; the rule that used the skill says what to do for the rest of the decision.',
    see: [{ screen: 'tree', panel: 'rt-outline', label: 'the aim skill' }],
    code: 'ruletree/tree.py · SkillCall',
    solutions: ['rules'],
  },
  {
    id: 'action-code',
    term: 'action code',
    aliases: ['action codes'],
    meaning:
      'Four characters, one for each group of keys held during a decision: walk (F forward, B backward), sidestep (L, R), turn (L, R) and fire (1), with 0 for none. F001 walks forward and fires. A sequence such as 00R0:3+0001:5 turns right for 3 tics, then fires for 5.',
    see: [{ screen: 'watch', panel: 'rt-walk', label: 'the Act row on Watch, which says it in words' }],
    code: 'ruletree/codes.py · segments',
    solutions: ['rules'],
  },
  {
    id: 'tic',
    term: 'tic',
    aliases: ['tics'],
    meaning: 'One step of the game clock. Doom runs at 35 tics a second, and a decision of the rule tree lasts 8 tics.',
    see: [{ screen: 'watch', panel: 'rt-walk', label: 'the Act row on Watch' }],
    code: 'ruletree/codes.py · segments',
    solutions: ['rules'],
  },
  {
    id: 'soft-loop',
    term: 'soft loop',
    aliases: [],
    meaning:
      'The part of the program that adds rules to a tree, between games. It plays the training seeds; for a game that went wrong, a rule writer proposes one rule. The check replays that game with and without the rule, and the gate plays every training seed with and without it. The rule is added only if it passes both. The shipped trees started from general-9, whose rules were written before the loop ran.',
    see: [{ screen: 'written', panel: 'rt-rounds', label: 'the record of how this tree was written' }],
    code: 'ruletree/loop.py · run_loop',
    solutions: ['rules'],
  },
  {
    id: 'rule-writer',
    term: 'rule writer',
    aliases: ['writer'],
    meaning:
      'The model that proposes rules in the soft loop: Claude or Codex. It reads a dossier of the game that went wrong and writes one rule, or a small group of rules, in plain words. It does not play: Jev judges every condition.',
    see: [{ screen: 'written', panel: 'rt-round', label: 'a proposal and its reason' }],
    code: 'ruletree/writers.py · Writer',
    solutions: ['rules'],
  },
  {
    id: 'cornerstone',
    term: 'cornerstone',
    aliases: ['cornerstones'],
    meaning:
      'The decision a rule was written for, kept with the rule: the seed, the actions that led there, the state text and the screen. Every later rule must leave that decision on the same route, or end its game no worse.',
    see: [{ screen: 'tree', panel: 'rt-rule', label: 'a rule’s cornerstone' }],
    code: 'ruletree/tree.py · Cornerstone',
    solutions: ['rules'],
  },
  {
    id: 'seed',
    term: 'seed',
    aliases: ['seeds'],
    meaning:
      'A number that sets the game’s random events, so each seed is a different game. A recording is one game on one seed, and the soft loop’s seeds are split into training and held-out seeds.',
    see: [{ screen: 'results', panel: 'rt-benchmark', label: 'the benchmark seeds' }],
    code: 'ruletree/game.py · Game.reset',
    solutions: ['rules'],
  },
  {
    id: 'training-seed',
    term: 'training seed',
    aliases: ['training seeds'],
    meaning:
      'A game the soft loop plays and writes rules for: seeds 9 to 19 for the shipped trees. A rule is added only if the tree with it clears at least as many training seeds as the tree without it.',
    see: [{ screen: 'results', panel: 'rt-passes', label: 'seeds cleared, step by step' }],
    code: 'ruletree/loop.py · run_loop',
    solutions: ['rules'],
  },
  {
    id: 'held-out-seed',
    term: 'held-out seed',
    aliases: ['held-out seeds'],
    meaning:
      'A game the soft loop writes no rule for: seeds 20 to 39, played after every training seed clears, to see whether the rules work on games they were not written for, and seeds 40 to 59, never played while the shipped trees were written.',
    see: [{ screen: 'results', panel: 'rt-passes', label: 'seeds cleared, step by step' }],
    code: 'ruletree/loop.py · run_loop',
    solutions: ['rules'],
  },
]

export const GLOSSARY_BY_ID: Record<string, GlossaryEntry> = Object.fromEntries(GLOSSARY.map((e) => [e.id, e]))

/** The words of the earlier design, which no screen shows any more: one line on the Reference screen. */
export const REMOVED_TERMS = [
  'arbiter',
  'module',
  'gate network',
  'budget mode',
  'committed pick',
  'exploration pressure',
]
