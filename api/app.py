"""Gulf API — read-only HTTP API over gulf.db (System Design phase 1, 4 Nov 2026).

The database is an immutable SQLite file built by .github/workflows/api-db.yml from the git data branches and published
as the release asset gulf.db.gz (tag api-db). Each instance downloads it at start and re-checks every REFRESH_S with
an ETag, then swaps it in atomically. Writers never touch a running database, so readers need no locks.

Env:
  API_KEY     required; clients send it in the X-Api-Key header (never in the URL: URLs end up in request logs)
  DB_PATH     local database file (tests / local runs); used as-is when set
  DB_ASSET    GitHub API URL of the release: …/repos/<owner>/<repo>/releases/tags/api-db (not an …/assets/<id> URL:
              every build re-uploads gulf.db.gz, which gives it a new asset id)
  GH_TOKEN    read-only GitHub token for the private repo (Contents: read)
  REFRESH_S   seconds between update checks (default 900)

Endpoints (JSON; times are minutes since 1970-01-01 UTC, days are days since 1970-01-01):
  GET /health                                   no key; database version and row counts
  GET /v1/aircraft?group=&country=&active_days=&q=&limit=&cursor=
  GET /v1/aircraft/<hex>                        profile + last position + last legs / events / ACARS destination
  GET /v1/aircraft/<hex>/track?from=&to=&limit= positions, oldest first
  GET /v1/events?since=&until=&event=&hex=&limit=&cursor=
  GET /v1/legs?hex=&from_apt=&to_apt=&since=&until=&limit=&cursor=
  GET /v1/acars/destinations?hex=&since=&limit=&cursor=
  GET /v1/stats/daily?days=&group=              airframes flying per day and group
Paging: newest first, `cursor` = the `next` value of the previous page. Errors: {"error": "..."} with 400 / 403 / 404 / 503.
"""
import gzip, hashlib, hmac, json, os, shutil, sqlite3, threading, time, urllib.parse, urllib.request
from collections import OrderedDict

from flask import Flask, Response, g, request

app = Flask(__name__)
app.logger.setLevel('INFO')
MAX_LIMIT = 1000
_DB = {'path': None, 'version': None, 'etag': None, 'asset': None, 'meta': {}}
_LOCK = threading.Lock()


