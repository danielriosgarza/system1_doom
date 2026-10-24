// A stand-in for `python -m system1_doom.serve` in the browser tests, with no dependencies: the built
// app, plus live mode replaying a shipped recording as live-1, live-2, … one tick every 80 ms, with a
// second's rest between episodes. The routes and events are serve's (src/system1_doom/serve.py).
import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const WEB = fileURLToPath(new URL('..', import.meta.url))
const DIST = join(WEB, 'dist')
const EPISODES = join(WEB, 'public', 'episodes')
const SOURCE = join(EPISODES, 'deadly_corridor-heuristics-9')
const PORT = Number(process.env.LIVE_PORT ?? 4174)
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
const tickNumbers = tickLines.map((line) => JSON.parse(line).tick)
const proposals = lines('proposals.jsonl').map((line) => JSON.parse(line))
// Macros the slow path admitted join the catalog when their proposal arrives, as they do in serve.
const admitted = new Set(proposals.filter((p) => p.admission_decision).map((p) => p.admitted_action_id))
const config = {
  scenario: recorded.scenario,
  seed: recorded.seed,
  model: recorded.model,
  d1: false,
  codex: false,
  slow_path: true,
  deterministic: false,
  max_ticks: 500,
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
const shownProposals = (n) => (n === 0 ? [] : proposals.filter((p) => p.tick <= tickNumbers[n - 1]))

function catalog(n) {
  const shown = new Set(shownProposals(n).map((p) => p.admitted_action_id))
  return Object.fromEntries(Object.entries(recorded.actions).filter(([id]) => !admitted.has(id) || shown.has(id)))
}

function meta(name, n, final) {
  const seed = seedOf(name)
  const base = { ...recorded, name, seed, title: `deadly corridor, heuristics only, seed ${seed}, live` }
  if (final) return { ...base, recorded_at: new Date().toISOString() }
  const zero = { health: 0, armor: 0, kills: 0, reward: 0, ticks: 0, finished: false, cleared: false, died: false }
  return {
    ...base,
    result: { ...recorded.result, ...zero, transitions: 0, explored_steps: 0, network_share: 0, actions: [] },
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
  if (held < tickLines.length) setTimeout(nextTick, TICK_MS)
  else endEpisode()
}

function endEpisode() {
  const final = meta(current, held, true)
  const entry = {
    name: current,
    title: final.title,
    scenario: final.scenario,
    model: final.model,
    seed: final.seed,
    cleared: final.result.cleared,
    died: final.result.died,
    reward: final.result.reward,
    ticks: final.tick_count,
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

/** A live episode's three record files: the one in progress as it stands, a finished one whole. */
function liveFile(name, rest) {
  const final = finals.get(name)
  if (name !== current && !final) return null
  const n = final ? tickLines.length : held
  if (rest === 'episode.json') return JSON.stringify(final ?? meta(name, n, false), null, 2)
  if (rest === 'ticks.jsonl')
    return tickLines
      .slice(0, n)
      .map((line) => line + '\n')
      .join('')
  if (rest === 'proposals.jsonl') {
    return shownProposals(n)
      .map((p) => JSON.stringify(p) + '\n')
      .join('')
  }
  return undefined
}

createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url ?? '/', 'http://localhost').pathname)
  if (path === '/live/status.json') {
    const status = { schema_version: 1, running: true, current, tick: held && current ? tickNumbers[held - 1] : null }
    return reply(
      res,
      200,
      JSON.stringify({ ...status, episodes: finished, config, started_at: startedAt }),
      TYPES['.json'],
      true,
    )
  }
  if (path === '/live/events') {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' })
    const tick = held && current ? tickNumbers[held - 1] : null
    res.write(`event: hello\ndata: ${JSON.stringify({ current, tick, episodes: finished })}\n\n`)
    clients.add(res)
    req.on('close', () => clients.delete(res))
    return
  }
  const live = /^\/episodes\/(live-\d+)\/(.+)$/.exec(path)
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
  console.log(`Mock live server at http://127.0.0.1:${PORT}/`)
  startEpisode()
})
