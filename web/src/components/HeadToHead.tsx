import { admissions, fmt, pct, stillPlaying, stoppedEarly, tickEvents } from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import type { BundleIndexEntry, EpisodeMeta, EvaluationSummary } from '../schema/bundle'
import { openEpisode, setTickIndex, useApp } from '../store'
import { Mark } from './Marks'
import { KIND_LANE } from './markKinds'
import { useEpisode } from './useEpisode'
import { useWidth } from './useWidth'

const STRIP_H = 58
const TOP = 14
const BOTTOM = 40
const PAD = 8

const BRAINS: Array<{ id: 'heuristics' | 'latest' | 'best'; label: string }> = [
  { id: 'heuristics', label: 'Heuristics only' },
  { id: 'latest', label: 'Latest checkpoint' },
  { id: 'best', label: 'Best checkpoint' },
]

function brainLabel(meta: Pick<EpisodeMeta, 'model' | 'brains'>): string {
  if (meta.model === 'heuristics') return 'the heuristics alone'
  return meta.brains.d1_ultra ? "with the networks and d1-ultra's advice" : 'with the networks'
}

function ending(meta: EpisodeMeta): string {
  const { result, tick_count: ticks } = meta
  if (stillPlaying(meta)) return `played ${ticks} decisions so far, and the episode is still running`
  const verb = result.cleared
    ? 'cleared the level'
    : result.died
      ? 'died'
      : stoppedEarly(meta)
        ? 'was stopped by hand'
        : 'ran out of time'
  return `${verb} after ${ticks} decisions with reward ${fmt(result.reward, 0)}`
}

function Strip({
  bundle,
  tick,
  span,
  current,
}: {
  bundle: EpisodeBundle
  /** The tick under the shared cursor. */
  tick: number
  /** Ticks on the shared axis, so both strips line up. */
  span: number
  current: boolean
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const slot = Math.max(0, width - PAD * 2) / Math.max(1, span)
  const x = (t: number) => PAD + slot * (t + 0.5)
  const y = (h: number) => BOTTOM - (Math.max(0, Math.min(100, h)) / 100) * (BOTTOM - TOP)
  const admitted = admissions(bundle.proposals)
  const path = bundle.ticks.map((t, i) => `${i === 0 ? 'M' : 'L'}${x(t.tick)},${y(t.state?.health ?? 0)}`).join(' ')
  const last = bundle.ticks[bundle.ticks.length - 1]?.tick ?? 0
  const open = () => {
    if (current) return
    void openEpisode(bundle.name, Math.min(tick, last))
  }
  return (
    <div className={`h2h-strip ${current ? 'current' : 'other'}`} ref={ref} data-episode={bundle.name}>
      <div className="h2h-strip-head">
        <strong>
          {bundle.meta.model === 'heuristics'
            ? 'Heuristics only'
            : bundle.meta.brains.d1_ultra
              ? "With the networks and d1-ultra's advice"
              : 'With the networks'}
        </strong>{' '}
        <span className="muted">{ending(bundle.meta)}</span>
        {current ? (
          <span className="h2h-here">this recording</span>
        ) : (
          <button type="button" className="link-button" onClick={open}>
            Open it at tick {Math.min(tick, last)} →
          </button>
        )}
      </div>
      <svg
        width={width}
        height={STRIP_H}
        role="img"
        aria-label={`Health over ${bundle.ticks.length} ticks, ${brainLabel(bundle.meta)}`}
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          const t = Math.max(0, Math.min(last, Math.floor((e.clientX - rect.left - PAD) / Math.max(1, slot))))
          if (current) setTickIndex(bundle.ticks.findIndex((tt) => tt.tick === t))
          else void openEpisode(bundle.name, t)
        }}
      >
        <rect x={PAD} y={TOP} width={Math.max(0, x(last) + slot / 2 - PAD)} height={BOTTOM - TOP} className="h2h-bed" />
        <path d={path} className="h2h-health" />
        {bundle.ticks.map((t) => {
          const list = tickEvents(t, admitted)
          return list.map((e, j) => {
            // Marks of one tick and lane sit side by side, as on the timeline, so a minus and a bar never make a plus.
            const sameLane = list.filter((o) => KIND_LANE[o.kind] === KIND_LANE[e.kind])
            const offset = (sameLane.indexOf(e) - (sameLane.length - 1) / 2) * Math.min(9, slot)
            return (
              <Mark
                key={`${t.tick}-${e.kind}-${j}`}
                kind={e.kind}
                x={x(t.tick) + offset}
                y={KIND_LANE[e.kind] === 'top' ? 7 : 50}
              />
            )
          })
        })}
        {tick <= last && (
          <rect x={x(tick) - slot / 2} y={TOP - 2} width={slot} height={BOTTOM - TOP + 4} className="h2h-cursor" />
        )}
      </svg>
    </div>
  )
}

