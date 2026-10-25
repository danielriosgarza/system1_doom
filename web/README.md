# System 1 Doom, explained

A static web app that replays an episode the `system1_doom` agent played,
decision by decision, and shows that every decision in it was made by
d1-ultra: what each of the six instances (five senses and the central)
was sent, verbatim, what it answered, and what System 2, the slow loop,
changed about what they see.

The browser never runs the game. It reads **episode bundles** (trace
schema 2) written by `python -m system1_doom.export` (see
`docs/DOCUMENTATION.md`, §8.15 and §11), so every word and number on a
screen is one the agent recorded; nothing in the app ranks, scores or
decides. In live mode (below) the same app follows an episode while it is
played.

**Online:** <https://danielriosgarza.github.io/system1_doom/>, the three
shipped recordings. Live mode is not there: a static site cannot stream,
so it runs on your machine (below).

## Run it

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

Six screens, keys 1 to 6 in this order:

- **Watch**, where a fresh visit lands (`#corridor-9/0/watch`, the first
  recording that cleared the corridor): the game plays at the agent's own
  pace, one decision every 8 game frames (about 0.23 s), and beside it the
  strip: a row per sense (spoke, with its strength as a bar, its action
  and reason; silent; or missed, with why), the central's row (its pick,
  the probability, whether that was its top answer, drawn, or a miss, and
  how many messages it heard), the Act row (the primitives held) and a
  thin configuration line (the version, the last change and what became
  of it, the trial in flight). A click on a row opens that instance on
  The instances at that decision. Under the game: Play and Pause, Real
  time or Slow (one decision a second), the counter ("decision 18 of 59 ·
  3.9 s of play") and a progress bar that seeks. Below, a card per
  recording, each playing from the start, with a link to how it was
  made. Watch plays on its own only on a fresh visit or a link to its
  first decision, and never for a viewer who asked for reduced motion;
  playing on its own, it holds the result for 2.5 s and starts again,
  and anything the viewer does ends that loop.
- **The instances**: one instance at a time, from a tab per instance. Its
  scope as chips (the channels it was shown and those it was not), the
  screen it was sent when `frame` is in its scope, its evidence verbatim
  with each `[channel]` header marked, and its answers as bars: the speak
  strength against yes_at, the action and reason distributions, or the
  central's choice distribution over the legal menu. A miss shows its
  reason and the raw answer.
- **The slow system**: System 2's record of the episode, from
  `reflections.jsonl`, `relevance.json` and the configuration at the
  start and end. The configuration versions (the change, the reflector
  that proposed it, System 2's central's choice, kept or reverted or
  queued); the cycles, each reflector's answer and evidence, and System
  2's central; the history test as a table (each sampled tick, its
  stratum, the old and new answers, the metrics, the verdict, the noise
  re-asks); the trial's before and during table and the judge; the
  relevance ledger per sense and situation; each scope at the start and
  end.
- **Learning**: the paid-off rate of each sense's followed messages over
  episodes, from every recording's ledger, and the value networks as
  evidence: the `values` channel's numbers and how often each action was
  tried in this situation in training (`trust.json`).
- **Growing the menu**: the menu at this decision, the menu reflector's
  answers, each slow-path proposal with its stages, and the admit
  instance's answer and evidence.
- **Reference**: the one rule and the principles, a drawing of the two
  systems, the glossary (kept in step with `docs/DOCUMENTATION.md` §18 by
  a test), how this recording was made, and the keys.

Every screen but Watch shares the timeline at the bottom: the counter,
the pace, and marks for damage, kills, a death, a miss, a drawn pick, a
configuration change and each System 2 cycle. The top bar holds the
screens, the recording picker and the theme, on one row from 1280 px; on
a phone the tabs scroll inside the bar. Every panel's heading opens an
explanation that links its glossary words, once each, to their entries
on Reference, and names the code behind the panel.

Keyboard: ← and → step one decision (Shift for ten), Home and End jump to
the ends, Space plays and pauses, 1 to 6 switch screens, and l follows
the live episode (live mode only). No key fires while typing in a box.
The theme and the pace are remembered in this browser. Links keep the
episode, decision and screen in the URL hash, for example
`#corridor-11/42/slow`; without a screen (`#corridor-11/42`) a link opens
The instances. While Watch plays, the hash keeps the decision playback
started from, and is brought up to date on Pause or a change of screen.

## The recordings

