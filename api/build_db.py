#!/usr/bin/env python3
"""Build gulf.db (SQLite, read-only for the API) from the GitHub data branches. 4 Nov 2026, System Design phase 1.
Source of truth stays the append-only git branches; this file is a disposable index of them — rebuild any time.

usage: build_db.py --air <air-history checkout> --hist <history-2025 checkout> --acars <acars-data checkout> --out gulf.db
  air-history: air/air-*.csv.gz (hex,type,reg,callsign,minute,lat,lon,alt; day-only rows have empty lat/lon) + moves/moves-*.csv.gz
  history-2025: legs_all.csv.gz (hex,type,reg,ownOp,callsign,from,to,day,time_min)
  acars-data: acars/destinations.csv (msg_time,hex,tail,callsign,kind,from,to,eta,msg_id)
Minutes and days are since 1970-01-01 UTC (same as every other file in the repo)."""
import argparse, csv, datetime, glob, gzip, hashlib, json, math, os, re, sqlite3, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from types_groups import group          # one shared ICAO type -> group list (4 Nov 2026)
from acars.archive import country       # ICAO hex block -> US / UK / IL / RU / CN

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE aircraft(hex TEXT PRIMARY KEY, type TEXT, reg TEXT, callsign TEXT, grp TEXT, country TEXT,
                      first_day INT, last_day INT, days_30 INT, days_90 INT, last_minute REAL);
CREATE TABLE positions(hex TEXT, minute REAL, lat REAL, lon REAL, alt INT, source TEXT);
CREATE TABLE presence(day INT, hex TEXT, source TEXT, points INT, PRIMARY KEY(day, hex, source)) WITHOUT ROWID;
CREATE TABLE legs(hex TEXT, minute INT, day INT, from_apt TEXT, to_apt TEXT, callsign TEXT, type TEXT, reg TEXT);
CREATE TABLE events(minute REAL, hex TEXT, reg TEXT, callsign TEXT, type TEXT, category TEXT, event TEXT, place TEXT,
                    lat REAL, lon REAL, alt INT, note TEXT);
CREATE TABLE acars_dest(msg_id TEXT PRIMARY KEY, minute REAL, hex TEXT, tail TEXT, callsign TEXT, kind TEXT,
                        from_apt TEXT, to_apt TEXT, eta TEXT);
