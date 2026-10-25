"""The history store: the ring bound, persistence, and re-rendering a stored tick byte for byte."""

import json

import pytest

from system1_doom.configuration import default_configuration
from system1_doom.d1_client import D1UltraClient
from system1_doom.history import HistoryStore, load_history, make_record, relevance_decisions, rerender, rerender_instance
from system1_doom.system1 import System1
from tests.fake_d1 import FakeD1
from tests.test_evidence import golden_inputs

CONFIG = default_configuration()


@pytest.fixture(scope="module")
def decided():
    fake = FakeD1()
    client = D1UltraClient(api_key="liquid_test_key", transport=fake, max_workers=6)
    s1 = System1(client, pool_size=6, seed=1)
    try:
        yield s1.tick(CONFIG, golden_inputs().model_copy(update={"messages": ()}), frame_b64="QUJD")
    finally:
        s1.shutdown()
        client.shutdown(wait=False)


def _record(result, tick=42, episode_id="ep1", reward=1.0):
    record = make_record(
        result,
        episode_id=episode_id,
        configuration_version=CONFIG.version,
        active_strategy="strat_tactical_combat",
        executed_action=result.pick.action,
        primitives=("shoot",),
        reward=reward,
        done=False,
    )
    return record.model_copy(update={"tick": tick})


def test_a_stored_tick_rerendered_under_its_own_scope_is_byte_for_byte_what_was_seen(decided, tmp_path):
    store = HistoryStore(tmp_path / "history.jsonl")
    store.append(_record(decided))
    for name, result in decided.instances.items():
        assert store.rerender(42, name).text == result.evidence, name
        assert store.rerender(42, name).image_ref == result.image_ref, name
    (loaded,) = load_history(tmp_path / "history.jsonl")
    for name, result in decided.instances.items():
        assert rerender_instance(loaded, name).text == result.evidence, name


def test_a_stored_tick_rerenders_under_any_scope(decided):
    record = _record(decided)
    wider = rerender_instance(record, "survival", CONFIG.senses["survival"].scope + ("pickups",))
    assert "[pickups]\n1 pickup visible" in wider.text and wider.text.startswith(decided.senses["survival"].evidence.split("\n\n")[0])
    assert rerender(record, ("menu",)).text.startswith("[menu]\nthe legal actions now:")


def test_every_tick_is_persisted_and_the_ring_is_bounded(decided, tmp_path):
    path = tmp_path / "logs" / "history.jsonl"
    store = HistoryStore(path, ring=3)
    for tick in range(5):
        store.append(_record(decided, tick=tick))
    assert len(store) == 3 and [r.tick for r in store.records()] == [2, 3, 4]
    assert store.get(0) is None and store.get(4).tick == 4
    with pytest.raises(KeyError):
        store.rerender(0, "central")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5 and store.appended == 5
    first = json.loads(lines[0])
    assert first["tick"] == 0 and set(first["instances"]) == {"survival", "combat", "navigation", "resource", "goal", "central"}
    assert [r.tick for r in load_history(path)] == [0, 1, 2, 3, 4]


def test_the_records_feed_the_relevance_ledger(decided):
    records = [_record(decided, tick=t, reward=r) for t, r in ((1, 1.0), (2, -2.0))]
    missed = records[1].model_copy(update={"executed_action": None})
    decisions = relevance_decisions([records[0], missed])
    assert decisions[0].executed_action == decided.pick.action and decisions[1].executed_action is None
    assert [(m.sense, m.action, m.strength) for m in decisions[0].spoken] == [(m.sense, m.action, m.strength) for m in decided.messages]
    assert decisions[0].context == golden_inputs().context and decisions[0].reward == 1.0


def test_records_by_episode(decided):
    store = HistoryStore(None, ring=10)
    store.append(_record(decided, tick=1, episode_id="a"))
    store.append(_record(decided, tick=1, episode_id="b"))
    assert [r.episode_id for r in store.records("b")] == ["b"] and store.get(1, "a").episode_id == "a"


def test_the_ring_keeps_each_records_frame_in_memory_and_drops_it_with_the_record(decided):
    store = HistoryStore(None, ring=2)
    first, second, third = (_record(decided, tick=t, episode_id="a") for t in (0, 1, 2))
    store.append(first, frame_b64="Zmlyc3Q=")
    store.append(second)
    assert store.frame(first) == "Zmlyc3Q=" and store.frame(second) is None
    # The same tick number in another episode is another frame: `frames/<tick>.jpg` on disk would be shared.
    other = _record(decided, tick=0, episode_id="b")
    store.append(other, frame_b64="b3RoZXI=")
    assert store.frame(first) is None and store.frame(other) == "b3RoZXI=" and store.get(0, "b") is other
    store.append(third, frame_b64="dGhpcmQ=")
    assert store.frame(other) == "b3RoZXI=" and store.frame(third) == "dGhpcmQ=" and len(store) == 2
