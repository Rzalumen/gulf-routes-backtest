#!/usr/bin/env python3
"""Merge one Scramble UK batch into the units branch files (the owner 20 Nov 2026, RAF first).

usage: python3 units/raf_merge.py <batch.json> [prefix]   (prefix 'raf' = UK default, 'il' = Israel, ...)
batch.json = window.__raf from scramble_raf_runner.js: {stack, done, rows, log, q, status, started, finished}

Writes (all under units/):
  raf_rows.csv   every row seen, one per serial (newest wins): serial,code,type,cn,unit,status
  raf.json       {serial: unit} for rows with a unit (what the bot will read later)
  raf_state.json {stack, done, batches[...]} — the next batch pops from stack
Never shrinks raf.json: a serial is only added or updated.
"""
import csv, json, os, sys

D = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(D, f)

PFX = sys.argv[2] if len(sys.argv) > 2 else 'raf'
b = json.load(open(sys.argv[1]))
# column order from the page header when the runner saw one (USN layout: serial, code, type, c/n, unit, status)
H = [h.lower() for h in (b.get('head') or [])]
def col(name, dflt):
    for i, h in enumerate(H):
        if name in h:
            return i
    return dflt
IX = [0, col('code', 1), col('type', 2), col('c/n', 3), col('unit', 4), col('status', 5)]
# UK serials are unique; Israeli (and other plain-number) serials repeat across types (IAF 902 = F-35I, AH-64A, CH-53),
# so for every prefix but 'raf' a row is keyed serial|type and the map key is 'serial|type' too.
KEY = (lambda r: r[0]) if PFX == 'raf' else (lambda r: r[0] + '|' + r[2])
rows = {}
if os.path.exists(P(PFX + '_rows.csv')):
    for r in csv.reader(open(P(PFX + '_rows.csv'), newline='')):
        if r and r[0] != 'serial':
            rows[KEY(r)] = r
old_rows = len(rows)
for r in b.get('rows', []):
    r = list(r) + [''] * 8
    r = [r[i] if i < len(r) else '' for i in IX]
    s = r[0].strip().upper()
    if s:
        r[0] = s
        rows[KEY(r)] = r
with open(P(PFX + '_rows.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['serial', 'code', 'type', 'cn', 'unit', 'status'])
    for s in sorted(rows):
        w.writerow(rows[s])

m = json.load(open(P(PFX + '.json'))) if os.path.exists(P(PFX + '.json')) else {}
old_map = len(m)
for s, r in rows.items():
    if r[4].strip():
        m[s] = r[4].strip()
assert len(m) >= old_map, PFX + '.json would shrink'
json.dump(m, open(P(PFX + '.json'), 'w'), separators=(',', ':'), ensure_ascii=False, sort_keys=True)

st = json.load(open(P(PFX + '_state.json'))) if os.path.exists(P(PFX + '_state.json')) else {'done': [], 'batches': []}
st['stack'] = b.get('stack', [])
st['done'] = sorted(set(st.get('done', [])) | set(b.get('done', [])))
st['batches'] = (st.get('batches', []) + [{
    'started': b.get('started'), 'finished': b.get('finished'), 'queries': b.get('q'),
    'status': b.get('status'), 'rows_in': len(b.get('rows', [])),
    'head': b.get('head'), 'serials': len(rows), 'new_serials': len(rows) - old_rows, 'units': len(m), 'new_units': len(m) - old_map}])[-60:]
json.dump(st, open(P(PFX + '_state.json'), 'w'), indent=1)

print(json.dumps({'queries': b.get('q'), 'status': b.get('status'), 'serials': len(rows), 'new_serials': len(rows) - old_rows,
                  'units': len(m), 'new_units': len(m) - old_map, 'stack_left': len(st['stack']), 'log': b.get('log', [])}))
