import { useEffect, useMemo } from 'react'
import { ArbiterPanel } from './components/ArbiterPanel'
import { GameView } from './components/GameView'
import { LegalActions } from './components/LegalActions'
import { ModuleMatrix } from './components/ModuleMatrix'
import { MotorPanel } from './components/MotorPanel'
import { OutcomeCard } from './components/OutcomeCard'
import { Panel } from './components/Panel'
import { ProjectionStrip } from './components/ProjectionStrip'
import { Scrubber } from './components/Scrubber'
import { Story, TopBar } from './components/TopBar'
import { WorldState } from './components/WorldState'
import type { ExplainerContext } from './content/explainers'
import { admissions } from './data/derive'
import { getState, onHashChange, setState, setTickIndex, start, step, useApp } from './store'

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

  useEffect(() => {
    void start()
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      const count = getState().bundle?.ticks.length ?? 0
      if (e.key === 'ArrowRight') step(e.shiftKey ? 10 : 1)
      else if (e.key === 'ArrowLeft') step(e.shiftKey ? -10 : -1)
      else if (e.key === 'Home') setTickIndex(0)
      else if (e.key === 'End') setTickIndex(count - 1)
      else if (e.key === ' ' && (e.target as HTMLElement | null)?.tagName !== 'BUTTON') {
        setState({ playing: !getState().playing })
      } else return
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
        }
      : null

  return (
    <div className="app">
      <TopBar />
      <Story />
      {error && (
        <p className="status error" role="alert">
          {error}
        </p>
      )}
      {!error && loading && !bundle && <p className="status">Loading the episode…</p>}
      {bundle && tick && ctx && (
        <>
          <main className="main" aria-busy={loading}>
            <div className="column">
              <Panel id="game" ctx={ctx}>
                <GameView bundle={bundle} tick={tick} />
              </Panel>
              <Panel id="world" ctx={ctx}>
                <WorldState tick={tick} />
              </Panel>
              <Panel id="outcome" ctx={ctx} bounds={['≤ 12 strategies', '≤ 100k transitions']}>
                <OutcomeCard tick={tick} meta={bundle.meta} />
              </Panel>
            </div>
            <div className="column">
              <Panel id="legal" ctx={ctx} bounds={['menu ≤ 16 steps per macro', 'one proposal in flight']}>
                <LegalActions bundle={bundle} tick={tick} admitted={admitted} />
              </Panel>
              <Panel
                id="projection"
                ctx={ctx}
                bounds={['16 candidates', 'depth 4 · 2 branches', '15 ms', '≤ 50 samples']}
              >
                <ProjectionStrip tick={tick} />
              </Panel>
              <Panel id="modules" ctx={ctx} bounds={['deadline 65% of tick']}>
                <ModuleMatrix tick={tick} meta={bundle.meta} />
              </Panel>
              <Panel id="arbiter" ctx={ctx} bounds={['one pick from the menu']}>
                <ArbiterPanel tick={tick} />
              </Panel>
              <Panel id="motor" ctx={ctx} bounds={['8 frames']}>
                <MotorPanel tick={tick} meta={bundle.meta} />
              </Panel>
            </div>
          </main>
          <Scrubber ticks={bundle.ticks} admitted={admitted} ctx={ctx} />
        </>
      )}
    </div>
  )
}
