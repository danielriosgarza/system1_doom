"""System 2: its cadence, the reflectors' scopes and criteria, System 2's central, one change per cycle, the
trial and its verdicts, the safety bound, exact reverts, misses, ties, the call bound and its saved state,
on a synthetic history with the fake d1-ultra, then end to end on ViZDoom."""

import re
import threading
from pathlib import Path
from typing import Callable, List, Optional

import pytest

from system1_doom.actions import ActionVocabulary
from system1_doom.admission import AdmissionDecisionResult
from system1_doom.archive import StrategyArchive
from system1_doom.configuration import Configuration
from system1_doom.controller import ControllerConfig, DoomDecisionController
from system1_doom.d1_client import D1UltraClient
from system1_doom.evidence import StrategyLine
from system1_doom.history import HistoryStore
from system1_doom.history_channels import HISTORY_CHANNELS
from system1_doom.logger import DecisionLogger
from system1_doom.reflection import ReflectionTrace, System2Note, TrialVerdictTrace, load_reflections
from system1_doom.reflectors import REFLECTORS, apply_change, change_option, config_diff
from system1_doom.system2 import System2
from system1_doom.vizdoom_env import ViZDoomBridge
from tests.fake_d1 import (
    SYSTEM2_CENTRAL,
    TRIAL_JUDGE,
    FakeD1,
    default_system2_policy,
    is_system2,
    judge,
    reflector_answer,
    survival_until_pickups,
)
from tests.system2_fixtures import CONFIG, make_record

CONTEXTS = tuple(f"ctx_{c}" for c in "abcdefg")
MACRO = ActionVocabulary.default().get("weave_fire").model_copy(update={"id": "zigzag_fire"})
SPECS = {spec.name: spec for spec in REFLECTORS}


class FakeHost:
    """What System 2 reads from the controller, with the tick boundary played by hand (`boundary`)."""

    def __init__(self, tmp_path: Path, fake: FakeD1, configuration: Configuration = CONFIG, slow_path: bool = False, state: Optional[Path] = None):
        self.configuration = configuration
        self.history = HistoryStore(None, ring=2000)
        self.logger = DecisionLogger(tmp_path / "logs")
        self.slow_client = D1UltraClient(api_key="liquid_test_key", transport=fake, max_workers=2)
        self.episode_id = "a"
        self.pending: Optional[Configuration] = None
        self.slow_path = slow_path
        self.expansions: List[tuple] = []
        self.system2 = System2(self, seed=3, state_path=state)
        self.system2.begin()

    def next_configuration(self) -> Configuration:
        return self.pending or self.configuration

    def request_configuration(self, configuration: Configuration) -> None:
        self.pending = configuration

    def request_expansion(self, source: str, description: str) -> bool:
        self.expansions.append((source, description))
        return self.slow_path

    def slow_path_available(self) -> bool:
        return self.slow_path

    def archive_lines(self) -> List[StrategyLine]:
        return [
            StrategyLine(strategy_id=e.strategy_id, action_sequence=e.action_sequence, observed_reward=e.observed_reward,
                         success_rate=e.success_rate, usage_count=e.usage_count)
            for e in StrategyArchive().entries()
        ]

    def boundary(self) -> None:
        if self.pending is not None:
            old, self.configuration, self.pending = self.configuration, self.pending, None
            self.system2.on_configuration_applied(old, self.configuration)

    def close(self) -> None:
        self.system2.shutdown(wait_sec=10)
        self.slow_client.shutdown(wait=False)


def negative(t: int) -> float:
    return -1.0 - (t % 7) * 0.5


def positive(t: int) -> float:
    return 1.0 + (t % 7) * 0.5


