import { useEffect, useMemo } from 'react'
import { Reference } from './components/Reference'
import { Scrubber } from './components/Scrubber'
import { TopBar } from './components/TopBar'
import { Tour } from './components/Tour'
import type { ExplainerContext } from './content/explainers'
import { LIVE_COPY } from './content/live'
import { admissions } from './data/derive'
import { PACE_MS } from './data/playback'
import { Hierarchy } from './screens/Hierarchy'
import { Inspector } from './screens/Inspector'
import { Learning } from './screens/Learning'
import { Menu } from './screens/Menu'
import { Overview } from './screens/Overview'
import { Watch } from './screens/Watch'
import {
  SCREENS,
  closeDrawer,
  endTour,
  followLive,
  getState,
  onHashChange,
  openDrawer,
  setScreen,
  setState,
  setTickIndex,
  setTourStep,
  start,
  startTour,
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
  const hovered = useApp((s) => s.hoveredAction)
  const screen = useApp((s) => s.screen)
  const tour = useApp((s) => s.tour)
  const pace = useApp((s) => s.pace)
  // The playback timer runs here, so a recording plays on every screen, Watch included, which has no timeline.
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
      const { tour: tourStep, bundle: current, drawer } = getState()
      // While the reference drawer is open, only Esc (here) and Tab (inside the dialog) reach the app.
      if (drawer !== null) {
        if (e.key === 'Escape') {
          closeDrawer()
          e.preventDefault()
        }
        return
      }
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      if (tourStep !== null) {
        // During the tour the arrows walk the tour, not the episode.
        if (e.key === 'ArrowRight') setTourStep(tourStep + 1)
        else if (e.key === 'ArrowLeft') setTourStep(tourStep - 1)
        else if (e.key === 'Escape') endTour()
        else return
        e.preventDefault()
        return
      }
      const count = current?.ticks.length ?? 0
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
      const screen = /^[1-9]$/.test(key) ? SCREENS[Number(key) - 1] : undefined
      if (screen) setScreen(screen.id)
      else if (key === 't') startTour()
      else if (key === 'f') setState({ depth: getState().depth === 'plain' ? 'formula' : 'plain' })
      else if (key === 'g') openDrawer('glossary')
      else if (key === 'i') openDrawer('recording')
      else if (key === '?') openDrawer('keys')
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

  const admitted = useMemo(() => admissions(bundle?.proposals ?? []), [bundle])
  const tick = bundle?.ticks[tickIndex]
  const ctx: ExplainerContext | null =
    bundle && tick
      ? {
          tick,
          meta: bundle.meta,
          focus: hovered && tick.available_actions.includes(hovered) ? hovered : tick.selected_action,
          prev: bundle.ticks[tickIndex - 1] ?? null,
          proposals: bundle.proposals,
          ticks: bundle.ticks,
          index: tickIndex,
          metrics: bundle.metrics,
          trust: bundle.trust,
        }
      : null

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
      {bundle && tick && ctx && (
        <>
          {screen === 'watch' && <Watch bundle={bundle} tick={tick} tickIndex={tickIndex} />}
          {screen === 'overview' && <Overview bundle={bundle} tick={tick} ctx={ctx} />}
          {screen === 'tick' && <Inspector bundle={bundle} tick={tick} admitted={admitted} ctx={ctx} />}
          {screen === 'hierarchy' && <Hierarchy bundle={bundle} tick={tick} tickIndex={tickIndex} ctx={ctx} />}
          {screen === 'learning' && <Learning bundle={bundle} tick={tick} ctx={ctx} />}
          {screen === 'menu' && <Menu bundle={bundle} tick={tick} ctx={ctx} />}
          {screen !== 'watch' && <Scrubber ticks={bundle.ticks} admitted={admitted} ctx={ctx} />}
          {tour !== null && <Tour step={tour} bundle={bundle} tick={tick} />}
          <Reference bundle={bundle} ctx={ctx} />
        </>
      )}
    </div>
  )
}
