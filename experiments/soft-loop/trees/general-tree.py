"""The general tree: goals at the top, a focus Jev picks, one shared aiming skill. No enemy names, no map facts."""
import json, sys
from pathlib import Path

def node(nid, parent, condition, action, focus=None):
    n = {"id": nid, "parent": parent, "condition": condition, "action": action, "children": [], "cornerstones": [],
         "meta": {"why": "general rewrite of the v2 tree"}}
    if focus:
        n["focus"] = focus
    return n

T = {}
def add(n):
    T[n["id"]] = n
    if n["parent"]:
        T[n["parent"]]["children"].append(n["id"])

add(node("root", None, None, "random"))
add(node("r1", "root", "The threats list shows at least one enemy.", {"skill": "aim", "then": "0001"},
         {"from": ["threats"], "question": "Which of these enemies is the biggest danger to me right now?"}))
add(node("r2", "r1", "The focus channel says the enemy is more than 400 units away.", {"skill": "aim", "then": "F001"}))
add(node("r3", "root", "The threats list says no enemy is visible.", {"skill": "aim", "then": "F000"},
         {"from": ["landmarks"], "question": "Which of these is the goal I am trying to reach?"}))
add(node("aim", None, None, "then"))
bands = [("between 3 and 7", 3), ("between 7 and 12", 5), ("more than 12", 7)]
k = 4
for side, key in (("right", "R"), ("left", "L")):
    for words, tics in bands:
        add(node(f"r{k}", "aim", f"The focus channel says it is {words} degrees to the {side}.", f"00{key}0:{tics}"))
        k += 1
out = Path(sys.argv[1]) / "tree.json"
out.write_text(json.dumps(T))
print("wrote", out)
