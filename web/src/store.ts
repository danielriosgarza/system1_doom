// A tiny external store: the solution shown, one episode, one current tick, the screen, and the viewer's settings.
import { useEffect, useSyncExternalStore } from 'react'
import {
  LIVE_NAME,
  type LiveEvent,
  type LiveStatus,
  applyLiveEvent,
  fetchLiveStatus,
  mergedEpisodes,
  subscribeLive,
} from './data/live'
import {
  type EpisodeBundle,
  type EpisodeIndex,
  SUPPORTED_SCHEMA_VERSION,
  defaultEpisode,
  loadEpisode,
  loadIndex,
} from './data/loader'
import { END_HOLD_MS, PACE_MS, type Pace } from './data/playback'
import { type RulesBundle, defaultRulesEpisode, loadRulesEpisode } from './data/rules'
import type { BundleIndexEntry } from './schema/bundle'

export type Theme = 'dark' | 'light'

/** The two ways this package plays: the senses and central, and the rule tree. */
export type Solution = 'senses' | 'rules'
export type SensesScreen = 'watch' | 'instances' | 'slow' | 'learning' | 'menu' | 'reference'
export type RulesScreen = 'watch' | 'questions' | 'written' | 'results' | 'tree' | 'reference'
export type Screen = SensesScreen | RulesScreen

/** The side tab's two tabs, in its order. */
export const SOLUTIONS: Array<{ id: Solution; label: string }> = [
  { id: 'senses', label: 'Senses and central' },
  { id: 'rules', label: 'Rule tree' },
]

/** The senses and central's screens, in the order the tabs and the keys 1 to 6 list them; the ids are the URL's. */
export const SCREENS: Array<{ id: SensesScreen; label: string }> = [
  { id: 'watch', label: 'Watch' },
  { id: 'instances', label: 'The instances' },
  { id: 'slow', label: 'The slow system' },
  { id: 'learning', label: 'Learning' },
  { id: 'menu', label: 'Growing the menu' },
  { id: 'reference', label: 'Reference' },
]

/** The rule tree's screens, at the same positions: screen 2 of one solution is screen 2 of the other. */
export const RULE_SCREENS: Array<{ id: RulesScreen; label: string }> = [
  { id: 'watch', label: 'Watch' },
  { id: 'questions', label: 'The questions' },
  { id: 'written', label: 'How the rules were written' },
  { id: 'results', label: 'Results' },
  { id: 'tree', label: 'The rule tree' },
  { id: 'reference', label: 'Reference' },
]

export const screensOf = (solution: Solution): Array<{ id: Screen; label: string }> =>
  solution === 'rules' ? RULE_SCREENS : SCREENS

const hasScreen = (solution: Solution, screen: string | undefined): screen is Screen =>
  screensOf(solution).some((s) => s.id === screen)

export interface AppState {
  index: EpisodeIndex | null
  /** Which solution's screens show; the side tab switches it. */
  solution: Solution
  /** The senses and central's open recording. */
  bundle: EpisodeBundle | null
  /** The rule tree's open recording. */
  rules: RulesBundle | null
  loading: boolean
  error: string | null
  /** Position in bundle.ticks (or in rules.decisions), not the tick number. */
  tickIndex: number
  screen: Screen
  theme: Theme
  /** The instance open on The instances: a sense's name or `central`. */
  instance: string
  /** The step of the walk open on The questions, by its position in the decision's steps. */
  question: number
  /** The rule open on The rule tree; null shows the rule the decision's walk ended at. */
  rule: string | null
  /** The entry of the build record open on How the rules were written; null opens the first proposal. */
  round: number | null
  playing: boolean
  /** Real time (one decision every 8 game frames) or slow (one a second). */
  pace: Pace
  /** Start playing once the open recording's first frames are decoded: a fresh visit and a recording card ask it. */
  playWhenReady: boolean
  /**
   * The landing's own playback: at the end, hold the end frame and start again. Any interaction ends it: a pause,
   * a seek, a card, a row, another screen; so does following live play.
   */
  loop: boolean
  /** Playback ran past the last decision; Watch shows the end frame and the result until the cursor moves. */
  ended: boolean
  /** Playback has run in this visit; until it has, Watch offers a large Play button on the frame. */
  played: boolean
  /** A panel to scroll to and flash once its screen is showing. */
  focusPanel: string | null
  /** The glossary entry the Reference screen scrolls to and marks; not in the URL. */
  term: string | null
  /** What `python -m system1_doom.serve` is playing; null when there is no live mode here. */
  live: LiveStatus | null
  /**
   * The viewer follows live play: the cursor stays on the newest tick of the live episode as ticks arrive,
   * and each new episode is opened as it starts. Any move of the cursor, a play or another episode ends it.
   */
  following: boolean
  /** The live episode the viewer has open, kept after it ends so the bar can say so; null otherwise. */
  liveOpen: string | null
}

