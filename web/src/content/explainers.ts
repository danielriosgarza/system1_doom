// What each panel explains when its "?" is opened: one sentence always shown, a few paragraphs, the code it
// reads, and a formula only where one applies (the n-step return and the history test's metrics). The rule tree's
// panels are in `rules/explainers.ts`.
import { RULE_EXPLAINERS } from './rules/explainers'

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
    title: 'The six instances at this decision',
    sentence:
      'Five sense instances each answered whether to send a message. The central instance chose the action from the messages it received, and Act pressed that action’s keys.',
    paragraphs: [
      'Each row is one d1-ultra call. A sense is shown only the channels in its scope and answers three questions: whether the central instance needs a message from it (a probability), which action it recommends, and why. When that probability is 0.5 or more, the sense sends a message: its recommended action, its reason, and the probability as the message’s strength. Below 0.5 it sends nothing, which the row shows as silent.',
      'In recordings made since the senses choose the motor’s targets, the combat sense also answers which visible enemy the aim locks onto, and the resource sense which remembered pickup a walk goes to. Act names both: the motor aims and walks only at targets a sense chose, never at one of its own.',
      'The central instance receives the messages, together with each sense’s track record, and chooses one action from the legal menu. Under the exploit level, the action with the highest probability is executed. Under the explore level, an action is drawn at random from the central instance’s own probabilities. When the central instance gives no usable answer, no keys are pressed and the decision is recorded as missed.',
      'Click a row to open that instance at this decision: the evidence text it was sent, exactly as sent, and all of its answers.',
    ],
    code: 'senses.py · run_senses; system1.py · pick_action',
  },
  'config-line': {
    title: 'The configuration in force',
    sentence:
      'The configuration version this decision was made under, the last change that produced it, and whether a trial is in progress.',
    paragraphs: [
      'The configuration is everything System 2 can change: the channels each instance is shown (its scope), the exploration level, the active strategy, and the macros admitted into the menu. Every change produces a new version number.',
      'A change to a scope is first tested on stored decisions (the history test). Any change then takes effect between two decisions, as a trial: it is observed for a fixed number of decisions, and the trial judge keeps it or reverts it.',
    ],
    code: 'configuration.py · Configuration; system2.py · System2',
  },
  evidence: {
    title: 'What it was sent',
    sentence:
      'The evidence text this instance received at this decision, exactly as sent, plus the screen image when the frame channel is in its scope.',
    paragraphs: [
      'The text is divided into channels, each under a [channel] header, always in the same order. An instance is shown only the channels in its scope. The highlighted chips list those channels; the dimmed chips are channels that exist but were not sent to this instance.',
      'A sense is never shown the other senses’ messages or their track records; only the central instance is. Whatever a scope leaves out never reaches the instance in any form. For example, the survival sense is not shown the pickups channel unless System 2 widens its scope to include it.',
    ],
    code: 'evidence.py · render_scope; instance.py · run_instance',
  },
  answers: {
    title: 'What it answered',
    sentence:
      'Every answer d1-ultra returned for this instance, shown as probability distributions. The marked option is the instance’s answer.',
    paragraphs: [
      'A sense answers three questions: speak (one probability), action (a distribution over the legal menu) and reason (a distribution over its own fixed list of reasons). The central instance answers one question, which action to execute, as a distribution over the same menu.',
      'The combat and resource senses answer a fourth, target: which visible enemy the aim locks onto, or which remembered pickup a walk goes to, as a distribution over the candidates their evidence shows, each in the words they saw it in. With one candidate there is nothing to choose between and no question is asked: that one is the target. Older recordings, made before the senses chose targets, have no target answers.',
      'An answer that arrived too late, failed, or named an option outside the menu is a miss. Nothing replaces it. A missed sense sends no message; a missed central instance presses no keys for the decision.',
    ],
    code: 'instance.py · read_choice; instance.py · read_noul; system1.py · targets_of',
  },
  scrubber: {
    title: 'The timeline',
    sentence: 'Every decision of the episode, with the agent’s health over time and marks for what happened.',
    paragraphs: [
      'Marks above the track are game events: damage taken, a kill, the agent’s death. Marks below the track are events in the decision system: a call that missed, an action drawn at random under the explore level, a new configuration version taking effect, and a System 2 cycle.',
      'Click or drag on the track to move to a decision. Every screen then shows that decision.',
    ],
    code: 'logger.py · TickTrace',
  },
  versions: {
    title: 'Configuration versions',
    sentence:
      'Each configuration version the episode played under or produced: the change, the reflector that proposed it, System 2’s choice, the history test and the trial.',
    paragraphs: [
      'A reflector is a d1-ultra instance that reads part of the history and may propose one configuration change. System 2’s central instance receives the proposals and chooses one change, or none.',
      'A scope change must pass the history test before it is applied. Every change then takes effect between two decisions, as a trial. After the trial’s decisions, the trial judge keeps or reverts the change. A revert restores the previous configuration under a new version number.',
    ],
    code: 'system2.py · System2; reflectors.py · config_diff',
  },
  cycles: {
    title: 'Every cycle',
    sentence: 'Each time System 2 ran: what each reflector was shown and answered, and what resulted.',
    paragraphs: [
      'A cycle starts after every 20 new decisions and at the end of an episode, unless a trial is in progress. A reflector that the bounds leave with no change to propose is not called; the cycle records why.',
    ],
    code: 'system2.py · System2; reflection.py · ReflectionTrace',
  },
  'history-test': {
    title: 'The history test',
    sentence:
      'The instance asked again under the new scope, on decisions it already answered, with the old and new answers side by side.',
    paragraphs: [
      'The test takes 24 stored decisions from the last 3 episodes, chosen by their outcome: 8 with a bad n-step return (the bottom quarter), 8 with a good one (the top quarter) and 8 from the rest, with at most 4 from any one situation. Each is rendered again under the new scope and sent to d1-ultra once more. The old scope’s answers are the ones stored when the decision was made.',
      'For a sense, three metrics: alarm recall on bad decisions (it sent a message recommending a different action from the one executed), good agreement on good decisions (it sent no message, or recommended the executed action), and quiet on the rest (it sent no message). For the central instance: agreement with the executed action on good decisions and disagreement on bad ones. A missed call counts as no message.',
      'The composite score is the mean of the metrics. The change passes when the new composite is at least 0.05 above the old one and no single metric falls by more than 0.10. Because d1-ultra’s answers vary, the old scope is also asked again on 4 of the decisions, and how often it repeats its stored answer is reported as a noise estimate. The labels come from what the agent actually did, and the alternatives were never played, so the test measures agreement with good outcomes, not what would have happened.',
    ],
    formula:
      'composite = mean of the quality metrics · pass ⇔ new composite − old composite ≥ 0.05 and every (old − new) ≤ 0.10',
    code: 'history_test.py · run_history_test',
  },
  trial: {
    title: 'The trial',
    sentence:
      'The change under observation: the decisions before it and the decisions under it, side by side, and the verdict.',
    paragraphs: [
      'After the trial’s decisions (60 by default), the trial judge, one more d1-ultra call, is shown this table and answers keep or revert. If the judge gives no usable answer, the trial is extended by 20 decisions and the judge is asked again; after three misses the change is reverted without a verdict.',
      'One case needs no judge. For a scope change, if the changed instance’s followed messages pay off much less often during the trial than before (a drop of more than 0.15, over at least 10 followed messages), a safety bound reverts the change at once.',
    ],
    code: 'system2.py · trial_table',
  },
  ledger: {
    title: 'The relevance ledger',
    sentence:
      'Each sense’s track record per situation: how often it sent a message, how often the central instance followed it, and how often that paid off.',
    paragraphs: [
      'At the end of every episode, each decision where a sense sent a message is counted once. It counts as followed when the central instance executed the sense’s recommended action, and as overruled otherwise. A decision paid off when its n-step return was positive. The ledger also keeps the sense’s mean strength on decisions that paid off and on those that did not, which shows whether a high strength means anything.',
      'The central instance is shown each sense’s record for the current situation as plain counts, in its relevance channel. These numbers are evidence only; nothing in the code multiplies them into a decision.',
    ],
    formula:
      'G_t = r_t + γ·r_t+1 + … + γ^(n−1)·r_t+n−1, n = 8, γ = 0.9 (truncated at the episode’s end) · paid off ⇔ G_t > 0',
    code: 'relevance.py · update_ledger',
  },
  'relevance-episodes': {
    title: 'Relevance over episodes',
    sentence: 'How often each sense’s followed messages paid off, as the ledger grew from one episode to the next.',
    paragraphs: [
      'Each recording carries the ledger as it stood after its episode, and the open episode’s own decisions give the ledger before it as well. All the recordings here were played in one run folder, so their ledgers are successive points on one line.',
    ],
    formula: 'paid-off share = followed and paid off ÷ followed, with paid off ⇔ G_t > 0',
    code: 'relevance.py · update_ledger',
  },
  values: {
    title: 'The value networks, as evidence',
    sentence:
      'Five small neural networks’ predicted returns for each legal action, shown to the one instance whose scope includes the values channel.',
    paragraphs: [
      'The networks are trained between episodes on the agent’s own play, one per sense’s reward. They do not decide anything. Their predictions are one more channel of evidence text, together with how often each action was tried in this situation during training, so the instance can tell a well-tested number from a guess.',
    ],
    code: 'learning.py · Learner; evidence.py · render_scope',
  },
  trust: {
    title: 'How much training is behind the numbers',
    sentence:
      'The situations training saw most, and how often each action was tried in the current situation: the counts behind the values channel’s “tried N here”.',
    paragraphs: [
      'The counts come from the network checkpoint this recording was played with (trust.json). In a situation the networks have rarely seen, their predictions are worth little, and the values channel shows the counts so the instance can see that.',
    ],
    code: 'learning.py · Learner.tried_counts',
  },
  proposals: {
    title: 'Proposals',
    sentence:
      'Each macro-action the slow path proposed when System 2 requested one, and whether it was admitted into the menu.',
    paragraphs: [
      'The menu reflector may propose requesting a new macro when no legal action fits one sense’s problem. If System 2’s central instance chooses that proposal, the slow path writes one macro: a short, fixed list of primitive actions. Before any d1-ultra instance sees the macro, it must parse, use only known primitives, and pass a rough simulation (the sandbox).',
    ],
    code: 'llm_worker.py · SlowLLMWorker; admission.py · ProposalAdmissionPipeline',
  },
  admit: {
    title: 'The admit instance',
    sentence:
      'One d1-ultra call that answers yes or no to a macro that passed every check, from the evidence shown here.',
    paragraphs: [
      'The admit instance is shown the proposed macro, its primitives, the sandbox’s numbers and the problem it was requested for, and answers with one probability. At 0.5 or more the macro joins the menu at the start of the next decision, as a trial. Anything else, including a miss, rejects it.',
    ],
    code: 'admission.py · admit_evidence; instance.py · run_admit',
  },
  drawing: {
    title: 'How it works',
    sentence:
      'Two systems built from one building block: a d1-ultra instance with its own evidence and its own fixed set of questions.',
    paragraphs: [
      'System 1 makes every decision. Five senses, each shown its own scope, answer whether to send a message. The central instance receives the messages and chooses the action. Act presses that action’s keys for 8 game frames. Every decision is stored in full in the history.',
      'System 2 runs on its own thread and reads that history. Its reflectors propose configuration changes, its central instance chooses one at a time, a scope change is tested on the history first, and every change is run as a trial and judged.',
    ],
    code: 'controller.py · DoomDecisionController',
  },
  reflectors: {
    title: 'The reflectors',
    sentence:
      'Nine d1-ultra instances that read the history: what each was shown, exactly as sent, and the change it proposed.',
    paragraphs: [
      'Each reflector reads history channels over three time windows (the last 20 decisions, the last 100, and the last 3 episodes) and answers three questions: speak (a probability), change (one option from its fixed list of changes) and reason.',
      'Before any call, the bounds remove changes from each reflector’s list: a trial in progress, a cooling period, a scope already at its limit of 7 channels, the menu channel (never removed), a built-in action (never retired). A reflector left with no change is not called. One whose speak probability reaches 0.5 and whose change is not keep sends a proposal; one below 0.5, missed, or answering keep sends nothing.',
    ],
    code: 'reflectors.py · ReflectorSpec; instance.py · run_system2_instance',
  },
  'system2-central': {
    title: 'System 2’s central instance',
    sentence: 'One d1-ultra choice among the proposals the bounds still allow, plus the option of no change.',
    paragraphs: [
      'It is shown the proposals in its messages channel, the configuration’s change log, and what play produced over the three windows. The option with the highest probability is the change; a tie goes to the first option. When this call misses, nothing changes in this cycle.',
    ],
    code: 'system2.py · System2',
  },
  'configuration-changes': {
    title: 'The configuration at the start and the end',
    sentence:
      'Each instance’s scope, the admitted macros, the active strategy and the exploration level, as the episode began and as it ended.',
    paragraphs: [
      'A recording that starts from a later version starts with what earlier episodes left behind: the configuration is saved to the run folder at every change that takes effect, and every run starts from that file.',
    ],
    code: 'configuration.py · Configuration; reflectors.py · config_diff',
  },
  'menu-now': {
    title: 'The menu',
    sentence:
      'Every action this recording knew, which ones were legal at this decision, and how often each was executed in the episode.',
    paragraphs: [
      'An action is a fixed list of primitive moves (single steps such as strafe left or shoot) with preconditions. The legal menu at a decision is the set of actions whose preconditions hold. Every instance chooses from exactly that menu; nothing else can be executed.',
      'A macro admitted while the episode is played joins the menu at the start of a decision, as a trial.',
    ],
    code: 'actions.py · ActionVocabulary',
  },
  'menu-reflector': {
    title: 'The menu reflector',
    sentence: 'At every cycle, whether the reflector responsible for the menu requested a new macro, and why.',
    paragraphs: [
      'It reads each action’s count and mean return over the three windows. It may propose requesting a new macro for one sense’s problem, retiring an admitted macro, or keeping the menu as it is. A request needs the slow path to be switched on and idle.',
    ],
    code: 'reflectors.py · ReflectorSpec',
  },
  principles: {
    title: 'The one rule',
    sentence: 'What decides, and what only produces evidence, enforces limits and presses keys.',
    paragraphs: [
      'The hand-written code produces evidence and enforces limits: the channels, the legal menu, the simulator’s projections, the value networks’ numbers, and every bound. None of it ranks, scores or picks an action.',
    ],
    code: 'system1.py · pick_action; instance.py · run_admit',
  },
  glossary: {
    title: 'Glossary',
    sentence: 'The terms the screens use, with where to see each one and where the code defines it.',
    paragraphs: ['A test keeps this glossary and the one in docs/DOCUMENTATION.md, section 18, in step.'],
  },
  provenance: {
    title: 'How this recording was made',
    sentence:
      'The command, the scenario, the seed, the value networks and the configuration version it was played under.',
    paragraphs: [
      'Every recording here was played by d1-ultra or by Jev, TypeSafe’s decision model, with the same instances, evidence and questions; its card and the top bar say which. Each was exported with python -m system1_doom.export, which checks the files before they are shipped.',
    ],
    code: 'export.py · record_bundle; export.py · check_bundle',
  },
  keys: {
    title: 'Keyboard shortcuts',
    sentence: 'Moving through a recording without the mouse.',
    paragraphs: ['The shortcuts do nothing while you type in a text field.'],
  },
  ...RULE_EXPLAINERS,
} satisfies Record<string, Explainer>

export type PanelId = keyof typeof EXPLAINERS
