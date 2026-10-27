import { useMemo } from 'react'
import { type Bands, Timeline } from '../../components/Scrubber'
import { TIMELINE, TOP_RULE_WORDS } from '../../content/rules/words'
import { gameSeconds } from '../../data/playback'
import { type RulesBundle, type RulesMarkKind, NONE, ROOT, decisionMarks, topRule } from '../../data/rules'
import type { RuleTreeDecision } from '../../schema/bundle'
import type { Screen } from '../../store'
import { HowWritten } from './HowWritten'
import { Models } from './Models'
import { Questions } from './Questions'
import { RulesReference } from './Reference'
import { Results } from './Results'
import { Tree } from './Tree'
import { RulesWatch } from './Watch'

/** The rule tree's seven screens, and the timeline under every one but Watch. */
export function RulesScreens({
  bundle,
  decision,
  index,
  screen,
}: {
  bundle: RulesBundle
  decision: RuleTreeDecision
  index: number
  screen: Screen
}) {
  return (
    <>
      {screen === 'watch' && <RulesWatch bundle={bundle} decision={decision} index={index} />}
      {screen === 'questions' && <Questions bundle={bundle} decision={decision} index={index} />}
      {screen === 'written' && <HowWritten bundle={bundle} />}
      {screen === 'results' && <Results bundle={bundle} />}
      {screen === 'tree' && <Tree bundle={bundle} decision={decision} />}
      {screen === 'reference' && <RulesReference bundle={bundle} />}
      {screen === 'models' && <Models bundle={bundle} decision={decision} />}
      {screen !== 'watch' && <RulesScrubber bundle={bundle} />}
    </>
  )
}

const LANE: Record<RulesMarkKind, 'top' | 'bottom'> = { damage: 'top', kill: 'top', death: 'top', miss: 'bottom' }

/** The band key of a top rule: its place among the root's rules, so the colours do not depend on rule ids. */
function bandKey(root: string[], top: string): string {
  const at = root.indexOf(top)
  return at >= 0 ? `top${at}` : top === 'missed' ? 'missed' : NONE
}

/** The timeline of a rule-tree recording: the health line, the top rule of each walk, and what happened. */
export function RulesScrubber({ bundle }: { bundle: RulesBundle }) {
  const { decisions, tree } = bundle
  const marks = useMemo(() => decisionMarks(decisions), [decisions])
  const health = useMemo(() => decisions.map((d) => d.health_before), [decisions])
  const bands = useMemo((): Bands => {
    const root = tree.nodes[ROOT]?.children ?? []
    const tops = decisions.map(topRule)
    return {
      keys: tops.map((t) => bandKey(root, t)),
      legend: [
        ...root.map((id, k) => {
          const condition = tree.nodes[id]?.condition ?? ''
          return { key: `top${k}`, label: `${id}: ${TOP_RULE_WORDS[condition] ?? 'its condition'}`, title: condition }
        }),
        ...(tops.includes(NONE) ? [{ key: NONE, label: TIMELINE.none }] : []),
        ...(tops.includes('missed') ? [{ key: 'missed', label: TIMELINE.missed }] : []),
      ],
    }
  }, [decisions, tree])
  return (
    <Timeline
      health={health}
      marks={marks}
      lane={LANE}
      legend={[...TIMELINE.legend]}
      explainer="rt-scrubber"
      tick={(i) => decisions[i]?.decision ?? i}
      seconds={(i) => gameSeconds(decisions[i]?.decision ?? i)}
      words={(i) => decisions[i]?.action_words ?? ''}
      bands={bands}
    />
  )
}
