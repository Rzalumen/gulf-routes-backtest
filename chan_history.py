#!/usr/bin/env python3
"""The bot's OWN history from its public channel (Reza 3 Nov 2026 22:45 ET: "the bot should look into all the existing data
and feeding history"). Every aircraft post in t.me/s/gulfsituation is one sighting: airframe (hex), UTC time, and the place
the post names. Written as air-history rows (hex,type,reg,callsign,minute,lat,lon,alt) in air/air-chan-YYYY-MM-DD.csv.gz so
make_patterns.py counts them like the adsb.lol and air-bot files.
- lat/lon only when the place is precise (a city, a sea / gulf, a small country). Big countries and "X coast" give a
  day-only row (lat/lon empty): the airframe's flying day counts, no area cell is invented.
- Posts naming several airframes (digests) give day-only rows for each.
- Also: claude/data/oct2026_flight_log.csv (DG / AA tracking, 1 Oct - 1 Nov 2026) → day-only rows (air-log-*).
usage: chan_history.py OUT_DIR [LOG_CSV] [CITIES_JSON]"""
import sys, os, re, csv, gzip, json, time, datetime, collections, urllib.request
from html.parser import HTMLParser

OUT = sys.argv[1]
LOG = sys.argv[2] if len(sys.argv) > 2 else ''
CITIES = sys.argv[3] if len(sys.argv) > 3 else ''
os.makedirs(OUT, exist_ok=True)

# display type in the post → ICAO type code (only the group matters downstream)
DISPLAY = [('KC-46', 'B762'), ('KC-135', 'K35R'), ('KC-10', 'DC10'), ('KC-707', 'B703'), ('KC-130', 'C30J'), ('C-130J', 'C30J'),
           ('C-130', 'C130'), ('C-17', 'C17'), ('C-5', 'C5M'), ('A400', 'A400'), ('Voyager', 'A332'), ('MRTT', 'A332'), ('Phenix', 'A332'),
           ('A330', 'A332'), ('P-8', 'P8'), ('RQ-4', 'Q4'), ('MQ-4', 'Q4'), ('Global Hawk', 'Q4'), ('Triton', 'Q4'), ('MQ-9', 'Q9'),
           ('Reaper', 'Q9'), ('Heron', 'HRON'), ('RC-135', 'R135'), ('Rivet Joint', 'R135'), ('E-3', 'E3TF'), ('E-7', 'E737'),
           ('Wedgetail', 'E737'), ('E-767', 'E767'), ('E-2', 'E2'), ('E-8', 'E8'), ('E-6', 'E6'), ('U-2', 'U2'), ('G550', 'GLF5'),
           ('B-52', 'B52'), ('B-1', 'B1'), ('B-2', 'B2'), ('C-40', 'B737'), ('C-32', 'C32'), ('C-37', 'C37'), ('UC-35', 'C560'),
           ('C-12', 'BE20'), ('C-26', 'SW4'), ('MV-22', 'V22'), ('CV-22', 'V22'), ('CMV-22', 'V22'), ('V-22', 'V22'), ('F-35', 'F35'),
           ('F-16', 'F16'), ('F-15', 'F15'), ('F/A-18', 'F18'), ('Typhoon', 'EUFI'), ('Rafale', 'RFAL'), ('EA-37', 'GLF5'),
           ('UH-60', 'H60'), ('Black Hawk', 'H60'), ('CH-47', 'H47'), ('Chinook', 'H47')]
CATEGORY = [('Tanker', 'K35R'), ('Airlifter', 'C17'), ('Bomber', 'B52'), ('Maritime patrol', 'P8'), ('AWACS', 'E3TF'),
            ('surveillance', 'E3TF'), ('Surveillance drone', 'Q9'), ('drone', 'Q9'), ('EARLY WARNING', 'GLF5')]

