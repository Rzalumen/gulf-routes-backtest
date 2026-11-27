"""Own aircraft silhouettes (nose up, unit box -1..1) + type → category/icon/size table."""
import math
from matplotlib.path import Path

def _mir(half):  # half outline on +x side (nose→tail), mirrored to a closed polygon
    return half + [(-x, y) for x, y in reversed(half)]

def _poly(pts):
    return [(Path.MOVETO, pts[0])] + [(Path.LINETO, p) for p in pts[1:]] + [(Path.CLOSEPOLY, pts[0])]

def _rect(cx, cy, w, h):
    return _poly([(cx - w, cy - h), (cx + w, cy - h), (cx + w, cy + h), (cx - w, cy + h)])

def _circle(cx, cy, r, n=24):
    return _poly([(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)])

def _jet(span, sweep, engines, tail=0.38):
    body = _mir([(0, 1), (0.07, 0.85), (0.08, 0.3), (span, -0.05 - sweep), (span, -0.17 - sweep), (0.08, -0.08),
                 (0.07, -0.7), (tail, -0.9), (tail, -0.98), (0.04, -0.92), (0, -1)])
    parts = [(_poly(body), 1)]
    for ex in engines:  # pods hang under the wing (separate filled parts, no holes)
        ey = 0.3 + (-0.05 - sweep - 0.3) * (ex - 0.08) / (span - 0.08) - 0.02
        parts.append((_rect(ex, ey, 0.05, 0.12), 1)); parts.append((_rect(-ex, ey, 0.05, 0.12), 1))
    return parts

SHAPES = {
    'heavy4': _jet(0.95, 0.35, [0.38, 0.66]),
    'twin': _jet(0.9, 0.3, [0.36]),
    'turboprop': [(_poly(_mir([(0, 1), (0.08, 0.8), (0.08, 0.25), (0.95, 0.2), (0.95, 0.02), (0.08, 0.0), (0.07, -0.7),
                             (0.38, -0.82), (0.38, -0.95), (0.04, -0.9), (0, -1)])), 1)] +
                 [(_rect(sx * x, 0.3, 0.05, 0.13), 1) for x in (0.32, 0.62) for sx in (1, -1)],
    'bomber': [(_poly(_mir([(0, 1), (0.06, 0.75), (0.1, 0.35), (0.3, 0.1), (0.8, -0.55), (0.8, -0.65), (0.14, -0.3), (0.12, -0.72),
                          (0.45, -0.88), (0.45, -0.98), (0, -0.95)])), 1)],
    'flyingwing': [(_poly(_mir([(0, 0.75), (1, -0.25), (1, -0.38), (0.72, -0.5), (0.5, -0.32), (0.3, -0.5), (0.12, -0.32), (0, -0.45)])), 1)],
    'fighter': [(_poly(_mir([(0, 1), (0.1, 0.55), (0.14, 0.1), (0.78, -0.35), (0.78, -0.52), (0.18, -0.45), (0.38, -0.8),
                           (0.38, -0.98), (0.1, -0.92), (0, -1)])), 1)],
    'drone': [(_poly(_mir([(0, 0.85), (0.06, 0.6), (0.06, 0.2), (1, 0.12), (1, 0.03), (0.06, 0.0), (0.05, -0.65),
                         (0.3, -0.92), (0.3, -1), (0, -0.85)])), 1)],
    'helicopter': [(_circle(0, 0.15, 0.85, 32), 0.3), (_poly(_mir([(0, 0.55), (0.2, 0.4), (0.2, -0.1), (0.06, -0.3), (0.05, -0.9),
                                                            (0.22, -0.95), (0.22, -1), (0, -1)])), 1)],
    'tiltrotor': [(_circle(0.75, 0.15, 0.32), 0.35), (_circle(-0.75, 0.15, 0.32), 0.35), (_poly(_mir([(0, 1), (0.1, 0.75), (0.1, 0.25), (0.62, 0.22), (0.62, 0.05), (0.1, 0.02), (0.08, -0.7),
                             (0.4, -0.85), (0.4, -0.97), (0, -0.95)])), 1)],
}

def markers(shape, heading_deg):
    """[(Path, alpha)] parts of a silhouette rotated to heading (0 = north, clockwise). Paths are scaled so the
    whole aircraft keeps one size (each part shares the same 2x2 box via invisible corner points)."""
    a = math.radians(-(heading_deg or 0)); out = []
    for segs, alpha in SHAPES[shape]:
        codes, verts = [], []
        for c, (x, y) in segs:
            codes.append(c); verts.append((x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)))
        for cx, cy in ((-1.5, -1.5), (1.5, 1.5)):  # fixed box so parts line up
            codes += [Path.MOVETO]; verts += [(cx, cy)]
        out.append((Path(verts, codes), alpha))
    return out

# ICAO type → (category, shape, size in points). Size follows real wingspan roughly.
T = {}
def _add(cat, shape, size, *codes):
    for c in codes: T[c] = (cat, shape, size)
