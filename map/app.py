"""Gulf Situation map drawer (Night Ops style).

POST /draw  JSON  -> image/jpeg
  key      shared key (must match env MAP_KEY when that is set)
  track    [[lon, lat], ...]  oldest first; last point = aircraft now (1+ points)
  label    text under the plane, e.g. "YETI41 · KC-46A · FL260"
  start    optional text at the first track point, e.g. "Took off Souda Bay 09:12 UTC"
  title    optional title bar text (default "GULF SITUATION · AIRCRAFT WATCH")
  foot     optional footer text
  heading  optional degrees (0 = north); otherwise taken from the last track leg
  bbox     optional [lon0, lat0, lon1, lat1]; otherwise fitted to the track
  others   optional group alert: [{track, label, heading, type_code}, ...] planes flying with the lead; all kept in frame
GET /health -> "ok"
"""
import io, json, math, os, re, threading, time, urllib.parse, urllib.request

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.collections import LineCollection, PolyCollection
import numpy as np
from flask import Flask, Response, request
from PIL import Image
import icons

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1280, 720
S = dict(land='#2c333b', sea='#161c22', border='#66717d', coast='#4b5560', label='#cfd6dd', country='#7d8893',
         halo='#000000', track='#ffb000', bar='#0f1317', bar_text='#9dbb6b', tag='#ffffff')  # Ops Slate (the owner 24 Oct 2026)


def merc_xy(lon, lat):
    lat = max(-85.0, min(85.0, lat))
    return lon, math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


_HOLES = {'land.geojson': [], 'land10.geojson': []}


def _load(lf, cf):
    land = json.load(open(os.path.join(HERE, lf)))
    polys = []
    for f in land['features']:
        g = f['geometry']
        rings = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for poly in rings:
            a = np.array(poly[0], dtype=float)
            a[:, 1] = np.degrees(np.log(np.tan(np.pi / 4 + np.radians(np.clip(a[:, 1], -85, 85)) / 2)))
            polys.append((a[:, 0].min(), a[:, 0].max(), a[:, 1].min(), a[:, 1].max(), a))
            for hole in poly[1:]:  # water inside land (the Caspian Sea) — was thrown away, so it was painted as land (the owner 25 Oct 2026)
                h = np.array(hole, dtype=float)
                if h[:, 1].max() < -85:
                    continue  # Antarctica's edge artefact in the 110m file, not water
                h[:, 1] = np.degrees(np.log(np.tan(np.pi / 4 + np.radians(np.clip(h[:, 1], -85, 85)) / 2)))
                _HOLES[lf].append((h[:, 0].min(), h[:, 0].max(), h[:, 1].min(), h[:, 1].max(), h))
    b = json.load(open(os.path.join(HERE, cf)))
    g = b.get('geometry', b)
    lines = []
    for line in g['coordinates']:
        a = np.array(line, dtype=float)
        a[:, 1] = np.degrees(np.log(np.tan(np.pi / 4 + np.radians(np.clip(a[:, 1], -85, 85)) / 2)))
        lines.append((a[:, 0].min(), a[:, 0].max(), a[:, 1].min(), a[:, 1].max(), a))
    return polys, lines


POLYS, LINES = _load('land.geojson', 'countries.geojson')
POLYS10, LINES10 = _load('land10.geojson', 'countries10.geojson')
HOLES, HOLES10 = _HOLES['land.geojson'], _HOLES['land10.geojson']


def _load_detail():
    """Map detail (Natural Earth 1:10m, cut to the bot's region): rivers, lakes, province lines, main roads, built-up areas
    (the owner 25 Oct 2026: 'the entire map thing is missing details')."""
    raw = json.load(open(os.path.join(HERE, 'detail.json')))
    out = {}
    for k, parts in raw.items():
        L = []
        for c in parts:
            a = np.array(c, dtype=float)
            a[:, 1] = np.degrees(np.log(np.tan(np.pi / 4 + np.radians(np.clip(a[:, 1], -85, 85)) / 2)))
            L.append((a[:, 0].min(), a[:, 0].max(), a[:, 1].min(), a[:, 1].max(), a))
        out[k] = L
    return out


DETAIL = _load_detail()


def _detail(ax, X0, X1, Y0, Y1, span):
    """Geographic detail shared by every map the service draws (alert maps, airport holding maps): Caspian Sea as water,
    built-up areas, lakes, rivers, and on close-ups province lines and main roads — enough to read the area, no small clutter
    (the owner 25 Oct 2026)."""
    hv = [p[4] for p in (HOLES10 if span < 25 else HOLES) if p[1] >= X0 and p[0] <= X1 and p[3] >= Y0 and p[2] <= Y1]
    if hv:  # Caspian Sea drawn as water (the owner 25 Oct 2026)
        ax.add_collection(PolyCollection(hv, facecolors=S['sea'], edgecolors=S['coast'], linewidths=0.8, zorder=1.5))
    _in = lambda k: [p[4] for p in DETAIL[k] if p[1] >= X0 and p[0] <= X1 and p[3] >= Y0 and p[2] <= Y1]
    ax.add_collection(PolyCollection(_in('urban'), facecolors='#3a424c', edgecolors='none', zorder=1.2))  # built-up areas
    ax.add_collection(PolyCollection(_in('lakes'), facecolors=S['sea'], edgecolors=S['coast'], linewidths=0.5, zorder=1.5))
    if span < 40:
        ax.add_collection(LineCollection(_in('rivers'), colors='#2e4d63', linewidths=0.9, zorder=1.6))
    if span < 25:
        ax.add_collection(LineCollection(_in('prov'), colors='#3d454f', linewidths=0.6, linestyles=(0, (1.5, 2)), zorder=1.7))
        ax.add_collection(LineCollection(_in('roads'), colors='#4d5560', linewidths=0.7, zorder=1.8))
LOGO = np.asarray(Image.open(os.path.join(HERE, 'logo.png')).convert('RGB').resize((50, 50)))

# Places shown when inside the frame: (name, lon, lat, label on the left?)
PLACES = [
    ('Mildenhall', 0.49, 52.36, 0), ('Lakenheath', 0.56, 52.41, 1), ('Fairford', -1.79, 51.68, 0), ('Brize Norton', -1.58, 51.75, 1),
    ('Ramstein', 7.60, 49.44, 0), ('Spangdahlem', 6.69, 49.97, 1), ('Aviano', 12.60, 46.03, 0), ('Sigonella', 14.92, 37.40, 0),
    ('Rota', -6.35, 36.64, 0), ('Morón', -5.62, 37.17, 1), ('Lajes', -27.09, 38.76, 0), ('Istres', 4.92, 43.52, 0),
    ('Souda Bay', 24.15, 35.53, 0), ('Akrotiri', 32.99, 34.59, 0), ('Incirlik', 35.43, 37.00, 0), ('Sofia', 23.41, 42.70, 0),
    ('Bucharest', 26.08, 44.57, 0), ('Athens', 23.73, 37.98, 0), ('Ankara', 32.85, 39.93, 0), ('Beirut', 35.50, 33.89, 1),
    ('Damascus', 36.29, 33.51, 0), ('Tel Aviv', 34.78, 32.08, 1), ('Amman', 35.93, 31.95, 0), ('Muwaffaq Salti', 36.78, 31.83, 0),
    ('Cairo', 31.24, 30.04, 0), ('Baghdad', 44.36, 33.31, 1), ('Erbil', 44.01, 36.19, 0), ('Kuwait', 47.98, 29.37, 0),
    ('Riyadh', 46.72, 24.71, 0), ('Prince Sultan AB', 47.58, 24.06, 0), ('Bahrain', 50.58, 26.07, 0), ('Al Udeid', 51.31, 25.12, 0),
    ('Al Dhafra', 54.55, 24.25, 1), ('Dubai', 55.27, 25.20, 0), ('Muscat', 58.41, 23.59, 0), ('Tehran', 51.39, 35.69, 0),
    ('Isfahan', 51.67, 32.65, 0), ('Bandar Abbas', 56.27, 27.18, 0), ('Jeddah', 39.17, 21.54, 0), ('Djibouti', 43.15, 11.55, 0),
    ('Sanaa', 44.21, 15.37, 0), ('Aden', 45.03, 12.78, 0), ('Diego Garcia', 72.41, -7.31, 0), ('Benghazi', 20.07, 32.12, 0),
    ('Tripoli', 13.19, 32.89, 0), ('Tunis', 10.18, 36.81, 0), ('Algiers', 3.06, 36.75, 0), ('Madrid', -3.70, 40.42, 0),
    ('Rome', 12.50, 41.90, 0), ('Istanbul', 28.98, 41.01, 0), ('Kyiv', 30.52, 50.45, 0), ('Warsaw', 21.01, 52.23, 0),
    ('Rzeszów', 22.02, 50.11, 0), ('London', -0.13, 51.51, 1), ('Paris', 2.35, 48.86, 0), ('Berlin', 13.40, 52.52, 0),
    ('Prestwick', -4.59, 55.51, 0), ('Shannon', -8.92, 52.70, 0), ('Gander', -54.57, 48.95, 0), ('Bangor', -68.83, 44.81, 0),
]
# Regional cities (Natural Earth populated places: capitals + 250k+ people, Atlantic to Pakistan), biggest first — fills maps over
# Iran, Iraq, Saudi Arabia etc. where the hand list above has nothing (the owner 25 Oct 2026). Names already in PLACES are skipped.
_HAND = {(round(lo), round(la)) for _, lo, la, _l in PLACES}
CITIES = [(c[0], c[1], c[2]) for c in json.load(open(os.path.join(HERE, 'cities.json'))) if (round(c[1]), round(c[2])) not in _HAND]
BASES = {'Mildenhall', 'Lakenheath', 'Fairford', 'Brize Norton', 'Ramstein', 'Spangdahlem', 'Aviano', 'Sigonella', 'Rota', 'Morón',
         'Lajes', 'Istres', 'Souda Bay', 'Akrotiri', 'Incirlik', 'Muwaffaq Salti', 'Prince Sultan AB', 'Al Udeid', 'Al Dhafra',
         'Diego Garcia', 'Djibouti'}

