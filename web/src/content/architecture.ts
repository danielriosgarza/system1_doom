// The overview diagram's boxes: what each one is called, which explainer it opens, and which
// inspector panel shows it in detail. The numbered ones are the six beats of every tick.
import type { ExplainerId, PanelId } from './explainers'

export type BoxId =
  | 'freeze'
  | 'menu'
  | 'opinions'
  | 'decision'
  | 'act'
  | 'remember'
  | 'request'
  | 'worker'
  | 'gate'
  | 'join'
  | 'rewards'
  | 'replay'
  | 'networks'
  | 'trust'
  | 'gateShare'
  | 'simulator'
  | 'archive'
  | 'd1'

/** What each box explains, and which inspector panel shows it in detail. */
export const BOXES: Record<BoxId, { title: string; explainer: ExplainerId; panel?: PanelId; beat?: number }> = {
  freeze: { title: 'Freeze the world', explainer: 'world', panel: 'game', beat: 1 },
  menu: { title: 'Shorten the menu', explainer: 'legal', panel: 'legal', beat: 2 },
  opinions: { title: 'Five opinions', explainer: 'modules', panel: 'modules', beat: 3 },
  decision: { title: 'One decision', explainer: 'arbiter', panel: 'arbiter', beat: 4 },
  act: { title: 'Act', explainer: 'motor', panel: 'motor', beat: 5 },
  remember: { title: 'See and remember', explainer: 'outcome', panel: 'outcome', beat: 6 },
  request: { title: 'A module asks', explainer: 'request', panel: 'modules' },
  worker: { title: 'Slow worker writes', explainer: 'worker' },
  gate: { title: 'Admission gate', explainer: 'gate', panel: 'legal' },
  join: { title: 'Joins the menu', explainer: 'legal', panel: 'legal' },
  rewards: { title: 'Five rewards', explainer: 'rewards', panel: 'outcome' },
  replay: { title: 'Replay buffer', explainer: 'replay' },
  networks: { title: 'Learned networks', explainer: 'networks', panel: 'modules' },
  trust: { title: 'trust λ', explainer: 'trust', panel: 'modules' },
  gateShare: { title: 'gate share g', explainer: 'networks', panel: 'arbiter' },
  simulator: { title: 'Bounded simulator', explainer: 'projection', panel: 'projection' },
  archive: { title: 'Strategy archive', explainer: 'steering', panel: 'outcome' },
  d1: { title: 'd1-ultra', explainer: 'd1' },
}
