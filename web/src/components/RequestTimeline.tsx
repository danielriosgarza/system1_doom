import {
  EXPANSION_TRIGGERS,
  MEMORY_LABELS,
  MODULES,
  type ModuleName,
  type RequestSpan,
  TRIGGER_OTHER,
  prettyId,
  triggerAt,
} from '../data/derive'
import type { TickTrace } from '../schema/bundle'
import { setTickIndex, useApp } from '../store'
import { Mark } from './Marks'
import { useWidth } from './useWidth'

const ROW_H = 46
const TOP = 12
const BOTTOM = 34
const LANE = 41
const PAD = 8

/** One module across the episode: its counter up to the threshold, its other condition, its requests. */
function ModuleStrip({
  module,
  ticks,
  spans,
  width,
}: {
  module: ModuleName
  ticks: TickTrace[]
  spans: RequestSpan[]
  width: number
}) {
  const tickIndex = useApp((s) => s.tickIndex)
  const trigger = EXPANSION_TRIGGERS[module]
  const readings = ticks.map((t) => triggerAt(module, t))
  const slot = Math.max(0, width - PAD * 2) / Math.max(1, ticks.length)
  const x = (i: number) => PAD + slot * (i + 0.5)
  const indexOf = (tick: number) => ticks.findIndex((t) => t.tick === tick)
  const top = Math.max(trigger.threshold ?? 1, ...readings.map((r) => r.value ?? 0))
  const y = (v: number) => BOTTOM - (Math.min(v, top) / top) * (BOTTOM - TOP)
  const line =
    trigger.counter === null
      ? null
      : readings.map((r, i) => `${i === 0 ? 'M' : 'L'}${x(i) - slot / 2},${y(r.value ?? 0)} h${slot}`).join(' ')
  const mine = spans.filter((s) => s.module === module)
  const label = trigger.counter ? (MEMORY_LABELS[trigger.counter] ?? trigger.counter) : null
  return (
    <div className="rt-row" data-module={module}>
      <div className="rt-label">
        <span className="dot" style={{ background: `var(--${module})` }} /> {module}
        <span className="muted">
          {label ? `${label} vs ${trigger.threshold}` : 'no counter'}
          {TRIGGER_OTHER[module] ? ` · or ${TRIGGER_OTHER[module]}` : ''}
          {module === 'goal' ? ' · the controller never advances it' : ''}
        </span>
      </div>
      <svg
        width={width}
        height={ROW_H}
        role="img"
        aria-label={`${module}: ${mine.length === 0 ? 'never asked' : `asked at tick ${mine.map((s) => s.asked).join(' and ')}`}`}
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          setTickIndex(Math.floor((e.clientX - rect.left - PAD) / Math.max(1, slot)))
        }}
      >
        {mine.map((s) => {
          const from = indexOf(s.asked)
          const to = s.arrived === null ? ticks.length - 1 : indexOf(s.arrived)
          return (
            <rect
              key={`busy-${s.asked}`}
              className="rt-busy"
              x={x(from)}
              y={2}
              width={Math.max(2, x(to) - x(from))}
              height={ROW_H - 4}
            >
              <title>
                The worker was busy with this request from tick {s.asked}
                {s.arrived === null ? ' to the end' : ` until tick ${s.arrived}`}
              </title>
            </rect>
          )
        })}
        {trigger.threshold !== null && (
          <>
            <line
              x1={PAD}
              x2={width - PAD}
              y1={y(trigger.threshold)}
              y2={y(trigger.threshold)}
              className="rt-threshold"
            />
            <text x={width - PAD} y={y(trigger.threshold) - 2} textAnchor="end" className="rt-tick-label">
              asks at {trigger.threshold}
            </text>
          </>
        )}
        <line x1={PAD} x2={width - PAD} y1={BOTTOM} y2={BOTTOM} className="rt-base" />
        {line && <path d={line} className="rt-counter" style={{ stroke: `var(--${module})` }} />}
        {readings.map((r, i) =>
          r.other ? (
            <rect
              key={`other-${i}`}
              x={x(i) - 3}
              y={LANE - 3}
              width={6}
              height={6}
              style={{ fill: `var(--${module})` }}
              className="rt-other"
            >
              <title>
                Tick {ticks[i]?.tick}: {TRIGGER_OTHER[module]}
              </title>
            </rect>
          ) : null,
        )}
        {mine.map((s) => (
          <g key={`ask-${s.asked}`} className="rt-mark">
            <Mark kind="expansion" x={x(indexOf(s.asked))} y={7} />
            <title>
              Tick {s.asked}: {module} asked. “{s.description}”
            </title>
          </g>
        ))}
        {mine.map((s) =>
          s.arrived === null ? null : (
            <g key={`arrive-${s.arrived}`} className="rt-mark">
              <Mark kind="admission" x={x(indexOf(s.arrived))} y={7} />
              <title>
                Tick {s.arrived}: {prettyId(s.proposal?.admitted_action_id ?? 'the proposal')} reached the gate
                {s.proposal?.admission_decision ? ' and was admitted' : ' and was rejected'}
              </title>
            </g>
          ),
        )}
        <rect x={x(tickIndex) - slot / 2} y={0} width={slot} height={ROW_H} className="rt-cursor" />
      </svg>
    </div>
  )
}

/** Every module's expansion rule over the whole episode, with the requests and when they were answered. */
export function RequestTimeline({ ticks, spans }: { ticks: TickTrace[]; spans: RequestSpan[] }) {
  const [ref, measured] = useWidth<HTMLDivElement>()
  const width = Math.max(0, measured - 2)
  const step = ticks.length > 40 ? 10 : 5
  return (
    <div className="request-timeline">
      <div className="rt-rows" ref={ref}>
        {MODULES.map((m) => (
          <ModuleStrip key={m} module={m} ticks={ticks} spans={spans} width={width} />
        ))}
        <svg className="rt-axis" width={width} height={16} aria-hidden>
          {ticks.map((t, i) =>
            t.tick % step === 0 ? (
              <text
                key={t.tick}
                x={PAD + (Math.max(0, width - PAD * 2) / Math.max(1, ticks.length)) * (i + 0.5)}
                y={12}
                textAnchor="middle"
                className="rt-tick-label"
              >
                {t.tick}
              </text>
            ) : null,
          )}
        </svg>
      </div>
      <div className="rt-legend muted" aria-hidden>
        <span>
          <svg width={18} height={10}>
            <path d="M1,8 h6 v-5 h10" className="rt-counter" style={{ stroke: 'var(--muted)' }} />
          </svg>
          counter
        </span>
        <span>
          <svg width={18} height={10}>
            <line x1={1} x2={17} y1={5} y2={5} className="rt-threshold" />
          </svg>
          threshold
        </span>
        <span>
          <svg width={10} height={10}>
            <rect x={2} y={2} width={6} height={6} style={{ fill: 'var(--muted)' }} />
          </svg>
          other condition holds
        </span>
        <span>
          <svg width={12} height={14}>
            <Mark kind="expansion" x={5} y={7} />
          </svg>
          asked
        </span>
        <span>
          <svg width={18} height={10}>
            <rect x={1} y={1} width={16} height={8} className="rt-busy" />
          </svg>
          worker busy
        </span>
        <span>
          <svg width={12} height={12}>
            <Mark kind="admission" x={6} y={6} />
          </svg>
          reached the gate
        </span>
      </div>
    </div>
  )
}