_add('TANKER', 'heavy4', 36, 'K35R', 'K35E', 'KC10', 'C135')
_add('UNIDENTIFIED', 'heavy4', 36, 'B703')   # Boeing 707 (IAF tanker etc.): four-engine shape only, the role label comes from the bot (the owner 26 Oct 2026)
_add('TANKER', 'twin', 34, 'K46', 'KC46', 'B762', 'A332', 'A339', 'MRTT', 'KC30', 'KC2')
_add('AIRLIFT', 'heavy4', 42, 'C5M', 'C5')
_add('AIRLIFT', 'heavy4', 36, 'C17')
_add('AIRLIFT', 'turboprop', 30, 'C130', 'C30J', 'A400', 'C2')
_add('AIRLIFT', 'turboprop', 24, 'C27J', 'C295', 'CN35')
_add('ISR / RECON', 'heavy4', 34, 'R135')
_add('ISR / RECON', 'drone', 24, 'U2')
_add('ISR / RECON', 'turboprop', 24, 'EP3')
_add('ISR / RECON', 'turboprop', 16, 'RC12')
_add('ISR / RECON', 'heavy4', 36, 'E8')
_add('ELECTRONIC WARFARE', 'twin', 22, 'EA37')
_add('AIRBORNE EARLY WARNING', 'heavy4', 36, 'E3TF', 'E3CF', 'E3')
_add('AIRBORNE EARLY WARNING', 'twin', 30, 'E7', 'E737')
_add('AIRBORNE EARLY WARNING', 'turboprop', 22, 'E2', 'E2D')
_add('COMMAND & COMMS', 'heavy4', 38, 'B744', 'E4')
_add('COMMAND & COMMS', 'heavy4', 32, 'E6')
_add('COMMAND & COMMS', 'twin', 22, 'E11A', 'BD70', 'GLEX')
_add('MARITIME PATROL', 'twin', 30, 'P8')
_add('MARITIME PATROL', 'drone', 30, 'Q4')
_add('DRONE', 'drone', 30, 'RQ4', 'GLHK')
_add('DRONE', 'drone', 18, 'MQ9', 'Q9', 'PRDT')
_add('DRONE', 'drone', 18, 'HRON')   # IAI Heron: drone shape, as ADS-B Exchange draws it (the owner 26 Oct 2026, was falling back to the jet shape)
_add('BOMBER', 'heavy4', 40, 'B52')
_add('BOMBER', 'bomber', 32, 'B1')
_add('BOMBER', 'flyingwing', 36, 'B2')
_add('FIGHTER', 'fighter', 20, 'F15', 'F15E', 'F16', 'F22', 'F35', 'FA18', 'F18S', 'EA18', 'EUFI', 'TOR')
_add('SPECIAL OPS', 'turboprop', 30, 'MC130', 'AC130')
_add('SPECIAL OPS', 'tiltrotor', 22, 'V22')
_add('VIP / GOVERNMENT', 'twin', 30, 'C32', 'B752', 'C40', 'B737', 'B738')
_add('VIP / GOVERNMENT', 'heavy4', 38, 'VC25')
_add('VIP / GOVERNMENT', 'twin', 20, 'C37', 'GLF5', 'GLF6', 'C21', 'LJ35')
_add('ARMY / UTILITY', 'turboprop', 16, 'BE20', 'B350', 'BE9L', 'C12')
_add('ARMY / UTILITY', 'turboprop', 16, 'SW4', 'C26')   # C-26 Metro (US Army / ANG), the owner 27 Oct 2026 PAT71 was labelled UNIDENTIFIED
_add('ARMY / UTILITY', 'twin', 16, 'C560', 'UC35')
_add('HELICOPTER', 'helicopter', 22, 'H47', 'CH47')
_add('HELICOPTER', 'helicopter', 18, 'H60', 'S70', 'H64', 'H53', 'H53S', 'NH90', 'EH10')

CAT_COLOR = {'TANKER': '#9dbb6b', 'AIRLIFT': '#6fa8dc', 'ISR / RECON': '#e8a33d', 'AIRBORNE EARLY WARNING': '#b07fd8',
             'COMMAND & COMMS': '#8e9eff', 'MARITIME PATROL': '#4fc3c7', 'ELECTRONIC WARFARE': '#e8a33d', 'DRONE': '#d4d46a', 'BOMBER': '#e06c5a',
             'FIGHTER': '#ff6b6b', 'SPECIAL OPS': '#a3b18a', 'USMC': '#c9a54a', 'VIP / GOVERNMENT': '#d9c08f', 'ARMY / UTILITY': '#8fa36b',
             'HELICOPTER': '#9aa5b1', 'UNIDENTIFIED': '#6c757d'}

def lookup(type_code, category=None):
    c = str(type_code or '').upper().strip()
    if c in T:
        cat, shape, size = T[c]
    else:  # type not in this table: no role tag (never 'UNIDENTIFIED' for a plane the bot knows); the bot sends 'UNIDENTIFIED' itself when it is (the owner 27 Oct 2026, PAT71)
        cat, shape, size = '', 'twin', 24
    if category:  # bot override (e.g. Government / VIP from its own VIP check)
        cat = category
    return cat, shape, size
