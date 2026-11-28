#!/usr/bin/env python3
"""Read one adsb.lol globe_history day (tar stream on stdin), keep military / VIP aircraft only,
and write compact events: hex,type,reg,ownOp,callsign,time_min,lat,lon,alt (alt -1 = ground).
Low points (<= 1,500 ft) within 6 km of an airfield are kept, but a stay at the same airfield is merged into its
first and last point (parked / taxiing planes report every few seconds). The first point at/above 3,000 ft after
each low point is kept as the take-off marker. Same airfield list and distance as the bot (airports.json).
27 Nov 2026 (audit item 45): "low" and "3,000 ft" are measured ABOVE THE AIRFIELD (airports_elev.json, OurAirports elevations of 300 ft+;
sea level before, so no landing was ever counted at Muwaffaq Salti 1,706 ft, Prince Sultan 1,651 ft or Riyadh 2,049 ft). The alt column of a
low point is now the height above the airfield (0-1,500), so every reader of the events files keeps its "under 3,000 = low" rule."""
import sys, tarfile, gzip, json, csv, math, collections
VIP_REGS = {'4X-ISR', 'EP-GDS', 'EP-PLN', 'A7-MHH'}
LOW, AIR, APT_KM = 1500, 3000, 6
grid = collections.defaultdict(list)
for a in json.load(open('airports.json')):
    grid[(int(a[2] // 100), int(a[3] // 100))].append(a)
try: ELEV = json.load(open('airports_elev.json'))
except Exception: ELEV = {}
ELEV_MAX = max(ELEV.values(), default=0)
def near(lat, lon):
    best, bd, k = None, APT_KM, math.cos(math.radians(lat))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for a in grid.get((math.floor(lat) + dy, math.floor(lon) + dx), []):
                d = math.hypot((a[2] / 100 - lat) * 111.2, (a[3] / 100 - lon) * 111.2 * k)
                if d < bd: bd, best = d, a
    return best
w = csv.writer(sys.stdout)
import os
COV = os.environ.get('COV_OUT')   # coverage control (27 Oct 2026): ALL aircraft per region, civil included, and how many were MLAT-located
def creg(lat, lon):
    if 10 <= lat <= 42 and 25 <= lon <= 75: return 'CENTCOM'
    if 34 <= lat <= 72 and -12 <= lon < 25: return 'EUROPE'
    if 20 <= lat <= 72 and -60 <= lon < -12: return 'ATLANTIC'
    if lon < -60: return 'AMERICAS'
    return 'OTHER'
AIR_OUT = os.environ.get('AIR_OUT')   # airborne track points (2 Nov 2026, the owner: enough history for routine vs unusual):
# one point per aircraft per 15 min while >= 3,000 ft, Diego Garcia / CENTCOM / Europe / Atlantic only. events stay unchanged.
afh = gzip.open(AIR_OUT, 'wt') if AIR_OUT else None
aw = csv.writer(afh) if afh else None
def abox(lat, lon):
    return -12 <= lat <= 72 and -60 <= lon <= 80
cov = collections.defaultdict(lambda: [0, 0, 0])   # region -> [aircraft, of them civil, of them seen by MLAT]
tf = tarfile.open(fileobj=sys.stdin.buffer, mode='r|')
for m in tf:
    if not m.isfile() or '/traces/' not in '/' + m.name or 'trace_full_' not in m.name:
        continue
    raw = tf.extractfile(m).read()
    try:
        j = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    except Exception:
        continue
    if COV:
        rs, ml = set(), set()
        for p in j.get('trace') or []:
            if isinstance(p[1], (int, float)) and isinstance(p[3], (int, float)) and p[3] >= 3000:
                rg = creg(p[1], p[2]); rs.add(rg)
                if len(p) > 9 and isinstance(p[9], str) and p[9].startswith('mlat'): ml.add(rg)
        for rg in rs:
            c = cov[rg]; c[0] += 1; c[1] += 0 if (j.get('dbFlags') or 0) & 1 else 1; c[2] += rg in ml
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
    ab = None
    for p in j.get('trace') or []:
        if len(p) > 8 and isinstance(p[8], dict) and p[8].get('flight'):
            cs = str(p[8]['flight']).strip() or cs
        a = 0 if p[3] == 'ground' else p[3]
        if not isinstance(a, (int, float)) or not isinstance(p[1], (int, float)):
            continue
        tm = round((base + p[0]) / 60, 1)
        if aw and a >= AIR and int(tm // 15) != ab and abox(p[1], p[2]):
            ab = int(tm // 15); aw.writerow([hx, t, reg, cs, tm, round(p[1], 3), round(p[2], 3), int(a)])
        ap = near(p[1], p[2]) if a <= LOW + ELEV_MAX else None
        el = ELEV.get(ap[1], 0) if ap else 0
        if a <= LOW and not ap:
            continue
        if ap and (p[3] == 'ground' or a <= LOW + el):
            alt = -1 if p[3] == 'ground' else max(0, int(a - el))
            if ap[1] == code and low:                  # still at the same airfield: just remember the latest points
                last = row(tm, p[1], p[2], alt)
                if alt == -1: lastg = last
                continue
            flush(); last = lastg = None               # close the previous stay
            w.writerow(row(tm, p[1], p[2], alt)); code, low = ap[1], True
        elif a >= AIR + ELEV.get(code, 0) and low:
            flush(); last = lastg = None
            w.writerow(row(tm, p[1], p[2], int(a))); low, code = False, None
    flush()
if COV:
    json.dump({k: {'aircraft': v[0], 'civil': v[1], 'mlat': v[2]} for k, v in cov.items()}, open(COV, 'w'))
if afh: afh.close()
