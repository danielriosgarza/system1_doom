// Every word on the Watch screen, the landing: the recording plays at the agent's own pace beside the six
// levels of its decision chain. Each insider's word here sits next to the plain words for it.
import {
  type LevelId,
  moduleOpinions,
  pct,
  prettyId,
  stillPlaying,
  stoppedEarly,
  strategyName,
  towerLevels,
} from '../data/derive'
import type { Pace } from '../data/playback'
import type { BundleIndexEntry, EpisodeMeta, ProposalTrace, TickTrace } from '../schema/bundle'

export const WATCH = {
  title: 'A Doom agent built from a chain of six small decisions, made four times a second.',
  subtitle: 'Watch it play; each row shows what one level just decided.',
  chainTitle: 'The decision chain',
  chainNote: 'Slowest level at the top. Click a row to see why it chose that.',
  rowTitle: 'Open this level in The chain, at this decision',
  play: 'Play',
  pause: 'Pause',
  playLarge: 'Play the recording',
  paceGroup: 'Pace',
  pace: { real: 'Real time', slow: 'Slow' } satisfies Record<Pace, string>,
  paceTitle: {
    real: 'The agent’s own pace: one decision every 8 game frames, about 0.23 s',
    slow: 'One decision a second, to read the chain as it changes',
  } satisfies Record<Pace, string>,
  progress: 'Decision',
  again: 'Starting again from the first decision',
  honesty: 'A recording, replayed at the agent’s own pace: one frame per decision.',
  honestyLink: 'To watch it decide live, run it on your machine →',
  liveHonesty: 'Live: the agent is playing this episode on this machine now, and each decision appears as it is made.',
  help: {
    title: 'How to read this',
    lines: [
      'This is the agent playing, four decisions a second.',
      'Each row is one level of its decision chain; the top rows change rarely, the bottom rows every decision.',
      'Pause anywhere, or click a row, to see why.',
    ],
    dismiss: 'Got it',
    dismissTitle: 'Hide this card; it stays hidden in this browser',
  },
  cardsTitle: 'The recordings',
  cardsNote:
    'Each opens here and plays from the start. Two recordings with the same run number begin from the same game.',
  nowShowing: 'Now showing',
  made: 'How this recording was made →',
}

/** Decision N of M and the game time it was made at, as the transport's counter reads. */
export function counterText(index: number, count: number, seconds: number, live: boolean): string {
  const time = `${seconds.toFixed(1)} s of play`
  return live ? `decision ${index + 1} · ${time}, playing now` : `decision ${index + 1} of ${count} · ${time}`
}

// ---------------------------------------------------------------------------------------------
// The chain strip: the six levels of the tower, each as one row in plain words.

export const CHAIN_LEVELS: Record<LevelId, { name: string; gloss: string }> = {
  gate: { name: 'Growing the menu', gloss: 'adds a new move when a decider keeps failing' },
  steering: { name: 'Steering', gloss: 'which playbook the agent is following' },
  menu: { name: 'The menu', gloss: 'which moves are allowed right now' },
  opinions: { name: 'Five opinions', gloss: 'five small deciders each name a move' },
  arbiter: { name: 'One decision', gloss: 'one arbiter picks the move' },
  motor: { name: 'Act', gloss: 'the keys pressed for the next 8 frames' },
}

export interface ChainRow {
  id: LevelId
  name: string
  gloss: string
  /** What the level chose at this decision, in plain words. */
  value: string
  /** A bar's length in [0, 1], where the level has one share worth drawing; null elsewhere. */
  share: number | null
  /** What the bar measures, for its tooltip. */
  shareLabel: string
  /** Nothing happened at this level this decision. */
  idle: boolean
  /** The value differs from the previous decision's: the row pulses. */
  changed: boolean
}

/** How the arbiter's pick rule reads after the action it picked. */
function ruleWords(tick: TickTrace): string {
  const arbiter = tick.arbiter
  switch (arbiter?.pick_rule) {
    case 'sampled':
      return 'a close race, drawn by chance'
    case 'committed':
      return `${arbiter.committed_by ?? 'one decider'} insisted`
    case 'explored':
      return 'a random try'
    case 'critical_cached':
      return 'out of time: the last pick again'
    default:
      return 'top score'
  }
}

/**
 * The keys held over the motor's steps, in the order first pressed, each with the number of steps it was held
 * when more than one: "strafe left ×2, shoot ×4, strafe right ×2" for a weave that fires on every step.
 */
export function keysPressed(steps: string[]): string {
  const held = new Map<string, number>()
  for (const step of steps) {
    for (const key of step.split('+')) if (key && key !== 'idle') held.set(key, (held.get(key) ?? 0) + 1)
  }
  return [...held].map(([key, n]) => (n > 1 ? `${prettyId(key)} ×${n}` : prettyId(key))).join(', ') || 'nothing pressed'
}

function steeringValue(tick: TickTrace): Pick<ChainRow, 'value' | 'share' | 'shareLabel'> {
  const s = tick.steering
  if (!s) return { value: 'not recorded', share: null, shareLabel: '' }
  const after = strategyName(s.active_after)
  const value =
    s.choice === 'switch_to_archived_strategy'
      ? `switch to ${after}`
      : s.choice === 'explore_variation'
        ? `explore a variation of ${after}`
        : s.choice === 'request_new_strategy_proposal'
          ? 'ask for a new playbook'
          : `continue: ${after}`
  const share = s.probabilities?.[s.choice] ?? 0
  return { value, share, shareLabel: `${pct(share)} for this choice of four` }
}