def play(host: FakeHost, episode_id: str, n: int, start: int = 0, *, reward: Callable[[int], float] = negative, survival: bool = True) -> None:
    """`n` ticks: each starts at a boundary, is stored under the configuration in play, and System 2 is told.
    With `survival`, the survival sense speaks for strafe_left and is followed."""
    host.episode_id = episode_id
    for t in range(start, start + n):
        host.boundary()
        record = make_record(
            episode_id, t, reward(t), executed="strafe_left", spoken={"survival": ("strafe_left", 0.9)} if survival else None,
            context=CONTEXTS[t % len(CONTEXTS)], config=host.configuration,
        )
        host.history.append(record)
        host.system2.on_tick(record)
        assert host.system2.wait_idle(20)


def end(host: FakeHost, episode_id: str) -> None:
    host.system2.on_episode_end(episode_id)
    assert host.system2.wait_idle(20)


def cycles(host: FakeHost) -> List[ReflectionTrace]:
    return [r for r in host.system2.records if isinstance(r, ReflectionTrace)]


def verdicts(host: FakeHost) -> List[TrialVerdictTrace]:
    return [r for r in host.system2.records if isinstance(r, TrialVerdictTrace)]


def notes(host: FakeHost, kind: str) -> List[System2Note]:
    return [r for r in host.system2.records if isinstance(r, System2Note) and r.kind == kind]


def headers(state: str) -> List[str]:
    return re.findall(r"^\[([^\]]+)\]$", state, flags=re.M)


def s2_policy(**answers):
    """The default System 2 policy, with some instances' answers replaced: name -> fn(payload)."""

    def policy(name, payload):
        if name in answers:
            return answers[name](payload)
        return default_system2_policy(name, payload)

    return policy


@pytest.fixture
def hosts(tmp_path):
    made: List[FakeHost] = []

    def make(fake: FakeD1, **kwargs) -> FakeHost:
        host = FakeHost(tmp_path / f"h{len(made)}", fake, **kwargs)
        made.append(host)
        return host

    yield make
    for host in made:
        host.close()


def test_a_cycle_every_20_decisions_or_at_episode_end_and_none_while_a_trial_is_in_flight(hosts):
    fake = FakeD1(survival_until_pickups)
    host = hosts(fake)
    play(host, "a", 19)
    assert cycles(host) == []
    play(host, "a", 1, start=19)
    (first,) = cycles(host)
    assert (first.trigger, first.decision, first.outcome) == ("decisions", 20, "test_waiting")
    assert [m.change for m in first.messages] == ["widen:survival:pickups"] and first.choice == "widen:survival:pickups"
    assert first.history_test.status == "waiting" and first.history_test.candidates == 20 and host.pending is None
    play(host, "a", 10, start=20)
    assert len(cycles(host)) == 1  # 30 decisions: the next cadence mark is 40
    end(host, "a")
    second = cycles(host)[1]
    assert (second.trigger, second.outcome) == ("episode_end", "queued") and second.history_test.passed
    assert second.history_test.old.composite == pytest.approx(1 / 3, abs=1e-6) and second.history_test.new.composite == pytest.approx(2 / 3, abs=1e-6)
    assert second.applied.diff.changes == ("survival scope: + pickups",)
    # Queued, not in play: it takes effect at the next tick boundary, as the trial.
    assert host.pending.version == 2 and host.configuration.version == 1
    play(host, "b", 1, reward=positive, survival=False)
    assert host.configuration.version == 2 and len(notes(host, "trial_started")) == 1
    # No cycle while the trial is in flight, through cadence marks and an episode end.
    play(host, "b", 40, start=1, reward=positive, survival=False)
    end(host, "b")
    play(host, "c", 18, reward=positive, survival=False)
    assert len(cycles(host)) == 2 and verdicts(host) == [] and fake.count(TRIAL_JUDGE) == 0
    play(host, "c", 1, start=18, reward=positive, survival=False)
    (verdict,) = verdicts(host)
    assert verdict.cycle_id == second.cycle_id and verdict.trial.verdict == "keep" and not verdict.trial.safety_revert
    assert verdict.trial.table.during.decisions == 60 and verdict.trial.table.before.decisions == 30
    assert verdict.trial.table.before.paid_off_rate == 0.0 and "survival's followed messages" in verdict.trial.table.text
    assert "the history test predicted: composite 0.33 under the old scope, 0.67 under the new" in verdict.trial.table.text
    assert fake.count(TRIAL_JUDGE) == 1 and host.configuration.version == 2 and host.pending is None
    # The survival sense then rests 60 decisions: its auditor is not called in the next cycle.
    third = cycles(host)[2]
    assert "survival_auditor" in third.skipped and "cooling: survival rests" in third.skipped["survival_auditor"]
    log = host.system2.status().change_log
    assert [(e.version, e.change, e.by, e.status) for e in log] == [(2, "widen:survival:pickups", "system 2", "kept")]


