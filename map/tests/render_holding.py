"""Airport watch map test: real Dubai traffic of 26 Oct 2026 (12 aircraft, full-resolution ADS-B Exchange tracks, A6FAB C172 circling) → tests/out/holding_<tag>.jpg.
Run before/after any change to draw_holding (the owner 26 Oct 2026: every aircraft type, tracks, callsign, altitude, holding)."""
import importlib.util, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); MAP = os.path.dirname(HERE); sys.path.insert(0, MAP)
spec = importlib.util.spec_from_file_location('app', os.path.join(MAP, 'app.py')); app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)
app.time.strftime = lambda *a: 'TEST'
fl = []
for rec in open(os.path.join(HERE, 'holding_dxb_26oct.txt')).read().strip().split('~'):
    n, cs, t, alt, h, low, turn, trk, lat, lon, pts = rec.split('|')
    tr = [[float(x), float(y), None if a == 'g' else int(a) * 100] for x, y, a in (p.split(',') for p in pts.split(';'))]
    light = t in ('C172',)
    fl.append(dict(n=int(n), hex=cs, cs=cs, type_code=t, track=tr, lat=float(lat), lon=float(lon), alt=int(alt),
                   holding=h == '1' and not light, low=low == '1' or (light and h == '1'), turned=int(turn), heading=int(trk)))
d = {'airport': {'name': 'Dubai Intl (DXB)', 'icao': 'OMDB', 'lat': 25.253, 'lon': 55.364}, 'radius_nm': 60, 'flights': fl}
tag = sys.argv[1] if len(sys.argv) > 1 else 'now'
os.makedirs(os.path.join(HERE, 'out'), exist_ok=True)
img, _ = app.draw_holding(d); fn = os.path.join(HERE, 'out', 'holding_%s.jpg' % tag); open(fn, 'wb').write(img); print(fn)
