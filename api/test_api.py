#!/usr/bin/env python3
"""Self-test for build_db.py + app.py on a tiny made-up data set (no network).  usage: python3 api/test_api.py
Optional real-data smoke test: DB_PATH=/path/gulf.db python3 api/test_api.py"""
import csv, gzip, importlib, json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_db

M = 29897000                                    # a minute in Nov 2026


def fixture(d):
    os.makedirs(os.path.join(d, 'air', 'air'))
    os.makedirs(os.path.join(d, 'air', 'moves'))
    os.makedirs(os.path.join(d, 'hist'))
    os.makedirs(os.path.join(d, 'acars', 'acars'))
    with gzip.open(os.path.join(d, 'air', 'air', 'air-2026-11-03.csv.gz'), 'wt') as f:
        w = csv.writer(f)
        for i in range(30):                    # tanker orbiting, 15-min points
            w.writerow(['ae04b4', 'K35R', '57-1499', 'CLEAN51', M + i * 15, 25 + i / 100, 51, 30000])
        w.writerow(['ae04b4', 'K35R', '57-1499', 'CLEAN51', M - 5000, '', '', ''])   # day-only row
        w.writerow(['zzzzzz', 'K35R', 'x', 'x', M, 1, 1, 1])                          # bad hex: skipped
    with gzip.open(os.path.join(d, 'air', 'air', 'air-bot-2026-11-03.csv.gz'), 'wt') as f:
        csv.writer(f).writerow(['ae5f92', 'KC46', '18-46039', 'CLEAN53', M + 10, 26, 52, 28000])
    with gzip.open(os.path.join(d, 'air', 'moves', 'moves-2026-11.csv.gz'), 'wt') as f:
        csv.writer(f).writerow([M + 100, 'ae04b4', '57-1499', 'CLEAN51', 'K35R', 'Tanker', 'landed', 'OTBH', 25.1, 51.3, 0, ''])
    with gzip.open(os.path.join(d, 'hist', 'legs_all.csv.gz'), 'wt') as f:
        w = csv.writer(f)
        w.writerow(['hex', 'type', 'reg', 'ownOp', 'callsign', 'from', 'to', 'day', 'time_min'])
        for i in range(5):
            w.writerow(['ae04b4', 'K35R', '57-1499', '', 'CLEAN5%d' % i, 'EGUN', 'OTBH', (M - i * 1440) // 1440, M - i * 1440])
    with open(os.path.join(d, 'acars', 'acars', 'destinations.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['msg_time', 'hex', 'tail', 'callsign', 'kind', 'from', 'to', 'eta', 'msg_id'])
        w.writerow(['2026-11-04T10:00:00Z', 'AE04B4', '57-1499', 'CLEAN51', 'flight plan', 'EGUN', 'OTBH', '', '1'])


def client(path, key='k'):
    os.environ.update(DB_PATH=path, API_KEY=key)
    if 'app' in sys.modules:
        del sys.modules['app']
    app = importlib.import_module('app')
    return app, app.app.test_client()


def main():
    d = tempfile.mkdtemp()
    fixture(d)
    c = build_db.build(os.path.join(d, 'air'), os.path.join(d, 'hist'), os.path.join(d, 'acars'), os.path.join(d, 'g.db'))
    assert c == {'aircraft': 2, 'positions': 31, 'presence': 4, 'legs': 5, 'events': 1, 'acars_dest': 1}, c
    app, t = client(os.path.join(d, 'g.db'))
    H = {'X-Api-Key': 'k'}

    assert t.get('/health').status_code == 200
    assert t.get('/v1/aircraft').status_code == 403                       # no key
    assert t.get('/v1/aircraft?key=k').status_code == 403                 # key in the URL is not accepted
    assert t.get('/v1/aircraft', headers={'X-Api-Key': 'nope'}).status_code == 403

    r = t.get('/v1/aircraft', headers=H).get_json()
    assert [a['hex'] for a in r['items']] == ['ae04b4', 'ae5f92'], r     # newest last point first
    assert r['items'][1]['grp'] == 'TANKER' and r['items'][1]['country'] == 'US'
    assert t.get('/v1/aircraft?group=tanker&q=CLEAN51', headers=H).get_json()['items'][0]['hex'] == 'ae04b4'

    a = t.get('/v1/aircraft/AE04B4', headers=H).get_json()
    assert a['last_position']['minute'] == M + 29 * 15 and a['events'][0]['place'] == 'OTBH'
    assert a['acars_destination']['to_apt'] == 'OTBH' and len(a['legs']) == 5
    assert t.get('/v1/aircraft/ffffff', headers=H).status_code == 404
    assert t.get('/v1/aircraft/xyz', headers=H).status_code == 400

    tr = t.get('/v1/aircraft/ae04b4/track?from=%d&to=%d' % (M, M + 1000), headers=H).get_json()
    assert len(tr['points']) == 30 and tr['points'][0]['minute'] == M
    assert t.get('/v1/aircraft/ae04b4/track?from=0&to=%d' % M, headers=H).status_code == 400   # > 31 days
    assert len(t.get('/v1/aircraft/ae04b4/track', headers=H).get_json()['points']) == 30      # default: 24 h up to its last point

    # keyset paging over legs: 5 rows in pages of 2 = 2 + 2 + 1, no repeats
    seen, cur = [], ''
    for _ in range(4):
        p = t.get('/v1/legs?hex=ae04b4&limit=2' + ('&cursor=' + cur if cur else ''), headers=H).get_json()
        seen += [x['minute'] for x in p['items']]
        cur = p['next']
        if not cur:
            break
    assert seen == sorted(seen, reverse=True) and len(set(seen)) == 5, seen
    assert t.get('/v1/legs?cursor=bad', headers=H).status_code == 400

    assert t.get('/v1/events?event=landed', headers=H).get_json()['items'][0]['hex'] == 'ae04b4'
    assert t.get('/v1/acars/destinations?hex=ae04b4', headers=H).get_json()['items'][0]['kind'] == 'flight plan'
    s = t.get('/v1/stats/daily?days=10&group=TANKER', headers=H).get_json()['days']
    assert s and all(x['grp'] == 'TANKER' for x in s)

    # cache + ETag: same answer, 304 on If-None-Match
    r1 = t.get('/v1/aircraft/ae04b4', headers=H)
    r2 = t.get('/v1/aircraft/ae04b4', headers=dict(H, **{'If-None-Match': r1.headers['ETag']}))
    assert r2.status_code == 304 and r1.headers['Cache-Control'].startswith('private')

    # a new database version is never answered from the old cache
    v0 = app._DB['version']
    fixture2 = os.path.join(d, 'g2.db')
    import shutil, sqlite3
    shutil.copy(os.path.join(d, 'g.db'), fixture2)
    con = sqlite3.connect(fixture2); con.execute("UPDATE aircraft SET reg = 'NEW' WHERE hex = 'ae04b4'"); con.commit(); con.close()
    app._install(fixture2)
    assert app._DB['version'] != v0 and t.get('/v1/aircraft/ae04b4', headers=H).get_json()['reg'] == 'NEW'

    # fail closed without API_KEY
    _, t2 = client(os.path.join(d, 'g.db'), key='')
    assert t2.get('/v1/aircraft', headers=H).status_code == 503
    print('selftest ok')


def smoke(path):
    _, t = client(path)
    H = {'X-Api-Key': 'k'}
    print('health', t.get('/health').get_json())
    for u in ['/v1/aircraft?group=TANKER&active_days=7&limit=5', '/v1/aircraft/ae04b4', '/v1/aircraft/ae04b4/track',
              '/v1/events?limit=5', '/v1/legs?to_apt=OTBH&limit=5', '/v1/acars/destinations?limit=5',
              '/v1/stats/daily?days=30', '/v1/legs?limit=1000']:
        t0 = time.time(); r = t.get(u, headers=H); t1 = time.time(); t.get(u, headers=H); t2 = time.time()
        assert r.status_code == 200, (u, r.status_code)
        body = r.get_json()
        n = len(body.get('items') or body.get('points') or body.get('days') or []) if isinstance(body, dict) else 0
        print('%-48s %d  %4d rows  first %6.1f ms  cached %5.1f ms  %6d bytes' % (u, r.status_code, n, (t1 - t0) * 1e3, (t2 - t1) * 1e3, len(r.data)))


if __name__ == '__main__':
    if os.environ.get('DB_PATH'):
        smoke(os.environ['DB_PATH'])
    else:
        main()