def test_each_reflector_sees_only_its_history_channels_and_the_central_its_three(hosts):
    fake = FakeD1(survival_until_pickups)
    host = hosts(fake)
    play(host, "a", 20)
    (cycle,) = cycles(host)
    assert set(cycle.reflectors) == set(SPECS) - {"menu_reflector"} and "menu_reflector" in cycle.skipped
    for name, result in cycle.reflectors.items():
        (payload,) = fake.payloads(name)
        assert headers(payload["state"]) == [c for c in HISTORY_CHANNELS if c in SPECS[name].scope], name
        assert payload["state"] == result.evidence and "images" not in payload
        assert list(payload["questions"]) == ["speak", "change", "reason"]
        assert list(payload["questions"]["change"]["criteria"]) == cycle.offered[name]
        assert list(payload["questions"]["reason"]["criteria"]) == list(SPECS[name].reasons)
    (central,) = fake.payloads(SYSTEM2_CENTRAL)
    assert headers(central["state"]) == ["messages", "h_outcomes", "h_config"]  # in channel order
    assert list(central["questions"]) == ["configure"]
    assert central["questions"]["configure"]["instructions"].endswith("Choose the one configuration change to make now, or none.")
    assert list(central["questions"]["configure"]["criteria"]) == cycle.central_criteria == ["widen:survival:pickups", "none"]
    assert "survival auditor proposes widen:survival:pickups" in central["state"]


def test_the_centrals_criteria_are_the_proposals_the_bounds_still_allow_and_none(hosts):
    # Combat already shows 7 channels, the bound: no widen of combat is offered, and an answer naming one is a miss.
    full = apply_change(CONFIG, change_option("widen:combat:pickups", CONFIG)).replace(version=1)
    holder = {}

    def menu(payload):
        holder["host"].slow_path = False  # the slow path became busy after the menu reflector was asked
        return reflector_answer(payload, 0.9, "macro:combat", "no_fitting_action")

    def combat(payload):
        answers = reflector_answer(payload, 0.9, "keep", "missing_evidence")
        answers["change"] = {"type": "choice", "choice": "widen:combat:geometry", "probabilities": {"widen:combat:geometry": 1.0}}
        return answers

    fake = FakeD1(survival_until_pickups, system2_policy=s2_policy(
        menu_reflector=menu, combat_auditor=combat,
        exploration_reflector=lambda p: reflector_answer(p, 0.8, "level:explore", "stuck_or_repeating"),
    ))
    host = hosts(fake, configuration=full, slow_path=True)
    holder["host"] = host
    play(host, "a", 20)
    (cycle,) = cycles(host)
    assert not any(o.startswith("widen:combat:") for o in cycle.offered["combat_auditor"])
    assert all(r.startswith("scope size") for c, r in cycle.blocked["combat_auditor"].items() if c.startswith("widen:"))
    assert cycle.reflectors["combat_auditor"].missed and cycle.reflectors["combat_auditor"].miss_reason == "off_menu"
    assert [m.change for m in cycle.messages] == ["widen:survival:pickups", "macro:combat", "level:explore"]
    assert cycle.central_criteria == ["widen:survival:pickups", "level:explore", "none"]
    assert any("macro:combat was proposed but the bounds no longer allow it" in n for n in cycle.notes)


