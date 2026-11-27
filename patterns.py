#!/usr/bin/env python3
"""Pattern report from the history-2025 branch (events/*.csv.gz, legs_all.csv.gz, coverage/*.json) + data/dg_tankers.csv.
Labels every US / UK / Israeli military airframe flying that day and compares each group's count with its own normal
(the previous 56 days). Evidence only, never a forecast. the owner 27 Oct 2026 (gulf-mission-patterns skill).

usage: python3 patterns.py [YYYY-MM-DD]            full owner text (default: newest day)
       python3 patterns.py YYYY-MM-DD --short      the short morning message (Telegram, a few lines)
       python3 patterns.py --all                   one JSON line per day (flags only), for grade.py
       python3 patterns.py --labels                labels/<hex[:3]>.json for the bot (last 90 days per airframe)"""
import sys, os, csv, gzip, glob, json, datetime, collections, statistics

EPOCH = datetime.date(1970, 1, 1)
def dnum(s): return (datetime.date.fromisoformat(s) - EPOCH).days
def dstr(n): return (EPOCH + datetime.timedelta(n)).isoformat()
def dshort(n): return (EPOCH + datetime.timedelta(n)).strftime('%a %d %b')

GROUPS = {   # ICAO type -> group (same split as the bot's map roles)
    'TANKER': 'K35R K35E KC10 K46 KC46 B762 A332 KC2 KC30 MRTT KC39 C135 B703',
    'AIRLIFT': 'C17 C5M C5 C130 C30J A400 C2 C27J C295 CN35',
    'BOMBER': 'B52 B1 B2 B21',
    'ISR': 'R135 W135 E3TF E3CF E3 E6 E7 E737 P8 U2 GLEX Q4 RQ4 MQ9 E8 EA37',
    'VIP': 'B742 B748 B752 B757 C32 GLF5 GLF6 GA7C C37 B737 B738 A319',
    'FIGHTER': 'F15 F16 F18 F18S F22 F35 FA18 EA18 F15E',
}
GROUP = {t: g for g, ts in GROUPS.items() for t in ts.split()}
REGIONS = ('CENTCOM', 'EUROPE', 'ATLANTIC')
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
APT = {}
try:
    APT = {a[1]: a[0] for a in json.load(open('airports.json'))}
except FileNotFoundError:
    pass
def apt(c): return STAGING.get(c) or (APT.get(c, c).replace(' Air Base', '').replace(' International Airport', '').replace(' Airport', '')[:22])
AMER = ('K', 'P', 'C', 'M', 'T')
def abroad(fr, to):
    if fr[:1] in AMER and to[:1] in AMER: return False
    if fr[:2] == to[:2]: return False      # same country (EG>EG, LI>LI)
    return True
def xatl(fr, to): return fr[:1] in AMER and to[:1] in ('E', 'L', 'B')

# ---------------- load once ----------------
act = collections.defaultdict(dict)          # day -> hex -> [type, cs, set(regions)]
first = {}                                    # hex -> first day ever seen
civil = {}                                    # day -> region -> civil aircraft seen (coverage files, from 24 Oct 2026)
for f in glob.glob('coverage/coverage-*.json'):
    civil[dnum(f[-15:-5])] = {k: v.get('civil', 0) for k, v in json.load(open(f)).items()}
