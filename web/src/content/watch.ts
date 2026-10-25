// Every word on the Watch screen, the landing: the recording plays at the agent's own pace beside the six
// d1-ultra instances that decided each move.
import type { Pace } from '../data/playback'
import type { BundleIndexEntry, EpisodeMeta, TickTrace } from '../schema/bundle'

export const WATCH = {
  title: 'Every action in this game is chosen by d1-ultra, Liquid AI’s decision model.',
  subtitle:
    'At each decision, five instances each answer questions about one part of the game, and a sixth, the central instance, chooses the action from their answers. The rows beside the game show what each of the six instances answered at the decision shown.',
  play: 'Play',
  pause: 'Pause',
  playLarge: 'Play the recording',
  paceGroup: 'Speed',
  pace: { real: 'Real time', slow: 'Slow' } satisfies Record<Pace, string>,
  paceTitle: {
    real: 'Real time: one decision every 8 game frames, about 0.23 seconds, as the agent played',
    slow: 'Slow: one decision per second, so the rows can be read as they change',
  } satisfies Record<Pace, string>,
  progress: 'Decision',
  again: 'Starting again from the first decision',
  honesty: 'This is a recording, replayed at the speed the agent played: one video frame per decision.',
  honestyLink: 'To watch it decide live, run it on your machine →',
  liveHonesty:
    'Live: d1-ultra is playing this episode on this machine now. Each decision appears as soon as it is made.',
  cardsTitle: 'The recordings',
  cardsNote:
    'Click a recording to play it from the start. A recording that starts from a later configuration version shows the changes System 2 made in earlier episodes.',
  nowShowing: 'Now showing',
  made: 'How this recording was made →',
}

/** Decision N of M and the game time it was made at, as the transport's counter reads. */
export function counterText(index: number, count: number, seconds: number, live: boolean): string {
  const time = `${seconds.toFixed(1)} s of game time`
  return live ? `decision ${index + 1} · ${time}, playing now` : `decision ${index + 1} of ${count} · ${time}`
}

const placeWords = (scenario: string) => (scenario === 'deadly_corridor.cfg' ? 'the corridor' : 'the level')

export const scenarioWords = (scenario: string) => scenario.replace('.cfg', '').replaceAll('_', ' ')

/** "cleared the corridor in 59 decisions, 6 kills", from the index line alone. */
export function resultWords(
  entry: Pick<BundleIndexEntry, 'scenario' | 'cleared' | 'died' | 'ticks' | 'kills'>,
): string {
  const kills = entry.kills === undefined ? '' : `, ${entry.kills} ${entry.kills === 1 ? 'kill' : 'kills'}`
  if (entry.cleared) return `cleared ${placeWords(entry.scenario)} in ${entry.ticks} decisions${kills}`
  if (entry.died) return `died after ${entry.ticks} decisions${kills}`
  return `survived ${entry.ticks} decisions${kills}`
}

/** "configuration version 1" or "configuration versions 2 → 4". */
export function versionWords(start: number, end: number): string {
  return start === end ? `configuration version ${start}` : `configuration versions ${start} → ${end}`
}

/** How a recording is named on its card and in the picker: its seed and the configuration it started from. */
export function recordingName(entry: Pick<BundleIndexEntry, 'seed' | 'configuration_start'>): string {
  return `Seed ${entry.seed}, from configuration version ${entry.configuration_start ?? 1}`
}

/** The episode was cut off before its end: the decision limit, or stopped by hand. */
export function stoppedEarly(meta: EpisodeMeta): boolean {
  return meta.result.finished_reason === 'stopped' || meta.result.finished_reason === 'max_ticks'
}

/** A live episode still being played has no result yet. */
export function stillPlaying(meta: EpisodeMeta): boolean {
  return !meta.result.finished && !meta.result.finished_reason
}

/** The line over the end frame: "Cleared the corridor: 59 decisions, 6 kills". */
export function endLine(meta: EpisodeMeta): string {
  const { result } = meta
  const kills = `${result.kills} ${result.kills === 1 ? 'kill' : 'kills'}`
  if (stillPlaying(meta)) return `Still playing: ${meta.tick_count} decisions so far`
  if (result.cleared) return `Cleared ${placeWords(meta.scenario)}: ${result.ticks} decisions, ${kills}`
  if (result.died) return `Died after ${result.ticks} decisions, ${kills}`
  if (result.finished_reason === 'max_ticks')
    return `Stopped at the decision limit after ${result.ticks} decisions, ${kills}`
  if (stoppedEarly(meta)) return `Stopped by hand after ${result.ticks} decisions, ${kills}`
  return `Survived ${result.ticks} decisions, ${kills}`
}

/** The stage image's text for one decision: what was on screen and what the instances did with it. */
export function frameAlt(tick: TickTrace, index: number, count: number): string {
  const enemies = tick.state?.enemies?.length ?? 0
  const health = tick.state?.health
  const seen = enemies === 0 ? 'no enemy in view' : enemies === 1 ? 'one enemy in view' : `${enemies} enemies in view`
  const act = tick.executed_action
    ? `the central instance chose ${tick.executed_action.replaceAll('_', ' ')}`
    : 'the central instance gave no usable answer'
  return `The game at decision ${index + 1} of ${count}: ${seen}${health === undefined ? '' : `, health ${Math.round(health)}`}; ${act}.`
}
