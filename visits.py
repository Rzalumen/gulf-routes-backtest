#!/usr/bin/env python3
"""Airfield visit log from backtest day events (not legs).
A visit = one aircraft seen low (on the ground, or below 1,500 ft) within 6 km of a listed airfield;
points at the same field less than 90 min apart join one visit.
Usage: visits.py <events_dir> <airports.json> <out.csv>"""
import sys, csv, gzip, glob, json, math, collections, os, datetime
ev_dir, apt_file, out = sys.argv[1:4]
APT_KM, LOW, GAP = 6, 1500, 90
apts = json.load(open(apt_file))
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
TANK = {'K35R', 'KC135', 'K35E', 'KC46', 'KC10', 'DC10', 'A332', 'A330', 'MRTT', 'KC30', 'K30', 'A400', 'KC2', 'KC39'}
LIFT = {'C17', 'C5', 'C5M', 'C130', 'C30J', 'C27J', 'B742', 'B744', 'B748', 'B763', 'B772', 'B77L', 'B77W', 'MD11', 'A124', 'IL76', 'C2'}
VIP = {'C32', 'B752', 'VC25', 'B748', 'C37', 'GLF5', 'GLF6', 'GL5T', 'C40', 'B737', 'B738', 'B739', 'C21', 'LJ35', 'C12', 'B350', 'GLEX', 'F900', 'FA7X', 'A319', 'A320', 'A321', 'A20N', 'A21N', 'BCS3', 'C35', 'C560', 'E35L', 'CL60'}
def role(t, cs):
    t = (t or '').upper(); c = (cs or '').upper()
    if t in TANK or c.startswith(('PEARL', 'NKAC', 'SHELL', 'BLUE', 'GOLD', 'ETHYL', 'ESSO', 'QUID', 'LAGR', 'PACK', 'TEAL', 'MOBIL', 'DECOY')): return 'tanker'
    if c.startswith(('SAM', 'EXEC', 'VENUS', 'SPAR', 'AF1', 'AF2', 'ORDER', 'CODY')): return 'vip'
    if t in LIFT or c.startswith(('RCH', 'REACH', 'MC', 'CNV', 'ATLAS')): return 'airlift'
    if t in VIP: return 'vip?'
    return ''
open_v, done = {}, []
for f in sorted(glob.glob(os.path.join(ev_dir, 'events-*.csv.gz'))):
    rows = list(csv.reader(gzip.open(f, 'rt')))
    rows.sort(key=lambda r: (r[0], float(r[5])))
    for hx, t, reg, own, cs, tm, lat, lon, alt in rows:
        tm, lat, lon, alt = float(tm), float(lat), float(lon), int(alt)
        v = open_v.get(hx)
        if v and cs: v['cs'].add(cs)
        if alt > LOW and alt != -1: continue
        a = near(lat, lon)
        if not a: continue
        if v and v['apt'] == a[1] and tm - v['last'] <= GAP:
            v['last'] = tm; v['n'] += 1; v['gnd'] |= alt == -1; v['minalt'] = min(v['minalt'], max(alt, 0))
            if cs: v['cs'].add(cs)
            continue
        if v: done.append(v)
        open_v[hx] = {'hex': hx, 'type': t, 'reg': reg, 'own': own, 'cs': {cs} if cs else set(), 'apt': a[1], 'name': a[0],
                      'first': tm, 'last': tm, 'n': 1, 'gnd': alt == -1, 'minalt': max(alt, 0)}
done += open_v.values()
def ts(m): return datetime.datetime.utcfromtimestamp(m * 60).strftime('%Y-%m-%d %H:%M')
done.sort(key=lambda v: v['first'])
with open(out, 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['first_utc', 'last_utc', 'airfield', 'code', 'hex', 'type', 'reg', 'operator', 'callsigns', 'role', 'on_ground', 'min_alt_ft', 'points'])
    for v in done:
        cs = ' '.join(sorted(v['cs']))
        w.writerow([ts(v['first']), ts(v['last']), v['name'], v['apt'], v['hex'], v['type'], v['reg'], v['own'], cs,
                    role(v['type'], cs.split(' ')[0] if cs else ''), int(v['gnd']), v['minalt'], v['n']])
print(len(done), 'visits')
