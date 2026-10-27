import type {
  BundleIndexEntry,
  EpisodeMeta,
  ProposalTrace,
  ReflectionTrace,
  RelevanceLedger,
  System2Note,
  TickTrace,
  TrialVerdictTrace,
  TrustFile,
} from '../schema/bundle'

/** The bundle schema version this app reads; `python -m system1_doom.export` writes it into every episode.json. */
export const SUPPORTED_SCHEMA_VERSION = 2

export interface EpisodeIndex {
  schema_version: number
  episodes: BundleIndexEntry[]
}

/** One line of `reflections.jsonl`: a System 2 cycle, a trial's verdict, or a note. */
export type System2Record = ReflectionTrace | TrialVerdictTrace | System2Note

/** One recorded episode, as the export command wrote it. */
export interface EpisodeBundle {
  name: string
  /** URL of the bundle folder, without a trailing slash. */
  base: string
  meta: EpisodeMeta
  ticks: TickTrace[]
  /** Macro proposals and their admission, the admit instance's answer included. */
  proposals: ProposalTrace[]
  /** What System 2 did while the episode was played, in the order it happened. */
  records: System2Record[]
  /** Which moment `relevance` is from: a live episode read while playing holds the ledger as it started. */
  ledgerAt: 'start' | 'end'
  /** The relevance ledger after the episode (as it started, for a live episode in progress); null when absent. */
  relevance: RelevanceLedger | null
  /** How often each action was tried in each context in training; only bundles played with networks have it. */
  trust: TrustFile | null
}

export class BundleError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'BundleError'
  }
}

export type Fetcher = (url: string) => Promise<Response>

const defaultFetcher: Fetcher = (url) => fetch(url)

async function fetchText(url: string, fetcher: Fetcher, optional = false): Promise<string> {
  let response: Response
  try {
    response = await fetcher(url)
  } catch (error) {
    throw new BundleError(`Could not fetch ${url}: ${String(error)}`)
  }
  if (!response.ok) {
    if (optional && response.status === 404) return ''
    throw new BundleError(`Could not fetch ${url}: HTTP ${response.status}`)
  }
  return response.text()
}

function parseJson<T>(text: string, file: string): T {
  try {
    return JSON.parse(text) as T
  } catch (error) {
    throw new BundleError(`${file} is not valid JSON: ${String(error)}`)
  }
}

/** Parse JSON Lines, skipping blank lines; errors name the file and line. */
export function parseJsonl<T>(text: string, file: string): T[] {
  const records: T[] = []
  text.split('\n').forEach((line, i) => {
    if (!line.trim()) return
    try {
      records.push(JSON.parse(line) as T)
    } catch (error) {
      throw new BundleError(`${file} line ${i + 1} is not valid JSON: ${String(error)}`)
    }
  })
  return records
}

/**
 * A file of another schema version is refused with a message that says what to do. Schema 1 is the old
 * architecture (five modules weighed by an arbiter); its recordings cannot be shown as d1-ultra's decisions.
 */
export function checkSchemaVersion(version: number | undefined, file: string): void {
  if (version === SUPPORTED_SCHEMA_VERSION) return
  if (version === 1) {
    throw new BundleError(
      `${file} is a schema 1 recording, from the old architecture where an arbiter weighed five modules. ` +
        `This app reads schema ${SUPPORTED_SCHEMA_VERSION}, where every decision is made by d1-ultra. ` +
        'Record the episode again with `python -m system1_doom.export`.',
    )
  }
  throw new BundleError(
    `${file} uses bundle schema version ${version ?? 'none'}, but this app reads version ${SUPPORTED_SCHEMA_VERSION}. ` +
      'Re-export the episode with the matching package, or update the app.',
  )
}

/** Whether an index line is a recording of the senses and central; a line without `solution` is. */
export const isSensesRecording = (entry: Pick<BundleIndexEntry, 'solution'>): boolean =>
  (entry.solution ?? 'senses-and-central') === 'senses-and-central'

/**
 * The index of the recordings these screens read. `index.json` also lists the rule tree's recordings, which have
 * files of their own (`decisions.jsonl` instead of `ticks.jsonl`), so they are left out here.
 */
export async function loadIndex(root = 'episodes', fetcher: Fetcher = defaultFetcher): Promise<EpisodeIndex> {
  const index = parseJson<EpisodeIndex>(await fetchText(`${root}/index.json`, fetcher), `${root}/index.json`)
  checkSchemaVersion(index.schema_version, `${root}/index.json`)
  return { ...index, episodes: index.episodes.filter(isSensesRecording) }
}

export interface LoadOptions {
  /**
   * An episode still being played: it may have no ticks yet, and its files are read at slightly different
   * moments, so the tick count is taken from the ticks rather than checked against the meta.
   */
  live?: boolean
}

