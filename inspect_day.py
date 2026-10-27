#!/usr/bin/env python3
"""Coverage check for one adsb.lol day (tar stream on stdin): is a jump in military aircraft over CENTCOM real,
or did the receivers change? Counts ALL aircraft (civil too) airborne over CENTCOM, by sub-area, and how their
positions were received (ADS-B / MLAT / other), plus the same for US tankers. Pattern system step 1 (27 Oct 2026)."""
import sys, tarfile, gzip, json, collections
AREAS = {'Israel/Levant': (29, 34, 33.5, 37), 'UAE/Oman': (22, 27, 51, 58), 'Qatar/Bahrain': (24, 27, 50, 52),
         'Iraq/Kuwait': (28, 37, 39, 48.5), 'Saudi': (16, 32, 36, 50), 'Red Sea/Egypt': (12, 30, 30, 43.5)}
TANK = {'K35R', 'K35E', 'B762', 'KC46', 'KC10', 'A332'}
day = sys.argv[1]
tot = collections.Counter(); src_all = collections.Counter(); src_tank = collections.Counter(); area_all = collections.Counter()
area_mil = collections.Counter(); tankers = []
tf = tarfile.open(fileobj=sys.stdin.buffer, mode='r|')
for m in tf:
    if not m.isfile() or 'trace_full_' not in m.name: continue
    raw = tf.extractfile(m).read()
    try: j = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    except Exception: continue
    hx, t, mil = str(j.get('icao', '')).lower(), str(j.get('t') or '').upper(), bool((j.get('dbFlags') or 0) & 1)
    tot['traces'] += 1
    hit, areas, srcs = False, set(), collections.Counter()
    for p in j.get('trace') or []:
        if not isinstance(p[1], (int, float)) or p[3] == 'ground' or not isinstance(p[3], (int, float)) or p[3] < 3000: continue
        la, lo = p[1], p[2]
        if not (10 <= la <= 42 and 25 <= lo <= 75): continue
        hit = True
        s = p[9] if len(p) > 9 and isinstance(p[9], str) else '?'
        srcs[s.split('_')[0]] += 1
        for a, (y0, y1, x0, x1) in AREAS.items():
            if y0 <= la <= y1 and x0 <= lo <= x1: areas.add(a)
    if not hit: continue
    tot['centcom_all'] += 1
    if mil: tot['centcom_mil'] += 1
    for a in areas:
        area_all[a] += 1
        if mil: area_mil[a] += 1
    src_all.update(srcs)
    if mil and t in TANK and hx[:2] in ('ae', 'af'):
        src_tank.update(srcs); tankers.append([hx, t, sorted(areas), dict(srcs)])
out = {'day': day, 'totals': tot, 'areas_all': area_all, 'areas_mil': area_mil,
       'sources_all_points': src_all, 'sources_us_tanker_points': src_tank, 'us_tankers': tankers}
print(json.dumps(out))
