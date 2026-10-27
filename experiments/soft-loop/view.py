import json, sys, re
t = json.load(open(sys.argv[1]))['trace']
lo = int(sys.argv[2]) if len(sys.argv) > 2 else max(0, len(t) - 14)
hi = int(sys.argv[3]) if len(sys.argv) > 3 else len(t)
for r in t[lo:hi]:
    x = r['text']
    th = x[x.index('[threats]') + 10:x.index('[incoming]')].strip().split('\n')
    th = ' ; '.join(l.strip('- ').replace(' at distance', '').replace(', size', ' sz').split(', under')[0] + (' XHAIR' if 'crosshair' in l else '') for l in th[1:]) or th[0]
    inc = re.search(r'damage taken since the last decision (\d+)', x).group(1)
    def short(p):
        if 'skill' in p: return p['skill']
        if 'focus' in p: return 'F[' + ','.join((p['pick'] or 'nothing').split(',')[:2]).replace(' at distance', '') + ']'
        return p['pick'] + f"({p['p']})"
    path = '>'.join(short(p) for p in r['path'])
    print(f"{r['i']:3d} {r['code']:<14} {r['node']:<5} hp{r['health_before']:.0f}->{r['health_after']:.0f} x{r.get('x')} | {th} | {path} {r['events'] or ''}")
