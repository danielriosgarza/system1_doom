// The words for the instances: the strip on Watch, the configuration line, and The instances screen.
import { type CentralRow, type ConfigurationAt, type VersionEntry, pct, words } from '../data/readings'

export const STRIP = {
  title: 'The instances at this decision',
  note: 'Each row is one d1-ultra call. Click a row to see what it saw and answered.',
  rowTitle: 'Open this instance at this decision',
  spoke: 'spoke',
  silent: 'silent',
  missed: 'missed',
  followed: 'followed',
  central: 'central',
  act: 'Act',
  actGloss: 'the keys held for 8 frames',
}

export const INSTANCES = {
  title: (decision: number) => `Decision ${decision}: what each instance saw and answered`,
  intro:
    'Six d1-ultra calls made this decision. Pick an instance to read the evidence it was sent, exactly as sent, and every answer it gave.',
  tabs: 'Instances',
  scope: 'Its scope at this decision',
  hidden: 'Not shown to it',
  frame: 'The screen it was sent',
  noFrame: 'No screen: frame is not in its scope.',
  text: 'The state text, verbatim',
  speak: 'Speak',
  speakNote: (yesAt: number) => `It speaks at ${yesAt.toFixed(2)} or more; the line marks that.`,
  action: 'Action',
  reason: 'Reason',
  choice: 'Its choice',
  heard: 'The messages it heard',
  heardNone: 'No sense spoke: it chose from the menu and its own channels.',
  miss: 'This call missed',
  raw: 'The raw answer, as returned',
  executed: 'executed',
}

/** Why a call missed, in words. */
export function missWords(reason: string | null): string {
  switch (reason) {
    case 'timeout':
      return 'no answer within the call budget'
    case 'error':
      return 'the call failed'
    case 'http_429_exhausted':
      return 'rate-limited, retries used up'
    case 'off_menu':
      return 'it answered with something off the menu'
    case 'malformed':
      return 'its probabilities were malformed'
    default:
      return 'no usable answer'
  }
}

/** The central row's words after its action: how the answer became the executed action. */
export function pickWords(row: CentralRow): string {
  if (row.kind === 'missed') return `missed (${missWords(row.missReason)}): no keys held`
  const heard = row.heard === 0 ? 'heard no message' : `heard ${row.heard} message${row.heard === 1 ? '' : 's'}`
  const how =
    row.kind === 'drawn' ? `drawn under explore at ${pct(row.probability)}` : `its top answer, ${pct(row.probability)}`
  return `${how}${row.tie ? ', a tie broken by menu order' : ''} · ${heard}`
}

/** The configuration line's three parts. */
export function configWords(at: ConfigurationAt): { version: string; change: string; trial: string } {
  const version = `Configuration version ${at.version}`
  const entry: VersionEntry | null = at.entry
  let change: string
  if (!entry || entry.status === 'start') {
    change = at.version === 1 ? 'no change yet: the design’s initial configuration' : 'last change: before this episode'
  } else if (entry.status === 'revert') {
    change = `last change: reverted ${words(entry.change.replace(/^revert:/, ''))}`
  } else {
    change = `last change: ${entry.changes.join('; ') || words(entry.change)}`
  }
  const trial = at.trial
    ? `trial in flight: ${Math.min(at.trial.decisions, at.trial.of)} of ${at.trial.of} decisions`
    : 'no trial in flight'
  return { version, change, trial }
}
