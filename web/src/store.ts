// A tiny external store: one episode, one current tick, and the viewer's settings.
import { useSyncExternalStore } from 'react'
import { type EpisodeBundle, type EpisodeIndex, loadEpisode, loadIndex } from './data/loader'

export type Depth = 'plain' | 'formula'
export type Theme = 'dark' | 'light'

export interface AppState {
  index: EpisodeIndex | null
  bundle: EpisodeBundle | null
  loading: boolean
  error: string | null
  /** Position in bundle.ticks, not the tick number. */
  tickIndex: number
  depth: Depth
  theme: Theme
  /** An action the viewer is pointing at; every panel highlights it. */
  hoveredAction: string | null
  playing: boolean
}

const SETTINGS_KEY = 'system1-doom-explainer'

function readSettings(): Partial<Pick<AppState, 'depth' | 'theme'>> {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY)
    return raw ? (JSON.parse(raw) as Partial<Pick<AppState, 'depth' | 'theme'>>) : {}
  } catch {
    return {}
  }
}

function writeSettings(settings: Pick<AppState, 'depth' | 'theme'>): void {
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
  } catch {
    // Private windows and blocked storage: settings simply do not persist.
  }
}

const saved = typeof window === 'undefined' ? {} : readSettings()

let state: AppState = {
  index: null,
  bundle: null,
  loading: true,
  error: null,
  tickIndex: 0,
  depth: saved.depth === 'formula' ? 'formula' : 'plain',
  theme: saved.theme === 'light' ? 'light' : 'dark',
  hoveredAction: null,
  playing: false,
}

const listeners = new Set<() => void>()

export function getState(): AppState {
  return state
}

export function setState(patch: Partial<AppState>): void {
  const next = { ...state, ...patch }
  if (next.depth !== state.depth || next.theme !== state.theme) writeSettings({ depth: next.depth, theme: next.theme })
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

/** The URL hash is `#<episode name>/<tick>`, so a link opens the same tick. */
function readHash(): { episode: string | null; tick: number | null } {
  const [episode, tick] = decodeURIComponent(window.location.hash.replace(/^#/, '')).split('/')
  const parsed = tick === undefined || tick === '' ? NaN : Number(tick)
  return { episode: episode || null, tick: Number.isInteger(parsed) ? parsed : null }
}

function writeHash(): void {
  const { bundle, tickIndex } = state
  if (!bundle) return
  const tick = bundle.ticks[tickIndex]?.tick ?? 0
  const hash = `#${encodeURIComponent(bundle.name)}/${tick}`
  if (window.location.hash !== hash) window.history.replaceState(null, '', hash)
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
  if (!bundle || bundle.name !== wanted.episode) {
    void openEpisode(wanted.episode, wanted.tick)
    return
  }
  if (wanted.tick !== null) {
    const found = bundle.ticks.findIndex((t) => t.tick === wanted.tick)
    if (found >= 0 && found !== state.tickIndex) setState({ tickIndex: found })
  }
}