COUNTRIES = [
    ('TURKEY', 33.5, 38.8), ('SYRIA', 38.6, 35.0), ('IRAQ', 43.0, 32.4), ('JORDAN', 37.1, 30.6), ('EGYPT', 29.0, 27.8),
    ('LIBYA', 18.0, 27.5), ('GREECE', 22.2, 39.4), ('SAUDI ARABIA', 45.0, 23.5), ('IRAN', 54.0, 32.5), ('OMAN', 56.8, 20.5),
    ('YEMEN', 47.5, 15.6), ('SPAIN', -4.0, 39.6), ('FRANCE', 2.5, 46.6), ('ITALY', 12.6, 42.9), ('GERMANY', 10.4, 51.2),
    ('POLAND', 19.2, 52.0), ('UKRAINE', 31.5, 49.0), ('UK', -2.0, 53.5), ('ALGERIA', 3.0, 28.5), ('SUDAN', 30.0, 15.5),
    # added 25 Oct 2026 (the owner: IRAN03 over India showed no country names)
    ('INDIA', 79.0, 22.5), ('PAKISTAN', 69.5, 29.0), ('AFGHANISTAN', 66.0, 33.8), ('TURKMENISTAN', 59.0, 39.2), ('UZBEKISTAN', 64.0, 41.7),
    ('KAZAKHSTAN', 67.0, 48.0), ('NEPAL', 84.0, 28.3), ('UAE', 54.2, 23.4), ('KUWAIT', 47.6, 29.3), ('AZERBAIJAN', 47.7, 40.3),
    ('GEORGIA', 43.5, 42.2), ('ARMENIA', 45.0, 40.2), ('LEBANON', 35.9, 33.9), ('ISRAEL', 34.9, 31.0), ('CYPRUS', 33.0, 35.0),
    ('ERITREA', 38.8, 15.6), ('ETHIOPIA', 39.5, 9.0), ('SOMALIA', 45.5, 6.0), ('DJIBOUTI', 42.6, 11.8), ('KENYA', 37.9, 0.5),
    ('SOUTH SUDAN', 30.5, 7.3), ('CHAD', 18.7, 15.5), ('TUNISIA', 9.5, 34.0), ('MOROCCO', -6.0, 32.0), ('PORTUGAL', -8.0, 39.6),
    ('ROMANIA', 25.0, 45.9), ('BULGARIA', 25.3, 42.7), ('SERBIA', 20.8, 44.0), ('HUNGARY', 19.4, 47.2), ('AUSTRIA', 14.5, 47.6),
    ('SWITZERLAND', 8.2, 46.8), ('CZECHIA', 15.3, 49.8), ('BELARUS', 28.0, 53.5), ('BANGLADESH', 90.3, 23.7), ('CHINA', 92.0, 33.0),
]


# ADS-B Exchange / tar1090 altitude colours: hue ramp by altitude (ft), saturation 88 %, lightness by hue
_H = [(0, 20), (2000, 32.5), (4000, 43), (6000, 54), (8000, 72), (9000, 85), (11000, 140), (40000, 300)]
_L = [(0, 53), (20, 50), (32, 54), (40, 52), (46, 51), (50, 46), (60, 43), (80, 41), (100, 41), (120, 41), (140, 41), (160, 40),
      (180, 40), (190, 44), (198, 50), (200, 58), (220, 58), (240, 58), (255, 55), (266, 55), (270, 58), (280, 58), (290, 47),
      (300, 43), (310, 48), (320, 48), (330, 48), (340, 52), (350, 52)]


def _interp(tab, x):
    if x <= tab[0][0]:
        return tab[0][1]
    for (x0, y0), (x1, y1) in zip(tab, tab[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return tab[-1][1]


def alt_color(alt):
    import colorsys
    if alt is None or alt == 'ground':
        return (0.62, 0.62, 0.62)
    h = _interp(_H, float(alt)); l = _interp(_L, h) / 100
    l = min(0.75, l + 0.08)  # a touch brighter on the dark map
    return colorsys.hls_to_rgb(h / 360, l, 0.88)


_PHOTO = {}  # hex -> (time, image or None, photographer)
_PHOTO_ERR = {}


_FLAGS = {}


def _flag(cc):
    """Country flag PNG from flagcdn (cached for the life of the instance)."""
    cc = (cc or '').lower()
    if not cc or len(cc) != 2:
        return None
    if cc not in _FLAGS:
        try:
            req = urllib.request.Request('https://flagcdn.com/w80/%s.png' % cc, headers={'User-Agent': 'gulf-situation-map/1.0 (+https://t.me/gulfsituation)'})
            _FLAGS[cc] = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=4).read())).convert('RGBA')
        except Exception:
            _FLAGS[cc] = None
    return _FLAGS[cc]


def _roundel(kind, hgt=36):
    """National aircraft markings drawn here (no outside images): US star-and-bar, RAF roundel, IAF Star of David roundel."""
    from PIL import ImageDraw
    k = 4  # draw big, shrink for smooth edges
    if kind == 'us':
        Wd, Hd = int(hgt * 2.1) * k, hgt * k
        im = Image.new('RGBA', (Wd, Hd), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
        cx, cy, r = Wd / 2, Hd / 2, Hd / 2 - 1
        bh = Hd * 0.42; bw = Wd / 2 - 1
        dr.rectangle([1, cy - bh / 2, Wd - 2, cy + bh / 2], fill=(255, 255, 255), outline=(19, 41, 75), width=int(1.6 * k))
        dr.rectangle([1 + 2 * k, cy - bh * 0.14, Wd - 2 - 2 * k, cy + bh * 0.14], fill=(191, 13, 62))
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(19, 41, 75))
        star = []
        for i in range(10):
            rr = r * (0.92 if i % 2 == 0 else 0.36); a = math.radians(-90 + i * 36)
            star.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        dr.polygon(star, fill=(255, 255, 255))
    else:
        Wd = Hd = hgt * k
        im = Image.new('RGBA', (Wd, Hd), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
        c = Wd / 2
        def circ(rr, col): dr.ellipse([c - rr, c - rr, c + rr, c + rr], fill=col)
        if kind == 'gb':
            circ(c - 1, (0, 36, 125)); circ((c - 1) * 0.66, (255, 255, 255)); circ((c - 1) * 0.36, (200, 16, 46))
        else:  # il
            circ(c - 1, (0, 56, 184)); circ((c - 1) * 0.86, (255, 255, 255))
            rr = (c - 1) * 0.74
            for off in (-90, 90):
                dr.polygon([(c + rr * math.cos(math.radians(off + j * 120)), c + rr * math.sin(math.radians(off + j * 120))) for j in range(3)], fill=(0, 56, 184))
            ri = rr * 0.5
            for off in (-90, 90):  # hollow centre like the real marking
                dr.polygon([(c + ri * math.cos(math.radians(off + j * 120)), c + ri * math.sin(math.radians(off + j * 120))) for j in range(3)], fill=(255, 255, 255))
    return im.resize((im.width // k, im.height // k), Image.LANCZOS)


def badge_img(b):
    """Badge next to the aircraft name: state / VIP planes → country flag; US, UK, Israeli military → roundel; other military → flag."""
    cc = str(b.get('cc') or '').lower(); force = str(b.get('force') or '')
    try:
        if not b.get('gov'):
            if cc == 'us' or force.startswith('US') or force == 'USMC':
                return _roundel('us')
            if cc == 'gb' or 'RAF' in force:
                return _roundel('gb')
            if cc == 'il' or 'IAF' in force or 'IDF' in force:
                return _roundel('il')
        f = _flag(cc)
        if f is None:
            return None
        hgt = 26
        f = f.resize((int(f.width * hgt / f.height), hgt), Image.LANCZOS)
        out = Image.new('RGBA', (f.width + 2, hgt + 2), (60, 66, 74, 255)); out.paste(f, (1, 1), f)  # thin frame
        return out
    except Exception:
        return None


_PHOTO_SRC = {}  # hex -> which site the photo came from (diagnostics)


def _fr24_photo(hexcode, ua):
    """Real photo of this airframe as Flightradar24 shows it (JetPhotos), found by hex → registration. FR24's generic
    side-view drawing is never used — only an actual photo of the plane (the owner 25 Oct 2026: if FR or ADS-B has a photo, use it)."""
    get = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers=ua), timeout=2.5))
    reg = None
    for r in (get('https://www.flightradar24.com/v1/search/web/find?query=%s&limit=10' % hexcode.upper()).get('results') or []):
        if r.get('type') == 'aircraft' and str((r.get('detail') or {}).get('hex') or '').lower() == hexcode:
            reg = r.get('id'); break
    if not reg:
        return None, ''
    j = get('https://api.flightradar24.com/common/v1/flight/list.json?query=%s&fetchBy=reg&limit=1' % urllib.parse.quote(reg))
    ims = ((((j.get('result') or {}).get('response') or {}).get('aircraftImages')) or [])
    for im in ims:
        if str(im.get('registration') or '').upper() != reg.upper():
            continue
        imgs = im.get('images') or {}
        for size in ('large', 'medium', 'thumbnails'):
            for p in imgs.get(size) or []:
                src = str(p.get('src') or '')
                if src.startswith('http') and '/sideviews/' not in src:
                    pic = Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(src, headers=ua), timeout=2.5).read())).convert('RGB')
                    return pic, str(p.get('copyright') or 'JetPhotos')
    return None, ''


