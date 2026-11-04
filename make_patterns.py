#!/usr/bin/env python3
"""patterns.json for the map service: what is NORMAL, from the adsb.lol history (history-2025 branch).
Lets the bot say "routine" vs "unusual" with a number behind it (Reza 2 Nov 2026: "the bot should have enough
historic and backfill data to recognize routine mission vs unusual").

Usage: make_patterns.py <air dir> <events dir> <legs_all.csv[.gz]> <out.json>
Airborne presence comes from air-history (air/air-YYYY-MM-DD.csv.gz: hex,type,reg,callsign,minute,lat,lon,alt, one
point per 15 min) + the bot's own sightings (air/air-bot-YYYY-MM-DD.csv.gz, same columns, sight.yml, 3 Nov 2026) + the bot's channel
history and the DG / AA flight log (air/air-chan-*, air/air-log-*, chan_history.py / chan.yml; day-only rows have empty lat/lon) —
history-2025 events only hold take-offs / landings, so orbits over CENTCOM were missing there.
events are used only for "first seen" (back to 1 May 2025).
Output (compact; days = days since 1970-01-01, asof = newest day in the data):
  a: {hex: [d30, d90, d365, last_day, first_day, c90, [[FROM>TO, legs in 365 d], …top 3]]}   per airframe
     d30/d90/d365 = days airborne in the air-history area; c90 = days airborne inside the CENTCOM box
  c: {"GROUP|lat|lon": [d30, d90, airframes90]}   2° cells (whole air-history area), days any plane of that group flew there
  r: {"GROUP|FROM>TO": [n30, n90, n365]}          legs per route per group (both ends known)
  g: {"GROUP": days the group was seen anywhere in the area in the last 90 days}
Counts are days, not points: the first-airborne-point row that only days from 25 Oct 2026 carry cannot inflate them."""
import sys, os, csv, gzip, json, glob, collections, datetime

from types_groups import GROUPS, TG, group   # one shared list (4 Nov 2026)

def cent(lat, lon):                  # same CENTCOM box as extract_day.py creg()
    return 10 <= lat <= 42 and 25 <= lon <= 75
