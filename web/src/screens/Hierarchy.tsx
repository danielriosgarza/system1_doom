import { Fragment, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { DecisionCard } from '../components/DecisionCard'
import { HeadTools } from '../components/DepthToggle'
import { ExplorationGauge } from '../components/ExplorationGauge'
import { GameFrame } from '../components/GameView'
import { flashElement } from '../components/flash'
import { GateDetail, GatePipeline } from '../components/GateStages'
import { BoundBadges, ExplainerBody } from '../components/Panel'
import { SteeringCard } from '../components/SteeringCard'
import { EXPLAINERS, type ExplainerContext, type ExplainerId, type PanelId } from '../content/explainers'
import {
  type LevelId,
  type TowerLevel,
  d1Arbiter,
  d1Modules,
  d1Words,
  exploration,
  explainPick,
  fmt,
  gameSeconds,
  learning,
  moduleOpinions,
  motorSteps,
  pct,
  pressureForArbiter,
  pressureReading,
  prettyId,
  towerLevels,
} from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import type { EpisodeMeta, TickTrace } from '../schema/bundle'
import { openInInspector, openPanel, setState, useApp } from '../store'

const LEVEL_EXPLAINER: Record<LevelId, ExplainerId> = {
  gate: 'gate',
  steering: 'steering',
  menu: 'legal',
  opinions: 'modules',
  arbiter: 'arbiter',
  motor: 'motor',
}

const LEVEL_PANEL: Record<LevelId, PanelId> = {
  gate: 'legal',
  steering: 'outcome',
  menu: 'legal',
  opinions: 'modules',
  arbiter: 'arbiter',
  motor: 'motor',
}

type SourceId = 'exploration' | 'd1' | 'networks' | 'simulator'

interface Source {
  id: SourceId
  explainer: ExplainerId
  title: string
  bounds: string[]
  feeds: LevelId[]
  /** Line style of its arrows: solid for hand-written, dashed for learned, dotted for d1. */
  line: 'solid' | 'learned' | 'dotted'
  panel?: PanelId
  learning?: PanelId
}

const SOURCES: Source[] = [
  {
    id: 'exploration',
    explainer: 'exploration',
    title: 'Exploration pressure',
    bounds: ['each term ≤ 0.25', 'pressure 0.02 to 1'],
    feeds: ['steering', 'arbiter'],
    line: 'solid',
    panel: 'arbiter',
  },
  {
    id: 'd1',
    explainer: 'd1',
    title: 'd1-ultra advice',
    bounds: ['advice only'],
    feeds: ['gate', 'opinions', 'arbiter'],
    line: 'dotted',
    panel: 'arbiter',
  },
  {
    id: 'networks',
    explainer: 'networks',
    title: 'Learned networks',
    bounds: ['≤ 100k transitions', 'trains between episodes'],
    feeds: ['opinions', 'arbiter'],
    line: 'learned',
    panel: 'modules',
    learning: 'trustmap',
  },
  {
    id: 'simulator',
    explainer: 'projection',
    title: 'Bounded simulator',
    bounds: ['16 candidates', 'depth 4 · 2 branches', '15 ms'],
    feeds: ['opinions', 'arbiter'],
    line: 'solid',
    panel: 'projection',
  },
]

const LEVEL_TITLES: Record<LevelId, string> = {
  gate: 'the gate',
  steering: 'steering',
  menu: 'the menu',
  opinions: 'the opinions',
  arbiter: 'the arbiter',
  motor: 'the motor',
}

function SideCard({
  source,
  ctx,
  off,
  children,
}: {
  source: Source
  ctx: ExplainerContext
  off: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <section className={`side-card ${off ? 'off' : ''} line-${source.line}`} data-source={source.id}>
      <header className="panel-head">
        <span className="beat-num side" title="A side input, not a level of the tower">
          ↳
        </span>
        <h3>{source.title}</h3>
        <span className="spacer" />
        <button
          type="button"
          className="explain-toggle"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          title={open ? 'Hide the explanation' : 'Explain this input'}
        >
          {open ? 'Hide' : '?'}
        </button>
      </header>
      <p className="sentence">{EXPLAINERS[source.explainer].sentence}</p>
      <BoundBadges bounds={source.bounds} />
      {children}
      <p className="feeds">
        Feeds {source.feeds.map((f) => LEVEL_TITLES[f]).join(', ')}
        {off ? ' (off in this episode)' : ''}.
      </p>
      {open && (
        <>
          <ExplainerBody id={source.explainer} ctx={ctx} />
          {source.panel && (
            <button type="button" className="link-button" onClick={() => openInInspector(source.panel as string)}>
              See this in the inspector →
            </button>
          )}{' '}
          {source.learning && (
            <button
              type="button"
              className="link-button"
              onClick={() => openPanel('learning', source.learning as string)}
            >
              See it in Learning →
            </button>
          )}
        </>
      )}
    </section>
  )
}

function SimulatorReading({ tick }: { tick: TickTrace }) {
  const projected = Object.keys(tick.projection_results_used).length
  const summary = tick.projection_results_used[tick.selected_action]
  if (projected === 0) return <p className="empty-note">No projections this tick: the budget was too short.</p>
  return (
    <dl className="facts">
      <dt>Projected</dt>
      <dd>
        {projected} of {tick.available_actions.length} legal actions
      </dd>
      {summary && (
        <>
          <dt>{prettyId(tick.selected_action)}</dt>
          <dd>
            expected value {fmt(summary.expected_value ?? 0, 2)}, survival {pct(summary.survival_probability ?? 0)},
            damage taken {fmt(summary.expected_damage_taken ?? 0, 1)}
          </dd>
        </>
      )}
    </dl>
  )
}

function D1Reading({ tick, meta }: { tick: TickTrace; meta: EpisodeMeta }) {
  if (!meta.brains.d1_ultra) return <p className="empty-note">Off in this recording: no advice was asked for.</p>
  const arbiter = d1Arbiter(tick)
  const modules = d1Modules(tick)
  return (
    <div data-testid="d1-reading">
      <p className="d1-words">{d1Words(tick, meta)}</p>
      {(arbiter || modules.length > 0) && (
        <dl className="facts">
          {arbiter && (
            <>
              <dt>the arbiter</dt>
              <dd>
                {arbiter.ranked
                  .slice(0, 3)
                  .map((r) => `${prettyId(r.action)} ${pct(r.p)}`)
                  .join(', ')}
              </dd>
            </>
          )}
          {modules.map((m) => {
            const out = tick.module_outputs[m]
            const top = out?.d1_top_action ?? ''
            return (
              <Fragment key={m}>
                <dt>{m}</dt>
                <dd>
                  {prettyId(top)} {pct(out?.d1_probabilities?.[top] ?? 0)}, mixed in at {fmt(out?.d1_weight ?? 0, 2)}
                </dd>
              </Fragment>
            )
          })}
        </dl>
      )}
    </div>
  )
}

function NetworksReading({ tick, on }: { tick: TickTrace; on: boolean }) {
  if (!on) return <p className="empty-note">No checkpoint loaded: every opinion is the heuristic alone.</p>
  const view = learning(tick)
  const rows = [
    { label: `trust λ in ${prettyId(tick.selected_action)}`, value: view.network_share ?? 0 },
    { label: 'gate share g', value: view.gate_share ?? 0 },
  ]
  return (
    <div className="share-rows">
      {rows.map((r) => (
        <div key={r.label} className="share-row">
          <span>{r.label}</span>
          <span className="bar-track" style={{ ['--c' as string]: 'var(--goal)' }}>
            <span className="bar-fill" style={{ width: `${r.value * 100}%` }}>
              <span className="hatched" style={{ width: '100%' }} />
            </span>
          </span>
          <span className="num">{pct(r.value)}</span>
        </div>
      ))}
    </div>
  )
}

function Opinions({ tick, expanded }: { tick: TickTrace; expanded: boolean }) {
  const hovered = useApp((s) => s.hoveredAction)
  const opinions = moduleOpinions(tick)
  if (opinions.length === 0) return <p className="empty-note">No module opinions this tick.</p>
  return (
    <div className={`opinions ${expanded ? 'full' : ''}`}>
      {opinions.map((o) => {
        const out = tick.module_outputs[o.module]
        return (
          <div key={o.module} className="opinion" style={{ ['--c' as string]: `var(--${o.module})` }}>
            <div className="module-name">{o.module}</div>
            <div
              className={`opinion-top ${o.top === hovered ? 'row-hover' : ''}`}
              onMouseEnter={() => o.top && setState({ hoveredAction: o.top })}
              onMouseLeave={() => setState({ hoveredAction: null })}
            >
              {o.agrees && <span className="pick-mark" aria-label="the arbiter picked this too" />}
              {prettyId(o.top ?? '–')}
            </div>
            <span className="bar-track">
              <span className="bar-fill" style={{ width: `${o.topProbability * 100}%` }}>
                <span className="solid" style={{ width: `${(1 - o.learned) * 100}%` }} />
                <span className="hatched" style={{ width: `${o.learned * 100}%` }} />
              </span>
            </span>
            <div className="opinion-stats">
              {pct(o.topProbability)} · sure {pct(o.confidence)}
            </div>
            {expanded && (
              <ol className="opinion-list">
                {tick.available_actions.map((a) => (
                  <li
                    key={a}
                    className={`${a === hovered ? 'row-hover' : ''} ${a === tick.selected_action ? 'is-selected' : ''}`}
                    onMouseEnter={() => setState({ hoveredAction: a })}
                    onMouseLeave={() => setState({ hoveredAction: null })}
                  >
                    <span className="row-label">{prettyId(a)}</span>
                    <span className="num">{pct(out?.probabilities?.[a] ?? 0)}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )
      })}
    </div>
  )
}

function MotorSteps({ tick, plan }: { tick: TickTrace; plan: string[] }) {
  const steps = motorSteps(plan, tick.primitive_steps_executed)
  return (
    <ol className="motor-steps">
      {steps.map((s) => {
        const planned = new Set((s.planned ?? '').replace('_shoot', '+shoot').split('+'))
        return (
          <li key={s.index} title={s.words}>
            <span className="step-num">{s.index + 1}</span>
            <span className="keys">
              {s.pressed.map((k) => (
                <span key={k} className={`keycap ${planned.has(k) ? '' : 'extra'}`}>
                  {prettyId(k)}
                </span>
              ))}
            </span>
            {s.assisted && <span className="reflex">reflex</span>}
          </li>
        )
      })}
    </ol>
  )
}

/** The frame the agent saw at this decision, kept beside the chain so its six levels can be read against it. */
function SawCard({ bundle, tick, tickIndex }: { bundle: EpisodeBundle; tick: TickTrace; tickIndex: number }) {
  return (
    <section className="side-card saw-card" aria-labelledby="saw-title">
      <header className="panel-head">
        <span className="beat-num" title="Step 1 of a tick: freeze the world">
          1
        </span>
        <h3 id="saw-title">What it saw</h3>
      </header>
      <p className="sentence">
        Decision {tickIndex + 1} of {bundle.ticks.length} (tick {tick.tick}), {fmt(gameSeconds(tick.tick), 1)} s into
        the game.
      </p>
      <GameFrame bundle={bundle} tick={tick} />
      <button type="button" className="link-button" onClick={() => openInInspector('game')}>
        See what it read from it in the inspector →
      </button>
    </section>
  )
}

/** Arrows from each side input to the levels it feeds, measured from the laid-out cards. */
function Connectors({ layoutKey }: { layoutKey: string }) {
  const ref = useRef<SVGSVGElement | null>(null)
  const [paths, setPaths] = useState<Array<{ key: string; d: string; line: Source['line']; off: boolean }>>([])
  const [size, setSize] = useState({ w: 0, h: 0 })

  useLayoutEffect(() => {
    const svg = ref.current
    const grid = svg?.parentElement
    if (!svg || !grid) return
    const measure = () => {
      const box = grid.getBoundingClientRect()
      const tower = grid.querySelector('.tower')?.getBoundingClientRect()
      const side = grid.querySelector('.side-inputs')?.getBoundingClientRect()
      setSize({ w: box.width, h: box.height })
      // Side by side only; stacked on narrow screens, where each card says what it feeds instead.
      if (!tower || !side || side.left < tower.right) {
        setPaths([])
        return
      }
      const incoming = new Map<LevelId, Array<{ source: Source; y: number }>>()
      const sources = SOURCES.map((source) => {
        const el = grid.querySelector(`[data-source="${source.id}"]`)?.getBoundingClientRect()
        return { source, rect: el }
      })
      for (const { source, rect } of sources) {
        if (!rect) continue
        for (const level of source.feeds) {
          const list = incoming.get(level) ?? []
          list.push({ source, y: rect.top })
          incoming.set(level, list)
        }
      }
      const next: typeof paths = []
      for (const [level, list] of incoming) {
        const target = grid.querySelector(`[data-level="${level}"]`)?.getBoundingClientRect()
        if (!target) continue
        list.sort((a, b) => a.y - b.y)
        list.forEach(({ source }, i) => {
          const from = sources.find((s) => s.source.id === source.id)?.rect
          if (!from) return
          const span = Math.min(target.height - 24, 22 * list.length)
          const ty = target.top + 18 + (list.length === 1 ? 0 : (span * i) / (list.length - 1)) - box.top
          const tx = target.right - box.left
          const order = source.feeds.indexOf(level)
          const fy = from.top + 22 + order * 10 - box.top
          const fx = from.left - box.left
          const mid = (fx + tx) / 2
          next.push({
            key: `${source.id}-${level}`,
            d: `M${fx},${fy} C${mid},${fy} ${mid},${ty} ${tx + 6},${ty}`,
            line: source.line,
            off: grid.querySelector(`[data-source="${source.id}"]`)?.classList.contains('off') ?? false,
          })
        })
      }
      setPaths(next)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(grid)
    window.addEventListener('resize', measure)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', measure)
    }
    // The cards change height with the tick and with what is expanded, so measure again on both.
  }, [layoutKey])

  return (
    <svg ref={ref} className="connectors" width={size.w} height={size.h} aria-hidden>
      <defs>
        <marker id="connector-head" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="var(--faint)" />
        </marker>
      </defs>
      {paths.map((p) => (
        <path
          key={p.key}
          d={p.d}
          className={`connector ${p.line} ${p.off ? 'off' : ''}`}
          markerEnd="url(#connector-head)"
        />
      ))}
    </svg>
  )
}

/** The hierarchy: the same tick as six levels, slowest at the top, each drawn as the same card. */
export function Hierarchy({
  bundle,
  tick,
  tickIndex,
  ctx,
}: {
  bundle: EpisodeBundle
  tick: TickTrace
  tickIndex: number
  ctx: ExplainerContext
}) {
  // A row clicked on Watch opens its level here: expanded, scrolled to and flashed once.
  const focusLevel = useApp((s) => s.focusLevel)
  const [expanded, setExpanded] = useState<LevelId | null>(focusLevel)
  const [askedFor, setAskedFor] = useState(focusLevel)
  if (focusLevel && focusLevel !== askedFor) {
    setAskedFor(focusLevel)
    setExpanded(focusLevel)
  }
  useEffect(() => {
    if (!focusLevel) return
    const frame = window.requestAnimationFrame(() => {
      flashElement(`level-${focusLevel}`, true)
      setState({ focusLevel: null })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [focusLevel])
  const levels = towerLevels(tick, bundle.meta, bundle.proposals)
  const meta = bundle.meta
  const reading = pressureReading(pressureForArbiter(bundle.ticks, tickIndex))
  const next = pressureReading(exploration(tick))
  const plan = meta.actions[tick.selected_action]?.primitives ?? []

  const scores = (level: TowerLevel): ReactNode => {
    switch (level.id) {
      case 'gate':
        return <GatePipeline tick={tick} proposals={bundle.proposals} />
      case 'opinions':
        return <Opinions tick={tick} expanded={expanded === 'opinions'} />
      case 'motor':
        return <MotorSteps tick={tick} plan={plan} />
      default:
        return undefined
    }
  }
  const detail = (level: TowerLevel): ReactNode => {
    switch (level.id) {
      case 'gate':
        return (
          <>
            <GateDetail tick={tick} proposals={bundle.proposals} />
            <button type="button" className="link-button" onClick={() => openPanel('menu', 'gate')}>
              See it in Growing the menu →
            </button>
          </>
        )
      case 'steering':
        return <SteeringCard tick={tick} />
      case 'arbiter':
        return (
          <p className="dc-note">
            <strong>{explainPick(tick).headline}</strong> {explainPick(tick).detail}
          </p>
        )
      default:
        return null
    }
  }

  return (
    <main className="hierarchy" aria-label="The hierarchy at this tick">
      <header className="screen-head">
        <div>
          <h2>Tick {tick.tick} as a chain of six levels, the slowest at the top</h2>
          <p>
            Every level is the same kind of decision: a short menu it cannot leave, a score for each option, one rule
            that chooses, and a hard bound. The levels at the top change slowly and shape the menus of the fast ones
            below. Click a level for all of its options and the full explanation.
          </p>
        </div>
        <HeadTools tour />
      </header>
      <div className="tower-grid">
        <ol className="tower">
          {levels.map((level, i) => (
            <li key={level.id}>
              <DecisionCard
                id={level.id}
                index={i + 1}
                title={level.title}
                explainer={LEVEL_EXPLAINER[level.id]}
                bounds={level.bounds}
                menuSize={level.menuSize}
                chips={level.menu}
                candidates={level.candidates}
                choiceLabel={level.choiceLabel}
                rule={level.rule}
                reads={level.reads}
                writes={level.writes}
                idle={level.idle}
                expanded={expanded === level.id}
                onToggle={() => setExpanded(expanded === level.id ? null : level.id)}
                ctx={ctx}
                panel={LEVEL_PANEL[level.id]}
                actions={level.id === 'menu' || level.id === 'opinions' || level.id === 'arbiter'}
                scores={scores(level)}
                detail={detail(level)}
              />
            </li>
          ))}
        </ol>
        <aside className="side-inputs" aria-label="Side inputs: not levels, but evidence the levels read">
          <SawCard bundle={bundle} tick={tick} tickIndex={tickIndex} />
          {SOURCES.map((source) => {
            const off =
              (source.id === 'networks' && !meta.brains.learned_networks) ||
              (source.id === 'd1' && !meta.brains.d1_ultra)
            return (
              <SideCard key={source.id} source={source} ctx={ctx} off={off}>
                {source.id === 'exploration' && (
                  <ExplorationGauge
                    reading={reading}
                    next={next}
                    margin={tick.arbiter?.score_margin ?? 0}
                    rule={tick.arbiter?.pick_rule ?? 'greedy'}
                  />
                )}
                {source.id === 'simulator' && <SimulatorReading tick={tick} />}
                {source.id === 'networks' && <NetworksReading tick={tick} on={meta.brains.learned_networks} />}
                {source.id === 'd1' && <D1Reading tick={tick} meta={meta} />}
              </SideCard>
            )
          })}
        </aside>
        <Connectors layoutKey={`${bundle.name}/${tickIndex}/${expanded ?? ''}`} />
      </div>
    </main>
  )
}
