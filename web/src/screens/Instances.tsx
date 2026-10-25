import { type KeyboardEvent, useId } from 'react'
import { BarList, Meter } from '../components/Bars'
import { Panel } from '../components/Panel'
import { INSTANCES, STRIP, missWords, pickWords } from '../content/instances'
import { type EpisodeBundle, bundleFileUrl } from '../data/loader'
import {
  CENTRAL,
  CHANNELS,
  type InstanceView,
  boundsOf,
  centralRow,
  concernOf,
  fmt,
  instanceView,
  words,
} from '../data/readings'
import type { TickTrace } from '../schema/bundle'
import { setState, useApp } from '../store'

const HEADER = /^\[[a-z0-9_:]+\]$/

/** The state text exactly as sent, with its channel headers picked out. */
function EvidenceText({ text, name }: { text: string; name: string }) {
  const lines = text.split('\n')
  return (
    <pre className="evidence-text" data-testid="evidence-text" data-instance={name} tabIndex={0}>
      {lines.map((line, i) => (
        <span key={i} className={HEADER.test(line) ? 'ev-head' : undefined}>
          {line}
          {i < lines.length - 1 ? '\n' : ''}
        </span>
      ))}
    </pre>
  )
}

/** The eighteen channels: the ones in the instance's scope, and the ones it was not shown. */
function ScopeChips({ view }: { view: InstanceView }) {
  return (
    <div className="scope-chips">
      <p className="chips-label">{INSTANCES.scope}</p>
      <ul className="chips" data-testid="scope-chips">
        {CHANNELS.filter((c) => view.scope.includes(c)).map((c) => (
          <li key={c} className="chip on" data-channel={c}>
            {c}
          </li>
        ))}
      </ul>
      <p className="chips-label">{INSTANCES.hidden}</p>
      <ul className="chips" data-testid="hidden-chips">
        {view.hidden.map((c) => (
          <li key={c} className="chip off" data-channel={c}>
            {c}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Answers({ view, tick, yesAt }: { view: InstanceView; tick: TickTrace; yesAt: number }) {
  const central = view.kind === 'central'
  return (
    <div className="answers" data-testid="answers">
      {view.missed && (
        <div className="miss-box" data-testid="miss-box">
          <p>
            <strong>{INSTANCES.miss}:</strong> {missWords(view.missReason)}
            {view.error ? ` (${view.error})` : ''}.{' '}
            {central ? 'No keys were held for this decision.' : 'A missed sense is silent; nothing stands in for it.'}
          </p>
          {view.raw && (
            <>
              <p className="chips-label">{INSTANCES.raw}</p>
              <pre className="raw-answer">{view.raw}</pre>
            </>
          )}
        </div>
      )}
      {!central && (
        <div className="answer-block">
          <h3>
            {INSTANCES.speak}{' '}
            <span className="answer-value">
              {fmt(view.speak)} · {view.missed ? STRIP.missed : view.spoke ? STRIP.spoke : STRIP.silent}
            </span>
          </h3>
          <Meter value={view.speak} mark={yesAt} label="speak" className="answer-meter" />
          <p className="faint small">{INSTANCES.speakNote(yesAt)}</p>
        </div>
      )}
      <div className="answer-block">
        <h3>
          {central ? INSTANCES.choice : INSTANCES.action}{' '}
          <span className="answer-value">{words(view.action) || '–'}</span>
        </h3>
        {central && <p className="small">{pickWords(centralRow(tick))}</p>}
        <BarList
          bars={view.actionBars}
          label={central ? 'The central’s choice distribution' : 'Action distribution'}
          floor={0.02}
          mark={{ option: tick.executed_action, word: INSTANCES.executed }}
        />
      </div>
      {!central && (
        <div className="answer-block">
          <h3>
            {INSTANCES.reason} <span className="answer-value">{words(view.reason) || '–'}</span>
          </h3>
          <BarList bars={view.reasonBars} label="Reason distribution" />
        </div>
      )}
      {central && (
        <div className="answer-block">
          <h3>{INSTANCES.heard}</h3>
          {(tick.messages ?? []).length === 0 ? (
            <p className="small muted">{INSTANCES.heardNone}</p>
          ) : (
            <ul className="heard">
              {(tick.messages ?? []).map((m) => (
                <li key={m.sense}>
                  <span className={`dot sense-${m.sense}`} aria-hidden /> {m.sense} says{' '}
                  <strong>{words(m.action)}</strong>, strength {fmt(m.strength)}, reason {words(m.reason)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <p className="faint small">
        {view.latency === null ? '' : `answered in ${Math.round(view.latency)} ms`}
        {view.retries ? ` after ${view.retries} retr${view.retries === 1 ? 'y' : 'ies'}` : ''}
        {view.cost === null ? '' : ` · $${view.cost.toFixed(6)}`}
      </p>
    </div>
  )
}

/** One decision opened: every instance's evidence, verbatim, and its answers. */
export function Instances({ bundle, tick, tickIndex }: { bundle: EpisodeBundle; tick: TickTrace; tickIndex: number }) {
  const selected = useApp((s) => s.instance)
  const tabsId = useId()
  const names = Object.keys(tick.instances)
  const name = names.includes(selected) ? selected : (names[0] ?? CENTRAL)
  const view = instanceView(tick, name)
  const yesAt = boundsOf(bundle.meta).yes_at
  const configuration =
    tick.configuration_version === bundle.meta.configuration_end.version
      ? bundle.meta.configuration_end
      : bundle.meta.configuration_start
  const concern = concernOf(configuration, name)
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const at = names.indexOf(name)
    const next = e.key === 'ArrowRight' ? at + 1 : e.key === 'ArrowLeft' ? at - 1 : null
    if (next === null) return
    e.preventDefault()
    const target = names[(next + names.length) % names.length]
    if (!target) return
    setState({ instance: target })
    window.requestAnimationFrame(() => document.getElementById(`${tabsId}-${target}`)?.focus())
  }
  return (
    <main className="screen instances" aria-label="The instances">
      <header className="screen-head">
        <h2>{INSTANCES.title(tickIndex + 1)}</h2>
        <p>{INSTANCES.intro}</p>
      </header>
      <div className="instance-tabs" role="tablist" aria-label={INSTANCES.tabs}>
        {names.map((n) => {
          const r = tick.instances[n]
          const state = r?.missed ? 'missed' : r?.kind === 'central' ? 'central' : r?.spoke ? 'spoke' : 'silent'
          return (
            <button
              key={n}
              id={`${tabsId}-${n}`}
              type="button"
              role="tab"
              aria-selected={n === name}
              aria-controls={`${tabsId}-panel`}
              tabIndex={n === name ? 0 : -1}
              data-instance={n}
              data-state={state}
              onClick={() => setState({ instance: n })}
              onKeyDown={onKey}
            >
              <span className={`dot sense-${n}`} aria-hidden />
              {n}
              <span className="tab-state">
                {state === 'central' ? words(tick.executed_action) || STRIP.missed : STRIP[state]}
              </span>
            </button>
          )
        })}
      </div>
      {view && (
        <div
          className="instance-grid"
          role="tabpanel"
          id={`${tabsId}-panel`}
          aria-labelledby={`${tabsId}-${name}`}
          data-testid="instance-panel"
          data-instance={name}
        >
          <Panel id="evidence" aside={concern ? <span className="panel-aside">{concern}</span> : undefined}>
            <ScopeChips view={view} />
            {view.imageRef ? (
              <figure className="instance-frame">
                <div className="frame">
                  <img src={bundleFileUrl(bundle, view.imageRef)} alt={`${INSTANCES.frame}: ${view.imageRef}`} />
                </div>
                <figcaption className="faint small">{INSTANCES.frame}</figcaption>
              </figure>
            ) : (
              <p className="faint small">{INSTANCES.noFrame}</p>
            )}
            <p className="chips-label">{INSTANCES.text}</p>
            <EvidenceText text={tick.instances[name]?.evidence ?? ''} name={name} />
          </Panel>
          <Panel id="answers">
            <Answers view={view} tick={tick} yesAt={yesAt} />
          </Panel>
        </div>
      )}
    </main>
  )
}
