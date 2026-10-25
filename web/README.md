# System 1 Doom, explained

A static web app that replays one recorded episode of the `system1_doom`
controller, tick by tick, and explains every level of each decision: what
the controller saw, which actions were legal, what the simulator guessed,
what each of the five modules wanted, how the arbiter scored and picked,
what the motor pressed, and what came back.

The browser never runs the game. It reads **episode bundles** written by
`python -m system1_doom.export` (see `docs/DOCUMENTATION.md`, §8.15 and
§11), so every number on screen is one the controller recorded. In
live mode (below) the same app follows an episode while it is played.

**Online:** <https://danielriosgarza.github.io/system1_doom/>, the four
shipped recordings. Live mode is not there: a static site cannot stream,
so it runs on your machine (below).

## Run it

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

Six screens, keys 1 to 6 in this order:

- **Watch**, where a fresh visit lands (`#deadly_corridor-learned-9/0/watch`,
  the first recording that cleared the corridor): the recording plays at
  the agent's own pace, one decision every 8 game frames (about 0.23 s),
  with its decision chain beside it, six rows from the slowest level at
  the top to the keys pressed at the bottom. A row pulses when what its
  level chose changes, and a click on it pauses and opens The chain at
  that decision with the level expanded. Under the game: Play and Pause,
  Real time or Slow (one decision a second), the counter ("decision 18 of
  52 · 3.9 s of play"), and a progress bar with the health line that
  seeks on click or drag. At the end the result shows over the last
  screen. Below, one card per recording, each opening here and playing
  from the start, and a three-line "How to read this" card that stays
  away once dismissed. Watch plays on its own only on a fresh visit or a
  link to its first decision, and never for a viewer who asked for
  reduced motion; a link to a later decision waits for Play. Playing on
  its own, it holds the result for 2.5 s and starts again; anything the
  viewer does (Pause, the pace, the progress bar, a row, a key, a card,
  another screen) ends that loop, and the next end stays on the result.
- **The chain**: the current tick as a tower of six decision cards,
  slowest at the top, with what the agent saw at that decision (the
  frame), exploration pressure, d1-ultra, the learned networks and the
  simulator feeding them from the side.
- **The inspector**: every level of one decision in panels.
- **The diagram**: the whole controller as one diagram, every box showing
  the current tick and opening its explanation, with the brains of the
  open recording and a line for each screen.
- **Learning**: the training run behind the checkpoint, the evaluation
  of each brain, the two recordings of the same seed side by side, and
  at this tick the trust map, the gate's module weights and what each
  module learns from. It reads `metrics.jsonl`, `evaluation.json` and
  `trust.json` when the bundle has them.
- **Growing the menu**: the slow path over the whole episode (each
  module's expansion counter against its threshold, the requests and when
  the worker answered), then the proposal shown at this tick from the
  sentence that asked to the parsed macro, the admission gate with the
  sandbox rollout, the menu before and after with the 12-number encoding,
  and what the admitted macro and its strategy did afterwards.

Every screen but Watch shares the timeline at the bottom, which carries
the tick counter and the pace. The top bar holds the screens, the
recording picker, **Reference** and the theme. Depth (Plain or Formula)
sits in the header of The chain, The inspector, Learning and Growing the
menu, and **Take the tour** in the first two: six coach marks over one
real tick in the inspector and a seventh on The chain.

The **reference** drawer (Reference in the top bar, or the keys below)
has four tabs: the **glossary**, forty words with their meaning, this
tick's value where there is one, where the screens show them and where
the code keeps them; the **principles**, the one invariant and the seven
rules with where each is visible; **this recording**, how the bundle was
made, the export command that makes it again, and the serve command that
plays the same game live on your machine (Watch's line under the game
opens it there); and the **keyboard**. Every explanation links its
glossary words, once each, with a dotted underline.

Keyboard: ← and → step one tick (Shift for ten), Home and End jump to the
ends, Space plays and pauses; 1 to 6 switch screens, t starts the tour, f
toggles Depth, g opens the glossary, i opens this recording, l follows
the live episode (live mode only) and ? lists the keys; Esc closes the
drawer. During the tour → and ← walk the tour and Esc leaves it. No key
fires while typing in a box, and while the drawer is open only Esc and
Tab reach the app. Depth, the theme, the pace and a dismissed help card
are remembered in this browser. Links keep the episode, tick and screen
in the URL hash, for example `#deadly_corridor-learned-9/17/hierarchy`
(`hierarchy` is The chain, `tick` the inspector, `overview` the diagram);
without a screen (`#deadly_corridor-learned-9/17`) a link opens the
inspector, as it always did. While Watch plays, the hash keeps the
decision playback started from, and is brought up to date on Pause or a
change of screen. The drawer is not in the hash.

## The recordings

`public/episodes/` holds four recordings of the deadly corridor, two
per seed, so the Learning screen can set each one beside the other
brain on the same seed:

| Recording | Brain | Result |
|---|---|---|
| `deadly_corridor-heuristics-9` | heuristics only | died after 36 decisions, 1 kill |
| `deadly_corridor-learned-9` | the networks after 300 training episodes | cleared the corridor in 52 decisions, 6 kills |
| `deadly_corridor-heuristics-11` | heuristics only | died after 55 decisions, 4 kills |
| `deadly_corridor-learned-d1-11` | the same networks with d1-ultra's advice | died after 44 decisions, 4 kills |

The d1 recording was made with `--d1 --d1-sync`: every tick waited for
d1-ultra's answers (134 calls, about a minute), so each tick carries
them, and the app shows them wherever it has a place: the overview's
d1-ultra box, the module columns, the arbiter card, the exploration
gauge, the admission gate's d1 stage, which turned away both of this
episode's proposals, and the hierarchy. Making it again needs
`LIQUID_API_KEY`; the other three need no key.

## Live mode

Watch the controller decide right now instead of replaying a recording.
From the repository root, build the app once and start the live server:

```bash
(cd web && npm install && npm run build)
python -m system1_doom.serve --scenario deadly_corridor.cfg --model latest
# open http://127.0.0.1:8765/   (Ctrl+C stops it)
```

`serve` plays episodes one after another with the same deciders and
settings as `export` (seeds 7, 8, 9, … by default), writes each one as an
ordinary bundle in `live/live-<k>`, and streams every tick to the browser
as it is decided. Its flags are in `docs/DOCUMENTATION.md`, §11. Each
start clears the earlier `live-<k>` folders from `live/`; to keep one,
copy it into `web/public/episodes/` and rebuild the index as under Add
an episode below. Ctrl+C finishes the current episode's files as they
stand, and the app then reads it as stopped by hand.

A visit with no hash, or `#live`, lands on Watch with the episode being
played and follows it: the bar shows a pulsing LIVE badge, the progress
bar and the timeline grow, and the cursor stays on the newest tick,
riding into the next episode when one ends; Watch never loops while it
follows. Any move of the cursor (←, →, a click on the timeline, Space)
stops following, so a tick can be studied while play goes on; **Follow**
in the bar, or the key l, goes back to the newest tick. Every screen,
the tour and the drawer work on the live episode; until it ends, its
result reads as still playing and This recording shows the serve command.
`#live/<screen>`, for example `#live/hierarchy`, links to whatever is
playing; `#live` alone is `#live/watch`. The picker lists the live episodes under **Live** (the one
playing first, then the finished ones with their results) above the
shipped **Recordings**, and a finished live episode opens like any
recording. The viewer only watches: it cannot pause, steer or restart
play, and nothing ahead of the newest tick exists yet.

To work on the app against a live server, run `serve` and `npm run dev`
side by side: the dev server passes `/live` and `/episodes/live-*`
through to `127.0.0.1:8765` (`vite.config.ts`). Without `serve`, the app
finds no `live/status.json` and is exactly the static explainer.

## Check it

```bash
npm run build        # type-check and production build into dist/
npm run lint         # oxlint, warnings fail
npx prettier --check src e2e
npm test             # Vitest: loader and the featured recording, playback pace, trace readings, tower levels, pressure, trust, gate blend, returns, slow path, d1-ultra's advice, Watch's chain rows and words, glossary, term links, export and serve commands, live events and the picker
npm run e2e          # Playwright: Watch (landing, autoplay, rows, cards, the end and the loop, reduced motion, pace, help card, phone), scrubbing, links, the tour (desktop and phone), the chain, the diagram, d1's answers, learning, growing the menu, the reference drawer, keys, live mode
```

The live mode tests run against `e2e/live-server.mjs`, a stand-in for
`serve` with no Python: it replays `deadly_corridor-heuristics-9` as
`live-1`, `live-2`, … one tick every 80 ms. Playwright starts it beside
the preview server.

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

From the repository root:

```bash
python -m system1_doom.export --scenario deadly_corridor.cfg --seed 9 --model latest \
    --out web/public/episodes/deadly_corridor-learned-9
python -m system1_doom.export --check web/public/episodes/deadly_corridor-learned-9
python -m system1_doom.export --index web/public/episodes
```

With `--d1 --d1-sync` (and `LIQUID_API_KEY` set) the recording waits for
d1-ultra at every tick, as `deadly_corridor-learned-d1-11` did.

## When the trace models change

The TypeScript types in `src/schema/bundle.ts` are generated from the
pydantic models, never edited by hand:

```bash
npm run schema       # python -m system1_doom.export --schema web/schema/bundle.schema.json
npm run types        # json-schema-to-typescript → src/schema/bundle.ts
```

Bump `TRACE_SCHEMA_VERSION` in `logger.py` and `SUPPORTED_SCHEMA_VERSION`
in `src/data/loader.ts` together when a change is not backwards compatible;
the loader refuses bundles from another version with a message that says so.

## Where things live

| Path | What it is |
|---|---|
| `src/content/watch.ts` | Every word on Watch: the title, the transport, the six chain rows in plain words, the recording cards, the help card, the end line and the stage's alt text |
| `src/content/explainers.ts` | Every panel's and box's three-layer copy: sentence, paragraphs, and the formula with the tick's numbers |
| `src/content/tour.ts` | The tour's seven steps and the invariants they name |
| `src/content/architecture.ts` | The overview's boxes: title, explainer, and the panels that show them on the other screens |
| `src/content/glossary.ts` | The glossary: term, aliases, meaning, where to see it, code location and this tick's value; a test keeps it in step with the documentation's glossary |
| `src/content/principles.ts`, `src/content/keys.ts` | The invariant and the seven principles; every key the app listens to |
| `src/content/live.ts` | The words live mode adds: the badge, Follow, the picker's groups, the overview line and This recording's lines |
| `src/data/loader.ts` | Fetches `episodes/index.json` and a bundle (with its training-run files when listed), checks the schema version; an episode in progress may hold fewer ticks than it did a moment ago |
| `src/data/live.ts` | Live mode's data: `live/status.json`, the event stream, applying an event to the open bundle, and the picker's list |
| `src/data/derive.ts` | Pure readings of a trace shared by panels (context buckets, pruning reasons, motor steps in words, pick rule in words, the six tower levels, exploration pressure from its terms, the featured tick, trust and the gate blend, n-step returns, action encodings, expansion rules, requests and follow-ups, the export and serve commands), with the controller's constants |
| `src/data/playback.ts` | The pace of play: one decision every 8 game frames in real time, one a second slow, and how long the end holds |
| `src/store.ts` | One episode, one current tick, the screen, playback (playing, the pace, the landing's start and loop, the end), the tour step, depth (plain or formula), theme, the hovered action, the reference drawer's tab and glossary entry, the level The chain opens with; in live mode the status, whether the viewer is following, and the stream's events applied as they arrive; `usePlayback` runs the clock |
| `src/screens/` | Watch, Hierarchy (The chain), Inspector (The inspector), Overview (The diagram), Learning and Menu (Growing the menu) |
| `src/components/Stage.tsx`, `ChainStrip.tsx`, `RecordingCards.tsx`, `useFrames.ts` | Watch's parts: the game with a crossfade between frames, the six rows, the cards, and the frames fetched and decoded ahead of play |
| `src/components/` | One component per panel, the architecture diagram, the decision card, the exploration gauge, the steering card, the tour, the learning curves, trust map, gate view, head-to-head and reward anatomy, the request timeline, proposal card, admission gate, vocabulary diff and follow-up, plus the panel frame and the timeline |
| `src/components/Reference.tsx` | The reference drawer: the dialog, its focus handling, and the Glossary, Principles and Keyboard tabs |
| `src/components/Provenance.tsx` | The This recording tab, built from `episode.json` and the index |
| `src/components/Terms.tsx`, `TermLink.tsx` | `linkTerms`, which links each glossary word once per explanation, and the linked word itself |
| `public/episodes/` | The four recordings and their index |
| `e2e/live-server.mjs` | The stand-in for `serve` the live mode browser tests run against |

The build uses relative URLs (`base: './'`), so `dist/` can be served from
GitHub Pages or any folder.