def cell(lat, lon):
    return '%d|%d' % (int(lat // 2) * 2, int(lon // 2) * 2)

air_dir, ev_dir, legs_path, out = sys.argv[1:5]
days_of = lambda f: (datetime.date.fromisoformat(os.path.basename(f)[-17 if f.endswith('.gz') else -14:][:10]) - datetime.date(1970, 1, 1)).days
afiles = sorted(glob.glob(os.path.join(air_dir, 'air-*.csv*')))
files = sorted(glob.glob(os.path.join(ev_dir, 'events-*.csv*')))
UPTO = os.environ.get('UPTO')                  # backtests: only data from days before UPTO (YYYY-MM-DD)
if UPTO:
    cut = (datetime.date.fromisoformat(UPTO) - datetime.date(1970, 1, 1)).days
    afiles = [f for f in afiles if days_of(f) < cut]; files = [f for f in files if days_of(f) < cut]
asof = max(days_of(f) for f in afiles)   # air-bot-* files (the bot's own sightings, 3 Nov 2026) sort after air-2026-*
seen = collections.defaultdict(set)            # hex -> airborne days
cseen = collections.defaultdict(set)           # hex -> airborne days inside CENTCOM
first = {}
cells = collections.defaultdict(lambda: [set(), set()])   # key -> [days, hexes in 90 d]
gdays = collections.defaultdict(set)
htype = {}
for f in files:                                # first seen + flying days from the worldwide take-off / landing records
    d = days_of(f)
    prev = {}
    with gzip.open(f, 'rt') if f.endswith('.gz') else open(f) as fh:
        for r in csv.reader(fh):
            if not r:
                continue
            hx = r[0].lower().lstrip('~')
            first.setdefault(hx, d)
            # The airframe flew that day, anywhere in the world (Reza 4 Nov 2026 00:40 ET: KC-135 59-1464 got "Last flight in our
            # history 3 Aug" although these records show Tinker sorties on 23 and 26 Oct and a landing on 13 Sep — the US is outside
            # the air-history box): a take-off marker (>= 3,000 ft), or a descent between two airborne points within 10 min
            # (a landing). A ground run (GNDTST at the same height) does not count. Day only: no area cell.
            if asof - d >= 365:
                continue
            try:
                m, alt = float(r[5]), float(r[8])
            except (ValueError, IndexError):
                continue
            if alt >= 3000:
                seen[hx].add(d)
            elif alt > 0:
                pm, pa = prev.get(hx, (None, None))
                if pm is not None and pa > 0 and 0 <= m - pm <= 10 and pa - alt >= 100:
                    seen[hx].add(d)
            prev[hx] = (m, alt)

for f in afiles:
    d = days_of(f)
    if asof - d >= 365:
        continue
    with gzip.open(f, 'rt') if f.endswith('.gz') else open(f) as fh:
        for r in csv.reader(fh):
            if len(r) < 8:
                continue
            hx = r[0].lower().lstrip('~')
            # flying day first: day-only rows (lat/lon empty) from the bot's channel history / flight log count for the airframe,
            # but never invent an area cell (Reza 3 Nov 2026 22:45 ET: use ALL the existing data)
            first.setdefault(hx, d)
            seen[hx].add(d)
            if r[1]: htype[hx] = r[1]
            try:
                lat, lon = float(r[5]), float(r[6])
            except ValueError:
                continue
            if asof - d < 90:                  # 2° cells over the whole air-history area (CENTCOM, Europe, Atlantic, DG)
                g = group(r[1])
                for k in (g + '|' + cell(lat, lon), 'ALL|' + cell(lat, lon)):   # ALL = coverage check (any military)
                    cells[k][0].add(d); cells[k][1].add(hx)
                gdays[g].add(d)
                if cent(lat, lon): cseen[hx].add(d)

legs = collections.defaultdict(collections.Counter)     # hex -> route counts (365 d)
routes = collections.defaultdict(lambda: [0, 0, 0])
op = gzip.open if legs_path.endswith('.gz') else open
with op(legs_path, 'rt') as fh:
    for r in csv.DictReader(fh):
        if not r['from'] or not r['to'] or r['from'] == r['to']:
            continue
        age = asof - int(r['day'])
        if age < 0 or age >= 365:
            continue
        rt = r['from'] + '>' + r['to']
        hx = r['hex'].lower().lstrip('~')
        legs[hx][rt] += 1
        x = routes[group(r['type']) + '|' + rt]
        x[2] += 1
        if age < 90: x[1] += 1
        if age < 30: x[0] += 1

def n(s, k):
    return sum(1 for d in s if asof - d < k)
A = {}
for hx in set(seen):
    s = seen.get(hx, set())
    A[hx] = [n(s, 30), n(s, 90), n(s, 365), max(s) if s else -1, first.get(hx, -1), len(cseen.get(hx, ())),
             [[k, v] for k, v in legs[hx].most_common(3)]]
C = {k: [n(v[0], 30), len(v[0]), len(v[1])] for k, v in cells.items()}
o = {'asof': asof, 'from': min(days_of(f) for f in afiles), 'days': len({days_of(f) for f in afiles}), 'first_from': days_of(files[0]) if files else asof, 'a': A, 'c': C, 'r': {k: v for k, v in routes.items() if v[1] >= 2},
     'g': {g: len(v) for g, v in gdays.items()}, 'tg': TG}
json.dump(o, open(out, 'w'), separators=(',', ':'))
print('%d airframes, %d cells, %d routes, data %s → %s (%d day files)' % (
    len(A), len(C), len(routes), datetime.date(1970, 1, 1) + datetime.timedelta(o['from']),
    datetime.date(1970, 1, 1) + datetime.timedelta(asof), len(afiles)))
