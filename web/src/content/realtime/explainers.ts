// What each real-time panel explains when its "?" is opened: the panels only the real-time screens have (`rtm-`), and
// the rule tree's panels they share, in real-time words (REALTIME_OVERRIDES).
import type { Explainer } from '../explainers'
import { LOCAL_OVERRIDES } from '../local/explainers'

export const REALTIME_PANELS = {
  'rtm-steps': {
    title: 'From a state to its action',
    sentence:
      'What happens between the moment a state is read and the moment its action begins, while the game goes on.',
    paragraphs: [
      'A tic is one frame of the game; Doom runs 35 a second. A decision is asked every 8 tics, as in the other tabs, but here the game does not wait for it: the action begins at the first tic after the answers are in.',
      'So an action is decided for a state a few tics old. With the rules made for a paused game this made the aim turn twice for one angle and swing from side to side, which is why the helper aims between Laya’s answers.',
    ],
    code: 'ruletree/realtime.py · play_realtime',
  },
  'rtm-helper': {
    title: 'The helper',
    sentence: 'What presses the keys between Laya’s answers, from what is on the screen, and why it is fair.',
    paragraphs: [
      'The helper is a few lines of code that run at every tic. It is given the focus Laya picked and the action’s own keys, and it turns toward the focus until the crosshair is on it, then presses those keys.',
      'It reads the same labels the state text is written from, 4 tics late, and its own facing; it never reads where an enemy really is inside the game.',
    ],
    code: 'ruletree/realtime.py · Helper; ruletree/realtime.py · tracked',
  },
  'rtm-around': {
    title: 'Around this decision',
    sentence: 'The timing of the decisions near the one showing, from the recording.',
    paragraphs: [
      'State read is the tic the state text was written at; action began is the tic its action started; late by is the difference, in tics and in milliseconds of game time. Laya took is the time of the walk’s questions, one after another.',
    ],
    code: 'ruletree/bundle.py · record_realtime_episode',
  },
  'rtm-settings': {
    title: 'This recording',
    sentence: 'How this recording was played, from its episode.json.',
    paragraphs: [
      'On the real clock the game runs at 35 tics a second whatever the program does; if the program itself fell behind, the tics it missed would be played at once. None were.',
    ],
    code: 'ruletree/bundle.py · RealtimeSettings',
  },
  'rtm-path': {
    title: 'From 9 to 80',
    sentence: 'Each change, in the order it was made, and how many of the 81 benchmark seeds were cleared after it.',
    paragraphs: [
      'Every number is one run of the 81 seeds on the real clock, one game at a time, with nothing else asking Laya. Games differ a little from run to run because the answers arrive at slightly different tics, so a difference of one or two games is within chance.',
    ],
    code: 'ruletree/__main__.py · main (realtime)',
  },
  'rtm-loops': {
    title: 'The rules for real time',
    sentence: 'The rule writer’s loops on games played at Laya’s speed.',
    paragraphs: [
      'A loop plays the training seeds, takes the first game that failed to Codex, the rule writer, with a report of its last decisions, and tests the rule it proposes: it is kept only when the training seeds clear at least as well with it. The seeds used to write rules are never the benchmark seeds.',
    ],
    code: 'ruletree/rtloop.py · run_rt_loop',
  },
  'rtm-training': {
    title: 'Laya, retrained',
    sentence:
      'Kev-27B answered the new rules’ questions in games played at Laya’s speed, and Laya learned its answers.',
    paragraphs: [
      'Kev is too slow to play in real time, about 1.3 s a decision. But a game can be held while it answers and then go on as if the answer had come in Laya’s time: its answers are then answers to the states Laya meets in real time. Laya was trained to give Kev’s probabilities to those questions.',
    ],
    code: 'ruletree/teach.py · build; laya-train, from the laya package',
  },
  'rtm-lag': {
    title: 'What a late answer does to rules made for a paused game',
    sentence:
      'The first day’s measurement, before the helper: each action started a fixed number of tics after its state.',
    paragraphs: [
      'A lag near one action, 8 tics, is the worst for those rules: the next decision is made before the last turn shows on the screen, so two actions turn for one angle.',
    ],
    code: 'ruletree/realtime.py · play_realtime',
  },
  'rtm-totals': {
    title: 'This recording',
    sentence: 'What this game asked of Laya and how it ended.',
    paragraphs: [
      'A question repeated with the same text in the same game is answered from the earlier answer, without a call.',
    ],
  },
} satisfies Record<string, Explainer>

/** The rule tree's panels as the real-time screens show them: Laya answers, and the game does not wait. */
export const REALTIME_OVERRIDES: Record<string, Explainer> = {
  ...LOCAL_OVERRIDES,
  'rt-walk': {
    title: 'The questions at this decision',
    sentence:
      'Each row is one question Laya answered at this decision, in the order it was asked, followed by the action, when it began, and what the helper pressed.',
    paragraphs: [
      'At a rule that has rules under it, Laya is asked “Which of these is true right now?”, with their conditions and “None of these is true right now.” as the options. The walk moves into the rule Laya picks and asks again; when Laya picks none, or reaches a rule with nothing under it, that rule’s action is the one done.',
      'Some rules first ask Laya what to pay attention to: which visible enemy is the biggest danger, or which landmark is the goal. Laya’s pick is the focus, and it is what the helper aims at.',
      'The game does not wait while Laya answers. The action begins at the first tic after the answers are in, and until the next action begins the helper presses the keys: it turns toward the focus until the crosshair is on it, then presses the action’s own keys.',
    ],
    code: 'ruletree/walk.py · decide; ruletree/realtime.py · play_realtime',
  },
  'rt-outline': {
    title: 'The tree',
    sentence: 'The rules this decision’s walk went through are marked, and the rule it ended at is outlined.',
    paragraphs: [
      'This is realtime-12: the rule tree’s first rules, without its turning rules (the helper turns), and the seven rules the rule writer added from games played at Laya’s speed. A rule’s action can say what to do once its focus is dead, such as walk on toward the goal, firing.',
    ],
    code: 'ruletree/tree.py · RuleTree',
  },
  'rt-principles': {
    title: 'Who makes each choice',
    sentence: 'What Laya decides, what the helper does, and what the program does.',
    paragraphs: [
      'During a game the program writes the state, asks the questions and follows the answers; the helper presses the keys between answers. Neither ranks, scores or picks a target or an action.',
    ],
    code: 'ruletree/walk.py · decide; ruletree/realtime.py · Helper',
  },
  'rt-provenance': {
    title: 'How this recording was made',
    sentence: 'The tree, the seed, the model, the clock and the command that recorded it.',
    paragraphs: [
      'Every decision in these recordings was made by Laya, trained on Kev-27B’s real-time answers and served by laya-serve on the computer that played, and the game ran on the real clock. Each recording was exported with python -m system1_doom.export --solution rule-tree --realtime wall, which plays the game, keeps every question and answer, one screen image per decision and every key pressed, and checks the files before they are shipped.',
    ],
    code: 'ruletree/bundle.py · record_realtime_episode; ruletree/bundle.py · check_recording',
  },
}
