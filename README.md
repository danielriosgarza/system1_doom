# system1-doom

A bounded decision controller for ViZDoom. Five independent decision
modules, a finite arbiter, bounded simulation, explicit exploration and a
strategy archive decide every tick inside a fixed time budget; per-module
learned value networks and Liquid AI's d1-ultra advise; an asynchronous
slow path can propose new macro-actions, which enter play only after
deterministic admission.

## Web explainer

**<https://danielriosgarza.github.io/system1_doom/>** replays recorded
episodes tick by tick and explains every level of each decision: what the
controller saw, which actions were legal, what each module wanted, how the
arbiter picked, what the motor pressed and what came back. One recording
has d1-ultra's advice at every tick. The app and its screens are described
in [`web/README.md`](web/README.md); the bundles it reads, the recordings
and how they were made are in
[`docs/DOCUMENTATION.md` §8.15](docs/DOCUMENTATION.md#815-episode-bundles--the-web-explainer--tracingpy-exportpy-web).

The site is static, so live mode is not on it. To watch the controller
decide right now, each tick streamed to the same app as it is played, run
it locally:

```bash
pip install -e ".[dev]"
(cd web && npm install && npm run build)
python -m system1_doom.serve --scenario deadly_corridor.cfg --model heuristics
# open http://127.0.0.1:8765/   (Ctrl+C stops it)
```

`--model latest` plays the trained networks instead, once
`python -m system1_doom.train` (or a copied run) has filled
`runs/deadly_corridor/`; that needs the `learn` extra (torch).

## Keys and services

Nothing above needs a key. `--d1` (d1-ultra, in `cli`, `train`, `export`
and `serve`) needs `LIQUID_API_KEY`, in the environment or in `.env`, and
so do the five live tests (`pytest -k live`); `--codex` needs the Codex
CLI. Without them the controller plays on its own deciders and the slow
path on fallback templates.

## Documentation

- [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md): how everything works,
  every entry point and flag (§11), testing and CI (§16).
- [`docs/spec.md`](docs/spec.md): the original implementation spec.
- [`web/README.md`](web/README.md): the web explainer.

```bash
python -m pytest -k "not live"     # the Python suite without a key
(cd web && npm test && npm run e2e) # the app's unit and browser tests
```