`public/episodes/` holds five recordings of `deadly_corridor.cfg` with
the run folder's best value networks as evidence (`--networks best`):
three with every decision made by d1-ultra, two with every decision made
by Jev, TypeSafe's decision model (`--decider jev`), on the same seeds.
The index names each recording's decider, and so do its card, the
picker, the top bar and How this recording was made.

| Recording | Decided by | Configuration | Result | Size |
|---|---|---|---|---:|
| `corridor-9` | d1-ultra | version 1 (`--fresh-configuration`) | cleared the corridor in 59 decisions, 6 kills | 4.3 MB |
| `jev-corridor-9` | Jev | version 1 (`--fresh-configuration`) | cleared the corridor in 42 decisions, 6 kills | 2.9 MB |
| `corridor-11` | d1-ultra | version 1 (`--fresh-configuration`) | cleared the corridor in 179 decisions, 7 kills | 11.7 MB |
| `jev-corridor-11` | Jev | versions 1 → 3 | died after 211 decisions, 5 kills | 11.2 MB |
| `corridor-9-v2` | d1-ultra | versions 2 → 4 | died after 233 decisions, 8 kills | 14.2 MB |

Version 2 is the strategy (`strat_evasive_survival`) System 2 chose and
its judge kept over two `cli` episodes on the same run folder; in
`corridor-9-v2` System 2 tries the other strategy, the judge reverts it
(version 4), and the change chosen again at the end is queued for the
next episode. In `jev-corridor-11` System 2 puts the agent on explore
for a 60-decision trial, the judge reverts it (version 3), and a widened
scope passes the history test at the end and is queued. Their calls,
costs and what System 2 did in each are in `docs/DOCUMENTATION.md` §15.
Together they are 44.3 MB, mostly the decisions' text. Making the
d1-ultra ones again needs `LIQUID_API_KEY`, the Jev ones
`TYPESAFE_API_KEY`.

## Live mode

Watch d1-ultra decide right now instead of replaying a recording. From
the repository root, build the app once and start the live server:

```bash
(cd web && npm install && npm run build)
python -m system1_doom.serve --scenario deadly_corridor.cfg --networks best
# open http://127.0.0.1:8765/#live/watch   (Ctrl+C stops it)
```

`serve` plays episodes one after another with the same configuration and
settings as `export` (seeds 7, 8, 9, … by default), writes each one as an
ordinary schema-2 bundle in `live/live-<k>`, and streams each decision to
the browser as it is made (`tick`) and each of System 2's records as it
is written (`reflection`). Its flags are in `docs/DOCUMENTATION.md`, §11.
Each start clears the earlier `live-<k>` folders from `live/`; to keep
one, copy it into `web/public/episodes/` and rebuild the index as under
Add an episode below. Ctrl+C finishes the current episode's files as
they stand, and the app then reads it as stopped by hand.

A visit with no hash, or `#live`, lands on Watch with the episode being
played and follows it: the bar shows a LIVE badge, the strip shows each
decision as it arrives, and the cursor stays on the newest one, riding
into the next episode when one ends; Watch never loops while it follows.
Any move of the cursor stops following, so a decision can be studied
while play goes on; **Follow** in the bar, or the key l, goes back to the
newest one. Every screen works on the live episode: The slow system adds
each cycle, verdict and note as it arrives. `#live/<screen>`, for example
`#live/slow`, links to whatever is playing. The picker lists the live
episodes under **Live** above the shipped **Recordings**, and a finished
live episode opens like any recording. The viewer only watches: it
cannot pause, steer or restart play.

To work on the app against a live server, run `serve` and `npm run dev`
side by side: the dev server passes `/live` and `/episodes/live-*`
through to `127.0.0.1:8765` (`vite.config.ts`). Without `serve`, the app
finds no `live/status.json` and is the recordings only.

## Check it

```bash
npm run lint         # oxlint, warnings fail
npx prettier --check src e2e
npm test             # Vitest, 69 tests: the loader (schema 1 refused), the strip and instance readings, System 2's records, learning, live events, playback, the glossary against the docs and the code
npm run build        # type-check and production build into dist/
npm run e2e          # Playwright, 30 tests: Watch, The instances (verbatim evidence, out-of-scope channels absent), the slow system's history test table, Learning, Growing the menu, Reference, phone width, the top bar, live mode, the shipped recordings
```

