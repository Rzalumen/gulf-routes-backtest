#!/usr/bin/env bash
# Stream one adsb.lol globe_history day into a command (4 Nov 2026 review: this block was copy-pasted in daily, air,
# backtest and inspect.yml). Tries the release tags in order; split archives (.aa .ab …) and single .tar both work.
# usage: fetch_day.sh YYYY-MM-DD OUT_FILE cmd [args…]   — cmd reads the tar on stdin and writes OUT_FILE's content on stdout.
# Exit 1 when no tag gave a non-empty OUT_FILE. Prints "TAG → N lines, B bytes" (B = archive size).
set -u
DAY=$1 OUT=$2; shift 2
D=${DAY//-/.}; Y=${D:0:4}
for n in prod-0 prod-1 prod-2 prod-0tmp prod-1tmp staging-0 mlatonly-0; do
  TAG=v$D-planes-readsb-$n; URL=https://github.com/adsblol/globe_history_$Y/releases/download/$TAG/$TAG.tar
  rm -f part.* "$OUT"
  # 27 Nov 2026 (audit item 56): the "does this part exist" checks retry on time-outs and 5xx (a 404 is not retried), so one failed check in the
  # middle of a split archive no longer ends the part list early and passes a cut-off day on as a complete one
  if curl -sfIL --retry 3 "$URL.aa" >/dev/null; then
    ok=1; for s in aa ab ac ad ae af ag ah; do
      curl -sfIL --retry 3 "$URL.$s" >/dev/null || break
      curl -sfL --retry 3 -o "part.$s" "$URL.$s" || { ok=0; break; }
    done
    [ "$ok" = 1 ] && cat part.* | "$@" > "$OUT" || rm -f "$OUT"
  elif curl -sfIL --retry 3 "$URL" >/dev/null; then
    curl -sfL --retry 3 -o part.tar "$URL" && "$@" < part.tar > "$OUT" || rm -f "$OUT"
  fi
  B=$(cat part.* 2>/dev/null | wc -c); rm -f part.*
  [ -s "$OUT" ] && { echo "$TAG → $(wc -l < "$OUT") lines, $B bytes"; exit 0; }
done
echo "::error::no complete archive for $DAY (adsb.lol may not have published it yet)"; exit 1
