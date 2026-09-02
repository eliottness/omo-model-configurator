---
name: omo-model-upgrade
description: Use when upgrading, reviewing, auditing, or dry-running which models an oh-my-openagent (OMO) configuration uses - including "dry run my OMO config", "audit my models", "upgrade my OMO models", "what should I change in omo.jsonc", "is there a better model for my agents", "add <model> to my config", "review my agent model config", or after a provider ships a new model. Default mode is a no-edit audit that ends in a per-agent proposal table. Enforces reading the upstream agent-model matching guide first, then validating that each candidate model actually resolves to an intended prompt family in OMO's source rather than a silent fallback prompt. Not for editing non-OMO agent configs, and not for general model benchmarking questions unrelated to a config change.
---

# Upgrading an OMO model configuration

Changing a model in OMO is not a config edit — it is a prompt-routing decision.
OMO picks a system prompt by pattern-matching the model **name**, so a model that
matches nothing silently gets a generic fallback prompt. A "better" model on
paper can be a downgrade in practice.

## Phase 0 — Fix the mode and the output before running anything

**Default mode is DRY RUN: propose, edit nothing.** Only switch to APPLY after
the user approves a specific table you have already shown them.

> "Dry run" means "propose without editing". It is **unrelated** to
> `bunx oh-my-openagent config migrate --dry-run`, which previews a
> deprecated-key rewrite and is not part of this workflow.

**The deliverable in both modes is a per-slot proposal table** — one row per
agent and per category in the user's config, with current model, current prompt
family, proposed model, proposed prompt family, score and cost deltas, and a
verdict of `swap` / `keep` / `blocked`. The exact column layout and the rules for
filling it in are in `AGENTS.md` under "The deliverable". A run that produces no
table is not finished.

Enumerate the slots first, so you know how many rows you owe:

```bash
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

Work through the phases in order. **Phase 4 is mandatory — a proposal without
leaderboard data is a guess.**

## Phase 1 — Read the matching guide (mandatory, first)

```bash
curl -fsSL https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/refs/heads/dev/docs/guide/agent-model-matching.md
```

Use `curl`, not a summarizing web-fetch tool — the rendered page truncates and
drops the per-agent fallback chains and the safe/dangerous override table.

Extract and hold on to: each agent's documented primary and chain, the
maintainer-verified model set for the orchestrator, and which agents have no
cross-family fallback.

## Phase 2 — Establish what the user actually has

A model appearing in a catalogue is **not** proof of entitlement.

```bash
opencode models                    # what this install can address
opencode auth list                 # which providers are authenticated
python3 scripts/doctor_check.py --version <pinned-version>
```

`doctor_check.py` wraps `bunx oh-my-openagent@<version> doctor --json` and splits
real findings from documented false positives. **Pin the version** — check names
and wording change between releases, so an unpinned run is not reproducible.

Ask the user to confirm access to anything you intend to recommend. Recommending
an unavailable model wastes the whole exercise. Note that `doctor` can report a
working provider as unavailable — see `docs/known-issues.md` before treating a
warning as real.

## Phase 3 — Validate prompt routing (mandatory, before recommending)

For **every** candidate model:

```bash
python3 scripts/validate_prompt_match.py <provider>/<model> --explain
```

- Exit `1` = the model lands in `fallback`. **This is a blocker.** Say so.
- A match is not automatically the *right* match. Check `docs/prompt-families.md`
  for the ordering hazards and version-collapse behaviour.
- Prompt selection is only **one** of three model-name gates. Guard hooks
  (`no-sisyphus-gpt`, `no-hephaestus-non-gpt`) can refuse a pairing outright, and
  capability heuristics may guess settings for an unknown model. See
  `docs/config-surface.md` before assuming a pairing is viable.

Read the source yourself when the stakes are high — file map in `AGENTS.md`.

## Phase 4 — Get real data, not vibes

```bash
scripts/scrape_leaderboard.sh --setup     # first time only
scripts/scrape_leaderboard.sh
python3 scripts/match_config.py --config <omo.jsonc> --leaderboard <csv>
python3 scripts/lint_omo_config.py <omo.jsonc>          # static rules
python3 scripts/doctor_check.py --version <pinned> --strict   # what OMO itself reports
```

Static linting cannot see effective resolution or capability fallback; `doctor`
can. Run both.

`scrape_leaderboard.sh` needs network. If it fails, **say so and stop** — do not
fall back on remembered model rankings.

Deprecated-key findings are **reported here, not fixed**. Migrating keys
(`oh-my-openagent config migrate`) is a different task; do not run it as part of
an upgrade unless the user asks for it specifically.

Read `docs/methodology.md` before quoting any leaderboard column. In particular a
high non-hallucination rate usually means the model **abstains** more, not that
it knows more — decompose it before using it as an argument.

If throughput or latency matters, measure it. Leaderboard tok/s is measured on
the vendor's own endpoint and does not transfer to yours:

```bash
scripts/bench_throughput.sh <provider>/<model>[:variant]
```

If the user is moving an agent to a different provider family, check schema
compatibility first:

```bash
python3 scripts/check_tool_schema.py --file <tools.json>
```

## Phase 5 — Present the table, then stop

Emit the per-slot proposal table described in Phase 0, one row per slot, plus an
explicit list of what you could not verify. Give each row a concrete reason:
prompt family, capability, price.

**In DRY RUN you are done here. Change no files, even if every check passed.**
Wait for the user to approve specific rows.

## Phase 6 — Apply (only on explicit approval of a specific table)

1. **Back up the config and verify the backup** before editing:
   ```bash
   cp ~/.omo/omo.jsonc ~/.omo/omo.jsonc.bak-$(date +%Y%m%dT%H%M%S)
   diff ~/.omo/omo.jsonc ~/.omo/omo.jsonc.bak-*    # must be empty
   ```
2. Make the smallest edit achieving the approved rows.
3. Honour "keep X as-is" **mechanically**: count occurrences of X before and
   after and show they match. Do not rely on having been careful.
4. Re-run `lint_omo_config.py` and `doctor_check.py` afterwards, and distinguish
   pre-existing findings from ones you introduced — run against the backup to
   prove which is which. Do not report a pre-existing warning as something you
   caused, or vice versa.
5. Verify at least one changed model with a live call.
