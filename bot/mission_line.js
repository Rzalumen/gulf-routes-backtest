// ===== 📋 Mission line (generalised 16 Nov 2026, the owner: "i want 📋 line whenever available for every military, vip, gov,
// cargo, hidden and etc"; answers: mode 1 now, "prepare to switch to 2 or 3"; place = head posts and updates).
// Drop-in replacement for acarsMission_(tx, tMs) in aircraft.gs (same name, same return: '' or '\n📋 …').
// Notes: claude/START-HERE-11nov-mission-line.md, claude/mission-number-decode.md. Skill: gulf-mission-decode.
// ACARS_MLINE_MODE: 0 off · 1 words only for known layouts (special airlift, CENTCOM shuttle) · 2 also "Mission ID on file"
// for any other real AMC-style ID · 3 also the raw ID for any other real ID. Wording rules (the owner 11 Nov): plain, short,
// no codes in modes 1-2, never VIP / POTUS / who is aboard, never "filed" / "dated".
var ACARS_MLINE_MODE = 1;
var ACARS_MLINE_REJECT = { COLLINSAM123: 1, ZZZ123456789: 1, RCAFCYTR1234: 1 };   // test / dummy / Canadian IDs
var ACARS_MLINE_MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// /ID<tail>,<callsign>,<MISSION>/ → {tail, cs, id} or null (the identity check against the feed is done by acarsCheck_)
function acarsMissionId_(tx) {
  var m = /\/ID([A-Z0-9]+),([A-Z0-9]*),([A-Z0-9]{12})(?=[\/,]|$)/.exec(String(tx || ''));
  return m ? { tail: m[1], cs: m[2], id: m[3] } : null;
}

// last 3 chars = day of year → "16 Nov", '' when not a day or more than 45 days before / 14 days after the message
// (planned missions can carry a date a few days ahead, e.g. AMZM2910C325 on day 320). Year from the message time.
function acarsMissionDate_(id, tMs) {
  var doy = /(\d{3})$/.exec(id); if (!doy) return '';
  doy = +doy[1]; if (doy < 1 || doy > 366) return '';
  var t0 = new Date(tMs || Date.now()), best = null;
  var now = new Date(Date.UTC(t0.getUTCFullYear(), t0.getUTCMonth(), t0.getUTCDate()));   // whole days, not time of day
  for (var y = now.getUTCFullYear() - 1; y <= now.getUTCFullYear() + 1; y++) {
    var d = new Date(Date.UTC(y, 0, 1) + (doy - 1) * 864e5);
    if (d.getUTCFullYear() !== y) continue;                    // day 366 in a non-leap year
    var diff = (d.getTime() - now.getTime()) / 864e5;
    if (diff >= -45 && diff <= 14 && (!best || Math.abs(diff) < Math.abs(best.diff))) best = { d: d, diff: diff };
  }
  return best ? best.d.getUTCDate() + ' ' + ACARS_MLINE_MON[best.d.getUTCMonth()] : '';
}

// mission ID → line text without the leading newline, or ''
function acarsMissionText_(id, tMs, mode) {
  try {
    mode = mode == null ? ACARS_MLINE_MODE : mode;
    if (!mode || !id || id.length !== 12 || ACARS_MLINE_REJECT[id] || !/^[A-Z0-9]{12}$/.test(id)) return '';
    var date = acarsMissionDate_(id, tMs); if (!date) return '';
    // special airlift (SAAM, hobby layout): [ALPJUX][JAV]M + serial dddd + aircraft code (2) + day — unchanged since 11 Nov
    var s = /^[ALPJUX][JAV]M\d{4}([A-Z0-9]{2})\d{3}$/.exec(id);
    if (s) return '📋 Special airlift mission · ' + (/^7[1-9]$/.test(s[1]) ? 'high priority · ' : '') + date;
    // CENTCOM shuttle (Observed 12-16 Nov: A?YF + last 3 of the RCH 49xx number + YT + day; ETAR / ETAD / OTBH / OJKF legs)
    if (/^A[JMV]YF\d{3}YT\d{3}$/.test(id)) return '📋 CENTCOM shuttle · ' + date;
    if (mode === 2) return '📋 Mission ID on file · ' + date;
    if (mode === 3) return /VIP|POTUS|FILED|DATED/.test(id) ? '📋 Mission ID on file · ' + date : '📋 Mission ' + id + ' · ' + date;
    return '';
  } catch (e) { return ''; }
}

// same signature as the 11 Nov function: message text + message time → '' or '\n📋 …'
function acarsMission_(tx, tMs) {
  try { var m = acarsMissionId_(tx); var t = m ? acarsMissionText_(m.id, tMs) : ''; return t ? '\n' + t : ''; }
  catch (e) { return ''; }
}

if (typeof module !== 'undefined') module.exports = { acarsMission_: acarsMission_, acarsMissionText_: acarsMissionText_,
  acarsMissionId_: acarsMissionId_, acarsMissionDate_: acarsMissionDate_ };
