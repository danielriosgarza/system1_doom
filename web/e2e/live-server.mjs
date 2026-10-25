// A stand-in for `python -m system1_doom.serve` in the browser tests, with no dependencies: the built app and the
// fixture recordings (e2e/fixtures/episodes). With LIVE=1 it also runs live mode, replaying the fixture as live-1,
// live-2, … one tick every 80 ms with a second's rest between episodes, and each of System 2's records right after
// the tick it followed. The routes and events are serve's (src/system1_doom/serve.py), schema version 2.
import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const WEB = fileURLToPath(new URL('..', import.meta.url))
const DIST = join(WEB, 'dist')
const EPISODES = join(WEB, 'e2e', 'fixtures', 'episodes')
const SOURCE = join(EPISODES, 'fixture-corridor')
const PORT = Number(process.env.PORT ?? 4174)
const LIVE = process.env.LIVE !== '0'
const TICK_MS = 80
const REST_MS = 1000

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.jsonl': 'application/x-ndjson',
  '.jpg': 'image/jpeg',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
}

const lines = (file) => readFileSync(join(SOURCE, file), 'utf8').split('\n').filter(Boolean)
const recorded = JSON.parse(readFileSync(join(SOURCE, 'episode.json'), 'utf8'))
const tickLines = lines('ticks.jsonl')
const tickTimes = tickLines.map((line) => Date.parse(JSON.parse(line).timestamp))
const tickNumbers = tickLines.map((line) => JSON.parse(line).tick)
const proposals = lines('proposals.jsonl').map((line) => JSON.parse(line))
const recordLines = lines('reflections.jsonl')
/** How many ticks had been played when each record was written: it is sent right after that tick. */
const recordAfter = recordLines.map((line) => {
  const record = JSON.parse(line)
  const when = Date.parse(record.started_at ?? record.timestamp)
  return Math.max(1, tickTimes.filter((t) => t <= when).length)
})
// Macros the admit instance admitted join the catalog when their proposal arrives, as they do in serve.
const admitted = new Set(proposals.filter((p) => p.admission_decision).map((p) => p.admitted_action_id))
const config = {
  scenario: recorded.scenario,
  seed: recorded.seed,
  decider: 'd1-ultra',
  networks: recorded.value_networks,
  call_budget_sec: null,
  exploration_level: null,
  codex: false,
  slow_path: true,
  system2: true,
  max_ticks: recorded.config.max_ticks,
  pace_sec: TICK_MS / 1000,
  episodes: null,
}
const startedAt = new Date().toISOString()

let k = 0
let current = null
let held = 0
let episodeStarted = startedAt
/** Finished live episodes' final metas, by name, and their index lines, newest first. */
const finals = new Map()
const finished = []
const clients = new Set()

const seedOf = (name) => config.seed + Number(name.slice('live-'.length)) - 1
const shownProposals = (n) => (n === 0 ? [] : proposals.filter((p) => (p.tick ?? 0) <= tickNumbers[n - 1]))
const shownRecords = (n) => recordLines.filter((_, i) => recordAfter[i] <= n)

function catalog(n) {
  const shown = new Set(shownProposals(n).map((p) => p.admitted_action_id))
  return Object.fromEntries(Object.entries(recorded.actions).filter(([id]) => !admitted.has(id) || shown.has(id)))
}

function meta(name, n, final) {
  const seed = seedOf(name)
  const base = { ...recorded, name, seed, title: `deadly corridor, seed ${seed}, live` }
  if (final) return { ...base, recorded_at: new Date().toISOString() }
  const zero = { health: 0, armor: 0, kills: 0, reward: 0, ticks: 0, finished: false, cleared: false, died: false }
  return {
    ...base,
    result: { ...recorded.result, ...zero, finished_reason: null, transitions: 0, actions: [] },
    configuration_end: recorded.configuration_start,
    system2: null,
    first_tick: 0,
    last_tick: n === 0 ? 0 : tickNumbers[n - 1],
    tick_count: n,
    frames: { ...recorded.frames, end_frame: null },
    actions: catalog(n),
    recorded_at: episodeStarted,
  }
}

function send(event, data, id) {
  const frame = `event: ${event}\n${id === undefined ? '' : `id: ${id}\n`}data: ${data}\n\n`
  for (const res of clients) res.write(frame)
}

function startEpisode() {
  k += 1
  current = `live-${k}`
  held = 0
  episodeStarted = new Date().toISOString()
  send('start', JSON.stringify({ name: current, meta: meta(current, 0, false) }))
  setTimeout(nextTick, TICK_MS)
}

