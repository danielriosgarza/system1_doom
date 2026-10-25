import { useEffect, useState } from 'react'
import { Drawing } from '../components/Drawing'
import { Panel } from '../components/Panel'
import { linkTerms } from '../components/Terms'
import { GLOSSARY, REMOVED_TERMS } from '../content/glossary'
import { REFERENCE } from '../content/reference'
import { resultWords } from '../content/watch'
import type { EpisodeBundle } from '../data/loader'
import { openPanel, setState, useApp } from '../store'

export function Reference({ bundle }: { bundle: EpisodeBundle }) {
  return (
    <main className="screen reference" aria-label="Reference">
      <header className="screen-head">
        <h2>{REFERENCE.title}</h2>
      </header>
      <Panel id="principles">
        <p className="one-rule" data-testid="one-rule">
          {REFERENCE.rule}
        </p>
        <p>{REFERENCE.ruleNote}</p>
        <ul className="principles">
          {REFERENCE.principles.map((p) => {
            const seen = new Set<string>()
            return (
              <li key={p.title}>
                <strong>{p.title}.</strong> {linkTerms(p.text, seen)}
              </li>
            )
          })}
        </ul>
        <p className="small muted" data-testid="removed-terms">
          {REFERENCE.history(REMOVED_TERMS)}
        </p>
      </Panel>
      <Panel id="drawing">
        <Drawing />
      </Panel>
      <Panel id="glossary">
        <Glossary />
      </Panel>
      <div className="reference-grid">
        <Panel id="provenance">
          <Provenance bundle={bundle} />
        </Panel>
        <Panel id="keys">
          <dl className="keys">
            {REFERENCE.keys.map(([k, v]) => (
              <div key={k}>
                <dt>
                  <kbd>{k}</kbd>
                </dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      </div>
    </main>
  )
}

function Glossary() {
  const term = useApp((s) => s.term)
  const [filter, setFilter] = useState('')
  const q = filter.trim().toLowerCase()
  const entries = GLOSSARY.filter(
    (e) =>
      e.id === term ||
      !q ||
      e.term.toLowerCase().includes(q) ||
      e.aliases.some((a) => a.toLowerCase().includes(q)) ||
      e.meaning.toLowerCase().includes(q),
  )
  useEffect(() => {
    if (!term) return
    const frame = window.requestAnimationFrame(() =>
      document.getElementById(`term-${term}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }),
    )
    return () => window.cancelAnimationFrame(frame)
  }, [term])
  return (
    <div className="glossary">
      <label className="glossary-filter">
        <span className="chips-label">{REFERENCE.glossaryFilter}</span>
        <input
          type="search"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value)
            setState({ term: null })
          }}
        />
      </label>
      {entries.length === 0 && <p className="muted small">{REFERENCE.glossaryEmpty}</p>}
      <dl className="glossary-list">
        {entries.map((e) => (
          <div
            key={e.id}
            id={`term-${e.id}`}
            className={`glossary-entry ${term === e.id ? 'marked' : ''}`}
            data-testid="glossary-entry"
            data-term={e.id}
          >
            <dt>
              {e.term}
              {e.aliases.length > 0 && (
                <span className="small muted">
                  {' '}
                  · {REFERENCE.aliases} {e.aliases.join(', ')}
                </span>
              )}
            </dt>
            <dd>
              <p>{e.meaning}</p>
              <p className="small">
                {REFERENCE.see}:{' '}
                {e.see.map((s, i) => (
                  <span key={s.label}>
                    {i > 0 && ' · '}
                    <button
                      type="button"
                      className="link"
                      onClick={() => {
                        setState({ term: null })
                        if (s.panel) openPanel(s.screen, s.panel)
                        else openPanel(s.screen, '')
                      }}
                    >
                      {s.label}
                    </button>
                  </span>
                ))}{' '}
                · {REFERENCE.code}: <code>{e.code}</code>
              </p>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function Provenance({ bundle }: { bundle: EpisodeBundle }) {
  const m = bundle.meta
  const P = REFERENCE.provenance
  const start = m.configuration_start.version ?? 1
  const end = m.configuration_end.version ?? start
  const rows: Array<[string, string]> = [
    [P.scenario, m.scenario],
    [P.seed, String(m.seed)],
    [
      P.networks,
      m.value_networks === 'none'
        ? 'none'
        : `${m.value_networks}${m.checkpoint ? ` (${m.checkpoint.file}, ${m.checkpoint.episodes} training episodes)` : ''}`,
    ],
    [P.configuration, start === end ? `version ${start}` : `version ${start} → ${end}`],
    [P.slowPath, m.slow_path],
    [P.budget, `${m.config.call_budget_sec} s per call, at most ${m.config.max_ticks} decisions`],
    [P.calls, `${m.cost.calls ?? 0}, $${(m.cost.usd ?? 0).toFixed(4)}`],
    [P.misses, `${m.misses.total ?? 0} (${m.misses.missed_ticks ?? 0} decisions with no keys)`],
    [P.result, resultWords({ ...m.result, scenario: m.scenario })],
    [
      P.recorded,
      `${m.recorded_at.slice(0, 16).replace('T', ' ')} UTC${m.package_version ? `, package ${m.package_version}` : ''}`,
    ],
  ]
  const command = `python -m system1_doom.export --scenario ${m.scenario} --seed ${m.seed} --networks ${m.value_networks} --out web/public/episodes/${bundle.name} --name ${bundle.name}`
  return (
    <div className="provenance" data-testid="provenance">
      <p>
        <strong>{m.title}</strong>
      </p>
      <dl className="facts-list">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <p className="chips-label">{P.command}</p>
      <pre className="command">{command}</pre>
      {start > 1 && <p className="small muted">{P.fromVersion(start)}</p>}
      <p className="chips-label">{P.serve}</p>
      <pre className="command">python -m system1_doom.serve --scenario {m.scenario}</pre>
    </div>
  )
}