type Settings = Partial<Pick<AppState, 'theme' | 'pace' | 'solution'>>

const SETTINGS_KEY = 'system1-doom-site'

function readSettings(): Settings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY)
    return raw ? (JSON.parse(raw) as Settings) : {}
  } catch {
    return {}
  }
}

function writeSettings(settings: Settings): void {
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
  } catch {
    // Private windows and blocked storage: settings simply do not persist.
  }
}

const saved = typeof window === 'undefined' ? {} : readSettings()
const prefersLight =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-color-scheme: light)').matches
/** The theme follows the system until the viewer picks one; only a picked theme is saved. */
let themePicked = saved.theme === 'light' || saved.theme === 'dark'

let state: AppState = {
  index: null,
  solution: saved.solution === 'rules' ? 'rules' : 'senses',
  bundle: null,
  rules: null,
  loading: true,
  error: null,
  tickIndex: 0,
  screen: 'watch',
  theme: themePicked ? (saved.theme as Theme) : prefersLight ? 'light' : 'dark',
  instance: 'survival',
  question: 0,
  rule: null,
  round: null,
  playing: false,
  pace: saved.pace === 'slow' ? 'slow' : 'real',
  playWhenReady: false,
  loop: false,
  ended: false,
  played: false,
  focusPanel: null,
  term: null,
  live: null,
  following: false,
  liveOpen: null,
}

const listeners = new Set<() => void>()

export function getState(): AppState {
  return state
}

export function setState(patch: Partial<AppState>): void {
  const next = { ...state, ...patch }
  if (next.theme !== state.theme) themePicked = true
  if (next.theme !== state.theme || next.pace !== state.pace || next.solution !== state.solution) {
    writeSettings({ pace: next.pace, solution: next.solution, ...(themePicked ? { theme: next.theme } : {}) })
  }
  state = next
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useApp<T>(selector: (s: AppState) => T): T {
  const get = () => selector(state)
  // The same snapshot on the server, where the glossary's tests render linked text.
  return useSyncExternalStore(subscribe, get, get)
}

/** How many decisions the open recording of the solution showing has. */
export function decisionCount(s: AppState = state): number {
  return s.solution === 'rules' ? (s.rules?.decisions.length ?? 0) : (s.bundle?.ticks.length ?? 0)
}

/** The name of the open recording of the solution showing. */
export function openName(s: AppState = state): string | null {
  return (s.solution === 'rules' ? s.rules?.name : s.bundle?.name) ?? null
}

// ---------------------------------------------------------------------------------------------
// The URL hash: `#<episode name>/<tick>/<screen>`; without a screen it means The instances, so a link to a
// decision opens that decision. `#live/<screen>` follows the live episode, whichever it is; plain `#live`
// lands on Watch. The rule tree's are `#rules/<episode name>/<decision>/<screen>`; without a screen it means The
// questions. While a recording plays, the hash keeps the tick it started from and is written when playback
// stops: browsers limit how often a page may rewrite its address, and real time is more than four decisions a
// second.

const LIVE_HASH = 'live'
const RULES_HASH = 'rules'

/** The viewer asked the system for less motion: nothing plays on its own, and nothing fades. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

interface Wanted {
  /** Null for a visit without a hash. */
  solution: Solution | null
  episode: string | null
  tick: number | null
  screen: Screen | null
}

