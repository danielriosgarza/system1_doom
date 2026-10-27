import json, sys
r = json.load(open(sys.argv[1]))
def short(p):
    if "skill" in p: return ("skill", p["skill"])
    if "focus" in p: return ("focus", ",".join((p["pick"] or "nothing").split(",")[:2]), p["p"])
    return (p.get("at") or p.get("menu"), p["pick"], p["p"])
print(r["rule"], "under", r["attach_to"], "PASS" if r["pass"] else "FAIL", "calls", r["jev_calls"])
print(" sees", r["sees"]["pass"], [short(p) for p in r["sees"]["path"]])
print(" unchanged", r["unchanged"]["pass"], r["unchanged"]["cornerstones"], r["unchanged"]["changed"])
a = r["avoids"]
print(" avoids", a["pass"], a["at_horizon"], "first event", a["first_event_after"], "end", a["end"])
print("  ", a["actions"][:500])
