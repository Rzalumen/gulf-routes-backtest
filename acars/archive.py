#!/usr/bin/env python3
"""ACARS archive (Airframes Pro) — Reza 28 Oct 2026: "save records, don't toss data out".
30 Oct 2026: worldwide for the bot's own aircraft (US, UK, Israel, Russia, China military + government), started by the bot.

Every run:
  1. Hex list = HEXES env (the bot's in-scope aircraft from its own worldwide feed, sent with repository_dispatch)
               or, on the backup cron, US/UK/IL/RU/CN military airborne now (adsb.lol /v2/mil)
               + every hex already in acars/known.json seen in the last KEEP_DAYS days
               + (backfill) the same countries' hexes in history-2025 legs.csv from the last 30 days.
  2. For each hex: Airframes /v1/messages?icao=HEX&timeframe=… paged by offset (100 per page).
  3. New messages (by id) are appended to acars/msgs/YYYY-MM-DD.jsonl (by message time). Never rewritten, never deleted.
  4. Messages that state a destination are appended to acars/destinations.csv.
  5. acars/latest.json = last 24 h digest the bot reads (one file, one Google fetch): per hex newest messages + stated destination,
     plus the newest 60 messages overall for the dashboard ACARS card.
Usage: AIRFRAMES_KEY=… archive.py <data dir> [--backfill]   |   archive.py --selftest
"""
import csv, datetime, json, os, re, sys, time, urllib.request, urllib.error

API = 'https://api.airframes.io/v1/messages'
KEEP_DAYS = 3

# ICAO address blocks (only used on military-flagged lists, so airliners of these countries never enter)
BLOCKS = {'US': (0xADF7C8, 0xAFFFFF), 'UK': (0x43C000, 0x43CFFF), 'IL': (0x738000, 0x73FFFF),
          'RU': (0x100000, 0x1FFFFF), 'CN': (0x780000, 0x7BFFFF)}

def country(h):
    try: n = int(str(h).lstrip('~'), 16)
    except ValueError: return ''
    for c, (a, b) in BLOCKS.items():
        if a <= n <= b: return c
    return ''

def mil(h):
    return country(h) in ('US', 'UK')   # backfill from legs.csv keeps its 28 Oct scope

def parse(tx):
    """Destination ONLY when the message states it (same rules as acarsParse_ in aircraft.gs)."""
    tx = tx or ''
    m = re.search(r'DA:([A-Z]{4}):AA:([A-Z]{4})', tx)
    if m: return {'k': 'flight plan', 'from': m[1], 'to': m[2]}
    m = re.search(r'/AF([A-Z]{4}),([A-Z]{4})', tx)
    if m: return {'k': 'route', 'from': m[1], 'to': m[2]}
    m = re.search(r'/PSN[0-9NSEW]+,\d+,\d+,([A-Z]{4}),(\d{6})', tx)
    if m: return {'k': 'position report', 'to': m[1], 'eta': m[2]}
    m = re.search(r'\b([A-Z]{4}) ARR ATIS', tx)
    if m: return {'k': 'arrival ATIS request', 'to': m[1]}
    return None

def callsign(tx):
    m = re.search(r'/ID\w+,([A-Z]{2,6}\d{1,4})\b', tx or '')
    return m[1] if m else ''

