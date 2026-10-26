#!/usr/bin/env python3
"""Join all day event files, replay each aircraft in time order with the bot's route rules
(start = airfield where on the ground / below 1,500 ft within 6 km; leg = next different airfield within 30 h
after being airborne 3,000 ft+), and write legs.csv + routes.json (same key style as the bot: hex|TYPE|FROM>TO counts)."""
import sys, csv, json, math, glob, collections
APT_KM, LOW, AIR, MAX_MIN = 6, 1500, 3000, 30 * 60
apts = json.load(open('airports.json'))   # the bot's own ACW_APTS list: [name, code, lat*100, lon*100]
grid = collections.defaultdict(list)
for a in apts:
    grid[(int(a[2] // 100), int(a[3] // 100))].append(a)
def near(lat, lon):
    best, bd, k = None, APT_KM, math.cos(math.radians(lat))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for a in grid.get((math.floor(lat) + dy, math.floor(lon) + dx), []):
                d = math.hypot((a[2] / 100 - lat) * 111.2, (a[3] / 100 - lon) * 111.2 * k)
                if d < bd: bd, best = d, a
    return best
rows = []
for f in sorted(glob.glob('events/*.csv')):
    for r in csv.reader(open(f)):
        rows.append(r)
rows.sort(key=lambda r: (r[0], float(r[5])))
legs, st, lastcs = [], {}, {}
for hx, t, reg, own, cs, tm, lat, lon, alt in rows:
    tm, lat, lon, alt = float(tm), float(lat), float(lon), int(alt)
    if cs: lastcs[hx] = cs
    s = st.get(hx)
    if alt >= AIR:
        if s: s[2] = 1; s[3] = tm
        continue
    a = near(lat, lon)
    if not a: continue
    code = a[1]
    if s and s[0] != code and s[2] and tm - s[1] <= MAX_MIN:
        legs.append([hx, t, reg, own, lastcs.get(hx, ''), s[0], code, int(tm // 1440), int(tm)])
    if not s or s[2] or (s[0] != code and alt == -1): st[hx] = [code, tm, 0, tm]
    elif s[0] == code: s[1] = tm; s[3] = tm
# CENTCOM = these ICAO prefixes, or OurAirports local idents of these countries (e.g. AE-0026)
CENTCOM_ICAO = ('OA', 'OB', 'HE', 'OI', 'OR', 'LL', 'OJ', 'OK', 'OL', 'OO', 'OP', 'OT', 'OE', 'OS', 'OM', 'OY', 'UA', 'UC', 'UT')
CENTCOM_ISO = ('AF', 'BH', 'EG', 'IR', 'IQ', 'IL', 'JO', 'KW', 'LB', 'OM', 'PK', 'QA', 'SA', 'SY', 'AE', 'YE', 'KZ', 'KG', 'TJ', 'TM', 'UZ')
APT_POS = {a[1]: (a[2] / 100, a[3] / 100) for a in apts}
def centcom(code):
    if len(code) == 4 and code.isalpha():
        return code[:2] in CENTCOM_ICAO
    if len(code) == 4 and code[:2] in CENTCOM_ICAO and code[:2].isalpha():   # OP12, OY74, HE16, UT1G … (review 25 Oct 2026)
        la, lo = APT_POS.get(code, (0, 0))
        return 10 <= la <= 46 and 24 <= lo <= 80
    return code.split('-')[0] in CENTCOM_ISO
FEED_MIN = 7 * 1440                       # earlier legs up to 7 days before entering CENTCOM count as feeders
entries = collections.defaultdict(list)   # hex -> times it landed in CENTCOM from outside
for l in legs:
    if centcom(l[6]) and not centcom(l[5]): entries[l[0]].append(l[8])
def keep(l):
    if centcom(l[5]) or centcom(l[6]): return True
    return any(0 <= e - l[8] <= FEED_MIN for e in entries.get(l[0], []))
kept = [l for l in legs if keep(l)]
head = ['hex', 'type', 'reg', 'ownOp', 'callsign', 'from', 'to', 'day', 'time_min']
for name, rows_ in (('legs_all.csv', legs), ('legs.csv', kept)):
    with open(name, 'w', newline='') as f:
        csv.writer(f).writerows([head] + rows_)
agg = {}
for hx, t, reg, own, cs, fr, to, day, tmin in kept:
    k = hx + '|' + (t or '?').upper() + '|' + fr + '>' + to
    e = agg.setdefault(k, [0, day, cs, own]); e[0] += 1
    if day >= e[1]: e[1] = day; e[2] = cs or e[2]
json.dump(agg, open('routes.json', 'w'), separators=(',', ':'))
print(len(rows), 'events', len(legs), 'legs worldwide', len(kept), 'CENTCOM + feeder legs', len(agg), 'hex-routes')
