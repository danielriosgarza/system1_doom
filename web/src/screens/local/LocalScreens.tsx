import type { RulesBundle } from '../../data/rules'
import type { RuleTreeDecision } from '../../schema/bundle'
import type { Screen } from '../../store'
import { Questions } from '../rules/Questions'
import { RulesScrubber } from '../rules/RulesScreens'
import { Tree } from '../rules/Tree'
import { RulesWatch } from '../rules/Watch'
import { LocalReference } from './Reference'
import { LocalResults } from './Results'
import { Trained } from './Trained'

/**
 * The local models' six screens: the rule tree's Watch, The questions and The rule tree, which speak for whoever
 * played; How Laya was trained, Results and Reference of their own; and the timeline under every one but Watch.
 */
export function LocalScreens({
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
      {screen === 'trained' && <Trained />}
      {screen === 'results' && <LocalResults bundle={bundle} decision={decision} />}
      {screen === 'tree' && <Tree bundle={bundle} decision={decision} />}
      {screen === 'reference' && <LocalReference bundle={bundle} />}
      {screen !== 'watch' && <RulesScrubber bundle={bundle} />}
    </>
  )
}
