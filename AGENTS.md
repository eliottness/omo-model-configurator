# AGENTS.md — read this before touching any OMO config

This repository is a **runbook plus tooling for auditing and upgrading
[oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent) (OMO) model
configuration** — deciding, per agent and per category, whether a newer model is
a safe swap.

---

## START HERE — what you were asked for

Match the user's request to a mode. **If in doubt, use DRY RUN.**

| The user said something like | Mode | You must |
|---|---|---|
| "dry run", "dry-run this", "audit my config", "review my models", "what should I upgrade", or just pasted this repo's URL | **DRY RUN** (default) | Produce the proposal table. **Change no files.** |
| "apply it", "do it", "make the change", "upgrade my config" *after* seeing a table | **APPLY** | Back up, edit, re-verify. |

**DRY RUN is the default.** If the user has not seen a proposal table yet, you
are in DRY RUN, even if they used the word "upgrade".

> **"Dry run" here means "propose without editing".** It does **not** mean
> `bunx oh-my-openagent config migrate --dry-run`. That command previews a
> deprecated-key rewrite and is **not part of this workflow**. Do not run it, and
> do not run any `config migrate` unless the user explicitly asks for a key
> migration as a separate task.

## The deliverable

**Both modes end in one artifact: a per-slot proposal table.** A DRY RUN that
does not produce this table has not been done, no matter how many commands ran.

One row per agent and per category in the user's config — not per model, not a
summary. Copy this shape:

| Slot | Current model | Prompt family | Proposed model | Prompt family | AAII | Cost/task | Verdict |
|---|---|---|---|---|---|---|---|
| `agent:sisyphus` | `prov/model-a` | `glm-5-2` | `prov/model-b` | `glm-5-2` | 82 → 89 | $0.42 → $0.31 | **swap** — same family, cheaper, +7 |
| `agent:oracle` | `prov/model-c` | `default` | `prov/model-d` | **`fallback`** | 88 → 93 | $1.10 → $0.90 | **blocked** — candidate lands in `fallback` |
| `category:deep` | `prov/model-e` | `gpt` | — | — | — | — | **keep** — no candidate beats it on prompt fit |

Rules for the table:

- **Every slot in the config gets a row**, including ones you are not proposing
  to change. Verdict `keep` is a result, not an omission.
- `Prompt family` comes from `validate_prompt_match.py`, not from a guess.
- A candidate resolving to **`fallback` is `blocked`**, regardless of price or
  score. Say so; do not quietly drop it and pick another.
- Anything you could not measure is `unknown`, never a plausible-looking number.

Below the table, list explicitly: what you could not verify, and any slot where
the user's stated constraints ("keep X") conflict with a candidate.

---

## MANDATE 1 — Read the agent/model matching guide FIRST

Before proposing a single model change, read the upstream guide:

```bash
curl -fsSL https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/refs/heads/dev/docs/guide/agent-model-matching.md
```

Rendered version: <https://omo.dev/docs#agent-model-matching>

**Use `curl`, not a web-fetch tool.** The rendered docs page truncates and
summarizes; fetching it through a summarizing tool silently drops the per-agent
fallback chains, the supported-model set, and the safe-vs-dangerous override
table — which are exactly the parts you need. The guide states this itself.

What that guide establishes, and what you must not contradict:

- Each agent has its own hardcoded fallback chain. **There is no global model
  priority list.**
- The orchestrator agent is only maintainer-verified on a narrow, explicitly
  listed set of models. Off-list models are not merely unproven — they can break
  at the next upstream patch with no warning.
- Some agents have no cross-family fallback at all. Losing one provider disables
  them outright rather than degrading them.

## MANDATE 2 — Read OMO's source, because prompt selection is model-NAME matching

OMO does not feed every model the same system prompt. It picks a prompt **by
pattern-matching the model name**, first-match-wins. A model that matches no
pattern does not error — it silently receives a generic `fallback` prompt that is
not tuned for it.

So: **a new model ID is not "configured" until you have verified which prompt it
resolves to.**

Read these, at a pinned commit so your reasoning is reproducible:

```bash
git clone --depth 1 --branch dev https://github.com/code-yeongyu/oh-my-openagent.git
# reference commit for the notes in docs/prompt-families.md:
# 4480fd41ab26ceea0e4bfd1584d495b748b95dfa
```

| What | Where |
|---|---|
| Prompt-family dispatch (first-match-wins, ends in `fallback`) | `packages/omo-opencode/src/agents/sisyphus-agent-factory.ts` |
| The model-name detectors themselves | `packages/model-core/src/model-family-detectors.ts` |
| Variant selection for other prompt tables | `packages/prompts-core/src/variant-resolver.ts` |
| Per-agent hardcoded fallback chains | `packages/model-core/src/agent-model-requirements.ts` |
| Per-category hardcoded chains | `packages/model-core/src/category-model-requirements.ts` |
| Resolution precedence | `packages/model-core/src/model-resolution-pipeline.ts` |
| Hard agent/model guard hooks | `no-sisyphus-gpt`, `no-hephaestus-non-gpt` (see `docs/config-surface.md`) |

Model names are matched in **three** places, not one: prompt selection, guard
hooks that refuse a pairing outright, and capability heuristics.
`docs/config-surface.md` covers the other two.

