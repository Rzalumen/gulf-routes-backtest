#!/usr/bin/env python3
"""Read one adsb.lol globe_history day (tar stream on stdin), keep military / VIP aircraft only,
and write compact events: hex,type,reg,ownOp,callsign,time_min,lat,lon,alt (alt -1 = ground).
Only points at or below 1,500 ft and the first point at/above 3,000 ft after each low point are kept."""
import sys, tarfile, gzip, json, csv
VIP_REGS = {'4X-ISR', 'EP-GDS', 'EP-PLN', 'A7-MHH'}
LOW, AIR = 1500, 3000
w = csv.writer(sys.stdout)
tf = tarfile.open(fileobj=sys.stdin.buffer, mode='r|')
for m in tf:
    if not m.isfile() or '/traces/' not in '/' + m.name or 'trace_full_' not in m.name:
        continue
    raw = tf.extractfile(m).read()
    try:
        j = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    except Exception:
        continue
    reg = str(j.get('r') or '').upper()
    if not ((j.get('dbFlags') or 0) & 1 or reg in VIP_REGS or reg.startswith('EP-IG')):
        continue
    hx, t, own = str(j.get('icao', '')).lower().lstrip('~'), j.get('t') or '', j.get('ownOp') or ''
    base, cs, low = j.get('timestamp', 0), '', False
    for p in j.get('trace') or []:
        if len(p) > 8 and isinstance(p[8], dict) and p[8].get('flight'):
            cs = str(p[8]['flight']).strip() or cs
        a = 0 if p[3] == 'ground' else p[3]
        if not isinstance(a, (int, float)) or not isinstance(p[1], (int, float)):
            continue
        tm = round((base + p[0]) / 60, 1)
        if a <= LOW:
            w.writerow([hx, t, reg, own, cs, tm, round(p[1], 4), round(p[2], 4), -1 if p[3] == 'ground' else int(a)]); low = True
        elif a >= AIR and low:
            w.writerow([hx, t, reg, own, cs, tm, round(p[1], 4), round(p[2], 4), int(a)]); low = False
