#!/usr/bin/env python3
"""Grade the 🚨 days against real events (data/events.csv). usage: python3 patterns.py --all > all.jsonl; python3 grade.py all.jsonl
An episode = 🚨 days no more than 3 days apart. Hit = an event within 14 days after the episode starts (or during it)."""
import sys, json, csv, datetime
E = datetime.date(1970, 1, 1); dn = lambda s: (datetime.date.fromisoformat(s) - E).days
days = [json.loads(l) for l in open(sys.argv[1])]
first, last = dn(days[0]['day']), dn(days[-1]['day'])
ev = [(dn(r['date']), r['event']) for r in csv.DictReader(open('data/events.csv')) if first <= dn(r['date']) <= last + 14]
al = [dn(o['day']) for o in days if o['alarm']]
eps = []
for d in al:
    if eps and d - eps[-1][1] <= 3: eps[-1][1] = d
    else: eps.append([d, d])
print('🚨 episodes %d in %d days (%s → %s)' % (len(eps), last - first + 1, days[0]['day'], days[-1]['day']))
used = set()
for a, b in eps:
    hit = [(d, e) for d, e in ev if a <= d <= b + 14]
    used |= {d for d, e in hit}
    print('%s → %s  %s' % ((E + datetime.timedelta(a)).isoformat(), (E + datetime.timedelta(b)).isoformat(),
          '; '.join('%s (%+d days)' % (e, d - a) for d, e in hit) or 'no event in the list (false alarm or unlisted)'))
for d, e in ev:
    if d not in used: print('MISSED %s %s' % ((E + datetime.timedelta(d)).isoformat(), e))
