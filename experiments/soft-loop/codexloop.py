"""The soft loop with Codex as System 2: Codex writes every rule; this script only plays, checks and gates.

  python codexloop.py RUN --start trees/general-9.json --train 9-19 --held 20-39 --rounds 12

Each round plays the training seeds with fresh Jev answers. If every seed clears, the held-out seeds are played
and the run stops. Otherwise the first failure not tried before goes to Codex with the rule-writer prompt and the
failure's dossier. Its proposal is checked; a failed check goes back to Codex with the report (three attempts per
failure). A rule that passes its check is gated on the training seeds and committed if the gate passes.
Everything Codex was sent and answered, and every report, is kept under runs/RUN/codex/.

Codex is called once per attempt, without memory between calls: each prompt carries the earlier attempts on the
same failure and their reports. The command reads the prompt on stdin and must leave Codex's last message in the
file `{out}`; set CODEX_CMD to change it, for example to pick a model.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import softloop as S  # noqa: E402

CODEX_CMD = os.environ.get("CODEX_CMD", "codex exec --skip-git-repo-check --sandbox read-only --output-last-message {out} -")
ATTEMPTS = 3


def seeds(spec):
    lo, hi = map(int, spec.split("-"))
    return list(range(lo, hi + 1))


def log(run_dir, **row):
    row["time"] = time.strftime("%H:%M:%S")
    with (run_dir / "codex" / "log.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)


def softloop(*args):
    """Run a softloop.py command; return its standard output."""
    out = subprocess.run([sys.executable, str(HERE / "softloop.py"), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"softloop {' '.join(args)} failed:\n{out.stdout[-2000:]}\n{out.stderr[-2000:]}")
    return out.stdout


def summary(report):
    """A check report in the few lines the rule writer needs."""
    def step(p):
        if "skill" in p:
            return f"skill {p['skill']}"
        if "focus" in p:
            return f"focus picked {p['pick']!r} ({p['p']})"
        return f"at {p.get('at') or p.get('menu')} picked {p['pick']} ({p['p']})"
    a = report["avoids"]
    lines = [f"check: {'PASS' if report['pass'] else 'FAIL'} (your rule became {report['rule']}, attached under {report['attach_to']})",
             f"sees: {'pass' if report['sees']['pass'] else 'FAIL'}; the walk at your frame: " + "; ".join(step(p) for p in report["sees"]["path"]),
             f"unchanged: {'pass' if report['unchanged']['pass'] else 'FAIL'}; earlier frames that now take another route: {report['unchanged']['changed'] or 'none'}",
             f"avoids: {'pass' if a['pass'] else 'FAIL'}; standing at decision {a['horizon']} as (alive, goal reached, health, furthest point): "
             f"old tree {a['at_horizon']['old_tree']}, new tree {a['at_horizon']['new_tree']}; first unwanted event with your rule: {a['first_event_after']}",
             f"the new tree's decisions from your frame (decision:action:node): {a['actions'][:1500]}"]
    return "\n".join(lines)


def ask_codex(run_dir, name, prompt):
    """One Codex call: the prompt on stdin, its last message read back from a file."""
    d = run_dir / "codex"
    (d / f"{name}.prompt.md").write_text(prompt)
    out = d / f"{name}.answer.txt"
    cmd = [part.replace("{out}", str(out)) for part in shlex.split(CODEX_CMD)]
    t0 = time.time()
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=HERE, timeout=1800)
    (d / f"{name}.stdout.txt").write_text(proc.stdout[-200000:] + "\n--- stderr ---\n" + proc.stderr[-20000:])
    answer = out.read_text() if out.exists() and out.read_text().strip() else proc.stdout
    return answer, round(time.time() - t0)


def parse(answer):
    """The JSON object in Codex's answer (bare, or in a fenced block)."""
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", answer, re.S)
    candidates = blocks + [answer[answer.find("{"): answer.rfind("}") + 1]]
    for c in candidates:
        try:
            return json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue
    raise ValueError("no JSON object in the answer")


def instructions():
    text = (HERE / "rule-writer-prompt.md").read_text()
    return text.split("\n---\n", 1)[1] if "\n---\n" in text else text


