"""Rule-writer's workbench: replay a trace to decision k, then try fixed action sequences and print what follows."""
import json, sys
import vizdoom as vzd
from softloop import Game
trace_path, k = sys.argv[1], int(sys.argv[2])
seqs = sys.argv[3:]
t = json.load(open(trace_path)); seed, tr = t['seed'], t['trace']
g = Game()
V = lambda n: g.g.get_game_variable(getattr(vzd.GameVariable, n))
for seq in seqs:
    acts = []
    for part in seq.split(','):
        a, _, n = part.partition('*')
        acts += [a] * int(n or 1)
    g.reset(seed)
    for r in tr[:k]:
        g.observe(); g.step(r['code'])
    out = []
    for a in acts:
        g.observe(); rec = g.step(a)
        if rec['died']:
            out.append('DEAD'); break
        if rec['finished']:
            out.append('END'); break
        out.append(f"{rec['health_after']:.0f}/{rec['kills']:.0f}k/{rec['x']}")
    print(f"{seq:40s} {' '.join(out)}")