# precise places (lat, lon): seas / gulfs where the bot names them, small countries and emirates
PLACES = {
    'persian gulf': (26.5, 52.5), 'arabian gulf': (26.5, 52.5), 'gulf of oman': (24.5, 58.5), 'strait of hormuz': (26.5, 56.3),
    'gulf of aden': (12.5, 47.5), 'red sea': (20.0, 38.5), 'arabian sea': (17.0, 62.0), 'eastern mediterranean': (34.0, 33.5),
    'gulf of aqaba': (28.8, 34.8), 'gulf of suez': (28.5, 33.0), 'black sea': (43.0, 34.0), 'caspian sea': (41.0, 51.0),
    'qatar': (25.3, 51.2), 'qatar coast': (25.3, 51.2), 'bahrain': (26.0, 50.55), 'kuwait': (29.3, 47.8), 'uae': (24.2, 54.5),
    'uae coast': (24.6, 54.6), 'united arab emirates': (24.2, 54.5), 'djibouti': (11.6, 43.1), 'israel': (31.5, 34.9),
    'lebanon': (33.8, 35.8), 'cyprus': (35.0, 33.2), 'jordan': (31.5, 36.5), 'gaza': (31.4, 34.4), 'west bank': (31.9, 35.2),
    'kuwait bay': (29.4, 47.9), 'sinai': (29.5, 33.8), 'diego garcia': (-7.3, 72.4),
    'aegean sea': (38.5, 25.0), 'israel coast': (32.3, 34.6), 'cyprus coast': (34.8, 33.0), 'central mediterranean': (35.0, 15.0),
    'djibouti coast': (11.8, 43.3), 'lebanon coast': (33.8, 35.4), 'bahrain coast': (26.1, 50.6), 'kuwait coast': (29.3, 48.1),
}

def ll_of(place, cities):
    p = re.sub(r'\s+', ' ', place or '').strip().strip('~').strip()
    p = re.sub(r'^(now: )?(over|near|off|above) ', '', p, flags=re.I).strip()
    k = p.lower()
    if k in PLACES:
        return PLACES[k]
    if k in cities:
        return cities[k]
    return None

class Page(HTMLParser):
    """t.me/s page → [(post_id, iso_time, text)] with reply quotes left out"""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts, self.cur, self.depth, self.in_text, self.skip = [], None, 0, 0, 0
    def handle_starttag(self, tag, a):
        a = dict(a); cls = a.get('class') or ''
        if tag == 'div' and 'tgme_widget_message ' in cls + ' ' and a.get('data-post'):
            self.cur = {'id': int(a['data-post'].split('/')[-1]), 't': None, 'text': []}
            self.posts.append(self.cur)
        if self.cur is None:
            return
        # main text only: class 'js-message_text' (a reply quote uses 'js-message_reply_text')
        if tag == 'div' and 'js-message_text' in cls.split():
            self.in_text = 1; return
        if self.in_text:
            if tag == 'div': self.in_text += 1
            if tag == 'br': self.cur['text'].append('\n')
        if tag == 'time' and a.get('datetime') and not self.cur['t']:
            self.cur['t'] = a['datetime']
    def handle_startendtag(self, tag, a):
        if self.in_text and tag == 'br' and self.cur is not None:
            self.cur['text'].append('\n')
    def handle_endtag(self, tag):
        if tag != 'div':
            return
        if self.in_text:
            self.in_text -= 1
    def handle_data(self, d):
        if self.cur is not None and self.in_text:
            self.cur['text'].append(d)

def fetch(before):
    url = 'https://t.me/s/gulfsituation' + ('?before=%d' % before if before else '')
    for k in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (history backfill)'})
            return urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'replace')
        except Exception as e:
            print('fetch', before, e); time.sleep(5 * (k + 1))
    sys.exit('::error::t.me page before=%s failed 4 times - nothing written (a partial read would replace the full channel history)' % before)

def type_of(text):
    head = text[:300]
    for k, v in DISPLAY:
        if k.lower() in head.lower():
            return v
    for k, v in CATEGORY:
        if k.lower() in head.lower():
            return v
    return ''

