#!/usr/bin/env python3
"""Backtest the routine/unusual labels: for each test day D, build patterns.json from data BEFORE D only,
then label every US military airframe airborne inside CENTCOM on D (its first CENTCOM point of the day).
Usage: [REGION=C|E] [PATTERNS_PY=…/map/patterns.py] backtest_patterns.py <air dir> <events dir> <legs_all.csv.gz> <day> …
REGION C = CENTCOM box (default), E = Europe / Atlantic. Results 2 Nov 2026: Oct 2026 0–7 % new/unusual;
18 Feb 2026 (build-up) Europe/Atlantic 29 of 115 US airframes first-time + 10 back after a gap."""
import sys, os, csv, gzip, json, subprocess, collections, importlib.util
REPO = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('pt', os.environ.get('PATTERNS_PY', '../map-service/map/patterns.py'))  # map-service checkout
pt = importlib.util.module_from_spec(spec); spec.loader.exec_module(pt)
air, ev, legs = sys.argv[1:4]
US = lambda h: 'adf7c8' <= h <= 'afffff'
BOX = (lambda la, lo: 10 <= la <= 42 and 25 <= lo <= 75) if os.environ.get('REGION', 'C') == 'C' else (lambda la, lo: lo < 25 and la > 25)
res = {}
for D in sys.argv[4:]:
    out = '/tmp/pat-%s.json' % D
    if not os.path.exists(out):
        subprocess.run(['python3', REPO + '/make_patterns.py', air, ev, legs, out], check=True,
                       env=dict(os.environ, UPTO=D), stdout=subprocess.DEVNULL)
    P = json.load(open(out))
    f = os.path.join(air, 'air-%s.csv.gz' % D)
    if not os.path.exists(f):
        print(D, 'no air file'); continue
    pts = {}
    for r in csv.reader(gzip.open(f, 'rt')):
        h = r[0].lower().lstrip('~')
        la, lo = float(r[5]), float(r[6])
        if US(h) and BOX(la, lo) and h not in pts:
            pts[h] = (r[1], la, lo, r[3])
    kinds = collections.Counter(); ex = []
    for h, (t, la, lo, cs) in sorted(pts.items()):
        L = pt.label(P, h, t, la, lo)
        k = L['kind'] or 'none'; kinds[k] += 1
        ex.append((k, h, t, cs, round(la, 1), round(lo, 1), ' | '.join(L['lines'])))
    n = sum(kinds.values())
    print('%s  US airframes %d  %s  unusual+new %d%%' % (D, n, dict(kinds),
          round(100 * (kinds['unusual'] + kinds['new']) / max(n, 1))))
    res[D] = ex
json.dump(res, open('/tmp/bt_result.json', 'w'), indent=0)
