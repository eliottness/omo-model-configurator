# omo-model-configurator

Evidence-based OMO model audits and small, approved configuration changes for
native OMO/Senpi and OpenCode. Start with [AGENTS.md](AGENTS.md) for the runbook.

An audit reports each configured slot and its ordered fallback entries, the
main-session selection, benchmark evidence, and installed runtime support. It
does not change your OMO configuration or settings. Reports and collected AA
data stay local: **commit code, documentation, and synthetic fixtures only**.

## Quick start

Run from this repository's root:

```bash
# One-time scraper dependencies; core Python scripts need no pip dependencies.
scripts/scrape_leaderboard.sh --setup

# A failed collection exits nonzero; never treat an old CSV as a fresh result.
scripts/scrape_leaderboard.sh && \
python3 scripts/audit_config.py audit \
  --config ~/.omo/omo.jsonc \
  --leaderboard vendor/aa-scraper/data/leaderboard.csv \
  --harness auto --output audit-output
```

Inspect local `audit-output/report.md`, `report.json`, and `plan.json`.
For native custom providers, add `--models-path ~/.omo/agent/models.json`.
Use `--profile NAME` to select a configuration overlay. Auto-detection prefers
native OMO when both runtimes exist; pass `--harness opencode` to audit OpenCode.
The lower-level lint and legacy prompt-check commands retain their OpenCode
default for compatibility: always pass their harness explicitly.

To propose exact replacements, repeat `--replace provider/old=provider/new`.
This generates a plan; it does not select winners or edit the configuration.
The plan binds the configuration and leaderboard hashes, records raw edit
locations, and keeps inactive harness blocks and chain order intact.

## What changed about missing measurements

The models UI defaults to **Status: Current**, which hides older models that
still have measurements. The collector requests `?status=all`, verifies
**Status: All**, and expands the metric columns. A missing row means
`row-absent-from-input`, not that AA never measured the model.

Identity, effort, and evaluation policy are separate. `auto` does not mean
`max`; available benchmark variants remain in the JSON report when effort is
unresolved. `minimal`, non-reasoning qualifiers, and `with fallback` labels
are retained. Fast variants use a clearly labelled base-model proxy only when
no exact row exists; Pro is not silently collapsed into the base model.
Estimated cells retain their markers. AA throughput is not your endpoint's
throughput, and a base-model price is not a measured Fast-tier price.

## Runtime evidence, not a universal prompt regex

`runtime_probe.mjs` reads the installed native engine's registry, preset
resolver, and capability metadata without starting a session or making model
requests. It reports the engine version. Registry admission, credentials,
live entitlement, and role suitability are different checks: credentials and
live entitlement remain `not-probed` during an audit.

`validate_prompt_match.py --harness native --role ROLE` uses this evidence.
Read/search utility roles can legitimately use the default preset. OpenCode's
Sisyphus detector must not reject unrelated native roles. The OpenCode detector
is a **historical source snapshot**, not proof about an arbitrary installed
version; verify its relevant role against that version's source before applying.
See [prompt-families.md](docs/prompt-families.md).

`doctor_check.py --harness native` calls `omo doctor`;
`--harness opencode --version VERSION` calls the pinned OpenCode package.
A cache warning is suspected until matching registry evidence confirms it.
That confirmation still does not prove live entitlement.

## Approved apply

Apply only a reviewed plan. Supply an executable verification command whose
nonzero exit means failure; it runs once for each changed model, in a temporary
HOME and working directory containing the candidate configuration. Arguments
can contain `{model}` and `{config}`. Use absolute script paths because the
working directory is isolated.

```bash
python3 scripts/audit_config.py apply --plan audit-output/plan.json --approve \
  --verify-command /absolute/path/to/your-model-check '{model}' '{config}'
```

For an explicitly authorized live check, `--credentials-from ~/.omo/agent`
privately copies the supported agent credential/config files into that temporary
home. Nothing is copied by default. The command must validate the response and
any required tool call, not merely launch the model process. HOME isolation is
not an OS security sandbox; use a verification command you trust.

Verification failure or a runtime migration leaves the real config untouched.
A changed baseline or leaderboard refuses apply. Successful apply makes a
verified backup, changes only the planned JSONC string tokens, preserves comments
and permissions, and records a local receipt. It does not migrate deprecated keys.

## Tools and limits

All Python scripts in `scripts/` are **standard-library only**. The native
probe requires the installed native engine and Bun or Node. The vendored
browser scraper has its own isolated Python environment.

| Tool | Purpose |
|---|---|
| `audit_config.py` | Local report, hash-bound plan, isolated verification and approved apply |
| `match_config.py` | Ordered model/effort matching and available benchmark variants |
| `runtime_config.py`, `runtime_probe.mjs` | Effective override layers and installed native metadata |
| `validate_prompt_match.py` | Native preset inspection or historical OpenCode role checks |
| `lint_omo_config.py` | Active-harness config lint, separate inactive findings |
| `doctor_check.py` | Edition-correct diagnostics with command evidence |
| `check_tool_schema.py`, `bench_throughput.sh` | Tool-schema checks and endpoint-specific throughput |
| `scrape_leaderboard.sh` | All-model collection with local immutable cache and provenance |
| `scrub_check.sh` | Reject private strings, datasets, captures, and marked local reports |

The audit inventories explicit configuration overrides. It does not claim to
observe host CLI overrides, live session state, or every runtime-built-in chain.
Named model catalogs that are not literal provider/model IDs need separate
runtime resolution; do not invent their benchmark identity. See
[config-surface.md](docs/config-surface.md), [methodology.md](docs/methodology.md),
and [known-issues.md](docs/known-issues.md).

## Verification

```bash
python3 -m pytest tests/ -q
(cd vendor/aa-scraper && .venv/bin/python -m pytest tests/ -q)
bash scripts/scrub_check.sh
git diff --check
```

Fixtures contain invented measurements, never real AA exports. CSVs, manifests,
captures, and audit outputs are ignored and must not be force-added. A manifest
binds its CSV hash, source scope, collection time, headers, and row count. It
records a benchmark revision only when known; different revisions are not
implicitly comparable. Check the collection time rather than calling an old
but hash-valid cache fresh.

## Licence

**GPL-3.0.** This repository vendors
[deyil/artificial-analysis-leaderboards-scraper](https://github.com/deyil/artificial-analysis-leaderboards-scraper)
at `99167bae89b203e427c48f04edcf7366eae04ef5`. Its licence is preserved;
see [NOTICE](NOTICE) and [local patches](vendor/aa-scraper/PATCHES.md).
Collected AA data is not part of this distribution.
