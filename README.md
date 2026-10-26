# system1-doom

A ViZDoom agent whose every decision is made by Liquid AI's d1-ultra.
Five senses (survival, combat, navigation, resource, goal) are each one
d1-ultra call that sees only its own slice of the evidence and decides
whether to send a message: an action, a reason, a strength. A central
d1-ultra call hears the messages, with each sense's track record, and
chooses the action; the motor presses that action's fixed keys, aiming
only at targets d1-ultra chose (the combat sense picks which visible enemy
to aim at, the resource sense which remembered pickup to walk to). The code
renders evidence, keeps the bounds and presses the keys; it never ranks,
scores or picks an action itself, and a missed answer is recorded as a
miss rather than filled in by a rule. An asynchronous slow path can
propose new macro-actions, which enter the menu only on an admit
instance's yes.

The design is in
[`docs/superpowers/specs/2026-10-25-d1-decision-maker-design.md`](docs/superpowers/specs/2026-10-25-d1-decision-maker-design.md);
System 1 (the senses and the central), System 2 (a slow loop that
changes what each instance sees) and the web app that shows both are
built.

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

The same hierarchy runs on TypeSafe's Jev, a System One decision model
that answers the same `noul`, `choice` and `score` questions, with
`--decider jev` on `cli`, `train`, `export` and `serve`. Every
instance's call then goes to `api.typesafe.ai` (it needs
`TYPESAFE_API_KEY`), the screen goes as an image asset scaled up to
Jev's minimum side, and the cost is counted at Jev's published $0.042
per million input tokens, since its usage block names none. Nothing
else changes: the same evidence, questions, bounds and misses, and a
bundle or a summary says which decider played (`decider`) and which
model version answered (`models`).

## Web explainer

**<https://danielriosgarza.github.io/system1_doom/>** opens on the agent
playing the corridor at its own pace, and beside the game what each of
the six d1-ultra instances answered at that decision: which senses spoke
or stayed silent, with what action, reason and strength, and what the
central picked. Every decision can be checked: a click on a row opens
that instance with the evidence it was sent, verbatim, the channels in
its scope and those it was not shown (the survival sense never sees the
pickups unless System 2 widens its scope), and its answers as bars. The
slow system's screen shows every configuration version with the change,
the reflector that proposed it and System 2's central's choice, the
history test's whole table, the trial and the judge, and the relevance
ledger; Learning, Growing the menu and Reference (the one rule, a drawing
of the two systems, the glossary) follow.

It ships nine recordings of `deadly_corridor.cfg` with the best
networks as evidence. Four show the agent as it is now, with the senses
choosing the motor's targets: seeds 9 to 12, played by Jev because
d1-ultra's account had no credit when they were made (seed 12 clears the
corridor in 61 decisions and is the landing; 9, 10 and 11 die in
fights; all four recorded ship). On 30 held-out seeds this agent cleared
18 against the earlier one's 12 (`docs/DOCUMENTATION.md` §15). The other
five were recorded before the senses chose targets, and their cards say
so. Three of those were played by d1-ultra: seeds 9 and 11 from
the design's version 1 (both clear the corridor, in 59 and 179
decisions) and seed 9 again from version 2, the strategy System 2 chose
and kept on the same run folder (it tries another strategy, the judge
reverts it, and the episode dies after 233 decisions). Two were played
by Jev with `--decider jev`, seeds 9 and 11 from version 1 (seed 9
cleared in 42 decisions; on seed 11 System 2 tried exploring, reverted
it, and the episode died after 211), so each decider can be watched on
the same seed; every card and the top bar say which model played. The
app reads trace schema 2 and is described in
[`web/README.md`](web/README.md); the bundles, the screens and how they
are made are in
[`docs/DOCUMENTATION.md` §8.15](docs/DOCUMENTATION.md#815-episode-bundles--the-web-explainer--exportpy-servepy-web),
and the recordings' numbers in §15.

To watch it decide live, `python -m system1_doom.serve` plays on your
machine and the same app follows each decision as it is made, and each of
System 2's records as it is written:

```bash
(cd web && npm install && npm run build)
python -m system1_doom.serve --scenario deadly_corridor.cfg --networks best
# http://127.0.0.1:8765/#live/watch   (Ctrl+C stops it)
```

## Documentation

- [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md): how everything works,
  System 2 (§8.16), every entry point and flag (§11), misses and budgets
  (§14), measured results (§15), testing and CI (§16).
- [`docs/spec.md`](docs/spec.md): the original implementation spec.
- [`web/README.md`](web/README.md): the web explainer.

```bash
python -m pytest -k "not live"     # the Python suite, on a fake d1-ultra (and a fake Jev), no key needed
python -m pytest -m live           # the seven live tests: four on d1-ultra (LIQUID_API_KEY), three on Jev (TYPESAFE_API_KEY)
(cd web && npm test && npm run e2e) # the app's unit and browser tests
```
