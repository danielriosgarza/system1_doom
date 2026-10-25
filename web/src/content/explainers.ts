// What each panel explains when its "?" is opened: one sentence always shown, a few paragraphs, the code it
// reads, and a formula only where one applies (the n-step return and the history test's metrics).

export interface Explainer {
  title: string
  /** One sentence, always shown under the title. */
  sentence: string
  paragraphs: string[]
  /** The general formula, shown with the paragraphs; only the n-step return and the test metrics have one. */
  formula?: string
  /** Where in the package this comes from: file · symbol. */
  code?: string
}

export const EXPLAINERS = {
  strip: {
    title: 'The instances at this decision',
    sentence:
      'Five senses decided whether to speak; the central heard the messages and chose the action; Act pressed its keys.',
    paragraphs: [
      'Each row is one d1-ultra call. A sense sees only the channels in its scope and answers three questions: whether to speak (a probability), which action, and why. It speaks when that probability reaches 0.5, and then sends a message: the action, the reason, and the probability as its strength.',
      'The central instance hears the messages, with each sense’s relevance, and chooses one action from the legal menu. Under the exploit level its top answer is executed; under explore its answer is drawn from. When it misses, no keys are held and the tick is recorded as missed.',
      'Click a row to open that instance at this decision: the evidence text it was sent, verbatim, and its answers in full.',
    ],
    code: 'senses.py · run_senses; system1.py · pick_action',
  },
  'config-line': {
    title: 'The configuration in force',
    sentence: 'The version the decision was made under, the change that made it, and a trial still under observation.',
    paragraphs: [
      'The configuration is everything the slow system can change: each instance’s scope, the exploration level, the active strategy, and the admitted macros. Every change makes a new version.',
      'A change is first tested on the history (for a scope change), then applied at a tick boundary as a trial, observed for a fixed number of decisions, and kept or reverted by the trial judge.',
    ],
    code: 'configuration.py · Configuration; system2.py · System2',
  },
  evidence: {
    title: 'What it saw',
    sentence:
      'The state text this instance was sent at this decision, exactly as sent, with the screen when its scope holds the frame.',
    paragraphs: [
      'The text is cut into channels, each under a [channel] header, in a fixed order. An instance is shown only the channels in its scope: the chips list them, and the dimmed chips are the channels it was not shown.',
      'A sense is never shown the messages of the others or their record; only the central is. Whatever a scope leaves out never reaches the instance at all: the survival sense, for example, sees no pickups until the slow system widens its scope.',
    ],
    code: 'evidence.py · render_scope; instance.py · run_instance',
  },
  answers: {
    title: 'What it answered',
    sentence: 'Every answer d1-ultra returned, as distributions; the marked option is the instance’s answer.',
    paragraphs: [
      'A sense answers speak (a probability), action (a distribution over the legal menu) and reason (a distribution over its own finite reasons). The central answers one question, the action, over the same menu.',
      'An answer that came too late, failed, or named something off the menu is a miss: nothing stands in for it. A missed sense is silent; a missed central holds no keys for the decision.',
    ],
    code: 'instance.py · read_choice; instance.py · read_noul',
  },
  scrubber: {
    title: 'The timeline',
    sentence: 'Every decision of the episode, with its health line and what happened.',
    paragraphs: [
      'Marks above the track are what the game did: damage taken, a kill, the death. Marks below are what the instances and the slow system did: a missed call, an action drawn under explore, a new configuration version taking effect, and a cycle of the slow system.',
      'Drag or click to move to a decision; every screen shows the decision under the cursor.',
    ],
    code: 'logger.py · TickTrace',
  },
  versions: {
    title: 'Configuration versions',
    sentence:
      'Each version the episode played under or produced: the change, who proposed it, the slow system’s choice, the test and the trial.',
    paragraphs: [
      'A reflector is a sense over the history: it reads its history channels and may propose one change. The slow system’s central hears the proposals and chooses one change, or none.',
      'A scope change must pass the history test before it is applied. Every change is then applied at a tick boundary as a trial; after its decisions the trial judge keeps or reverts it, and a revert restores the previous configuration with the version bumped.',
    ],
    code: 'system2.py · System2; reflectors.py · config_diff',
  },
  cycles: {
    title: 'Every cycle',
    sentence: 'Each time the slow system reflected, with what each reflector saw and answered and what came of it.',
    paragraphs: [
      'A cycle starts every few decisions and at the end of an episode, unless a trial is in flight. Reflectors with no change the bounds allow are not called; the cycle says why.',
    ],
    code: 'system2.py · System2; reflection.py · ReflectionTrace',
  },
  'history-test': {
    title: 'The history test',
    sentence:
      'The instance asked again, under the new scope, on ticks it already answered; the old and new answers side by side.',
    paragraphs: [
      'Ticks are drawn from the last episodes, stratified by each decision’s n-step return: bad (the bottom quarter), good (the top quarter), and the rest, with at most a few from any one situation.',
      'For a sense: alarm recall on bad ticks (it spoke for another action than the one executed), good agreement on good ticks (silent, or it asked for the executed action), quiet on the rest (silent). For the central: agreement with the executed action on good ticks, disagreement on bad ticks. A missed call counts as silent.',
      'The change passes when the new composite is at least the margin above the old and no metric falls by more than the worst drop allowed. The old scope is re-asked on a few ticks as a noise estimate. Hindsight labels come from what the agent did; the alternatives were never played.',
    ],
    formula:
      'composite = mean of the quality metrics · pass ⇔ new composite − old composite ≥ 0.05 and every (old − new) ≤ 0.10',
    code: 'history_test.py · run_history_test',
  },
  trial: {
    title: 'The trial',
    sentence: 'The change under observation: the decisions before it and during it, side by side, and the verdict.',
    paragraphs: [
      'After the trial’s decisions, the trial judge, one more d1-ultra instance, is shown this table and answers keep or revert. If the changed instance’s followed messages pay off far less often during the trial, the safety bound reverts it without asking.',
    ],
    code: 'system2.py · trial_table',
  },
  ledger: {
    title: 'The relevance ledger',
    sentence: 'Each sense’s track record per situation: how often it spoke, was followed, and paid off.',
    paragraphs: [
      'At the end of every episode, each tick where a sense spoke counts once: followed when the central executed its action, overruled otherwise, and paid off when the decision’s n-step return was positive. The mean strength on ticks that paid off and on ticks that did not shows whether a sense’s urgency means anything.',
      'The central is shown each sense’s record in the current situation as evidence, in its relevance channel. Nothing learned is ever multiplied into a decision.',
    ],
    formula:
      'G_t = r_t + γ·r_t+1 + … + γ^(n−1)·r_t+n−1, n = 8, γ = 0.9 (truncated at the episode’s end) · paid off ⇔ G_t > 0',
    code: 'relevance.py · update_ledger',
  },
  'relevance-episodes': {
    title: 'Relevance over episodes',
    sentence: 'How often each sense’s followed messages paid off, as the ledger grew episode by episode.',
    paragraphs: [
      'Each recording carries the ledger after its episode; the open episode’s ticks give the ledger before it too. All recordings here were played on one run folder, so their ledgers are points on one line.',
    ],
    formula: 'paid-off share = followed and paid off ÷ followed, with paid off ⇔ G_t > 0',
    code: 'relevance.py · update_ledger',
  },
  values: {
    title: 'The value networks, as evidence',
    sentence:
      'Five networks’ predicted returns for each legal action, shown to the instance whose scope holds the values channel.',
    paragraphs: [
      'The networks are trained between episodes on the agent’s own play. They decide nothing: their numbers are one more channel of evidence, with how often each action was tried in this situation in training, so an instance can tell a well-tried number from a guess.',
    ],
    code: 'learning.py · Learner; evidence.py · render_scope',
  },
  trust: {
    title: 'How much play is behind the numbers',
    sentence:
      'Where training tried actions most: the situations and the counts behind the values channel’s “tried N here”.',
    paragraphs: [
      'The counts come from the checkpoint the recording was played with (trust.json). A situation the networks have rarely seen gives numbers worth little, and the values channel says so with its counts.',
    ],
    code: 'learning.py · Learner.tried_counts',
  },
  proposals: {
    title: 'Proposals',
    sentence: 'Each macro-action the slow path proposed when the slow system asked, and whether it was admitted.',
    paragraphs: [
      'The menu reflector proposes asking for a macro when no legal action fits a sense’s problem. If the slow system chooses it, the slow path writes one bounded macro: a finite list of primitives. It must parse, use only legal primitives and stay inside the sandbox’s bounds before any instance sees it.',
    ],
    code: 'llm_worker.py · SlowLLMWorker; admission.py · ProposalAdmissionPipeline',
  },
  admit: {
    title: 'The admit instance',
    sentence:
      'One d1-ultra call that answers yes or no to a macro that passed every bound, from the evidence shown here.',
    paragraphs: [
      'The admit instance sees the proposed macro, its primitives, the sandbox’s numbers and the problem it was asked for, and answers one probability. At 0.5 or more the macro joins the menu at the next tick boundary, as a trial.',
    ],
    code: 'admission.py · admit_evidence; instance.py · run_admit',
  },
  drawing: {
    title: 'How it works',
    sentence:
      'Two systems built from one part: a d1-ultra instance with its own evidence and its own finite questions.',
    paragraphs: [
      'System 1 decides every action: five senses, each with its own scope, decide whether to speak; the central hears them and chooses; Act presses the action’s keys for 8 game frames. The history keeps every tick whole.',
      'System 2 reflects on the history, slowly and on its own thread: reflectors propose changes to the configuration, its central chooses one at a time, a scope change is tested on the history first, and every change is tried and judged.',
    ],
    code: 'controller.py · DoomDecisionController',
  },
  reflectors: {
    title: 'The reflectors',
    sentence: 'Nine d1-ultra instances over the history: what each was shown, verbatim, and the change it proposed.',
    paragraphs: [
      'Each reflector reads history channels over three windows (the recent decisions, a longer run of them, and the last episodes) and answers three questions: speak (a probability), change (one option from its finite menu) and reason.',
      'Before any call, the bounds take changes off each menu: a trial in flight, cooling, a full scope, the menu channel, a built-in action. A reflector left with no change is not called. One that speaks for a change other than keep sends a proposal; one that stays silent, misses, or picks keep sends nothing.',
    ],
    code: 'reflectors.py · ReflectorSpec; instance.py · run_system2_instance',
  },
  'system2-central': {
    title: 'System 2’s central',
    sentence: 'One d1-ultra choice over the proposals the bounds still allow, and none.',
    paragraphs: [
      'It is shown the proposals in its messages channel, the configuration’s change log and what play produced. Its top answer is the change, a tie going to the first option; when it misses, nothing changes this cycle.',
    ],
    code: 'system2.py · System2',
  },
  'configuration-changes': {
    title: 'The configuration at the start and the end',
    sentence: 'Each instance’s scope, the admitted macros, the strategy and the level, as the episode began and ended.',
    paragraphs: [
      'A recording that starts from a later version starts from what earlier episodes left: the configuration is saved to the run folder at every change that takes effect, and every run starts from it.',
    ],
    code: 'configuration.py · Configuration; reflectors.py · config_diff',
  },
  'menu-now': {
    title: 'The menu',
    sentence: 'Every action this recording knew, the ones legal at this decision, and how often each was executed.',
    paragraphs: [
      'An action is a fixed list of primitives with preconditions. The legal menu of a decision is the actions whose preconditions hold, and every instance chooses over exactly that menu: nothing else can be executed.',
      'A macro admitted while the episode played joins the menu at a tick boundary, as a trial.',
    ],
    code: 'actions.py · ActionVocabulary',
  },
  'menu-reflector': {
    title: 'The menu reflector',
    sentence: 'At every cycle, whether the reflector that grows the menu asked for a new macro, and why.',
    paragraphs: [
      'It reads each action’s count and mean return over the windows. It may ask for a new macro for one sense’s problem, retire an admitted macro, or keep the menu. Asking needs the slow path to be on and free.',
    ],
    code: 'reflectors.py · ReflectorSpec',
  },
  principles: {
    title: 'The one rule',
    sentence: 'What decides, and what only renders evidence, keeps bounds and presses keys.',
    paragraphs: [
      'What stays hand-written is evidence and bounds: the channels, the legal menu, the simulator’s projections, the value networks’ numbers, and every limit. None of it ranks, scores or picks an action.',
    ],
    code: 'system1.py · pick_action; instance.py · run_admit',
  },
  glossary: {
    title: 'Glossary',
    sentence: 'The words the screens use, with where to see each one and where the code keeps it.',
    paragraphs: ['A test keeps this glossary and the one in docs/DOCUMENTATION.md, section 18, in step.'],
  },
  provenance: {
    title: 'How this recording was made',
    sentence: 'The command, the scenario, the seed, the value networks and the configuration it played under.',
    paragraphs: [
      'Every recording here was played by d1-ultra and exported with python -m system1_doom.export, which checks the bundle before it is shipped.',
    ],
    code: 'export.py · record_bundle; export.py · check_bundle',
  },
  keys: {
    title: 'Keys',
    sentence: 'Moving through a recording without the mouse.',
    paragraphs: ['Keys do nothing while a text field has the focus.'],
  },
} satisfies Record<string, Explainer>

export type PanelId = keyof typeof EXPLAINERS
