#!/usr/bin/env bash
# Run the vendored Artificial Analysis scraper and report where the CSV landed.
# Requires network access and a one-time dependency install (see --help).
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRAPER="$ROOT/vendor/aa-scraper"

usage() {
  cat <<'USAGE'
scrape_leaderboard.sh - scrape the Artificial Analysis model leaderboard to CSV

  usage: scrape_leaderboard.sh [--setup] [--out <dir>]

    --setup   create vendor/aa-scraper/.venv, install requirements and the
              Playwright Chromium browser, then exit
    --out     directory to copy the resulting CSV into

First run:
    scripts/scrape_leaderboard.sh --setup
    scripts/scrape_leaderboard.sh

Output columns include: Model, Artificial Analysis Intelligence Index,
Cost per Task USD, Input/Output Price USD/1M Tokens, Median Tokens/s.
Feed the CSV to scripts/match_config.py.
USAGE
}

OUT_DIR=""; DO_SETUP=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --setup)   DO_SETUP=1; shift ;;
    --out)     OUT_DIR="${2:?--out needs a directory}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 64 ;;
  esac
done

[ -d "$SCRAPER" ] || { echo "FATAL: vendored scraper missing at $SCRAPER" >&2; exit 2; }
command -v python3 >/dev/null || { echo "FATAL: python3 not on PATH" >&2; exit 127; }
VENV="$SCRAPER/.venv"

if [ "$DO_SETUP" -eq 1 ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$SCRAPER/requirements.txt"
  "$VENV/bin/python" -m playwright install chromium
  echo "setup complete: $VENV"
  exit 0
fi

[ -x "$VENV/bin/python" ] || { echo "FATAL: not set up. Run: $0 --setup" >&2; exit 3; }
( cd "$SCRAPER" && "$VENV/bin/python" src/main.py )
CSV="$SCRAPER/data/leaderboard.csv"
[ -f "$CSV" ] || { echo "FATAL: scraper produced no CSV at $CSV" >&2; exit 4; }
rows="$(( $(wc -l < "$CSV") - 1 ))"
echo "scraped $rows rows -> $CSV"
if [ -n "$OUT_DIR" ]; then
  mkdir -p "$OUT_DIR" && cp "$CSV" "$OUT_DIR/" && echo "copied -> $OUT_DIR/leaderboard.csv"
  if [ -f "$CSV.manifest.json" ]; then
    cp "$CSV.manifest.json" "$OUT_DIR/leaderboard.csv.manifest.json"
  fi
fi
