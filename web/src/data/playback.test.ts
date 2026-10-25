import { describe, expect, it } from 'vitest'
import { DOOM_FPS, gameSeconds } from './derive'
import { DECISION_MS, END_HOLD_MS, PACE_MS, READY_FRAMES } from './playback'

describe('the pace of playback', () => {
  it('plays in real time at one decision per 8 game frames, about 0.229 s', () => {
    expect(DECISION_MS).toBeCloseTo((8 / DOOM_FPS) * 1000, 6)
    expect(PACE_MS.real).toBeCloseTo(228.571, 3)
    // The same span the timeline and the counters use for game time.
    expect(PACE_MS.real).toBeCloseTo(gameSeconds(1) * 1000, 6)
  })

  it('plays slow at one decision a second, and four decisions a second in real time', () => {
    expect(PACE_MS.slow).toBe(1000)
    expect(Math.floor(1000 / PACE_MS.real)).toBe(4)
  })

  it('holds the end for 2.5 s and starts once the first eight frames are ready', () => {
    expect(END_HOLD_MS).toBe(2500)
    expect(READY_FRAMES).toBe(8)
  })
})
