#!/usr/bin/env python3
"""lastland.json for the map service: each airframe's last 3 landings from legs_all.csv
(hex -> [[airfield code, minute since epoch], ...] oldest first) plus "_through" = newest minute in the data.
Used by the bot's "Last landed" line (Reza 27 Oct 2026). Usage: make_lastland.py legs_all.csv out.json"""
import csv, json, sys, collections

legs = collections.defaultdict(list)
for r in csv.DictReader(open(sys.argv[1])):
    legs[r['hex'].lower().lstrip('~')].append((int(r['time_min']), r['to']))
out = {h: [[c, t] for t, c in sorted(v)[-3:]] for h, v in legs.items()}
out['_through'] = max((t for v in legs.values() for t, _ in v), default=0)
json.dump(out, open(sys.argv[2], 'w'), separators=(',', ':'))
print(len(out) - 1, 'airframes, data through minute', out['_through'])
