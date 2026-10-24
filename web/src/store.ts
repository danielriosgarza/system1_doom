// A tiny external store: one episode, one current tick, the screen, and the viewer's settings.
import { useSyncExternalStore } from 'react'
import { TOUR } from './content/tour'
import { featuredTickIndex } from './data/derive'
import { type EpisodeBundle, type EpisodeIndex, loadEpisode, loadIndex } from './data/loader'

export type Depth = 'plain' | 'formula'
export type Theme = 'dark' | 'light'
export type Screen = 'overview' | 'tick' | 'hierarchy' | 'learning'

export const SCREENS: Array<{ id: Screen; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'tick', label: 'Tick' },
  { id: 'hierarchy', label: 'Hierarchy' },
  { id: 'learning', label: 'Learning' },
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
// so links written before the other screens existed still open the same tick.

function readHash(): { episode: string | null; tick: number | null; screen: Screen | null } {
  const [episode, tick, screen] = decodeURIComponent(window.location.hash.replace(/^#/, '')).split('/')
  const parsed = tick === undefined || tick === '' ? NaN : Number(tick)
  return {
    episode: episode || null,
    tick: Number.isInteger(parsed) ? parsed : null,
    screen: SCREENS.some((s) => s.id === screen) ? (screen as Screen) : null,
  }
}

/** Ticks replace the history entry; a change of screen adds one, so Back returns to the last screen. */
function writeHash(push = false): void {
  const { bundle, tickIndex, screen } = state
  if (!bundle) return
  const tick = bundle.ticks[tickIndex]?.tick ?? 0
  const hash = `#${encodeURIComponent(bundle.name)}/${tick}${screen === 'tick' ? '' : `/${screen}`}`
  if (window.location.hash === hash) return
  if (push) window.history.pushState(null, '', hash)
  else window.history.replaceState(null, '', hash)
}

// ---------------------------------------------------------------------------------------------
// Actions.

export function setTickIndex(index: number): void {
  const count = state.bundle?.ticks.length ?? 0
  if (count === 0) return
  const clamped = Math.max(0, Math.min(count - 1, index))
  if (clamped !== state.tickIndex) setState({ tickIndex: clamped })
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

export function openInInspector(panel: string): void {
  openPanel('tick', panel)
}

export async function openEpisode(name: string, tick: number | null = null): Promise<void> {
  setState({ loading: true, error: null, playing: false, hoveredAction: null })
  try {
    const bundle = await loadEpisode(name)
    const found = tick === null ? -1 : bundle.ticks.findIndex((t) => t.tick === tick)
    setState({ bundle, loading: false, tickIndex: Math.max(0, found) })
    writeHash()
  } catch (error) {
    setState({ loading: false, error: error instanceof Error ? error.message : String(error) })
  }
}

export async function start(): Promise<void> {
  try {
    const index = await loadIndex()
    setState({ index })
    const wanted = readHash()
    // A fresh visit lands on the overview; a link without a screen opens the inspector.
    setState({ screen: wanted.screen ?? (wanted.episode ? 'tick' : 'overview') })
    const names = index.episodes.map((e) => e.name)
    const name = wanted.episode && names.includes(wanted.episode) ? wanted.episode : names[0]
    if (!name) {
      setState({ loading: false, error: 'episodes/index.json lists no episodes.' })
      return
    }
    await openEpisode(name, wanted.tick)
  } catch (error) {
    setState({ loading: false, error: error instanceof Error ? error.message : String(error) })
  }
}

export function onHashChange(): void {
  const wanted = readHash()
  const { bundle } = state
  if (!wanted.episode) return
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
  setState({ playing: false, hoveredAction: null, tickIndex: featuredTickIndex(ticks) })
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
