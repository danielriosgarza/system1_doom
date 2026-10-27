"""Training data from games: each question as it was sent, the teacher's or the text's label, once, misses left out."""

import json

from system1_doom.ruletree.teach import build, main
from system1_doom.ruletree.walk import NODE_QUESTION, NONE
from tests.test_ruletree_agreement import AIM, EMPTY, FOCUS_LINE, ROOT, STATE, answer


def run_with_games(tmp_path):
    rec = {"text": STATE + "\n\n[focus]\n" + FOCUS_LINE, "steps": [
        {"kind": "rule", "node": "root", "question": NODE_QUESTION, "options": ROOT, "answer": answer("r1", ROOT)},
        {"kind": "focus", "node": "r1", "question": "Which enemy?", "options": {"i0": FOCUS_LINE}, "focus_line": FOCUS_LINE},
        {"kind": "skill", "node": "r1", "skill": "aim"},
        # The teacher was wrong here: 6 degrees right is r4.
        {"kind": "rule", "node": "aim", "question": NODE_QUESTION, "options": AIM, "answer": answer("r5", AIM)},
    ]}
    missed = {"text": EMPTY, "steps": [
        {"kind": "rule", "node": "root", "question": NODE_QUESTION, "options": ROOT, "answer": {"miss": "timeout"}},
    ]}
    games = tmp_path / "run" / "games"
    games.mkdir(parents=True)
    # The same decision in two games of seed 400 is written once; seed 9 is not asked for.
    (games / "s400-00.json").write_text(json.dumps({"seed": 400, "trace": [rec, missed]}))
    (games / "s400-01.json").write_text(json.dumps({"seed": 400, "trace": [rec]}))
    (games / "s9-00.json").write_text(json.dumps({"seed": 9, "trace": [rec]}))
    (games / "s401-00.json").write_text("{}")
    return tmp_path / "run"


def test_the_teacher_labels_every_answered_question_once(tmp_path):
    lines, counts = build([run_with_games(tmp_path)], [400, 401])
    assert dict(counts) == {"rule:root:teacher": 1, "rule:aim:teacher": 1}
    root, aim = lines
    assert root["state"] == STATE and root["questions"]["q"] == {"type": "choice", "instructions": NODE_QUESTION, "criteria": ROOT}
    assert root["gold"]["q"]["probabilities"] == answer("r1", ROOT)["probabilities"]
    # After the focus the question reads its line, as it was sent.
    assert aim["state"] == STATE + "\n\n[focus]\n" + FOCUS_LINE and max(aim["gold"]["q"]["probabilities"].items(), key=lambda kv: kv[1])[0] == "r5"


def test_the_text_settles_what_it_can_and_the_teacher_the_rest(tmp_path):
    run = run_with_games(tmp_path)
    lines, counts = build([run], [400], labels="text")
    assert dict(counts) == {"rule:root:text": 1, "rule:aim:text": 1}
    assert [line["expected"]["q"] for line in lines] == ["r1", "r4"]
    out = tmp_path / "train.jsonl"
    assert main([str(out), str(run), "--seeds", "400", "--labels", "text+teacher"]) == 0
    assert [json.loads(line).get("expected", {}).get("q") for line in out.read_text().splitlines()] == ["r1", "r4"]
    assert NONE in json.loads(out.read_text().splitlines()[1])["questions"]["q"]["criteria"]
