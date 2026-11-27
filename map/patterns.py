"""Routine vs unusual, from the airborne history (patterns.json, rebuilt daily by make_patterns.py on main).
Evidence only, never a forecast: every line carries the number behind it (the owner 2 Nov 2026).
label(P, hex, type, lat, lon, frm, to) -> {'lines': [...], 'kind': 'routine' | 'unusual' | 'new' | 'back' | ''}"""
import datetime

NAMES = {'TANKER': 'tankers', 'AIRLIFT': 'airlifters', 'ISR': 'ISR / patrol planes', 'DRONE': 'drones',
         'BOMBER': 'bombers', 'FIGHTER': 'fighters', 'VIP': 'VIP / government planes', 'HELO': 'helicopters',
         'OTHER': 'military planes'}
ROUTINE_PLANE, ROUTINE_AREA, ROUTINE_ROUTE, MIN_GROUP_DAYS, COVERED = 8, 10, 5, 20, 10
RARE_AREA = 3   # under 3 days in 30 within 200 km = ⚠️ rare area (4 Nov 2026)


TG_FIX = {'F2TH': 'VIP'}      # Falcon 2000 is a business / VIP jet, not a fighter (the owner 3 Nov 2026: wrong tags)


def _group(P, t):
    k = ((t or '').upper().split(' ') or [''])[0]
    return TG_FIX.get(k) or (P.get('tg') or {}).get(k, 'OTHER')


def _dd(n):
    return '%d day%s' % (n, '' if n == 1 else 's')


def _day(n):
    return (datetime.date(1970, 1, 1) + datetime.timedelta(n)).strftime('%-d %b %Y')


def _cent(lat, lon):
    return 10 <= lat <= 42 and 25 <= lon <= 75


def _box(lat, lon):            # air-history area (extract_day.py abox)
    return -12 <= lat <= 72 and -60 <= lon <= 80


def _covered(P, cy, cx):       # some military plane was seen within ~200 km on 10+ of the last 30 days
    return max(P['c'].get('ALL|%d|%d' % (cy + dy, cx + dx), [0])[0] for dy in (-2, 0, 2) for dx in (-2, 0, 2)) >= COVERED