The unit tests and most browser tests read
`e2e/fixtures/episodes/fixture-corridor`, a 40-tick bundle the fake
d1-ultra plays on the corridor, recorded by `scripts/record_fixture.py`
with no API key: its System 2 admits a macro and widens the survival
sense's scope to `pickups` after a passed history test, and it holds a
sense that fails and a central that answers off the menu. Playwright
serves it with `e2e/live-server.mjs`, a stand-in for `serve` with no
Python (port 4175), and again in live mode (port 4174), replaying it as
`live-1`, `live-2`, … one tick every 80 ms with System 2's records after
the ticks they followed; `e2e/recordings.spec.ts` runs against the built
site with the shipped recordings (port 4173).

## CI and GitHub Pages

`.github/workflows/checks.yml` runs these checks on every pull request
and push to main (the `web` job, Node 22, then
`npx playwright install --with-deps chromium` before `npm run e2e`),
beside a `python` job that runs `python -m pytest -k "not live"`.
`.github/workflows/pages.yml` builds this folder on every push to main
and publishes `dist/` to the site above; the relative base makes it
work under `/system1_doom/`. It needs one repository setting: Settings →
Pages → Build and deployment → Source: GitHub Actions. A run can also be
started by hand from the Actions tab.

## Add an episode

From the repository root, with `LIQUID_API_KEY` set:

```bash
python -m system1_doom.export --scenario deadly_corridor.cfg --seed 9 --networks best \
    --fresh-configuration --out web/public/episodes/corridor-9 --name corridor-9
python -m system1_doom.export --check web/public/episodes/corridor-9
python -m system1_doom.export --index web/public/episodes
```

Without `--fresh-configuration` the episode starts from the configuration
System 2 left in `runs/<scenario>/configuration.json`, as `corridor-9-v2`
did.

## When the trace models change

The TypeScript types in `src/schema/bundle.ts` are generated from the
pydantic models, never edited by hand:

```bash
npm run schema       # python -m system1_doom.export --schema web/schema/bundle.schema.json
npm run types        # json-schema-to-typescript → src/schema/bundle.ts
```

Bump `TRACE_SCHEMA_VERSION` in `logger.py` and `SUPPORTED_SCHEMA_VERSION`
in `src/data/loader.ts` together when a change is not backwards
compatible; the loader refuses bundles from another version with a
message that says so.

## Where things live

| Path | What it is |
|---|---|
| `src/data/loader.ts` | Fetches `episodes/index.json` and a bundle (ticks, proposals, System 2's records, the ledger, the training-run files when listed), checks the schema version; an episode in progress may hold fewer ticks than its meta says, and is read with the ledger it started from (`ledgerAt`) |
| `src/data/readings.ts` | System 1's ticks rearranged for the screens: the strip's rows, the Act keys, the configuration line, each instance's scope, evidence sections, frame and answer bars, the configuration versions and System 2's cycles placed on the ticks, the timeline marks, n-step returns, the ledger before and after |
| `src/data/system2.ts` | System 2's records rearranged: a cycle's reflectors, the proposer and verdict, the history test's table and metrics, the trial's rows, the configuration at start and end, the cycle a screen opens on |
| `src/data/learning.ts` | The ledgers over episodes and the tried counts behind the values |
| `src/data/live.ts` | Live mode's data: `live/status.json`, the event stream, applying an event to the open bundle, and the picker's list |
| `src/data/playback.ts` | The pace of play: one decision every 8 game frames in real time, one a second slow, and how long the end holds |
| `src/store.ts` | The screens, one episode and its current decision, playback (playing, the pace, the landing's start and loop), the instance and glossary term open, the theme; in live mode the status, whether the viewer is following, and the stream's events applied as they arrive |
| `src/screens/` | `Watch`, `Instances`, `SlowSystem`, `Learning`, `Menu` and `Reference` |
| `src/components/` | The strip, the stage with its crossfade, the recording cards, the timeline (`Scrubber`), the panel frame and its explanation, bars, verbatim evidence, the relevance chart, the two-system drawing, linked glossary words (`Terms`, `TermLink`), the top bar |
| `src/content/` | Every word on the screens, one file per screen; `explainers.ts`, each panel's explanation and the code behind it; `glossary.ts`, the glossary a test keeps in step with the documentation and the code |
| `public/episodes/` | The five recordings and their index |
| `e2e/fixtures/episodes/` | The fixture recording the tests read |
| `e2e/live-server.mjs` | The stand-in for `serve` the browser tests run against |

The build uses relative URLs (`base: './'`), so `dist/` can be served
from GitHub Pages or any folder.
