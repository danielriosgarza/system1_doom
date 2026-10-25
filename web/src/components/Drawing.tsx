import type { ReactNode } from 'react'
import { SENSES } from '../data/readings'
import { REFLECTORS } from '../data/system2'
import { TermLink } from './TermLink'

/** A box of the drawing: a d1-ultra instance (it decides) or code (evidence, bounds, keys; it never chooses). */
function Node({ d1, children, className }: { d1?: boolean; children: ReactNode; className?: string }) {
  return (
    <div className={`node ${d1 ? 'd1' : 'code'} ${className ?? ''}`}>
      {d1 && <span className="node-badge">d1-ultra</span>}
      {children}
    </div>
  )
}

function Arrow({ children }: { children?: ReactNode }) {
  return (
    <div className="flow" aria-hidden={children ? undefined : true}>
      <span className="flow-line" aria-hidden />
      {children && <span className="flow-label">{children}</span>}
    </div>
  )
}

/** The two systems, drawn: what decides (d1-ultra) and what only renders, bounds and presses keys (code). */
export function Drawing() {
  return (
    <figure className="drawing" data-testid="two-systems">
      <div className="drawing-cols">
        <section className="sys sys1" aria-label="System 1">
          <h3>
            <TermLink id="system-1" text="System 1" /> <span className="muted">every decision</span>
          </h3>
          <Node>
            <strong>Evidence</strong>: eighteen <TermLink id="channel" text="channels" /> rendered as text from the
            game, the simulator and the value networks
          </Node>
          <Arrow>each sense is shown only its scope</Arrow>
          <div className="node-row">
            {SENSES.map((s) => (
              <Node key={s} d1 className={`sense sense-${s}`}>
                <span className={`dot sense-${s}`} aria-hidden /> {s}
              </Node>
            ))}
          </div>
          <Arrow>
            <TermLink id="message" text="messages" />: action, reason, strength (only senses that speak)
          </Arrow>
          <Node d1 className="central">
            <strong>
              <TermLink id="central" text="Central" />
            </strong>
            : hears the messages and each sense’s relevance, chooses the action from the legal menu
          </Node>
          <Arrow>
            <TermLink id="pick" text="pick" />: top · drawn · missed
          </Arrow>
          <Node>
            <strong>Act</strong>: the action’s fixed primitives for 8 game frames, or no keys after a miss
          </Node>
          <Arrow>the game moves on; the next decision</Arrow>
          <Node>
            <strong>History</strong>: every tick whole · the relevance ledger · the value networks, trained between
            episodes
          </Node>
        </section>
        <section className="sys sys2" aria-label="System 2">
          <h3>
            <TermLink id="system-2" text="System 2" /> <span className="muted">every 20 decisions, its own thread</span>
          </h3>
          <Node>
            <strong>History channels</strong> over three windows: the recent decisions, a longer run, the last episodes
          </Node>
          <Arrow>each reflector is shown its own channels; the bounds filter its changes</Arrow>
          <Node d1 className="reflectors">
            <strong>
              Nine <TermLink id="reflector" text="reflectors" />
            </strong>
            <span className="node-list small">{REFLECTORS.map((r) => r.replace('_', ' ')).join(' · ')}</span>
          </Node>
          <Arrow>proposals: change, reason, strength</Arrow>
          <Node d1>
            <strong>System 2’s central</strong>: one change, or none
          </Node>
          <div className="node-split">
            <div>
              <Arrow>a scope change</Arrow>
              <Node>
                <strong>
                  <TermLink id="history-test" text="History test" />
                </strong>
                : the instance asked again (d1-ultra) on stored ticks; passes or not
              </Node>
            </div>
            <div>
              <Arrow>a new macro</Arrow>
              <Node d1>
                <strong>
                  <TermLink id="slow-path" text="Slow path" />
                </strong>
                , bounds, then the <TermLink id="admit-instance" text="admit instance" />: yes or no
              </Node>
            </div>
          </div>
          <Arrow>at a tick boundary</Arrow>
          <Node>
            <strong>
              <TermLink id="configuration" text="Configuration" />
            </strong>{' '}
            version n + 1: scopes, menu, strategy, level
          </Node>
          <Arrow>
            a <TermLink id="trial" text="trial" />, then
          </Arrow>
          <Node d1>
            <strong>
              <TermLink id="judge" text="Trial judge" />
            </strong>
            : keep, or revert to the previous configuration
          </Node>
        </section>
      </div>
      <p className="drawing-loop">
        <span aria-hidden>↺</span> System 1 reads the configuration at every decision: what each instance is shown, the
        menu it chooses from, the strategy and the level. System 2 never presses a key and never holds up a tick.
      </p>
      <figcaption className="drawing-legend">
        <span className="node d1 legend-node">
          <span className="node-badge">d1-ultra</span>
        </span>{' '}
        a d1-ultra instance: it decides · <span className="node code legend-node">code</span> code: it renders evidence,
        keeps bounds and presses keys; it never chooses
      </figcaption>
    </figure>
  )
}
