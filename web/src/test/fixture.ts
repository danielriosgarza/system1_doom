// The fixture every unit test reads: one short corridor episode played by the fake d1-ultra
// (web/scripts/record_fixture.py), the same files the browser tests serve.
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { type EpisodeBundle, type Fetcher, loadEpisode } from '../data/loader'

/** The folder that holds `episodes/`, with a trailing slash. */
export const FIXTURES = fileURLToPath(new URL('../../e2e/fixtures/', import.meta.url))

/** The fixture recording's name. */
export const FIXTURE = 'fixture-corridor'

/** Serves files under the fixture folder the way the server serves public/; an override of null is a 404. */
export function diskFetcher(overrides: Record<string, string | null> = {}): Fetcher {
  return async (url) => {
    if (url in overrides) {
      const body = overrides[url]
      return body === null || body === undefined ? new Response('missing', { status: 404 }) : new Response(body)
    }
    try {
      return new Response(await readFile(FIXTURES + url, 'utf8'))
    } catch {
      return new Response('missing', { status: 404 })
    }
  }
}

/** The fixture recording, loaded as the app loads it. */
export function loadFixture(): Promise<EpisodeBundle> {
  return loadEpisode(FIXTURE, 'episodes', diskFetcher())
}
