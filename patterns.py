#!/usr/bin/env python3
"""Pattern report for one day from the history-2025 branch (events/*.csv.gz + legs_all.csv.gz).
Labels every US / UK / Israeli military airframe flying that day and compares each group's count with its own
normal (the previous 56 days). Evidence only, never a forecast. Reza 27 Oct 2026 (gulf-mission-patterns skill).

usage: python3 patterns.py [YYYY-MM-DD]   (default: the newest day in events/)
writes patterns-<day>.json and prints the owner text."""
import sys, csv, gzip, glob, json, datetime, collections, statistics

EPOCH = datetime.date(1970, 1, 1)
def dnum(s): return (datetime.date.fromisoformat(s) - EPOCH).days
def dstr(n): return (EPOCH + datetime.timedelta(n)).isoformat()

GROUPS = {   # ICAO type -> group (same split as the bot's map roles)
    'TANKER': 'K35R K35E KC10 K46 KC46 B762 A332 KC2 KC30 MRTT KC39 C135 B703',
    'AIRLIFT': 'C17 C5M C5 C130 C30J A400 C2 C27J C295 CN35',
    'BOMBER': 'B52 B1 B2 B21',
    'ISR': 'R135 W135 E3TF E3CF E3 E6 E7 E737 P8 U2 GLEX Q4 RQ4 MQ9 E8 EA37',
    'VIP': 'B742 B748 B752 B757 C32 GLF5 GLF6 GA7C C37 B737 B738 A319',
    'FIGHTER': 'F15 F16 F18 F18S F22 F35 FA18 EA18 F15E',
}
GROUP = {t: g for g, ts in GROUPS.items() for t in ts.split()}
def force(hx):
    h = int(hx, 16) if hx and all(c in '0123456789abcdef' for c in hx) else -1
    if 0xADF7C8 <= h <= 0xAFFFFF: return 'US'
    if 0x43C000 <= h <= 0x43CFFF: return 'UK'
    if 0x738000 <= h <= 0x73FFFF: return 'IL'
    return None
def region(lat, lon):
    if 10 <= lat <= 42 and 25 <= lon <= 75: return 'CENTCOM'
    if 34 <= lat <= 72 and -12 <= lon < 25: return 'EUROPE'
    if 20 <= lat <= 72 and -60 <= lon < -12: return 'ATLANTIC'
    if lon < -60: return 'AMERICAS'
    return 'OTHER'
STAGING = {'LEMO': 'Morón', 'LERT': 'Rota', 'LPLA': 'Lajes', 'LLBG': 'Ben Gurion', 'LGSA': 'Chania', 'LBSF': 'Sofia',
           'LROP': 'Bucharest', 'EGVA': 'Fairford', 'FJDG': 'Diego Garcia', 'LICZ': 'Sigonella', 'LTAG': 'Incirlik',
           'EGUN': 'Mildenhall', 'ETAR': 'Ramstein', 'LFMI': 'Istres', 'OJMS': 'Muwaffaq Salti', 'OTBH': 'Al Udeid'}

