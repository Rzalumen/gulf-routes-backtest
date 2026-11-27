// DRAFT — not in the bot yet (pattern system step 4, 27 Oct 2026). Goes into aircraft.gs only after the owner's "approved".
// One line under each alert, owner copy first: how often THIS airframe flies, from the history the GitHub job publishes
// daily to branch 'labels' (labels/<first 3 hex chars>.json: { asof, hex: { <hex>: [days of last 30, days of last 90,
// last seen, first seen, [[FROM>TO, flights] … only routes flown 3+ times]] } }).
// Needs Script Property GH_READ = a fine-grained GitHub token, repository Rzalumen/gulf-routes-backtest, Contents: Read-only
// (the owner pastes it himself). Cached 6 h per shard; one fetch per shard, never slows an alert by more than one request.
var ACW_PAT = { ON: true, SHOW_CHANNEL: false };
function acwPatShard_(hex) {
  var k = String(hex || '').toLowerCase().slice(0, 3), c = CacheService.getScriptCache(), v = c.get('pat_' + k);
  if (v) return v === '-' ? null : JSON.parse(v);
  var tok = PropertiesService.getScriptProperties().getProperty('GH_READ'); if (!tok) return null;
  var o = null;
  try {
    var r = UrlFetchApp.fetch('https://api.github.com/repos/Rzalumen/gulf-routes-backtest/contents/labels/' + k + '.json?ref=labels',
      { headers: { Authorization: 'Bearer ' + tok, Accept: 'application/vnd.github.raw' }, muteHttpExceptions: true });
    if (r.getResponseCode() === 200) o = JSON.parse(r.getContentText());
  } catch (e) {}
  var s = o ? JSON.stringify(o) : '-'; if (s.length < 95000) c.put('pat_' + k, s, 21600);
  return o;
}
function acwPatLine_(hex, shard) {   // shard: optional (tests); returns one line or ''
  if (!ACW_PAT.ON || !hex) return '';
  var o = shard || acwPatShard_(hex); if (!o) return '';
  var rec = (o.hex || {})[String(hex).toLowerCase()];
  if (!rec) return '🆕 Not seen by free ADS-B in the last 90 days';
  var d30 = rec[0], d90 = rec[1], last = rec[2], first = rec[3], rt = ((rec[4] || [])[0] || [])[0], asof = o.asof;
  var gap = Math.round((Date.parse(asof) - Date.parse(last)) / 864e5);
  var route = rt ? ' · usually ' + rt.split('>').map(function (c) { return acwPatApt_(c); }).join(' → ') : '';
  if (first === asof) return '🆕 First time seen in ' + Math.round((Date.parse(asof) - Date.parse('2025-05-01')) / 2592e6) + ' months of history';
  if (d30 >= 8) return '♻️ Routine — seen on ' + d30 + ' of the last 30 days' + route;
  if (d30 >= 1) return '📊 Seen on ' + d30 + ' of the last 30 days (' + d90 + ' of 90)' + route;
  return '💤 First flight in ' + gap + ' days (last seen ' + last + ')';
}
function acwPatApt_(code) {   // airport name from the bot's own list when it has it, else the ICAO code
  try { for (var i = 0; i < ACW_APTS.length; i++) if (ACW_APTS[i][1] === code) return ACW_APTS[i][0]; } catch (e) {}
  return code;
}
