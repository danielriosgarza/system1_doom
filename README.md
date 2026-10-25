# system1-doom

A ViZDoom agent whose every decision is made by Liquid AI's d1-ultra.
Five senses (survival, combat, navigation, resource, goal) are each one
d1-ultra call that sees only its own slice of the evidence and decides
whether to send a message: an action, a reason, a strength. A central
d1-ultra call hears the messages, with each sense's track record, and
chooses the action; the motor presses that action's fixed keys. The code
renders evidence, keeps the bounds and presses the keys; it never ranks,
scores or picks an action itself, and a missed answer is recorded as a
miss rather than filled in by a rule. An asynchronous slow path can
propose new macro-actions, which enter the menu only on an admit
instance's yes.

The design is in
[`docs/superpowers/specs/2026-10-25-d1-decision-maker-design.md`](docs/superpowers/specs/2026-10-25-d1-decision-maker-design.md);
System 1 (the senses and the central) and System 2 (a slow loop that
changes what each instance sees) are built; the web app's rewrite around
them is the third pull request.

## System 2

System 2 changes what the agent's instances see while it plays, one
change at a time, and every one of its decisions is a d1-ultra instance
too. On its own thread, every 20 decisions or at the end of an episode,
nine reflectors read System 1's history: one for each sense, one for
the central, one each for the menu, the strategy and the exploration
level. Each may propose one change from a finite menu the bounds allow:
widen or narrow a scope by one channel, ask the slow path for a macro or
retire one, switch the strategy, change the level. System 2's central
chooses one change or none. A scope change must first pass a history
test (the instance re-run under the new scope on 24 of the agent's own
stored ticks); then the change takes effect at a tick boundary, is
observed for 60 decisions, and a trial judge keeps or reverts it. Every
cycle is logged to `reflections.jsonl`. The configuration reached is
saved to `runs/<scenario>/configuration.json`, and the next run in that
folder starts from it (`--fresh-configuration` starts from the design's
version 1; each run says which on stderr). `--no-system2` switches System 2 off in
`cli`, `train`, `export` and `serve`. A cycle without a history test is
at most 10 calls, about $0.0003; a history test adds 28 calls, about
$0.001.

## Play

Every decision is a d1-ultra call, so playing needs `LIQUID_API_KEY`, in
the environment or in `.env`:

```bash
pip install -e ".[dev]"
python -m system1_doom.cli --scenario basic.cfg --disable-slow-llm      # 15 decisions, JSON summary
python -m system1_doom.cli --scenario deadly_corridor.cfg --episodes 1 --visible
```

A tick takes about 0.8 s (five sense calls in parallel, then the
central) and costs about $0.0002 at the measured usage. `cli`, `train`,
`export` and `serve` all exit with a message when the key is missing;
`--call-budget`, `--explore`/`--exploit`, `--seed`, `--configuration`,
`--fresh-configuration` and `--no-system2` work on each.
`--codex` lets the slow path ask the Codex CLI for proposals instead of
its templates.

## Web explainer

**<https://danielriosgarza.github.io/system1_doom/>** replays recordings
of the agent in the corridor, tick by tick, with every level of each
decision explained. Its four recordings and its screens show the
architecture this design replaced (five hand-written modules and an
arbiter); they read trace schema 1. The Python side now writes schema 2,
in which each tick holds the six instances, the evidence each one saw
verbatim, their answers and the pick, and the app is rewritten around it
with new recordings in the design's third pull request. The app is
described in [`web/README.md`](web/README.md); the bundles and how they
are made are in
[`docs/DOCUMENTATION.md` §8.15](docs/DOCUMENTATION.md#815-episode-bundles--the-web-explainer--exportpy-servepy-web).

`python -m system1_doom.serve` plays live and streams schema-2 ticks to a
local server (the current app will render them from the third pull
request on):

```bash
(cd web && npm install && npm run build)
python -m system1_doom.serve --scenario deadly_corridor.cfg --networks best
# http://127.0.0.1:8765/   (Ctrl+C stops it)
```

## Documentation

- [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md): how everything works,
  System 2 (§8.16), every entry point and flag (§11), misses and budgets
  (§14), measured results (§15), testing and CI (§16).
- [`docs/spec.md`](docs/spec.md): the original implementation spec.
- [`web/README.md`](web/README.md): the web explainer.

```bash
python -m pytest -k "not live"     # the Python suite, on a fake d1-ultra, no key needed
python -m pytest -m live           # the four live tests, with LIQUID_API_KEY
(cd web && npm test && npm run e2e) # the app's unit and browser tests
```
