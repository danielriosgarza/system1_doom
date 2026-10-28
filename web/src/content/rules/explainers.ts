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
      'Some rules first ask Jev what to pay attention to: which visible enemy is the biggest danger, or which landmark is the goal. Jev’s pick is the focus. It is added to the state as a [focus] channel, and the rules under it speak about the focus. When the list has only one item, there is nothing to choose: Jev is not asked, and that item is the focus.',
      'An action can use a skill. The aim skill is a set of rules that each turn toward the focus by an amount that fits its angle. The rule that used the skill says what to do for the rest of the decision: fire, walk forward and fire, or walk forward.',
      'The game waits while Jev answers. The action is then held for 8 tics, about a quarter of a second, and the next decision starts again at the top of the tree.',
    ],
    code: 'ruletree/walk.py · decide',
  },
  'rt-sent': {
    title: 'What Jev was sent',
    sentence: 'The state text this question was sent with, exactly as sent, and the screen sent with it as an image.',
    paragraphs: [
      'The state is plain text in channels, each under a [channel] header, always in the same order. The program writes it from the game: health, the enemies in view with their distance, angle and size on screen, what the last shots hit, the pickups and landmarks, the walls, the position and the last actions. Nothing in it says what to do.',
      'Every question of a decision is sent the same screen and the same state text, except that the questions after a focus question also get a [focus] channel at the end, which names the item picked. When it is there, it is highlighted. A question asked before any focus has none.',
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
      'When a focus list has only one item, there is nothing to choose: Jev is not asked, and that item is the focus. Each question Jev is asked is one call.',
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
      'A seed is a number that sets the game’s random events, so each seed is a different game. The training seeds, 9 to 19, are the games the soft loop plays and writes rules for.',
      'A pass plays every training seed once with the tree as it is. Each game that died or stopped making progress is a failure. For a failure, a rule writer, Claude or Codex, proposes one rule (or a small group) for the moment it went wrong; the rule is added or rejected. The held-out seeds are played after every training seed clears.',
      'The same tree can clear a different number of seeds each time it plays them, because Jev’s answers can differ from one run to the next.',
    ],
    code: 'ruletree/loop.py · run_loop',
  },
  'rt-round': {
    title: 'This step',
    sentence: 'What happened at the step picked on the left.',
    paragraphs: [
      'A proposed rule is first checked on the game it was written for, with three tests.',
      'Reaches the rule: at the decision it was written for, the walk now goes into the new rule.',
      'Earlier rules unchanged: the decisions the earlier rules were written for still reach their rules, or their games end no worse.',
      'Ends better: the game is replayed twice from that decision, once with the old tree and once with the new one, for up to 24 decisions after the point where it failed. The new tree must do better in one of three ways: the player stays alive where it died, it reaches the goal where it did not, or it ends with no less health and no less distance and more of at least one.',
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
    sentence:
      'Each cell gives two runs: before, then after, a fix to how the state text shows enemies’ angles. The tree played 81 seeds; the senses and central played the 30 seeds 201 to 215 and 301 to 315.',
    paragraphs: [
      'Every game of the benchmark was played afresh, with new answers from Jev. Seeds 201 to 215 and 301 to 315 are the senses and central’s benchmark seeds; neither solution was written or tuned on them. Seeds 40 to 59 were never played while the trees were written.',
    ],
    code: 'ruletree/__main__.py · main',
  },
  'rt-uses': {
    title: 'Which rules the walks reached',
    sentence:
      'For each rule, at how many decisions of this recording the walk went into it, and at how many it ended there.',
    paragraphs: [
      'A walk goes through several rules and ends at one. When it ends at a rule of the aim skill, that rule turns toward the focus, and the rule that used the skill gives the rest of the decision, such as fire. That is why a rule such as r1 can be reached at many decisions and never be where a walk ends. When none of the aim skill’s rules is true, the walk ends at aim itself, and the action of the rule that used the skill is played without a turn.',
    ],
  },
  'rt-totals': {
    title: 'This recording',
    sentence: 'What this game cost and how it ended.',
    paragraphs: [
      'Jev is asked one question at a time, so a decision takes as long as its questions together. When a question repeats one asked earlier in the same game, with the same text and screen, the earlier answer is used again and no call is made, so it adds no call and no cost.',
    ],
  },
  'rt-outline': {
    title: 'The tree',
    sentence: 'The rules this decision’s walk went through are marked, and the rule it ended at is outlined.',
    paragraphs: [
      'The tree is a file: its rules, the questions that pick a focus, its skills, and for each rule added by the soft loop the decision it was written for. With this file and Jev’s answers, the program can play the game.',
      'general-9 has 9 rules, written before the soft loop ran. general-11 and codex-11 each grew from general-9 to 11 rules in the soft loop, with Claude and with Codex as the rule writer. Rules are numbered as they are added, and the count includes the top of the tree and the aim skill, so the first rule the soft loop added is r11 and there is no r10.',
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
    title: 'Who makes each choice',
    sentence: 'What Jev decides, and what the program does.',
    paragraphs: [
      'During a game the program writes the state, asks the questions, follows the answers and presses the keys. It never ranks, scores or picks an action, apart from the random action code played when no rule at the top of the tree is true. Between games it replays games to grade proposed rules.',
    ],
    code: 'ruletree/walk.py · decide; ruletree/walk.py · action_of',
  },
  'rt-drawing': {
    title: 'How it works',
    sentence:
      'Two parts: the walk down the tree at every decision, with Jev answering each question, and the soft loop adding rules between games.',
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
      'Every decision in these recordings was made by Jev, TypeSafe’s decision model. Each recording was exported with python -m system1_doom.export --solution rule-tree, which plays the game, keeps every question and answer and one screen image per decision, and checks the files before they are shipped: it walks the tree again with the recorded answers and confirms that every action played is the action those answers lead to.',
    ],
    code: 'ruletree/bundle.py · record_episode; ruletree/bundle.py · check_recording',
  },
} satisfies Record<string, Explainer>