def test_one_change_per_cycle_queued_for_the_tick_boundary(hosts):
    def choose_level(payload):
        criteria = list(payload["questions"]["configure"]["criteria"])
        assert criteria == ["widen:survival:pickups", "strategy:strat_corridor_advance", "level:explore", "none"]
        return {"configure": {"type": "choice", "choice": "level:explore", "probabilities": {c: (0.7 if c == "level:explore" else 0.1) for c in criteria}}}

    fake = FakeD1(survival_until_pickups, system2_policy=s2_policy(**{
        SYSTEM2_CENTRAL: choose_level,
        "strategy_reflector": lambda p: reflector_answer(p, 0.7, "strategy:strat_corridor_advance", "strategy_failing"),
        "exploration_reflector": lambda p: reflector_answer(p, 0.8, "level:explore", "stuck_or_repeating"),
    }))
    host = hosts(fake)
    play(host, "a", 20)
    (cycle,) = cycles(host)
    assert len(cycle.messages) == 3 and cycle.outcome == "queued" and cycle.history_test is None
    assert cycle.applied.change == "level:explore" and cycle.applied.queued and cycle.calls == 8 + 1
    assert config_diff(host.configuration, host.pending).changes == ("exploration level: exploit -> explore",)
    assert host.configuration.exploration_level == "exploit"  # nothing changes before the boundary


def _level_trial(hosts, verdict: str, judge_faults=(), state=None):
    fake = FakeD1(survival_until_pickups, system2_policy=s2_policy(**{
        SYSTEM2_CENTRAL: lambda p: {"configure": {"type": "choice", "choice": "level:explore", "probabilities": {
            c: (0.7 if c == "level:explore" else 0.3 / (len(p["questions"]["configure"]["criteria"]) - 1)) for c in p["questions"]["configure"]["criteria"]}}},
        "exploration_reflector": lambda p: reflector_answer(p, 0.8, "level:explore", "stuck_or_repeating"),
        TRIAL_JUDGE: lambda p: judge(p, verdict),
    }))
    for index in judge_faults:
        fake.fail(TRIAL_JUDGE, [index], "raise")
    host = hosts(fake, state=state)
    play(host, "a", 20)
    play(host, "a", 1, start=20)  # the boundary: the level change takes effect
    assert host.configuration.exploration_level == "explore" and host.configuration.version == 2
    play(host, "a", 59, start=21)
    return host, fake


def test_the_judge_keeps_a_change_after_60_decisions(hosts):
    host, fake = _level_trial(hosts, "keep")
    (verdict,) = verdicts(host)
    assert verdict.trial.verdict == "keep" and verdict.trial.kind == "level" and verdict.trial.revert is None
    assert verdict.trial.table.instance is None and "no history test: not a scope change" in verdict.trial.table.text
    assert verdict.calls == 1 and host.pending is None and host.configuration.exploration_level == "explore"


def test_a_revert_restores_the_previous_configuration_exactly_with_the_version_bumped(hosts):
    host, fake = _level_trial(hosts, "revert")
    (verdict,) = verdicts(host)
    assert verdict.trial.verdict == "revert" and not verdict.trial.safety_revert
    restored = host.pending
    assert restored.version == 3 and restored.model_dump(exclude={"version"}) == CONFIG.model_dump(exclude={"version"})
    assert verdict.trial.revert.model_dump() == {"old_version": 2, "new_version": 3, "changes": ("exploration level: explore -> exploit",)}
    play(host, "a", 1, start=80)
    assert host.configuration == restored and len(notes(host, "revert_applied")) == 1
    log = host.system2.status().change_log
    assert [(e.version, e.change, e.by, e.status) for e in log] == [
        (2, "level:explore", "system 2", "reverted"),
        (3, "revert:level:explore", "revert", "applied"),
    ]
    # After a level change System 2 as a whole rests: the next cycle calls no one.
    play(host, "a", 20, start=81)
    last = cycles(host)[-1]
    assert last.calls == 0 and last.outcome == "no_proposal" and set(last.skipped) == set(SPECS)
    assert all("System 2 as a whole" in why for name, why in last.skipped.items() if name != "menu_reflector")


