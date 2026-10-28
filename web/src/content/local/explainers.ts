// What each local-models panel explains when its "?" is opened: the panels only the local models' screens have
// (`lm-`), and the rule tree's panels they share, in Laya's words (LOCAL_OVERRIDES).
import type { Explainer } from '../explainers'

export const LOCAL_PANELS = {
  'lm-workflow': {
    title: 'How the trained Laya was made',
    sentence: 'The steps from Kev’s answers to a small model that answers the tree’s questions on its own.',
    paragraphs: [
      'A decision model answers a multiple-choice question with a probability for each option. Kev and Laya answer the same request: the state as text, the question and its options. So the tree can be walked with either of them, on the computer that plays.',
      'Kev-27B answers these questions well without any training on them, but it is large. Laya is small and fast, but out of the box it answered close to chance. Training Laya on Kev’s answers gives a model that is fast and answers as Kev does.',
      'Laya is trained to give the same probabilities as Kev, not only the same pick, so it also learns how sure Kev was. The games on this site and the benchmark seeds were never used for training.',
    ],
    code: 'ruletree/teach.py · build; laya-train, from the laya package',
  },
  'lm-facts': {
    title: 'The training, in numbers',
    sentence: 'Who taught, what was learned from, and how close the student came.',
    paragraphs: [
      'The check examples come from seeds the training never saw. Same pick as Kev means that Laya’s highest-probability option was Kev’s.',
    ],
    code: 'ruletree/teach.py · build',
  },
  'lm-thor': {
    title: 'Serving Kev on this computer',
    sentence: 'How long Kev-27B takes per question on the Jetson Thor, as installed and as tuned.',
    paragraphs: [
      'The Jetson Thor’s GPU is of NVIDIA’s Blackwell generation. It multiplies 16-bit numbers at about 92 trillion operations a second, 8-bit numbers at about 190, and 4-bit numbers faster still. Kev as installed used 16-bit numbers and none of its own fused kernels, because they asked for an older version of a library.',
      'Tuned, Kev runs its fused kernels and stores its weights in 8-bit, and in 4-bit in its largest layers. A question about a state already read only needs the question’s own words, so it costs less than a question about a new state.',
    ],
    code: 'tools/kev_thor/serve_thor.py',
  },
  'lm-benchmark': {
    title: 'The benchmark',
    sentence: 'The same tree on the same 81 seeds, with each model answering every question.',
    paragraphs: [
      'A seed is a number that sets the game’s random events, so each seed is a different game. Seeds 201 to 215 and 301 to 315 are the senses and central’s benchmark seeds, 9 to 19 the seeds the tree’s rules were written on, and 20 to 59 seeds held out from that. None of them was used to train Laya.',
      'A difference of one or two games out of 81 is within chance.',
    ],
    code: 'ruletree/__main__.py · main',
  },
  'lm-questions': {
    title: 'The questions of these recordings',
    sentence:
      'Every question Laya answered in the four recordings here, asked again of its teacher and of the untrained Laya.',
    paragraphs: [
      'For some questions the state text alone settles the answer, so each answer can be marked right or wrong: whether the threats list names an enemy, which angle band the target is in, whether the target is far, and which landmark is the goal. The other questions, such as which enemy is the biggest danger, are judgements and are only compared.',
    ],
    code: 'ruletree/agreement.py · compare',
  },
  'lm-decision': {
    title: 'This decision, by each model',
    sentence:
      'Each question asked at this decision, with what Laya answered in play and what its teacher and the untrained Laya answered to the same question.',
    paragraphs: [
      'Kev and the untrained Laya were asked afterwards, with the text and options Laya was sent, so the walk shown on the other screens is the trained Laya’s. A different pick here would have led the walk elsewhere.',
      'The percentage is the probability the model gave the option it picked.',
    ],
    code: 'ruletree/site_models.py · site_answers',
  },
  'lm-totals': {
    title: 'This recording',
    sentence: 'What this game asked of Laya and how it ended.',
    paragraphs: [
      'Laya is asked one question at a time, so a decision takes as long as its questions together. When a question repeats one asked earlier in the same game, with the same text, the earlier answer is used again and no call is made.',
    ],
  },
} satisfies Record<string, Explainer>

