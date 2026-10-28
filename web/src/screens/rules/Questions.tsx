import { type KeyboardEvent, useId } from 'react'
import { EvidenceText } from '../../components/Evidence'
import { Panel } from '../../components/Panel'
import { pct } from '../../data/readings'
import {
  type RulesBundle,
  NONE,
  actionWords,
  optionBars,
  questionIndexes,
  readStep,
  rulesFileUrl,
  skillIds,
  textSent,
} from '../../data/rules'
import type { RuleTreeDecision, WalkStep } from '../../schema/bundle'
import { setState, useApp } from '../../store'
import { useTreeWords } from './useTreeWords'

/** One decision opened: every question asked (of Jev, or Laya), the text it was sent exactly as sent, and its answers. */
export function Questions({
  bundle,
  decision,
  index,
}: {
  bundle: RulesBundle
  decision: RuleTreeDecision
  index: number
}) {
  const { watch: W, questions: Q } = useTreeWords()
  const selected = useApp((s) => s.question)
  const tabsId = useId()
  const asked = questionIndexes(decision)
  const at = asked.includes(selected) ? selected : (asked[0] ?? 0)
  const step = decision.steps[at]
  const text = textSent(decision, at) ?? ''
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const k = asked.indexOf(at)
    const next = e.key === 'ArrowRight' ? k + 1 : e.key === 'ArrowLeft' ? k - 1 : null
    if (next === null) return
    e.preventDefault()
    const target = asked[(next + asked.length) % asked.length]
    if (target === undefined) return
    setState({ question: target })
    window.requestAnimationFrame(() => document.getElementById(`${tabsId}-${target}`)?.focus())
  }
  return (
    <main className="screen questions" aria-label="The questions">
      <header className="screen-head">
        <h2>{Q.title(index + 1)}</h2>
        <p>{Q.intro}</p>
      </header>
      <div className="instance-tabs" role="tablist" aria-label={Q.tabs}>
        {asked.map((i, k) => {
          const s = decision.steps[i] as WalkStep
          const r = readStep(s)
          const state = r.miss ? 'missed' : r.asked ? 'spoke' : 'silent'
          return (
            <button
              key={i}
              id={`${tabsId}-${i}`}
              type="button"
              role="tab"
              aria-selected={i === at}
              aria-controls={`${tabsId}-panel`}
              tabIndex={i === at ? 0 : -1}
              data-step={i}
              data-state={state}
              onClick={() => setState({ question: i })}
              onKeyDown={onKey}
            >
              {Q.tab(k + 1)}
              <span className="tab-state">
                {s.kind === 'focus' ? Q.focusTab : `at ${s.node}`}
                {r.miss ? ` · ${W.missed}` : r.option && s.kind === 'rule' ? ` → ${r.option}` : ''}
              </span>
            </button>
          )
        })}
      </div>
      {step && (
        <div
          className="instance-grid"
          role="tabpanel"
          id={`${tabsId}-panel`}
          aria-labelledby={`${tabsId}-${at}`}
          data-testid="question-panel"
          data-step={at}
        >
          <Panel id="rt-sent">
            <figure className="instance-frame">
              <div className="frame">
                <img src={rulesFileUrl(bundle, decision.frame)} alt={`${Q.frame}: ${decision.frame}`} />
              </div>
              <figcaption className="faint small">{Q.frame}</figcaption>
            </figure>
            <p className="chips-label">{Q.text}</p>
            <EvidenceText text={text} name={`step-${at}`} testId="state-text" highlight="focus" />
            <p className="faint small">
              {text.includes('\n[focus]\n') ? Q.focusNote : step.kind === 'focus' ? Q.noFocusNote : ''}
            </p>
          </Panel>
          <Panel id="rt-answer">
            <Answer bundle={bundle} step={step} />
          </Panel>
        </div>
      )}
    </main>
  )
}

/** One question: its words, every option with the answering model's probability, and where the answer led. */
function Answer({ bundle, step }: { bundle: RulesBundle; step: WalkStep }) {
  const { questions: Q } = useTreeWords()
  const r = readStep(step)
  const bars = optionBars(step)
  const skills = skillIds(bundle.tree)
  const where =
    step.kind === 'focus'
      ? `the focus question of ${step.node}`
      : skills.includes(step.node)
        ? `the ${step.node} skill`
        : step.node
  return (
    <div className="answers" data-testid="question-answers">
      <div className="answer-block">
        <h3>
          {Q.question} <span className="answer-value">asked at {where}</span>
        </h3>
        <p className="question-text" data-testid="question-text">
          {step.question}
        </p>
      </div>
      {r.miss && (
        <div className="miss-box" data-testid="miss-box">
          <p>
            <strong>{Q.miss}:</strong> {r.miss}
            {step.answer?.error ? ` (${step.answer.error})` : ''}. {Q.missNote}
          </p>
        </div>
      )}
      <div className="answer-block">
        <h3>{Q.options}</h3>
        {!r.asked && <p className="small">{bars.length === 0 ? Q.noneListed : Q.onlyOne}</p>}
        <ul className="bar-list option-bars" aria-label={Q.options}>
          {bars.map((b) => (
            <li key={b.option} className={`bar-row ${b.picked ? 'top' : ''}`} data-option={b.option}>
              <span className="bar-label">
                {step.kind === 'rule' && b.option !== NONE && <span className="rule-id mono">{b.option}</span>} {b.text}
              </span>
              <span className="bar-track">
                <span className="bar-fill" style={{ width: `${Math.max(0, Math.min(1, b.p)) * 100}%` }} />
              </span>
              <span className="bar-value">{r.asked ? pct(b.p, b.p < 0.1 && b.p > 0 ? 1 : 0) : '–'}</span>
              <span className="bar-note">{b.picked ? Q.picked : ''}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="answer-block">
        <h3>{Q.leadsTo}</h3>
        <p className="small" data-testid="leads-to">
          {leadsTo(bundle, step)}
        </p>
      </div>
      {r.cached && <p className="faint small">{Q.cached}</p>}
      {step.answer && !r.cached && (
        <p className="faint small">{Q.timing(step.answer.latency_ms ?? 0, step.answer.cost ?? 0)}</p>
      )}
    </div>
  )
}

/** Where the walk went after this question, in words. */
function leadsTo(bundle: RulesBundle, step: WalkStep): string {
  const r = readStep(step)
  if (r.miss) return 'Nowhere: the call missed, so the walk stopped here.'
  if (step.kind === 'focus') {
    return step.focus_line
      ? `The focus is now: ${step.focus_line}. The questions after this one read it in their [focus] channel.`
      : 'There is no focus.'
  }
  const node = bundle.tree.nodes[step.node]
  if (r.option === NONE || !r.option) {
    return node
      ? `None was true, so the walk stays at ${step.node}, whose action is ${actionWords(node.action)}.`
      : 'None was true.'
  }
  const child = bundle.tree.nodes[r.option]
  if (!child) return `Into ${r.option}.`
  const below = child.focus
    ? ' Its focus question is asked next.'
    : (child.children ?? []).length > 0
      ? ' Its own rules are asked next.'
      : typeof child.action !== 'string'
        ? ` The walk goes on in the ${child.action.skill} skill.`
        : ''
  return `Into ${r.option}, whose action is ${actionWords(child.action)}.${below}`
}