def test_a_revert_not_yet_in_play_when_the_run_ends_is_queued_again_on_restore(tmp_path, hosts):
    state = tmp_path / "system2.json"
    host, _ = _level_trial(hosts, "revert", state=state)
    assert host.pending.version == 3
    host.system2.shutdown(wait_sec=10)  # the run ends before the next tick boundary
    again = hosts(FakeD1(survival_until_pickups), configuration=host.configuration, state=state)
    assert "revert:level:explore had not taken effect and is queued again" in notes(again, "restored")[0].detail
    assert again.pending.version == 3 and again.pending.model_dump(exclude={"version"}) == CONFIG.model_dump(exclude={"version"})
    play(again, "z", 1)
    assert again.configuration.exploration_level == "exploit" and len(notes(again, "revert_applied")) == 1


def test_a_missed_judge_extends_the_trial_by_20_decisions_and_asks_again(hosts):
    host, fake = _level_trial(hosts, "keep", judge_faults=(0,))
    assert verdicts(host) == [] and len(notes(host, "judge_missed")) == 1 and "extended by 20 decisions to 80" in notes(host, "judge_missed")[0].detail
    play(host, "a", 19, start=80)
    assert verdicts(host) == []
    play(host, "a", 1, start=99)
    (verdict,) = verdicts(host)
    assert verdict.trial.extensions == 1 and [r.missed for r in verdict.trial.judge] == [True, False]
    assert verdict.trial.table.during.decisions == 80 and verdict.calls == 2


def test_the_safety_bound_reverts_a_scope_change_without_asking(hosts):
    always = lambda p: reflector_answer(p, 0.9, "widen:survival:pickups", "missing_evidence")  # noqa: E731
    fake = FakeD1(survival_until_pickups, system2_policy=s2_policy(survival_auditor=always))
    host = hosts(fake)
    play(host, "a", 30, reward=positive)  # survival followed, and it paid off every time
    end(host, "a")
    assert cycles(host)[-1].outcome == "queued"
    # Under the change survival is still followed, and it never pays off: after 10 followed messages whose
    # returns are complete (17 decisions: a return needs its 8 rewards), the safety bound reverts without asking the judge.
    play(host, "b", 16)
    assert verdicts(host) == []
    play(host, "b", 1, start=16)
    (verdict,) = verdicts(host)
    assert verdict.trial.safety_revert and verdict.trial.verdict == "revert" and verdict.trial.judge == []
    assert fake.count(TRIAL_JUDGE) == 0 and "safety bound: survival's paid-off rate fell from 1.00 to 0.00" in verdict.trial.table.text
    assert host.pending.version == 3 and host.pending.senses["survival"].scope == CONFIG.senses["survival"].scope
    assert host.system2.status().verdicts[-1].by == "the safety bound"
    play(host, "b", 1, start=17)
    assert host.system2.status().change_log[-1].by == "safety revert"


def test_a_missed_central_changes_nothing_and_a_tie_goes_to_the_first_option(hosts):
    fake = FakeD1(survival_until_pickups).fail(SYSTEM2_CENTRAL, [0], "raise")
    host = hosts(fake)
    play(host, "a", 20)
    (missed,) = cycles(host)
    assert missed.outcome == "central_missed" and missed.central.missed and missed.choice is None and host.pending is None
    assert any("System 2's central missed (error); no change this cycle" in n for n in missed.notes)

    def tie(payload):
        criteria = list(payload["questions"]["configure"]["criteria"])
        return {"configure": {"type": "choice", "choice": criteria[1], "probabilities": {c: 1 / len(criteria) for c in criteria}}}

    fake = FakeD1(survival_until_pickups, system2_policy=s2_policy(**{SYSTEM2_CENTRAL: tie}))
    host = hosts(fake)
    play(host, "a", 20)
    (tied,) = cycles(host)
    assert tied.tie and tied.tied == ["widen:survival:pickups", "none"] and tied.choice == "widen:survival:pickups"
    assert any(n.startswith("tie between widen:survival:pickups, none") for n in tied.notes)


