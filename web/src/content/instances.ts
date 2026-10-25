// The words for the instances: the strip on Watch, the configuration line, and The instances screen.
import { type CentralRow, type ConfigurationAt, type VersionEntry, pct, words } from '../data/readings'
import { type Decider, deciderName } from './decider'

export const STRIP = {
  title: 'The six instances at this decision',
  note: (decider: Decider) =>
    `Each row is one ${deciderName(decider)} call. A sense that spoke sent the central instance a message: its strength, a recommended action and a reason. Silent means it sent none; missed means it gave no usable answer. Click a row to see what that instance was sent and what it answered.`,
  rowTitle: 'Open this instance at this decision',
  spoke: 'spoke',
  silent: 'silent',
  missed: 'missed',
  followed: 'followed',
  central: 'central',
  act: 'Act',
  actGloss: 'the keys held for the 8 game frames of this decision',
}

export const INSTANCES = {
  title: (decision: number) => `Decision ${decision}: what each instance was sent and what it answered`,
  intro: (decider: Decider) =>
    `Six ${deciderName(decider)} calls made this decision: five senses and the central instance. Pick one to read the evidence it was sent, exactly as sent, and every answer it returned.`,
  tabs: 'Instances',
  scope: 'Channels it was shown',
  hidden: 'Channels it was not shown',
  frame: 'The screen image it was sent',
  noFrame: 'No screen image: the frame channel is not in its scope.',
  text: 'The evidence text, exactly as sent',
  speak: 'Speak',
  speakNote: (yesAt: number, decider: Decider) =>
    `${deciderName(decider)}’s probability that this sense should send a message now. At ${yesAt.toFixed(2)} or more it does; the mark on the bar is that point.`,
  action: 'Action',
  reason: 'Reason',
  choice: 'Chosen action',
  heard: 'The messages it received',
  heardNone: 'No sense sent a message. The central instance chose from the menu and its other channels alone.',
  miss: 'This call missed',
  raw: 'The raw answer, as returned',
  executed: 'executed',
}

/** Why a call missed, in words. */
export function missWords(reason: string | null): string {
  switch (reason) {
    case 'timeout':
      return 'no answer within the time allowed for a call'
    case 'error':
      return 'the call failed'
    case 'http_429_exhausted':
      return 'rate-limited by the API, and the retries ran out'
    case 'off_menu':
      return 'it answered with something off the menu'
    case 'malformed':
      return 'its probabilities were malformed (negative, or not summing to 1)'
    default:
      return 'no usable answer'
  }
}

/** The central row's words after its action: how the answer became the executed action. */
export function pickWords(row: CentralRow): string {
  if (row.kind === 'missed') return `missed (${missWords(row.missReason)}): no keys pressed`
  const heard = row.heard === 0 ? 'received no message' : `received ${row.heard} message${row.heard === 1 ? '' : 's'}`
  const how =
    row.kind === 'drawn'
      ? `drawn at random under the explore level, ${pct(row.probability)}`
      : `its top answer, ${pct(row.probability)}`
  return `${how}${row.tie ? ', a tie broken by menu order' : ''} · ${heard}`
}

/** The configuration line's three parts. */
export function configWords(at: ConfigurationAt): { version: string; change: string; trial: string } {
  const version = `Configuration version ${at.version}`
  const entry: VersionEntry | null = at.entry
  let change: string
  if (!entry || entry.status === 'start') {
    change =
      at.version === 1 ? 'no change yet: the initial configuration from the design' : 'last change: before this episode'
  } else if (entry.status === 'revert') {
    change = `last change: reverted ${words(entry.change.replace(/^revert:/, ''))}`
  } else {
    change = `last change: ${entry.changes.join('; ') || words(entry.change)}`
  }
  const trial = at.trial
    ? `trial in progress: ${Math.min(at.trial.decisions, at.trial.of)} of ${at.trial.of} decisions observed`
    : 'no trial in progress'
  return { version, change, trial }
}
