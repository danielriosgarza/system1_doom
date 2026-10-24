import http.client
import json
from pathlib import Path
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

from system1_doom import export, serve
from system1_doom.logger import TickTrace

RECORDINGS = Path(__file__).resolve().parents[1] / "web" / "public" / "episodes"

Event = Tuple[str, Dict[str, Any], Optional[str]]


class GatedHub(serve.LiveHub):
    """Holds the play loop after live-1's second tick until the test has read the episode in progress."""

    def __init__(self, config: serve.ServeConfig) -> None:
        super().__init__(config)
        self.held = threading.Event()
        self.release = threading.Event()

    def add_tick(self, name: str, trace: TickTrace) -> None:
        super().add_tick(name, trace)
        if name == "live-1" and trace.tick == 1:
            self.held.set()
            self.release.wait(30)


def _events(response: http.client.HTTPResponse, deadline: float) -> Iterator[Event]:
    """Server-sent events as (event, data, id), until the stream closes or the deadline passes."""
    event, data, event_id = "", [], None
    while time.monotonic() < deadline:
        raw = response.fp.readline()
        if not raw:
            return
        line = raw.decode("utf-8").rstrip("\n")
        if not line:
            if event:
                yield event, json.loads("\n".join(data)), event_id
            event, data, event_id = "", [], None
        elif not line.startswith(":"):
            field, _, value = line.partition(": ")
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
            elif field == "id":
                event_id = value


