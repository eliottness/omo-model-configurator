---
name: omo-model-upgrade
description: Use when upgrading, reviewing, or changing which models an oh-my-openagent (OMO) configuration uses - including "upgrade my OMO models", "what should I change in omo.jsonc", "is there a better model for my agents", "add <model> to my config", "review my agent model config", or after a provider ships a new model. Enforces reading the upstream agent-model matching guide first, then validating that each candidate model actually resolves to an intended prompt family in OMO's source rather than a silent fallback prompt. Not for editing non-OMO agent configs, and not for general model benchmarking questions unrelated to a config change.
---

# Upgrading an OMO model configuration

Changing a model in OMO is not a config edit — it is a prompt-routing decision.
OMO picks a system prompt by pattern-matching the model **name**, so a model that
matches nothing silently gets a generic fallback prompt. A "better" model on
paper can be a downgrade in practice.

Work through these phases in order. Do not skip to phase 4.

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
can. Run both. If `doctor` reports a deprecated key,
`bunx oh-my-openagent config migrate --dry-run` previews the rewrite.

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

## Phase 5 — Propose, then change

1. **Back up the config and verify the backup** before editing.
2. Present the proposed change per agent/category with a concrete reason —
   prompt family, capability, price, and what you could not verify.
3. Honour "keep X as-is" **mechanically**: count occurrences of X before and
   after and show they match. Do not rely on having been careful.
4. Prefer the smallest change achieving the goal.
5. Re-run `lint_omo_config.py` and `doctor_check.py` afterwards, and distinguish
   pre-existing findings from ones you introduced — run against the backup to
   prove which is which. Do not report a pre-existing warning as something you
   caused, or vice versa.
6. Verify at least one changed model with a live call.