def test_the_calls_of_a_cycle_are_counted_and_kept_under_the_bound(hosts):
    fake = FakeD1(survival_until_pickups)
    host = hosts(fake)
    play(host, "a", 30)
    end(host, "a")
    cycle = cycles(host)[-1]
    system2_calls = sum(fake.count(name) for name in {n for n, _ in fake.calls if is_system2(n)})
    assert cycle.calls == 8 + 1 + 28 <= CONFIG.bounds.system2_calls_per_cycle
    assert cycles(host)[0].calls + cycle.calls == system2_calls + 28
    assert host.slow_client.counters()["history_test:survival"].calls == 28
    # A tighter bound leaves too few calls for the test: the change waits, and nothing is called past the bound.
    tight = CONFIG.with_bounds(system2_calls_per_cycle=30)
    fake = FakeD1(survival_until_pickups)
    host = hosts(fake, configuration=tight)
    play(host, "a", 30)
    end(host, "a")
    cycle = cycles(host)[-1]
    assert cycle.outcome == "test_waiting" and cycle.calls == 9 and cycle.history_test is None
    assert any("needs 28 calls and the cycle's bound leaves 21" in n for n in cycle.notes)


def test_a_macro_request_goes_to_the_slow_path_and_a_reverted_macro_is_retired(hosts):
    fake = FakeD1(survival_until_pickups, system2_policy=s2_policy(**{
        "menu_reflector": lambda p: reflector_answer(p, 0.9, "macro:combat", "no_fitting_action"),
        TRIAL_JUDGE: lambda p: judge(p, "revert"),
    }))
    host = hosts(fake, slow_path=True)
    play(host, "a", 20, reward=positive)  # survival pays off: only the menu reflector proposes
    (cycle,) = cycles(host)
    assert cycle.outcome == "macro_requested" and cycle.choice == "macro:combat" and cycle.applied.diff is None
    ((source, description),) = host.expansions
    assert source == "combat" and "winning the current fight" in description and "no fitting action" in description
    # The admit instance rejects it: nothing changes, and cycles resume.
    host.system2.on_proposal(AdmissionDecisionResult(admitted=False, raw_proposal="{}", rejection_reason="sandbox: no progress", source_module="combat"))
    assert notes(host, "macro_rejected") and host.system2.status().pending is None
    play(host, "a", 20, start=20, reward=positive)
    assert cycles(host)[-1].outcome == "macro_requested"
    # Admitted: the controller queues it, it takes effect at the boundary, and it is the trial.
    host.system2.on_proposal(AdmissionDecisionResult(admitted=True, raw_proposal="{}", admitted_action_id="zigzag_fire", admitted_action=MACRO, source_module="combat"))
    host.request_configuration(host.configuration.with_changes(admitted_macros=[MACRO.model_dump()]))
    play(host, "a", 60, start=40, reward=positive)
    (verdict,) = verdicts(host)
    assert verdict.trial.kind == "macro" and verdict.trial.detail == "admitted as zigzag_fire" and verdict.trial.verdict == "revert"
    assert host.pending.admitted_macros == () and verdict.trial.revert.changes == ("admitted macros: - zigzag_fire",)


