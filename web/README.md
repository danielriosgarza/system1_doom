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

Five screens share the timeline at the bottom:

- **Overview**, where a fresh visit lands: the whole controller as one
  diagram, every box showing the current tick and opening its
  explanation, and the **tour**, six coach marks over one real tick and
  a seventh on the hierarchy.
- **Tick**, the inspector: every level of one decision in panels.
- **Hierarchy**: the same tick as a tower of six decision cards, slowest
  at the top, with exploration pressure, d1-ultra, the learned networks
  and the simulator feeding them from the side.
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

Over any screen, the **reference** drawer (Glossary in the top bar, the ⓘ
button beside the episode picker, or the keys below) has four tabs: the
**glossary**, forty words with their meaning, this tick's value where
there is one, where the screens show them and where the code keeps them;
the **principles**, the one invariant and the seven rules with where each
is visible; **this recording**, how the bundle was made and the export
command that makes it again; and the **keyboard**. Every explanation links
its glossary words, once each, with a dotted underline.

Keyboard: ← and → step one tick (Shift for ten), Home and End jump to the
ends, Space plays and pauses; 1 to 5 switch screens, t starts the tour, f
toggles Depth, g opens the glossary, i opens this recording and ? lists
the keys; Esc closes the drawer. During the tour → and ← walk the tour and
Esc leaves it. No key fires while typing in a box, and while the drawer is
open only Esc and Tab reach the app. Depth and the theme are remembered in
this browser. Links keep the episode, tick and screen in the URL hash, for
example `#deadly_corridor-learned-9/17/hierarchy`; without a screen
(`#deadly_corridor-learned-9/17`) a link opens the inspector. The drawer is
not in the hash.

## Check it

```bash
npm run build        # type-check and production build into dist/
npm run lint         # oxlint, warnings fail
npm test             # Vitest: loader, trace readings, tower levels, pressure, trust, gate blend, returns, slow path, glossary, term links, export command
npm run e2e          # Playwright: scrubbing, links, the tour (desktop and phone), hierarchy, overview, learning, growing the menu, the reference drawer, keys
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
| `src/content/explainers.ts` | Every panel's and box's three-layer copy: sentence, paragraphs, and the formula with the tick's numbers |
| `src/content/tour.ts` | The tour's seven steps and the invariants they name |
| `src/content/architecture.ts` | The overview's boxes: title, explainer, and the panels that show them on the other screens |
| `src/content/glossary.ts` | The glossary: term, aliases, meaning, where to see it, code location and this tick's value; a test keeps it in step with the documentation's glossary |
| `src/content/principles.ts`, `src/content/keys.ts` | The invariant and the seven principles; every key the app listens to |
| `src/data/loader.ts` | Fetches `episodes/index.json` and a bundle (with its training-run files when listed), checks the schema version |
| `src/data/derive.ts` | Pure readings of a trace shared by panels (context buckets, pruning reasons, motor steps in words, pick rule in words, the six tower levels, exploration pressure from its terms, the featured tick, trust and the gate blend, n-step returns, action encodings, expansion rules, requests and follow-ups, the export command), with the controller's constants |
| `src/store.ts` | One episode, one current tick, the screen, the tour step, depth (plain or formula), theme, the hovered action, the reference drawer's tab and glossary entry |
| `src/screens/` | Overview, Inspector (Tick), Hierarchy, Learning and Menu (Growing the menu) |
| `src/components/` | One component per panel, the architecture diagram, the decision card, the exploration gauge, the steering card, the tour, the learning curves, trust map, gate view, head-to-head and reward anatomy, the request timeline, proposal card, admission gate, vocabulary diff and follow-up, plus the panel frame and the timeline |
| `src/components/Reference.tsx` | The reference drawer: the dialog, its focus handling, and the Glossary, Principles and Keyboard tabs |
| `src/components/Provenance.tsx` | The This recording tab, built from `episode.json` and the index |
| `src/components/Terms.tsx`, `TermLink.tsx` | `linkTerms`, which links each glossary word once per explanation, and the linked word itself |
| `public/episodes/` | The demo bundles and their index |

The build uses relative URLs (`base: './'`), so `dist/` can be served from
GitHub Pages or any folder.
