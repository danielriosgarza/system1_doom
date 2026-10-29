// What each real-time panel explains when its "?" is opened: the panels only the real-time screens have (`rtm-`), and
// the rule tree's panels they share, worded for real time (REALTIME_OVERRIDES).
import type { Explainer } from '../explainers'
import { LOCAL_OVERRIDES } from '../local/explainers'

export const REALTIME_PANELS = {
  'rtm-steps': {
    title: 'From state to action',
    sentence: 'What happens between reading a state and starting its action, while the game keeps running.',
    paragraphs: [
      'A tic is one frame of the game; Doom runs at 35 tics a second. As in the other tabs, a decision is made every 8 tics, but the game is not paused while Laya answers. The action starts at the first tic after the answers arrive.',
      'Each action is therefore based on a state that is a few tics old. With the rules written for the paused game, this caused the player to turn twice for the same angle and overshoot. The helper was added to fix this.',
    ],
    code: 'ruletree/realtime.py · play_realtime',
  },
  'rtm-helper': {
    title: 'The helper',
    sentence: 'The code that presses the keys between Laya’s answers, using what is on the screen.',
    paragraphs: [
      'The helper runs at every tic. It receives the focus that Laya selected and the keys of the action. It turns toward the focus until the crosshair is on it, then presses the action’s keys.',
      'It reads the same on-screen information used to write the state text, with a 4-tic delay, and the player’s own facing. It does not use the positions of enemies that are not visible.',
    ],
    code: 'ruletree/realtime.py · Helper; ruletree/realtime.py · tracked',
  },
  'rtm-around': {
    title: 'Decisions around this one',
    sentence: 'The timing of the decisions near the current one, from the recording.',
    paragraphs: [
      'State read is the tic at which the state text was written. Action started is the tic at which its action began. Delay is the difference, in tics and in milliseconds of game time. Laya’s answers is the total time of the decision’s questions.',
    ],
    code: 'ruletree/bundle.py · record_realtime_episode',
  },
  'rtm-settings': {
    title: 'This recording',
    sentence: 'How this recording was played, from its episode.json.',
    paragraphs: [
      'In real time the game runs at 35 tics a second regardless of the program. If the program fell behind, the missed tics would be played at once. In these recordings this did not happen.',
    ],
    code: 'ruletree/bundle.py · RealtimeSettings',
  },
  'rtm-path': {
    title: 'Changes and results',
    sentence: 'Each change in the order it was made, and the number of the 81 benchmark seeds cleared after it.',
    paragraphs: [
      'Each number is one run of the 81 seeds in real time, one game at a time, with no other program using Laya. Results vary slightly between runs because the answers arrive at slightly different tics, so a difference of one or two games is not meaningful.',
    ],
    code: 'ruletree/__main__.py · main (realtime)',
  },
  'rtm-loops': {
    title: 'Rule writing',
    sentence: 'The rounds of rule writing on games played in real time.',
    paragraphs: [
      'Each round plays the training seeds, sends the first failed game to Codex with a report of its last decisions, and tests the rule Codex proposes. The rule is kept only if the training seeds clear at least as well with it. The training seeds are different from the benchmark seeds.',
    ],
    code: 'ruletree/rtloop.py · run_rt_loop',
  },
  'rtm-training': {
    title: 'Retraining Laya',
    sentence:
      'Kev-27B answered the new rules’ questions in games with Laya’s delay, and Laya was trained on those answers.',
    paragraphs: [
      'Kev takes about 1.3 s per decision, which is too slow for real time. The game was therefore paused while Kev answered, and then continued as if the answer had arrived after Laya’s delay. This gives answers to the same kind of states Laya sees in real time. Laya was trained to give the same probabilities as Kev.',
    ],
    code: 'ruletree/teach.py · build; laya-train, from the laya package',
  },
  'rtm-lag': {
    title: 'Effect of the delay on the original rules',
    sentence: 'The first measurement, before the helper: each action started a fixed number of tics after its state.',
    paragraphs: [
      'A delay of about one action (8 tics) gives the worst result with these rules, because the next turn is decided before the previous turn is visible on the screen.',
    ],
    code: 'ruletree/realtime.py · play_realtime',
  },
  'rtm-totals': {
    title: 'This recording',
    sentence: 'The questions asked of Laya in this game, and how it ended.',
    paragraphs: [
      'A question asked again with the same text in the same game reuses the earlier answer, without a new call.',
    ],
  },
} satisfies Record<string, Explainer>

/** The rule tree's panels as the real-time screens show them. */
export const REALTIME_OVERRIDES: Record<string, Explainer> = {
  ...LOCAL_OVERRIDES,
  'rt-walk': {
    title: 'The questions at this decision',
    sentence:
      'Each row is one question Laya answered at this decision, in order, followed by the action, its timing and what the helper pressed.',
    paragraphs: [
      'At a rule with rules under it, Laya is asked “Which of these is true right now?”, with their conditions and “None of these is true right now.” as the options. The walk moves into the rule Laya selects and asks again. When Laya selects none, or reaches a rule with no rules under it, that rule’s action is used.',
      'Some rules first ask Laya which item to focus on, such as the most dangerous visible enemy or the goal. The focus is what the helper aims at.',
      'The game is not paused while Laya answers. The action starts at the first tic after the answers arrive. Until the next action starts, the helper turns toward the focus until the crosshair is on it, then presses the action’s keys.',
    ],
    code: 'ruletree/walk.py · decide; ruletree/realtime.py · play_realtime',
  },
  'rt-outline': {
    title: 'The tree',
    sentence: 'The rules this decision went through are marked, and the rule it ended at is outlined.',
    paragraphs: [
      'This is realtime-12: the rule tree’s first rules without its turning rules (the helper does the turning), plus seven rules written by Codex from games played in real time. A rule’s action can include a follow-up action for after its target is killed, such as walking forward toward the goal while firing.',
    ],
    code: 'ruletree/tree.py · RuleTree',
  },
  'rt-principles': {
    title: 'Who decides what',
    sentence: 'What Laya decides, what the helper does, and what the program does.',
    paragraphs: [
      'During a game, the program writes the state, asks the questions and follows the answers. The helper presses the keys between answers. Neither selects a target or an action.',
    ],
    code: 'ruletree/walk.py · decide; ruletree/realtime.py · Helper',
  },
  'rt-provenance': {
    title: 'How this recording was made',
    sentence: 'The tree, the seed, the model, the timing and the command used to record it.',
    paragraphs: [
      'Every decision in these recordings was made by Laya, trained on Kev-27B’s answers in real-time games and served by laya-serve on the computer that played. The game was not paused. Each recording was made with python -m system1_doom.export --solution rule-tree --realtime wall, which plays the game, saves every question and answer, one screen image per decision and every key pressed, and checks the files before they are shipped.',
    ],
    code: 'ruletree/bundle.py · record_realtime_episode; ruletree/bundle.py · check_recording',
  },
}
