import type {
  ActionSpec,
  BundleIndexEntry,
  EpisodeMeta,
  EvaluationSummary,
  MetricsRow,
  ProposalTrace,
  TickTrace,
  TrustFile,
} from '../schema/bundle'

/** The bundle schema version this app reads; `python -m system1_doom.export` writes it into every episode.json. */
export const SUPPORTED_SCHEMA_VERSION = 1

export interface EpisodeIndex {
  schema_version: number
  episodes: BundleIndexEntry[]
}

/** One recorded episode, as the export command wrote it. */
export interface EpisodeBundle {
  name: string
  /** URL of the bundle folder, without a trailing slash. */
  base: string
  meta: EpisodeMeta
  ticks: TickTrace[]
  proposals: ProposalTrace[]
  /** The training run behind the checkpoint, one row per episode; null when the bundle has none. */
  metrics: MetricsRow[] | null
  /** The same seeded episodes played by each brain after training; null when absent. */
  evaluation: EvaluationSummary | null
  /** The checkpoint's experience counts; only bundles recorded with a model have them. */
  trust: TrustFile | null
  /** Macros admitted during training; null when absent. */
  macros: ActionSpec[] | null
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

export function checkSchemaVersion(version: number | undefined, file: string): void {
  if (version !== SUPPORTED_SCHEMA_VERSION) {
    throw new BundleError(
      `${file} uses bundle schema version ${version ?? 'none'}, but this app reads version ${SUPPORTED_SCHEMA_VERSION}. ` +
        'Re-export the episode with the matching package, or update the app.',
    )
  }
}

export async function loadIndex(root = 'episodes', fetcher: Fetcher = defaultFetcher): Promise<EpisodeIndex> {
  const index = parseJson<EpisodeIndex>(await fetchText(`${root}/index.json`, fetcher), `${root}/index.json`)
  checkSchemaVersion(index.schema_version, `${root}/index.json`)
  return index
}

export interface LoadOptions {
  /**
   * An episode still being played: it may have no ticks yet, and the three files are read at slightly
   * different moments, so the tick count is taken from the ticks rather than checked against the meta.
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
  ])
  const [metaText = '', ticksText = '', proposalsText = ''] = settled.map((r) => {
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
  const proposals = parseJsonl<ProposalTrace>(proposalsText, `${name}/proposals.jsonl`)

  // Files copied from the training run, fetched only when episode.json lists them.
  const listed = new Set(meta.files ?? [])
  const extra = (file: string) =>
    listed.has(file) ? fetchText(`${base}/${file}`, fetcher, true).then((text) => text || null) : Promise.resolve(null)
  const [metricsText, evaluationText, trustText, macrosText] = await Promise.all([
    extra('metrics.jsonl'),
    extra('evaluation.json'),
    extra('trust.json'),
    extra('macros.json'),
  ])
  return {
    name,
    base,
    meta,
    ticks,
    proposals,
    metrics: metricsText === null ? null : parseJsonl<MetricsRow>(metricsText, `${name}/metrics.jsonl`),
    evaluation:
      evaluationText === null ? null : parseJson<EvaluationSummary>(evaluationText, `${name}/evaluation.json`),
    trust: trustText === null ? null : parseJson<TrustFile>(trustText, `${name}/trust.json`),
    macros: macrosText === null ? null : parseJson<ActionSpec[]>(macrosText, `${name}/macros.json`),
  }
}

/**
 * The recording a fresh visit opens: the first in the index that cleared its level, else the first. The
 * index lists recordings in the order they were exported, so the first is not always the one worth watching.
 */
export function defaultEpisode(index: Pick<EpisodeIndex, 'episodes'> | null): string | null {
  const episodes = index?.episodes ?? []
  return (episodes.find((e) => e.cleared) ?? episodes[0])?.name ?? null
}

/** URL of the screen the controller saw when it decided `tick`. */
export function frameUrl(bundle: Pick<EpisodeBundle, 'base' | 'meta'>, tick: number): string {
  return `${bundle.base}/${bundle.meta.frames.dir ?? 'frames'}/${String(tick).padStart(5, '0')}.jpg`
}

/** URL of the screen after the last action, or null when the bundle has none (a live episode still playing). */
export function endFrameUrl(bundle: Pick<EpisodeBundle, 'base' | 'meta'>): string | null {
  const end = bundle.meta.frames.end_frame
  return end ? `${bundle.base}/${end}` : null
}
