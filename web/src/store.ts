// A tiny external store: one episode, one current tick, the screen, and the viewer's settings.
import { useSyncExternalStore } from 'react'
import { TOUR } from './content/tour'
import { featuredTickIndex } from './data/derive'
import {
  LIVE_NAME,
  type LiveEvent,
  type LiveStatus,
  applyLiveEvent,
  fetchLiveStatus,
  mergedEpisodes,
  subscribeLive,
} from './data/live'
import { type EpisodeBundle, type EpisodeIndex, loadEpisode, loadIndex } from './data/loader'

export type Depth = 'plain' | 'formula'
export type Theme = 'dark' | 'light'
export type Screen = 'overview' | 'tick' | 'hierarchy' | 'learning' | 'menu'
/** The reference drawer's four tabs. */
export type DrawerSection = 'glossary' | 'principles' | 'recording' | 'keys'

export const SCREENS: Array<{ id: Screen; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'tick', label: 'Tick' },
  { id: 'hierarchy', label: 'Hierarchy' },
  { id: 'learning', label: 'Learning' },
  { id: 'menu', label: 'Growing the menu' },
]

/** The tour's last step is on the hierarchy screen; the ones before it are the six beats. */
const TOUR_STEPS = TOUR.length

export interface AppState {
  index: EpisodeIndex | null
  bundle: EpisodeBundle | null
  loading: boolean
  error: string | null
  /** Position in bundle.ticks, not the tick number. */
  tickIndex: number
  screen: Screen
  depth: Depth
  theme: Theme
  /** An action the viewer is pointing at; every panel highlights it. */
  hoveredAction: string | null
  playing: boolean
  /** The tour's current step, or null when no tour is running. */
  tour: number | null
  /** The viewer has finished or skipped the tour once; only changes the overview's button label. */
  tourSeen: boolean
  /** A panel to scroll to and flash once its screen is showing. */
  focusPanel: string | null
  /** The reference drawer's open tab, or null when it is closed; not in the URL. */
  drawer: DrawerSection | null
  /** The glossary entry to scroll to and mark. */
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

type Settings = Partial<Pick<AppState, 'depth' | 'theme' | 'tourSeen'>>

const SETTINGS_KEY = 'system1-doom-explainer'

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
  bundle: null,
  loading: true,
  error: null,
  tickIndex: 0,
  screen: 'overview',
  depth: saved.depth === 'formula' ? 'formula' : 'plain',
  theme: themePicked ? (saved.theme as Theme) : prefersLight ? 'light' : 'dark',
  hoveredAction: null,
  playing: false,
  tour: null,
  tourSeen: saved.tourSeen === true,
  focusPanel: null,
  drawer: null,
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
  if (next.depth !== state.depth || next.theme !== state.theme || next.tourSeen !== state.tourSeen) {
    writeSettings({ depth: next.depth, tourSeen: next.tourSeen, ...(themePicked ? { theme: next.theme } : {}) })
  }
  state = next
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useApp<T>(selector: (s: AppState) => T): T {
  return useSyncExternalStore(subscribe, () => selector(state))
}

// ---------------------------------------------------------------------------------------------
// The URL hash: `#<episode name>/<tick>/<screen>`. Without a screen it means the tick inspector,
// so links written before the other screens existed still open the same tick. `#live/<screen>`
// follows the live episode, whichever it is; plain `#live` lands on the overview.

const LIVE_HASH = 'live'

function readHash(): { episode: string | null; tick: number | null; screen: Screen | null } {
  const parts = decodeURIComponent(window.location.hash.replace(/^#/, '')).split('/')
  const [episode, tick, screen] = parts[0] === LIVE_HASH ? [LIVE_HASH, '', parts[1]] : parts
  const parsed = tick === undefined || tick === '' ? NaN : Number(tick)
  return {
    episode: episode || null,
    tick: Number.isInteger(parsed) ? parsed : null,
    screen: SCREENS.some((s) => s.id === screen) ? (screen as Screen) : null,
  }
}

/** Ticks replace the history entry; a change of screen adds one, so Back returns to the last screen. */
function writeHash(push = false): void {
  const { bundle, tickIndex, screen, following, live } = state
  if (!bundle) return
  const tick = bundle.ticks[tickIndex]?.tick ?? 0
  const where = screen === 'tick' ? '' : `/${screen}`
  const hash =
    following && live?.current === bundle.name
      ? `#${LIVE_HASH}/${screen}`
      : `#${encodeURIComponent(bundle.name)}/${tick}${where}`
  if (window.location.hash === hash) return
  if (push) window.history.pushState(null, '', hash)
  else window.history.replaceState(null, '', hash)
}

// ---------------------------------------------------------------------------------------------
// Actions.

/** Move the cursor; any move the viewer makes stops following the live episode. */
export function setTickIndex(index: number): void {
  const count = state.bundle?.ticks.length ?? 0
  if (count === 0) return
  const clamped = Math.max(0, Math.min(count - 1, index))
  if (clamped !== state.tickIndex || state.following) setState({ tickIndex: clamped, following: false })
  writeHash()
}

export function step(delta: number): void {
  setTickIndex(state.tickIndex + delta)
}

export function setScreen(screen: Screen): void {
  if (screen === state.screen) return
  setState({ screen, hoveredAction: null })
  writeHash(true)
  window.scrollTo({ top: 0 })
}

/** Switch screen and flash one of its panels. */
export function openPanel(screen: Screen, panel: string): void {
  setScreen(screen)
  setState({ focusPanel: panel })
}

/** Open the reference drawer on one tab; for the glossary, optionally at one entry. Playback is left alone. */
export function openDrawer(section: DrawerSection, term: string | null = null): void {
  setState({ drawer: section, term })
}

export function closeDrawer(): void {
  if (state.drawer !== null) setState({ drawer: null, term: null })
}

export function openInInspector(panel: string): void {
  openPanel('tick', panel)
}

/** Counts calls to openEpisode, so a slow load never replaces a later one. */
let opening = 0
/** Live events that arrive while the live episode's files load; applied once they have. */
let pending: LiveEvent[] | null = null

/**
 * Open an episode at a tick, or at the first. The episode in progress is loaded as it stands and then
 * kept up to date by the live events. With `follow`, the cursor rides the newest tick; a live episode
 * that has just ended is then shown at its end, marked ended, until the next one starts.
 */
export async function openEpisode(name: string, tick: number | null = null, follow = false): Promise<void> {
  const mine = ++opening
  const live = state.live?.current === name
  // Following holds while the files load, so an episode that starts meanwhile is still followed into.
  setState({ loading: true, error: null, playing: false, hoveredAction: null, following: follow })
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
    writeHash()
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
  const { live, bundle, tour } = state
  if (!live?.running && !live?.current) return
  if (tour !== null) endTour()
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
  } else if (event.type === 'proposals') {
    if (bundle?.name === event.name) setState({ bundle: applyLiveEvent(bundle, event) })
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
    const index: EpisodeIndex = loaded instanceof Error ? { schema_version: 1, episodes: [] } : (loaded as EpisodeIndex)
    setState({ index, live })
    if (live?.running) await connectLive()
    const wanted = readHash()
    // A fresh visit lands on the overview; a link without a screen opens the inspector.
    setState({ screen: wanted.screen ?? (wanted.episode && wanted.episode !== LIVE_HASH ? 'tick' : 'overview') })
    // While serve is playing, a visit without a link, or with #live, follows live play: the episode in
    // progress, or between two episodes the one that just ended, until the next starts.
    const wantsLive = !!state.live?.running && (!wanted.episode || wanted.episode === LIVE_HASH)
    const followed = wantsLive ? (state.live?.current ?? state.live?.episodes[0]?.name) : undefined
    if (followed) {
      await openEpisode(followed, null, true)
      return
    }
    const names = mergedEpisodes(index, state.live).map((e) => e.name)
    const name =
      wanted.episode && names.includes(wanted.episode) ? wanted.episode : (index.episodes[0]?.name ?? names[0])
    if (!name) {
      setState({ loading: false, error: 'episodes/index.json lists no episodes.' })
      return
    }
    await openEpisode(name, wanted.tick)
    // Serve has not finished an episode yet: the first one is opened when it starts.
    if (wantsLive) setState({ following: true })
  } catch (error) {
    setState({ loading: false, error: error instanceof Error ? error.message : String(error) })
  }
}

export function onHashChange(): void {
  const wanted = readHash()
  const { bundle } = state
  if (!wanted.episode) return
  if (wanted.episode === LIVE_HASH) {
    const screen = wanted.screen ?? 'overview'
    if (screen !== state.screen) setState({ screen, hoveredAction: null })
    if (!state.following) followLive()
    return
  }
  const screen = wanted.screen ?? 'tick'
  if (screen !== state.screen) setState({ screen, hoveredAction: null })
  if (!bundle || bundle.name !== wanted.episode) {
    void openEpisode(wanted.episode, wanted.tick)
    return
  }
  if (wanted.tick !== null) {
    const found = bundle.ticks.findIndex((t) => t.tick === wanted.tick)
    if (found >= 0 && found !== state.tickIndex) setState({ tickIndex: found })
  }
}

// ---------------------------------------------------------------------------------------------
// The guided tour: six beats on the inspector over the featured tick, then the hierarchy.

export function startTour(): void {
  const ticks = state.bundle?.ticks ?? []
  if (ticks.length === 0) return
  setState({ playing: false, following: false, hoveredAction: null, tickIndex: featuredTickIndex(ticks) })
  setTourStep(0)
}

export function setTourStep(index: number): void {
  if (index < 0) return
  if (index >= TOUR_STEPS) {
    endTour()
    return
  }
  setState({ tour: index })
  setScreen(index === TOUR_STEPS - 1 ? 'hierarchy' : 'tick')
  writeHash()
}

export function endTour(): void {
  setState({ tour: null, tourSeen: true })
}
