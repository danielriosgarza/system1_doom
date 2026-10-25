import { useEffect, useState } from 'react'

/**
 * Frames fetched and decoded in this visit, by URL. The images are kept, so a decoded picture stays in memory and
 * showing it again later costs no request.
 */
const decoded = new Map<string, { image: HTMLImageElement; ready: Promise<void> }>()

/** Fetch and decode one frame, once per visit. A frame that fails to load resolves too: it is simply not there. */
export function decodeFrame(url: string): Promise<void> {
  let entry = decoded.get(url)
  if (!entry) {
    const image = new Image()
    image.decoding = 'async'
    image.src = url
    entry = { image, ready: image.decode().catch(() => undefined) }
    decoded.set(url, entry)
  }
  return entry.ready
}

/** Frames decoded side by side; the rest wait their turn, so the first ones arrive first. */
const PARALLEL = 6

/**
 * Decode a recording's frames in order, a few at a time, and report how many of the first ones are ready. In live
 * mode the list grows with every decision, and only the new frames are fetched.
 */
export function usePreloadedFrames(urls: string[]): number {
  const key = urls.join('\n')
  const [ready, setReady] = useState({ key: '', count: 0 })
  useEffect(() => {
    const list = key ? key.split('\n') : []
    const done = list.map(() => false)
    let alive = true
    let next = 0
    const report = () => {
      let count = 0
      while (count < done.length && done[count]) count += 1
      if (alive) setReady({ key, count })
    }
    const worker = async () => {
      while (alive && next < list.length) {
        const i = next
        next += 1
        await decodeFrame(list[i] as string)
        done[i] = true
        report()
      }
    }
    for (let k = 0; k < PARALLEL; k += 1) void worker()
    return () => {
      alive = false
    }
  }, [key])
  // A count kept from another recording means nothing for this one.
  return ready.key === key ? ready.count : 0
}
