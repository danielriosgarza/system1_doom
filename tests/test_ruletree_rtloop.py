"""The soft loop on real-time games, on ViZDoom with canned answers and a scripted writer: a failure's real-time
dossier, the proposal's `sees` check at its frame, the gate against the round's games, the commit, and the record."""

import json
import re

from system1_doom.ruletree.game import Game
from system1_doom.ruletree.rtloop import PROMPT, run_rt_loop
from system1_doom.ruletree.run import Run
from system1_doom.ruletree.tree import load_tree
from tests.fake_d1 import FakeD1
from tests.ruletree_fixtures import by_text, jev_client, scripted


class Scripted:
    """A writer that answers with the proposals given, one per call, and keeps the prompts it was sent."""

    name = "scripted"

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def write(self, prompt, name, folder):
        self.prompts.append(prompt)
        return json.dumps(self.answers.pop(0))


def test_a_real_time_failure_gets_a_rule_that_is_checked_gated_and_committed(tmp_path):
    # Every rule question picks the new rule's condition if it is offered, else an enemy if one is listed.
    fake = FakeD1(scripted(by_text("I am still in the game.", "at least one enemy", "no enemy")), decider="jev")
    run = Run(tmp_path / "run", client=jev_client(fake, budget=5.0), workers=1, game_factory=Game)
    run.start(load_tree("realtime-5"))
    first = {"frame": 0, "under": "root", "condition": "I am still in the game.", "action": "B000",
             "why": "back away from everything (it gets nowhere, so the gate turns it down)"}
    writer = Scripted(first, {**first, "action": {"skill": "aim", "then": "0001", "after": "F001"}})
    try:
        result = run_rt_loop(run, writer, [9], [], rounds=1, attempts=2)
    finally:
        run.close()
    rows = [json.loads(line) for line in (tmp_path / "run" / "build.jsonl").read_text().splitlines()]
    steps = [r["step"] for r in rows]
    assert steps[:2] == ["start", "pass"] and rows[1]["realtime"] and result["rounds"] == 1
    assert steps.count("proposal") == 2 and steps.count("check") == 2
    checks = [r for r in rows if r["step"] == "check"]
    assert all(c["sees"] and c["attach_to"] == "root" for c in checks)
    # The writer was sent the real-time instructions and a dossier of a game the game did not wait in.
    assert PROMPT.read_text(encoding="utf-8")[:200] in writer.prompts[0]
    assert "Played in real time: every action started 7 tics after the state" in writer.prompts[0]
    read = re.findall(r"state read at tic (\d+), action from tic (\d+)", writer.prompts[0])
    assert read and all(int(b) - int(a) == 7 for a, b in read)
    game = json.loads(next((tmp_path / "run" / "games").glob("s9-00.json")).read_text())
    assert game["realtime"]["lag"] == 7 and all("text" in d and "frame" in d for d in game["decisions"])
    gates = [r for r in rows if r["step"] == "gate"]
    assert gates and gates[0]["of"] == 1
    if "commit" in steps:
        assert "I am still in the game." in json.dumps(run.tree().model_dump())
