import { useRef, useState } from 'react'
import { BRAIN_WORDS, INDEX_COMMAND, MODULES, exportCommand, fmt, pct, prettyId, utcStamp } from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import type { TickTrace } from '../schema/bundle'
import { openEpisode, useApp } from '../store'
import { Brains } from './Brains'

const thousands = (n: number) => n.toLocaleString('en-US')

/** The command in a block, with a button that copies it; where the clipboard is blocked, it selects it. */
function Command({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState<string | null>(null)
  const ref = useRef<HTMLElement | null>(null)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied('Copied')
    } catch {
      const range = document.createRange()
      if (ref.current) range.selectNodeContents(ref.current)
      window.getSelection()?.removeAllRanges()
      window.getSelection()?.addRange(range)
      setCopied('Selected: copy it with Ctrl+C or ⌘C')
    }
    window.setTimeout(() => setCopied(null), 2500)
  }
  return (
    <div className="command">
      <pre>
        <code ref={ref}>{text}</code>
      </pre>
      <button type="button" className="icon-button" onClick={() => void copy()} aria-label={`Copy ${label}`}>
        Copy
      </button>
      <span className="command-status muted" aria-live="polite">
        {copied}
      </span>
    </div>
  )
}

/** This recording: what it is, what was on, how it was played, what it scored, what it holds, and how to make it again. */
export function Provenance({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const index = useApp((s) => s.index)
  const { meta } = bundle
  const { config, result, checkpoint } = meta
  const others = index?.episodes.filter((e) => e.name !== bundle.name) ?? []
  return (
    <div className="provenance">
      <h3 className="prov-title">{meta.title}</h3>
      <dl className="prov-list">
        <dt>Scenario and seed</dt>
        <dd>
          {prettyId(meta.scenario.replace('.cfg', ''))} (<code>{meta.scenario}</code>), seed {meta.seed}
        </dd>
        <dt>Brain</dt>
        <dd>{BRAIN_WORDS[meta.model]}</dd>
        <dt>Recorded</dt>
        <dd>{utcStamp(meta.recorded_at)}</dd>
        <dt>Versions</dt>
        <dd>
          package {meta.package_version ?? 'unknown'}, bundle schema {meta.schema_version ?? 1}
        </dd>
      </dl>

      <h4>What was on</h4>
      <Brains meta={meta} />

      <h4>How it was played</h4>
      <dl className="prov-list">
        <dt>Execution mode</dt>
        <dd>
          <code>{config.execution_mode}</code>
          {config.execution_mode === 'async_cached' ? ': d1 answers are read from a cache and never awaited' : ''}
        </dd>
        <dt>Tick budget</dt>
        <dd>{fmt(config.tick_budget_sec * 1000, 0)} ms</dd>
        <dt>Arbiter</dt>
        <dd>
          {config.deterministic_arbiter
            ? 'deterministic: always the top score'
            : 'not deterministic: it may sample when the top two are close and pressure is high'}
        </dd>
        <dt>Exploration floor</dt>
        <dd>{config.exploration_floor > 0 ? fmt(config.exploration_floor, 2) : '0: never a random draw'}</dd>
        <dt>Tick cap</dt>
        <dd>
          {config.max_ticks}; the episode ended at tick {meta.last_tick}, after {meta.tick_count} ticks
        </dd>
      </dl>

      <h4>The checkpoint</h4>
      {checkpoint ? (
        <dl className="prov-list" data-testid="checkpoint">
          <dt>File</dt>
          <dd>
            <code>{checkpoint.file}</code>
          </dd>
          <dt>Training episodes</dt>
          <dd>{thousands(checkpoint.episodes)}</dd>
          <dt>Transitions seen</dt>
          <dd>{thousands(checkpoint.transitions_seen)}</dd>
          <dt>Network share</dt>
          <dd>{pct(checkpoint.network_share)}</dd>
          {checkpoint.best_score !== undefined && checkpoint.best_score !== null && (
            <>
              <dt>Best evaluation score</dt>
              <dd>{thousands(Math.round(checkpoint.best_score))}</dd>
            </>
          )}
        </dl>
      ) : (
        <p className="empty-note" data-testid="checkpoint">
          No checkpoint: the heuristics played alone.
        </p>
      )}

      <h4>The result</h4>
      <dl className="prov-list">
        <dt>Outcome</dt>
        <dd>{result.cleared ? 'cleared the level' : result.died ? 'died' : 'survived to the tick cap'}</dd>
        <dt>Ticks</dt>
        <dd>{result.ticks}</dd>
        <dt>Reward</dt>
        <dd>{fmt(result.reward, 2)}</dd>
        <dt>Kills</dt>
        <dd>{fmt(result.kills, 0)}</dd>
        <dt>At the end</dt>
        <dd>
          health {fmt(result.health, 0)}, armor {fmt(result.armor, 0)}
        </dd>
        <dt>Network share</dt>
        <dd>
          {meta.brains.learned_networks
            ? `${pct(result.network_share ?? 0)} of the say on the actions picked, on average`
            : 'none'}
        </dd>
      </dl>

      <h4>The five questions</h4>
      <ul className="prov-modules">
        {MODULES.filter((m) => meta.modules[m]).map((m) => (
          <li key={m} data-module={m}>
            <span className="dot" style={{ background: `var(--${m})` }} />
            <strong style={{ color: `var(--${m})` }}>{m}</strong> {meta.modules[m]}
          </li>
        ))}
      </ul>

      <h4>The files</h4>
      <ul className="prov-files">
        {meta.files.map((f) => (
          <li key={f}>
            <code>{f}</code>
          </li>
        ))}
        <li>
          <code>{meta.frames.dir ?? 'frames'}/</code>: one {meta.frames.width ?? 320} × {meta.frames.height ?? 240} JPEG
          per tick ({meta.tick_count}){meta.frames.end_frame ? ', and the screen after the last action' : ''}
        </li>
      </ul>
      {others.length > 0 && (
        <>
          <h4>The other recordings</h4>
          <ul className="prov-others">
            {others.map((e) => {
              const at = Math.min(tick.tick, e.ticks - 1)
              return (
                <li key={e.name}>
                  <button type="button" className="link-button" onClick={() => void openEpisode(e.name, at)}>
                    {e.title}, at tick {at} →
                  </button>
                  {e.scenario === meta.scenario && e.seed === meta.seed && (
                    <span className="muted"> the same episode, played by the other brain</span>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}

      <h4>How to make it again</h4>
      <p>From the repository root, with the package installed:</p>
      <Command text={exportCommand(meta)} label="the export command" />
      <p>Then rebuild the list of recordings the app offers:</p>
      <Command text={INDEX_COMMAND} label="the index command" />
      <p className="muted">
        The defaults that matter: the trained models are read from the run folder{' '}
        <code>runs/{meta.scenario.replace('.cfg', '')}</code>, the tick budget is 40 ms, the exploration floor is 0 and
        nothing is learned while recording.
      </p>
    </div>
  )
}
