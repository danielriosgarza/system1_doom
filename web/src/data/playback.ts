// Playback: how fast a recording plays, and how the landing's own playback starts, ends and starts again.

/** Doom runs at 35 game frames a second. */
export const DOOM_FPS = 35

/** One decision lasts 8 game frames (the `decision_frames` bound): Act holds the action's primitives that long. */
export const DECISION_FRAMES = 8

/** Seconds of game time before decision `tick` was made. */
export function gameSeconds(tick: number): number {
  return (tick * DECISION_FRAMES) / DOOM_FPS
}

/** Real time is the agent's own pace; slow is one decision a second, to read the instances as they change. */
export type Pace = 'real' | 'slow'

/** One decision covers 8 frames at 35 frames per second, about 0.229 s. */
export const DECISION_MS = (1000 * DECISION_FRAMES) / DOOM_FPS

/** Milliseconds between two decisions on screen at each pace. */
export const PACE_MS: Record<Pace, number> = { real: DECISION_MS, slow: 1000 }

/** At the end of a recording, the landing holds the end frame and the result this long before it starts again. */
export const END_HOLD_MS = 2500

/** The landing starts playing once this many of the recording's first frames are decoded. */
export const READY_FRAMES = 8

/** Playback that waits for frames still starts after this long, so a slow or failing image never holds it. */
export const READY_TIMEOUT_MS = 3000
