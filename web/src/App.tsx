import { useEffect } from 'react'
import { TopBar } from './components/TopBar'
import { LIVE_COPY } from './content/live'
import { PACE_MS } from './data/playback'
import { Watch } from './screens/Watch'
import {
  SCREENS,
  followLive,
  getState,
  onHashChange,
  setScreen,
  setTickIndex,
  start,
  step,
  togglePlay,
  useApp,
  usePlayback,
} from './store'

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return (
    !!el && (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
  )
}

export default function App() {
  const bundle = useApp((s) => s.bundle)
  const tickIndex = useApp((s) => s.tickIndex)
  const loading = useApp((s) => s.loading)
  const error = useApp((s) => s.error)
  const theme = useApp((s) => s.theme)
  const pace = useApp((s) => s.pace)
  // The playback timer runs here, so a recording plays on every screen.
  usePlayback()

  useEffect(() => {
    void start()
    // Back and Forward between screens fire popstate; links typed into the address bar fire hashchange.
    window.addEventListener('hashchange', onHashChange)
    window.addEventListener('popstate', onHashChange)
    return () => {
      window.removeEventListener('hashchange', onHashChange)
      window.removeEventListener('popstate', onHashChange)
    }
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      const count = getState().bundle?.ticks.length ?? 0
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
      const target = /^[1-9]$/.test(key) ? SCREENS[Number(key) - 1] : undefined
      if (target) setScreen(target.id)
      else if (key === 'l') followLive()
      else if (e.key === 'ArrowRight') step(e.shiftKey ? 10 : 1)
      else if (e.key === 'ArrowLeft') step(e.shiftKey ? -10 : -1)
      else if (e.key === 'Home') setTickIndex(0)
      else if (e.key === 'End') setTickIndex(count - 1)
      else if (e.key === ' ' && (e.target as HTMLElement | null)?.tagName !== 'BUTTON') togglePlay()
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const tick = bundle?.ticks[tickIndex]
  return (
    // One decision's span on screen, for animations that run once per decision.
    <div className="app" style={{ ['--decision-ms' as string]: `${Math.round(PACE_MS[pace])}ms` }}>
      <TopBar />
      {error && (
        <p className="status error" role="alert">
          {error}
        </p>
      )}
      {!error && loading && !bundle && <p className="status">Loading the episode…</p>}
      {!error && bundle && !tick && <p className="status">{LIVE_COPY.waiting}</p>}
      {bundle && tick && <Watch bundle={bundle} tick={tick} tickIndex={tickIndex} />}
    </div>
  )
}
