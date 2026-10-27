// What each rule-tree panel explains when its "?" is opened. The ids start with `rt-`, beside the senses and
// central's in `../explainers.ts`, which lists both.
import type { Explainer } from '../explainers'

export const RULE_EXPLAINERS = {
  'rt-walk': {
    title: 'The questions at this decision',
    sentence:
      'Each row is one question Jev answered at this decision, in the order it was asked, followed by the action that was played.',
    paragraphs: [
      'A rule has a condition and an action. The rules under a rule are its exceptions: more specific rules that replace its action when their condition is true. At a rule that has rules under it, Jev is asked “Which of these is true right now?”, with their conditions and “None of these is true right now.” as the options. The walk moves into the rule Jev picks and asks again. When Jev picks none, or reaches a rule with nothing under it, that rule’s action is played.',
      'Some rules first ask Jev what to pay attention to: which visible enemy is the biggest danger, or which landmark is the goal. Jev’s pick is added to the state as a [focus] channel, and the rules under it speak about the focus.',
      'An action can use a skill. The aim skill is a set of rules that each turn toward the focus by an amount that fits its angle. The rule that used the skill says what to do for the rest of the decision: fire, walk forward and fire, or walk forward.',
      'The action is held for 8 tics, about a quarter of a second. Then the next decision starts again at the top of the tree.',
    ],
    code: 'ruletree/walk.py · decide',
  },
  'rt-sent': {
    title: 'What Jev was sent',
    sentence: 'The state text this question was sent with, exactly as sent, and the screen sent with it as an image.',
    paragraphs: [
      'The state is plain text in channels, each under a [channel] header, always in the same order. The program writes it from the game: health, the enemies in view with their distance, angle and size on screen, what the last shots hit, the pickups and landmarks, the walls, the position and the last actions. Nothing in it says what to do.',
      'Every question of a decision is sent the same state and the same screen. After a focus question, the questions that follow are also sent a [focus] channel at the end, which names the item Jev picked; it is highlighted here.',
    ],
    code: 'ruletree/game.py · Game.observe; ruletree/walk.py · with_focus',
  },
  'rt-answer': {
    title: 'What Jev answered',
    sentence:
      'Jev’s probability for every option of this question. The option with the highest probability is its answer, and the walk goes there.',
    paragraphs: [
      'Jev is TypeSafe’s decision model. It answers a multiple-choice question with a probability for each option. The walk takes the option with the highest probability, and nothing else is weighed.',
      'A call that fails, runs out of time, or answers with an option that was not offered is a miss. The walk stops at the rule it has reached and that rule’s action is played. Nothing replaces the missing answer.',
      'When a focus question has only one item to choose from, no question is asked: that item is the focus.',
    ],
    code: 'ruletree/walk.py · Jev.ask',
  },
  'rt-scrubber': {
    title: 'The timeline',
    sentence:
      'One slot per decision of this recording, with the health line, the top rule each walk went into, and what happened.',
    paragraphs: [
      'Click or drag to move to a decision; every screen follows it. The coloured band under each slot shows which of the tree’s top rules the walk went into at that decision. The marks above the slots show damage taken, a kill and a death. A circle below a slot marks a decision where a call missed.',
    ],
  },
  'rt-rounds': {
    title: 'The record, step by step',
    sentence: 'Every step the soft loop took to write this tree, in order.',
    paragraphs: [
      'A pass plays every training seed once with the tree as it is. Each game that died or stopped making progress is a failure the rule writer can write a rule for. A proposal is one rule (or a small group) the writer proposed; it is added or rejected. The held-out seeds are played once the training seeds all clear.',
    ],
    code: 'ruletree/loop.py · run_loop',
  },
  'rt-round': {
    title: 'This step',
    sentence: 'What happened at the step picked on the left.',
    paragraphs: [
      'A proposed rule is first checked on the game it was written for, with three tests. Sees: at the decision it was written for, the walk now reaches the new rule. Unchanged: the decisions the earlier rules were written for still reach their rules, or their games end no worse. Avoids: the game is replayed from that decision to 24 decisions past the failure, once with the old tree and once with the new one, and the new one must end better: alive rather than dead, the goal reached rather than not, or else no less health and no less distance, with more of one of them.',
      'A rule that passes its check goes to the gate: the current tree and the tree with the rule each play every training seed once. The rule is added only if the tree with it clears at least as many seeds. A rule can pass its check on one game and still lose games elsewhere.',
      'The program runs the games and grades the outcomes. Every answer in those games is Jev’s.',
    ],
    code: 'ruletree/check.py · check; ruletree/gate.py · gate',
  },
  'rt-passes': {
    title: 'Seeds cleared, step by step',
    sentence: 'How many seeds the tree cleared each time the soft loop played them all.',
    paragraphs: [
      'The training seeds are the games the soft loop plays and writes rules for. The held-out seeds are played only once every training seed clears, to see whether the rules work on games they were not written for.',
    ],
    code: 'ruletree/loop.py · run_loop',
  },
  'rt-benchmark': {
    title: 'The benchmark',
    sentence: 'The tree on 81 seeds, with the senses and central on the 30 they share.',
    paragraphs: [
      'Every game of the benchmark was played afresh, with new answers from Jev. Seeds 201 to 215 and 301 to 315 are the senses and central’s benchmark seeds; neither solution was written or tuned on them.',
    ],
    code: 'ruletree/__main__.py · main',
  },
  'rt-uses': {
    title: 'Which rules decided this recording',
    sentence:
      'For each rule, at how many decisions of this recording the walk went into it, and at how many it ended there and played its action.',
    paragraphs: [
      'A walk can go through several rules. Its action comes from the last one it reached; when that rule is part of a skill, the rule that used the skill says how the decision ends.',
    ],
  },
  'rt-totals': {
    title: 'This recording',
    sentence: 'What this game cost and how it ended.',
    paragraphs: [
      'Jev is asked one question at a time, so a decision takes as long as its questions together. Calls answered from an identical earlier question of the same game are not counted.',
    ],
  },
  'rt-outline': {
    title: 'The tree',
    sentence:
      'Every rule, each under the rule it is an exception to. The rules this decision’s walk went through are marked, and the one whose action was played is outlined.',
    paragraphs: [
      'The tree is a file: its rules, the questions that pick a focus, its skills, and for each rule added by the soft loop the decision it was written for. The program plays it without anything else.',
    ],
    code: 'ruletree/tree.py · RuleTree',
  },
  'rt-rule': {
    title: 'Where this rule came from',
    sentence: 'The rule’s condition and action, who wrote it and why, and the decision it was written for.',
    paragraphs: [
      'A rule the soft loop added keeps the decision it was written for: the seed, the actions that led there, the state text and the screen. Every later rule must leave that decision on the same route, or end its game no worse.',
    ],
    code: 'ruletree/tree.py · Cornerstone',
  },
  'rt-principles': {
    title: 'The one rule',
    sentence: 'What decides, and what the program only does.',
    paragraphs: [
      'The program writes the state, asks the questions, follows the answers, presses the keys, and between games replays games to grade proposed rules. None of it ranks, scores or picks an action.',
    ],
    code: 'ruletree/walk.py · decide; ruletree/walk.py · action_of',
  },
  'rt-drawing': {
    title: 'How it works',
    sentence: 'Two systems: Jev walking the tree at every decision, and the soft loop writing new rules between games.',
    paragraphs: [
      'At every decision the program writes the state of the game as text and asks Jev the tree’s questions, one after another, from the top. The rule the answers lead to gives the action, which is held for 8 tics.',
      'Between games, the soft loop plays the training seeds. When a game fails, a rule writer proposes one rule for the moment it failed. The program checks the rule on that game and gates it on every training seed; only a rule that passes both is added.',
    ],
    code: 'ruletree/walk.py · decide; ruletree/loop.py · attempt',
  },
  'rt-provenance': {
    title: 'How this recording was made',
    sentence: 'The tree, the seed, the model and the command that recorded it.',
    paragraphs: [
      'Every decision in these recordings was made by Jev, TypeSafe’s decision model. Each recording was exported with python -m system1_doom.export --solution rule-tree, which plays the game, keeps every question and answer and every frame, and checks the files before they are shipped: it walks the tree again with the recorded answers and confirms that every action played is the action those answers lead to.',
    ],
    code: 'ruletree/bundle.py · record_episode; ruletree/bundle.py · check_recording',
  },
} satisfies Record<string, Explainer>
