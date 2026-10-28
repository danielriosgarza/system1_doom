import { useEffect } from 'react'
import { Scrubber } from './components/Scrubber'
import { SolutionTabs } from './components/SolutionTabs'
import { TopBar } from './components/TopBar'
import { LIVE_COPY } from './content/live'
import { PACE_MS } from './data/playback'
import { Instances } from './screens/Instances'
import { Learning } from './screens/Learning'
import { Menu } from './screens/Menu'
import { Reference } from './screens/Reference'
import { SlowSystem } from './screens/SlowSystem'
import { Watch } from './screens/Watch'
import { LocalScreens } from './screens/local/LocalScreens'
import { RulesScreens } from './screens/rules/RulesScreens'
import { isLocalBundle } from './data/rules'
import {
  decisionCount,
  followLive,
  getState,
  onHashChange,
  SOLUTIONS,
  entriesOf,
  playsTree,
  screensOf,
  setScreen,
  setState,
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
  const screen = useApp((s) => s.screen)
  const solution = useApp((s) => s.solution)
  const rules = useApp((s) => s.rules)
  // A tree recording shows only on its own solution's screens: Jev's on the rule tree's, Laya's on the local models'.
  const treeShown = !!rules && (solution === 'local') === isLocalBundle(rules)
  const both = useApp((s) => SOLUTIONS.filter((x) => entriesOf(x.id, s.index).length > 0).length > 1)
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

  // A "see it" link names a panel: once its screen shows, scroll to it, let it flash, then forget it.
  const focusPanel = useApp((s) => s.focusPanel)
  useEffect(() => {
    if (!focusPanel) return
    const frame = window.requestAnimationFrame(() =>
      document.getElementById(`panel-${focusPanel}`)?.scrollIntoView({ block: 'start', behavior: 'smooth' }),
    )
    const timer = window.setTimeout(() => setState({ focusPanel: null }), 1600)
    return () => {
      window.cancelAnimationFrame(frame)
      window.clearTimeout(timer)
    }
  }, [focusPanel, screen])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      const count = decisionCount()
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
      const target = /^[1-9]$/.test(key) ? screensOf(getState().solution)[Number(key) - 1] : undefined
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
  const decision = rules?.decisions[tickIndex]
  return (
    // One decision's span on screen, for animations that run once per decision.
    <div
      className={`app ${both ? 'has-solutions' : ''}`}
      data-solution={solution}
      style={{ ['--decision-ms' as string]: `${Math.round(PACE_MS[pace])}ms` }}
    >
      <SolutionTabs />
      <TopBar />
      {error && (
        <p className="status error" role="alert">
          {error}
        </p>
      )}
      {playsTree(solution) && !error && loading && !treeShown && <p className="status">Loading the episode…</p>}
      {solution === 'rules' && treeShown && rules && decision && (
        <RulesScreens bundle={rules} decision={decision} index={tickIndex} screen={screen} />
      )}
      {solution === 'local' && treeShown && rules && decision && (
        <LocalScreens bundle={rules} decision={decision} index={tickIndex} screen={screen} />
      )}
      {solution === 'senses' && !error && loading && !bundle && <p className="status">Loading the episode…</p>}
      {solution === 'senses' && !error && bundle && !tick && <p className="status">{LIVE_COPY.waiting}</p>}
      {solution === 'senses' && bundle && tick && (
        <>
          {screen === 'watch' && <Watch bundle={bundle} tick={tick} tickIndex={tickIndex} />}
          {screen === 'instances' && <Instances bundle={bundle} tick={tick} tickIndex={tickIndex} />}
          {screen === 'slow' && <SlowSystem bundle={bundle} tick={tick} tickIndex={tickIndex} />}
          {screen === 'learning' && <Learning bundle={bundle} tick={tick} />}
          {screen === 'menu' && <Menu bundle={bundle} tick={tick} />}
          {screen === 'reference' && <Reference bundle={bundle} />}
          {screen !== 'watch' && <Scrubber bundle={bundle} />}
        </>
      )}
    </div>
  )
}
