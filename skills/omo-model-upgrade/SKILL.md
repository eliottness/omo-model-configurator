---
name: omo-model-upgrade
description: Audit or upgrade native OMO/Senpi and OpenCode model configurations after model releases, or when asked to review models, dry-run an upgrade, or change omo.jsonc. Resolve the active harness, preserve ordered chains, use local AA evidence and installed runtime metadata, and present a per-slot proposal before any approved apply. Not for unrelated model benchmarking or non-OMO configuration.
---

# OMO model upgrades

Read `../../AGENTS.md` relative to this skill and execute its runbook from the
repository root. Read `../../README.md` for command syntax and limitations.
Do not reproduce an older inline config parser or assume `[opencode]` is the
active configuration.

1. Establish the user's requested mode. Dry run may create local reports but
   never changes OMO config, settings, credentials, or live sessions. A request
   to maintain the configurator itself does not authorize changing the live setup.
2. Read the upstream matching guide and identify the edition and installed
   version. Resolve shared, harness, and selected-profile layers. Inventory the
   explicit main selection and ordered agent/category chains; keep inactive
   harnesses separate.
3. Collect AA's models table with `status=all` and expanded columns. Stop on
   collection failure. Verify the CSV/manifest hash and collection time. Never
   infer unavailable measurements from a failed identity or effort join.
4. Run `audit_config.py audit`. Preserve evaluation qualifiers and estimates;
   show available effort rows when the effective effort is unspecified. Fast
   proxy measurements are not measured Fast prices or throughput. Pro is a
   separate identity.
5. Probe the installed native registry/preset/capabilities for native roles.
   Do not apply OpenCode's historical Sisyphus gate universally. Registry,
   credentials, entitlement, and prompt suitability are separate evidence.
   Dispatch doctor to the correct edition and pin its version.
6. Present every slot with current/proposed IDs, evidence, and keep/swap/blocked
   verdicts. Explain unverified items precisely. Do not manufacture rankings,
   numeric deltas, defaults, catalog resolutions, or live-session observations.
7. Apply only an approved hash-bound plan using an isolated verification command
   that checks the real behavior. Preserve comments, inactive blocks, and ordered
   chains. Report pre-existing diagnostics; deprecated-key migration is separate.

**Never commit or upload AA measurements, caches, captures, manifests, local
reports, or user configurations.** Only source, docs, and synthetic fixtures may
be distributed. Use ignored output locations and the scrub gate.