def _get(port: int, path: str) -> Tuple[int, Dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def session(tmp_path_factory) -> Dict[str, Any]:
    root = tmp_path_factory.mktemp("serve")
    config = serve.ServeConfig(
        scenario="basic.cfg",
        seed=3,
        run_dir=root / "no_run",
        max_ticks=5,
        deterministic=True,
        episodes=2,
        pace=0.0,
        rest=0.0,
        port=0,
        out=root / "live",
        app=root / "no_app",
        recordings=RECORDINGS,
    )
    serve.prepare_live_dir(config.out)
    hub = GatedHub(config)
    server = serve.start_server(config, hub)
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    conn.request("GET", "/live/events")
    response = conn.getresponse()
    stream = _events(response, time.monotonic() + 60)
    hello = next(stream)
    play = threading.Thread(target=serve.play, args=(config, hub, threading.Event()), daemon=True)
    play.start()

    events: List[Event] = []
    frames_missing: List[str] = []
    middle: Dict[str, Any] = {}
    ends = 0
    for event in stream:
        events.append(event)
        kind, data, _ = event
        if kind == "tick":
            tick = data["trace"]["tick"]
            if not (config.out / data["name"] / "frames" / f"{tick:05d}.jpg").is_file():
                frames_missing.append(f"{data['name']} {tick}")
            if hub.held.is_set() and not middle:
                middle["meta"] = _get(port, "/episodes/live-1/episode.json")
                middle["ticks"] = _get(port, "/episodes/live-1/ticks.jsonl")
                middle["tick"] = tick
                hub.release.set()
        elif kind == "end":
            ends += 1
            name = data["name"]
            on_disk = json.loads((config.out / name / "episode.json").read_text(encoding="utf-8"))
            middle[f"{name} same meta"] = on_disk == data["meta"]
            middle[f"{name} problems"] = export.check_bundle(config.out / name)
            if ends == 2:
                break
    hub.release.set()
    play.join(30)
    result = {
        "config": config,
        "port": port,
        "hello": hello,
        "events": events,
        "frames_missing": frames_missing,
        "middle": middle,
        "status": json.loads(_get(port, "/live/status.json")[2]),
        "index": _get(port, "/episodes/index.json"),
        "stopped": next(stream, None),
    }
    yield result
    hub.close_clients()
    server.shutdown()
    server.server_close()
    conn.close()


def _episodes(events: List[Event]) -> Dict[str, List[Event]]:
    by_name: Dict[str, List[Event]] = {}
    for event in events:
        by_name.setdefault(event[1]["name"], []).append(event)
    return by_name


def test_each_episode_streams_start_ticks_proposals_on_change_and_end(session):
    assert session["hello"] == ("hello", {"current": None, "tick": None, "episodes": []}, None)
    by_name = _episodes(session["events"])
    assert list(by_name) == ["live-1", "live-2"]
    for name, events in by_name.items():
        kinds = [kind for kind, _, _ in events]
        assert kinds[0] == "start" and kinds[-1] == "end" and kinds.count("start") == kinds.count("end") == 1, name
        assert set(kinds[1:-1]) <= {"tick", "proposals"}
        ticks = [data["trace"]["tick"] for kind, data, _ in events if kind == "tick"]
        assert 1 <= len(ticks) <= 5 and ticks == list(range(len(ticks))), name
        ids = [event_id for kind, _, event_id in events if kind == "tick"]
        assert ids == [str(t) for t in ticks]
        lists = [[]] + [data["proposals"] for kind, data, _ in events if kind == "proposals"]
        assert all(a != b for a, b in zip(lists, lists[1:])), "a proposals event repeated the list"
        start, end = events[0][1]["meta"], events[-1][1]["meta"]
        assert start["tick_count"] == 0 and start["result"]["finished"] is False
        assert end["tick_count"] == len(ticks) and end["last_tick"] == ticks[-1]
        assert events[-1][1]["entry"]["name"] == name and events[-1][1]["entry"]["ticks"] == len(ticks)
    assert by_name["live-2"][0][1]["meta"]["seed"] == by_name["live-1"][0][1]["meta"]["seed"] + 1
    assert session["stopped"] is not None and session["stopped"][0] == "stopped"


def test_every_frame_is_on_disk_before_its_tick_is_published(session):
    assert session["frames_missing"] == []


def test_the_episode_in_progress_is_served_from_memory(session):
    status, headers, body = session["middle"]["meta"]
    assert status == 200 and headers["Cache-Control"] == "no-store"
    meta = export.EpisodeMeta.model_validate_json(body)
    assert meta.name == "live-1" and meta.tick_count == 2 and meta.last_tick == 1 and not meta.result.finished
    status, headers, body = session["middle"]["ticks"]
    assert status == 200 and headers["Content-Type"] == "application/x-ndjson"
    ticks = [TickTrace.model_validate_json(line) for line in body.decode("utf-8").splitlines()]
    assert [t.tick for t in ticks] == [0, 1]


def test_a_finished_episode_is_a_valid_bundle(session):
    for name in ("live-1", "live-2"):
        assert session["middle"][f"{name} problems"] == []
        assert session["middle"][f"{name} same meta"]
        status, headers, body = _get(session["port"], f"/episodes/{name}/episode.json")
        assert status == 200 and headers["Cache-Control"] == "no-store"
        assert json.loads(body) == json.loads((session["config"].out / name / "episode.json").read_text())


def test_status_lists_the_finished_episodes_and_the_shipped_index_is_untouched(session):
    status = session["status"]
    assert status["schema_version"] == 1 and status["running"] is False and status["current"] is None
    assert [e["name"] for e in status["episodes"]] == ["live-2", "live-1"]
    assert status["config"]["scenario"] == "basic.cfg" and status["config"]["episodes"] == 2
    code, _, body = session["index"]
    assert code == 200 and body == (RECORDINGS / "index.json").read_bytes()


def test_stopping_finishes_the_episode_with_finished_false(tmp_path):
    config = serve.ServeConfig(
        scenario="basic.cfg", seed=3, run_dir=tmp_path / "no_run", max_ticks=5, deterministic=True,
        pace=0.0, rest=0.0, out=tmp_path / "live",
    )
    stop = threading.Event()

    class StoppingHub(serve.LiveHub):
        def add_tick(self, name: str, trace: TickTrace) -> None:
            super().add_tick(name, trace)
            if trace.tick == 1:
                stop.set()

    serve.prepare_live_dir(config.out)
    hub = StoppingHub(config)
    serve.play(config, hub, stop)
    meta = export.EpisodeMeta.model_validate_json((config.out / "live-1" / "episode.json").read_text())
    assert meta.tick_count == 2 and meta.result.finished is False
    assert export.check_bundle(config.out / "live-1") == []
    assert sorted(p.name for p in config.out.iterdir()) == ["live-1"]
    assert hub.status()["running"] is False


def test_the_out_folder_is_cleared_only_of_earlier_episodes(tmp_path):
    out = tmp_path / "live"
    (out / "live-1" / "frames").mkdir(parents=True)
    (out / "live-2").mkdir()
    (out / "live-2" / "episode.json").write_text("{}")
    serve.prepare_live_dir(out)
    assert list(out.iterdir()) == []
    (out / "notes.txt").write_text("mine")
    with pytest.raises(FileExistsError):
        serve.prepare_live_dir(out)
    (out / "notes.txt").unlink()
    (out / "live-3").mkdir()
    with pytest.raises(FileExistsError):
        serve.prepare_live_dir(out)


def test_a_macro_admitted_mid_episode_reaches_the_catalog_with_its_proposal(tmp_path):
    # Deadly corridor, seed 9, heuristics: the slow path admits evasive_burst_1 at tick 18.
    config = serve.ServeConfig(
        scenario="deadly_corridor.cfg", seed=9, run_dir=tmp_path / "no_run", max_ticks=25, deterministic=True,
        episodes=1, pace=0.0, rest=0.0, out=tmp_path / "live",
    )
    serve.prepare_live_dir(config.out)
    hub = serve.LiveHub(config)
    client, _ = hub.connect()
    serve.play(config, hub, threading.Event())
    events = []
    while not client.queue.empty():
        frame = client.queue.get_nowait().decode("utf-8")
        fields = dict(line.split(": ", 1) for line in frame.strip().splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    proposals = [data for kind, data in events if kind == "proposals"]
    assert proposals, "no proposals event"
    for data in proposals:
        admitted = {p["admitted_action_id"] for p in data["proposals"] if p["admission_decision"]}
        assert admitted <= set(data["actions"])
    end = next(data for kind, data in events if kind == "end")
    assert "evasive_burst_1" in end["meta"]["actions"]
    on_disk = [json.loads(line) for line in (config.out / "live-1" / "proposals.jsonl").read_text().splitlines()]
    assert on_disk == proposals[-1]["proposals"]
    assert [kind for kind, _ in events][-2:] == ["end", "stopped"]
