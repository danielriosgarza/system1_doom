"""A run of the soft loop: one folder with the tree being built, every game played, Jev's answers, and the record.

    <run>/tree/           the tree (tree.json, cornerstones/)
    <run>/games/<g>.json  one game: its seed, the tree that played it, and a record per decision
    <run>/games/<g>/      the game's dossier for the rule writer (dossier.md, frame-NNN.jpg)
    <run>/answers/        Jev's answers, one file per game or check
    <run>/proposals/      what the rule writer was sent and answered, each check and gate report
    <run>/build.jsonl     the record: one line per pass, proposal, check, gate and commit

Games are played in parallel threads; each game borrows an engine from a pool and returns it, so engines are started
once per run. One client serves them all.
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from system1_doom.d1_client import D1UltraClient

from .dossier import write_dossier
from .game import Game, outcome, play
from .tree import RuleTree, load_tree, save_tree, tree_folder
from .walk import AnswerBook, Jev

GameFactory = Callable[[], Any]


class Run:
    def __init__(
        self,
        folder: Union[str, Path],
        client: Optional[D1UltraClient] = None,
        workers: int = 6,
        game_factory: GameFactory = Game,
    ) -> None:
        self.folder = Path(folder)
        self.workers = max(1, workers)
        self.client = client if client is not None else D1UltraClient(decider="jev", max_workers=max(6, 2 * self.workers))
        self.game_factory = game_factory
        self._names = threading.Lock()
        self._log = threading.Lock()
        self._idle: "queue.Queue[Any]" = queue.Queue()
        self._own: Optional[Any] = None
        self._games: List[Any] = []

    # ------------------------------------------------------------------ the tree

    @property
    def tree_dir(self) -> Path:
        return self.folder / "tree"

    def start(self, source: Union[str, Path, RuleTree]) -> RuleTree:
        """Begin the run from a tree (a folder, a tree.json, a shipped tree's name, or a tree), unless it has one."""
        if not (self.tree_dir / "tree.json").is_file():
            self.folder.mkdir(parents=True, exist_ok=True)
            tree = source if isinstance(source, RuleTree) else load_tree(source)
            save_tree(tree, self.tree_dir)
            self.log(step="start", tree=tree.name, source=tree.name if isinstance(source, RuleTree) else str(tree_folder(source)))
        return self.tree()

    def tree(self) -> RuleTree:
        return load_tree(self.tree_dir)

    def save(self, tree: RuleTree) -> None:
        save_tree(tree, self.tree_dir)

    # ------------------------------------------------------------------ Jev and games

    def jev(self, read: bool = True, shard: Optional[str] = None) -> Jev:
        """Jev for this run: `read` uses every recorded answer first (checks); `shard` keeps new answers there."""
        return Jev(self.client, AnswerBook(self.folder / "answers", shard, read=read))

    def game(self) -> Any:
        """The game a check replays in, one after the other."""
        if self._own is None:
            self._own = self._start_game()
        return self._own

    def _start_game(self) -> Any:
        g = self.game_factory()
        with self._names:
            self._games.append(g)
        return g

    def _borrow(self) -> Any:
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            return self._start_game()

    def _discard(self, g: Any) -> None:
        with self._names:
            if g in self._games:
                self._games.remove(g)
        g.close()

    def close(self) -> None:
        for g in list(self._games):
            g.close()
        self._games.clear()
        self._own = None
        self._idle = queue.Queue()

    def new_name(self, seed: int, label: str = "") -> str:
        """A fresh game name: `s9-00`, `s9-01`, ... (`gate-s9-00` with a label)."""
        games = self.folder / "games"
        with self._names:
            games.mkdir(parents=True, exist_ok=True)
            n = 0
            while (games / f"{label}s{seed}-{n:02d}.json").exists():
                n += 1
            name = f"{label}s{seed}-{n:02d}"
            (games / f"{name}.json").write_text("{}", encoding="utf-8")
            return name

    def play(self, seed: int, tree: Optional[RuleTree] = None, label: str = "") -> Dict[str, Any]:
        """One game from the start with fresh answers, until the first unwanted event or the end; it is kept with its
        dossier. Returns its summary."""
        tree = tree if tree is not None else self.tree()
        name = self.new_name(seed, label)
        jev = self.jev(read=False, shard=f"{name}.json")
        t0 = time.monotonic()
        game = self._borrow()
        try:
            trace = play(game, tree, jev, seed)
        except Exception:
            self._discard(game)
            raise
        self._idle.put(game)
        jev.book.save()
        self.save_game(name, seed, tree, trace)
        last = trace[-1]
        steps = [s for r in trace for s in r["steps"] if "answer" in s and not s["answer"].get("cached")]
        return {
            "game": name, "seed": seed, "event": outcome(trace), "decisions": len(trace), "max_x": last["max_x"],
            "health": last["health_after"], "jev_calls": len(steps), "misses": sum(1 for s in steps if s["answer"].get("miss")),
            "cost": round(sum(s["answer"].get("cost", 0.0) for s in steps), 6), "seconds": round(time.monotonic() - t0, 1),
        }

    def play_many(self, seeds: Sequence[int], tree: Optional[RuleTree] = None, label: str = "") -> List[Dict[str, Any]]:
        """Play every seed once, in parallel, with fresh answers."""
        tree = tree if tree is not None else self.tree()
        return self.play_jobs([(seed, tree, label) for seed in seeds])

    def play_jobs(self, jobs: Sequence[Tuple[int, RuleTree, str]]) -> List[Dict[str, Any]]:
        """Play (seed, tree, label) jobs in parallel; their summaries, in the order given."""

        def one(job: Tuple[int, RuleTree, str]) -> Dict[str, Any]:
            seed, tree, label = job
            try:
                return self.play(seed, tree, label)
            except Exception as exc:  # noqa: BLE001 - a crashed game is reported with the others, not raised
                return {"seed": seed, "event": "crashed", "error": f"{type(exc).__name__}: {exc}"[:500]}

        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(one, jobs))

    def save_game(self, name: str, seed: int, tree: RuleTree, trace: List[Dict[str, Any]]) -> None:
        games = self.folder / "games"
        data = {"name": name, "seed": seed, "tree": tree.name, "trace": trace}
        (games / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
        write_dossier(games / name, name, seed, trace, tree)

    def game_record(self, name: str) -> Dict[str, Any]:
        path = self.folder / "games" / f"{name}.json"
        if not path.is_file():
            raise FileNotFoundError(f"no game {name!r} in {self.folder}")
        return json.loads(path.read_text(encoding="utf-8"))

    def dossier(self, name: str) -> Path:
        return self.folder / "games" / name / "dossier.md"

    # ------------------------------------------------------------------ the record

    def log(self, **row: Any) -> Dict[str, Any]:
        row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), **row}
        with self._log:
            self.folder.mkdir(parents=True, exist_ok=True)
            with (self.folder / "build.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        return row

    def proposals_dir(self) -> Path:
        d = self.folder / "proposals"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def finish(self, to: Union[str, Path]) -> Path:
        """Copy the tree and its record into a tree folder that plays on its own."""
        to = Path(to)
        save_tree(self.tree(), to)
        if (self.folder / "build.jsonl").is_file():
            shutil.copyfile(self.folder / "build.jsonl", to / "build.jsonl")
        return to
