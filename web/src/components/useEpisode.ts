import { useEffect, useState } from 'react'
import { type EpisodeBundle, loadEpisode } from '../data/loader'

/** Bundles fetched for comparison, kept for the session so switching back is instant. */
const fetched = new Map<string, Promise<EpisodeBundle>>()
const ready = new Map<string, EpisodeBundle>()

function fetchEpisode(name: string): Promise<EpisodeBundle> {
  let pending = fetched.get(name)
  if (!pending) {
    pending = loadEpisode(name).then((b) => {
      ready.set(name, b)
      return b
    })
    fetched.set(name, pending)
  }
  return pending
}

/** Another recording, loaded on first use; null until it arrives, or when no name is given. */
export function useEpisode(name: string | null): EpisodeBundle | null {
  const [, setLoaded] = useState(0)
  useEffect(() => {
    if (!name || ready.has(name)) return
    let alive = true
    void fetchEpisode(name).then(() => alive && setLoaded((n) => n + 1))
    return () => {
      alive = false
    }
  }, [name])
  return name ? (ready.get(name) ?? null) : null
}
