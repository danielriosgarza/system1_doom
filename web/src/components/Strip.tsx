import { useMemo } from 'react'
import { STRIP, configWords, missWords, pickWords } from '../content/instances'
import type { EpisodeBundle } from '../data/loader'
import {
  CENTRAL,
  actRow,
  boundsOf,
  centralRow,
  configurationAt,
  fmt,
  senseRows,
  versionTimeline,
  words,
} from '../data/readings'
import type { TickTrace } from '../schema/bundle'
import { openInstance } from '../store'
import { Meter } from './Bars'

/** Watch's strip: the five senses, the central and Act at this decision, and the configuration under them. */
export function Strip({ bundle, tick, tickIndex }: { bundle: EpisodeBundle; tick: TickTrace; tickIndex: number }) {
  const yesAt = boundsOf(bundle.meta).yes_at
  const senses = senseRows(tick)
  const central = centralRow(tick)
  const act = actRow(tick)
  return (
    <section className="strip" data-testid="strip" aria-labelledby="strip-title">
      <header className="strip-head">
        <h3 id="strip-title">{STRIP.title}</h3>
        <p>{STRIP.note}</p>
      </header>
      <ul className="strip-rows">
        {senses.map((row) => {
          const state = row.missed ? 'missed' : row.spoke ? 'spoke' : 'silent'
          return (
            <li key={row.name}>
              <button
                type="button"
                className={`strip-row sense-row ${state}`}
                data-testid="sense-row"
                data-sense={row.name}
                data-state={state}
                title={STRIP.rowTitle}
                onClick={() => openInstance(row.name)}
              >
                <span className={`dot sense-${row.name}`} aria-hidden />
                <span className="strip-name">{row.name}</span>
                <span className="strip-state">{STRIP[state]}</span>
                <Meter value={row.strength} mark={yesAt} label={`${row.name} speak`} className="strip-meter" />
                <span className="strip-value">
                  {row.missed ? (
                    missWords(row.missReason)
                  ) : (
                    <>
                      <span className="strip-strength">{fmt(row.strength)}</span>{' '}
                      <span className="strip-action">{words(row.action)}</span>
                      <span className="strip-reason"> · {words(row.reason)}</span>
                      {row.followed && <span className="strip-followed"> · {STRIP.followed}</span>}
                    </>
                  )}
                </span>
              </button>
            </li>
          )
        })}
        <li>
          <button
            type="button"
            className={`strip-row central-row ${central.kind}`}
            data-testid="central-row"
            data-kind={central.kind}
            title={STRIP.rowTitle}
            onClick={() => openInstance(CENTRAL)}
          >
            <span className="dot sense-central" aria-hidden />
            <span className="strip-name">{STRIP.central}</span>
            <span className="strip-pick" data-testid="central-pick">
              {central.action ? words(central.action) : 'no action'}
            </span>
            <span className="strip-value">{pickWords(central)}</span>
          </button>
        </li>
        <li className="strip-row act-row" data-testid="act-row">
          <span className="dot act" aria-hidden />
          <span className="strip-name">{STRIP.act}</span>
          <span className="strip-value">
            {act.action ? act.keys : 'nothing pressed: the central instance missed'}
            <span className="faint"> · {STRIP.actGloss}</span>
          </span>
        </li>
      </ul>
      <ConfigLine bundle={bundle} tickIndex={tickIndex} />
    </section>
  )
}

/** The thin line under the strip: the configuration version, its last change, and the trial in flight. */
export function ConfigLine({ bundle, tickIndex }: { bundle: EpisodeBundle; tickIndex: number }) {
  const timeline = useMemo(() => versionTimeline(bundle), [bundle])
  const at = configurationAt(bundle, timeline, tickIndex)
  const line = configWords(at)
  return (
    <p className="config-line" data-testid="config-line" data-version={at.version}>
      <span className="config-version">{line.version}</span>
      <span className="config-sep" aria-hidden>
        ·
      </span>
      <span>{line.change}</span>
      <span className="config-sep" aria-hidden>
        ·
      </span>
      <span className={at.trial ? 'config-trial' : 'faint'}>{line.trial}</span>
    </p>
  )
}