def get(url, headers=None, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:
                time.sleep(int(e.headers.get('Retry-After') or 15) + 1); continue
            print('HTTP', e.code, url.split('?')[0]); return None
        except Exception as e:
            print('ERR', e); time.sleep(5)
    return None

def messages(hexid, key, timeframe, max_pages):
    out = []
    for p in range(max_pages):
        j = get('%s?icao=%s&timeframe=%s&offset=%d' % (API, hexid, timeframe, p * 100), {'Authorization': 'Bearer ' + key})
        m = j if isinstance(j, list) else (j or {}).get('messages') or (j or {}).get('data') or []
        out += m
        if len(m) < 100: break
    return out

def main(d, backfill):
    key = os.environ['AIRFRAMES_KEY']
    now = datetime.datetime.now(datetime.timezone.utc)
    os.makedirs(os.path.join(d, 'msgs'), exist_ok=True)
    kp = os.path.join(d, 'known.json')
    known = json.load(open(kp)) if os.path.exists(kp) else {}
    hexes = {h for h, t in known.items() if now - datetime.datetime.fromisoformat(t) < datetime.timedelta(days=KEEP_DAYS)}
    sent = [h.strip().upper().lstrip('~') for h in os.environ.get('HEXES', '').split(',') if re.fullmatch(r'~?[0-9A-Fa-f]{6}', h.strip())]
    if sent:
        hexes |= set(sent)
    else:   # backup cron: no list from the bot
        live = get('https://api.adsb.lol/v2/mil') or {}
        hexes |= {a['hex'].upper() for a in live.get('ac', []) if country(a.get('hex', ''))}
    print('from bot', len(sent))
    legs = os.environ.get('LEGS', 'legs.csv')
    if backfill and os.path.exists(legs):
        cut = (now.date() - datetime.date(1970, 1, 1)).days - 30
        hexes |= {r['hex'].upper().lstrip('~') for r in csv.DictReader(open(legs)) if int(r['day']) >= cut and mil(r['hex'].lstrip('~'))}
    print('hexes', len(hexes))
    seen = {}   # day file -> set of ids already stored
    def ids(day):
        if day not in seen:
            p = os.path.join(d, 'msgs', day + '.jsonl')
            seen[day] = {json.loads(l)['id'] for l in open(p)} if os.path.exists(p) else set()
        return seen[day]
    dp = os.path.join(d, 'destinations.csv')
    new_dest = not os.path.exists(dp)
    dest = open(dp, 'a', newline=''); w = csv.writer(dest)
    if new_dest: w.writerow(['msg_time', 'hex', 'tail', 'callsign', 'kind', 'from', 'to', 'eta', 'msg_id'])
    n_new = n_dest = 0
    for h in sorted(hexes):
        ms = messages(h, key, 'last-month' if backfill else 'last-day', 30 if backfill else 10)
        if ms: known[h] = now.isoformat(timespec='seconds')
        for m in ms:
            ts = str(m.get('timestamp') or m.get('createdAt') or '')
            if not ts or m.get('id') is None: continue
            day = ts[:10]
            if m['id'] in ids(day): continue
            st = m.get('station') or {}
            m['station'] = {k: st.get(k) for k in ('ident', 'sourceType', 'sourceProtocol', 'nearestAirportIcao')}
            m['_hex'] = h
            with open(os.path.join(d, 'msgs', day + '.jsonl'), 'a') as f: f.write(json.dumps(m, separators=(',', ':')) + '\n')
            ids(day).add(m['id']); n_new += 1
            p = parse(m.get('text'))
            if p:
                w.writerow([ts, h, (m.get('airframe') or {}).get('tail') or '', callsign(m.get('text')), p['k'], p.get('from', ''), p['to'], p.get('eta', ''), m['id']])
                n_dest += 1
    dest.close()
    json.dump(known, open(kp, 'w'), indent=0, sort_keys=True)
    latest(d, now)
    print('new messages', n_new, 'new destinations', n_dest)

def latest(d, now):
    """acars/latest.json from the stored messages of the last 24 h (never rebuilt from the API)."""
    cut = (now - datetime.timedelta(hours=24)).isoformat()
    rows = []
    for day in {(now - datetime.timedelta(days=1)).date().isoformat(), now.date().isoformat()}:
        p = os.path.join(d, 'msgs', day + '.jsonl')
        if os.path.exists(p):
            rows += [m for m in map(json.loads, open(p)) if str(m.get('timestamp') or '') >= cut]
    rows.sort(key=lambda m: str(m.get('timestamp')), reverse=True)
    per = {}
    for m in rows:
        h = m.get('_hex') or ''
        x = per.setdefault(h, {'hex': h, 'country': country(h), 'tail': (m.get('airframe') or {}).get('tail') or m.get('tail') or '',
                               'type': (m.get('airframe') or {}).get('icaoType') or '', 'cs': '', 'n24': 0, 'last': m.get('timestamp'), 'dest': None, 'msgs': []})
        x['n24'] += 1
        x['cs'] = x['cs'] or callsign(m.get('text'))
        if not x['dest']:
            p = parse(m.get('text'))
            if p: x['dest'] = dict(p, t=m.get('timestamp'))
        if len(x['msgs']) < 5: x['msgs'].append([m.get('timestamp'), m.get('label') or '', (m.get('text') or '')[:300]])
    out = {'t': now.isoformat(timespec='seconds'), 'planes': sorted(per.values(), key=lambda x: str(x['last']), reverse=True),
           'recent': [[m.get('timestamp'), m.get('_hex'), (m.get('airframe') or {}).get('tail') or '', callsign(m.get('text')), m.get('label') or '', (m.get('text') or '')[:300]] for m in rows[:60]]}
    json.dump(out, open(os.path.join(d, 'latest.json'), 'w'), separators=(',', ':'))
    print('latest planes', len(per), 'messages 24h', len(rows))

def selftest():
    assert parse('FPN/ID10284S,RCH253,8JZ63OG2S300/MR3,/RP:DA:EGUN:AA:LLBG:F:BANEM') == {'k': 'flight plan', 'from': 'EGUN', 'to': 'LLBG'}
    assert parse('#MDINI/ID50104A,RCH5040,JBBGDR30D294/MR0,0/AFEGUN,ETAR/TD211650')['to'] == 'ETAR'
    assert parse('POS/ID23503S,RCH253,/DC27102026,202501/MR36,/ET272058/PSN52353E002324,202500,280,EGUN,272037,TUSMU')['eta'] == '272037'
    assert parse('/ETMATYA.TI2/LLER ARR ATIS E 1450Z')['to'] == 'LLER'
    assert parse('#MDWXR/ID60002A,RCH845,AMZA2960C300/MR4,65/MTLLOV,0414') is None   # weather request ≠ destination
    assert parse('KSEA DEP ATIS') is None
    assert callsign('#MDINI/ID50104A,RCH5040,JBBGDR30D294') == 'RCH5040'
    assert mil('ae07b0') and mil('43c6fa') and not mil('a5d1b9')
    assert country('738a45') == 'IL' and country('154f2a') == 'RU' and country('780a1b') == 'CN' and country('a5d1b9') == ''
    import tempfile
    t = tempfile.mkdtemp(); os.makedirs(os.path.join(t, 'msgs'))
    now = datetime.datetime.now(datetime.timezone.utc)
    with open(os.path.join(t, 'msgs', now.date().isoformat() + '.jsonl'), 'w') as f:
        f.write(json.dumps({'id': 1, '_hex': 'AE07EC', 'timestamp': now.isoformat(), 'label': 'H1', 'text': '#MDINI/ID50104A,RCH5040,JBBGDR30D294/MR0,0/AFEGUN,ETAR/TD211650', 'airframe': {'tail': '96-0002', 'icaoType': 'C17'}}) + '\n')
    latest(t, now)
    L = json.load(open(os.path.join(t, 'latest.json')))
    assert L['planes'][0]['dest']['to'] == 'ETAR' and L['planes'][0]['cs'] == 'RCH5040' and L['planes'][0]['country'] == 'US' and len(L['recent']) == 1
    print('selftest ok')

if __name__ == '__main__':
    if '--selftest' in sys.argv: selftest()
    else: main(sys.argv[1], '--backfill' in sys.argv)
