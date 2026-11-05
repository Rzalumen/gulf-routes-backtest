#!/usr/bin/env python3
"""Flightradar24 flight lists → air-history day-only rows (Reza 3 Nov 2026 23:04 ET "do flightradar").
Input: a text file of lines "hex:d1d2d3…" where each day is 2 base-36 chars = days since 1970-01-01 minus 20400 (from the
FR24 /data/aircraft/<reg> pages read in Reza's logged-in Chrome: one row per flight, its data-timestamp = UTC day flown).
Output: air/air-fr24-YYYY-MM-DD.csv.gz rows hex,type,reg,callsign,minute,lat,lon,alt with empty lat/lon (day-only:
the airframe's flying day counts in make_patterns.py, no area cell is invented).
Existing day files in OUT_DIR are kept: only airframe-days not already stored are added (4 Nov 2026, Reza: add, never replace).
usage: fr24_history.py IN.txt REGS.json OUT_DIR"""
import sys, os, csv, gzip, json, datetime, collections
src, regs_path, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
reg = dict(json.load(open(regs_path)))
by = collections.defaultdict(set)
n = 0
for line in open(src):
    line = line.strip()
    if ':' not in line:
        continue
    hx, s = line.split(':', 1)
    for i in range(0, len(s) - 1, 2):
        d = int(s[i:i + 2], 36) + 20400
        day = (datetime.date(1970, 1, 1) + datetime.timedelta(d)).isoformat()
        by[day].add((hx, '', reg.get(hx, ''), '', str(d * 1440 + 720), '', '', ''))
        n += 1
added = 0
for day, rs in sorted(by.items()):
    f = os.path.join(out, 'air-fr24-%s.csv.gz' % day)
    old = list(csv.reader(gzip.open(f, 'rt'))) if os.path.exists(f) else []
    have = {(r[0], r[4]) for r in old if len(r) > 4}
    new = sorted(r for r in rs if (r[0], r[4]) not in have)
    if not new:
        continue
    with gzip.open(f, 'wt') as fh:
        csv.writer(fh).writerows(old + new)
    added += len(new)
print('%d airframe-days on %d days in the input, %d new' % (n, len(by), added))