def test_system2_state_is_saved_and_restored_only_onto_the_configuration_it_was_saved_with(tmp_path, hosts):
    state = tmp_path / "system2.json"
    fake = FakeD1(survival_until_pickups)
    host = hosts(fake, state=state)
    play(host, "a", 30)
    end(host, "a")
    play(host, "b", 5, reward=positive, survival=False)  # the trial is 5 decisions in
    host.system2.shutdown(wait_sec=10)
    assert state.is_file()
    again = hosts(FakeD1(survival_until_pickups), configuration=host.configuration, state=state)
    (note,) = notes(again, "restored")
    assert "at 35 decisions, 2 cycles; trial of widen:survival:pickups continues" in note.detail
    assert again.system2.status().trial.observed == 5 and again.system2.status().decisions == 35
    fresh = hosts(FakeD1(survival_until_pickups), configuration=CONFIG, state=state)
    assert notes(fresh, "fresh_start") and fresh.system2.status().trial is None
    # Every record in reflections.jsonl reads back as the record it was.
    records = load_reflections((tmp_path / "h0" / "logs" / "reflections.jsonl").read_text())
    assert [r.record for r in records] == [r.record for r in host.system2.records]


# ---------------------------------------------------------------------------------------------------
# End to end on ViZDoom.


def test_end_to_end_a_widen_is_tested_applied_at_a_tick_boundary_and_kept(tmp_path):
    fake = FakeD1(survival_until_pickups)
    env = ViZDoomBridge(scenario="basic.cfg", window_visible=False, seed=11)
    cfg = ControllerConfig(
        log_dir=str(tmp_path / "logs"), enable_slow_llm=False, enable_system2=True,
        configuration_out=str(tmp_path / "run" / "configuration.json"), system2_state_path=str(tmp_path / "run" / "system2.json"),
    )
    ctrl = DoomDecisionController(env=env, config=cfg, api_key="liquid_test_key", transport=fake)
    traces = []
    try:
        for _ in range(25):
            result = ctrl.run_episode(max_ticks=200, on_tick=lambda t: not ctrl.wait_system2(30))
            traces += result["traces"]
            assert ctrl.wait_system2(30)
            if any(isinstance(r, TrialVerdictTrace) for r in ctrl.system2.records):
                break
    finally:
        ctrl.close()
    records = ctrl.system2.records
    cycle_records = [r for r in records if isinstance(r, ReflectionTrace)]
    queued = next(r for r in cycle_records if r.outcome == "queued")
    assert queued.choice == "widen:survival:pickups" and queued.history_test.passed and queued.calls <= 40
    assert all(r.outcome == "test_waiting" for r in cycle_records[: cycle_records.index(queued)])
    # The change took effect at one tick boundary: the tick after the cycle queued it.
    changed = [i for i, t in enumerate(traces) if t.configuration_changed]
    (first,) = changed
    assert traces[first - 1].configuration_version == 1 and traces[first].configuration_version == 2
    assert "[pickups]" not in traces[first - 1].instances["survival"].evidence
    assert "[pickups]" in traces[first].instances["survival"].evidence
    assert all(t.configuration_version == 2 for t in traces[first:])
    # Judged 60 decisions later, and kept.
    (verdict,) = [r for r in records if isinstance(r, TrialVerdictTrace)]
    assert verdict.trial.verdict == "keep" and verdict.trial.table.during.decisions == 60
    assert verdict.trial.judged_decision == verdict.trial.started_decision + 60
    assert ctrl.configuration.version == 2
    assert Configuration.load(tmp_path / "run" / "configuration.json").version == 2
    assert (tmp_path / "run" / "system2.json").is_file()
    logged = load_reflections((tmp_path / "logs" / "reflections.jsonl").read_text())
    assert [r.record for r in logged] == [r.record for r in records]
    assert not any(t.slow_path_request for t in traces)


