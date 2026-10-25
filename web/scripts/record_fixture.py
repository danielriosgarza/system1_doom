"""Record the app's test fixture: one short deadly-corridor bundle played by the fake d1-ultra.

Run from the repository root (it imports `tests.fake_d1`):

    .venv/bin/python web/scripts/record_fixture.py

It writes `web/e2e/fixtures/episodes/fixture-corridor/` and that folder's `index.json`. Nothing here calls the
real API. The bundle is small but holds everything the app reads:

- value networks: two 8-decision training episodes on the fake first, so the values channel has numbers
  and tried counts (`--networks latest`);
- a configuration with short System 2 bounds (a cycle every 8 decisions, an 8-decision trial), so one
  episode holds a macro request the admit instance answers, a history test that passes, a trial, a
  verdict and a configuration change mid-episode;
- misses: the navigation sense raises on its 4th call and the central answers off the menu on its 6th.

The warm-up episodes' training rows (`metrics.jsonl`) are left out; everything else is the bundle as exported.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from system1_doom import export, train  # noqa: E402
from system1_doom.configuration import default_configuration  # noqa: E402
from tests.fake_d1 import (  # noqa: E402
    SYSTEM2_CENTRAL,
    TRIAL_JUDGE,
    FakeD1,
    _sense,
    choice,
    first_message_action,
    health,
    judge,
    menu_of,
    reflector_answer,
    section,
    shoot_when_aimed,
)

OUT = ROOT / "web" / "e2e" / "fixtures" / "episodes"
NAME = "fixture-corridor"
SCENARIO = "deadly_corridor.cfg"
SEED = 9
MAX_TICKS = 40


def fixture_system1(name: str, payload: Dict[str, Any]):
    """Survival speaks for `weave_fire` every tick until its scope shows the pickups, then only under 40 health;
    combat shoots or turns toward the nearest enemy; resource asks for a pickup under 60 health when it sees one;
    navigation and goal stay silent. The central follows the first message, else weaves and fires."""
    state = payload["state"]
    if name == "central":
        menu = menu_of(payload)
        wanted = first_message_action(state)
        fallback = "weave_fire" if "weave_fire" in menu else menu[0]
        return {"choose": choice(menu, wanted if wanted in menu else fallback)}
    if name == "admit":
        return {"admit": {"type": "noul", "noul": 0.8}}
    menu = menu_of(payload)
    weave = "weave_fire" if "weave_fire" in menu else menu[0]
    hp = health(state)
    if name == "survival":
        if "[pickups]" not in state:
            return _sense(payload, 0.9, weave, "enemy_too_close")
        low = hp is not None and hp < 40
        return _sense(payload, 0.85 if low else 0.15, weave, "health_critical" if low else "no_threat")
    if name == "resource":
        near = "visible, nearest first" in section(state, "pickups")
        want = near and hp is not None and hp < 60 and "approach_pickup" in menu
        return _sense(payload, 0.7 if want else 0.2, "approach_pickup" if want else menu[0],
                      "health_pickup_near" if want else "nothing_needed")
    if name == "goal":
        return _sense(payload, 0.3, menu[0], "making_progress")
    return shoot_when_aimed(name, payload)


def fixture_system2():
    """The menu reflector asks for a combat macro in the first cycle; the survival auditor proposes showing the
    survival sense the pickups from the second; System 2's central prefers a macro, else the first change."""
    asked: Dict[str, int] = {}

    def policy(name: str, payload: Dict[str, Any]):
        asked[name] = asked.get(name, 0) + 1
        if name == SYSTEM2_CENTRAL:
            criteria = list(payload["questions"]["configure"]["criteria"])
            wanted = next((c for c in criteria if c.startswith("macro:")), None)
            wanted = wanted or next((c for c in criteria if c != "none"), "none")
            rest = 0.2 / max(1, len(criteria) - 1)
            probs = {c: (0.8 if c == wanted else rest) for c in criteria}
            return {"configure": {"type": "choice", "choice": wanted, "probabilities": probs, "confidence": 0.8}}
        if name == TRIAL_JUDGE:
            return judge(payload, "keep")
        changes = list(payload["questions"]["change"]["criteria"])
        if name == "menu_reflector" and asked[name] == 1 and "macro:combat" in changes:
            return reflector_answer(payload, 0.9, "macro:combat", "no_fitting_action")
        if name == "survival_auditor" and asked[name] >= 2 and "widen:survival:pickups" in changes:
            return reflector_answer(payload, 0.9, "widen:survival:pickups", "poor_payoff")
        return reflector_answer(payload, 0.1, "keep", "too_little_data")

    return policy


def trim(out: Path) -> None:
    """The training rows of the two warm-up episodes are not part of the story; the app does not read them."""
    (out / "metrics.jsonl").unlink(missing_ok=True)
    meta = json.loads((out / "episode.json").read_text(encoding="utf-8"))
    meta["files"] = [f for f in meta["files"] if f != "metrics.jsonl"]
    (out / "episode.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="fixture-"))
    try:
        run_dir = work / "run"
        trained = train.main(
            ["--scenario", SCENARIO, "--episodes", "2", "--max-ticks", "8", "--run-dir", str(run_dir),
             "--seed", "3", "--no-system2", "--train-steps", "20"],
            transport=FakeD1(fixture_system1),
        )
        if trained != 0:
            return trained
        config = work / "configuration.json"
        default_configuration().with_bounds(
            system2_cadence=8, trial_decisions=8, cooling_decisions=8, history_test_sample=12, history_test_noise=2,
            window_recent=8, window_long=40, safety_followed=40,
        ).save(config)
        fake = FakeD1(fixture_system1, system2_policy=fixture_system2())
        fake.fail("navigation", [3], "raise").fail("central", [5], "off_menu")
        out = OUT / NAME
        meta = export.record_bundle(
            scenario=SCENARIO, seed=SEED, out=out, networks="latest", run_dir=run_dir, max_ticks=MAX_TICKS,
            transport=fake, api_key="liquid_test_key", configuration_path=config, name=NAME,
            title="deadly corridor on the fake d1-ultra (test fixture)",
        )
        trim(out)
        problems = export.check_bundle(out)
        export.write_index(OUT)
        size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
        print(
            f"{out}: {meta.tick_count} ticks, configuration {meta.configuration_start.version} -> "
            f"{meta.configuration_end.version}, {meta.system2.cycles} cycles, {meta.system2.tests} tests, "
            f"{meta.system2.trials_judged} judged, {meta.misses.total} misses, {size / 1e6:.2f} MB",
        )
        for problem in problems:
            print("problem:", problem)
        return 1 if problems else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