function readHash(): Wanted {
  const parts = decodeURIComponent(window.location.hash.replace(/^#/, '')).split('/')
  const rules = parts[0] === RULES_HASH
  const [episode, tick, screen] = rules ? parts.slice(1) : parts[0] === LIVE_HASH ? [LIVE_HASH, '', parts[1]] : parts
  const parsed = tick === undefined || tick === '' ? NaN : Number(tick)
  const solution: Solution | null = rules ? 'rules' : episode ? 'senses' : null
  return {
    solution,
    episode: episode || null,
    tick: Number.isInteger(parsed) ? parsed : null,
    screen: hasScreen(solution ?? 'senses', screen) ? screen : null,
  }
}

/** Ticks replace the history entry; a change of screen adds one, so Back returns to the last screen. */
function writeHash(push = false): void {
  const { bundle, rules, solution, tickIndex, screen, following, live } = state
  let hash: string
  if (solution === 'rules') {
    if (!rules) return
    hash = `#${RULES_HASH}/${encodeURIComponent(rules.name)}/${rules.decisions[tickIndex]?.decision ?? 0}/${screen}`
  } else {
    if (!bundle) return
    const tick = bundle.ticks[tickIndex]?.tick ?? 0
    hash =
      following && live?.current === bundle.name
        ? `#${LIVE_HASH}/${screen}`
        : `#${encodeURIComponent(bundle.name)}/${tick}/${screen}`
  }
  if (window.location.hash === hash) return
  if (push) window.history.pushState(null, '', hash)
  else window.history.replaceState(null, '', hash)
}

// ---------------------------------------------------------------------------------------------
// Actions.

/** What any interaction does to the landing's own playback: no more looping, and no start still waiting. */
const INTERACTED: Partial<AppState> = { loop: false, playWhenReady: false }

/** Move the cursor; any move the viewer makes stops following the live episode and the landing's looping. */
export function setTickIndex(index: number): void {
  const count = decisionCount()
  if (count === 0) return
  const clamped = Math.max(0, Math.min(count - 1, index))
  if (clamped !== state.tickIndex || state.following || state.ended || state.loop || state.playWhenReady) {
    setState({ tickIndex: clamped, following: false, ended: false, ...INTERACTED })
  }
  writeHash()
}

export function step(delta: number): void {
  setTickIndex(state.tickIndex + delta)
}

/**
 * Switch screen. Leaving the landing while it plays on its own pauses it, so the next screen holds still on the
 * decision that was showing; playback the viewer started carries on. A screen only the other solution has
 * switches to that solution.
 */
export function setScreen(screen: Screen): void {
  if (!hasScreen(state.solution, screen)) {
    const other: Solution = state.solution === 'rules' ? 'senses' : 'rules'
    if (hasScreen(other, screen)) void switchSolution(other, screen)
    return
  }
  if (screen === state.screen) return
  const autoplaying = state.loop || state.playWhenReady
  // The entry being left keeps the decision that was showing, which playback has not written.
  writeHash()
  setState({ screen, ...INTERACTED, ...(autoplaying ? { playing: false } : {}) })
  writeHash(true)
  window.scrollTo({ top: 0 })
}

/** Switch screen and flash one of its panels. */
export function openPanel(screen: Screen, panel: string): void {
  setScreen(screen)
  setState({ focusPanel: panel })
}

/** Open one instance of the decision showing on The instances; playback pauses there. */
export function openInstance(name: string): void {
  setState({ instance: name, playing: false, ended: false, ...INTERACTED })
  setScreen('instances')
  writeHash()
}

/** Open the Reference screen at one glossary entry. */
export function openTerm(term: string): void {
  setScreen('reference')
  setState({ term })
}

/** Open one question of the decision showing on The questions; playback pauses there. */
export function openQuestion(step: number): void {
  setState({ question: step, playing: false, ended: false, ...INTERACTED })
  setScreen('questions')
  writeHash()
}

/** Open one rule on The rule tree; null follows the decision showing. */
export function openRule(id: string | null): void {
  setState({ rule: id, ...INTERACTED })
  setScreen('tree')
}

/** Open one entry of the build record on How the rules were written. */
export function openRound(entry: number): void {
  setState({ round: entry, ...INTERACTED })
  setScreen('written')
}

/** The recording a solution opens when nothing names one. */
function defaultOf(solution: Solution, entries: BundleIndexEntry[]): string | null {
  return solution === 'rules' ? defaultRulesEpisode(entries) : defaultEpisode({ episodes: entries })
}

/**
 * The recording a solution opens when switched to: one of the same seed as the one left (the one it had open, if
 * it is), else the one it had open, else its default.
 */
function recordingFor(
  solution: Solution,
  entries: BundleIndexEntry[],
  seed: number | undefined,
  loaded: string | null,
): string | null {
  const same = entries.filter((e) => e.seed === seed)
  if (loaded && same.some((e) => e.name === loaded)) return loaded
  if (same.length > 0) return defaultOf(solution, same)
  if (loaded && entries.some((e) => e.name === loaded)) return loaded
  return defaultOf(solution, entries)
}

/** The seed of the recording the solution showing has open, or is opening when it has not loaded yet. */
function seedShowing(): number | undefined {
  const { solution, index } = state
  if (state.loading && openingName?.solution === solution) {
    const entries = (solution === 'rules' ? index?.rules : index?.episodes) ?? []
    const name = openingName.name
    const entry = entries.find((e) => e.name === name)
    if (entry) return entry.seed
  }
  return solution === 'rules' ? state.rules?.meta.seed : state.bundle?.meta.seed
}

/**
 * Show the other solution: the screen at the same position (screen 3 opens screen 3), and the recording of the same
 * seed when it has one, at its first decision. Playback stops; the choice is remembered with the theme and pace.
 */
export async function switchSolution(to: Solution, screen?: Screen): Promise<void> {
  if (to === state.solution) {
    if (screen) setScreen(screen)
    return
  }
  const position = Math.max(
    0,
    screensOf(state.solution).findIndex((s) => s.id === state.screen),
  )
  const target = screen ?? screensOf(to)[position]?.id ?? 'watch'
  const seed = seedShowing()
  // The entry being left keeps the decision that was showing; while a recording loads, its hash already names it.
  if (!state.loading) writeHash()
  setState({
    solution: to,
    screen: target,
    playing: false,
    ended: false,
    following: false,
    error: null,
    tickIndex: 0,
    ...INTERACTED,
  })
  window.scrollTo({ top: 0 })
  const entries = (to === 'rules' ? state.index?.rules : state.index?.episodes) ?? []
  const loaded = to === 'rules' ? (state.rules?.name ?? null) : (state.bundle?.name ?? null)
  const name = recordingFor(to, entries, seed, loaded)
  if (!name) {
    setState({ error: 'episodes/index.json lists no recording of this solution.' })
    return
  }
  if (name === loaded) {
    writeHash(true)
    return
  }
  if (to === 'rules') await openRulesEpisode(name, null, true)
  else await openEpisode(name, null, false, true)
}

// ---------------------------------------------------------------------------------------------
// Playback. The timer lives in usePlayback (App), so a recording plays on every screen.

/** Play or pause. Play at the last decision starts again from the first. */
export function togglePlay(): void {
  const { playing, tickIndex, ended } = state
  if (playing) {
    setState({ playing: false, ...INTERACTED })
    writeHash()
    return
  }
  const last = Math.max(1, decisionCount()) - 1
  setState({
    playing: true,
    played: true,
    following: false,
    ended: false,
    ...INTERACTED,
    ...(ended || tickIndex >= last ? { tickIndex: 0 } : {}),
  })
}

/** A change of pace is the viewer taking over too: the landing stops looping, though a start still waiting stays. */
export function setPace(pace: Pace): void {
  if (pace !== state.pace || state.loop) setState({ pace, loop: false })
}

/** The open recording's first frames are decoded: start the playback a fresh visit or a card asked for. */
export function playWhenReady(): void {
  if (!state.playWhenReady || !openName()) return
  setState({ playWhenReady: false, playing: true, played: true, ended: false })
}

/**
 * One step of playback: the next decision, or past the last one the end, where the landing's loop holds and
 * anything else stops. A live episode still being played only ever stops at its newest decision.
 */
export function advancePlayback(): void {
  const { bundle, tickIndex, loop, ended, live, solution } = state
  const count = decisionCount()
  if (count === 0 || ended) return
  if (tickIndex < count - 1) {
    setState({ tickIndex: tickIndex + 1 })
    return
  }
  if (solution === 'senses' && bundle && live?.current === bundle.name) {
    setState({ playing: false, ...INTERACTED })
    writeHash()
    return
  }
  setState({ ended: true, ...(loop ? {} : { playing: false }) })
  if (!loop) writeHash()
}

/** After the end frame has been held, the landing's loop starts the recording again. */
export function restartLoop(): void {
  if (!state.loop || !state.playing) return
  setState({ tickIndex: 0, ended: false })
}

/** Run the playback timer while playing: one decision per pace interval, and the loop's hold at the end. */
export function usePlayback(): void {
  const playing = useApp((s) => s.playing)
  const pace = useApp((s) => s.pace)
  const ended = useApp((s) => s.ended)
  const loop = useApp((s) => s.loop)
  useEffect(() => {
    if (!playing) return
    if (ended) {
      if (!loop) return
      const hold = window.setTimeout(restartLoop, END_HOLD_MS)
      return () => window.clearTimeout(hold)
    }
    const timer = window.setInterval(advancePlayback, PACE_MS[pace])
    return () => window.clearInterval(timer)
  }, [playing, pace, ended, loop])
}

/**
 * Open a recording from Watch's cards: from its first decision, playing once its frames are ready (paused under
 * reduced motion), with no loop. The recording already open starts again.
 */
export async function openRecording(name: string): Promise<void> {
  const play = !prefersReducedMotion()
  if (openName() === name) {
    setState({
      tickIndex: 0,
      ended: false,
      following: false,
      ...INTERACTED,
      playing: play,
      played: play || state.played,
    })
    writeHash()
    return
  }
  setState({ ...INTERACTED, ended: false })
  if (state.solution === 'rules') await openRulesEpisode(name, null)
  else await openEpisode(name, null)
  if (openName() === name && !state.error) setState({ playWhenReady: play })
}

/** Counts calls to openEpisode and openRulesEpisode, so a slow load never replaces a later one. */
let opening = 0
/** The recording the latest of those calls opens, and its solution. */
let openingName: { solution: Solution; name: string } | null = null

/** Open a rule-tree recording at a decision, or at the first; `push` adds a history entry for it. */
export async function openRulesEpisode(name: string, decision: number | null = null, push = false): Promise<void> {
  const mine = ++opening
  openingName = { solution: 'rules', name }
  setState({ loading: true, error: null, playing: false, following: false, ended: false, ...INTERACTED })
  try {
    const rules = await loadRulesEpisode(name)
    if (mine !== opening) return
    const found = decision === null ? -1 : rules.decisions.findIndex((d) => d.decision === decision)
    setState({ rules, loading: false, tickIndex: Math.max(0, found) })
    writeHash(push)
  } catch (error) {
    if (mine !== opening) return
    setState({ loading: false, error: error instanceof Error ? error.message : String(error) })
  }
}
/** Live events that arrive while the live episode's files load; applied once they have. */
let pending: LiveEvent[] | null = null

/**
 * Open an episode at a tick, or at the first. The episode in progress is loaded as it stands and then
 * kept up to date by the live events. With `follow`, the cursor rides the newest tick; a live episode
 * that has just ended is then shown at its end, marked ended, until the next one starts.
 */
export async function openEpisode(
  name: string,
  tick: number | null = null,
  follow = false,
  push = false,
): Promise<void> {
  const mine = ++opening
  openingName = { solution: 'senses', name }
  const live = state.live?.current === name
  // Following holds while the files load, so an episode that starts meanwhile is still followed into.
  setState({ loading: true, error: null, playing: false, following: follow, ended: false, ...INTERACTED })
  pending = live ? [] : null
  try {
    let bundle = await loadEpisode(name, 'episodes', undefined, { live })
    if (mine !== opening) return
    for (const event of pending ?? []) bundle = applyLiveEvent(bundle, event)
    pending = null
    const found = tick === null ? -1 : bundle.ticks.findIndex((t) => t.tick === tick)
    setState({
      bundle,
      loading: false,
      tickIndex: follow ? Math.max(0, bundle.ticks.length - 1) : Math.max(0, found),
      liveOpen: live || (follow && LIVE_NAME.test(name)) || name === state.liveOpen ? name : null,
    })
    writeHash(push)
  } catch (error) {
    if (mine !== opening) return
    pending = null
    setState({ loading: false, following: false, error: error instanceof Error ? error.message : String(error) })
  }
}

/**
 * Follow the live episode: open it if another is open, and put the cursor on its newest tick. Between two
 * episodes, the next one is opened when it starts.
 */
export function followLive(): void {
  const { live, bundle } = state
  if (!live?.running && !live?.current) return
  // Live play is the senses and central's.
  if (state.solution === 'rules') setState({ solution: 'senses', screen: 'watch', tickIndex: 0 })
  setState({ ...INTERACTED, ended: false })
  if (!live.current) {
    setState({ following: true, playing: false })
    return
  }
  if (bundle?.name !== live.current) {
    void openEpisode(live.current, null, true)
    return
  }
  setState({ following: true, playing: false, tickIndex: Math.max(0, bundle.ticks.length - 1) })
  writeHash()
}

/** How many times the live stream has said hello: every connection, the first and each reconnect. */
let hellos = 0
/** Closes the live stream. */
let stopLive: (() => void) | null = null

function onLiveEvent(event: LiveEvent): void {
  const { live, bundle, following, liveOpen } = state
  if (!live) return
  if (pending && 'name' in event) pending.push(event)
  if (event.type === 'hello') {
    hellos += 1
    setState({ live: { ...live, current: event.current, tick: event.tick, episodes: event.episodes } })
    // Nothing missed while disconnected is replayed: a viewer following live goes to whatever is playing
    // now, and the open live episode is reloaded.
    if (hellos > 1 && following && event.current && bundle?.name !== event.current) {
      void openEpisode(event.current, null, true)
    } else if (hellos > 1 && liveOpen && bundle?.name === liveOpen) {
      void openEpisode(liveOpen, bundle.ticks[state.tickIndex]?.tick ?? null, following)
    }
  } else if (event.type === 'start') {
    setState({ live: { ...live, current: event.name, tick: null } })
    // A viewer following live rides on into each new episode.
    if (following && bundle?.name !== event.name) void openEpisode(event.name, null, true)
  } else if (event.type === 'tick') {
    const patch: Partial<AppState> = {}
    if (event.name === live.current) patch.live = { ...live, tick: event.trace.tick }
    if (bundle?.name === event.name) {
      const next = applyLiveEvent(bundle, event)
      if (next !== bundle) {
        patch.bundle = next
        if (following) patch.tickIndex = next.ticks.length - 1
      }
    }
    setState(patch)
  } else if (event.type === 'proposals' || event.type === 'reflection') {
    if (bundle && bundle.name === event.name) {
      const next = applyLiveEvent(bundle, event)
      if (next !== bundle) setState({ bundle: next })
    }
  } else if (event.type === 'end') {
    setState({
      live: {
        ...live,
        current: live.current === event.name ? null : live.current,
        tick: live.current === event.name ? null : live.tick,
        episodes: [event.entry, ...live.episodes.filter((e) => e.name !== event.name)],
      },
      ...(bundle?.name === event.name ? { bundle: applyLiveEvent(bundle, event) } : {}),
    })
    writeHash()
  } else if (event.type === 'stopped') {
    setState({ live: { ...live, running: false } })
    stopLive?.()
    stopLive = null
  }
}

/** Listen to the live events; resolves at the first hello, or after two seconds without one. */
function connectLive(): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, 2000)
    stopLive = subscribeLive((event) => {
      onLiveEvent(event)
      if (event.type === 'hello') {
        window.clearTimeout(timer)
        resolve()
      }
    })
  })
}

