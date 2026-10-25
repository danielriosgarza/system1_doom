// Playback: how fast a recording plays, and how the landing's own playback starts, ends and starts again.
import { DOOM_FPS, FRAMES_PER_STEP, STEPS_PER_DECISION } from './derive'

/** Real time is the agent's own pace; slow is one decision a second, to read the chain as it changes. */
export type Pace = 'real' | 'slow'

/** One decision covers 4 motor steps of 2 game frames each: 8 frames at 35 frames per second, about 0.229 s. */
export const DECISION_MS = (1000 * STEPS_PER_DECISION * FRAMES_PER_STEP) / DOOM_FPS

/** Milliseconds between two decisions on screen at each pace. */
export const PACE_MS: Record<Pace, number> = { real: DECISION_MS, slow: 1000 }

/** At the end of a recording, the landing holds the end frame and the result this long before it starts again. */
export const END_HOLD_MS = 2500

/** The landing starts playing once this many of the recording's first frames are decoded. */
export const READY_FRAMES = 8

/** Playback that waits for frames still starts after this long, so a slow or failing image never holds it. */
export const READY_TIMEOUT_MS = 3000
