# The config surface that actually affects model behaviour

Notes from OMO's own `docs/reference/features.md` and `docs/reference/cli.md`
(pinned `4480fd41ab26ceea0e4bfd1584d495b748b95dfa`). This page covers only what
matters when you change a model — it is not a full config reference.

## Model-name matching happens in THREE places, not one

`docs/prompt-families.md` covers prompt selection. There are two more gates, and
both are also keyed on the model **name**:

### 1. Prompt family selection
First-match-wins dispatch, falls through to a generic `fallback`. See
`docs/prompt-families.md`.

### 2. Hard agent/model guards (hooks)

| Hook | Effect |
|---|---|
| `no-sisyphus-gpt` | Prevents Sisyphus from running on incompatible GPT models |
| `no-hephaestus-non-gpt` | Prevents Hephaestus from running on **non**-GPT models |

These do not degrade quietly — they **refuse**. Hephaestus is GPT-only by
construction, and Sisyphus rejects some GPT models outright. So "this model
scores higher" is irrelevant if a guard hook blocks the pairing. There is an
`allow_non_gpt_model` escape on the Hephaestus agent schema; treat overriding a
guard as a deliberate, tested decision.

### 3. Capability heuristics
Model capabilities are models.dev-backed with a refreshable cache. When exact
metadata is unavailable OMO falls back to **name-pattern heuristics** to guess
capabilities. A brand-new model can therefore be driven with guessed settings.

```bash
bunx oh-my-openagent refresh-model-capabilities   # update the cache
bunx oh-my-openagent doctor                       # shows compatibility-fallback warnings
```

`doctor` explicitly surfaces "warnings when configured models rely on
compatibility fallback". Read those — they are the capability analogue of the
prompt `fallback`.

## Two independent fallback systems

Do not conflate them:

| System | Trigger | Behaviour |
|---|---|---|
| **model-fallback** | proactive | chooses the chain up front in chat params |
| **runtime-fallback** | reactive | switches models *after* a runtime failure (429/5xx, missing API key, provider retry signals) |

A chain entry can therefore be exercised either before any request or only after
one fails. A dead rung may sit unnoticed until the primary errors — which is why
a linter that only checks the primary is insufficient.

Note that `runtime-fallback`'s `message.updated` retry-signal detection requires
`timeout_seconds > 0`.

## Chain entry forms

Chains accept **both** bare strings and objects, and objects may tune more than
the model name:

```jsonc
{
  "agents": {
    "<agent>": {
      "fallback_models": [
        "<provider>/<model>",
        { "model": "<provider>/<model>", "variant": "high" },
        { "model": "<provider>/<model>",
          "thinking": { "type": "enabled", "budgetTokens": 64000 } }
      ]
    }
  }
}
```

`variant` and `reasoning` are both accepted by the schema. Upstream examples use
`variant`; the enum for `reasoning` is
`off | minimal | low | medium | high | xhigh | max | auto`.

**`fallback_models` is deprecated in favour of `models`.** `doctor` reports it
under its Deprecated Reasoning Keys group, and
`bunx oh-my-openagent config migrate` can rewrite it (`--dry-run` first). That
is a separate task from a model upgrade, and its `--dry-run` is unrelated to a
dry run of the workflow in `AGENTS.md`.

## Keys worth knowing when changing models

| Key | Why it matters here |
|---|---|
| `categories.<name>.warn_unavailable` | suppress or emit unavailable-chain notices per category |
| `categories.<name>.disable` | excludes the category from delegation entirely |
| `categories.<name>.prompt_append` | category-level prompt append (also works on agents) |
| `agents.<name>.prompt` | supports `file://` URLs, `~` expansion, relative paths |
| `model_capabilities.auto_refresh_on_start` | keeps the capability cache fresh, reducing heuristic guessing |
| `disabled_mcps` | fewer injected MCPs means a smaller tool schema surface |
| `hashline_edit` | default `false`; gates the hash-anchored `edit` tool |

Tool registration is config-gated: the registry exposes roughly **12 to 38
tools** depending on configuration. That count matters when a provider rejects a
tool schema — see `docs/known-issues.md`.

## Plugin-injected MCPs are invisible to static inspection

This one bites during debugging. OMO injects MCP servers at **runtime** through
the OpenCode plugin API, so:

```bash
opencode mcp list          # will NOT show plugin-injected MCPs
bunx oh-my-openagent doctor --verbose   # will
```

Built-in injected MCPs: `websearch`, `context7`, `grep_app`, `lsp`. Only MCPs
configured natively under the `mcp` key in `opencode.json` appear in
`opencode mcp list`.

Consequence: **searching the filesystem for a tool schema can legitimately find
nothing**, because runtime-injected schemas are never on disk. Use
`doctor --verbose` to enumerate what is actually loaded.

## Verify with doctor, not by reading config

`doctor` is the only thing that reports how your config *actually* resolves.

```bash
python3 scripts/doctor_check.py --version <pinned> --strict
```

Pin the version — check names and wording shift between releases. And read
`docs/known-issues.md` before acting on a warning: at least one is a routine
false positive.