/** The evaluation table, then the two recordings of the same seed side by side on one tick axis. */
export function HeadToHead({ bundle, evaluation }: { bundle: EpisodeBundle; evaluation: EvaluationSummary | null }) {
  const index = useApp((s) => s.index)
  const tickIndex = useApp((s) => s.tickIndex)
  const tick = bundle.ticks[tickIndex]?.tick ?? 0
  const pair: BundleIndexEntry | undefined = index?.episodes.find(
    (e) =>
      e.name !== bundle.name &&
      e.scenario === bundle.meta.scenario &&
      e.seed === bundle.meta.seed &&
      (e.model === 'heuristics') !== (bundle.meta.model === 'heuristics'),
  )
  const other = useEpisode(pair?.name ?? null)

  // Heuristics on top, the networks below.
  const both = (other ? [bundle, other] : [bundle]).sort(
    (a, b) => Number(a.meta.model !== 'heuristics') - Number(b.meta.model !== 'heuristics'),
  )
  const span = Math.max(...both.map((b) => (b.ticks[b.ticks.length - 1]?.tick ?? 0) + 1))
  const heuristic = both.find((b) => b.meta.model === 'heuristics')
  const learned = both.find((b) => b.meta.model !== 'heuristics')
  const builtin = Object.values(bundle.meta.actions).filter((a) => a.builtin).length
  return (
    <div className="h2h">
      {evaluation ? (
        <div className="h2h-table-wrap">
          <table className="h2h-table">
            <caption>
              {evaluation.episodes} seeded episodes per brain after {evaluation.trained_episodes ?? '?'} training
              episodes, played greedily: no exploration, no learning
              {bundle.meta.brains.d1_ultra ? ', and no d1-ultra, unlike this recording' : ''}.
            </caption>
            <thead>
              <tr>
                <th scope="col">brain</th>
                <th scope="col">reward</th>
                <th scope="col">cleared</th>
                <th scope="col">survived</th>
                <th scope="col">kills</th>
                <th scope="col">health left</th>
                <th scope="col">decisions</th>
              </tr>
            </thead>
            <tbody>
              {BRAINS.map(({ id, label }) => {
                const s = evaluation[id]
                if (!s) return null
                return (
                  <tr key={id} data-brain={id} className={bundle.meta.model === id ? 'is-selected' : ''}>
                    <th scope="row">{label}</th>
                    <td className="num">{fmt(s.reward, 0)}</td>
                    <td className="num">{pct(s.cleared)}</td>
                    <td className="num">{pct(s.survived)}</td>
                    <td className="num">{fmt(s.kills, 1)}</td>
                    <td className="num">{fmt(s.health, 1)}</td>
                    <td className="num">{fmt(s.ticks, 0)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty-note">This bundle carries no evaluation of the training run.</p>
      )}
      {heuristic && learned ? (
        <p className="h2h-sentence">
          Same scenario and seed, the same {builtin} built-in actions: the heuristics alone {ending(heuristic.meta)};{' '}
          {brainLabel(learned.meta)} the controller {ending(learned.meta)}.
        </p>
      ) : pair ? (
        <p className="h2h-sentence muted">Loading the other recording of seed {bundle.meta.seed}…</p>
      ) : (
        <p className="h2h-sentence muted">No other recording of this scenario and seed to compare with.</p>
      )}
      <div className="h2h-strips">
        {both.map((b) => (
          <Strip key={b.name} bundle={b} tick={tick} span={span} current={b.name === bundle.name} />
        ))}
      </div>
    </div>
  )
}
