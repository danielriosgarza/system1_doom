// The local models' per-question record: for each question asked in a rule-tree recording, what each
// open-weight model answered when asked the same question with the same text (`models.json`, written by
// `python -m system1_doom.ruletree.site_models`). Nothing here decides anything.
import { BundleError, parseJson } from './loader'

/** One model's answer to one question: the option it picked and the probability it gave it. */
export type ModelPick = [option: string, probability: number]

/** One question of a recording: where it was asked, and each model's answer. */
export interface ModelQuestion {
  decision: number
  /** The step's index in the decision's walk (`RuleTreeDecision.steps`). */
  step: number
  kind: 'rule' | 'focus'
  node: string
  picks: Record<string, ModelPick>
}

/** A recording's `models.json`: the models in the order the page shows them, and every question. */
export interface ModelAnswers {
  models: string[]
  answers: ModelQuestion[]
}

/** `models.json` read and checked; null when the recording has none (an empty text). */
export function parseModels(text: string, file: string): ModelAnswers | null {
  if (!text.trim()) return null
  const raw = parseJson<Partial<ModelAnswers>>(text, file)
  if (!Array.isArray(raw.models) || !Array.isArray(raw.answers)) {
    throw new BundleError(`${file} has no models or answers list.`)
  }
  for (const a of raw.answers) {
    if (typeof a.decision !== 'number' || typeof a.step !== 'number' || typeof a.picks !== 'object' || !a.picks) {
      throw new BundleError(`${file} has a question without its decision, step or picks.`)
    }
  }
  return { models: raw.models, answers: raw.answers }
}

/** The questions of one decision, in the order they were asked. */
export function questionsAt(models: ModelAnswers, decision: number): ModelQuestion[] {
  return models.answers.filter((a) => a.decision === decision).sort((a, b) => a.step - b.step)
}

/** How often each model picked what the model that played picked, over every question of the recording. */
export function agreementWithPlayed(
  models: ModelAnswers,
  playedPick: (q: ModelQuestion) => string | null,
): Record<string, { same: number; of: number }> {
  const out: Record<string, { same: number; of: number }> = {}
  for (const m of models.models) out[m] = { same: 0, of: 0 }
  for (const q of models.answers) {
    const played = playedPick(q)
    if (played === null) continue
    for (const m of models.models) {
      const pick = q.picks[m]
      const tally = out[m]
      if (!pick || !tally) continue
      tally.of += 1
      if (pick[0] === played) tally.same += 1
    }
  }
  return out
}