export async function loadEpisode(
  name: string,
  root = 'episodes',
  fetcher: Fetcher = defaultFetcher,
  options: LoadOptions = {},
): Promise<EpisodeBundle> {
  const base = `${root}/${name}`
  // Fetched together, but a failure is reported for the first file in this order, so a missing
  // bundle always names its episode.json rather than whichever request happened to fail first.
  const settled = await Promise.allSettled([
    fetchText(`${base}/episode.json`, fetcher),
    fetchText(`${base}/ticks.jsonl`, fetcher),
    fetchText(`${base}/proposals.jsonl`, fetcher, true),
    fetchText(`${base}/reflections.jsonl`, fetcher, true),
  ])
  const [metaText = '', ticksText = '', proposalsText = '', reflectionsText = ''] = settled.map((r) => {
    if (r.status === 'rejected') throw r.reason
    return r.value
  })
  let meta = parseJson<EpisodeMeta>(metaText, `${name}/episode.json`)
  checkSchemaVersion(meta.schema_version, `${name}/episode.json`)
  const ticks = parseJsonl<TickTrace>(ticksText, `${name}/ticks.jsonl`)
  if (!options.live) {
    if (ticks.length === 0) throw new BundleError(`${name}/ticks.jsonl has no ticks.`)
    if (ticks.length !== meta.tick_count) {
      throw new BundleError(`${name}/ticks.jsonl has ${ticks.length} ticks, but episode.json says ${meta.tick_count}.`)
    }
  }
  ticks.sort((a, b) => a.tick - b.tick)
  if (options.live) {
    meta = { ...meta, tick_count: ticks.length, last_tick: ticks[ticks.length - 1]?.tick ?? meta.last_tick }
  }
  const listed = new Set(meta.files ?? [])
  // Serve writes an episode's relevance.json before its first tick, so a live episode reads it even from a meta
  // read too early to list it; trust.json exists only with value networks, and only a listed one is fetched.
  const extra = (file: string) =>
    listed.has(file) || (options.live && file === 'relevance.json')
      ? fetchText(`${base}/${file}`, fetcher, true).then((text) => text || null)
      : Promise.resolve(null)
  const [relevanceText, trustText] = await Promise.all([extra('relevance.json'), extra('trust.json')])
  return {
    name,
    base,
    meta,
    ticks,
    proposals: latestProposals(parseJsonl<ProposalTrace>(proposalsText, `${name}/proposals.jsonl`)),
    records: parseJsonl<System2Record>(reflectionsText, `${name}/reflections.jsonl`),
    relevance: relevanceText === null ? null : parseJson<RelevanceLedger>(relevanceText, `${name}/relevance.json`),
    ledgerAt: options.live ? 'start' : 'end',
    trust: trustText === null ? null : parseJson<TrustFile>(trustText, `${name}/trust.json`),
  }
}

/**
 * Another recording's relevance ledger alone, for the ledger's growth over episodes; null when it has none or
 * cannot be read, since a missing point on that line is no reason to stop the screen.
 */
export async function loadLedger(
  name: string,
  root = 'episodes',
  fetcher: Fetcher = defaultFetcher,
): Promise<RelevanceLedger | null> {
  try {
    const text = await fetchText(`${root}/${name}/relevance.json`, fetcher, true)
    return text ? parseJson<RelevanceLedger>(text, `${name}/relevance.json`) : null
  } catch {
    return null
  }
}

/**
 * One line per proposal. The run log appends a proposal again each time its macro's performance is updated; the
 * newest line of a proposal (same request and same raw text) is the one kept, in the order proposals first came.
 */
export function latestProposals(proposals: ProposalTrace[]): ProposalTrace[] {
  const byKey = new Map<string, ProposalTrace>()
  for (const p of proposals) byKey.set(`${p.timestamp}|${p.raw_proposal}`, p)
  return [...byKey.values()]
}

/**
 * The recording a fresh visit opens: the most recently recorded one that cleared its level, so the landing shows
 * the agent as it is now; among equally recent ones (an index written before it said when), the first listed;
 * when none cleared, the first. The index lists recordings by scenario, networks, whether the senses chose the
 * motor's targets, seed and starting configuration, so the first is not always the one worth watching first.
 */
export function defaultEpisode(index: Pick<EpisodeIndex, 'episodes'> | null): string | null {
  const episodes = index?.episodes ?? []
  const cleared = episodes.filter((e) => e.cleared)
  const newest = cleared.reduce<(typeof episodes)[number] | undefined>(
    (best, e) => (best === undefined || (e.recorded_at ?? '') > (best.recorded_at ?? '') ? e : best),
    undefined,
  )
  return (newest ?? episodes[0])?.name ?? null
}

/** URL of the screen the instances saw when they decided `tick`. */
export function frameUrl(bundle: Pick<EpisodeBundle, 'base' | 'meta'>, tick: number): string {
  return `${bundle.base}/${bundle.meta.frames.dir ?? 'frames'}/${String(tick).padStart(5, '0')}.jpg`
}

/** URL of a file the bundle names by its path inside the bundle, as an instance's image reference. */
export function bundleFileUrl(bundle: Pick<EpisodeBundle, 'base'>, path: string): string {
  return `${bundle.base}/${path}`
}

/** URL of the screen after the last action, or null when the bundle has none (a live episode still playing). */
export function endFrameUrl(bundle: Pick<EpisodeBundle, 'base' | 'meta'>): string | null {
  const end = bundle.meta.frames.end_frame
  return end ? `${bundle.base}/${end}` : null
}
