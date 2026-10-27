"""The agreement check: a recording's questions as they were sent, the answers the text settles, and the scores."""

import io
import json
from contextlib import redirect_stdout

from system1_doom.d1_client import D1UltraClient
from system1_doom.ruletree.agreement import compare, main, questions, settled
from system1_doom.ruletree.walk import NODE_QUESTION, NONE, NONE_TEXT
from tests.fake_d1 import FakeD1
from tests.ruletree_fixtures import by_text, scripted

STATE = ("[goal]\nReach the green armor.\n\n[threats]\n1 enemy visible, nearest first:\n"
         "- Zombieman at distance 185, 6 deg right, size 22x59 px\n\n[outgoing]\ndamage dealt since the last decision 0")
EMPTY = "[goal]\nReach the green armor.\n\n[threats]\nno enemy visible\n\n[landmarks]\n- Shotgun (weapon): 203 away\n- GreenArmor (armor): 1328 away"
ROOT = {"r1": "The threats list shows at least one enemy.", "r3": "The threats list says no enemy is visible.", NONE: NONE_TEXT}
AIM = {f"r{i}": f"band {i}" for i in range(4, 10)} | {NONE: NONE_TEXT}
R1 = {"r2": "far", "r11": "fruitless", NONE: NONE_TEXT}
FOCUS_LINE = "Zombieman at distance 185, 6 deg right, size 22x59 px (from the threats list)"


def answer(pick, options):
    return {"probabilities": {k: (0.9 if k == pick else 0.1 / (len(options) - 1)) for k in options}, "pick": pick}


def recording(tmp_path):
    goal = {"i0": "Shotgun (weapon): 203 away", "i1": "GreenArmor (armor): 1328 away"}
    rows = [
        {"decision": 0, "state_text": STATE + "\n\n[focus]\n" + FOCUS_LINE, "steps": [
            {"kind": "rule", "node": "root", "question": NODE_QUESTION, "options": ROOT, "answer": answer("r1", ROOT)},
            # One enemy: the focus is not asked, but its line is added to what the next questions read.
            {"kind": "focus", "node": "r1", "question": "Which enemy?", "options": {"i0": FOCUS_LINE}, "focus_line": FOCUS_LINE},
            {"kind": "rule", "node": "r1", "question": NODE_QUESTION, "options": R1, "answer": answer(NONE, R1)},
            {"kind": "skill", "node": "r1", "skill": "aim"},
            {"kind": "rule", "node": "aim", "question": NODE_QUESTION, "options": AIM, "answer": answer("r4", AIM)},
        ]},
        {"decision": 1, "state_text": EMPTY, "steps": [
            {"kind": "rule", "node": "root", "question": NODE_QUESTION, "options": ROOT, "answer": answer("r3", ROOT)},
            {"kind": "focus", "node": "r3", "question": "Which is the goal?", "options": goal, "answer": answer("i1", goal),
             "focus_line": "GreenArmor (armor): 1328 away (from the landmarks list)"},
        ]},
    ]
    ep = tmp_path / "rules-corridor-9"
    ep.mkdir()
    (ep / "decisions.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return ep


def test_questions_are_rebuilt_as_they_were_sent(tmp_path):
    qs = list(questions(recording(tmp_path) / "decisions.jsonl"))
    assert [(q[0], q[1], q[2]) for q in qs] == [(0, "rule", "root"), (0, "rule", "r1"), (0, "rule", "aim"),
                                                (1, "rule", "root"), (1, "focus", "r3")]
    root, r1, aim = (q[3] for q in qs[:3])
    # The root reads the state without a focus; after the focus, the questions read its line at the end.
    assert root == STATE and r1 == aim == STATE + "\n\n[focus]\n" + FOCUS_LINE


def test_the_text_settles_the_root_the_aim_band_r1_and_the_goal():
    focused = STATE + "\n\n[focus]\n" + FOCUS_LINE
    assert settled("rule", "root", STATE, ROOT) == {"r1"} and settled("rule", "root", EMPTY, ROOT) == {"r3"}
    assert settled("rule", "aim", focused, AIM) == {"r4"}
    assert settled("rule", "aim", focused.replace("6 deg right", "15 deg left"), AIM) == {"r9"}
    assert settled("rule", "aim", focused.replace("6 deg right", "1 deg left"), AIM) == {NONE}
    # On a band's edge both bands hold: left out.
    assert settled("rule", "aim", focused.replace("6 deg right", "7 deg right"), AIM) is None
    assert settled("rule", "r1", focused, R1) == {NONE}
    far_and_fruitless = focused.replace("distance 185", "distance 512").replace(
        "dealt since the last decision 0", "dealt since the last decision 0; the last 6 decisions in which you fired hit nothing")
    assert settled("rule", "r1", far_and_fruitless, R1) == {"r2", "r11"}
    assert settled("focus", "r3", EMPTY, {"i0": "Shotgun (weapon): 203 away", "i1": "GreenArmor (armor): 1328 away"}) == {"i1"}
    # A judgement is compared, not scored.
    assert settled("focus", "r1", focused, {"i0": "a", "i1": "b"}) is None


def test_compare_scores_both_models_against_the_text(tmp_path):
    ep = recording(tmp_path)
    # A decider that always says no condition holds: right only where nothing holds.
    fake = FakeD1(scripted(by_text("nothing at all")), decider="laya")
    client = D1UltraClient(api_key="", decider="laya", transport=fake, max_workers=1)
    result = compare(client, [ep])
    client.shutdown()
    assert all(p["model"] == "english" and "assets" not in p for _, p in fake.calls)
    assert result["all"] | {"chance": None} == {"questions": 5, "missed": 0, "agree_with_jev": 1, "settled": 5,
                                                 "jev_right": 5, "right": 1, "chance": None}
    assert result["by_question"]["rule:r1"]["right"] == 1 and result["answered_by"] == {"laya-rl-agent": 5}

    out = io.StringIO()
    fake = FakeD1(scripted(by_text("nothing at all")), decider="laya")
    with redirect_stdout(out):
        code = main([str(tmp_path / "out.json"), "--episodes", str(ep)],
                    client=D1UltraClient(api_key="", decider="laya", transport=fake, max_workers=1))
    assert code == 0 and json.loads((tmp_path / "out.json").read_text())["all"]["right"] == 1
    assert out.getvalue().splitlines()[-1].startswith("all             5 asked,    1 as Jev")
