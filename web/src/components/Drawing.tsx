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

/** The two systems, drawn: what decides (d1-ultra) and what only produces evidence, enforces limits and presses keys (code). */
export function Drawing() {
  return (
    <figure className="drawing" data-testid="two-systems">
      <div className="drawing-cols">
        <section className="sys sys1" aria-label="System 1">
          <h3>
            <TermLink id="system-1" text="System 1" /> <span className="muted">every decision</span>
          </h3>
          <Node>
            <strong>Evidence</strong>: eighteen <TermLink id="channel" text="channels" /> of plain text, rendered from
            the game, the simulator and the value networks
          </Node>
          <Arrow>each sense is shown only the channels in its scope</Arrow>
          <div className="node-row">
            {SENSES.map((s) => (
              <Node key={s} d1 className={`sense sense-${s}`}>
                <span className={`dot sense-${s}`} aria-hidden /> {s}
              </Node>
            ))}
          </div>
          <Arrow>
            <TermLink id="message" text="messages" />: a recommended action, a reason and a strength, from each sense
            whose speak probability reached 0.5
          </Arrow>
          <Node d1 className="central">
            <strong>
              <TermLink id="central" text="Central instance" />
            </strong>
            : receives the messages and each sense’s relevance record, and chooses the action from the legal menu
          </Node>
          <Arrow>
            <TermLink id="pick" text="pick" />: top answer · drawn at random · missed
          </Arrow>
          <Node>
            <strong>Act</strong>: the action’s fixed primitives, held for 8 game frames; no keys after a miss
          </Node>
          <Arrow>the game moves on to the next decision</Arrow>
          <Node>
            <strong>History</strong>: every tick stored in full · the relevance ledger · the value networks, trained
            between episodes
          </Node>
        </section>
        <section className="sys sys2" aria-label="System 2">
          <h3>
            <TermLink id="system-2" text="System 2" />{' '}
            <span className="muted">after every 20 decisions, on its own thread</span>
          </h3>
          <Node>
            <strong>History channels</strong> over three time windows: the last 20 decisions, the last 100, and the last
            3 episodes
          </Node>
          <Arrow>each reflector is shown its own channels; the bounds filter the changes it may propose</Arrow>
          <Node d1 className="reflectors">
            <strong>
              Nine <TermLink id="reflector" text="reflectors" />
            </strong>
            <span className="node-list small">{REFLECTORS.map((r) => r.replace('_', ' ')).join(' · ')}</span>
          </Node>
          <Arrow>proposals: a change, a reason and a strength</Arrow>
          <Node d1>
            <strong>System 2’s central instance</strong>: one change, or none
          </Node>
          <div className="node-split">
            <div>
              <Arrow>for a scope change</Arrow>
              <Node>
                <strong>
                  <TermLink id="history-test" text="History test" />
                </strong>
                : the instance is asked again (d1-ultra) on stored decisions; the change passes or fails
              </Node>
            </div>
            <div>
              <Arrow>for a new macro</Arrow>
              <Node d1>
                <strong>
                  <TermLink id="slow-path" text="Slow path" />
                </strong>
                , then the checks, then the <TermLink id="admit-instance" text="admit instance" />: yes or no
              </Node>
            </div>
          </div>
          <Arrow>takes effect at the start of a decision</Arrow>
          <Node>
            <strong>
              <TermLink id="configuration" text="Configuration" />
            </strong>{' '}
            version n + 1: scopes, menu, strategy, exploration level
          </Node>
          <Arrow>
            a <TermLink id="trial" text="trial" /> of 60 decisions, then
          </Arrow>
          <Node d1>
            <strong>
              <TermLink id="judge" text="Trial judge" />
            </strong>
            : keep the change, or revert to the previous configuration
          </Node>
        </section>
      </div>
      <p className="drawing-loop">
        <span aria-hidden>↺</span> System 1 reads the configuration at every decision: what each instance is shown, the
        menu it chooses from, the active strategy and the exploration level. System 2 never presses a key and never
        delays a decision.
      </p>
      <figcaption className="drawing-legend">
        <span className="node d1 legend-node">
          <span className="node-badge">d1-ultra</span>
        </span>{' '}
        a d1-ultra instance: it decides · <span className="node code legend-node">code</span> code: it produces
        evidence, enforces limits and presses keys; it never chooses
      </figcaption>
    </figure>
  )
}
