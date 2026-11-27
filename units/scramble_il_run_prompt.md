# Scramble OTHER-COUNTRIES sweep — ISRAEL (the owner 23 Nov 2026: "2 Israel", after the UK sweep finished 22 Nov)

Canonical prompt for every batch. Files live on GitHub Rzalumen/gulf-routes-backtest, branch `units`, folder `units/`:
scramble_raf_runner.js (in-page runner), raf_merge.py (merge), il_state.json (stack + batch log), il_rows.csv, il.json (serial → unit).

## Hard rules
- SAME PACE AS USAF: ONE batch of max 15 queries, 120 s between queries. Batches 4 h apart, each one 2 h after a USAF batch start, so scramble.nl never sees more than 15 queries in a row.
- NEVER touch the Scramble USAF sweep (its tasks, prompt, files, Sheet or Browser tab). Only READ its scheduled task to time this one.
- Never solve or bypass a Cloudflare challenge. A challenge = stop the batch, keep the prefix on the stack.
- Never open the mailbox. Never post to Telegram. Never edit bot code (Apps Script) from this job.
- Credit Scramble (permission note 8 Nov 2026: full use + automated lookups allowed, credit required).

## Steps (one batch)
1. Clone: `git clone --depth 1 --branch units --single-branch https://github.com/Rzalumen/gulf-routes-backtest <new empty dir>` (attach with add_repo owner Rzalumen repo gulf-routes-backtest access push if needed). Read units/il_state.json → `page` and `stack`. Stack empty → step 7 (finish, no new batch).
2. Chrome (Claude in Chrome), Browser 1 (the browser named in the project notes) (if not connected, any connected Chrome on the owner's computer that is NOT running the USAF batch right now). Own new tab. Open `page` (https://www.scramble.nl/database/military/il). Title must be "Military Database" and the search form present; "Just a moment..." that does not clear by itself in ~15 s = blocked on load → write it into il_state.json batches (status "blocked on load"), push, schedule the next try as in step 6, tell the owner if the previous batch was also blocked.
3. Inject units/scramble_raf_runner.js (read the file, run its text in the page), then run `window.__rafStart(<stack JSON>, 15, 120000)`.
4. Poll every ~2 min with Bash sleep (never a JS sleep over ~40 s): `JSON.stringify({q: __raf.q, status: __raf.status, log: __raf.log.slice(-2)})` until status is not "running" (~30 min).
5. Extract `window.__raf` in chunks (rows 40 at a time, JSON.stringify; re-read any truncated chunk) into batch.json, run `python3 units/raf_merge.py batch.json il`, then `git add units/il_rows.csv units/il.json units/il_state.json`, commit "Israel units from Scramble (<units> airframes, batch <n>)", `git -c push.negotiate=true push origin units`. Touch no other file. Close the tab.
6. Schedule the next batch with send_later (this same session), message = "Scramble Israel sweep batch: follow units/scramble_il_run_prompt.md on branch units of Rzalumen/gulf-routes-backtest exactly." Time: list_triggers (recurring=false, enabled=true) → enabled task whose name starts "Scramble USAF sweep" → its next_run_at + 2 h. If none is enabled (USAF chain between batches or broken), use this batch's start + 4 h, but never within 60 min of a known USAF batch start. Confirm next_run_at in the result; retry once; if it still fails tell the owner "Israel sweep stopped".
7. Send the owner ONE short update (SendUserMessage), times in UTC, 4 lines max:
   "Scramble Israel batch <h:mm UTC>: <q> queries · <+new> serials · <units> Israeli airframes with a unit
   Prefixes left: <n> (next: <top 3>) · Next batch <h:mm UTC>
   <OK, or: challenge at query N / blocked on load / push failed>"

## After the UK stack is empty
Report the totals to the owner and ask before starting the next country (the bot wiring of il.json into the 🏷 unit line also needs his OK). Candidate order for CENTCOM relevance: Israel (IAF), France, Germany, Italy, then Gulf air forces.

## Israel notes
- IAF serials are plain numbers (e.g. 905, 272, 537); the start stack is the digits 0–9 and a 30-row page splits into prefix+0..9. Same runner file (units/scramble_raf_runner.js) — it only reads the stack you give it.
- After the Israel stack is empty: report totals, schedule nothing, ask the owner before wiring il.json into the bot or starting another country.
- IAF serials REPEAT across types (902 = F-35I, AH-64A and CH-53). When extracting rows from the page, de-duplicate by serial + '|' + type (never by serial alone). raf_merge.py with prefix 'il' keys rows and il.json by "serial|type".