/** The six rows at one decision, slowest first, without the comparison with the decision before. */
function chainValues(tick: TickTrace, meta: EpisodeMeta, proposals: ProposalTrace[]): Omit<ChainRow, 'changed'>[] {
  const levels = towerLevels(tick, meta, proposals)
  const level = (id: LevelId) => levels.find((l) => l.id === id)
  const row = (id: LevelId, fields: Pick<ChainRow, 'value' | 'share' | 'shareLabel'> & { idle?: boolean }) => ({
    id,
    ...CHAIN_LEVELS[id],
    idle: false,
    ...fields,
  })

  const gate = level('gate')
  const proposal = gate?.menu[0]?.label ?? 'a macro'
  const failed = gate?.candidates.find((c) => c.failed)?.label
  const gateValue =
    gate?.choice === 'admitted'
      ? `added ${proposal} to the menu`
      : gate?.choice === 'rejected'
        ? `turned ${proposal} away${failed ? ` at the ${failed} check` : ''}`
        : gate?.choice === 'requested'
          ? `${tick.slow_path_request?.module ?? 'a decider'} asked for a new move`
          : 'nothing proposed'

  const menu = level('menu')
  const legal = tick.available_actions.length
  const vocabulary = Math.max(legal, menu?.menuSize ?? legal)

  const opinions = moduleOpinions(tick)
  const agree = opinions.filter((o) => o.agrees).length
  const opinionsValue =
    opinions.length === 0
      ? 'no opinions: the last pick was kept'
      : agree === 0
        ? `none of ${opinions.length} agree with the pick`
        : `${agree} of ${opinions.length} agree with the pick`

  return [
    row('gate', { value: gateValue, share: null, shareLabel: '', idle: gate?.idle ?? false }),
    row('steering', steeringValue(tick)),
    row('menu', {
      value: `${legal} of ${vocabulary} allowed`,
      share: vocabulary > 0 ? legal / vocabulary : 0,
      shareLabel: `${legal} of the ${vocabulary} moves it knows are allowed`,
    }),
    row('opinions', {
      value: opinionsValue,
      share: opinions.length > 0 ? agree / opinions.length : null,
      shareLabel: `${agree} of ${opinions.length} deciders named the pick first`,
      idle: opinions.length === 0,
    }),
    row('arbiter', { value: `${prettyId(tick.selected_action)} · ${ruleWords(tick)}`, share: null, shareLabel: '' }),
    row('motor', { value: keysPressed(tick.primitive_steps_executed), share: null, shareLabel: '' }),
  ]
}

/** The six rows at one decision, each marked changed when its words differ from the decision before. */
export function chainRows(
  tick: TickTrace,
  prev: TickTrace | null,
  meta: EpisodeMeta,
  proposals: ProposalTrace[],
): ChainRow[] {
  const before = prev ? chainValues(prev, meta, proposals) : null
  return chainValues(tick, meta, proposals).map((row, i) => ({
    ...row,
    changed: before !== null && before[i]?.value !== row.value,
  }))
}

// ---------------------------------------------------------------------------------------------
// The recordings, as cards and as the stage's last line.

const placeWords = (scenario: string) => (scenario === 'deadly_corridor.cfg' ? 'the corridor' : 'the level')

/**
 * Who played a recording. The index carries no brains, so d1-ultra's advice is read from the open bundle's
 * meta when there is one, and otherwise from the title export gives such a recording.
 */
export function brainOf(entry: BundleIndexEntry, meta: EpisodeMeta | null): { name: string; gloss: string } {
  if (entry.model === 'heuristics') return { name: 'Heuristics only', gloss: 'hand-written rules, nothing learned' }
  const d1 = meta && meta.name === entry.name ? meta.brains.d1_ultra : /d1-ultra/i.test(entry.title)
  return d1
    ? {
        name: 'Trained networks with d1-ultra’s advice',
        gloss: 'the same networks, also advised by d1-ultra, an outside decision model',
      }
    : { name: 'Trained networks', gloss: 'the hand-written rules, weighed by networks trained on earlier games' }
}

/** "cleared the corridor in 52 decisions", from the index line alone. */
export function resultWords(entry: Pick<BundleIndexEntry, 'scenario' | 'cleared' | 'died' | 'ticks'>): string {
  if (entry.cleared) return `cleared ${placeWords(entry.scenario)} in ${entry.ticks} decisions`
  if (entry.died) return `died after ${entry.ticks} decisions`
  return `survived ${entry.ticks} decisions`
}

/** The line over the end frame: "Cleared the corridor: 52 decisions, 6 kills". */
export function endLine(meta: EpisodeMeta): string {
  const { result } = meta
  const kills = `${result.kills} ${result.kills === 1 ? 'kill' : 'kills'}`
  if (stillPlaying(meta)) return `Still playing: ${meta.tick_count} decisions so far`
  if (result.cleared) return `Cleared ${placeWords(meta.scenario)}: ${result.ticks} decisions, ${kills}`
  if (result.died) return `Died after ${result.ticks} decisions, ${kills}`
  if (stoppedEarly(meta)) return `Stopped by hand after ${result.ticks} decisions, ${kills}`
  return `Survived ${result.ticks} decisions, ${kills}`
}

/** The stage image's text for one decision: what was on screen and what the agent did with it. */
export function frameAlt(tick: TickTrace, index: number, count: number): string {
  const enemies = tick.state?.enemies?.length ?? 0
  const health = tick.state?.health
  const seen = enemies === 0 ? 'no enemy in view' : enemies === 1 ? 'one enemy in view' : `${enemies} enemies in view`
  return `The game at decision ${index + 1} of ${count}: ${seen}${health === undefined ? '' : `, health ${Math.round(health)}`}; the agent picks ${prettyId(tick.selected_action)}.`
}
