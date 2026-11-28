"""Oil and gas sites for HEAT WATCH (the owner 7 Nov 2026: "bot should have an updated coord of all the known oil fields").

Known flares: EOG VIIRS Nightfire MYC25Q4 annual_flare_site_records.csv (Zenodo 10.5281/zenodo.23091822, CC BY-NC 4.0,
upstream oil / gas flares 2012-2025). Plus OpenStreetMap: offshore platforms, flare stacks, refineries, oil / gas industrial sites.
Box = firms.gs firmsWhy_ box (Iran, Gulf states, Israel and seas).

usage: python3 make_oilsites.py flares.csv overpass.json out.json
out: {"_built": date, "_src": ..., "sites": [[lat, lon, kind, name, country, last_flare_year], ...]}
kind 'flare' = catalogued flare site with a detection in last_flare_year; other kinds come from OSM (last year 0).
"""
import csv, datetime, json, sys

BOX = (12.0, 40.0, 34.0, 63.5)   # lat min, lat max, lon min, lon max


def inbox(la, lo):
    return BOX[0] <= la <= BOX[1] and BOX[2] <= lo <= BOX[3]


def flares(path):
    out = {}
    for r in csv.DictReader(open(path, newline='', encoding='utf-8')):
        try:
            la, lo, y = float(r['lat']), float(r['lon']), int(r['year'])
        except (KeyError, ValueError):
            continue
        if not inbox(la, lo):
            continue
        f = out.setdefault(r['flare_id'], {'lat': la, 'lon': lo, 'c': r.get('country_iso', ''), 'u': r.get('upstream_class', ''), 'last': 0, 'reg': ''})
        try:
            det = float(r.get('n_det') or 0)
        except ValueError:
            det = 0
        if det > 0 and y >= f['last']:
            f['last'], f['reg'] = y, r.get('regime', '')
    nm = {'oil': 'oil-field flare', 'gas': 'gas-field flare'}
    return [[round(f['lat'], 4), round(f['lon'], 4), 'flare', '%s, %s' % (nm.get(f['u'], 'oil / gas flare'), f['reg'] or 'n/a'), f['c'], f['last']]
            for f in out.values() if f['last']]


def osm(path):
    out = []
    for e in json.load(open(path, encoding='utf-8')).get('elements', []):
        t = e.get('tags', {})
        c = e.get('center') or {}
        la, lo = e.get('lat', c.get('lat')), e.get('lon', c.get('lon'))
        if la is None or lo is None or not inbox(la, lo):
            continue
        mm, ind = t.get('man_made', ''), t.get('industrial', '')
        kind = ('platform' if mm == 'offshore_platform' else 'flare stack' if mm == 'flare' else 'refinery' if ind == 'refinery'
                else 'well' if mm == 'petroleum_well' else 'gas plant' if ind == 'gas' else 'oil site')
        name = t.get('name:en') or t.get('name') or t.get('operator') or ''
        out.append([round(la, 4), round(lo, 4), kind, name[:60], '', 0])
    return out


def main(fl, ov, dst):
    f, o = flares(fl), osm(ov)
    if len(f) < 500:   # the Gulf box holds ~2,000 flare sites; fewer = a failed download — keep the old file
        sys.exit('only %d flare sites — not writing %s' % (len(f), dst))
    try:   # 27 Nov 2026 (audit item 56): an empty or cut-off OpenStreetMap answer dropped every platform / refinery — keep the old file then
        old = sum(1 for s in json.load(open(dst, encoding='utf-8')).get('sites', []) if s[2] != 'flare')
    except (OSError, ValueError):
        old = 0
    if len(o) < 0.5 * old:
        sys.exit('only %d OpenStreetMap sites (the file has %d) — not writing %s' % (len(o), old, dst))
    json.dump({'_built': datetime.date.today().isoformat(),
               '_src': 'EOG VIIRS Nightfire MYC25Q4 (CC BY-NC 4.0) + OpenStreetMap contributors (ODbL)',
               'sites': f + o}, open(dst, 'w'), separators=(',', ':'))
    kinds = {}
    for s in o:
        kinds[s[2]] = kinds.get(s[2], 0) + 1
    print('flares %d (active 2023+: %d) · OSM %d %s' % (len(f), sum(1 for s in f if s[5] >= 2023), len(o), kinds))


if __name__ == '__main__':
    main(*sys.argv[1:4])