nrows = collections.Counter()                 # day -> event rows (day size check)
seenrow = set()
present = collections.defaultdict(set)        # day -> every US/UK/IL hex seen at all (per-plane labels: count every sighting of that plane)
for f in sorted(glob.glob('events/events-*.csv.gz')):
    for r in csv.reader(gzip.open(f, 'rt')):
        hx, t, reg, own, cs, tm, lat, lon, alt = r
        d = int(float(tm) // 1440)
        nrows[d] += 1
        if not force(hx): continue
        present[d].add(hx)
        # Same counting for every day: from 24 Oct 2026 extract_day.py also writes each plane's first airborne point of the
        # day (planes already flying at midnight); the 541 days extracted before that fix never have it. Skip that row so
        # old and new days compare like with like (27 Oct 2026: it made 17 US tankers over CENTCOM look like a surge from 0).
        if (d, hx) not in seenrow:
            seenrow.add((d, hx))
            if int(alt) >= 3000: continue
        e = act[d].setdefault(hx, [t, cs, set()])
        if cs: e[1] = cs
        if int(alt) >= 3000: e[2].add(region(float(lat), float(lon)))
        if hx not in first or d < first[hx]: first[hx] = d
for d, hs in present.items():
    for hx in hs:
        if hx not in first or d < first[hx]: first[hx] = d
routes = collections.defaultdict(list)        # (group or type, from, to) -> days
byhex = collections.defaultdict(list)         # hex -> [(from, to, day)]
xat = collections.defaultdict(list)           # group -> days of US -> Europe legs
for hx, t, reg, own, cs, fr, to, day, tmin in [r for r in csv.reader(gzip.open('legs_all.csv.gz', 'rt'))][1:]:
    if not force(hx): continue
    g = GROUP.get(t.upper(), t.upper())
    routes[(g, fr, to)].append(int(day)); byhex[hx].append((fr, to, int(day)))
    if xatl(fr, to): xat[g].append(int(day))
cnt = collections.defaultdict(collections.Counter)   # day -> (group, region|None) -> US airframes
for d, hs in act.items():
    for hx, (t, cs, rs) in hs.items():
        g = GROUP.get(t.upper())
        if not g or force(hx) != 'US': continue
        cnt[d][(g, None)] += 1
        for rg in rs: cnt[d][(g, rg)] += 1
dg = []
try:
    dg = [r for r in csv.DictReader(open('data/dg_tankers.csv'))]
except FileNotFoundError:
    pass
DAYS = sorted(d for d in act if nrows[d] >= 500)   # drop stray rows of a day not collected yet

# ---------------- one day ----------------
def report(D, deep=True):
    def med56(fn):
        h = [fn(d) for d in range(D - 56, D) if d in act]
        return statistics.median(h) if h else 0
    # 0. guards: civil traffic jump in a region = receivers changed; small day vs the same weekday = partial archive
    cov = {}
    for rg in REGIONS:
        prev = [civil[d].get(rg, 0) for d in range(D - 56, D) if d in civil]
        if D in civil and len(prev) >= 3:
            n, m = civil[D].get(rg, 0), statistics.median(prev)
            if n >= 1.5 * m and n >= m + 50: cov[rg] = (n, m)
    same_wd = [nrows[d] for d in range(D - 56, D, 7) if d in nrows] or [0]
    partial = nrows[D] < 0.5 * statistics.median(same_wd)
    # 1. US group counts per region vs the previous 56 days
    rows = []
    for g in GROUPS:
        for rg in (None,) + REGIONS:
            hist = [cnt[d][(g, rg)] for d in range(D - 56, D) if d in act]
            if len(hist) < 20: continue
            n, med = cnt[D][(g, rg)], statistics.median(hist)
            p95 = sorted(hist)[int(0.95 * (len(hist) - 1))]
            flag = '⚠️' if n > p95 and n >= med + 3 else ('↓' if n < sorted(hist)[int(0.05 * (len(hist) - 1))] else '')
            if rg is None: flag = ''              # world total: information only (mixes US home training with deployments)
            if flag == '⚠️' and rg in cov: flag = '⚙️'
            if flag == '↓' and partial: flag = '⚙️'
            rows.append({'group': g, 'region': rg or 'ALL', 'n': n, 'median': med, 'p95': p95, 'flag': flag})
    # 1b. Atlantic crossings US -> Europe, last 7 days vs the 8 weeks before
    xrows = []
    for g in ('TANKER', 'AIRLIFT', 'BOMBER', 'ISR', 'FIGHTER'):
        def wk(end): return sum(1 for x in xat[g] if end - 7 < x <= end)
        now, prev = wk(D), [wk(D - 7 * k) for k in range(1, 9)]
        med, hi = statistics.median(prev), max(prev)
        xrows.append({'group': g, 'week': now, 'median': med, 'max8w': hi, 'flag': '⚠️' if now > hi and now >= med + 3 else ''})
    # 1c. X counts: @DefenceGeek tanker tables (total +15 or RED +10 in 7 days, count at most 3 days old)
    xc = {}
    def val(col, upto):
        v = [(dnum(r['date']), int(r[col])) for r in dg if r[col] and dnum(r['date']) <= upto]
        return v[-1] if v else None
    for col, step in (('total_eu_centcom', 15), ('red_centcom', 10)):
        now = val(col, D)
        if now:
            win = [int(r[col]) for r in dg if r[col] and now[0] - 7 <= dnum(r['date']) < now[0]]
            before = min(win) if win else (val(col, now[0] - 7) or (None, None))[1]
            ch = now[1] - before if before is not None else None
            xc[col] = {'value': now[1], 'date': dstr(now[0]), 'age_days': D - now[0], 'change_7d': ch,
                       'flag': '⚠️' if ch is not None and ch >= step and D - now[0] <= 3 else ''}
    # 2. each airframe that day
    tags = []
    for hx, (t, cs, rs) in (sorted(act.get(D, {}).items()) if deep else []):
        g = GROUP.get(t.upper())
        if not g: continue
        seen = sum(1 for d in range(D - 30, D) if hx in present.get(d, ()))
        my = [(fr, to) for fr, to, dd in byhex.get(hx, []) if dd == D]
        lab, why = '♻️ routine', 'flew %d of the last 30 days' % seen
        if first.get(hx) == D:
            lab, why = '🆕 first time seen', 'not in %d days of history' % (D - DAYS[0])
        elif seen == 0:
            lab, why = '💤 back after a long gap', 'last seen %s' % dstr(max([d for d in DAYS if d < D and hx in act[d]] or [D]))
        if lab.startswith('🆕') and D - DAYS[0] < 180: lab, why = '♻️ routine', 'history too short to call it new'
        for fr, to in my:
            if not abroad(fr, to): continue
            if g not in ('TANKER', 'BOMBER', 'ISR'): continue   # airlift / VIP fly new routes almost daily: not a signal (27 Oct 2026)
            if not (to in STAGING or fr in STAGING or to[:1] in 'OLHF' or fr[:1] in 'OLHF'): continue   # must touch Europe / CENTCOM / staging
            prior = [x for x in routes[(g, fr, to)] if x < D]
            if not prior:
                lab, why = '⚠️ new route', 'first %s ever on %s → %s' % (g.lower(), apt(fr), apt(to))
            elif to in STAGING and g in ('TANKER', 'BOMBER') and not [x for x in prior if x >= D - 56]:
                lab, why = '⚠️ staging base', 'into %s, none in the previous 56 days' % apt(to)
        tags.append({'hex': hx, 'force': force(hx), 'type': t, 'cs': cs, 'group': g, 'regions': sorted(rs), 'label': lab,
                     'why': why, 'routes': ['%s>%s' % x for x in my]})
    o = {'day': dstr(D), 'x_counts': xc, 'coverage_jump': cov, 'partial_day': partial, 'counts': rows, 'atlantic': xrows,
            'aircraft': tags, '_same_wd': statistics.median(same_wd), '_nrows': nrows[D]}
    if deep: o['alarm'] = alarm(D, o)
    return o

def signals(o):   # independent signal types of one day
    s = set()
    for x in o['counts']:
        if x['flag'] == '⚠️': s.add('%s %s' % (x['group'].lower(), x['region'].lower()))
    for x in o['atlantic']:
        if x['flag']: s.add('atlantic %s' % x['group'].lower())
    for k, v in o['x_counts'].items():
        if v['flag']: s.add('DefenceGeek ' + ('tanker total' if k.startswith('total') else 'CENTCOM tankers'))
    return s
def is_tanker(x): return 'tanker' in x
def alarm(D, o=None):
    """🚨 = 3+ different signals within 3 days, at least one about tankers (backtest 27 Oct 2026: 11 episodes in 16 months;
    started 10 days before the 28 Feb 2026 war, 6 days before the 8 Sep 2026 strikes, a week before the 14 Oct reversal)."""
    w = set()
    for d in (D - 2, D - 1, D):
        if d in act: w |= signals(o if (o and d == D) else report(d, deep=False))
    return sorted(w) if len(w) >= 3 and any(is_tanker(x) for x in w) else []

def full_text(o):
    D = dnum(o['day']); L = ['📈 PATTERNS · %s (free ADS-B, US military counted)' % o['day'], '']
    if o.get('alarm'): L += ['🚨 Several signals together (3 days): ' + ', '.join(o['alarm']), '']
    for rg, (n, m) in o['coverage_jump'].items():
        L.append('⚙️ Coverage jump %s: %d civil aircraft seen vs normal %g — receivers changed, military counts there are not a surge' % (rg, n, m))
    if o['partial_day']: L.append('⚙️ Partial day: %d events vs normal %g for this weekday — counts are low' % (o['_nrows'], o['_same_wd']))
    for r in o['counts']:
        if r['flag'] or r['region'] == 'ALL':
            L.append('%s %s %s: %d (normal %g, high %d)' % (r['flag'] or '·', r['group'], r['region'], r['n'], r['median'], r['p95']))
    L.append('')
    xc = o['x_counts']
    if xc:
        L.append('X counts (@DefenceGeek tanker tables):')
        for col, name in (('total_eu_centcom', 'Tankers EUCOM+CENTCOM'), ('red_centcom', 'Tankers CENTCOM (RED)')):
            x = xc.get(col)
            if x: L.append('%s %s: %d on %s%s%s' % (x['flag'] or '·', name, x['value'], x['date'],
                           '' if x['change_7d'] is None else ' (%+d in 7 days)' % x['change_7d'],
                           ' — %d days old' % x['age_days'] if x['age_days'] > 7 else ''))
        L.append('')
    L.append('Atlantic, US → Europe, last 7 days:')
    for r in o['atlantic']:
        L.append('%s %s %d (normal %g/week, 8-week high %d)' % (r['flag'] or '·', r['group'], r['week'], r['median'], r['max8w']))
    L.append('')
    by = collections.Counter(x['label'] for x in o['aircraft'])
    L.append('Airframes: ' + ', '.join('%s %d' % kv for kv in by.most_common()))
    for x in notable(o['aircraft']):
        L.append('%s · %s %s · %s' % (x['label'], x['type'], x['cs'] or x['hex'], x['why']))
    return '\n'.join(L)

def notable(tags):   # what the short message lists: new routes / staging / first-seen, US first, tankers-bombers-ISR first
    pr = {'TANKER': 0, 'BOMBER': 0, 'ISR': 1, 'VIP': 2, 'AIRLIFT': 3, 'FIGHTER': 1}
    xs = [x for x in tags if x['label'].startswith('⚠️') or (x['label'].startswith('🆕') and x['group'] in ('TANKER', 'BOMBER', 'ISR', 'VIP'))]
    return sorted(xs, key=lambda x: (x['force'] != 'US', pr.get(x['group'], 9), x['label']))

def short_text(o):
    """The morning message: 5-10 short lines, flags first, normal days say so in one line."""
    D = dnum(o['day']); L = ['📈 <b>PATTERNS</b> · %s' % dshort(D)]
    if o.get('alarm'): L.append('🚨 <b>Several signals together (3 days):</b> ' + ', '.join(o['alarm']))
    xc = o['x_counts']
    t, r = xc.get('total_eu_centcom'), xc.get('red_centcom')
    if t:
        L.append('%s Tankers (DefenceGeek %s): %d EUCOM+CENTCOM%s%s' % (
            '⚠️' if (t['flag'] or (r and r['flag'])) else '⛽', (EPOCH + datetime.timedelta(dnum(t['date']))).strftime('%d %b'), t['value'],
            ' · %d CENTCOM' % r['value'] if r else '', '' if t['change_7d'] is None else ' (%+d / 7 d)' % t['change_7d'])
            + (' — no newer count' if t['age_days'] > 7 else ''))
    fl = [x for x in o['counts'] if x['flag'] == '⚠️'] + [dict(x, region='Atlantic, 7 days', n=x['week']) for x in o['atlantic'] if x['flag']]
    if fl:
        L.append('⚠️ Above normal: ' + ', '.join('%s %s %d (normal %g)' % (x['group'].lower(), x['region'].lower(), x['n'], x['median']) for x in fl))
    else:
        L.append('♻️ ADS-B counts normal (US tankers, airlift, bombers, ISR vs last 8 weeks)')
    for x in notable(o['aircraft'])[:5]:
        L.append('%s %s %s — %s' % (x['label'].split(' ')[0], x['cs'] or x['hex'].upper(), x['type'], x['why']))
    for rg, (n, m) in o['coverage_jump'].items():
        L.append('⚙️ %s: receivers changed (%d civil vs %g), not counted' % (rg, n, m))
    if o['partial_day']: L.append('⚙️ Small day file (%d events vs %g), counts may be low' % (o['_nrows'], o['_same_wd']))
    return '\n'.join(L)

def labels():
    """Per-airframe facts for the bot's label line: days flown in the last 30 / 90 days, last seen, usual routes."""
    D = DAYS[-1]; out = collections.defaultdict(dict)
    for hx in {h for d in DAYS[-90:] for h in present[d]}:
        d30 = sum(1 for d in range(D - 29, D + 1) if hx in present.get(d, ()))
        d90 = sum(1 for d in range(D - 89, D + 1) if hx in present.get(d, ()))
        last = max(d for d in DAYS[-90:] if hx in present[d])
        rc = collections.Counter('%s>%s' % (fr, to) for fr, to, dd in byhex.get(hx, []) if dd > D - 90)
        out[hx[:3]][hx] = [d30, d90, dstr(last), dstr(first.get(hx, last)), [[k, n] for k, n in rc.most_common(3) if n >= 3]]   # a route counts as usual from 3 flights
    os.makedirs('labels', exist_ok=True)
    for k, v in out.items():
        json.dump({'asof': dstr(D), 'hex': v}, open('labels/%s.json' % k, 'w'), separators=(',', ':'))
    print(len(out), 'files,', sum(len(v) for v in out.values()), 'airframes, as of', dstr(D))

if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if '--labels' in sys.argv: labels()
    elif '--all' in sys.argv:
        for D in DAYS[30:]:   # 30 days of history needed for a normal
            o = report(D)
            print(json.dumps({'day': o['day'], 'alarm': o['alarm'], 'signals': sorted(signals(o)), 'counts': [x for x in o['counts'] if x['flag'] == '⚠️'],
                              'atlantic': [x for x in o['atlantic'] if x['flag']], 'x': {k: v for k, v in o['x_counts'].items() if v['flag']},
                              'notable': [[x['label'], x['type'], x['cs'], x['why']] for x in notable(o['aircraft'])]}, ensure_ascii=False))
    else:
        o = report(dnum(a[0]) if a else DAYS[-1])
        json.dump(o, open('patterns-%s.json' % o['day'], 'w'), ensure_ascii=False, indent=0)
        print(short_text(o) if '--short' in sys.argv else full_text(o))
