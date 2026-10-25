"""Play episodes live and stream every tick to the web app as it is decided.

    cd web && npm run build && cd ..
    python -m system1_doom.serve --scenario deadly_corridor.cfg --model latest
    # then open http://127.0.0.1:8765/

The episodes are played exactly as `export` plays them (the same bridge, controller and
configuration) and written as the same bundles, one folder per episode under `live/`:
`live/live-1`, `live/live-2`, ... While an episode runs, the server answers for its files
from memory, so a reader never sees a half-written line; once it ends, its folder is a bundle
like any other (`python -m system1_doom.export --check live/live-1`).

On one origin:

    /                         the built app (--app)
    /episodes/index.json      the shipped recordings (--recordings), as they are
    /episodes/<name>/...      a shipped recording
    /episodes/live-<k>/...    a live episode: the one in progress from memory, finished ones from disk
    /live/status.json         what is playing and what has been played (404 means no live mode)
    /live/events              server-sent events: hello, start, tick, proposals, end, stopped

The fast path never waits for the network: publishing a tick is a queue put, a viewer whose
queue is full is dropped, and pacing is a sleep after a tick, never inside it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import posixpath
import queue
import re
import shutil
import signal
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlsplit

from system1_doom.export import (
    D1_SYNC_HELP,
    BundleIndexEntry,
    EpisodeMeta,
    Model,
    Player,
    _action_catalog,
    _load_model,
    build_player,
    copy_run_files,
    default_title,
    episode_meta,
    finish_bundle,
    index_entry,
    play_episode,
)
from system1_doom.logger import DecisionLogger, ProposalTrace, TickTrace
from system1_doom.train import RunStore, default_run_dir

LIVE_NAME = re.compile(r"^live-(\d+)$")
LIVE_FILES = ("episode.json", "ticks.jsonl", "proposals.jsonl")
KEEPALIVE_SEC = 15.0
CLIENT_QUEUE_SIZE = 1024
ZERO_RESULT: Dict[str, Any] = {
    "health": 0.0,
    "armor": 0.0,
    "kills": 0.0,
    "reward": 0.0,
    "ticks": 0,
    "finished": False,
    "cleared": False,
    "died": False,
}
NO_APP = (
    "No built app in {app}. Build it with `cd web && npm run build`, or run the Vite dev server "
    "(`cd web && npm run dev`), which passes /live and /episodes/live-* through to this server. "
    "The live data is served either way."
)


@dataclass(frozen=True)
class ServeConfig:
    scenario: str = "deadly_corridor.cfg"
    seed: int = 7
    model: Model = "heuristics"
    run_dir: Optional[Path] = None
    max_ticks: int = 500
    d1: bool = False
    d1_sync: bool = False
    codex: bool = False
    slow_path: bool = True
    deterministic: bool = False
    episodes: Optional[int] = None
    pace: float = 0.23
    rest: float = 3.0
    host: str = "127.0.0.1"
    port: int = 8765
    out: Path = Path("live")
    app: Path = Path("web/dist")
    recordings: Path = Path("web/public/episodes")

    def status(self) -> Dict[str, Any]:
        """The settings the app shows, and builds the serve command from."""
        return {
            "scenario": self.scenario,
            "seed": self.seed,
            "model": self.model,
            "d1": self.d1,
            "d1_sync": self.d1_sync,
            "codex": self.codex,
            "slow_path": self.slow_path,
            "deterministic": self.deterministic,
            "max_ticks": self.max_ticks,
            "pace_sec": self.pace,
            "episodes": self.episodes,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sse(event: str, data: str, event_id: Optional[int] = None) -> bytes:
    head = f"event: {event}\n" + (f"id: {event_id}\n" if event_id is not None else "")
    return (head + f"data: {data}\n\n").encode("utf-8")


class _Client:
    """One viewer of `/live/events`: a bounded queue of encoded events, and whether it has been dropped."""

    def __init__(self) -> None:
        self.queue: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=CLIENT_QUEUE_SIZE)
        self.closed = threading.Event()


class LiveHub:
    """What the play loop writes and the server reads: the episode in progress, the finished ones, the viewers.

    Every method holds the lock only for memory work; nothing here waits for a viewer.
    """

    def __init__(self, config: ServeConfig) -> None:
        self.config = config
        self.started_at = _now()
        self._lock = threading.Lock()
        self._clients: List[_Client] = []
        self._running = True
        self._current: Optional[str] = None
        self._meta: Optional[EpisodeMeta] = None
        self._actions: Dict[str, Any] = {}
        self._ticks: List[str] = []
        self._first_tick: Optional[int] = None
        self._last_tick: Optional[int] = None
        self._proposals: List[str] = []
        self._episodes: List[BundleIndexEntry] = []

    # The play loop's side.

    def start_episode(self, name: str, meta: EpisodeMeta) -> None:
        with self._lock:
            self._current, self._meta, self._actions = name, meta, dict(meta.actions)
            self._ticks, self._proposals = [], []
            self._first_tick = self._last_tick = None
            self._publish("start", json.dumps({"name": name, "meta": meta.model_dump(mode="json")}))

    def add_tick(self, name: str, trace: TickTrace) -> None:
        line = trace.model_dump_json()
        with self._lock:
            self._ticks.append(line)
            if self._first_tick is None:
                self._first_tick = trace.tick
            self._last_tick = trace.tick
            self._publish("tick", f'{{"name":{json.dumps(name)},"trace":{line}}}', trace.tick)

    def set_proposals(self, name: str, proposals: Sequence[ProposalTrace], actions: Dict[str, Any]) -> None:
        """The whole proposal list, and the action catalog with any macro it admitted."""
        lines = [p.model_dump_json() for p in proposals]
        catalog = {k: v.model_dump(mode="json") for k, v in actions.items()}
        with self._lock:
            self._proposals, self._actions = lines, dict(actions)
            data = f'{{"name":{json.dumps(name)},"proposals":[{",".join(lines)}],"actions":{json.dumps(catalog)}}}'
            self._publish("proposals", data)

    def end_episode(self, name: str, meta: EpisodeMeta) -> BundleIndexEntry:
        entry = index_entry(name, meta)
        data = json.dumps({"name": name, "meta": meta.model_dump(mode="json"), "entry": entry.model_dump()})
        with self._lock:
            self._episodes.insert(0, entry)
            self._current, self._meta = None, None
            self._ticks, self._proposals, self._actions = [], [], {}
            self._first_tick = self._last_tick = None
            self._publish("end", data)
        return entry

    def stop_play(self) -> None:
        with self._lock:
            self._running = False
            self._publish("stopped", "{}")

    def close_clients(self) -> None:
        with self._lock:
            for client in self._clients:
                client.closed.set()
                try:
                    client.queue.put_nowait(None)
                except queue.Full:
                    pass
            self._clients.clear()

    def _publish(self, event: str, data: str, event_id: Optional[int] = None) -> None:
        frame = _sse(event, data, event_id)
        for client in list(self._clients):
            try:
                client.queue.put_nowait(frame)
            except queue.Full:
                # A viewer this far behind is closed; its EventSource reconnects and reloads the files.
                client.closed.set()
                self._clients.remove(client)

    # The server's side.

    def connect(self) -> Tuple[_Client, Dict[str, Any]]:
        """A new viewer and its `hello`, taken together so no event falls between them."""
        client = _Client()
        with self._lock:
            self._clients.append(client)
            hello = {
                "current": self._current,
                "tick": self._last_tick,
                "episodes": [e.model_dump() for e in self._episodes],
            }
        return client, hello

    def disconnect(self, client: _Client) -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "schema_version": 1,
                "running": self._running,
                "current": self._current,
                "tick": self._last_tick,
                "episodes": [e.model_dump() for e in self._episodes],
                "config": self.config.status(),
                "started_at": self.started_at,
            }

    def live_file(self, name: str, file_name: str) -> Optional[bytes]:
        """A file of the episode in progress, from memory; None when `name` is not in progress."""
        if file_name not in LIVE_FILES:
            return None
        with self._lock:
            if name != self._current or self._meta is None:
                return None
            ticks, proposals = list(self._ticks), list(self._proposals)
            meta = self._meta.model_copy(
                update={
                    "tick_count": len(ticks),
                    "first_tick": self._first_tick or 0,
                    "last_tick": self._last_tick or 0,
                    "actions": dict(self._actions),
                }
            )
        if file_name == "episode.json":
            return meta.model_dump_json(indent=2).encode("utf-8")
        lines = ticks if file_name == "ticks.jsonl" else proposals
        return "".join(line + "\n" for line in lines).encode("utf-8")


class LiveServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, config: ServeConfig, hub: LiveHub) -> None:
        self.config = config
        self.hub = hub
        handler = functools.partial(LiveHandler, directory=str(config.app))
        super().__init__((config.host, config.port), handler)


class LiveHandler(SimpleHTTPRequestHandler):
    server: LiveServer
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".jsonl": "application/x-ndjson"}

    head_only = False

    def do_HEAD(self) -> None:  # noqa: N802 - the http.server name
        self.head_only = True
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        path = posixpath.normpath(unquote(urlsplit(self.path).path))
        if path == "/live/status.json":
            self._send(200, json.dumps(self.server.hub.status()).encode("utf-8"), "application/json", no_store=True)
        elif path == "/live/events" and not self.head_only:
            self._stream()
        elif path.startswith("/episodes/"):
            rest = path[len("/episodes/") :]
            name, _, file_name = rest.partition("/")
            if LIVE_NAME.match(name):
                body = self.server.hub.live_file(name, file_name)
                if body is not None:
                    self._send(200, body, self.guess_type(file_name), no_store=True)
                else:
                    self._send_file(self.server.config.out, rest, no_store=True)
            else:
                self._send_file(self.server.config.recordings, rest)
        elif path in ("/", "/index.html") and not (self.server.config.app / "index.html").is_file():
            self._send(404, NO_APP.format(app=self.server.config.app).encode("utf-8"), "text/plain; charset=utf-8")
        elif self.head_only:
            super().do_HEAD()
        else:
            super().do_GET()

    def _send(self, code: int, body: bytes, content_type: str, no_store: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not self.head_only:
            self.wfile.write(body)

    def _send_file(self, root: Path, relative: str, no_store: bool = False) -> None:
        base = root.resolve()
        target = (base / relative).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            self._send(404, b"Not found", "text/plain; charset=utf-8", no_store)
            return
        self._send(200, target.read_bytes(), self.guess_type(str(target)), no_store)

    def _stream(self) -> None:
        client, hello = self.server.hub.connect()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(_sse("hello", json.dumps(hello)))
            self.wfile.flush()
            last_write = time.monotonic()
            while not client.closed.is_set():
                try:
                    frame = client.queue.get(timeout=1.0)
                except queue.Empty:
                    if time.monotonic() - last_write >= KEEPALIVE_SEC:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        last_write = time.monotonic()
                    continue
                if frame is None:
                    break
                self.wfile.write(frame)
                self.wfile.flush()
                last_write = time.monotonic()
        except OSError:
            pass  # the viewer went away
        finally:
            self.server.hub.disconnect(client)

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        # One line per frame would drown the episode lines; only failures are worth printing.
        if isinstance(code, int) and code >= 400:
            super().log_request(code, size)


def prepare_live_dir(out: Path) -> None:
    """Clear the live episodes an earlier run left in `out`; refuse when it holds anything else."""
    if out.exists():
        if not out.is_dir():
            raise FileExistsError(f"{out} is not a folder; refusing to use it for live episodes.")
        strays = [
            p.name
            for p in out.iterdir()
            if not (p.is_dir() and LIVE_NAME.match(p.name) and ((p / "episode.json").is_file() or (p / "frames").is_dir()))
        ]
        if strays:
            raise FileExistsError(f"{out} holds {', '.join(sorted(strays))}, which serve did not write; refusing to clear it.")
        for p in out.iterdir():
            shutil.rmtree(p)
    out.mkdir(parents=True, exist_ok=True)


def start_server(config: ServeConfig, hub: LiveHub) -> LiveServer:
    """Serve on a thread of its own; `server_address` has the port when `config.port` is 0."""
    server = LiveServer(config, hub)
    threading.Thread(target=server.serve_forever, name="live-server", daemon=True).start()
    return server


def play_live_episode(player: Player, config: ServeConfig, hub: LiveHub, stop: threading.Event, k: int) -> EpisodeMeta:
    """Play episode `k` into `out/live-<k>`, publishing as it goes; returns its final meta."""
    name = f"live-{k}"
    out = config.out / name
    seed = config.seed + k - 1
    player.env.frames_dir = out / "frames"
    player.ctrl.logger = DecisionLogger(log_dir=out)
    player.env.reset_tick_count()
    player.keeper.last = None
    files, checkpoint = copy_run_files(player, out)
    title = f"{default_title(config.scenario, config.model, seed)}, live"
    opening = episode_meta(player, name, title, seed, ZERO_RESULT, [], files, checkpoint)
    (out / "episode.json").write_text(opening.model_dump_json(indent=2), encoding="utf-8")
    hub.start_episode(name, opening)

    published: List[ProposalTrace] = []
    tick_started = time.monotonic()

    def publish_proposals() -> None:
        nonlocal published
        proposals = player.ctrl.logger.proposal_traces
        # record_macro_performance replaces a proposal with a new object, so identity tells a change.
        if len(proposals) != len(published) or any(a is not b for a, b in zip(proposals, published)):
            published = proposals
            hub.set_proposals(name, proposals, _action_catalog(player.ctrl))

    def on_tick(trace: TickTrace) -> bool:
        nonlocal tick_started
        hub.add_tick(name, trace)
        publish_proposals()
        left = config.pace - (time.monotonic() - tick_started)
        if left > 0:
            stop.wait(left)
        tick_started = time.monotonic()
        return stop.is_set()

    result, traces = play_episode(player, seed, on_tick)
    # A slow-path request still in flight was asked by this episode, so its answer belongs here, not in the
    # next one: wait for it, at most as long as Codex is given, unless play is stopping.
    worker = player.ctrl.llm_worker
    deadline = time.monotonic() + worker.codex_timeout_sec + 5.0
    while worker.is_busy() and time.monotonic() < deadline and not stop.wait(0.05):
        pass
    player.ctrl.drain_slow_path()  # what `close` does after a recording
    publish_proposals()
    meta = finish_bundle(player, out, name, title, seed, result, traces, files, checkpoint)
    hub.end_episode(name, meta)
    return meta


def play(config: ServeConfig, hub: LiveHub, stop: threading.Event, log: bool = False) -> None:
    """Build once and play episode after episode until `config.episodes` are done or `stop` is set."""
    store = RunStore(config.run_dir or default_run_dir(config.scenario))
    learner, model_path = _load_model(store, config.model)
    player = build_player(
        config.scenario,
        config.seed,
        config.out / "live-1",
        config.model,
        store,
        learner,
        model_path,
        config.max_ticks,
        config.d1,
        config.slow_path,
        config.codex,
        config.deterministic,
        config.d1_sync,
    )
    try:
        k = 0
        while not stop.is_set() and (config.episodes is None or k < config.episodes):
            if k > 0 and config.rest > 0 and stop.wait(config.rest):
                break
            k += 1
            meta = play_live_episode(player, config, hub, stop, k)
            if log:
                outcome = "cleared" if meta.result.cleared else ("died" if meta.result.died else "survived")
                stopped = "" if meta.result.finished or not stop.is_set() else ", stopped"
                print(f"{config.out / meta.name}: {meta.tick_count} ticks, reward {meta.result.reward:.1f}, {outcome}{stopped}")
    finally:
        player.ctrl.close()
        hub.stop_play()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Play episodes live and stream them to the web app")
    parser.add_argument("--scenario", default="deadly_corridor.cfg", help="ViZDoom scenario config filename")
    parser.add_argument("--seed", type=int, default=7, help="Seed of the first episode; each next one takes the next seed")
    parser.add_argument("--model", choices=["heuristics", "best", "latest"], default="heuristics")
    parser.add_argument("--run-dir", default=None, help="Run folder with trained models (default: runs/<scenario name>)")
    parser.add_argument("--max-ticks", type=int, default=500, help="Decision cap per episode")
    parser.add_argument("--d1", action="store_true", help="Use Liquid AI d1-ultra (needs LIQUID_API_KEY)")
    parser.add_argument("--d1-sync", action="store_true", help=D1_SYNC_HELP)
    parser.add_argument("--codex", action="store_true", help="Let the slow path call the Codex CLI instead of templates")
    parser.add_argument("--no-slow-path", action="store_true", help="Switch the slow path off entirely")
    parser.add_argument("--deterministic", action="store_true", help="Always take the arbiter's top-scored action")
    parser.add_argument("--episodes", type=int, default=None, help="Episodes to play (default: until Ctrl+C)")
    parser.add_argument(
        "--pace", type=float, default=0.23, help="Least wall time per tick in seconds (default 0.23: 8 frames at 35 fps; 0 runs flat out)"
    )
    parser.add_argument("--rest", type=float, default=3.0, help="Pause between episodes in seconds (default 3)")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Address to listen on (default 127.0.0.1). Any other address exposes the stream to the network with no authentication.",
    )
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default 8765)")
    parser.add_argument("--out", default="live", help="Folder for the live episodes (default: live)")
    parser.add_argument("--app", default="web/dist", help="The built app to serve (default: web/dist)")
    parser.add_argument("--recordings", default="web/public/episodes", help="The shipped recordings (default: web/public/episodes)")
    return parser


def config_from_args(args: argparse.Namespace) -> ServeConfig:
    return ServeConfig(
        scenario=args.scenario,
        seed=args.seed,
        model=args.model,
        run_dir=Path(args.run_dir) if args.run_dir else None,
        max_ticks=args.max_ticks,
        d1=args.d1,
        d1_sync=args.d1_sync,
        codex=args.codex,
        slow_path=not args.no_slow_path,
        deterministic=args.deterministic,
        episodes=args.episodes,
        pace=max(0.0, args.pace),
        rest=max(0.0, args.rest),
        host=args.host,
        port=args.port,
        out=Path(args.out),
        app=Path(args.app),
        recordings=Path(args.recordings),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.d1_sync and not args.d1:
        parser.error("--d1-sync needs --d1")
    config = config_from_args(args)
    try:
        prepare_live_dir(config.out)
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 2
    hub = LiveHub(config)
    try:
        server = start_server(config, hub)
    except OSError as exc:
        print(f"Cannot listen on {config.host}:{config.port}: {exc}", file=sys.stderr)
        return 2

    stop = threading.Event()

    def on_interrupt(signum: int, frame: Any) -> None:
        if stop.is_set():
            raise KeyboardInterrupt
        print("\nStopping: finishing this episode's files (Ctrl+C again to quit at once)", file=sys.stderr)
        stop.set()

    signal.signal(signal.SIGINT, on_interrupt)
    host, port = server.server_address[:2]
    print(f"Live mode at http://{host}:{port}/  (Ctrl+C to stop)")
    if not (config.app / "index.html").is_file():
        print(NO_APP.format(app=config.app))
    seeds = f"seed {config.seed}" + ("" if config.episodes == 1 else " onwards")
    print(f"Playing {config.scenario} with {config.model}, {seeds}, into {config.out}/")
    try:
        try:
            play(config, hub, stop, log=True)
        except FileNotFoundError as exc:
            print(exc, file=sys.stderr)
            return 2
        if not stop.is_set():
            print(f"Done playing; still serving at http://{host}:{port}/  (Ctrl+C to stop)")
            while not stop.wait(0.5):
                pass
    except KeyboardInterrupt:
        pass
    finally:
        hub.close_clients()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
