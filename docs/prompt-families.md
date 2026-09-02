# Prompt families: how OMO decides which prompt your model gets

Reference commit: `4480fd41ab26ceea0e4bfd1584d495b748b95dfa` (branch `dev`).
Re-verify against source before trusting this — these are notes, not the source of truth.

## The mechanism

`resolveSisyphusPromptFamily(model)` in
`packages/omo-opencode/src/agents/sisyphus-agent-factory.ts` is a **first-match-wins**
chain that ends in a generic `fallback`:

| # | Family returned | Matches when |
|---|---|---|
| 1 | `kimi-k3` | `isKimiK3Model` |
| 2 | `kimi-k2-7` | `isKimiK27Model` |
| 3 | `kimi-k2-6` | `isKimiK2Model` |
| 4 | `gpt-5-5` | `isGpt5_5Model` OR `isGpt5_6Model` |
| 5 | `gpt-5-4` | `isGptNativeSisyphusModel` |
| 6 | `claude-fable-5` | `isClaudeFable5Model` |
| 7 | `claude-opus-5` | `isClaudeOpus5Model` |
| 8 | `claude-opus-4-8` | `isClaudeOpus48Model` |
| 9 | `claude-opus-4-7` | `isClaudeOpus47Model` |
| 10 | `glm-5-2` | `isGlmModel` |
| 11 | `grok-4` | `isGrok45Model` OR `isGrok46Model` |
| — | **`fallback`** | nothing above matched |

**Order beats specificity.** A model that satisfies two detectors gets whichever
appears first in this list, regardless of which is the better fit.

## There is no Gemini branch

Gemini models match nothing in the chain and land in `fallback`. OMO then
string-patches that generic prompt through
`applyGeminiFallbackOverrides()` in `sisyphus-agent-factory`'s sibling
`sisyphus-gemini-fallback-overrides.ts`, which splices Gemini-specific tool and
verification guidance into the fallback text. The filename is the tell: Gemini is
handled as a *patched fallback*, not as a first-class family.

## The detectors, and their landmines

From `packages/model-core/src/model-family-detectors.ts`:

```
extractModelName(model) = model.includes("/") ? model.split("/").pop() : model
```

Consequences worth knowing:

- **Multi-segment provider paths work.** `a/b/c/GLM-5.3` reduces to `GLM-5.3`,
  because `.pop()` takes only the last segment. Gateway-style IDs with three or
  four segments are matched on their final component.
- **`isGptModel` is `includes("gpt")`.** Any model whose name contains `gpt`
  matches the GPT family — including models that are not GPT at all, such as
  open-weight `gpt-oss-*` releases.
- **`isGlmModel` is `includes("glm")`.** *Every* GLM version collapses to the
  `glm-5-2` prompt. A newer GLM does not get a newer prompt; it gets the 5.2-era
  one. This is a version mismatch, not a fallback, but it is worth stating to a
  user explicitly.
- **`isKimiK3Model` includes `/k3[-.]?p?\d*$/`.** That matches any model name
  *ending* in `k3` plus optional digits — so an unrelated model can be routed to
  the Kimi K3 prompt purely by how its name ends. And because Kimi checks run
  first, that match wins over everything else.
- **Claude detectors normalise `.` to `-`.** `claude-opus-4.8` and
  `claude-opus-4-8` are treated identically.

## A second, different mechanism for other prompt tables

`resolveVariant()` in `packages/prompts-core/src/variant-resolver.ts` is **not**
the same dispatch. It iterates the *variant table's own keys, in insertion
order*, returning the first whose matcher matches, then falls back to `default`,
then to the first key.

- Matcher keys available: `gpt`, `gemini`, `kimi-k3`, `kimi-k2-7`, `kimi`, `glm`,
  `opus-4-7`, `minimax`
- If the agent is the planner and a `planner` variant exists, that wins first.

Observed variant tables:

| Table | Keys, in order |
|---|---|
| atlas | `default`, `gemini`, `glm`, `gpt`, `kimi-k2-7`, `kimi-k3`, `kimi`, `opus-4-7` |
| ultrawork | `codex`, `default`, `gemini`, `glm`, `gpt`, `planner` |

**There is no `opus-5` variant.** The only Claude matcher key is `opus-4-7`,
which requires the literal `claude-opus-4-7`. So a Claude Opus 5 model matches
nothing here and silently resolves to `default`.

## Check before you ship

```bash
python3 scripts/validate_prompt_match.py <provider>/<model> --explain
```

Exit code `1` means the model resolves to `fallback`. Treat it as a blocker.
