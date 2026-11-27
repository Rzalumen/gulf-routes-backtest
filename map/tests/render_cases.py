"""Draw every case in tests/cases.jsonl with the current app.py → tests/out/<tag>/<case>.jpg + a contact sheet.
Run before and after any map change (python3 tests/render_cases.py before / after) and compare the sheets:
only the cases the change is meant to affect may change (the owner 25 Oct 2026)."""
import importlib.util, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); MAP = os.path.dirname(HERE)
sys.path.insert(0, MAP)
spec = importlib.util.spec_from_file_location('app', os.path.join(MAP, 'app.py')); app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)
app.plane_photo = lambda h: (None, '')
app.time.strftime = lambda *a: 'TEST'
def tk(s):
    out = []
    for p in s.split(';'):
        a = p.split(','); alt = a[2]
        alt = 'ground' if alt == 'ground' else (None if alt in ('', 'null', 'undefined') else float(alt))
        out.append([float(a[0]), float(a[1]), alt, int(a[3])])
    return out
tag = sys.argv[1] if len(sys.argv) > 1 else 'now'
od = os.path.join(HERE, 'out', tag); os.makedirs(od, exist_ok=True)
files = []
for l in open(os.environ.get('CASES', os.path.join(HERE, 'cases.jsonl'))):
    d = json.loads(l)
    b = {'track': tk(d['track']), 'label': d['label'], 'start': d['start'], 'heading': d['heading'], 'type_code': d['type_code'],
         'category': d['category'], 'panel': {'callsign': d['c'], 'rows': []}}
    if d['others']:
        b['others'] = [{'track': tk(o['track']), 'label': o['label'], 'type_code': o['type_code'], 'panel': {'callsign': o['label']}} for o in d['others']]
    if d.get('near'):
        b['near'] = [dict(n, track=tk(n['track'])) if n.get('track') else n for n in d['near']]
    img, _ = app.draw(b)
    fn = os.path.join(od, d['c'].split()[0] + '.jpg'); open(fn, 'wb').write(img); files.append((d['c'], fn))
from PIL import Image, ImageDraw
W, H, C = 480, 270, 4
sheet = Image.new('RGB', (W * C, H * ((len(files) + C - 1) // C)), 'black'); dr = ImageDraw.Draw(sheet)
for i, (name, fn) in enumerate(files):
    x, y = (i % C) * W, (i // C) * H
    sheet.paste(Image.open(fn).resize((W, H)), (x, y)); dr.rectangle([x, y, x + 200, y + 18], fill='yellow'); dr.text((x + 4, y + 3), name[:32], fill='black')
sheet.save(os.path.join(HERE, 'out', 'sheet_%s.jpg' % tag), quality=85)
print(len(files), 'cases drawn →', os.path.join(HERE, 'out', 'sheet_%s.jpg' % tag))
