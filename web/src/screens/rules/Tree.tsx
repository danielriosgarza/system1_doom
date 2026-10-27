import { useMemo } from 'react'
import { EvidenceText } from '../../components/Evidence'
import { Panel } from '../../components/Panel'
import { RESULTS, TREE, WRITTEN, writerWords } from '../../content/rules/words'
import {
  type RulesBundle,
  ROOT,
  actionWords,
  proposalOf,
  readBuild,
  routeNodes,
  ruleUses,
  rulesFileUrl,
  skillIds,
} from '../../data/rules'
import type { RuleTreeDecision } from '../../schema/bundle'
import { openRound, setState, useApp } from '../../store'

/** The whole tree as an outline, this decision's walk marked, and where the rule picked came from. */
export function Tree({ bundle, decision }: { bundle: RulesBundle; decision: RuleTreeDecision }) {
  const picked = useApp((s) => s.rule)
  const route = useMemo(() => new Set(routeNodes(decision)), [decision])
  const skills = useMemo(() => skillIds(bundle.tree), [bundle])
  const id = picked && bundle.tree.nodes[picked] ? picked : decision.node
  const marks = { route, ended: decision.node, selected: id }
  return (
    <main className="screen tree-screen" aria-label="The rule tree">
      <header className="screen-head">
        <h2>
          {TREE.title}: {bundle.meta.tree}
        </h2>
        <p>{TREE.intro}</p>
      </header>
      <div className="tree-grid">
        <Panel id="rt-outline" aside={<span className="panel-aside">{bundle.meta.rules} rules</span>}>
          <div className="tree-outline" data-testid="tree-outline">
            <ul className="tree-list">
              <TreeNode bundle={bundle} id={ROOT} marks={marks} />
            </ul>
            {skills.map((s) => (
              <div key={s} className="tree-skill">
                <h3>{TREE.skillTitle(s)}</h3>
                <p className="faint small">{TREE.skillNote(s)}</p>
                <ul className="tree-list">
                  <TreeNode bundle={bundle} id={s} marks={marks} />
                </ul>
              </div>
            ))}
          </div>
          <p className="tree-legend small">
            <span className="tree-key on-route" /> {TREE.onRoute} · <span className="tree-key ended" /> {TREE.ended}
          </p>
        </Panel>
        <div className="tree-detail">
          <Panel id="rt-rule">
            <RuleDetail bundle={bundle} id={id} />
          </Panel>
        </div>
      </div>
    </main>
  )
}

interface Marks {
  route: Set<string>
  ended: string
  selected: string
}

function TreeNode({ bundle, id, marks }: { bundle: RulesBundle; id: string; marks: Marks }) {
  const node = bundle.tree.nodes[id]
  if (!node) return null
  const isRoot = id === ROOT
  const isSkill = node.parent === null && !isRoot
  const classes = [
    'tree-node',
    marks.route.has(id) ? 'on-route' : '',
    marks.ended === id ? 'ended' : '',
    marks.selected === id ? 'selected' : '',
  ].join(' ')
  return (
    <li className={classes} data-node={id}>
      <button
        type="button"
        className="tree-rule"
        aria-pressed={marks.selected === id}
        onClick={() => setState({ rule: id })}
        data-testid="tree-rule"
      >
        <span className="rule-id mono">{id}</span>
        <span className="tree-cond">{isRoot ? TREE.root : isSkill ? TREE.skillTitle(id) : node.condition}</span>
        {node.focus && (
          <span className="tree-focus small">
            {TREE.focus}: “{node.focus.question}” {TREE.focusFrom(node.focus.from)}
          </span>
        )}
        <span className="tree-act small">
          {isRoot ? TREE.rootAction : isSkill ? null : `→ ${actionWords(node.action)}`}
        </span>
      </button>
      {(node.children ?? []).length > 0 && (
        <ul className="tree-list">
          {(node.children ?? []).map((c) => (
            <TreeNode key={c} bundle={bundle} id={c} marks={marks} />
          ))}
        </ul>
      )}
    </li>
  )
}

