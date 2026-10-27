"""The command line on the stand-in corridor: show, eval, check, commit and finish."""

import io
import json

import pytest

from system1_doom.ruletree.__main__ import main, parse_seeds
from system1_doom.ruletree.tree import save_tree
from tests.fake_d1 import FakeD1
from tests.ruletree_fixtures import CorridorGame, general_tree, jev_client, scripted, sees_imp, walk_on_tree


def _main(*argv):
    out = io.StringIO()
    code = main(list(argv), client=jev_client(FakeD1(scripted(sees_imp), decider="jev")), game_factory=CorridorGame, out=out)
    return code, out.getvalue()


def test_parse_seeds():
    assert parse_seeds("9-12") == [9, 10, 11, 12]
    assert parse_seeds("9,12, 15") == [9, 12, 15]
    assert parse_seeds("9-10,40-41") == [9, 10, 40, 41]


def test_show_prints_a_tree(tmp_path):
    save_tree(general_tree(), tmp_path / "t")
    code, out = _main("show", "--tree", str(tmp_path / "t"))
    assert code == 0 and out.splitlines()[0] == "root: default -> random walk" and "skill aim:" in out


def test_eval_then_commit_a_rule_then_finish(tmp_path):
    save_tree(walk_on_tree(), tmp_path / "start")
    run = tmp_path / "run"
    code, out = _main("eval", str(run), "--tree", str(tmp_path / "start"), "--seeds", "9-10", "--workers", "2")
    assert code == 0 and out.splitlines()[-1] == "cleared 0 of 2"
    assert out.splitlines()[0].startswith("seed 9: died at decision 5")

    proposal = tmp_path / "p1.json"
    proposal.write_text(json.dumps({"trace": "s9-00", "frame": 3, "condition": "An enemy is in view.", "action": "0001"}))
    code, out = _main("check", str(run), str(proposal))
    assert code == 0 and out.startswith("check: PASS (your rule became r1, attached under root)")
    code, out = _main("commit", str(run), str(proposal))
    assert code == 0 and out.splitlines()[-1] == "committed r1"

    code, out = _main("eval", str(run), "--seeds", "9-10")
    assert out.splitlines()[-1] == "cleared 2 of 2"
    code, out = _main("finish", str(run), str(tmp_path / "done"))
    assert code == 0 and (tmp_path / "done" / "tree.json").is_file()
    steps = [json.loads(line)["step"] for line in (tmp_path / "done" / "build.jsonl").read_text().splitlines()]
    assert steps == ["start", "eval", "check", "check", "commit", "eval"]


def test_a_run_needs_a_tree(tmp_path):
    code, out = _main("check", str(tmp_path / "nothing"), str(tmp_path / "p1.json"))
    assert code == 2 and "has no tree yet" in out


def test_play_starts_from_the_default_tree(tmp_path):
    code, out = _main("show")
    assert code == 0 and "skill aim:" in out
    code, out = _main("play", str(tmp_path / "run"), "--seed", "9")
    assert code == 0 and out.splitlines()[0] == f"starting {tmp_path / 'run'} from general-11"
    assert json.loads((tmp_path / "run" / "tree" / "tree.json").read_text())["name"] == "general-11"


@pytest.mark.parametrize("decider, url, model, extra, answered_by", [
    ("laya", "http://127.0.0.1:8000/v1/systemone", "english", {"max_len": 2048}, "laya-rl-agent"),
    ("kev", "http://127.0.0.1:8008/v1/systemone", "kev-latest", {}, "kev-latest"),
])
def test_eval_on_a_local_model_needs_no_key_and_sends_the_text_alone(tmp_path, monkeypatch, decider, url, model, extra, answered_by):
    for key in ("LAYA_API_KEY", "KEV_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("system1_doom.ruletree.__main__.load_api_key", lambda decider: None)
    fake = FakeD1(scripted(sees_imp), decider=decider)
    monkeypatch.setattr("system1_doom.d1_client._default_requests_transport", fake)
    save_tree(general_tree(), tmp_path / "start")
    out = io.StringIO()
    code = main(["eval", str(tmp_path / "run"), "--tree", str(tmp_path / "start"), "--seeds", "9-10", "--workers", "2",
                 "--decider", decider], game_factory=CorridorGame, out=out)
    assert code == 0 and out.getvalue().splitlines()[-1].startswith("cleared ")
    assert fake.calls and {u for u, _ in fake.requests} == {url}
    assert all("Authorization" not in headers for _, headers in fake.requests)
    assert all(set(p) == {"model", "state", "questions", *extra} and p["model"] == model for _, p in fake.calls)
    assert all(p.get("max_len") == extra.get("max_len") for _, p in fake.calls)
    eval_row = json.loads((tmp_path / "run" / "build.jsonl").read_text().splitlines()[-1])
    assert eval_row["step"] == "eval" and set(eval_row["models"]) == {answered_by}


def test_play_needs_the_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("system1_doom.ruletree.__main__.load_api_key", lambda decider: None)
    out = io.StringIO()
    code = main(["eval", str(tmp_path / "run"), "--tree", "general-9", "--seeds", "9"], out=out)
    assert code == 2 and "TYPESAFE_API_KEY is not set" in out.getvalue()
