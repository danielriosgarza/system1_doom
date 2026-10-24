import { useState } from 'react'
import {
  MODULES,
  type ModuleName,
  TRUST_COUNT,
  contextWords,
  fmt,
  prettyId,
  trustActions,
  trustRow,
  trustRows,
} from '../data/derive'
import type { EpisodeMeta, TickTrace, TrustFile } from '../schema/bundle'
import { setState, useApp } from '../store'

const FIRST_ROWS = 20

function Cell({ n, lambda, action, context }: { n: number; lambda: number; action: string; context: string }) {
  if (n === 0) return <td className="tm-empty" title={`${prettyId(action)}: never taken here in training`} />
  return (
    <td title={`${prettyId(action)} in ${context}: n = ${n}, λ = ${n} ÷ (${n} + ${TRUST_COUNT}) = ${fmt(lambda, 3)}`}>
      <span className="tm-cell" style={{ ['--l' as string]: lambda }} />
    </td>
  )
}

/** Contexts × actions: how much say the networks have, earned by training experience. */
export function TrustMap({ trust, meta, tick }: { trust: TrustFile; meta: EpisodeMeta; tick: TickTrace }) {
  const hovered = useApp((s) => s.hoveredAction)
  const [showAll, setShowAll] = useState(false)
  const actions = trustActions(trust, meta)
  const rows = trustRows(trust, actions)
  const here = trustRow(trust, tick.context_signature, actions)
  const others = rows.filter((r) => r.context !== here.context)
  const shown = showAll ? others : others.slice(0, FIRST_ROWS - 1)
  return (
    <div className="trustmap">
      <div className="tm-scroll">
        <table className="tm-table">
          <thead>
            <tr>
              <th className="tm-context-head">Situation · training decisions</th>
              {actions.map((a) => (
                <th
                  key={a}
                  className={`tm-action ${a === tick.selected_action ? 'selected' : ''} ${a === hovered ? 'hovered' : ''}`}
                  data-action={a}
                  scope="col"
                >
                  <span>{prettyId(a)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[here, ...shown].map((row, i) => {
              const words = contextWords(row.context)
              return (
                <tr key={row.context} className={i === 0 ? 'pinned' : ''} data-context={row.context}>
                  <th scope="row" className="tm-context">
                    {i === 0 && <span className="tm-pin">this tick</span>}
                    {words} <span className="muted">· {row.n.toLocaleString('en')}</span>
                  </th>
                  {row.cells.map((c) => (
                    <Cell key={c.action} n={c.n} lambda={c.lambda} action={c.action} context={words} />
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="tm-foot">
        <span className="tm-legend" aria-hidden>
          {[0.1, 0.25, 0.5, 0.75, 0.9].map((l) => (
            <span key={l} className="tm-cell" style={{ ['--l' as string]: l }} />
          ))}
        </span>
        <span className="muted">
          λ from 0.1 to 0.9; half the say at n = {TRUST_COUNT}, three quarters at n = {3 * TRUST_COUNT}. Blank: never
          taken there.
        </span>
        <button type="button" className="link-button" onClick={() => setShowAll(!showAll)}>
          {showAll ? `Show the first ${FIRST_ROWS}` : `Show all ${rows.length} situations`}
        </button>
      </div>
      {here.n === 0 && (
        <p className="empty-note">
          This tick&apos;s situation never came up in training, so every module here is its heuristic alone.
        </p>
      )}
    </div>
  )
}

/** This tick's row in full: n, λ, and one module's heuristic, learned and blended utility per legal action. */
export function TrustHere({ trust, tick }: { trust: TrustFile; tick: TickTrace }) {
  const [module, setModule] = useState<ModuleName>('survival')
  const hovered = useApp((s) => s.hoveredAction)
  const out = tick.module_outputs[module]
  return (
    <div className="trust-here">
      <div className="segmented small" role="group" aria-label="Module">
        {MODULES.map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={m === module}
            className={m === module ? 'on' : ''}
            onClick={() => setModule(m)}
          >
            <span className="dot" style={{ background: `var(--${m})` }} /> {m}
          </button>
        ))}
      </div>
      <table className="th-table">
        <thead>
          <tr>
            <th scope="col">legal action</th>
            <th scope="col" title="training decisions that took it in this situation">
              n
            </th>
            <th scope="col">λ</th>
            <th scope="col">heuristic</th>
            <th scope="col">learned</th>
            <th scope="col">blend</th>
          </tr>
        </thead>
        <tbody>
          {tick.available_actions.map((a) => {
            const n = trust.action_counts[`${tick.context_signature}|${a}`] ?? 0
            return (
              <tr
                key={a}
                data-action={a}
                className={`${a === tick.selected_action ? 'is-selected' : ''} ${a === hovered ? 'row-hover' : ''}`}
                onMouseEnter={() => setState({ hoveredAction: a })}
                onMouseLeave={() => setState({ hoveredAction: null })}
              >
                <th scope="row">{prettyId(a)}</th>
                <td className="num">{n}</td>
                <td className="num">{fmt(out?.trust?.[a] ?? 0, 3)}</td>
                <td className="num">{fmt(out?.utility_heuristic?.[a] ?? 0, 2)}</td>
                <td className="num learned">{fmt(out?.utility_learned?.[a] ?? 0, 2)}</td>
                <td className="num strong">{fmt(out?.utility_blended?.[a] ?? 0, 2)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="dc-note">
        blend = (1 − λ) · heuristic + λ · learned, the same λ for all five modules. The heuristic is the module&apos;s
        hand-written score; the learned value is its network&apos;s prediction of the module&apos;s standardised return.
      </p>
    </div>
  )
}