function RuleDetail({ bundle, id }: { bundle: RulesBundle; id: string }) {
  const entries = useMemo(() => readBuild(bundle.build), [bundle])
  const use = useMemo(() => ruleUses(bundle).find((u) => u.id === id), [bundle, id])
  const node = bundle.tree.nodes[id]
  if (!node) return <p className="muted">{TREE.detailNone}</p>
  const isRoot = id === ROOT
  const isSkill = node.parent === null && !isRoot
  const provenance = node.provenance ?? {}
  const writer = typeof provenance.writer === 'string' ? provenance.writer : null
  const why = typeof provenance.why === 'string' ? provenance.why : null
  const proposal = proposalOf(entries, id)
  const start = entries.find((e) => e.kind === 'start')
  const cornerstone = (node.cornerstones ?? [])[0]
  return (
    <div className="rule-detail" data-testid="rule-detail" data-node={id}>
      <h3>
        <span className="rule-id mono">{id}</span> {isRoot ? TREE.root : isSkill ? TREE.skillTitle(id) : node.condition}
      </h3>
      <dl className="facts-list">
        {!isRoot && !isSkill && (
          <div>
            <dt>{TREE.action}</dt>
            <dd>{actionWords(node.action)}</dd>
          </div>
        )}
        {isRoot && (
          <div>
            <dt>{TREE.action}</dt>
            <dd>{TREE.rootAction}</dd>
          </div>
        )}
        {node.parent && (
          <div>
            <dt>
              {bundle.tree.nodes[node.parent]?.parent === null && node.parent !== ROOT ? TREE.partOf : TREE.parent}
            </dt>
            <dd>
              <button type="button" className="link mono" onClick={() => setState({ rule: node.parent })}>
                {node.parent}
              </button>
            </dd>
          </div>
        )}
        {(node.children ?? []).length > 0 && (
          <div>
            <dt>{TREE.children}</dt>
            <dd>
              {(node.children ?? []).map((c, i) => (
                <span key={c}>
                  {i > 0 && ', '}
                  <button type="button" className="link mono" onClick={() => setState({ rule: c })}>
                    {c}
                  </button>
                </span>
              ))}
            </dd>
          </div>
        )}
        {writer && (
          <div>
            <dt>{TREE.writer}</dt>
            <dd>{writerWords(writer)}</dd>
          </div>
        )}
      </dl>
      {use && <p className="small">{TREE.uses(use.reached, use.ended, bundle.decisions.length)}</p>}
      {!isRoot && !isSkill && !proposal && (
        <p className="small muted">{TREE.start(start?.kind === 'start' ? start.tree : null, writer)}</p>
      )}
      {isRoot && <p className="small muted">{RESULTS.root}</p>}
      {proposal && (
        <>
          {why && (
            <>
              <p className="chips-label">{TREE.why}</p>
              <p className="writer-why">{why}</p>
            </>
          )}
          <p className="chips-label">{TREE.record}</p>
          <p className="small">
            {WRITTEN.proposal(proposal.name)}: {WRITTEN.outcome[proposal.outcome]}
            {proposal.gate?.withRule !== null && proposal.gate?.withRule !== undefined && proposal.gate.of !== null
              ? `; ${WRITTEN.gateBoth(proposal.gate.current ?? 0, proposal.gate.withRule, proposal.gate.of)}`
              : ''}{' '}
            <button type="button" className="link-button" onClick={() => openRound(entries.indexOf(proposal))}>
              {TREE.recordLink}
            </button>
          </p>
        </>
      )}
      {cornerstone && (
        <>
          <p className="chips-label">{TREE.cornerstone}</p>
          <figure className="instance-frame">
            <div className="frame">
              <img src={rulesFileUrl(bundle, cornerstone.frame)} alt={`${TREE.cornerstone}: ${cornerstone.frame}`} />
            </div>
            <figcaption className="faint small">
              {TREE.cornerstoneNote(cornerstone.seed, cornerstone.prefix.length, cornerstone.expect)}
            </figcaption>
          </figure>
          <details className="saw">
            <summary>{TREE.cornerstoneText}</summary>
            <EvidenceText text={cornerstone.state_text} name={`cornerstone-${id}`} testId="cornerstone-text" />
          </details>
        </>
      )}
    </div>
  )
}