export async function start(): Promise<void> {
  try {
    const [loaded, live] = await Promise.all([loadIndex().catch((error: unknown) => error), fetchLiveStatus()])
    // Live mode can run without shipped recordings; without live mode, the index is required.
    if (loaded instanceof Error && !live) throw loaded
    const index: EpisodeIndex =
      loaded instanceof Error ? { schema_version: SUPPORTED_SCHEMA_VERSION, episodes: [] } : (loaded as EpisodeIndex)
    setState({ index, live })
    if (live?.running) await connectLive()
    const wanted = readHash()
    // While serve is playing, a visit without a link, or with #live, follows live play: the episode in
    // progress, or between two episodes the one that just ended, until the next starts.
    const wantsLive = !!state.live?.running && (!wanted.episode || wanted.episode === LIVE_HASH)
    // A link names its solution; a visit without one opens the solution chosen last, if it has recordings here.
    const solution = wanted.solution ?? (wantsLive ? 'senses' : state.solution)
    if (solution === 'rules' && (index.rules ?? []).length > 0) {
      await startRules(index.rules ?? [], wanted)
      return
    }
    // A fresh visit lands on Watch; a link to a decision without a screen opens The instances.
    const screen = wanted.screen ?? (wanted.episode && wanted.episode !== LIVE_HASH ? 'instances' : 'watch')
    setState({ solution: 'senses', screen })
    const followed = wantsLive ? (state.live?.current ?? state.live?.episodes[0]?.name) : undefined
    if (followed) {
      await openEpisode(followed, null, true)
      return
    }
    const names = mergedEpisodes(index, state.live).map((e) => e.name)
    const name = wanted.episode && names.includes(wanted.episode) ? wanted.episode : (defaultEpisode(index) ?? names[0])
    if (!name) {
      // Serve is still setting up its first episode and nothing is shipped: it is opened when it starts.
      if (wantsLive) setState({ following: true })
      else setState({ loading: false, error: 'episodes/index.json lists no episodes.' })
      return
    }
    await openEpisode(name, wanted.tick)
    // Serve has not finished an episode yet: the first one is opened when it starts.
    if (wantsLive) setState({ following: true })
    // Watch at its first decision plays on its own, and loops, once the first frames are decoded; a link to a
    // later decision waits for Play, and so does a viewer who asked for reduced motion.
    else if (screen === 'watch' && state.bundle?.name === name && state.tickIndex === 0 && !prefersReducedMotion()) {
      setState({ playWhenReady: true, loop: true })
    }
  } catch (error) {
    setState({ loading: false, error: error instanceof Error ? error.message : String(error) })
  }
}

