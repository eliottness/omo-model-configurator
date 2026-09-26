# OMO model audit and upgrade runbook

## Scope and modes

A model audit defaults to **DRY RUN**: produce local reports without editing the
user's OMO configuration, agent settings, credentials, or running sessions.
Local cache/report creation is allowed. Only apply a specific reviewed proposal
when the user authorizes it. A request to fix this repository is repository
maintenance, not permission to upgrade the user's live OMO configuration.

Do not run `config migrate` during this workflow. Deprecated-key findings are
reported, not fixed; migration is a separate user request.

**AA measurements, exports, HTML, screenshots, manifests, local reports, and
user configs must never be committed or uploaded.** Commit source, documentation,
and clearly synthetic fixtures only. Keep outputs under ignored `data/` or
`audit-output/` and run the scrub gate before committing.

## The deliverable

Include every active configured agent/category, the explicit main-session
selection, and all ordered fallback entries. Group entries by slot; give each
slot a `keep`, `swap`, or `blocked` verdict and its reason. Show current and
proposed IDs, their actual edition-specific preset evidence, AA measurements,
qualifiers, estimates, and exact edit paths. Keep inactive harness findings
separate. Do not confuse an active config view with an observed live selection.

A missing selected score is not proof of missing data. Distinguish an unresolved
effort, an absent input row, an unpublished cell, an approximate effort, and a
base-model proxy. Expose the available rows when effort is unresolved. Never
invent a value or label a failed join as an unbenchmarked model.

## Runbook

### 1. Read the upstream guide and identify the runtime

```bash
curl -fsSL https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/refs/heads/dev/docs/guide/agent-model-matching.md
omo --version
# For an OpenCode deployment instead:
opencode --version
```

Read the full guide and pin the applicable source version. Native OMO and
OpenCode do not share one universal prompt-selection contract. Native source
inspection uses the installed engine; historical OpenCode notes are not native
authority. Each role has its own model requirements and fallback chain.

### 2. Collect all model statuses and expanded metrics

```bash
scripts/scrape_leaderboard.sh --setup  # first time only
scripts/scrape_leaderboard.sh
```

The models route uses `?status=all`, not `?deprecation=all`. Confirm the UI's
Status: All state when investigating coverage. A failed fetch, parse, or write
must stop the workflow; an existing CSV is not proof the refresh succeeded.
Keep the CSV and its matching manifest together, check collection time and hash,
and read `docs/methodology.md` before comparing numbers.

### 3. Generate the audit and explicit proposal

```bash
python3 scripts/audit_config.py audit \
  --config ~/.omo/omo.jsonc \
  --leaderboard vendor/aa-scraper/data/leaderboard.csv \
  --harness auto --output audit-output
```

Use `--profile NAME` for a selected profile overlay, `--models-path PATH` for
native custom providers, and repeated `--replace provider/old=provider/new` to
propose replacements. Auto prefers native when both editions are installed;
select OpenCode explicitly when appropriate. Inspect `report.md`, `report.json`,
and `plan.json` locally. The tool does not choose upgrade candidates for you.

Effective overrides merge shared, legacy `[senpi]`, canonical `[native]`, then
selected profile layers. OpenCode uses only shared and its own layers. Arrays
replace rather than concatenate, so chain order must survive unchanged. The
inventory is explicit overrides, not a simulation of all runtime-built-in
chains, catalog aliases, or host command-line state.

### 4. Verify runtime support and diagnostics

```bash
python3 scripts/validate_prompt_match.py provider/model --harness native --role deep-low --json
python3 scripts/lint_omo_config.py ~/.omo/omo.jsonc --harness native --json
python3 scripts/doctor_check.py --harness native --version VERSION --json
# For OpenCode, use its relevant role and pin its package version:
python3 scripts/validate_prompt_match.py provider/model --harness opencode --agent sisyphus --explain
python3 scripts/doctor_check.py --harness opencode --version VERSION --strict
```

Replace VERSION with the installed native product version or intended OpenCode
package pin. Native validation checks registry admission, installed preset,
and capabilities. Credentials and live entitlement are not probed. Search/read
utility roles may legitimately use the default preset: never apply Sisyphus's
orchestrator gate to every role. A role's prompt suitability still needs review.

The OpenCode detector is a pinned historical snapshot; verify changed runtime
source rather than treating a stale detector as a current compatibility oracle.
Cache warnings remain suspected until evidence from the same harness confirms
registry admission. Even confirmation does not prove entitlement.

### 5. Present the proposal; apply only approved changes

In dry run, present all slots and limitations and stop without touching the
live setup. Preserve any models the user asked to keep. AA data stays local.

Use `audit_config.py apply --plan audit-output/plan.json --approve` with an
absolute `--verify-command`; see README for the command contract and optional
private credential copying. Verification runs against a candidate in a temporary
HOME and working directory before any real config write. Require the checker
to validate the intended model response/tool behavior. Exit zero alone is not
proof of live entitlement unless the checker actually tested it.

The baseline and dataset hashes must match. Apply verifies a backup, edits only
approved JSONC string values, preserves comments and permissions, and rejects
unexpected candidate migration. A failed preflight leaves the real config
untouched. Review the local receipt and resulting diff; report pre-existing
warnings separately. Never silently reorder chains or modify inactive blocks.

## Repository maintenance checks

```bash
python3 -m pytest tests/ -q
(cd vendor/aa-scraper && .venv/bin/python -m pytest tests/ -q)
bash scripts/scrub_check.sh
git diff --check
```

Core Python tooling must remain standard-library only. Use synthetic fixtures
for regressions and verify the affected CLI surface. Review staged filenames
and content for AA data and user-specific artifacts before any authorized push.