def test_end_to_end_served_bundles_carry_the_cycles_and_the_last_ends_at_configuration_version_2(tmp_path):
    from system1_doom import export, serve

    stop = threading.Event()

    class UntilTheVerdict(serve.LiveHub):
        def add_reflection(self, record):
            super().add_reflection(record)
            if record.record == "verdict":
                stop.set()

    config = serve.ServeConfig(
        scenario="basic.cfg", seed=11, run_dir=tmp_path / "run", max_ticks=200, episodes=25, pace=0.0, rest=0.0,
        slow_path=False, out=tmp_path / "live", transport=FakeD1(survival_until_pickups), api_key="liquid_test_key",
    )
    serve.prepare_live_dir(config.out)
    serve.play(config, UntilTheVerdict(config), stop)
    bundles = sorted(config.out.iterdir(), key=lambda p: int(p.name.split("-")[1]))
    metas = [export.EpisodeMeta.model_validate_json((b / "episode.json").read_text()) for b in bundles]
    assert stop.is_set() and len(bundles) < 25
    for bundle in bundles:
        assert export.check_bundle(bundle) == [], bundle.name
    assert metas[0].configuration_start.version == 1 and metas[-1].configuration_end.version == 2
    records = [r for b in bundles for r in load_reflections((b / "reflections.jsonl").read_text())]
    queued = [r for r in records if isinstance(r, ReflectionTrace) and r.outcome == "queued"]
    assert [r.choice for r in queued] == ["widen:survival:pickups"] and queued[0].history_test.passed
    (verdict,) = [r for r in records if isinstance(r, TrialVerdictTrace)]
    assert verdict.cycle_id == queued[0].cycle_id and verdict.trial.verdict == "keep"
    assert sum(m.system2.trials_started for m in metas) == 1 and sum(m.system2.kept for m in metas) == 1
    assert Configuration.load(tmp_path / "run" / "configuration.json").version == 2


def test_system2_is_off_unless_asked_for(tmp_path):
    fake = FakeD1(survival_until_pickups)
    env = ViZDoomBridge(scenario="basic.cfg", window_visible=False, seed=11)
    ctrl = DoomDecisionController(env=env, config=ControllerConfig(log_dir=str(tmp_path), enable_slow_llm=False), api_key="k", transport=fake)
    try:
        result = ctrl.run_episode(max_ticks=25)
    finally:
        ctrl.close()
    assert ControllerConfig().enable_system2 is False and ctrl.system2 is None
    assert not any(is_system2(name) for name, _ in fake.calls) and result["system2"]["enabled"] is False


@pytest.mark.live
def test_live_one_system2_cycle_on_a_short_real_history(tmp_path):
    from system1_doom.configuration import default_configuration
    from system1_doom.d1_client import load_api_key

    key = load_api_key()
    if not key:
        pytest.skip("needs LIQUID_API_KEY")
    small = default_configuration().with_bounds(system2_cadence=8, history_test_sample=4, history_test_noise=1, call_budget_sec=15.0)
    env = ViZDoomBridge(scenario="basic.cfg", window_visible=False, seed=5)
    cfg = ControllerConfig(log_dir=str(tmp_path / "logs"), enable_slow_llm=False, enable_system2=True, configuration=small)
    ctrl = DoomDecisionController(env=env, config=cfg, api_key=key)
    try:
        result = ctrl.run_episode(max_ticks=8, on_tick=lambda t: not ctrl.wait_system2(120))
        assert ctrl.wait_system2(120)
    finally:
        ctrl.close()
    # One cycle: at the 8th decision, or at the episode's end when the monster fell sooner.
    (cycle,) = [r for r in ctrl.system2.records if isinstance(r, ReflectionTrace)]
    assert cycle.decision == result["ticks"] and cycle.trigger == ("decisions" if result["ticks"] == 8 else "episode_end")
    assert cycle.reflectors and cycle.calls <= small.bounds.system2_calls_per_cycle
    answered = [n for n, r in cycle.reflectors.items() if not r.missed]
    assert len(answered) >= len(cycle.reflectors) - 1, {n: (r.miss_reason, r.error) for n, r in cycle.reflectors.items()}
    for name in answered:
        result = cycle.reflectors[name]
        assert result.change in cycle.offered[name] and result.reason in SPECS[name].reasons and 0.0 <= result.speak <= 1.0
    if cycle.central is not None:
        assert cycle.central_criteria[-1] == "none" and (cycle.central.missed or cycle.choice in cycle.central_criteria)
    assert cycle.usage.input_tokens > 0
