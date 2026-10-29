import type { RulesBundle } from '../../data/rules'
import type { RuleTreeDecision } from '../../schema/bundle'
import type { Screen } from '../../store'
import { Questions } from '../rules/Questions'
import { RulesScrubber } from '../rules/RulesScreens'
import { Tree } from '../rules/Tree'
import { RulesWatch } from '../rules/Watch'
import { RealtimeReference } from './Reference'
import { RealtimeResults } from './Results'
import { Timing } from './Timing'

/**
 * Real time's six screens: the rule tree's Watch, The questions and The rule tree, which speak for whoever played (and
 * Watch's strip adds the timing and the helper); How it plays in real time, Results and Reference of its own; and the
 * timeline under every one but Watch.
 */
export function RealtimeScreens({
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
      {screen === 'timing' && <Timing bundle={bundle} decision={decision} index={index} />}
      {screen === 'results' && <RealtimeResults bundle={bundle} />}
      {screen === 'tree' && <Tree bundle={bundle} decision={decision} />}
      {screen === 'reference' && <RealtimeReference bundle={bundle} />}
      {screen !== 'watch' && <RulesScrubber bundle={bundle} />}
    </>
  )
}
