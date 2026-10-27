"""The soft loop end to end on the stand-in corridor, with writers that answer from a script: a failure goes to
the writer, a proposal that fails its check goes back with the report, a good one is gated and committed, and every
step is a line of build.jsonl."""

import json

import pytest

from system1_doom.ruletree.loop import run_loop
from system1_doom.ruletree.run import Run
from system1_doom.ruletree.writers import FileWriter, parse
from tests.fake_d1 import FakeD1
from tests.ruletree_fixtures import CorridorGame, jev_client, scripted, sees_imp, walk_on_tree


class Scripted:
    """A writer that answers each call with the next answer of a list, as a function of the failure's game."""

    name = "scripted"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def write(self, prompt, name, folder):
        self.prompts.append(prompt)
        game = name.split("-", 1)[1].rsplit("-a", 1)[0]
        return self.answers.pop(0)(game)


def _rule(condition, action="0001"):
    def answer(game):
        frame = 3
        return "Here it is:\n```json\n" + json.dumps({"trace": game, "frame": frame, "condition": condition, "action": action,
                                                     "why": "stand and shoot the enemy in view"}) + "\n```"
    return answer


@pytest.fixture
def run(tmp_path):
    r = Run(tmp_path / "run", client=jev_client(FakeD1(scripted(sees_imp), decider="jev")), workers=2, game_factory=CorridorGame)
    r.start(walk_on_tree())
    yield r
    r.close()


def _build(run):
    return [json.loads(line) for line in (run.folder / "build.jsonl").read_text().splitlines()]


def test_the_loop_writes_one_rule_and_clears_every_seed(run):
    writer = Scripted(lambda game: "I am not sure.", _rule("The level is dark."), _rule("An enemy is in view."))
    result = run_loop(run, writer, train=[9, 10], held=[11, 12], rounds=4)
    assert result == {"rounds": 2, "train": "2/2", "held": "2/2"}
    steps = [row["step"] for row in _build(run)]
    assert steps == ["start", "pass", "proposal", "proposal", "check", "proposal", "check", "gate", "commit", "pass", "held-out", "done"]
    rows = _build(run)
    assert rows[1]["cleared"] == 0 and rows[1]["games"][0]["event"] == "died"
    assert rows[2]["error"] == "no JSON object in the answer"
    assert rows[4]["passed"] is False and rows[4]["sees"] is False
    assert rows[6]["passed"] is True and rows[7]["with_rule"] == 2 and rows[8]["rule"] == "r1"
    # The second and third prompts carry the earlier attempts and what the program said.
    assert "could not read a JSON object" in writer.prompts[1]
    assert "sees: FAIL" in writer.prompts[2] and "# The failure" in writer.prompts[2]
    assert "## The rule tree that played" in writer.prompts[0] and "You are System 2 of a Doom agent" in writer.prompts[0]
    tree = run.tree()
    assert tree.nodes["r1"].condition == "An enemy is in view." and len(tree.nodes["r1"].cornerstones) == 1
    # The finished tree plays on its own.
    out = run.finish(run.folder / "finished")
    assert (out / "tree.json").is_file() and (out / "build.jsonl").is_file() and list((out / "cornerstones").glob("*.jpg"))


def test_a_writer_can_say_the_state_lacks_the_information(run):
    writer = Scripted(lambda game: json.dumps({"trace": game, "needs_representation": "who shot me"}))
    result = run_loop(run, writer, train=[9], held=[], rounds=1)
    assert result["train"] == "0/1"
    assert [row["step"] for row in _build(run)] == ["start", "pass", "needs_representation", "done"]


def test_file_writer_waits_for_the_answer_file(tmp_path):
    import threading

    w = FileWriter(poll=0.01, timeout=5)
    threading.Timer(0.1, lambda: (tmp_path / "f01-s9-00-a1.answer.json").write_text('{"trace": "s9-00", "frame": 1}')).start()
    answer = w.write("the prompt", "f01-s9-00-a1", tmp_path)
    assert (tmp_path / "f01-s9-00-a1.prompt.md").read_text() == "the prompt"
    assert parse(answer) == {"trace": "s9-00", "frame": 1}


def test_parse_reads_bare_or_fenced_json():
    assert parse('{"a": 1}') == {"a": 1}
    assert parse('text\n```json\n{"a": {"b": 2}}\n```\nmore') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse("no json here")


def test_engines_are_started_once_and_reused(tmp_path):
    started = []

    def factory():
        started.append(CorridorGame())
        return started[-1]

    run = Run(tmp_path / "run", client=jev_client(FakeD1(scripted(sees_imp), decider="jev")), workers=2, game_factory=factory)
    run.start(walk_on_tree())
    for _ in range(3):
        assert len(run.play_many([9, 10, 11, 12])) == 4
    assert len(started) <= 2
    run.close()
