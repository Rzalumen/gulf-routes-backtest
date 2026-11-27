// Scramble "other countries" sweep runner — RAF / United Kingdom first (the owner 20 Nov 2026).
// Paste into a tab on https://www.scramble.nl/database/military/<cc> (cc = 'uk' first), then:
//   window.__rafStart(<stack JSON array>, 15, 120000)
// Same pace as the USAF sweep: max 15 queries per batch, 120 s between queries, stop at the first
// Cloudflare challenge. Never solves or bypasses a challenge. Progress lives in window.__raf
// (and localStorage 'raf_state') so it can be polled with short JS calls.
// Split rule: a query that returns >= 30 rows (Scramble's cap) is split into prefix+0..9
// (and prefix+A..Z while the prefix is only letters), pushed back in reverse so the stack pops them in order.
(function () {
  function isChallenge(status, html) {
    return status !== 200 || /<title>\s*Just a moment/i.test(html) || /cf_chl|challenge-platform/i.test(html);
  }
  function parseRows(html) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var out = [];
    doc.querySelectorAll('table').forEach(function (t) {
      var th = [].slice.call(t.querySelectorAll('th')).map(function (c) { return c.textContent.replace(/\s+/g, ' ').trim(); });
      if (th.length >= 5 && window.__raf && !window.__raf.head) window.__raf.head = th;
    });
    doc.querySelectorAll('table tr').forEach(function (tr) {
      var td = [].slice.call(tr.querySelectorAll('td')).map(function (c) { return c.textContent.replace(/\s+/g, ' ').trim(); });
      if (td.length >= 5 && /^[A-Z0-9]{1,3}[-A-Z0-9]*\d/i.test(td[0])) out.push(td.slice(0, 8));
    });
    return out;
  }
  function splitKids(p) {
    var kids = [];
    for (var d = 0; d <= 9; d++) kids.push(p + d);
    if (/^[A-Z]{1,2}$/.test(p) && p.length < 2) for (var c = 65; c <= 90; c++) kids.push(p + String.fromCharCode(c));
    return kids;
  }
  async function query(prefix) {
    var form = [].slice.call(document.forms).filter(function (f) { return /\/database\/military\//.test(f.getAttribute('action') || ''); })[0];
    if (!form) throw new Error('search form not found');
    var fd = new FormData(form);
    fd.set('jform[serial]', prefix + '*');
    fd.set('jform[code]', ''); fd.set('jform[type]', ''); fd.set('jform[unit]', ''); fd.set('jform[cn]', '');
    fd.set('jform[active]', '1');
    if (!fd.get('task')) fd.set('task', 'mil.search');
    var r = await fetch(form.action, { method: 'POST', body: fd, credentials: 'same-origin' });
    var html = await r.text();
    return { status: r.status, html: html };
  }
  window.__rafStart = function (stack, max, gap) {
    var S = window.__raf = { stack: stack.slice(), done: [], rows: [], log: [], q: 0, max: max || 15, gap: gap || 120000, status: 'running', started: new Date().toISOString() };
    (async function () {
      while (S.q < S.max && S.stack.length) {
        var p = S.stack.pop();
        var res;
        try { res = await query(p); } catch (e) { S.stack.push(p); S.status = 'error: ' + e; break; }
        S.q++;
        if (isChallenge(res.status, res.html)) { S.stack.push(p); S.status = 'challenge at query ' + S.q + ' (HTTP ' + res.status + ')'; S.log.push(p + ' CHALLENGE'); break; }
        var rows = parseRows(res.html);
        if (rows.length >= 30 && p.length < 5) {
          var kids = splitKids(p);
          for (var i = kids.length - 1; i >= 0; i--) S.stack.push(kids[i]);
          S.log.push(p + ' ' + rows.length + ' rows -> split');
          rows.forEach(function (r) { S.rows.push(r); });
        } else {
          rows.forEach(function (r) { S.rows.push(r); });
          S.done.push(p);
          S.log.push(p + ' ' + rows.length + ' rows');
        }
        try { localStorage.setItem('raf_state', JSON.stringify(S)); } catch (e) {}
        if (S.q < S.max && S.stack.length) await new Promise(function (r) { setTimeout(r, S.gap); });
      }
      if (S.status === 'running') S.status = S.stack.length ? 'batch done' : 'stack empty';
      S.finished = new Date().toISOString();
      try { localStorage.setItem('raf_state', JSON.stringify(S)); } catch (e) {}
    })();
    return 'started ' + S.stack.length;
  };
})();
