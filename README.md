# omo-model-configurator

Tooling and a written procedure for upgrading an
[oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent) (OMO) model
configuration — safely, with evidence, and without silently downgrading your
agents.

## Point an agent at it

```
Do a dry run of this: https://github.com/eliottness/omo-model-configurator
```

The agent follows [`AGENTS.md`](AGENTS.md) and should come back with **a table,
one row per agent and per category in your config** — current model, the prompt
family it actually resolves to, a proposed model, and a `swap` / `keep` /
`blocked` verdict. A dry run changes nothing on disk.

If an agent instead starts running `oh-my-openagent config migrate`, or reports
`doctor` output with no comparison table, it has not followed the runbook — the
required output is spelled out in [`AGENTS.md`](AGENTS.md) under
"The deliverable".

## Why this exists

Swapping a model in OMO looks like a config edit. It isn't.

**OMO chooses which system prompt to feed a model by pattern-matching the model
name.** The dispatch is first-match-wins and terminates in a generic `fallback`
prompt. So a newer, cheaper, higher-scoring model can quietly end up running a
prompt that was never tuned for it — no error, no warning, just worse behaviour
a few tool calls in.

Model names are matched in **three** places: prompt selection, guard hooks that
refuse a pairing outright, and capability heuristics that guess settings for
models the capability cache does not know. A benchmark win is not sufficient
evidence that a swap is safe.

On top of that, the leaderboard numbers people reach for are easy to misread:
throughput figures are measured on the vendor's own endpoint and do not describe
your deployment, and the hallucination metric rewards abstaining rather than
knowing.

This repo makes both problems checkable.

## The two mandates

Any agent using this repo must, before changing anything:

1. **Read the upstream matching guide** — via `curl`, because the rendered page
   truncates:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/refs/heads/dev/docs/guide/agent-model-matching.md
   ```
2. **Validate prompt routing from OMO's source** for every candidate model:
   ```bash
   python3 scripts/validate_prompt_match.py <provider>/<model> --explain
   ```
   Exit code `1` means the model resolves to `fallback`. That is a blocker.

Full reading order and the OMO source file map: [`AGENTS.md`](AGENTS.md).

## Scripts

All Python scripts are **standard-library only** — they run from a bare clone
with no `pip install`.

| Script | What it does |
|---|---|
| `scripts/validate_prompt_match.py` | Model ID -> resolved prompt family per agent. Warns on `fallback` / silent `default`. Exit 1 on fallback, so it works in CI. |
| `scripts/lint_omo_config.py` | Static config lint: deprecated `fallback_models`, invalid `reasoning` values, malformed IDs, duplicate/unreachable chain entries. |
| `scripts/doctor_check.py` | Runs `bunx oh-my-openagent@<version> doctor --json` and splits actionable findings from documented false positives, annotating each with the command that proves it. Version-pinnable for reproducibility; `--from-file` for offline use. |
| `scripts/match_config.py` | Joins your configured models against a scraped leaderboard, reasoning-tier aware. Reports unmatched models instead of dropping them. |
| `scripts/check_tool_schema.py` | Flags tool-schema constructs that break strict providers (non-string enums, union types, …). |
| `scripts/bench_throughput.sh` | Measures real decode throughput on *your* endpoint. Refuses to report when run-to-run spread is too high. |
| `scripts/scrape_leaderboard.sh` | Runs the vendored Artificial Analysis scraper to CSV. |
| `scripts/scrub_check.sh` | Repo hygiene gate: fails if machine/organisation-specific strings are present. |

## Docs

| Doc | Contents |
|---|---|
| [`docs/prompt-families.md`](docs/prompt-families.md) | The dispatch table, the detector landmines, and the two *different* prompt-selection mechanisms. |
| [`docs/methodology.md`](docs/methodology.md) | How to read Artificial Analysis columns without fooling yourself. |
| [`docs/config-surface.md`](docs/config-surface.md) | The config keys that actually affect model behaviour, the **three** places model names are matched (prompt, guard hooks, capability heuristics), and the two independent fallback systems. |
| [`docs/known-issues.md`](docs/known-issues.md) | Real breakages: Gemini tool-schema 400 (unresolved), `doctor` false positives, deprecated config keys. |

## Quick start

```bash
git clone https://github.com/eliottness/omo-model-configurator.git
cd omo-model-configurator

# 0. the full audit an agent runs, in order (edits nothing):
#      AGENTS.md -> "The runbook", steps 1-8

# 1. does a candidate model even get the right prompt?
#    this one exits 1: gpt-oss-120b has no Sisyphus branch, yet the variant
#    surfaces confidently match it as `gpt`
python3 scripts/validate_prompt_match.py exampleprovider/gpt-oss-120b --explain

# 2. lint an existing config, statically and via OMO's own diagnostics
python3 scripts/lint_omo_config.py examples/example-omo.jsonc
python3 scripts/doctor_check.py --version 4.19.4 --strict

# 3. get real leaderboard data (needs network, one-time setup)
scripts/scrape_leaderboard.sh --setup && scripts/scrape_leaderboard.sh

# 4. join it against your config
python3 scripts/match_config.py --config examples/example-omo.jsonc \
                                --leaderboard vendor/aa-scraper/data/leaderboard.csv
```

Tests (offline, no network):

```bash
python3 -m pytest tests/ -q
```

## What this repo does not claim

- **Prompt-family notes are pinned observations, not the source of truth.** They
  reflect OMO at `4480fd41ab26ceea0e4bfd1584d495b748b95dfa`. Re-verify against
  source; three GPT detector bodies in `validate_prompt_match.py` are marked
  INFERRED because they were not captured verbatim.
- **Known breakages, including one that is not root-caused, are in
  [`docs/known-issues.md`](docs/known-issues.md).**

## Licence

**GPL-3.0.** This repository vendors
[deyil/artificial-analysis-leaderboards-scraper](https://github.com/deyil/artificial-analysis-leaderboards-scraper)
(GPL-3.0) under `vendor/aa-scraper/`, pinned at
`99167bae89b203e427c48f04edcf7366eae04ef5`, which makes the combined work
GPL-3.0. Upstream's licence is preserved unmodified; local changes are documented
in [`vendor/aa-scraper/PATCHES.md`](vendor/aa-scraper/PATCHES.md). See
[`NOTICE`](NOTICE).
