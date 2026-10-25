"""The controller end to end on ViZDoom with the fake d1-ultra: d1 decides every tick, misses are misses."""

import json
import time
from pathlib import Path

import pytest

from system1_doom.actions import ActionVocabulary
from system1_doom.configuration import CHANNELS, default_configuration
from system1_doom.controller import ControllerConfig, DoomDecisionController, MissingAPIKey
from system1_doom.history import load_history
from system1_doom.learning import Learner
from system1_doom.logger import TickTrace
from system1_doom.motor import STEPS_PER_DECISION
from system1_doom.relevance import load_ledger
from system1_doom.vizdoom_env import ViZDoomBridge
from tests.fake_d1 import FakeD1, default_policy, shoot_when_aimed, spread_central

INSTANCES = ["survival", "combat", "navigation", "resource", "goal", "central"]


def _controller(tmp_path: Path, fake: FakeD1, scenario: str = "basic.cfg", seed: int = 11, **config) -> DoomDecisionController:
    env = ViZDoomBridge(scenario=scenario, window_visible=False, seed=seed)
    cfg = ControllerConfig(log_dir=str(tmp_path / "logs"), enable_slow_llm=False, **config)
    return DoomDecisionController(env=env, config=cfg, api_key="liquid_test_key", transport=fake)


def _play(tmp_path: Path, fake: FakeD1, max_ticks: int, scenario: str = "basic.cfg", learner=None, **config) -> dict:
    env = ViZDoomBridge(scenario=scenario, window_visible=False, seed=11)
    cfg = ControllerConfig(log_dir=str(tmp_path / "logs"), enable_slow_llm=False, record_experience=learner is not None, **config)
    ctrl = DoomDecisionController(env=env, config=cfg, api_key="liquid_test_key", transport=fake, learner=learner)
    try:
        return ctrl.run_episode(max_ticks=max_ticks)
    finally:
        ctrl.close()


def test_every_executed_action_is_the_centrals_pick_and_every_tick_records_six_instances(tmp_path):
    fake = FakeD1(default_policy)
    result = _play(tmp_path, fake, max_ticks=8, scenario="deadly_corridor.cfg")
    traces = result["traces"]
    assert len(traces) == 8 and result["finished_reason"] == "max_ticks"
    central_payloads = fake.payloads("central")
    for i, trace in enumerate(traces):
        assert list(trace.instances) == INSTANCES
        assert trace.pick.kind == "top" and trace.executed_action == trace.pick.action == trace.instances["central"].action
        assert trace.executed_action in trace.available_actions
        assert trace.configuration_version == 1 and trace.exploration_level == "exploit"
        for name, instance in trace.instances.items():
            assert instance.evidence and set(instance.scope) <= set(CHANNELS) and not instance.missed, name
            # What the trace says the instance saw is exactly what the API received.
            assert fake.payloads(name)[i]["state"] == instance.evidence, name
        assert central_payloads[i]["state"] == trace.instances["central"].evidence
        assert [m.sense for m in trace.messages] == [n for n in INSTANCES[:5] if trace.instances[n].spoke]
        assert trace.usage.input_tokens == sum(r.usage.input_tokens for r in trace.instances.values())
    lines = (tmp_path / "logs" / "ticks.jsonl").read_text().splitlines()
    assert [TickTrace.model_validate_json(line).tick for line in lines] == [t.tick for t in traces]
    history = load_history(tmp_path / "logs" / "history.jsonl")
    assert [r.tick for r in history] == [t.tick for t in traces]
    assert result["cost"]["calls"] == 6 * 8 and result["misses"] == {"total": 0, "missed_ticks": 0, "by_instance": {}}
    assert result["actions"] == [t.executed_action for t in traces]


def test_a_fake_that_shoots_when_aimed_clears_basic(tmp_path):
    result = _play(tmp_path, FakeD1(shoot_when_aimed), max_ticks=40)
    assert result["cleared"] and result["kills"] >= 1, {k: v for k, v in result.items() if k != "traces"}
    assert result["finished_reason"] == "episode_end"
    assert "shoot" in result["actions"] or any("shoot" in a for a in result["actions"])


def test_a_scripted_outage_yields_missed_ticks_then_connection_lost(tmp_path):
    fake = FakeD1(default_policy, timeout_overrun=0.05).fail("central", [2, 3, 4], "raise")
    result = _play(tmp_path, fake, max_ticks=20, scenario="deadly_corridor.cfg")
    traces = result["traces"]
    assert result["finished_reason"] == "connection_lost" and len(traces) == 5
    assert [t.missed for t in traces] == [False, False, True, True, True]
    for trace in traces[2:]:
        assert trace.pick.kind == "missed" and trace.executed_action is None
        assert trace.instances["central"].miss_reason == "error"
        # No keys for the decision's 8 frames: 4 reflex steps of 2 frames, each pressing nothing.
        assert trace.primitive_steps_executed == ["idle"] * 4
    assert result["misses"]["missed_ticks"] == 3 and result["misses"]["by_instance"] == {"central": {"error": 3}}
    assert result["actions"][2:] == ["missed"] * 3


