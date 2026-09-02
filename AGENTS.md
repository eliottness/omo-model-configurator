# AGENTS.md — read this before touching any OMO config

You are about to change which model an [oh-my-openagent](https://github.com/code-yeongyu/oh-my-openagent)
(OMO) agent runs on. **Two mandates come first. They are not optional, and they are
not reorderable.** Skipping them is the difference between an upgrade and a silent
downgrade that looks fine for three tool calls and then falls apart.

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
hooks that refuse a pairing outright, and capability heuristics. `docs/config-surface.md`
covers the other two.

Then verify your candidate model mechanically:

```bash
python3 scripts/validate_prompt_match.py <provider>/<model> --explain
```

Exit code 1 means the model lands in `fallback`. **Treat that as a blocker, not a
warning**, and say so to the user rather than shipping it.

See `docs/prompt-families.md` for the dispatch table and the known
pattern-matching landmines (loose substring matches, ordering hazards, and
version collapse).

---

## Then, and only then

1. Establish what the user actually has access to — a model appearing in a
   catalogue does **not** mean it is entitled. Verify, and ask if unsure.
2. Get real capability/price data: `scripts/scrape_leaderboard.sh`.
3. Join it against the user's config: `scripts/match_config.py`.
4. Lint the config statically (`scripts/lint_omo_config.py`) **and** run OMO's own
   diagnostics, which is the only thing that reports how the config actually
   resolves:
   ```bash
   python3 scripts/doctor_check.py --version <pinned-version> --strict
   ```
   Pin the version so the report is reproducible. Some `doctor` findings are
   routine false positives — the wrapper separates those out and prints the
   command that proves it. Read `docs/known-issues.md` before acting on one.
5. If the user is switching provider families, check schema compatibility:
   `scripts/check_tool_schema.py`.
6. Measure throughput yourself if it matters: `scripts/bench_throughput.sh`.
   Published vendor figures are measured on the vendor's own endpoint — see
   `docs/methodology.md`.
7. **Back up the config before editing it**, and verify the backup.

## Rules for the change itself

- **Never silently reorder or remove a model the user asked you to keep.** Prove
  it: count occurrences before and after and show that they match.
- Prefer the smallest change that achieves the stated goal.
- A model being cheaper and scoring higher on a leaderboard is **not** sufficient
  justification if it resolves to a `fallback` prompt. Prompt fit beats
  benchmark deltas.
- Report what you could not verify. Do not present an unmeasured number as
  measured.