See `docs/prompt-families.md` for the dispatch table and the known
pattern-matching landmines (loose substring matches, ordering hazards, and
version collapse).

---

## The runbook

Steps 1-7 are DRY RUN and **edit nothing**. Run them in order. Every step has a
command; if you are not running a command, you are not doing the step.

### 1. Locate the config and enumerate the slots

```bash
# where is the config?
ls -l ~/.omo/omo.jsonc || find ~ -maxdepth 4 -name 'omo.json*' 2>/dev/null

# list every agent and category slot it configures
python3 - <<'EOF'
import json, pathlib, re
raw = (pathlib.Path.home() / ".omo/omo.jsonc").read_text()
body = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("//"))
cfg = json.loads(re.sub(r",(?=\s*[}\]])", "", body))
oc = cfg.get("[opencode]", {})
for kind, label in (("agents", "agent"), ("categories", "category")):
    for name in oc.get(kind) or {}:
        print(f"{label}:{name}")
EOF
```

**This list is your table's rows.** Every one gets a row, and you own all of
them until the user says otherwise.

### 2. Establish what the user can actually reach

```bash
opencode models
opencode auth list
```

A model appearing in a catalogue does **not** mean it is entitled. If a candidate
is not clearly reachable, ask — do not assume.

### 3. Get real capability and price data — **mandatory, do not skip**

This is the step most often skipped. Without it you have no basis for a
proposal, and the table cannot be filled in.

```bash
scripts/scrape_leaderboard.sh --setup     # first time only: creates the venv
scripts/scrape_leaderboard.sh             # -> vendor/aa-scraper/data/leaderboard.csv
wc -l vendor/aa-scraper/data/leaderboard.csv
```

Needs network. If it fails, **say so and stop** — do not proceed on remembered
model rankings, and do not substitute your own impressions of which model is
better. Read `docs/methodology.md` before quoting any column from this CSV.

### 4. Join the leaderboard against the user's config

```bash
python3 scripts/match_config.py \
  --config ~/.omo/omo.jsonc \
  --leaderboard vendor/aa-scraper/data/leaderboard.csv
```

Output is one row per configured slot — the **current** half of your table. A
`not-benchmarked` row is information, not an error.

### 5. Validate prompt routing for every current and candidate model

Run this for each model you list in the table, both sides:

```bash
python3 scripts/validate_prompt_match.py <provider>/<model> --explain
```

Exit code `1` means the model lands in `fallback`. **That is a blocker, not a
warning** — record it as `blocked` and tell the user.

### 6. Lint the config, statically and via OMO's own diagnostics

```bash
python3 scripts/lint_omo_config.py ~/.omo/omo.jsonc
python3 scripts/doctor_check.py --version <pinned-version> --strict
```

Pin the version so the report is reproducible. Some `doctor` findings are routine
false positives — the wrapper separates those out and prints the command that
proves it. Read `docs/known-issues.md` before acting on one.

Deprecated-key findings are **reported, not fixed** here. Fixing them is a
separate task the user must ask for.

### 7. Optional, only when relevant

```bash
python3 scripts/check_tool_schema.py --file <tools.json>   # switching provider family
scripts/bench_throughput.sh <provider>/<model>[:variant]   # if latency matters
```

### 8. Present the table — and in DRY RUN, stop here

Emit the proposal table from **The deliverable** above, plus the list of things
you could not verify. Then stop and wait. **Do not edit the config in DRY RUN,
even if every check passed.**

### 9. APPLY — only after the user approves a specific table

1. **Back up the config and verify the backup:**
   ```bash
   cp ~/.omo/omo.jsonc ~/.omo/omo.jsonc.bak-$(date +%Y%m%dT%H%M%S)
   diff ~/.omo/omo.jsonc ~/.omo/omo.jsonc.bak-*   # must be empty
   ```
2. Make the smallest edit that achieves the approved rows.
3. Re-run steps 4-6 and **diff the findings against the backup**, so you can
   prove which findings you introduced and which pre-existed:
   ```bash
   python3 scripts/doctor_check.py --version <pinned> --from-file <(...)  # or against the backup
   ```
4. Verify at least one changed model with a live call:
   ```bash
   opencode run -m <provider>/<model> --format json "reply with exactly: OK"
   ```

## Before you claim you are done

- [ ] Mandate 1 read via `curl` (not a summarizing fetch).
- [ ] Every slot from step 1 has a row in the table.
- [ ] `scrape_leaderboard.sh` actually ran, or you stated it failed and stopped.
- [ ] Every model in the table has a prompt family from
      `validate_prompt_match.py`, and every `fallback` is marked `blocked`.
- [ ] Unverifiable values are `unknown`, not estimates.
- [ ] In DRY RUN: no file was modified. Confirm it.

## Rules for the change itself

- **Never silently reorder or remove a model the user asked you to keep.** Prove
  it: count occurrences before and after and show that they match.
- Prefer the smallest change that achieves the stated goal.
- A model being cheaper and scoring higher on a leaderboard is **not** sufficient
  justification if it resolves to a `fallback` prompt. Prompt fit beats benchmark
  deltas.
- Report what you could not verify. Do not present an unmeasured number as
  measured.