def test_isolated_central_misses_do_not_end_the_episode(tmp_path):
    fake = FakeD1(default_policy).fail("central", [1, 3], "malformed").fail("survival", [0, 1, 2, 3], "raise")
    result = _play(tmp_path, fake, max_ticks=6, scenario="deadly_corridor.cfg")
    assert result["finished_reason"] == "max_ticks" and [t.missed for t in result["traces"]] == [False, True, False, True, False, False]
    # A missed sense is silent: the tick goes on without it.
    assert all(t.instances["survival"].missed for t in result["traces"][:4])
    assert result["misses"]["by_instance"] == {"central": {"malformed": 2}, "survival": {"error": 4}}


def test_every_executed_step_follows_the_picked_actions_plan(tmp_path):
    vocab = ActionVocabulary.default()
    result = _play(tmp_path, FakeD1(default_policy), max_ticks=12, scenario="deadly_corridor.cfg")
    for trace in result["traces"]:
        plan = vocab.get(trace.executed_action).primitive_expansion
        hold = max(1, STEPS_PER_DECISION // len(plan))
        for i, step in enumerate(trace.primitive_steps_executed):
            pressed = set(step.split("+"))
            planned = plan[i // hold]
            if planned == "shoot":
                # Aiming at the locked target stands in for the shot until it is centred.
                assert pressed <= {"shoot", "turn_left", "turn_right", "strafe_left", "strafe_right"}
            elif planned.endswith("_shoot"):
                assert planned[: -len("_shoot")] in pressed, (trace.executed_action, i, step)
            else:
                assert planned in pressed, (trace.executed_action, i, step)


def test_the_value_networks_learn_from_what_d1_played_and_are_shown_as_evidence(tmp_path):
    learner = Learner()
    result = _play(tmp_path, FakeD1(default_policy), max_ticks=6, scenario="health_gathering.cfg", learner=learner)
    assert result["transitions"] == result["ticks"] == learner.replay.size > 0
    assert sum(learner.action_counts.values()) == result["ticks"]
    goal = result["traces"][0].instances["goal"].evidence
    assert "[values]\nlearned from past play" in goal and "tried 0 here" in goal
    no_networks = _play(tmp_path / "plain", FakeD1(default_policy), max_ticks=1, scenario="health_gathering.cfg")
    assert "[values]\nno value networks are loaded" in no_networks["traces"][0].instances["goal"].evidence


def test_the_relevance_ledger_updates_at_episode_end_and_is_restored(tmp_path):
    path = tmp_path / "runs" / "basic" / "relevance.json"
    first = _play(tmp_path, FakeD1(shoot_when_aimed), max_ticks=40, relevance_path=str(path))
    ledger = load_ledger(path)
    spoke = sum(len(t.messages) for t in first["traces"] if not t.missed)
    assert ledger.episodes == 1 and sum(c.spoke for c in ledger.entries.values()) == spoke > 0
    assert all(key.split("|", 1)[0] == "combat" for key in ledger.entries)
    ctrl = _controller(tmp_path / "second", FakeD1(shoot_when_aimed), relevance_path=str(path))
    try:
        assert ctrl.ledger == ledger
        trace = ctrl.step()
        context = trace.context_signature
        record = ledger.record("combat", context)
        relevance = trace.instances["central"].evidence.split("[relevance]\n", 1)[1]
        assert ("combat here: spoke" in relevance) == (record is not None and record.spoke > 0)
    finally:
        ctrl.close()


def test_a_pending_configuration_applies_only_at_the_tick_boundary(tmp_path):
    fake = FakeD1(spread_central)
    ctrl = _controller(tmp_path, fake, scenario="deadly_corridor.cfg", seed=5)
    try:
        before = ctrl.step()
        ctrl.request_configuration(ctrl.configuration.with_changes(exploration_level="explore"))
        assert ctrl.configuration.version == 1, "nothing changes until the next tick starts"
        after = ctrl.step()
        again = ctrl.step()
    finally:
        ctrl.close()
    assert (before.configuration_version, before.configuration_changed, before.pick.kind) == (1, False, "top")
    assert (after.configuration_version, after.configuration_changed, after.exploration_level) == (2, True, "explore")
    assert after.pick.kind == "drawn" and after.pick.draw is not None
    assert "novelty" in after.instances["central"].scope and "novelty" not in before.instances["central"].scope
    assert again.configuration_changed is False and again.configuration_version == 2


def test_explore_draws_reproduce_with_the_seed(tmp_path):
    explore = default_configuration(exploration_level="explore")

    def picks(seed, folder):
        result = _play(tmp_path / folder, FakeD1(spread_central), max_ticks=5, scenario="deadly_corridor.cfg", configuration=explore, seed=seed)
        return [(t.pick.kind, t.pick.action, t.pick.draw) for t in result["traces"]]

    first, again, other = picks(4, "a"), picks(4, "b"), picks(5, "c")
    assert first == again and all(kind == "drawn" for kind, _, _ in first)
    assert [d for _, _, d in first] != [d for _, _, d in other]


def test_a_macro_the_admit_instance_admits_enters_the_menu_at_the_next_boundary(tmp_path):
    def proposal(req):
        return json.dumps(
            {
                "id": "corridor_blitz_macro",
                "description": "Strafe left, fire, advance forward, and strafe right down the corridor",
                "preconditions": {"min_ammo": 0, "requires_visible_enemy": False},
                "maximum_duration": 4,
                "termination_condition": "corridor_step_complete",
                "primitive_expansion": ["strafe_left", "shoot", "move_forward", "strafe_right"],
                "strategy_id": "strat_corridor_blitz",
            }
        )

    env = ViZDoomBridge(scenario="deadly_corridor.cfg", window_visible=False, seed=11)
    cfg = ControllerConfig(log_dir=str(tmp_path / "logs"), enable_slow_llm=True, use_codex_cli=False)
    fake = FakeD1(default_policy)
    ctrl = DoomDecisionController(env=env, config=cfg, api_key="liquid_test_key", transport=fake, custom_llm_generator=proposal)
    try:
        first = ctrl.step()
        assert ctrl.request_expansion("test", "Need a corridor macro.")
        deadline = time.time() + 5.0
        while ctrl.llm_worker.is_busy() and time.time() < deadline:
            time.sleep(0.01)
        second = ctrl.step()  # drains the admitted proposal and queues the configuration change
        third = ctrl.step()  # the change takes effect at this tick's boundary
    finally:
        ctrl.close()
    assert "corridor_blitz_macro" not in first.available_actions and first.slow_path_request is None
    assert second.slow_path_request is not None and second.configuration_version == 1
    assert "corridor_blitz_macro" not in second.available_actions
    assert third.configuration_changed and third.configuration_version == 2
    assert "corridor_blitz_macro" in third.available_actions
    assert [m.id for m in ctrl.configuration.admitted_macros] == ["corridor_blitz_macro"]
    assert ctrl.archive.get("strat_corridor_blitz") is not None
    (payload,) = fake.payloads("admit")
    assert "corridor_blitz_macro" in payload["state"] and set(payload["questions"]) == {"admit"}
    record = json.loads((tmp_path / "logs" / "proposals.jsonl").read_text().splitlines()[-1])
    assert record["admission_decision"] is True and record["d1_admission_probability"] == 0.8
    assert record["admit_instance"]["answers"]["admit"] == {"type": "noul", "noul": 0.8}
    assert [s["stage"] for s in record["stage_results"]] == ["parse", "legality", "sandbox", "d1", "admit"]


def test_play_needs_the_key(tmp_path):
    env = ViZDoomBridge(scenario="basic.cfg", window_visible=False)
    try:
        with pytest.raises(MissingAPIKey):
            DoomDecisionController(env=env, config=ControllerConfig(log_dir=str(tmp_path)), api_key="")
    finally:
        env.close()


@pytest.mark.live
def test_live_one_tick_with_six_instances_answering(tmp_path):
    from system1_doom.d1_client import load_api_key

    key = load_api_key()
    if not key:
        pytest.skip("needs LIQUID_API_KEY")
    env = ViZDoomBridge(scenario="deadly_corridor.cfg", window_visible=False, seed=7)
    cfg = ControllerConfig(log_dir=str(tmp_path / "logs"), enable_slow_llm=False, call_budget_sec=15.0)
    ctrl = DoomDecisionController(env=env, config=cfg, api_key=key)
    try:
        trace = ctrl.step()
    finally:
        ctrl.close()
    assert list(trace.instances) == INSTANCES
    answered = [name for name, r in trace.instances.items() if not r.missed]
    assert answered == INSTANCES, {n: (r.miss_reason, r.error) for n, r in trace.instances.items()}
    assert trace.pick.kind == "top" and trace.executed_action in trace.available_actions
    assert trace.instances["combat"].image_ref is not None
    assert all(r.usage.input_tokens > 0 for r in trace.instances.values())
