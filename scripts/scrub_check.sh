#!/usr/bin/env bash
# Gate: no personal / organisation-specific strings may reach this public repo.
# Scans exactly what could be published - tracked files, plus untracked files
# that are not gitignored - so a local .venv or a scraped data/ directory
# cannot fail the gate on strings that were never going to ship.
# Exits 0 only when the tree is clean.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIST="$ROOT/forbidden_strings.txt"
[ -f "$LIST" ] || { echo "FATAL: $LIST missing" >&2; exit 2; }
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 \
  || { echo "FATAL: $ROOT is not a git repository" >&2; exit 2; }
cd "$ROOT"
files=()
while IFS= read -r -d '' file; do
  case "$file" in
    forbidden_strings.txt | scripts/scrub_check.sh) continue ;;
    data/* | */data/* | audit-output/* | */audit-output/* | snapshots/* | */snapshots/* | captures/* | */captures/* | .audit/* | */.audit/* | *.csv | *.har | *.manifest.json | *.snapshot.json)
      echo "SCRUB GATE FAILED - local-only data artifact: $file" >&2
      exit 1
      ;;
  esac
  files+=("$file")
done < <(git ls-files -z --cached --others --exclude-standard)
hits=""
if [ "${#files[@]}" -gt 0 ]; then
  local_reports="$(grep -IlE '^<!-- LOCAL_ONLY_AA_DATA -->$|^[[:space:]]*"local_only":[[:space:]]*true[,[:space:]]*$' -- "${files[@]}" || true)"
  if [ -n "$local_reports" ]; then
    echo "SCRUB GATE FAILED - local-only report data: $local_reports" >&2
    exit 1
  fi
  hits="$(grep -In --fixed-strings --file="$LIST" -- "${files[@]}" || true)"
fi
if [ -n "$hits" ]; then
  echo "SCRUB GATE FAILED - forbidden strings present:" >&2
  echo "$hits" >&2
  exit 1
fi
echo "SCRUB GATE PASSED: no forbidden strings in $ROOT"