def prompt_for(run, trace, history):
    dossier = (S.BASE / run / trace / "dossier.md").read_text()
    parts = [instructions(),
             "\n---\n\n# The failure\n",
             f"The dossier below is also at runs/{run}/{trace}/dossier.md; its frames are the frame-NNN.jpg files in "
             f"that folder, and you may open them. The current rule tree is in runs/{run}/tree.json. "
             "Answer with the JSON only.\n",
             dossier]
    if history:
        parts.append("\n# Your earlier attempts on this failure, and what the program said\n")
        for i, (proposal, verdict) in enumerate(history, 1):
            parts.append(f"## attempt {i}\n```json\n{json.dumps(proposal, indent=1)}\n```\n{verdict}\n")
        parts.append("Write a new proposal that addresses what the program said.")
    return "\n".join(parts)


def attempt_failure(run, train, failure, n):
    """Up to three Codex proposals for one failure; returns True if a rule was committed."""
    run_dir = S.BASE / run
    trace = failure["trace"]
    history = []
    for k in range(1, ATTEMPTS + 1):
        name = f"f{n:02d}-{trace}-a{k}"
        answer, secs = ask_codex(run_dir, name, prompt_for(run, trace, history))
        try:
            proposal = parse(answer)
        except ValueError as e:
            log(run_dir, step="answer", name=name, seconds=secs, error=str(e))
            history.append(({"unparsed": answer[:2000]}, f"The program could not read a JSON object from your answer ({e})."))
            continue
        if "needs_representation" in proposal:
            log(run_dir, step="needs_representation", name=name, seconds=secs, proposal=proposal)
            return False
        proposal["trace"] = trace
        path = run_dir / "codex" / f"{name}.json"
        path.write_text(json.dumps(proposal, indent=1))
        try:
            report = json.loads(softloop("check", run, str(path)))
        except (RuntimeError, json.JSONDecodeError, AssertionError, KeyError) as e:
            log(run_dir, step="check", name=name, seconds=secs, proposal=proposal, error=str(e)[-1500:])
            history.append((proposal, f"The program could not check this proposal: {str(e)[-1500:]}"))
            continue
        verdict = summary(report)
        (run_dir / "codex" / f"{name}.check.txt").write_text(verdict)
        log(run_dir, step="check", name=name, seconds=secs, proposal=proposal, passed=report["pass"])
        if not report["pass"]:
            history.append((proposal, verdict))
            continue
        gate_out = softloop("gate", run, str(path), f"{train[0]}-{train[-1]}")
        (run_dir / "codex" / f"{name}.gate.txt").write_text(gate_out)
        gate = json.loads(gate_out.strip().splitlines()[-1])
        log(run_dir, step="gate", name=name, **gate)
        if not gate["pass"]:
            history.append((proposal, verdict + "\n\ngate: FAIL. Played on every training seed, the current tree cleared "
                            f"{gate['current']} and the tree with your rule {gate['with_rule']} of {gate['of']}:\n" + gate_out))
            continue
        softloop("commit", run, str(path))
        log(run_dir, step="commit", name=name, tree="\n".join(S.tree_lines(S.load_tree(run_dir))))
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run")
    ap.add_argument("--start", help="a tree.json to start from (only when the run is new)")
    ap.add_argument("--train", default="9-19")
    ap.add_argument("--held", default="20-39")
    ap.add_argument("--rounds", type=int, default=12)
    args = ap.parse_args()
    run_dir = S.BASE / args.run
    (run_dir / "codex").mkdir(parents=True, exist_ok=True)
    if not (run_dir / "tree.json").exists():
        shutil.copy(args.start, run_dir / "tree.json")
    train, held = seeds(args.train), seeds(args.held)
    for r in range(1, args.rounds + 1):
        results = S.play_all([(args.run, s) for s in train])
        cleared = [x for x in results if x["event"] == "cleared"]
        log(run_dir, step="pass", round=r, cleared=len(cleared), of=len(train),
            failures=[f"seed {x['seed']}: {x['event']} at {x.get('decisions')} ({x.get('trace')})" for x in results if x["event"] != "cleared"])
        if len(cleared) == len(train):
            held_results = S.play_all([(args.run, s) for s in held])
            log(run_dir, step="held-out", cleared=sum(x["event"] == "cleared" for x in held_results), of=len(held),
                failures=[f"seed {x['seed']}: {x['event']} ({x.get('trace')})" for x in held_results if x["event"] != "cleared"])
            break
        # The first failure of this pass, by seed; every pass is a fresh game, so a failure is never repeated.
        failure = next((x for x in results if x["event"] not in ("cleared", "crashed")), None)
        if failure is None:
            log(run_dir, step="stop", reason="every seed that did not clear crashed")
            break
        attempt_failure(args.run, train, failure, r)
    log(run_dir, step="done", tree="\n".join(S.tree_lines(S.load_tree(run_dir))))


if __name__ == "__main__":
    main()