def label(P, hx, t='', lat=None, lon=None, frm='', to=''):
    hx = (hx or '').lower().lstrip('~')
    out, kind = [], ''
    asof, W = P['asof'], P['days']
    rec = P['a'].get(hx)
    # EVERY plane gets two tags (the owner 3 Nov 2026). ⚠️ only when truly odd (the owner 3 Nov 15:40: "wrong tags … all over" —
    # 10 of 28 normal tankers / airlifters were "irregular" because a tanker flying 2-6 days a month is normal rotation)
    # No receivers where the plane is now = the history cannot tell whether it flew here before (the owner 3 Nov: USMC C-130J
    # 170279 over Somalia got "Back after 39 days" although the bot itself posted it over Djibouti / Gulf of Aden on 22 Oct, 1 and 3 Nov;
    # the adsb.lol archive has no receivers there). Then only a ❔ line, never a ⚠️ claim.
    blind = False
    if lat is not None and lon is not None:
        blind = (not _box(lat, lon)) or not _covered(P, int(lat // 2) * 2, int(lon // 2) * 2)
    if blind and (rec is None or rec[0] < 1):
        out.append(('❔ Not in our flight history yet — few receivers here, it may have flown unseen' if rec is None else
                    '❔ Last flight in our history %s — few receivers here, it may have flown since unseen' % _day(rec[3])))
    elif rec is None:
        out.append('⚠️ First time seen — no earlier flights on record (records since %s)' % _day(P['from']))
        kind = 'new'
    else:
        d30, d90, last = rec[0], rec[1], rec[3]
        if d30 >= 1:
            out.append('♻️ Known airframe — flew on %s out of the last 30 (%d out of 90)' % (_dd(d30), d90))
            kind = 'routine'
        else:
            out.append('⚠️ Back after %d days — last flight %s' % (asof - last, _day(last)))
            kind = 'back'
    g = _group(P, t)
    n0, kind0 = len(out), kind
    if lat is not None and lon is not None:
        if not _box(lat, lon):
            out.append('⚠️ Unusual area for %s — outside the area the history covers' % NAMES[g])
            kind = kind if kind != 'routine' else 'unusual'
        else:
            cy, cx = int(lat // 2) * 2, int(lon // 2) * 2
            here = P['c'].get('%s|%d|%d' % (g, cy, cx), [0, 0, 0])
            near = [P['c'].get('%s|%d|%d' % (g, cy + dy, cx + dx), [0, 0, 0]) for dy in (-2, 0, 2) for dx in (-2, 0, 2)]
            thin = '' if _covered(P, cy, cx) else ' · few receivers here'
            # cells touched by a ±1° box around the plane (~100 km): the 2° grid edge must not make a busy area look unusual
            # (the owner 3 Nov 2026: KC-135 just south of 24N over the UAE got "unusual, 8 days" while 24-26N had 30/30)
            by = max(P['c'].get('%s|%d|%d' % (g, int(y // 2) * 2, int(x // 2) * 2), [0])[0]
                     for y in (lat - 1, lat, lat + 1) for x in (lon - 1, lon, lon + 1))
            if here[0] >= ROUTINE_AREA and here[0] >= by:
                out.append('♻️ Usual area for %s — seen here on %d days out of the last 30' % (NAMES[g], here[0]))
                kind = kind or 'routine'
            elif by >= ROUTINE_AREA:
                out.append('♻️ Usual area for %s — seen within 100 km on %d days out of the last 30' % (NAMES[g], by))
                kind = kind or 'routine'
            elif max(c[0] for c in near) == 0 and thin:
                # no receivers here in the history = no evidence either way (the owner 3 Nov 17:05: "most of the ⚠️ Unusual area for airlifters
                # statements are wrong" — Red Sea, Egypt, west Saudi, Yemen, east Iran have NO military plane of any kind in the adsb.lol history)
                out.append('❔ Area not rated for %s — no flight history here (few receivers)' % NAMES[g])
            elif max(c[0] for c in near) == 0:
                n90 = max(c[1] for c in near)
                out.append('⚠️ Unusual area for %s — none within 200 km in the last 30 days (%s)%s' % (
                    NAMES[g], 'none in 90 days either' if n90 == 0 else 'seen on %s out of 90' % _dd(n90), thin))
                kind = 'unusual'
            else:
                # some within 200 km: ♻️ from 3 days in 30. 1-2 days is RARE, not regular (the owner 4 Nov 2026, RC-135U COBRA49 over the
                # mid-Atlantic got "♻️ … seen within 200 km on 1 day": "It's not that regular … another fatal mistake")
                n = max(here[0], max(c[0] for c in near))
                if n < RARE_AREA:
                    out.append('⚠️ Rare area for %s — seen within 200 km on only %s out of the last 30%s' % (NAMES[g], _dd(n), thin))
                    kind = 'unusual'
                else:
                    out.append('♻️ %s seen within 200 km on %s out of the last 30' % (NAMES[g][0].upper() + NAMES[g][1:], _dd(n)))
    # Airlifters are passing through, not working the area (the owner 3 Nov: "keep rating across the Atlantic or areas in
    # Saudi Arabia as not known for airlifters … it's just crossing there and tag is wrong"): keep only a ♻️ usual-area line.
    # Tankers too (the owner 3 Nov: "yes" — same crossing problem off Nova Scotia / over Saudi)
    # 27 Nov 2026 audit: the lines that dropped every tanker warning here were removed. Owner rule of 21 Nov 2026: tankers get no
    # "usual area" line (the bot drops it) and DO get the warning when the area is unusual.
    # Airlifters (the owner 3 Nov: "no need for ♻️ Usual area for airlifters … it should only appear when it's unusual area for
    # lifters", too repetitive; : crossing the Atlantic / Saudi is not "unknown"): the area line stays ONLY when it is a
    # real ⚠️ unusual area where receivers exist — no ♻️ usual / within-200-km lines, no ❔ not-rated, no "outside the area".
    if g == 'AIRLIFT' and len(out) > n0:
        last = out[-1]
        if not (last.startswith('⚠️ Unusual area') and 'outside the area' not in last):
            out.pop()
            kind = kind0
    if frm and to and frm != to:
        r = P['r'].get('%s|%s>%s' % (g, frm.upper(), to.upper()))
        if r and r[1] >= ROUTINE_ROUTE:
            out.append('♻️ Usual route %s → %s — flown %d times by %s in 90 days' % (frm.upper(), to.upper(), r[1], NAMES[g]))
            kind = kind or 'routine'
    return {'lines': out, 'kind': kind, 'group': g, 'asof': _day(asof), 'days': W}
