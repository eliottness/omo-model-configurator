#!/usr/bin/env bash
# Gate: no personal / organisation-specific strings may reach this public repo.
# Exits 0 only when the tree is clean.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIST="$ROOT/forbidden_strings.txt"
[ -f "$LIST" ] || { echo "FATAL: $LIST missing" >&2; exit 2; }
hits="$(grep -RIn --fixed-strings --file="$LIST" \
          --exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=.pytest_cache \
          --exclude="forbidden_strings.txt" --exclude="scrub_check.sh" \
          "$ROOT" || true)"
if [ -n "$hits" ]; then
  echo "SCRUB GATE FAILED - forbidden strings present:" >&2
  echo "$hits" >&2
  exit 1
fi
echo "SCRUB GATE PASSED: no forbidden strings in $ROOT"