/** The rule tree's panels as the local models' screens show them: Laya answers where Jev did. */
export const LOCAL_OVERRIDES: Record<string, Explainer> = {
  'rt-walk': {
    title: 'The questions at this decision',
    sentence:
      'Each row is one question Laya answered at this decision, in the order it was asked, followed by the action that was played.',
    paragraphs: [
      'A rule has a condition and an action. The rules under a rule are its exceptions: more specific rules that replace its action when their condition is true. At a rule that has rules under it, Laya is asked “Which of these is true right now?”, with their conditions and “None of these is true right now.” as the options. The walk moves into the rule Laya picks and asks again. When Laya picks none, or reaches a rule with nothing under it, that rule’s action is played.',
      'Some rules first ask Laya what to pay attention to: which visible enemy is the biggest danger, or which landmark is the goal. Laya’s pick is the focus. It is added to the state as a [focus] channel, and the rules under it speak about the focus. When the list has only one item, there is nothing to choose: Laya is not asked, and that item is the focus.',
      'An action can use a skill. The aim skill is a set of rules that each turn toward the focus by an amount that fits its angle. The rule that used the skill says what to do for the rest of the decision.',
      'The game waits while Laya answers, on the same computer. The action is then held for 8 tics, about a quarter of a second, and the next decision starts again at the top of the tree.',
    ],
    code: 'ruletree/walk.py · decide',
  },
  'rt-sent': {
    title: 'What Laya was sent',
    sentence:
      'The state text this question was sent with, exactly as sent. The screen is shown for you; Laya reads text only.',
    paragraphs: [
      'The state is plain text in channels, each under a [channel] header, always in the same order. The program writes it from the game: health, the enemies in view with their distance, angle and size on screen, what the last shots hit, the pickups and landmarks, the walls, the position and the last actions. Nothing in it says what to do.',
      'Every question of a decision is sent the same state text, except that the questions after a focus question also get a [focus] channel at the end, which names the item picked. When it is there, it is highlighted.',
    ],
    code: 'ruletree/game.py · Game.observe; ruletree/walk.py · with_focus',
  },
  'rt-answer': {
    title: 'What Laya answered',
    sentence:
      'Laya’s probability for every option of this question. The option with the highest probability is its answer, and the walk goes there.',
    paragraphs: [
      'Laya is a decision model of 421 million parameters, made by Convai Innovations and trained here on Kev-27B’s answers to this tree’s questions. It answers a multiple-choice question with a probability for each option in about 50 ms on this computer. The walk takes the option with the highest probability, and nothing else is weighed.',
      'A call that fails, runs out of time, or answers with an option that was not offered is a miss. The walk stops at the rule it has reached and that rule’s action is played. Nothing replaces the missing answer.',
    ],
    code: 'ruletree/walk.py · Jev.ask',
  },
  'rt-outline': {
    title: 'The tree',
    sentence: 'The rules this decision’s walk went through are marked, and the rule it ended at is outlined.',
    paragraphs: [
      'The tree is a file: its rules, the questions that pick a focus, its skills, and for each rule added by the soft loop the decision it was written for. With this file and Laya’s answers, the program can play the game.',
      'This is general-11, the same tree as on the Rule tree tab, used here as it is. How its rules were written is told there.',
    ],
    code: 'ruletree/tree.py · RuleTree',
  },
  'rt-principles': {
    title: 'Who makes each choice',
    sentence: 'What Laya decides, and what the program does.',
    paragraphs: [
      'During a game the program writes the state, asks the questions, follows the answers and presses the keys. It never ranks, scores or picks an action, apart from the random action code played when no rule at the top of the tree is true.',
    ],
    code: 'ruletree/walk.py · decide; ruletree/walk.py · action_of',
  },
  'rt-provenance': {
    title: 'How this recording was made',
    sentence: 'The tree, the seed, the model and the command that recorded it.',
    paragraphs: [
      'Every decision in these recordings was made by Laya, trained on Kev-27B’s answers, served by laya-serve on the computer that played. Each recording was exported with python -m system1_doom.export --solution rule-tree --tree-decider laya, which plays the game, keeps every question and answer and one screen image per decision, and checks the files before they are shipped: it walks the tree again with the recorded answers and confirms that every action played is the action those answers lead to.',
    ],
    code: 'ruletree/bundle.py · record_episode; ruletree/bundle.py · check_recording',
  },
}