def plane_photo(hexcode):
    """Photo of this exact aircraft, used on every map (single, group, FR24 email, updates): Planespotters first (what
    ADS-B Exchange shows), then Flightradar24's real photo (JetPhotos). Cached per hex for 24 h; misses retried after 10 min."""
    hexcode = str(hexcode or '').lower().strip()
    if len(hexcode) != 6:
        return None, ''
    c = _PHOTO.get(hexcode)
    if c and time.time() - c[0] < 86400:
        return c[1], c[2]
    dl = getattr(_REQ, 'deadline', 0)
    if dl and time.time() > dl:
        return None, ''   # this request's photo time is used up: map without photo rather than missing the 30 s limit
    if len(_PHOTO) > 400:   # bounded cache: drop the oldest 100 (review 25 Oct 2026)
        for k in sorted(_PHOTO, key=lambda k: _PHOTO[k][0])[:100]:
            _PHOTO.pop(k, None)
    img, who, src_site, err = None, '', '', []
    ua = {'User-Agent': 'gulf-situation-map/1.0 (+https://t.me/gulfsituation)'}
    try:
        j = json.load(urllib.request.urlopen(urllib.request.Request('https://api.planespotters.net/pub/photos/hex/' + hexcode, headers=ua), timeout=2.5))
        ph = (j.get('photos') or [None])[0]
        if ph:
            src = (ph.get('thumbnail_large') or ph.get('thumbnail') or {}).get('src')
            who = ph.get('photographer') or ''
            if src:
                img = Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(src, headers=ua), timeout=2.5).read())).convert('RGB')
                src_site = 'planespotters'
    except Exception as e:
        img = None; err.append('planespotters ' + repr(e)[:150])
    if img is None and not (dl and time.time() > dl):
        try:
            img, who = _fr24_photo(hexcode, ua)
            if img is not None:
                src_site = 'flightradar24'
        except Exception as e:
            img, who = None, ''; err.append('fr24 ' + repr(e)[:150])
    if err:
        _PHOTO_ERR[hexcode] = ' | '.join(err)
    _PHOTO_SRC[hexcode] = src_site
    _PHOTO[hexcode] = (time.time(), img, who) if img is not None else (time.time() - 86400 + 600, None, '')  # retry misses after 10 min
    return img, who


class _ThreadList(threading.local):
    """Place-name collision boxes, one list per request thread (4 gunicorn threads shared one list — review 25 Oct 2026)."""
    def __init__(self):
        self.items = []
    def clear(self):
        self.items = []
    def append(self, x):
        self.items.append(x)
    def __iter__(self):
        return iter(self.items)


_PLACED = _ThreadList()
_REQ = threading.local()   # per-request photo deadline (review 25 Oct 2026)


def _free(ax, x, y, name, left):
    """Skip a place label that would overlap one already drawn (screen pixels)."""
    px, py = ax.transData.transform((x, y))
    w = len(name) * 7 + 10
    box = (px - w if left else px, py - 4, px if left else px + w, py + 16)
    for b in _PLACED:
        if not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]):
            return False
    _PLACED.append(box)
    return True