def main():
    cities = {}
    if CITIES and os.path.exists(CITIES):
        for c in json.load(open(CITIES)):
            cities.setdefault(str(c[0]).lower(), (float(c[2]), float(c[1])))   # [name, lon, lat, pop, …]
    rows = collections.defaultdict(set)          # day → rows
    mlines = []                                  # 📋 mission lines (self-check of the mission-ID decoder, 13 Nov 2026)
    unplaced = collections.Counter()
    before, n_posts, n_air, n_pos = 0, 0, 0, 0
    seen_ids = set()
    while True:
        p = Page(); p.feed(fetch(before))
        posts = [x for x in p.posts if x['id'] not in seen_ids]
        if not posts:
            break
        for x in posts:
            seen_ids.add(x['id']); n_posts += 1
            if not x['t']:
                continue
            text = ''.join(x['text'])
            hexes = list(dict.fromkeys(re.findall(r'\bhex\s+~?([0-9a-f]{6})\b', text, flags=re.I)))
            # every ACARS post (line due or not) and every 📋 line: the self-check needs both to spot a missing or a wrong line (16 Nov)
            ml = [ln.strip() for ln in text.split('\n') if ln.strip().startswith('📋')]
            acars = 1 if re.search(r'\bACARS\b', text) else 0
            if ml or acars:
                first = text.strip().split('\n')[0][:160]
                cs = (re.search(r'·\s*([A-Z]{2,6}\d{1,4}[A-Z]?)\s*(?:·|$)', first) or re.search(r'·\s*([A-Z]{2,6}\d{1,4}[A-Z]?)\s*·', text) or [None, ''])[1]
                rg = (re.search(r'([0-9]{2}-[0-9]{4,5}|[0-9]{6}|[A-Z][A-Z0-9]?-[A-Z0-9]{3,5})\s*$', re.sub(r'\s*·?\s*hex\s+\S+\s*$', '', first)) or [None, ''])[1]
                mlines.append((x['id'], x['t'], ' '.join(h.lower() for h in hexes), cs, rg, acars, first, ' | '.join(ml)))
            if not hexes:
                continue
            n_air += 1
            t = datetime.datetime.fromisoformat(x['t'].replace('Z', '+00:00'))
            minute = int(t.timestamp() // 60)
            day = t.date().isoformat()
            typ = type_of(text)
            reg = (re.search(r'·\s*([0-9]{2}-[0-9]{4,5}|[0-9]{6}|[A-Z]{1,2}-?[A-Z0-9]{3,5})\s*·\s*hex', text) or [None, ''])[1]
            cs = ''
            ll = None
            if len(hexes) == 1:
                m = re.search(r'📍\s*([^\n·]+)', text)
                if m:
                    ll = ll_of(m.group(1), cities)
                    if ll is None:
                        unplaced[re.sub(r'^(Now: )?(over|near) ', '', m.group(1).strip(), flags=re.I)] += 1
            for hx in hexes:
                hx = hx.lower()
                if ll and len(hexes) == 1:
                    rows[day].add((hx, typ, reg, cs, str(minute), '%.3f' % ll[0], '%.3f' % ll[1], ''))
                    n_pos += 1
                else:
                    rows[day].add((hx, typ, reg if len(hexes) == 1 else '', cs, str(minute), '', '', ''))
        before = min(x['id'] for x in posts)
        if before <= 1:
            break
        time.sleep(0.4)
    for day, rs in sorted(rows.items()):
        with gzip.open(os.path.join(OUT, 'air-chan-%s.csv.gz' % day), 'wt') as fh:
            csv.writer(fh).writerows(sorted(rs))
    # every ACARS post and every 📋 line with post id, time, hex(es), callsign and the post's first line → out/mission-lines.csv.gz (name does not match air-*, so
    # make_patterns.py ignores it; chan.yml's `cp out/*.csv.gz` puts it on air-history). Read-only record for the daily self-check.
    with gzip.open(os.path.join(OUT, 'mission-lines.csv.gz'), 'wt') as fh:
        w = csv.writer(fh); w.writerow(['post_id', 'time_utc', 'hexes', 'callsign', 'reg', 'acars_post', 'first_line', 'mission_line'])
        w.writerows(sorted(mlines))
    print('mission-lines.csv.gz: %d rows (%d with a 📋 line, %d ACARS posts)' % (len(mlines), sum(1 for r in mlines if r[7]), sum(r[5] for r in mlines)))
    print('channel: %d posts read, %d aircraft posts, %d rows with a position, %d days' % (n_posts, n_air, n_pos, len(rows)))
    print('places without a precise position (day-only):', unplaced.most_common(40))
    # DG / AA flight log (day-only)
    if LOG and os.path.exists(LOG):
        lr = collections.defaultdict(set)
        for r in csv.DictReader(open(LOG, newline='')):
            hx = (r.get('hex') or '').strip().lower()
            if not re.fullmatch(r'[0-9a-f]{6}', hx):
                continue
            typ = ''
            for k, v in DISPLAY:
                if k.lower() in (r.get('type') or '').lower():
                    typ = v; break
            d = r['date']
            minute = int(datetime.datetime.fromisoformat(d + 'T12:00:00+00:00').timestamp() // 60)
            lr[d].add((hx, typ, r.get('reg') or '', r.get('callsign') or '', str(minute), '', '', ''))
        for day, rs in sorted(lr.items()):
            with gzip.open(os.path.join(OUT, 'air-log-%s.csv.gz' % day), 'wt') as fh:
                csv.writer(fh).writerows(sorted(rs))
        print('flight log: %d airframe-days' % sum(len(v) for v in lr.values()))

main()
