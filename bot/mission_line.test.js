const L = require('./mission_line.js'), ids = require('./mission_ids_2026-11-16.json'), assert = require('assert');
const T = Date.UTC(2026, 10, 16, 21, 0);          // 16 Nov 2026 21:00 UTC = day 320
let n = 0; const eq = (a, b, m) => { assert.strictEqual(a, b, m); n++; };
// 11 Nov cases unchanged
eq(L.acarsMissionText_('PAM102071226', Date.UTC(2026,7,20), 1), '📋 Special airlift mission · high priority · 14 Aug');
eq(L.acarsMissionText_('AAM101971293', Date.UTC(2026,9,21), 1), '📋 Special airlift mission · high priority · 20 Oct');
eq(L.acarsMissionText_('JAM7971E1314', Date.UTC(2026,10,11), 1), '📋 Special airlift mission · 10 Nov');
eq(L.acarsMissionText_('AJM512171320', T, 1), '📋 Special airlift mission · high priority · 16 Nov');
eq(L.acarsMissionText_('AJM125701320', T, 1), '📋 Special airlift mission · 16 Nov');      // code 01, not high priority
eq(L.acarsMissionText_('JJM8633V1320', T, 1), '📋 Special airlift mission · 16 Nov');      // letter code not printed
eq(L.acarsMissionText_('JLM112501314', T, 1), '');                                          // L in pos 2: not SAAM
eq(L.acarsMissionText_('GAM102315311', T, 1), '');                                          // G in pos 1
// CENTCOM shuttle
eq(L.acarsMissionText_('AMYF996YT319', T, 1), '📋 CENTCOM shuttle · 15 Nov');
eq(L.acarsMissionText_('AJYF998YT320', T, 1), '📋 CENTCOM shuttle · 16 Nov');
// rejected in every mode
for (const m of [1,2,3]) for (const id of ['COLLINSAM123','ZZZ123456789','RCAFCYTR1234','RCH4155','AJM51217132','ajm512171320']) eq(L.acarsMissionText_(id, T, m), '', id+' m'+m);
// year rollover: message 2 Jan 2027, SAAM day 360 = 26 Dec 2026; day 002 in late Dec belongs to next year
eq(L.acarsMissionText_('PAM7973E3360', Date.UTC(2027,0,2), 1), '📋 Special airlift mission · 26 Dec');
eq(L.acarsMissionText_('PAM7973E3002', Date.UTC(2026,11,30), 1), '📋 Special airlift mission · 2 Jan');
eq(L.acarsMissionText_('PAM7973E3366', Date.UTC(2026,11,30), 1), '');   // 2026 has no day 366
// future planned date (AMZM2910C325 on day 320) ok in mode 2, too far ahead not
eq(L.acarsMissionText_('AMZM2910C325', T, 2), '📋 Mission ID on file · 21 Nov');
eq(L.acarsMissionText_('AMZM2910C340', T, 2), '');
// modes
eq(L.acarsMissionText_('PVZM2900C319', T, 1), '');
eq(L.acarsMissionText_('PVZM2900C319', T, 2), '📋 Mission ID on file · 15 Nov');
eq(L.acarsMissionText_('PVZM2900C319', T, 3), '📋 Mission PVZM2900C319 · 15 Nov');
eq(L.acarsMissionText_('PVZM2900C319', T, 0), '');
eq(L.acarsMissionText_('AJM512171320', T, 0), '');
// message parsing (real text from acars/latest.json) + wrapper
eq(L.acarsMission_('- #MDINI/ID50104A,RCH563,JBZGDU70F317/MR0,0/AFKDOV,ETAR/TD131600,230022BC', T), '');
eq(L.acarsMission_('- #MDINI/ID99206A,RCH4155,AJM512171320/MR0,0/AFRJTY,ZGSZ', T), '\n📋 Special airlift mission · high priority · 16 Nov');
eq(L.acarsMission_('- #MDINI/ID99206A,RCH4155,AJM5121713200/MR0', T), '');               // 13 chars
eq(L.acarsMission_('no id here', T), ''); eq(L.acarsMission_(null, T), ''); eq(L.acarsMission_(undefined, undefined), '');
// review 16 Nov: whole-day window, field must end at / , or end of text, mode 3 never prints the banned words
eq(L.acarsMissionText_('AJM512171275', T, 1), '📋 Special airlift mission · high priority · 2 Oct');
eq(L.acarsMissionText_('AJM512171274', T, 1), '');
eq(L.acarsMissionText_('AJM512171322', Date.UTC(2027,0,2,21), 1), '📋 Special airlift mission · high priority · 18 Nov');
for (const x of ['AJM512171320a/MR0','AJM512171320./','AJM512171320-X/','AJM512171320 X/']) eq(L.acarsMission_('/ID99206A,RCH4155,' + x, T), '', x);
eq(L.acarsMission_('/ID99206A,RCH4155,AJM512171320', T), '\n📋 Special airlift mission · high priority · 16 Nov');
for (const x of ['POTUS1234320','VIPA12345320','FILED1234320']) eq(L.acarsMissionText_(x, T, 3), '📋 Mission ID on file · 16 Nov', x);
// all 64 live IDs: no VIP/POTUS/filed/dated text in any mode; mode 1 only SAAM + shuttle
const c = {1:0,2:0,3:0}, out = [];
for (const id of Object.keys(ids)) for (const m of [1,2,3]) {
  const s = L.acarsMissionText_(id, T, m); if (s) c[m]++;
  assert(!/VIP|POTUS|filed|dated/i.test(s)); n++;
  if (m === 1 && s) { assert(/^[ALPJUX][JAV]M|^A[JMV]YF/.test(id), id); out.push(id + ' ' + ids[id].map(x=>x[0]).join('/') + ' → ' + s); }
}
console.log(out.join('\n'));
console.log('live IDs', Object.keys(ids).length, 'lines: mode1', c[1], 'mode2', c[2], 'mode3', c[3]);
console.log('ALL OK', n, 'asserts');