function nextTick() {
  const before = shownProposals(held).length
  held += 1
  send('tick', `{"name":${JSON.stringify(current)},"trace":${tickLines[held - 1]}}`, tickNumbers[held - 1])
  const shown = shownProposals(held)
  if (shown.length !== before) {
    send('proposals', JSON.stringify({ name: current, proposals: shown, actions: catalog(held) }))
  }
  recordLines.forEach((line, i) => {
    if (recordAfter[i] === held) send('reflection', `{"name":${JSON.stringify(current)},"record":${line}}`)
  })
  if (held < tickLines.length) setTimeout(nextTick, TICK_MS)
  else endEpisode()
}

function endEpisode() {
  const final = meta(current, held, true)
  const entry = {
    name: current,
    title: final.title,
    scenario: final.scenario,
    value_networks: final.value_networks,
    seed: final.seed,
    cleared: final.result.cleared,
    died: final.result.died,
    reward: final.result.reward,
    ticks: final.tick_count,
    kills: final.result.kills,
    configuration_start: final.configuration_start.version ?? 1,
    configuration_end: final.configuration_end.version ?? 1,
  }
  finals.set(current, final)
  finished.unshift(entry)
  send('end', JSON.stringify({ name: current, meta: final, entry }))
  current = null
  setTimeout(startEpisode, REST_MS)
}

function reply(res, status, body, type, noStore = false) {
  res.writeHead(status, { 'Content-Type': type, ...(noStore ? { 'Cache-Control': 'no-store' } : {}) })
  res.end(body)
}

function file(res, root, relative, noStore = false) {
  const path = normalize(join(root, relative))
  if (!path.startsWith(root + sep)) return reply(res, 404, 'Not found', 'text/plain')
  try {
    reply(res, 200, readFileSync(path), TYPES[extname(path)] ?? 'application/octet-stream', noStore)
  } catch {
    reply(res, 404, 'Not found', 'text/plain', noStore)
  }
}

/** A live episode's record files: the one in progress as it stands, a finished one whole. */
function liveFile(name, rest) {
  const final = finals.get(name)
  if (name !== current && !final) return null
  const n = final ? tickLines.length : held
  const jsonl = (items) => items.map((line) => line + '\n').join('')
  if (rest === 'episode.json') return JSON.stringify(final ?? meta(name, n, false), null, 2)
  if (rest === 'ticks.jsonl') return jsonl(tickLines.slice(0, n))
  if (rest === 'proposals.jsonl') return jsonl(shownProposals(n).map((p) => JSON.stringify(p)))
  if (rest === 'reflections.jsonl') return jsonl(shownRecords(n))
  return undefined
}

createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url ?? '/', 'http://localhost').pathname)
  if (path === '/live/status.json') {
    // Without live mode, answer as vite preview does: the app's page, which the app reads as no live mode.
    if (!LIVE) return file(res, DIST, 'index.html')
    const status = { schema_version: 2, running: true, current, tick: held && current ? tickNumbers[held - 1] : null }
    return reply(
      res,
      200,
      JSON.stringify({ ...status, episodes: finished, config, started_at: startedAt }),
      TYPES['.json'],
      true,
    )
  }
  if (path === '/live/events' && LIVE) {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' })
    const tick = held && current ? tickNumbers[held - 1] : null
    res.write(`event: hello\ndata: ${JSON.stringify({ current, tick, episodes: finished })}\n\n`)
    clients.add(res)
    req.on('close', () => clients.delete(res))
    return
  }
  const live = LIVE && /^\/episodes\/(live-\d+)\/(.+)$/.exec(path)
  if (live) {
    const [, name, rest] = live
    const body = liveFile(name, rest)
    if (body === null) return reply(res, 404, 'Not found', 'text/plain', true)
    if (body !== undefined) return reply(res, 200, body, TYPES[extname(rest)] ?? 'text/plain', true)
    return file(res, SOURCE, rest, true)
  }
  if (path.startsWith('/episodes/')) return file(res, EPISODES, path.slice('/episodes/'.length))
  return file(res, DIST, path === '/' ? 'index.html' : path.slice(1))
}).listen(PORT, '127.0.0.1', () => {
  console.log(`Fixture server at http://127.0.0.1:${PORT}/${LIVE ? ', live mode on' : ''}`)
  if (LIVE) startEpisode()
})
