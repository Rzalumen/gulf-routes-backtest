#!/usr/bin/env python3
"""Read one adsb.lol globe_history day (tar stream on stdin), keep military / VIP aircraft only,
and write compact events: hex,type,reg,ownOp,callsign,time_min,lat,lon,alt (alt -1 = ground).
Low points (<= 1,500 ft) within 6 km of an airfield are kept, but a stay at the same airfield is merged into its
first and last point (parked / taxiing planes report every few seconds). The first point at/above 3,000 ft after
each low point is kept as the take-off marker. Same airfield list and distance as the bot (airports.json)."""
import sys, tarfile, gzip, json, csv, math, collections
VIP_REGS = {'4X-ISR', 'EP-GDS', 'EP-PLN', 'A7-MHH'}
LOW, AIR, APT_KM = 1500, 3000, 6
grid = collections.defaultdict(list)
for a in json.load(open('airports.json')):
    grid[(int(a[2] // 100), int(a[3] // 100))].append(a)
def near(lat, lon):
    best, bd, k = None, APT_KM, math.cos(math.radians(lat))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for a in grid.get((math.floor(lat) + dy, math.floor(lon) + dx), []):
                d = math.hypot((a[2] / 100 - lat) * 111.2, (a[3] / 100 - lon) * 111.2 * k)
                if d < bd: bd, best = d, a
    return best
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
    base, cs, low, code, last, lastg = j.get('timestamp', 0), '', True, None, None, None   # low=True at day start: a take-off that
    # crosses midnight UTC still gets its first 3,000 ft+ point written (review 25 Oct 2026: such legs were lost)
    def row(tm, lat, lon, alt):
        return [hx, t, reg, own, cs, tm, round(lat, 4), round(lon, 4), alt]
    def flush():                                       # last on-the-ground point, then the last point of the stay
        if lastg is not None and lastg is not last: w.writerow(lastg)
        if last is not None: w.writerow(last)
    for p in j.get('trace') or []:
        if len(p) > 8 and isinstance(p[8], dict) and p[8].get('flight'):
            cs = str(p[8]['flight']).strip() or cs
        a = 0 if p[3] == 'ground' else p[3]
        if not isinstance(a, (int, float)) or not isinstance(p[1], (int, float)):
            continue
        tm = round((base + p[0]) / 60, 1)
        if a <= LOW:
            ap = near(p[1], p[2])
            if not ap:
                continue
            alt = -1 if p[3] == 'ground' else int(a)
            if ap[1] == code and low:                  # still at the same airfield: just remember the latest points
                last = row(tm, p[1], p[2], alt)
                if alt == -1: lastg = last
                continue
            flush(); last = lastg = None               # close the previous stay
            w.writerow(row(tm, p[1], p[2], alt)); code, low = ap[1], True
        elif a >= AIR and low:
            flush(); last = lastg = None
            w.writerow(row(tm, p[1], p[2], int(a))); low, code = False, None
    flush()
