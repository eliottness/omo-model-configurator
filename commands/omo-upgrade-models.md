---
description: Review and upgrade an oh-my-openagent model configuration, enforcing prompt-family validation before any change
---

Upgrade the user's oh-my-openagent (OMO) model configuration.

Follow the `omo-model-upgrade` skill in this repository, in order. The two
mandates in `AGENTS.md` are not skippable:

1. Read the upstream agent-model matching guide via `curl` (not a summarizing
   fetch tool) before proposing anything.
2. Validate that every candidate model resolves to an intended prompt family
   with `scripts/validate_prompt_match.py` before recommending it. A model that
   resolves to `fallback` is a blocker, not a footnote.

Then: establish real entitlement (`opencode models`, `opencode auth list`),
gather real data (`scripts/scrape_leaderboard.sh`, `scripts/match_config.py`,
`scripts/lint_omo_config.py`), measure throughput yourself if latency matters
(`scripts/bench_throughput.sh`), back up the config, and present the proposed
diff per agent with reasons before editing.

If the user says to keep a given model as-is, prove you did: count its
occurrences before and after and show they match.

$ARGUMENTS