# ---- load: one entry per (day, hex) with type, callsign, regions flown ----
act = collections.defaultdict(dict)          # day -> hex -> [type, cs, set(regions)]
first = {}                                    # hex -> first day ever seen
for f in sorted(glob.glob('events/events-*.csv.gz')):
    for r in csv.reader(gzip.open(f, 'rt')):
        hx, t, reg, own, cs, tm, lat, lon, alt = r
        if not force(hx): continue
        d = int(float(tm) // 1440)
        e = act[d].setdefault(hx, [t, cs, set()])
        if cs: e[1] = cs
        if int(alt) >= 3000: e[2].add(region(float(lat), float(lon)))
        if hx not in first or d < first[hx]: first[hx] = d
legs = [r for r in csv.reader(gzip.open('legs_all.csv.gz', 'rt'))][1:]
routes = collections.defaultdict(list)       # (group or type, from, to) -> days
hexroutes = collections.defaultdict(list)    # (hex, from, to) -> days
for hx, t, reg, own, cs, fr, to, day, tmin in legs:
    if not force(hx): continue
    routes[(GROUP.get(t.upper(), t.upper()), fr, to)].append(int(day))
    hexroutes[(hx, fr, to)].append(int(day))

AMER = ('K', 'P', 'C', 'M', 'T')
def abroad(fr, to):
    if fr[:1] in AMER and to[:1] in AMER: return False
    if fr[:2] == to[:2]: return False      # same country (EG>EG, LI>LI)
    return True
def xatl(fr, to): return fr[:1] in AMER and to[:1] in ('E', 'L', 'B')
D = dnum(sys.argv[1]) if len(sys.argv) > 1 else max(act)
def count(d, g, reg_=None):
    return sum(1 for hx, (t, cs, rs) in act.get(d, {}).items()
               if GROUP.get(t.upper()) == g and force(hx) == 'US' and (reg_ is None or reg_ in rs))
# ---- 1. group counts vs the previous 56 days ----
rows = []
for g in GROUPS:
    for rg in (None, 'CENTCOM', 'EUROPE', 'ATLANTIC'):
        hist = [count(d, g, rg) for d in range(D - 56, D) if d in act]
        if len(hist) < 20: continue
        n, med = count(D, g, rg), statistics.median(hist)
        p95 = sorted(hist)[int(0.95 * (len(hist) - 1))]
        flag = '⚠️' if n > p95 and n >= med + 3 else ('↓' if n < sorted(hist)[int(0.05 * (len(hist) - 1))] else '')
        rows.append({'group': g, 'region': rg or 'ALL', 'n': n, 'median': med, 'p95': p95, 'flag': flag})
# ---- 1b. Atlantic crossings US -> Europe, last 7 days vs the 8 weeks before ----
xrows = []
for g in ('TANKER', 'AIRLIFT', 'BOMBER', 'ISR', 'FIGHTER'):
    def wk(end): return sum(1 for (gg, fr, to), ds in routes.items() if gg == g and xatl(fr, to) for x in ds if end - 7 < x <= end)
    now, prev = wk(D), [wk(D - 7 * k) for k in range(1, 9)]
    med, hi = statistics.median(prev), max(prev)
    flag = '⚠️' if now > hi and now >= med + 3 else ''
    xrows.append({'group': g, 'week': now, 'median': med, 'max8w': hi, 'flag': flag})
# ---- 2. each airframe that day: routine / first seen / new route ----
tags = []
for hx, (t, cs, rs) in sorted(act.get(D, {}).items()):
    g = GROUP.get(t.upper())
    if not g: continue
    seen = sum(1 for d in range(D - 30, D) if hx in act.get(d, {}))
    my = [(fr, to) for (h, fr, to), ds in hexroutes.items() if h == hx and D in ds]
    lab, why = '♻️ routine', 'flew %d of the last 30 days' % seen
    if first.get(hx) == D:
        lab, why = '🆕 first time seen', 'not in %d days of history' % (D - min(first.values()))
    elif seen == 0:
        lab, why = '💤 back after a long gap', 'last seen %s' % dstr(max(d for d in act if d < D and hx in act[d]))
    for fr, to in my:
        if not abroad(fr, to): continue   # US-domestic and UK-domestic hops are training noise
        prior = [x for x in routes[(g, fr, to)] if x < D]
        if not prior:
            lab, why = '⚠️ route never flown before', '%s %s>%s: no %s on it in history' % (t, fr, to, g.lower())
        elif to in STAGING and g in ('TANKER', 'BOMBER') and len([x for x in prior if x >= D - 56]) == 0:
            lab, why = '⚠️ staging base', '%s into %s (%s), none in the previous 56 days' % (t, STAGING[to], to, )
    tags.append({'hex': hx, 'force': force(hx), 'type': t, 'cs': cs, 'group': g, 'regions': sorted(rs), 'label': lab, 'why': why,
                 'routes': ['%s>%s' % x for x in my]})
out = {'day': dstr(D), 'counts': rows, 'atlantic': xrows, 'aircraft': tags}
json.dump(out, open('patterns-%s.json' % dstr(D), 'w'), ensure_ascii=False, indent=0)

# ---- owner text ----
L = ['📈 PATTERNS · %s (free ADS-B, US military counted)' % dstr(D), '']
for r in rows:
    if r['flag'] or r['region'] == 'ALL':
        L.append('%s %s %s: %d (normal %g, high %d)' % (r['flag'] or '·', r['group'], r['region'], r['n'], r['median'], r['p95']))
L.append('')
L.append('Atlantic, US → Europe, last 7 days:')
for r in xrows:
    L.append('%s %s %d (normal %g/week, 8-week high %d)' % (r['flag'] or '·', r['group'], r['week'], r['median'], r['max8w']))
L.append('')
by = collections.Counter(x['label'] for x in tags)
L.append('Airframes: ' + ', '.join('%s %d' % kv for kv in by.most_common()))
for x in tags:
    if x['label'].startswith('⚠️') or (x['label'].startswith('🆕') and x['group'] in ('TANKER', 'BOMBER', 'ISR', 'VIP')):
        L.append('%s · %s %s %s · %s' % (x['label'], x['type'], x['cs'] or x['hex'], ' '.join(x['routes']), x['why']))
print('\n'.join(L))
