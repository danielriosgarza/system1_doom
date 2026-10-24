# System 1 Doom, explained

A static web app that replays one recorded episode of the `system1_doom`
controller, tick by tick, and explains every level of each decision: what
the controller saw, which actions were legal, what the simulator guessed,
what each of the five modules wanted, how the arbiter scored and picked,
what the motor pressed, and what came back.

The browser never runs the game. It reads **episode bundles** written by
`python -m system1_doom.export` (see `docs/DOCUMENTATION.md`, §8.15 and
§11), so every number on screen is one the controller recorded.

## Run it

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

Keyboard: ← and → step one tick (Shift for ten), Home and End jump to the
ends, Space plays and pauses. Links keep the episode and tick in the URL
hash, for example `#deadly_corridor-learned-9/17`.

## Check it

```bash
npm run build        # type-check and production build into dist/
npm run lint         # oxlint, warnings fail
npm test             # Vitest: loader and trace readings on a fixture bundle
npm run e2e          # Playwright: scrubbing to tick 5 shows the traced action
```

## Add an episode

From the repository root:

```bash
python -m system1_doom.export --scenario deadly_corridor.cfg --seed 9 --model latest \
    --out web/public/episodes/deadly_corridor-learned-9
python -m system1_doom.export --check web/public/episodes/deadly_corridor-learned-9
python -m system1_doom.export --index web/public/episodes
```

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
| `src/content/explainers.ts` | Every panel's three-layer copy: sentence, paragraphs, and the formula with the tick's numbers |
| `src/data/loader.ts` | Fetches `episodes/index.json` and a bundle, checks the schema version |
| `src/data/derive.ts` | Pure readings of a trace shared by panels (context buckets, pruning reasons, motor steps in words, pick rule in words), with the controller's constants |
| `src/store.ts` | One episode, one current tick, depth (plain or formula), theme, the hovered action |
| `src/components/` | One component per panel, plus the panel frame and the timeline |
| `public/episodes/` | The demo bundles and their index |

The build uses relative URLs (`base: './'`), so `dist/` can be served from
GitHub Pages or any folder.
