import { useEffect, useMemo, useRef } from 'react'
import { Meter } from '../../components/Bars'
import { Progress, Transport } from '../../components/Playback'
import { FrameStage } from '../../components/Stage'
import { RULES_WATCH, actSource, rulesEndLine, rulesRecordingName, rulesResultWords } from '../../content/rules/words'
import { WATCH } from '../../content/watch'
import { gameSeconds } from '../../data/playback'
import { pct } from '../../data/readings'
import {
  type RulesBundle,
  DEFAULT_TREE,
  NONE,
  readStep,
  rulesEndFrameUrl,
  rulesFileUrl,
  skillIds,
  skillOf,
} from '../../data/rules'
import type { RuleTreeDecision, WalkStep } from '../../schema/bundle'
import { openPanel, openQuestion, openRecording, openRule, useApp } from '../../store'

/** The rule tree's landing: the recording plays at the agent's own pace, beside the questions Jev answered. */
export function RulesWatch({
  bundle,
  decision,
  index,
}: {
  bundle: RulesBundle
  decision: RuleTreeDecision
  index: number
}) {
  const top = useRef<HTMLElement | null>(null)
  // A recording opened from a card lower down plays at the top of the page.
  const name = bundle.name
  useEffect(() => {
    const el = top.current
    if (el && el.getBoundingClientRect().top < 0) window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [name])
  const end = rulesEndFrameUrl(bundle)
  const frames = useMemo(
    () => [...bundle.decisions.map((d) => rulesFileUrl(bundle, d.frame)), ...(end ? [end] : [])],
    [bundle, end],
  )
  const count = bundle.decisions.length
  return (
    <main className="watch" aria-label="Watch the game" ref={top}>
      <header className="watch-head">
        <h2>{RULES_WATCH.title}</h2>
        <p>{RULES_WATCH.subtitle}</p>
      </header>
      <div className="watch-grid">
        <section className="watch-left" aria-label="The game">
          <FrameStage
            name={bundle.name}
            frames={frames}
            src={rulesFileUrl(bundle, decision.frame)}
            end={end}
            endText={rulesEndLine(bundle.meta)}
            alt={RULES_WATCH.frameAlt(index, count, decision.health_before, decision.action_words)}
            width={bundle.meta.frames.width ?? 320}
            height={bundle.meta.frames.height ?? 240}
          />
          <Progress health={bundle.decisions.map((d) => d.health_before)} index={index} />
          <Transport
            count={count}
            index={index}
            seconds={gameSeconds(decision.decision)}
            live={false}
            tick={decision.decision}
          />
          <p className="watch-honesty">
            {RULES_WATCH.honesty(bundle.meta)}{' '}
            <button type="button" className="link-button" onClick={() => openPanel('reference', 'rt-provenance')}>
              {RULES_WATCH.honestyLink}
            </button>
          </p>
        </section>
        <div className="watch-right">
          <WalkStrip bundle={bundle} decision={decision} />
        </div>
      </div>
      <RulesRecordingCards />
    </main>
  )
}

/** The question a rule step asked, with where in the tree it was asked. */
function ruleQuestion(step: WalkStep, skills: string[]): string {
  if (skills.includes(step.node)) return `In the ${step.node} skill: which of these is true right now?`
  return RULES_WATCH.ruleQuestion(step.node)
}

/** Each step's number among the questions of the walk, counting from 1; 0 for a skill step. */
function questionNumbers(steps: WalkStep[]): number[] {
  const out: number[] = []
  let n = 0
  for (const step of steps) out.push(step.kind === 'skill' ? 0 : ++n)
  return out
}

/** Watch's strip: one row per question of the walk, then the action played. */
export function WalkStrip({ bundle, decision }: { bundle: RulesBundle; decision: RuleTreeDecision }) {
  const skills = useMemo(() => skillIds(bundle.tree), [bundle])
  const numbers = questionNumbers(decision.steps)
  return (
    <section className="strip walk-strip" data-testid="walk-strip" aria-labelledby="walk-title">
      <header className="strip-head">
        <h3 id="walk-title">{RULES_WATCH.stripTitle}</h3>
        <p>{RULES_WATCH.stripNote}</p>
      </header>
      <ol className="strip-rows walk-rows">
        {decision.steps.map((step, i) => {
          if (step.kind === 'skill') {
            return (
              <li key={i} className="walk-skill" data-testid="walk-skill">
                <span className="walk-num" aria-hidden>
                  ↳
                </span>
                <span>{RULES_WATCH.skill(step.skill ?? '', step.node)}</span>
              </li>
            )
          }
          const asked = numbers[i] ?? 0
          const r = readStep(step)
          const state = r.miss ? 'missed' : r.asked ? 'answered' : 'only'
          return (
            <li key={i}>
              <button
                type="button"
                className={`walk-row ${state}`}
                data-testid="walk-row"
                data-kind={step.kind}
                data-node={step.node}
                data-pick={r.option ?? ''}
                title={RULES_WATCH.rowTitle}
                onClick={() => openQuestion(i)}
              >
                <span className="walk-num">{asked}</span>
                <span className="walk-q">
                  {step.kind === 'focus' && <span className="walk-tag">focus</span>}
                  {step.kind === 'rule' ? ruleQuestion(step, skills) : step.question}
                </span>
                <span className="walk-a">
                  {r.miss ? (
                    <span className="walk-missed">{RULES_WATCH.missed}</span>
                  ) : (
                    <>
                      {step.kind === 'rule' && r.option && r.option !== NONE && (
                        <span className="rule-id mono">{r.option}</span>
                      )}{' '}
                      {r.text ?? RULES_WATCH.noItem}
                      {state === 'only' && <span className="walk-only">{RULES_WATCH.only}</span>}
                    </>
                  )}
                </span>
                <Meter
                  value={r.asked ? r.p : null}
                  label={`Jev’s probability for question ${asked}`}
                  className="walk-meter"
                />
                <span className="walk-p">{r.miss || !r.asked ? '' : pct(r.p)}</span>
              </button>
            </li>
          )
        })}
        <li className="walk-act" data-testid="walk-act" data-node={decision.node}>
          <span className="dot act" aria-hidden />
          <span className="strip-name">{RULES_WATCH.act}</span>
          <span className="walk-act-body">
            <strong data-testid="walk-action">{decision.action_words}</strong>
            <span className="faint"> · {RULES_WATCH.actGloss}</span>
            <br />
            <button type="button" className="link-button walk-source" onClick={() => openRule(decision.node)}>
              {actSource(decision.node, skillOf(decision), decision.missed)}
            </button>
          </span>
        </li>
      </ol>
      <p className="config-line walk-cost" data-testid="walk-cost">
        {RULES_WATCH.calls(decision.calls, decision.latency_ms, decision.cost)}
      </p>
    </section>
  )
}

/** The rule tree's recordings, the featured one first; a card plays its recording from the start. */
function RulesRecordingCards() {
  const entries = useApp((s) => s.index?.rules ?? [])
  const open = useApp((s) => s.rules?.name)
  if (entries.length === 0) return null
  // In seed order, the default tree's first.
  const ordered = [...entries].sort(
    (a, b) =>
      a.seed - b.seed ||
      Number(b.tree === DEFAULT_TREE) - Number(a.tree === DEFAULT_TREE) ||
      a.name.localeCompare(b.name),
  )
  return (
    <section className="recordings" aria-labelledby="rules-recordings-title">
      <header className="recordings-head">
        <h3 id="rules-recordings-title">{RULES_WATCH.cardsTitle}</h3>
        <p>{RULES_WATCH.cardsNote}</p>
      </header>
      <ul className="recording-cards">
        {ordered.map((entry) => {
          const isOpen = open === entry.name
          return (
            <li
              key={entry.name}
              className={`recording-card ${isOpen ? 'open' : ''}`}
              data-recording={entry.name}
              aria-current={isOpen ? 'true' : undefined}
            >
              <button type="button" className="recording-main" onClick={() => void openRecording(entry.name)}>
                {isOpen && <span className="recording-now">{WATCH.nowShowing}</span>}
                <span className="recording-name">{rulesRecordingName(entry)}</span>
                <span className="recording-gloss">decided by Jev</span>
                <span className="recording-result">{rulesResultWords(entry)}</span>
              </button>
              {isOpen && (
                <button
                  type="button"
                  className="link-button recording-made"
                  onClick={() => openPanel('reference', 'rt-provenance')}
                >
                  {WATCH.made}
                </button>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
