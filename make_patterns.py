#!/usr/bin/env python3
"""patterns.json for the map service: what is NORMAL, from the adsb.lol history (history-2025 branch).
Lets the bot say "routine" vs "unusual" with a number behind it (Reza 2 Nov 2026: "the bot should have enough
historic and backfill data to recognize routine mission vs unusual").

Usage: make_patterns.py <air dir> <events dir> <legs_all.csv[.gz]> <out.json>
Airborne presence comes from air-history (air/air-YYYY-MM-DD.csv.gz: hex,type,reg,callsign,minute,lat,lon,alt, one
point per 15 min) — history-2025 events only hold take-offs / landings, so orbits over CENTCOM were missing there.
events are used only for "first seen" (back to 1 May 2025).
Output (compact; days = days since 1970-01-01, asof = newest day in the data):
  a: {hex: [d30, d90, d365, last_day, first_day, c90, [[FROM>TO, legs in 365 d], …top 3]]}   per airframe
     d30/d90/d365 = days airborne in the air-history area; c90 = days airborne inside the CENTCOM box
  c: {"GROUP|lat|lon": [d30, d90, airframes90]}   2° cells (whole air-history area), days any plane of that group flew there
  r: {"GROUP|FROM>TO": [n30, n90, n365]}          legs per route per group (both ends known)
  g: {"GROUP": days the group was seen anywhere in the area in the last 90 days}
Counts are days, not points: the first-airborne-point row that only days from 25 Oct 2026 carry cannot inflate them."""
import sys, os, csv, gzip, json, glob, collections, datetime

GROUPS = {
    'TANKER': 'K35R K35E K35T KC135 KC46 B762 KC10 DC10 A332 A330 MRTT K30 B703 B707 KC30 KC390 C390',
    'AIRLIFT': 'C17 C5M C5 C30J C130 A400 C2 B744 IL76 C27J CN35 C295 A124 Y20',
    'ISR': 'R135 E3TF E3CF E3 E7 E737 E8 E6 P8 P3 E2 GLF5 GLF6 G550 U2 Q4 RQ4 GLEX R1 CL60 SHAD DH8C B350 E390 RC12',
    'DRONE': 'Q9 MQ9 MQ1 HRON HERN Q1 Q4 RQ4 TB2 HER',
    'BOMBER': 'B52 B1 B2',
    'FIGHTER': 'F35 F16 F15 F18 FA18 F18S EUFI A10 F22 TOR RFAL F2TH M2K',
    'VIP': 'C32 C37 C40 VC25 B742 B748 GLF4 GLF5 A319 A320 A321 A332 B737 B738 B752 B763 B77W FA7X F900 C750 C25B CL35 GLF6 IL96 T154 T214 IL62 LJ35 C560 C21 C12',
    'HELO': 'H60 S70 H47 CH47 H53 V22 H64 AS32 EC35 NH90 MRH9 H1 UH1Y AH1 H72',
}
TG = {}
for g, ts in GROUPS.items():
    for t in ts.split():
        TG.setdefault(t, g)          # first group wins (A332 = tanker, GLF5 = ISR)
def group(t):
    return TG.get(((t or '').upper().split(' ') or [''])[0], 'OTHER')

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
asof = days_of(afiles[-1])
seen = collections.defaultdict(set)            # hex -> airborne days
cseen = collections.defaultdict(set)           # hex -> airborne days inside CENTCOM
first = {}
cells = collections.defaultdict(lambda: [set(), set()])   # key -> [days, hexes in 90 d]
gdays = collections.defaultdict(set)
htype = {}
for f in files:                                # first seen only
    d = days_of(f)
    with gzip.open(f, 'rt') if f.endswith('.gz') else open(f) as fh:
        for r in csv.reader(fh):
            if r: first.setdefault(r[0].lower().lstrip('~'), d)
for f in afiles:
    d = days_of(f)
    if asof - d >= 365:
        continue
    with gzip.open(f, 'rt') if f.endswith('.gz') else open(f) as fh:
        for r in csv.reader(fh):
            if len(r) < 8:
                continue
            hx = r[0].lower().lstrip('~')
            try:
                lat, lon = float(r[5]), float(r[6])
            except ValueError:
                continue
            first.setdefault(hx, d)
            seen[hx].add(d)
            if r[1]: htype[hx] = r[1]
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
o = {'asof': asof, 'from': days_of(afiles[0]), 'days': len(afiles), 'first_from': days_of(files[0]) if files else asof, 'a': A, 'c': C, 'r': {k: v for k, v in routes.items() if v[1] >= 2},
     'g': {g: len(v) for g, v in gdays.items()}, 'tg': TG}
json.dump(o, open(out, 'w'), separators=(',', ':'))
print('%d airframes, %d cells, %d routes, data %s → %s (%d day files)' % (
    len(A), len(C), len(routes), datetime.date(1970, 1, 1) + datetime.timedelta(o['from']),
    datetime.date(1970, 1, 1) + datetime.timedelta(asof), len(afiles)))