"""
INDEXES = """
CREATE INDEX pos_hex ON positions(hex, minute);
CREATE INDEX pos_min ON positions(minute);
CREATE INDEX leg_hex ON legs(hex, minute);
CREATE INDEX leg_day ON legs(day);
CREATE INDEX leg_min ON legs(minute);
CREATE INDEX leg_to ON legs(to_apt, minute);
CREATE INDEX ev_min ON events(minute);
CREATE INDEX ev_hex ON events(hex, minute);
CREATE INDEX ac_dest_hex ON acars_dest(hex, minute);
CREATE INDEX ac_grp ON aircraft(grp, last_day);
"""
HEX = re.compile(r'~?[0-9a-f]{6}')


def fnum(s):
    try:
        x = float(s)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None   # 'nan' / 'inf' parse as floats and would crash int() below


def source_of(path):   # air-2026-11-03 -> adsb, air-bot-… -> bot, air-chan / air-fr24 / air-log
    m = re.match(r'air-([a-z0-9]+)-\d{4}-', os.path.basename(path))
    return m.group(1) if m else 'adsb'


def iso_minute(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00')).timestamp() / 60
    except ValueError:
        return None


def build(air, hist, acars, out):
    t0 = time.time()
    tmp = out + '.tmp'
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;' + SCHEMA)
    ac = {}                                    # hex -> [type, reg, callsign, first_day, last_day, days set, last_minute]

    def seen(hx, t, reg, cs, minute):
        a = ac.setdefault(hx, ['', '', '', None, None, set(), 0])
        d = int(minute // 1440)
        if t: a[0] = t
        if reg: a[1] = reg
        if cs and minute >= a[6]: a[2] = cs
        a[3] = d if a[3] is None else min(a[3], d)
        a[4] = d if a[4] is None else max(a[4], d)
        a[5].add(d)
        a[6] = max(a[6], minute)

    # 1. airborne points + day-only rows (air-history)
    n_pos = 0
    pres = {}
    for f in sorted(glob.glob(os.path.join(air, 'air', 'air-*.csv.gz'))):
        src, rows = source_of(f), []
        for r in csv.reader(gzip.open(f, 'rt')):
            if len(r) < 8 or not HEX.fullmatch(r[0].lower()):
                continue
            hx, m = r[0].lower().lstrip('~'), fnum(r[4])
            if m is None:
                continue
            seen(hx, r[1], r[2], r[3], m)
            k = (int(m // 1440), hx, src)
            pres[k] = pres.get(k, 0) + 1
            la, lo = fnum(r[5]), fnum(r[6])
            if la is not None and lo is not None:
                rows.append((hx, m, la, lo, int(fnum(r[7]) or 0), src))
        db.executemany('INSERT INTO positions VALUES (?,?,?,?,?,?)', rows)
        n_pos += len(rows)
    db.executemany('INSERT INTO presence VALUES (?,?,?,?)', [k + (v,) for k, v in pres.items()])

    # 2. take-offs / landings (history-2025 legs)
    n_leg = 0
    lp = os.path.join(hist, 'legs_all.csv.gz')
    if os.path.exists(lp):
        rows = []
        for r in csv.DictReader(gzip.open(lp, 'rt')):
            hx = (r.get('hex') or '').lower().lstrip('~')
            m = fnum(r.get('time_min'))
            if not HEX.fullmatch(hx) or m is None:
                continue
            seen(hx, r.get('type'), r.get('reg'), r.get('callsign'), m)
            rows.append((hx, int(m), int(m // 1440), r.get('from') or '', r.get('to') or '', r.get('callsign') or '',
                         r.get('type') or '', r.get('reg') or ''))
        db.executemany('INSERT INTO legs VALUES (?,?,?,?,?,?,?,?)', rows)
        n_leg = len(rows)

    # 3. the bot's movement log (air-history moves/)
    rows = []
    for f in sorted(glob.glob(os.path.join(air, 'moves', 'moves-*.csv.gz'))):
        for r in csv.reader(gzip.open(f, 'rt')):
            hx = r[1].lower() if len(r) == 12 else ''
            if not HEX.fullmatch(hx):
                continue
            m = fnum(r[0])
            if m is None:
                continue
            rows.append((m, hx.lstrip('~'), r[2], r[3], r[4], r[5], r[6], r[7], fnum(r[8]), fnum(r[9]), int(fnum(r[10]) or 0), r[11]))
    db.executemany('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    n_ev = len(rows)

    # 4. destinations the aircraft stated in ACARS (acars-data)
    rows = {}
    dp = os.path.join(acars, 'acars', 'destinations.csv')
    if os.path.exists(dp):
        for r in csv.DictReader(open(dp, newline='')):
            hx, m = (r.get('hex') or '').lower(), iso_minute(r.get('msg_time'))
            if HEX.fullmatch(hx) and m is not None and r.get('msg_id'):
                rows[r['msg_id']] = (r['msg_id'], m, hx.lstrip('~'), r.get('tail') or '', r.get('callsign') or '', r.get('kind') or '',
                                     r.get('from') or '', r.get('to') or '', r.get('eta') or '')
    db.executemany('INSERT INTO acars_dest VALUES (?,?,?,?,?,?,?,?,?)', rows.values())
    n_dest = len(rows)

    # 5. one row per airframe
    asof = max((a[4] for a in ac.values() if a[4] is not None), default=0)
    db.executemany('INSERT INTO aircraft VALUES (?,?,?,?,?,?,?,?,?,?,?)', [
        (hx, a[0], a[1], a[2], group(a[0]), country(hx), a[3], a[4],
         sum(1 for d in a[5] if d > asof - 30), sum(1 for d in a[5] if d > asof - 90), round(a[6], 1))
        for hx, a in ac.items()])

    db.executescript(INDEXES)
    counts = {'aircraft': len(ac), 'positions': n_pos, 'presence': len(pres), 'legs': n_leg, 'events': n_ev,
              'acars_dest': n_dest}
    meta = {'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'data_to_day': asof, 'counts': json.dumps(counts), 'schema': '1'}
    db.executemany('INSERT INTO meta VALUES (?,?)', meta.items())
    db.commit()
    db.execute('VACUUM')
    db.close()
    os.replace(tmp, out)
    print('built %s in %.1f s: %s' % (out, time.time() - t0, counts))
    return counts


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--air', required=True)
    p.add_argument('--hist', required=True)
    p.add_argument('--acars', required=True)
    p.add_argument('--out', default='gulf.db')
    a = p.parse_args()
    build(a.air, a.hist, a.acars, a.out)
