#!/usr/bin/env bash
# Measure real decode throughput of a model AS SERVED TO YOU.
# Published leaderboard tok/s reflect the vendor's own endpoint; your gateway,
# region, quantization and batching differ. Measure, don't assume.
#
# Method: differential. rate = (tok_long - tok_short) / (wall_long - wall_short)
# Subtracting cancels harness startup, prefill and TTFT. Requires a LARGE token
# delta, otherwise startup jitter swamps the signal -- refuses to report if so.
set -Eeuo pipefail
IFS=$'\n\t'

REPS="${REPS:-3}"
SHORT_N="${SHORT_N:-20}"
LONG_N="${LONG_N:-1500}"
MAX_SPREAD_PCT="${MAX_SPREAD_PCT:-25}"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/omo-bench.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

command -v opencode >/dev/null || { echo "FATAL: opencode not on PATH" >&2; exit 127; }
command -v python3  >/dev/null || { echo "FATAL: python3 not on PATH" >&2; exit 127; }
[ "$#" -ge 1 ] || { echo "usage: $0 <provider/model[:variant]> [more...]" >&2; exit 64; }

now_ms() { python3 -c 'import time;print(int(time.time()*1000))'; }

probe() { # model variant n outfile -> "<wall_ms> <out_tok>"
  local model="$1" variant="$2" n="$3" out="$4" extra=() t0 t1
  [ -n "$variant" ] && extra=(--variant "$variant")
  t0="$(now_ms)"
  opencode run --dir "$WORKDIR" -m "$model" "${extra[@]}" --format json \
    "Output the integers from 1 to ${n}, one per line, with no other text." \
    >"$out" 2>/dev/null || true
  t1="$(now_ms)"
  python3 - "$out" "$t0" "$t1" <<'PY'
import json,sys
path,t0,t1=sys.argv[1],int(sys.argv[2]),int(sys.argv[3])
tok=None; err=None
try:
    for line in open(path):
        line=line.strip()
        if not line: continue
        d=json.loads(line)
        if d.get("type")=="error": err=str(d.get("error"))[:120]
        if d.get("type")=="step_finish": tok=d["part"]["tokens"].get("output")
except Exception as e: err=f"parse:{e}"
print(f"{t1-t0} {tok if tok is not None else -1} {err or '-'}")
PY
}

printf '%-42s %-8s %-9s %-9s %s\n' MODEL MEDIAN SPREAD% REPS VERDICT
printf '%s\n' "------------------------------------------------------------------------------------"
for spec in "$@"; do
  model="${spec%%:*}"; variant=""
  [ "$spec" != "$model" ] && variant="${spec##*:}"
  rates=()
  for rep in $(seq 1 "$REPS"); do
    IFS=' ' read -r sw st _ < <(probe "$model" "$variant" "$SHORT_N" "$WORKDIR/s$rep")
    IFS=' ' read -r lw lt _ < <(probe "$model" "$variant" "$LONG_N"  "$WORKDIR/l$rep")
    [ "$st" -gt 0 ] 2>/dev/null || continue
    [ "$lt" -gt 0 ] 2>/dev/null || continue
    dtok=$(( lt - st )); dwall=$(( lw - sw ))
    [ "$dtok" -gt 0 ] && [ "$dwall" -gt 0 ] || continue
    rates+=( "$(python3 -c "print(round($dtok/($dwall/1000),2))")" )
  done
  if [ "${#rates[@]}" -eq 0 ]; then
    printf '%-42s %-8s %-9s %-9s %s\n' "$spec" "-" "-" "0" "FAILED (no valid samples)"
    continue
  fi
  python3 - "$spec" "$MAX_SPREAD_PCT" "${rates[@]}" <<'PY'
import sys, statistics as st
spec, maxspread, *vals = sys.argv[1:]
v=[float(x) for x in vals]; med=st.median(v)
spread = (max(v)-min(v))/med*100 if med else 999
ok = spread <= float(maxspread) and len(v) >= 2
verdict = "OK" if ok else f"UNRELIABLE (spread>{maxspread}%) - raw: {v}"
shown = f"{med:.1f}" if ok else "n/a"
print(f"{spec:<42} {shown:<8} {spread:<9.1f} {len(v):<9} {verdict}")
PY
done