def orbit_focus(track):
    """The orbit at the end of a track, like ADS-B Exchange / Flightradar24 show it (the owner 25 Oct 2026: tanker orbits were
    invisible): walk back from the plane while the area stays under 300 km; if the plane turned 300°+ in it (loop, racetrack,
    holding — turning one way), return those points (lon, lat) — else None. Steps < 5 km are ignored and turning is signed, so wobble adds nothing."""
    pts = [(float(p[0]), float(p[1])) for p in track]
    if len(pts) < 8:
        return None
    def km(a, b):
        p1, p2 = math.radians(a[1]), math.radians(b[1])
        c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(math.radians(b[0] - a[0]))
        return 6371 * math.acos(max(-1.0, min(1.0, c)))
    inc, turn, prevb, last = [pts[-1]], 0.0, None, pts[-1]
    for i in range(len(pts) - 2, -1, -1):
        a = pts[i]
        if max(km(a, q) for q in (inc[0], inc[len(inc) // 2])) > 300:
            break
        inc.append(a)
        if km(a, last) < 5:   # steps under 5 km: position wobble, not a turn
            continue
        b = math.degrees(math.atan2((last[0] - a[0]) * math.cos(math.radians(a[1])), last[1] - a[1]))
        if prevb is not None:
            d = (b - prevb + 540) % 360 - 180   # signed: left-right wobble cancels, a real orbit keeps turning one way
            turn += d
            if abs(turn) >= 300:   # one full loop found: frame just the loop, not the straight flight before it
                return inc
        prevb, last = b, a
    return None


def frame(track, bbox, aw=W, ah=H, min_w=3.5):
    """Map frame centred on the aircraft (last track point), whole track inside, one zoom level further out
    than a tight fit (the owner 24 Oct 2026). min_w: smallest half-width in degrees (group maps zoom closer)."""
    if bbox:
        lon0, lat0, lon1, lat1 = bbox
        x0, y0 = merc_xy(lon0, lat0); x1, y1 = merc_xy(lon1, lat1)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w = max(x1 - x0, (y1 - y0) * aw / ah)
    else:
        cx, cy = merc_xy(*track[-1])
        pts = [merc_xy(*p) for p in track]
        dx = max(abs(x - cx) for x, y in pts); dy = max(abs(y - cy) for x, y in pts)
        w = max(2 * dx, 2 * dy * aw / ah) * 1.15
    w = max(w, min_w) * 2.0  # one zoom level out
    h = w * ah / aw
    return cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2

def _land_pts(X0, X1, Y0, Y1):
    """Share of a 9x9 grid of points in the frame that lies on land (0 = only sea in the picture)."""
    P = POLYS10 if (X1 - X0) < 25 else POLYS
    xs = [X0 + (X1 - X0) * (i + 0.5) / 9 for i in range(9)]; ys = [Y0 + (Y1 - Y0) * (j + 0.5) / 9 for j in range(9)]
    pts = [(x, y) for x in xs for y in ys]; on = [False] * len(pts)
    for p in P:
        if p[1] < X0 or p[0] > X1 or p[3] < Y0 or p[2] > Y1:
            continue
        hit = matplotlib.path.Path(p[4]).contains_points(pts)
        on = [o or bool(h) for o, h in zip(on, hit)]
        if all(on):
            break
    return sum(on) / len(pts)

def _widen_to_land(X0, X1, Y0, Y1, need=0.08, max_w=60):
    """Open-sea frame: widen around the same centre (x1.4 steps, at most max_w degrees across) until at least `need`
    of the picture is land, so the reader sees where the plane is (Atlantic Cross Watch, 26 Oct 2026)."""
    cx, cy, hw, hh = (X0 + X1) / 2, (Y0 + Y1) / 2, (X1 - X0) / 2, (Y1 - Y0) / 2
    for _ in range(8):
        if _land_pts(cx - hw, cx + hw, cy - hh, cy + hh) >= need or 2 * hw * 1.4 > max_w:
            break
        hw *= 1.4; hh *= 1.4
    return cx - hw, cx + hw, cy - hh, cy + hh

def _group_panel(fig, planes, cat, PW):
    """Side panel for a group alert: one section per plane (callsign + badge, type, role tag, operator, photo, data rows in two
    columns). Section height = panel height / number of planes; the photo shrinks to fit and is left out when there is no room."""
    import textwrap
    top, bot = H - 58, 34
    fig.patches.append(matplotlib.patches.Rectangle((0, bot / H), PW / W, (top - bot) / H, transform=fig.transFigure, color='#11161b', zorder=10))
    fig.patches.append(matplotlib.patches.Rectangle((PW / W - 3 / W, bot / H), 3 / W, (top - bot) / H, transform=fig.transFigure, color='#9dbb6b', zorder=11))
    n = len(planes); sec = (top - bot) / n
    for i, p in enumerate(planes):
        pn = p['panel']; y = top - i * sec - 10; ybot = top - (i + 1) * sec + 6
        if i:
            fig.patches.append(matplotlib.patches.Rectangle((18 / W, (y + 6) / H), (PW - 40) / W, 1 / H, transform=fig.transFigure, color='#9dbb6b', zorder=12))
        fig.text(18 / W, (y - 12) / H, pn.get('callsign', ''), color='#ffffff', fontsize=18, fontweight='bold', va='center', zorder=12)
        b = badge_img(p.get('badge') or {})
        if b is not None:
            b = b.resize((int(b.width * 22 / b.height), 22), Image.LANCZOS)
            fig.figimage(np.asarray(b), xo=int(PW - 16 - b.width), yo=int(y - 12 - b.height / 2), zorder=13)
        y -= 30
        role = pn.get('role') or icons.lookup(p.get('type_code'), p.get('category'))[0] or cat
        fig.text(18 / W, (y - 8) / H, textwrap.shorten(pn.get('type') or p.get('type_code') or '', 30, placeholder='…'), color='#cfd6dd', fontsize=11,
                 va='center', zorder=12)
        if role:
            fig.text((PW - 18) / W, (y - 8) / H, role, color='#111418', fontsize=8, fontweight='bold', ha='right', va='center', zorder=12,
                     bbox=dict(boxstyle='round,pad=0.25', facecolor=icons.CAT_COLOR.get(role, '#9dbb6b'), edgecolor='none'))
        y -= 20
        if pn.get('operator'):
            fig.text(18 / W, (y - 7) / H, textwrap.shorten(pn['operator'], 40, placeholder='…'), color='#9aa5b1', fontsize=9.5, va='center', zorder=12)
            y -= 18
        rows = [(k, v) for k, v in pn.get('rows', []) if v not in (None, '')][:6]
        rows_h = ((len(rows) + 1) // 2) * 24 + 8
        img, who = plane_photo(p.get('hex'))
        room = y - ybot - rows_h - 18
        if img is not None and room >= 50:  # photo of this airframe, shrunk to the room left, credited
            ph = int(min(room, 150)); pw = int(min(PW - 36, ph * img.width / img.height)); ph = int(pw * img.height / img.width)
            fig.figimage(np.asarray(img.resize((pw, ph))), xo=18, yo=int(y - ph - 2), zorder=12)
            fig.text(18 / W, (y - ph - 10) / H, ('Photo: ' + who)[:44], color='#7d8893', fontsize=7.5, va='center', zorder=12)
            y -= ph + 18
        elif img is not None and y - ybot - 12 >= 24:  # (no room for a photo → no photo, never a crash: 8+ planes, review 25 Oct 2026) tight section (3+ planes): small photo on the left, data in one column beside it — every airframe keeps its photo
            pw = 118; ph = int(min(y - ybot - 12, pw * img.height / img.width)); pw = int(ph * img.width / img.height)
            fig.figimage(np.asarray(img.resize((pw, ph))), xo=18, yo=int(y - ph - 2), zorder=12)
            fig.text(18 / W, (y - ph - 9) / H, ('Photo: ' + who)[:22], color='#7d8893', fontsize=6.5, va='center', zorder=12)
            x0, step = 18 + pw + 10, max(15, min(20, (y - ybot - 4) / max(1, len(rows))))
            for k, (key, v) in enumerate(rows):
                yy = y - k * step
                if yy - 8 < ybot:
                    break
                fig.text(x0 / W, (yy - 8) / H, key.upper(), color='#7d8893', fontsize=7.5, va='center', zorder=12)
                fig.text((PW - 18) / W, (yy - 8) / H, str(v), color='#ffffff', fontsize=10, fontweight='bold', ha='right', va='center', zorder=12)
            continue
        y -= 4
        cw = (PW - 40) / 2
        for k, (key, v) in enumerate(rows):
            cx = 18 + (k % 2) * (cw + 4); yy = y - (k // 2) * 24
            fig.text(cx / W, (yy - 8) / H, key.upper(), color='#7d8893', fontsize=7.5, va='center', zorder=12)
            fig.text((cx + cw - 6) / W, (yy - 8) / H, str(v), color='#ffffff', fontsize=10, fontweight='bold', ha='right', va='center', zorder=12)


def _clean_track(raw):
    """Drop broken points (not numbers, 0,0, beyond ±89°), re-join a track crossing ±180°, and drop points more than 3,500 km
    from the plane, so the map can never zoom out to the world (review 25 Oct 2026). Returns [] if nothing usable is left."""
    out = []
    for p in raw or []:
        try:
            lo, la = float(p[0]), float(p[1])
        except Exception:
            continue
        if not (math.isfinite(lo) and math.isfinite(la)) or abs(la) > 89 or (lo == 0 and la == 0):
            continue
        out.append([lo, la] + list(p[2:]))
    if not out:
        return out
    plon, plat = out[-1][0], out[-1][1]
    for q in out:
        while q[0] - plon > 180:
            q[0] -= 360
        while q[0] - plon < -180:
            q[0] += 360
    def km(q):
        a, b = math.radians(plat), math.radians(q[1])
        c = math.sin(a) * math.sin(b) + math.cos(a) * math.cos(b) * math.cos(math.radians(q[0] - plon))
        return 6371 * math.acos(max(-1.0, min(1.0, c)))
    return [q for q in out if km(q) <= 3500]


def draw(d):
    t0 = time.time()
    _REQ.deadline = t0 + 12   # photos may use at most 12 s of the 30 s request
    d = dict(d)
    d['track'] = _clean_track(d.get('track'))
    if not d['track']:
        raise ValueError('no usable track point')
    if d.get('others'):
        d['others'] = [dict(o, track=_clean_track(o.get('track'))) for o in d['others'] if isinstance(o, dict)]
    if d.get('near'):   # nearby planes may carry their own track (bot's position log) and panel (the owner 26 Oct 2026)
        def _leg(t):  # this flight only: start at the last take-off (ground point followed by airborne points)
            t = list(t or [])
            for i in range(len(t) - 1, 0, -1):
                if t[i - 1][2] == 'ground' and t[i][2] != 'ground':
                    return t[i - 1:]
            return t
        d['near'] = [dict(o, track=_clean_track(_leg(o['track']))) if isinstance(o, dict) and o.get('track') else o for o in d['near']]
    try:
        hd = float(d['heading']) if d.get('heading') is not None else None
        d['heading'] = hd if hd is not None and math.isfinite(hd) else None
    except Exception:
        d['heading'] = None
    bb = d.get('bbox')
    if bb:   # a frame box that doesn't contain the plane is ignored (review 25 Oct 2026)
        try:
            lo, la = d['track'][-1][0], d['track'][-1][1]
            if not (len(bb) == 4 and min(bb[0], bb[2]) <= lo <= max(bb[0], bb[2]) and min(bb[1], bb[3]) <= la <= max(bb[1], bb[3])):
                d['bbox'] = None
        except Exception:
            d['bbox'] = None
    raw = d['track']
    track = [(float(p[0]), float(p[1])) for p in raw]
    alts = [(p[2] if len(p) > 2 else None) for p in raw]
    gaps = [bool(len(p) > 3 and p[3]) for p in raw]
    panel = d.get('panel')
    others = [o for o in (d.get('others') or []) if o.get('track')]  # group alert: wingmen flying with the lead (the owner 25 Oct 2026, DEXTER1/2)
    # "Also airborne nearby" planes: small numbered pins matching the alert's numbered list (the owner 26 Oct 2026)
    near = [o for o in (d.get('near') or []) if isinstance(o, dict) and isinstance(o.get('lat'), (int, float))
            and isinstance(o.get('lon'), (int, float)) and abs(o['lat']) < 85][:9]
    PW = 330 if panel else 0  # left info panel width (px), like ADS-B Exchange / Flightradar24
    # group: frame fitted to where the planes are now (close-up, like the DEXTER picture), lead centred; tracks may run off the edge
    fpts = [(float(o['track'][-1][0]), float(o['track'][-1][1])) for o in others] + [track[-1]] if others else track
    orb = None if (others or d.get('bbox')) else orbit_focus(track)
    if orb:   # orbiting: frame the orbit and the plane closely, earlier track runs off the edge (the owner 25 Oct 2026)
        X0, X1, Y0, Y1 = frame(orb, None, W - PW, H, 3.0)   # orbit clearly visible + coast and place names around it
    else:
        X0, X1, Y0, Y1 = frame(fpts, d.get('bbox'), W - PW, H, 3.5)  # short track: ~600 km across, not ~1,200 (the owner 26 Oct 2026, RCH4950 4-min track); groups unchanged  # group: zoomed out more (the owner 25 Oct 2026)
    if not d.get('bbox'):   # over open sea: zoom out (same centre) until coast / a country is in the picture (the owner 26 Oct 2026, RANGR91 off Ireland)
        X0, X1, Y0, Y1 = _widen_to_land(X0, X1, Y0, Y1)
    if near:   # widen just enough (same centre) to fit every numbered plane
        cx, cy = (X0 + X1) / 2, (Y0 + Y1) / 2; hw, hh = (X1 - X0) / 2, (Y1 - Y0) / 2; r = hw / hh
        for o in near:
            x, y = merc_xy(o['lon'], o['lat'])
            hw = max(hw, abs(x - cx) * 1.15, abs(y - cy) * 1.2 * r)
        X0, X1, Y0, Y1 = cx - hw, cx + hw, cy - hw / r, cy + hw / r
    span = X1 - X0
    fig = matplotlib.figure.Figure(figsize=(W / 100, H / 100), dpi=100)   # not registered with pyplot: no leak on errors, safe across threads (review 25 Oct 2026)
    ax = fig.add_axes([PW / W, 0, 1 - PW / W, 1])
    ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1); ax.axis('off')
    ax.set_facecolor(S['sea']); fig.patch.set_facecolor(S['sea'])
    P, L = (POLYS10, LINES10) if span < 25 else (POLYS, LINES)
    vis = [p[4] for p in P if p[1] >= X0 and p[0] <= X1 and p[3] >= Y0 and p[2] <= Y1]
    ax.add_collection(PolyCollection(vis, facecolors=S['land'], edgecolors=S['coast'], linewidths=0.8, zorder=1))
    _detail(ax, X0, X1, Y0, Y1, span)
    segs = [l[4] for l in L if l[1] >= X0 and l[0] <= X1 and l[3] >= Y0 and l[2] <= Y1]
    ax.add_collection(LineCollection(segs, colors=S['border'], linewidths=1.0, linestyles=(0, (4, 3)), zorder=2))
    halo = [pe.withStroke(linewidth=3, foreground=S['halo'])]
    fs = 11 if span < 40 else 9
    dx = span * 0.006
    ends = [merc_xy(*track[0]), merc_xy(*track[-1])]
    _PLACED.clear()
    # Reserve the screen area of the plane, its tag and the track-start label, so place names fill the rest of the map
    # instead of being dropped near the plane (the owner 25 Oct 2026: IRAN09 over Iran showed only Isfahan)
    def _block(x, y, w, h, top):  # w, h in pixels; box hangs below (top=True) or is centred on y
        px, py = ax.transData.transform((x, y))
        _PLACED.append((px - w / 2, py - h if top else py - h / 2, px + w / 2, py if top else py + h / 2))
    _block(ends[1][0], ends[1][1], 80, 80, False)
    if d.get('label'):
        _block(ends[1][0], ends[1][1] - span * 0.05, len(d['label']) * 10 + 30, 36, True)
    if len(track) > 1:
        _block(ends[0][0], ends[0][1], 24, 24, False)
        if d.get('start'):
            _block(ends[0][0], ends[0][1] - span * 0.02, len(d['start']) * 8 + 10, 22, True)
    for o in others:
        ox, oy = merc_xy(float(o['track'][-1][0]), float(o['track'][-1][1]))
        _block(ox, oy, 80, 80, False)
        _block(ox, oy + (-span * 0.04 if oy < ends[1][1] else span * 0.035 + span * 0.02), len(o.get('label') or '') * 10 + 30, 36, True)
    for o in near:
        nx, ny = merc_xy(o['lon'], o['lat'])
        _block(nx, ny, 60, 60, False)
    # the city the plane is over is always named, beside the plane (the owner 26 Oct 2026: IRAN02 over Tehran showed no Tehran)
    under = None
    _lo, _la = track[-1]; _bd = 40.0
    for c in [(p[0], p[1], p[2]) for p in PLACES] + [(c[0], c[1], c[2]) for c in CITIES]:
        _d = math.hypot((c[1] - _lo) * 111.32 * math.cos(math.radians(_la)), (c[2] - _la) * 110.57)
        if _d < _bd:
            _bd, under = _d, c[0]
    if under:
        ux, uy = ends[1][0] + span * 0.022, ends[1][1] + span * 0.018
        ax.text(ux, uy, under, color='#e6ebef', fontsize=12, fontweight='bold', ha='left', va='bottom', zorder=9, path_effects=halo)
        _block(ux + (len(under) * 8) / 2 * (X1 - X0) / ax.bbox.width, uy + span * 0.01, len(under) * 9 + 10, 22, False)
    shown = 0
    for n, lo, la, left in PLACES + [(c[0], c[1], c[2], 0) for c in CITIES]:
        if shown >= 24:
            break
        if n == under:
            continue
        x, y = merc_xy(lo, la)
        if X0 < x < X1 and Y0 + (Y1 - Y0) * 0.06 < y < Y1 - (Y1 - Y0) * 0.1 and _free(ax, x, y, n, left):
            shown += 1
            base = n in BASES  # military bases: green triangle, cities: grey dot (the owner 24 Oct 2026)
            ax.plot(x, y, '^' if base else 'o', ms=6 if base else 3.5, color='#9dbb6b' if base else S['label'], markeredgecolor='#000000',
                    markeredgewidth=0.6 if base else 0, zorder=4)
            ax.text(x - dx if left else x + dx, y + dx, n, color='#c5d9a5' if base else S['label'], fontsize=10.5, ha='right' if left else 'left',
                    zorder=4, path_effects=halo)
    # country names after the place names, only where they don't hit a place name, the plane or a tag (the owner 25 Oct 2026)
    for n, lo, la in COUNTRIES:
        x, y = merc_xy(lo, la)
        if X0 < x < X1 and Y0 < y < Y1:
            px, py = ax.transData.transform((x, y)); w = len(n) * (fs * 0.9) + 6
            box = (px - w / 2, py - fs, px + w / 2, py + fs)
            if any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]) for b in _PLACED):
                continue
            _PLACED.append(box)
            ax.text(x, y, n, color=S['country'], fontsize=fs, fontweight='bold', ha='center', va='center', zorder=3,
                    path_effects=[pe.withStroke(linewidth=2, foreground=S['land'])])
    pts = [merc_xy(*p) for p in track]
    tx, ty = zip(*pts)
    has_alt = any(a is not None for a in alts)
    if len(pts) > 1:
        segs_all = [[pts[i], pts[i + 1]] for i in range(len(pts) - 1)]
        cols_all = [alt_color(alts[i + 1]) if has_alt else S['track'] for i in range(len(pts) - 1)]
        # 4th track value 1 = no position reports for 2+ min before that point (coverage gap / GPS jamming) → thin grey dashes,
        # like ADS-B Exchange (the owner 24 Oct 2026)
        gap = [gaps[i + 1] for i in range(len(pts) - 1)]
        segs2 = [s for s, g in zip(segs_all, gap) if not g]
        cols = [c for c, g in zip(cols_all, gap) if not g]
        gsegs, cur = [], []
        for i, g in enumerate(gap):  # join neighbouring gap pieces so the dash pattern runs through them
            if g:
                cur = cur or [pts[i]]; cur.append(pts[i + 1])
            elif cur:
                gsegs.append(cur); cur = []
        if cur:
            gsegs.append(cur)
        if segs2:
            ax.add_collection(LineCollection(segs2, colors=cols, linewidths=6, alpha=0.10, capstyle='round', zorder=5))  # soft glow (thinner, the owner 24 Oct 2026)
            ax.add_collection(LineCollection(segs2, colors='#000000', linewidths=4, alpha=0.35, capstyle='round', zorder=5))
            ax.add_collection(LineCollection(segs2, colors=cols, linewidths=2.2, capstyle='round', zorder=6))
        if gsegs:
            ax.add_collection(LineCollection(gsegs, colors='#b8c1ca', linewidths=1.8, linestyles=(0, (4, 3)), alpha=0.95, zorder=6))
        cols = cols_all
        ax.plot(tx[0], ty[0], 'o', ms=10, mfc='#ffffff', mec=cols[0], mew=3, zorder=7)
        sx, sy = ax.transData.transform((tx[0], ty[0])); px_, py_ = ax.transData.transform((tx[-1], ty[-1]))
        if d.get('start') and math.hypot(sx - px_, sy - py_) > 150 and X0 + span * 0.12 < tx[0] < X1 - span * 0.12 and Y0 + (Y1 - Y0) * 0.1 < ty[0] < Y1:   # not cut off at the edge (review 25 Oct 2026)  # start text only when it can't sit on the plane / its tag (side panel has Track start)
            ax.text(tx[0], ty[0] - span * 0.02, d['start'], color=S['tag'], fontsize=12, ha='center', va='top', zorder=7, path_effects=halo)
    if d.get('heading') is not None:
        ang = 90 - float(d['heading'])
    elif len(pts) > 1:
        ang = math.degrees(math.atan2(ty[-1] - ty[-2], tx[-1] - tx[-2]))
    else:
        ang = 0
    pc = alt_color(alts[-1]) if has_alt else S['track']
    cat, shape, size = icons.lookup(d.get('type_code'), d.get('category'))
    hd = float(d['heading']) if d.get('heading') is not None else (90 - ang)
    for path, al in icons.markers(shape, hd):  # own silhouette, sized by aircraft, coloured by altitude
        ax.plot(tx[-1], ty[-1], marker=path, markersize=size * 1.4, color=pc, markeredgecolor='#000000', markeredgewidth=0.9,
                alpha=al, linestyle='none', zorder=8)
    lab_up = False
    if d.get('label') and near:   # a nearby plane under the tag would be hidden → tag above the lead instead (the owner 26 Oct 2026)
        lw_ = (len(d['label']) * 10 + 30) / 2 + 12
        def _hit(up):
            lx, ly = ax.transData.transform((tx[-1], ty[-1]))
            for o in near:
                px_, py_ = ax.transData.transform(merc_xy(o['lon'], o['lat']))
                if abs(px_ - lx) < lw_ and ((ly + 18 < py_ < ly + 80) if up else (ly - 80 < py_ < ly - 18)):
                    return True
            return False
        lab_up = _hit(False) and not _hit(True)
    if d.get('label'):  # callsign in a light filled box so it pops (the owner 24 Oct 2026)
        ax.text(tx[-1], ty[-1] + (span * 0.035 if lab_up else -span * 0.05), d['label'], color='#111418', fontsize=14, fontweight='bold', ha='center',
                va='bottom' if lab_up else 'top', zorder=9, bbox=dict(boxstyle='round,pad=0.35', facecolor='#e9edf0', edgecolor='#9dbb6b', linewidth=1.5))
    for o in near:  # numbered nearby plane: its track (thinner), own silhouette (smaller), number badge beside it
        nx, ny = merc_xy(o['lon'], o['lat'])
        ntk = o.get('track') or []
        if len(ntk) > 1:
            npts = [merc_xy(float(p[0]), float(p[1])) for p in ntk]
            nal = [(p[2] if len(p) > 2 else None) for p in ntk]; ngp = [bool(len(p) > 3 and p[3]) for p in ntk]
            sg = [[npts[i], npts[i + 1]] for i in range(len(npts) - 1) if not ngp[i + 1]]
            sc = [alt_color(nal[i + 1]) if isinstance(nal[i + 1], (int, float)) else S['track'] for i in range(len(npts) - 1) if not ngp[i + 1]]
            gs = [[npts[i], npts[i + 1]] for i in range(len(npts) - 1) if ngp[i + 1]]
            if sg:
                ax.add_collection(LineCollection(sg, colors='#000000', linewidths=3, alpha=0.3, capstyle='round', zorder=5))
                ax.add_collection(LineCollection(sg, colors=sc, linewidths=1.6, capstyle='round', zorder=6))
            if gs:
                ax.add_collection(LineCollection(gs, colors='#b8c1ca', linewidths=1.3, linestyles=(0, (4, 3)), alpha=0.9, zorder=6))
        _, nshape, nsize = icons.lookup(o.get('type_code'))
        na = o.get('alt') if isinstance(o.get('alt'), (int, float)) else None
        for path, al in icons.markers(nshape, o.get('heading') if isinstance(o.get('heading'), (int, float)) else 0):
            ax.plot(nx, ny, marker=path, markersize=nsize * 1.1, color=alt_color(na) if na is not None else S['track'],
                    markeredgecolor='#000000', markeredgewidth=0.7, alpha=al, linestyle='none', zorder=8)
        bx, by = nx + span * 0.02, ny + span * 0.02
        if d.get('label'):   # badge on the first corner that is clear of the lead's callsign tag
            lx, ly = ax.transData.transform((tx[-1], ty[-1])); ly += 50 if lab_up else -50
            lw_ = (len(d['label']) * 10 + 30) / 2 + 14
            for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                px_, py_ = ax.transData.transform((nx + sx * span * 0.02, ny + sy * span * 0.02))
                if not (abs(px_ - lx) < lw_ and abs(py_ - ly) < 32):
                    bx, by = nx + sx * span * 0.02, ny + sy * span * 0.02
                    break
        ax.text(bx, by, str(o.get('n') or ''), color='#111418', fontsize=11, fontweight='bold', ha='center',
                va='center', zorder=9, bbox=dict(boxstyle='circle,pad=0.25', facecolor='#e9edf0', edgecolor='#9dbb6b', linewidth=1.2))
    for o in others:  # each wingman: same track style, own silhouette, callsign tag above the plane
        ot = o['track']; op = [merc_xy(float(p[0]), float(p[1])) for p in ot]
        oa = [(p[2] if len(p) > 2 else None) for p in ot]; og = [bool(len(p) > 3 and p[3]) for p in ot]
        if len(op) > 1:
            sg = [[op[i], op[i + 1]] for i in range(len(op) - 1) if not og[i + 1]]
            sc = [alt_color(oa[i + 1]) if has_alt else S['track'] for i in range(len(op) - 1) if not og[i + 1]]
            gs = [[op[i], op[i + 1]] for i in range(len(op) - 1) if og[i + 1]]
            if sg:
                ax.add_collection(LineCollection(sg, colors='#000000', linewidths=4, alpha=0.35, capstyle='round', zorder=5))
                ax.add_collection(LineCollection(sg, colors=sc, linewidths=2.2, capstyle='round', zorder=6))
            if gs:
                ax.add_collection(LineCollection(gs, colors='#b8c1ca', linewidths=1.8, linestyles=(0, (4, 3)), alpha=0.95, zorder=6))
        if o.get('heading') is not None:
            oh = float(o['heading'])
        elif len(op) > 1:
            oh = 90 - math.degrees(math.atan2(op[-1][1] - op[-2][1], op[-1][0] - op[-2][0]))
        else:
            oh = hd
        _, oshape, osize = icons.lookup(o.get('type_code') or d.get('type_code'), d.get('category'))
        for path, al in icons.markers(oshape, oh):
            ax.plot(op[-1][0], op[-1][1], marker=path, markersize=osize * 1.4, color=alt_color(oa[-1]) if has_alt else S['track'],
                    markeredgecolor='#000000', markeredgewidth=0.9, alpha=al, linestyle='none', zorder=8)
        if o.get('label'):  # tag on the side away from the lead (lead's tag sits under the lead)
            below = op[-1][1] < ty[-1]
            ax.text(op[-1][0], op[-1][1] + (-span * 0.04 if below else span * 0.035), o['label'], color='#111418', fontsize=13, fontweight='bold',
                    ha='center', va='top' if below else 'bottom',
                    zorder=9, bbox=dict(boxstyle='round,pad=0.3', facecolor='#e9edf0', edgecolor='#9dbb6b', linewidth=1.2))
    fig.patches.append(matplotlib.patches.Rectangle((0, 1 - 58 / H), 1, 58 / H, transform=fig.transFigure, color=S['bar'], alpha=0.85, zorder=10))
    fig.figimage(LOGO, xo=14, yo=H - 54, zorder=12)
    fig.text(76 / W, 1 - 30 / H, 'gulf situation', color='#7d8893', fontsize=11, va='center', zorder=11)
    if panel:  # category already sits in the side panel → title bar just says PLANE WATCH (the owner 24 Oct 2026)
        fig.text(180 / W, 1 - 30 / H, d.get('title') or 'PLANE WATCH', color='#e6ebef', fontsize=21, fontweight='bold', va='center', zorder=11)
    else:
        fig.text(180 / W, 1 - 30 / H, d.get('title') or cat, color=icons.CAT_COLOR.get(cat, S['bar_text']), fontsize=21, fontweight='bold', va='center', zorder=11)
    sq = str(d.get('squawk') or '').strip()
    EMG = {'7700': 'EMERGENCY', '7600': 'RADIO FAILURE', '7500': 'HIJACK'}
    if sq in EMG:  # emergency squawk, top right, red (the owner 24 Oct 2026)
        fig.text(1 - 20 / W, 1 - 30 / H, 'SQUAWK ' + sq + ' · ' + EMG[sq], color='#ff9a9a', fontsize=11.5, fontweight='semibold', ha='right', va='center',
                 zorder=12, bbox=dict(boxstyle='round,pad=0.45', facecolor='#3a1717', edgecolor='#d65a5a', linewidth=1))
    fig.patches.append(matplotlib.patches.Rectangle((0, 0), 1, 34 / H, transform=fig.transFigure, color=S['bar'], alpha=0.85, zorder=10))
    fig.text(20 / W, 17 / H, d.get('foot') or 'Map: Natural Earth', color=S['bar_text'], fontsize=11, va='center', zorder=11)
    fig.text(1 - 20 / W, 17 / H, time.strftime('%d %b %Y · %H:%M UTC', time.gmtime()), color='#cfd6dd', fontsize=11, ha='right', va='center', zorder=11)
    # distance scale, bottom-left of the map
    clat = math.degrees(2 * math.atan(math.exp(math.radians((Y0 + Y1) / 2))) - math.pi / 2)
    km_per_unit = 111.32 * math.cos(math.radians(clat))
    target = (X1 - X0) * 0.16 * km_per_unit
    nice = min([10, 20, 50, 100, 200, 300, 500, 1000, 2000], key=lambda v: abs(v - target))
    L0 = X0 + (X1 - X0) * 0.03; L1 = L0 + nice / km_per_unit; Ly = Y0 + (Y1 - Y0) * 0.075
    ax.plot([L0, L1], [Ly, Ly], color='#cfd6dd', lw=2, zorder=9, solid_capstyle='butt')
    for xx in (L0, L1):
        ax.plot([xx, xx], [Ly - (Y1 - Y0) * 0.006, Ly + (Y1 - Y0) * 0.006], color='#cfd6dd', lw=2, zorder=9)
    ax.text((L0 + L1) / 2, Ly + (Y1 - Y0) * 0.012, '%d km' % nice, color='#cfd6dd', fontsize=9, ha='center', va='bottom', zorder=9,
            path_effects=[pe.withStroke(linewidth=2, foreground='#000000')])
    if has_alt:  # altitude key, bottom right, like ADS-B Exchange
        steps = [0, 2000, 4000, 6000, 8000, 10000, 20000, 30000, 40000]
        bw, x0l, y0l = 26 / W, 1 - 20 / W - 26 * len(steps) / W, 44 / H
        for k, a in enumerate(steps):
            fig.patches.append(matplotlib.patches.Rectangle((x0l + k * bw, y0l), bw, 12 / H, transform=fig.transFigure, color=alt_color(a), zorder=11))
            if k % 2 == 0:
                fig.text(x0l + k * bw + bw / 2, y0l + 16 / H, ('%dk' % (a // 1000)) if a else '0', color='#ffffff', fontsize=8, ha='center', zorder=11,
                         path_effects=[pe.withStroke(linewidth=2, foreground='#000000')])
        fig.text(x0l - 6 / W, y0l + 6 / H, 'ft', color='#ffffff', fontsize=8, ha='right', va='center', zorder=11)
    near_p = [dict(o, panel=dict(o['panel'], callsign='%s · %s' % (o.get('n'), o['panel'].get('callsign', '')))) for o in near if isinstance(o.get('panel'), dict)]
    if panel and (others or near_p):  # group or nearby planes: one section per plane, stacked, sized to fit — same info as a single alert (the owner 25/26 Oct 2026)
        _group_panel(fig, [dict(o, panel=dict(o.get('panel') or {})) for o in [dict(d, panel=panel)] + others] + near_p, cat, PW)
    elif panel:
        top, bot = H - 58, 34
        fig.patches.append(matplotlib.patches.Rectangle((0, bot / H), PW / W, (top - bot) / H, transform=fig.transFigure, color='#11161b', zorder=10))
        fig.patches.append(matplotlib.patches.Rectangle((PW / W - 3 / W, bot / H), 3 / W, (top - bot) / H, transform=fig.transFigure, color='#9dbb6b', zorder=11))
        y = top - 18
        if not panel.get('role'):
            panel['role'] = cat   # one role table (icons.py) for title and panel — 24 Oct 2026, P-8 was labelled ISR
        if panel.get('role'):
            fig.text(18 / W, (y - 10) / H, panel['role'], color='#111418', fontsize=10, fontweight='bold', va='center', zorder=12,
                     bbox=dict(boxstyle='round,pad=0.3', facecolor=icons.CAT_COLOR.get(panel['role'], '#9dbb6b'), edgecolor='none'))
            y -= 36
        fig.text(18 / W, (y - 14) / H, panel.get('callsign', ''), color='#ffffff', fontsize=24, fontweight='bold', va='center', zorder=12)
        bimg = badge_img(d.get('badge') or {})
        if bimg is not None:  # roundel (US / RAF / IAF military) or country flag (state planes), right side of the name line
            fig.figimage(np.asarray(bimg), xo=int(PW - 16 - bimg.width), yo=int(y - 14 - bimg.height / 2), zorder=13)
        y -= 42
        if panel.get('type'):
            import textwrap
            for ln in textwrap.wrap(panel['type'], 30)[:2]:
                fig.text(18 / W, (y - 8) / H, ln, color='#cfd6dd', fontsize=12, va='center', zorder=12)
                y -= 22
            y -= 4
        if panel.get('operator'):
            fig.text(18 / W, (y - 8) / H, panel['operator'], color='#9aa5b1', fontsize=11, va='center', zorder=12)
            y -= 30
        img, who = plane_photo(d.get('hex'))
        if img is not None:  # photo of this aircraft, photographer credited underneath
            pw = PW - 36; ph = int(pw * img.height / img.width)
            ph = min(ph, 190); im = img.resize((pw, ph))
            fig.figimage(np.asarray(im), xo=18, yo=int(y - ph - 4), zorder=12)
            y -= ph + 10
            fig.text(18 / W, (y - 6) / H, ('Photo: ' + who)[:44], color='#7d8893', fontsize=8.5, va='center', zorder=12)
            y -= 20
        fig.patches.append(matplotlib.patches.Rectangle((18 / W, y / H), (PW - 40) / W, 1 / H, transform=fig.transFigure, color='#3a434d', zorder=12))
        y -= 16
        for k, v in panel.get('rows', []):
            if v in (None, ''):
                continue
            fig.text(18 / W, (y - 8) / H, k.upper(), color='#7d8893', fontsize=9, va='center', zorder=12)
            fig.text((PW - 22) / W, (y - 8) / H, str(v), color='#ffffff', fontsize=12, fontweight='bold', ha='right', va='center', zorder=12)
            y -= 30
            if y < bot + 20:
                break
    buf = io.BytesIO()
    fig.savefig(buf, format='jpg', dpi=100, facecolor=S['sea'], pil_kwargs={'quality': 88})
    return buf.getvalue(), time.time() - t0


app = Flask(__name__)


@app.get('/health')
def health():
    return 'ok'


@app.get('/photo/<hexcode>')
def photo_check(hexcode):  # diagnostics: what happens when we ask for this aircraft's photo
    key = os.environ.get('MAP_KEY', '')
    if key and request.args.get('key') != key:   # was open to anyone (review 25 Oct 2026)
        return Response('bad key', status=403)
    if not re.fullmatch(r'[0-9a-fA-F]{6}', hexcode or ''):
        return Response('bad hex', status=400)
    _PHOTO.pop(hexcode.lower(), None); _PHOTO_ERR.pop(hexcode.lower(), None)
    _REQ.deadline = time.time() + 12   # fresh deadline: a stale one from an earlier /draw on this thread made it say "no photo" instantly (26 Oct 2026)
    t = time.time(); img, who = plane_photo(hexcode)
    return {'hex': hexcode, 'ok': img is not None, 'size': img.size if img is not None else None, 'photographer': who,
            'source': _PHOTO_SRC.get(hexcode.lower()), 'error': _PHOTO_ERR.get(hexcode.lower()), 'seconds': round(time.time() - t, 2)}


@app.post('/draw')
def draw_route():
    d = request.get_json(force=True, silent=True) or {}
    key = os.environ.get('MAP_KEY', '')
    if key and d.get('key') != key:
        return Response('bad key', status=403)
    if not d.get('track'):
        return Response('no track', status=400)
    try:
        img, secs = draw(d)
    except (ValueError, TypeError, KeyError, IndexError) as e:   # bad input → 400, not a crash (review 25 Oct 2026)
        return Response('bad input: %s' % str(e)[:120], status=400)
    return Response(img, mimetype='image/jpeg', headers={'X-Draw-Seconds': '%.2f' % secs})



def draw_holding(d):
    """Airport watch picture: big map around the airport with EVERY nearby aircraft (airliners, cargo, private, military,
    trainers) — its recent track, a number badge, and a list on the right with callsign, type and altitude. Holding planes
    are highlighted (orange) with close-ups; planes circling but not holding (light aircraft, under 2,500 ft) get a blue badge (the owner 24 + 26 Oct 2026)."""
    t0 = time.time()
    apt = d['airport']; alat, alon = float(apt['lat']), float(apt['lon'])
    flights = []
    for f in d.get('flights', []) or []:
        if not isinstance(f, dict):
            continue
        tr = [p for p in (f.get('track') or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
        if not tr and isinstance(f.get('lat'), (int, float)) and isinstance(f.get('lon'), (int, float)):
            tr = [[f['lon'], f['lat'], f.get('alt')]]   # no track: the plane is still drawn where it is
        if tr:
            flights.append(dict(f, track=tr))
    hold = [f for f in flights if f.get('holding')]
    low = [f for f in flights if f.get('low') and not f.get('holding')]
    if any(isinstance(f.get('n'), int) for f in flights):
        flights.sort(key=lambda f: f.get('n') if isinstance(f.get('n'), int) else 999)
    else:   # old bot: holding first (most turned), then the rest
        flights.sort(key=lambda f: (0 if f.get('holding') else 1, -float(f.get('turned') or 0)))
    for k, f in enumerate(flights):
        if not isinstance(f.get('n'), int):
            f['n'] = k + 1
    hold.sort(key=lambda f: f['n'])
    MW = 760  # main map width (px)
    fig = matplotlib.figure.Figure(figsize=(W / 100, H / 100), dpi=100)   # not registered with pyplot: no leak on errors, safe across threads (review 25 Oct 2026)
    fig.patch.set_facecolor(S['sea'])
    top, bot = H - 58, 34
    ax = fig.add_axes([0, bot / H, MW / W, (top - bot) / H])
    cx, cy = merc_xy(alon, alat)
    nm = float(d.get('radius_nm') or 60)
    half_h = nm / 60.0 / math.cos(math.radians(alat)) * 1.0  # nm → degrees of mercator y (approx)
    half_w = half_h * MW / (top - bot)
    X0, X1, Y0, Y1 = cx - half_w, cx + half_w, cy - half_h, cy + half_h
    span = X1 - X0
    _base_map(ax, X0, X1, Y0, Y1, span, avoid=(cx, cy))
    # range rings
    for r in (20, 40):
        rr = r / 60.0 / math.cos(math.radians(alat))
        ax.add_patch(matplotlib.patches.Circle((cx, cy), rr, fill=False, ec='#56677a', lw=0.8, ls=(0, (3, 3)), zorder=3))
        ax.text(cx + rr * 0.71, cy + rr * 0.71, '%d nm' % r, color='#7d8893', fontsize=8, zorder=3)
    ax.plot(cx, cy, marker='^', ms=11, color='#9dbb6b', mec='#000', zorder=6)
    ax.text(cx, cy - span * 0.03, apt.get('name', ''), color='#c5d9a5', fontsize=11, fontweight='bold', ha='center', va='top', zorder=6,
            path_effects=[pe.withStroke(linewidth=3, foreground='#000')])

    def last_alt(f):
        tr = f.get('track') or []
        a = tr[-1][2] if tr and len(tr[-1]) > 2 else None
        return a if isinstance(a, (int, float)) else (f.get('alt') if isinstance(f.get('alt'), (int, float)) else None)

    def trackline(a, f, lw, alpha, z):
        tr = f.get('track') or []
        if len(tr) < 2:
            return
        pts = [merc_xy(p[0], p[1]) for p in tr]
        segs = [[pts[i], pts[i + 1]] for i in range(len(pts) - 1)]
        cols = [alt_color(tr[i + 1][2] if len(tr[i + 1]) > 2 else None) for i in range(len(pts) - 1)]
        a.add_collection(LineCollection(segs, colors='#000000', linewidths=lw + 1.6, alpha=0.35 * alpha, capstyle='round', zorder=z))
        a.add_collection(LineCollection(segs, colors=cols, linewidths=lw, alpha=alpha, capstyle='round', zorder=z))

    def plane(a, f, size, alpha, z):
        tr = f.get('track') or []
        if not tr:
            return
        x, y = merc_xy(tr[-1][0], tr[-1][1])
        cat, shape, sz = icons.lookup(f.get('type_code'))
        for path, al in icons.markers(shape, f.get('heading') or 0):
            a.plot(x, y, marker=path, markersize=size, color=alt_color(last_alt(f)), markeredgecolor='#000',
                   markeredgewidth=0.6, alpha=al * alpha, linestyle='none', zorder=z)
        return x, y

    def badge_col(f):
        return '#e8a33d' if f.get('holding') else ('#6fa8dc' if f.get('low') else '#cfd6dd')

    def alt_txt(a):
        if not isinstance(a, (int, float)):
            return ''
        return ('FL%d' % round(a / 100)) if a >= 18000 else ('{:,} ft'.format(int(round(a / 100.0) * 100)))

    for f in flights:   # every aircraft: track, plane, number (holding ones on top, thicker)
        hl = bool(f.get('holding'))
        trackline(ax, f, 3.0 if hl else 1.7, 1.0 if hl else 0.8, 7 if hl else 5)
    placed = []
    for f in sorted(flights, key=lambda f: 1 if f.get('holding') else 0):
        hl = bool(f.get('holding'))
        xy = plane(ax, f, 22 if hl else 15, 1.0, 8 if hl else 6)
        if not xy:
            continue
        d0 = span * 0.02   # badge beside its own plane; try the 8 directions around it so badges never sit on each other
        opts = [(1, 1), (1, -1), (-1, 1), (-1, -1), (1.4, 0), (-1.4, 0), (0, 1.4), (0, -1.4), (2, 2), (-2, 2), (2, -2), (-2, -2)]
        bx, by = xy[0] + d0, xy[1] + d0
        for ox, oy in opts:
            tx, ty = xy[0] + ox * d0, xy[1] + oy * d0
            if all(abs(tx - px) > span * 0.028 or abs(ty - py) > span * 0.028 for px, py in placed):
                bx, by = tx, ty
                break
        placed.append((bx, by))
        ax.plot([xy[0], bx], [xy[1], by], color='#cfd6dd', lw=0.7, alpha=0.75, zorder=8)   # thin leader line: which plane the number belongs to
        ax.text(bx, by, str(f['n']), color='#111418', fontsize=9 if hl else 7.5, fontweight='bold', ha='center', va='center', zorder=9,
                bbox=dict(boxstyle='circle,pad=0.22', facecolor=badge_col(f), edgecolor='#000'))
    # right side: close-ups of up to 4 holding loops, then the list of every aircraft
    gx0, RW = MW + 12, W - MW - 24
    y_list = top - 10
    if hold:
        gw, gh = RW / 2, 150
        for k, f in enumerate(hold[:4]):
            col, row = k % 2, k // 2
            x0 = gx0 + col * gw; y0 = top - 8 - (row + 1) * gh
            sub = fig.add_axes([(x0 + 4) / W, (y0 + 4) / H, (gw - 8) / W, (gh - 30) / H])
            tr = f.get('track') or []
            pts = [merc_xy(p[0], p[1]) for p in tr] or [(cx, cy)]
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            mx, my = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            aw, ah = gw - 8, gh - 30
            w = max(max(xs) - min(xs), (max(ys) - min(ys)) * aw / ah, 0.25) * 1.3; h = w * ah / aw
            _base_map(sub, mx - w / 2, mx + w / 2, my - h / 2, my + h / 2, w, labels=False)
            trackline(sub, f, 2.4, 1.0, 7); plane(sub, f, 16, 1.0, 8)
            sub.add_patch(matplotlib.patches.Rectangle((0, 0), 1, 1, transform=sub.transAxes, fill=False, ec='#3a434d', lw=1, zorder=20))
            fig.text((x0 + 6) / W, (y0 + gh - 14) / H, '%d  %s' % (f['n'], f.get('cs') or f.get('hex', '').upper()), color='#ffffff',
                     fontsize=10.5, fontweight='bold', va='center', zorder=21)
            info = ' · '.join(filter(None, [alt_txt(last_alt(f)), ('%d°' % round(float(f['turned']))) if f.get('turned') else '']))
            fig.text((x0 + gw - 10) / W, (y0 + gh - 14) / H, info, color='#9aa5b1', fontsize=8.5, ha='right', va='center', zorder=21)
        y_list = top - 8 - ((min(len(hold), 4) + 1) // 2) * gh - 8
    head = ('%d holding' % len(hold)) if hold else 'No holding seen'
    fig.text(gx0 / W, (y_list - 8) / H, head + ' · every aircraft within %d nm' % int(nm), color='#e8a33d' if hold else '#cfd6dd',
             fontsize=10.5, fontweight='bold', va='center', zorder=21)
    rh = 17.5
    rows = max(1, int((y_list - 22 - bot - 8) // rh))
    show = flights if len(flights) <= rows else flights[:rows - 1]
    for k, f in enumerate(show):
        yy = (y_list - 28 - k * rh) / H
        fig.text((gx0 + 9) / W, yy, str(f['n']), color='#111418', fontsize=7.5, fontweight='bold', ha='center', va='center', zorder=21,
                 bbox=dict(boxstyle='circle,pad=0.2', facecolor=badge_col(f), edgecolor='none'))
        fig.text((gx0 + 24) / W, yy, str(f.get('cs') or f.get('hex', '').upper())[:10], color='#ffffff', fontsize=9.5, fontweight='bold', va='center', zorder=21)
        fig.text((gx0 + 120) / W, yy, str(f.get('type_label') or f.get('type_code') or '')[:12], color='#9aa5b1', fontsize=9, va='center', zorder=21)
        fig.text((gx0 + 250) / W, yy, alt_txt(last_alt(f)), color='#cfd6dd', fontsize=9, ha='right', va='center', zorder=21)
        st = ('holding · %.1f laps' % (float(f.get('turned') or 0) / 360)) if f.get('holding') else ('circling' if f.get('low') else '')
        fig.text((gx0 + RW) / W, yy, st, color=badge_col(f) if st else '#7d8893', fontsize=8.5, ha='right', va='center', zorder=21)
    if len(show) < len(flights):
        fig.text((gx0 + 24) / W, (y_list - 28 - len(show) * rh) / H, '+%d more' % (len(flights) - len(show)), color='#7d8893', fontsize=9, va='center', zorder=21)
    if not flights:
        fig.text((gx0 + RW / 2) / W, 0.45, 'No aircraft seen near the airport', color='#7d8893', fontsize=13, ha='center', va='center')
    # bars
    fig.patches.append(matplotlib.patches.Rectangle((0, top / H), 1, 58 / H, transform=fig.transFigure, color=S['bar'], alpha=0.9, zorder=10))
    fig.figimage(LOGO, xo=14, yo=H - 54, zorder=12)
    fig.text(76 / W, 1 - 30 / H, 'gulf situation', color='#7d8893', fontsize=11, va='center', zorder=11)
    fig.text(180 / W, 1 - 30 / H, 'AIRPORT WATCH · ' + (apt.get('name') or apt.get('icao', '')), color='#e8a33d', fontsize=21, fontweight='bold', va='center', zorder=11)
    fig.text(1 - 20 / W, 1 - 30 / H, '%d holding · %d aircraft' % (len(hold), len(flights)) + (' · %d circling' % len(low) if low else ''), color='#cfd6dd',
             fontsize=12, ha='right', va='center', zorder=11)
    fig.patches.append(matplotlib.patches.Rectangle((0, 0), 1, bot / H, transform=fig.transFigure, color=S['bar'], alpha=0.9, zorder=10))
    fig.text(20 / W, 17 / H, d.get('foot') or 'Tracks: ADS-B Exchange / Flightradar24 feed · map: Natural Earth', color=S['bar_text'], fontsize=10.5, va='center', zorder=11)
    fig.text(1 - 20 / W, 17 / H, time.strftime('%d %b %Y · %H:%M UTC', time.gmtime()), color='#cfd6dd', fontsize=10.5, ha='right', va='center', zorder=11)
    buf = io.BytesIO()
    fig.savefig(buf, format='jpg', dpi=100, facecolor=S['sea'], pil_kwargs={'quality': 88})
    return buf.getvalue(), time.time() - t0


def _base_map(ax, X0, X1, Y0, Y1, span, labels=True, avoid=None):
    ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1); ax.axis('off'); ax.set_facecolor(S['sea'])
    P, L = (POLYS10, LINES10) if span < 25 else (POLYS, LINES)
    vis = [p[4] for p in P if p[1] >= X0 and p[0] <= X1 and p[3] >= Y0 and p[2] <= Y1]
    ax.add_collection(PolyCollection(vis, facecolors=S['land'], edgecolors=S['coast'], linewidths=0.8, zorder=1))
    _detail(ax, X0, X1, Y0, Y1, span)   # same detail as the alert maps (the owner 25 Oct 2026)
    segs = [l[4] for l in L if l[1] >= X0 and l[0] <= X1 and l[3] >= Y0 and l[2] <= Y1]
    ax.add_collection(LineCollection(segs, colors=S['border'], linewidths=0.9, linestyles=(0, (4, 3)), zorder=2))
    if labels:
        _PLACED.clear(); shown = 0
        for n, lo, la, left in PLACES + [(c[0], c[1], c[2], 0) for c in CITIES]:   # + regional cities, like the alert maps
            if shown >= 16:
                break
            x, y = merc_xy(lo, la)
            if avoid and abs(x - avoid[0]) < span * 0.06 and abs(y - avoid[1]) < span * 0.04:
                continue   # airport watch: no city label on top of the airport's own name
            if X0 < x < X1 and Y0 < y < Y1 and _free(ax, x, y, n, left):
                shown += 1
                ax.plot(x, y, '^' if n in BASES else 'o', ms=5 if n in BASES else 3, color='#9dbb6b' if n in BASES else S['label'], zorder=4)
                ax.text(x + span * 0.008, y + span * 0.006, n, color='#c5d9a5' if n in BASES else S['label'], fontsize=9.5, zorder=4,
                        path_effects=[pe.withStroke(linewidth=3, foreground='#000')])


@app.post('/holding')
def holding_route():
    d = request.get_json(force=True, silent=True) or {}
    key = os.environ.get('MAP_KEY', '')
    if key and d.get('key') != key:
        return Response('bad key', status=403)
    if not d.get('airport'):
        return Response('no airport', status=400)
    img, secs = draw_holding(d)
    return Response(img, mimetype='image/jpeg', headers={'X-Draw-Seconds': '%.2f' % secs})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
