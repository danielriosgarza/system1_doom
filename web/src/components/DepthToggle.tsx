import { setState, startTour, useApp } from '../store'

/** Plain or Formula: whether explanations show this tick's arithmetic. Shown on the screens that have formulas. */
export function DepthToggle() {
  const depth = useApp((s) => s.depth)
  return (
    <span className="control depth-toggle" title="Explanation depth: Formula adds this tick’s arithmetic (f)">
      <span className="control-label">Depth</span>
      <span className="segmented" role="group" aria-label="Explanation depth">
        <button type="button" aria-pressed={depth === 'plain'} onClick={() => setState({ depth: 'plain' })}>
          Plain
        </button>
        <button type="button" aria-pressed={depth === 'formula'} onClick={() => setState({ depth: 'formula' })}>
          Formula
        </button>
      </span>
    </span>
  )
}

/** The guided tour's button: seven steps through one real decision, ending on the chain. */
export function TourButton() {
  const tourSeen = useApp((s) => s.tourSeen)
  const running = useApp((s) => s.tour !== null)
  const ready = useApp((s) => s.bundle !== null)
  return (
    <button
      type="button"
      className="icon-button tour-button"
      onClick={startTour}
      disabled={!ready || running}
      title="Seven steps through one real decision: six beats in the inspector, then the chain (t)"
    >
      {tourSeen ? 'Take the tour again' : 'Take the tour'}
    </button>
  )
}

/** The tools at the right of a screen's header. */
export function HeadTools({ tour = false }: { tour?: boolean }) {
  return (
    <div className="head-tools">
      {tour && <TourButton />}
      <DepthToggle />
    </div>
  )
}
