# Soft loop

System 2 wires System 1 one failure at a time. The agent plays until something unwanted happens (it dies, or
it stops making progress). A rule writer then proposes one rule Jev could have used at that moment: a condition
Jev judges from the state, and an action. A program checks the rule by replaying the game, gates it on every
training seed, and adds it to a tree of nested exceptions (Ripple-Down Rules). Then the agent plays again.
The engine only plays and replays; Jev never sees it, and no hand-written rule decides anything.

`NOTES.md` has the three stages so far. In the third stage, 11 general rules (no monster names, no map facts)
cleared the training seeds 22 of 22, the held-out seeds 20 to 39 39 of 40, and new seeds 40 to 59 18 of 20.

## Files

- `softloop.py`: `play RUN SEED`, `check RUN RULE.json`, `gate RUN RULE.json LO-HI`, `commit RUN RULE.json`,
  `show RUN`, `eval RUN LO-HI`. Runs live in `runs/RUN/` (not committed).
- `codexloop.py`: the whole loop with Codex as the rule writer.
- `rule-writer-prompt.md`: the instructions any LLM rule writer gets.
- `trees/general-9.json`: the 9-rule general tree to start from (`trees/general-tree.py` builds it).
- `view.py`, `report.py`, `seqtest.py`: print a game, print a check report, try action sequences from a frame.

## Running it

```bash
pip install -e .                     # from the repository root: vizdoom, requests, pillow, pydantic
export TYPESAFE_API_KEY=...          # or put it in the repository's .env
cd experiments/soft-loop
python softloop.py eval mytree 9-19  # needs runs/mytree/tree.json; cp trees/general-9.json there first
python codexloop.py codex1 --start trees/general-9.json --train 9-19 --held 20-39 --rounds 12
```

`codexloop.py` calls `codex exec` with the prompt on stdin and reads Codex's last message from a file. Set
`CODEX_CMD` to change the command (`{out}` is replaced by that file's path). What Codex was sent and answered,
each check report, each gate and each commit are kept in `runs/RUN/codex/`, with one line per step in `log.jsonl`.

A pass over 11 seeds takes about 90 seconds (6 games at a time, about 100 Jev calls per game at about 0.25 s).