/** The first visit's rule-tree half of `start`: the linked recording, or the newest cleared one, as for the senses. */
async function startRules(entries: BundleIndexEntry[], wanted: Wanted): Promise<void> {
  const screen = wanted.screen ?? (wanted.episode ? 'questions' : 'watch')
  setState({ solution: 'rules', screen })
  const names = entries.map((e) => e.name)
  const name =
    wanted.episode && names.includes(wanted.episode)
      ? wanted.episode
      : (defaultRulesEpisode(entries) ?? (names[0] as string))
  await openRulesEpisode(name, wanted.episode === name ? wanted.tick : null)
  if (screen === 'watch' && state.rules?.name === name && state.tickIndex === 0 && !prefersReducedMotion()) {
    setState({ playWhenReady: true, loop: true })
  }
}

/** The landing's own playback stops when the viewer goes elsewhere. */
function showScreen(solution: Solution, screen: Screen): void {
  if (solution === state.solution && screen === state.screen) return
  const autoplaying = state.loop || state.playWhenReady
  setState({ solution, screen, ...INTERACTED, ...(autoplaying ? { playing: false } : {}) })
}

export function onHashChange(): void {
  const wanted = readHash()
  if (!wanted.episode) return
  if (wanted.solution === 'rules') {
    const before = state.solution
    showScreen('rules', wanted.screen ?? 'questions')
    const { rules } = state
    if (!rules || rules.name !== wanted.episode) {
      void openRulesEpisode(wanted.episode, wanted.tick)
      return
    }
    const found = wanted.tick === null ? -1 : rules.decisions.findIndex((d) => d.decision === wanted.tick)
    if (found >= 0 && found !== state.tickIndex) setState({ tickIndex: found, ended: false })
    else if (found < 0 && before !== 'rules') setState({ tickIndex: 0, ended: false })
    return
  }
  if (wanted.episode === LIVE_HASH) {
    showScreen('senses', wanted.screen ?? 'watch')
    if (!state.following) followLive()
    return
  }
  const before = state.solution
  showScreen('senses', wanted.screen ?? 'instances')
  const { bundle } = state
  if (!bundle || bundle.name !== wanted.episode) {
    void openEpisode(wanted.episode, wanted.tick)
    return
  }
  const found = wanted.tick === null ? -1 : bundle.ticks.findIndex((t) => t.tick === wanted.tick)
  if (found >= 0 && found !== state.tickIndex) setState({ tickIndex: found, ended: false })
  else if (found < 0 && before !== 'senses') setState({ tickIndex: 0, ended: false })
}