# ---------- database: download, verify, swap ----------
def _open(path):
    con = sqlite3.connect('file:%s?mode=ro&immutable=1' % path, uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _install(path):
    """Check a downloaded file, then make it the live database (old file removed once swapped)."""
    con = _open(path)
    meta = {r['key']: r['value'] for r in con.execute('SELECT key, value FROM meta')}
    con.execute('SELECT hex FROM aircraft LIMIT 1').fetchall()
    con.close()
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    with _LOCK:
        old = _DB['path']
        _DB.update(path=path, version=h.hexdigest()[:12], meta=meta)
        _CACHE.clear()
    if old and old != path and not os.environ.get('DB_PATH'):
        threading.Timer(120, lambda: os.path.exists(old) and os.remove(old)).start()   # let running requests finish


class _NoAuthOnOtherHost(urllib.request.HTTPRedirectHandler):
    """GitHub answers an asset download with a redirect to a signed URL on another host: do not send it our token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header('Authorization')
        return new


_HTTP = urllib.request.build_opener(_NoAuthOnOtherHost)


def _fetch_asset():
    """Download gulf.db.gz when it changed. Returns True when a new database was installed.
    Change test: the asset's id + updated_at from the release (each build re-uploads it), then the ETag as a fallback."""
    url, tok = os.environ.get('DB_ASSET', ''), os.environ.get('GH_TOKEN', '')
    if not url:
        return False
    hdr = {'Accept': 'application/octet-stream', 'User-Agent': 'gulf-api/1.0'}
    if tok:
        hdr['Authorization'] = 'Bearer ' + tok
    asset = None
    if '/releases/tags/' in url:   # resolve the tag to its gulf.db.gz asset
        req = urllib.request.Request(url, headers=dict(hdr, Accept='application/vnd.github+json'))
        with _HTTP.open(req, timeout=30) as r:
            rel = json.load(r)
        a = next((a for a in rel.get('assets', []) if a['name'] == 'gulf.db.gz'), None)
        if a is None:
            raise RuntimeError('release has no gulf.db.gz (build still uploading?)')
        url, asset = a['url'], '%s@%s' % (a['id'], a.get('updated_at'))
        if _DB['path'] and asset == _DB['asset']:
            return False
    if _DB['path'] and _DB['etag'] and asset is None:   # GitHub said the asset changed: always download it
        hdr['If-None-Match'] = _DB['etag']
    try:
        r = _HTTP.open(urllib.request.Request(url, headers=hdr), timeout=120)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            _DB['asset'] = asset
            return False
        raise
    dst = '/tmp/gulf-%d.db' % time.time_ns()   # unique even when two fetches land in the same second
    try:                            # /tmp is memory on Cloud Run: never leave a partial or rejected copy behind
        with r, gzip.GzipFile(fileobj=r) as src, open(dst + '.part', 'wb') as out:
            shutil.copyfileobj(src, out, 1 << 20)
        os.replace(dst + '.part', dst)
        _install(dst)
    except BaseException:
        for p in (dst + '.part', dst):
            if os.path.exists(p) and p != _DB['path']:
                os.remove(p)
        raise
    _DB.update(etag=r.headers.get('ETag'), asset=asset)
    return True


def _refresher():
    first = True
    while True:   # first try at once; no database yet: retry every 30 s, not after a full REFRESH_S
        if not first:
            time.sleep(30 if _DB['path'] is None else int(os.environ.get('REFRESH_S', '900')))
        first = False
        try:
            if _fetch_asset():
                app.logger.info('database updated to %s', _DB['version'])
        except Exception as e:   # keep serving the current database; try again next round
            app.logger.warning('database refresh failed: %s', e)


def _startup():
    if os.environ.get('DB_PATH'):
        _install(os.environ['DB_PATH'])
    else:   # download in the background: the worker starts at once and /health answers 503 until the database is in
        threading.Thread(target=_refresher, daemon=True).start()


def db():
    if _DB['path'] is None:
        return None
    c = g.get('con')
    if c is None or g.get('con_path') != _DB['path']:
        c = g.con = _open(_DB['path'])
        g.con_path = _DB['path']
    return c


@app.teardown_appcontext
def _close(_e):
    c = g.pop('con', None)
    if c is not None:
        c.close()


# ---------- response cache (per instance, keyed by database version) ----------
class TTLCache:
    """Small LRU with per-entry expiry. Entries are tied to the database version, so a new database never serves
    an old answer. ponytail: per-instance only; a shared cache (Memorystore) is only worth it past a few instances."""

    def __init__(self, size=512, max_bytes=64 << 20):   # bytes cap too: one track answer can be ~1 MB
        self.size, self.max_bytes, self.bytes, self.d, self.lock = size, max_bytes, 0, OrderedDict(), threading.Lock()

    def get(self, k):
        with self.lock:
            v = self.d.get(k)
            if not v or v[0] < time.time():
                if v:
                    self.bytes -= len(self.d.pop(k)[1])
                return None
            self.d.move_to_end(k)
            return v[1]

    def put(self, k, v, ttl):
        if len(v) > self.max_bytes // 8:
            return
        with self.lock:
            if k in self.d:
                self.bytes -= len(self.d[k][1])
            self.d[k] = (time.time() + ttl, v)
            self.bytes += len(v)
            self.d.move_to_end(k)
            while len(self.d) > self.size or self.bytes > self.max_bytes:
                self.bytes -= len(self.d.popitem(last=False)[1][1])

    def clear(self):
        with self.lock:
            self.d.clear()
            self.bytes = 0


_CACHE = TTLCache()


# ---------- helpers ----------
class NotFound(Exception):
    pass


def err(code, msg):
    return Response(json.dumps({'error': msg}), status=code, mimetype='application/json')


def num(name, default=None, lo=None, hi=None):
    v = request.args.get(name)
    if v in (None, ''):
        return default
    try:
        x = float(v)
    except ValueError:
        raise ValueError('%s must be a number' % name)
    if lo is not None: x = max(lo, x)
    if hi is not None: x = min(hi, x)
    return x


def limit():
    return int(num('limit', 100, 1, MAX_LIMIT))


def hexarg(h):
    h = (h or '').strip().lower().lstrip('~')
    if len(h) != 6 or any(c not in '0123456789abcdef' for c in h):
        raise ValueError('hex must be 6 hex digits')
    return h


def rows(sql, args=()):
    return [dict(r) for r in db().execute(sql, args)]


def page(sql_where, args, table, cols, order_col, lim):
    """Keyset paging, newest first: cursor = '<order value>:<rowid>' of the last row returned."""
    cur = request.args.get('cursor')
    if cur:
        try:
            v, rid = cur.rsplit(':', 1)
            sql_where.append('(%s < ? OR (%s = ? AND rowid < ?))' % (order_col, order_col))
            args += [float(v), float(v), int(rid)]
            if not 0 < args[-1] < 1 << 63:
                raise ValueError
        except ValueError:
            raise ValueError('bad cursor')
    w = (' WHERE ' + ' AND '.join(sql_where)) if sql_where else ''
    out = rows('SELECT rowid AS _rid, %s FROM %s%s ORDER BY %s DESC, rowid DESC LIMIT ?' % (cols, table, w, order_col),
               args + [lim])
    nxt = ('%s:%d' % (out[-1][order_col], out[-1]['_rid'])) if len(out) == lim else None
    for r in out:
        r.pop('_rid')
    return {'items': out, 'next': nxt}


def cached(ttl):
    """Cache GET answers per database version + full URL; send ETag / Cache-Control and answer 304."""
    def deco(fn):
        def wrap(*a, **k):
            if db() is None:
                return err(503, 'database not loaded yet')
            key = (_DB['version'], request.full_path)
            body = _CACHE.get(key)
            if body is None:
                try:
                    body = json.dumps(fn(*a, **k), separators=(',', ':'))
                except ValueError as e:
                    return err(400, str(e))
                except NotFound as e:
                    return err(404, str(e))
                _CACHE.put(key, body, ttl)
            tag = '"%s-%s"' % (_DB['version'], hashlib.sha1(body.encode()).hexdigest()[:10])
            if request.headers.get('If-None-Match') == tag:
                return Response(status=304, headers={'ETag': tag})
            return Response(body, mimetype='application/json',
                            headers={'ETag': tag, 'Cache-Control': 'private, max-age=%d' % ttl})
        wrap.__name__ = fn.__name__
        return wrap
    return deco


@app.before_request
def auth():
    if request.path == '/health':
        return None
    key = os.environ.get('API_KEY', '')
    if not key:
        return err(503, 'API_KEY not configured')   # fail closed: never run open
    if not hmac.compare_digest(request.headers.get('X-Api-Key', '').encode(), key.encode()):
        return err(403, 'bad key')
    return None


# ---------- endpoints ----------
@app.get('/health')
def health():
    m = _DB['meta']
    return {'ok': _DB['path'] is not None, 'version': _DB['version'], 'built_at': m.get('built_at'),
            'data_to_day': m.get('data_to_day'), 'counts': json.loads(m.get('counts', '{}'))}, \
        (200 if _DB['path'] else 503)


@app.get('/v1/aircraft')
@cached(300)
def aircraft_list():
    w, a = [], []
    if request.args.get('group'):
        w.append('grp = ?'); a.append(request.args['group'].upper())
    if request.args.get('country'):
        w.append('country = ?'); a.append(request.args['country'].upper())
    days = num('active_days', None, 1, 3650)
    if days:
        w.append("last_day > (SELECT CAST(value AS INT) FROM meta WHERE key = 'data_to_day') - ?"); a.append(days)
    q = (request.args.get('q') or '').strip().upper()
    if q:
        w.append('(UPPER(callsign) LIKE ? OR UPPER(reg) LIKE ? OR hex = ?)'); a += [q + '%', q + '%', q.lower()]
    return page(w, a, 'aircraft', 'hex, type, reg, callsign, grp, country, first_day, last_day, days_30, days_90, last_minute',
                'last_minute', limit())


@app.get('/v1/aircraft/<h>')
@cached(120)
def aircraft_one(h):
    h = hexarg(h)
    a = rows('SELECT * FROM aircraft WHERE hex = ?', (h,))
    if not a:
        raise NotFound('unknown aircraft')
    out = a[0]
    out['last_position'] = (rows('SELECT minute, lat, lon, alt, source FROM positions WHERE hex = ? '
                                 'ORDER BY minute DESC LIMIT 1', (h,)) or [None])[0]
    out['legs'] = rows('SELECT minute, from_apt, to_apt, callsign FROM legs WHERE hex = ? ORDER BY minute DESC LIMIT 10', (h,))
    out['events'] = rows('SELECT minute, event, place, lat, lon, alt, note FROM events WHERE hex = ? '
                         'ORDER BY minute DESC LIMIT 10', (h,))
    out['acars_destination'] = (rows('SELECT minute, kind, from_apt, to_apt, eta, callsign FROM acars_dest WHERE hex = ? '
                                     'ORDER BY minute DESC LIMIT 1', (h,)) or [None])[0]
    out['sources'] = rows('SELECT source, COUNT(*) AS days, SUM(points) AS points FROM presence WHERE hex = ? '
                          'GROUP BY source', (h,))
    return out


@app.get('/v1/aircraft/<h>/track')
@cached(120)
def track(h):
    h = hexarg(h)
    t1 = num('to')
    if t1 is None:                          # default end: the aircraft's last known position, not "now"
        t1 = (db().execute('SELECT MAX(minute) FROM positions WHERE hex = ?', (h,)).fetchone()[0] or 0)
    t0 = num('from', t1 - 1440)             # default: the 24 h before the end
    if t1 - t0 > 31 * 1440:
        raise ValueError('at most 31 days per request')
    return {'hex': h, 'points': rows('SELECT minute, lat, lon, alt, source FROM positions WHERE hex = ? AND minute BETWEEN ? AND ? '
                                     'ORDER BY minute LIMIT ?', (h, t0, t1, limit() * 10))}


@app.get('/v1/events')
@cached(60)
def events():
    w, a = [], []
    if request.args.get('since'): w.append('minute >= ?'); a.append(num('since'))
    if request.args.get('until'): w.append('minute < ?'); a.append(num('until'))
    if request.args.get('event'): w.append('event = ?'); a.append(request.args['event'])
    if request.args.get('hex'): w.append('hex = ?'); a.append(hexarg(request.args['hex']))
    return page(w, a, 'events', 'minute, hex, reg, callsign, type, category, event, place, lat, lon, alt, note', 'minute', limit())


@app.get('/v1/legs')
@cached(300)
def legs():
    w, a = [], []
    if request.args.get('hex'): w.append('hex = ?'); a.append(hexarg(request.args['hex']))
    if request.args.get('from_apt'): w.append('from_apt = ?'); a.append(request.args['from_apt'].upper())
    if request.args.get('to_apt'): w.append('to_apt = ?'); a.append(request.args['to_apt'].upper())
    if request.args.get('since'): w.append('minute >= ?'); a.append(num('since'))
    if request.args.get('until'): w.append('minute < ?'); a.append(num('until'))
    return page(w, a, 'legs', 'minute, hex, from_apt, to_apt, callsign, type, reg', 'minute', limit())


@app.get('/v1/acars/destinations')
@cached(120)
def acars_dest():
    w, a = [], []
    if request.args.get('hex'): w.append('hex = ?'); a.append(hexarg(request.args['hex']))
    if request.args.get('since'): w.append('minute >= ?'); a.append(num('since'))
    return page(w, a, 'acars_dest', 'minute, hex, tail, callsign, kind, from_apt, to_apt, eta', 'minute', limit())


@app.get('/v1/stats/daily')
@cached(600)
def stats_daily():
    days = int(num('days', 30, 1, 400))
    w, a = ["p.day > (SELECT CAST(value AS INT) FROM meta WHERE key = 'data_to_day') - ?"], [days]
    if request.args.get('group'):
        w.append('ac.grp = ?'); a.append(request.args['group'].upper())
    return {'days': rows('SELECT p.day, ac.grp AS grp, COUNT(DISTINCT p.hex) AS airframes FROM presence p '
                         'JOIN aircraft ac ON ac.hex = p.hex WHERE ' + ' AND '.join(w) +
                         ' GROUP BY p.day, ac.grp ORDER BY p.day', a)}


_startup()
