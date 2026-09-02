# Known issues

Findings from real use. Where something is unresolved, it says so.

## 1. Gemini models fail on tool calls (UNRESOLVED)

**Symptom.** In the environment where this was observed, every `google/*` model
returned HTTP 400 as soon as tools were in play:

```
Invalid value at 'tools[0].function_declarations[143].parameters
  .properties[0].value.enum[0]' (TYPE_STRING), true
```

Google requires `enum` members to be **strings**. Something in the tool set is
declaring an `enum` whose first member is the boolean `true`.

**Reproduce.**

```bash
opencode run -m google/gemini-3.5-flash-lite --format json "hello"
```

**What is established.** It still reproduces under `opencode run --pure`, which
disables external plugins — so the offending schema is neither from a plugin nor
from the MCP servers OMO injects at runtime. That leaves OpenCode's builtin
tools, or an MCP configured natively under the `mcp` key in `opencode.json`.

**What is NOT established:** which specific tool. **Root cause unknown.**

To enumerate what is actually loaded — including runtime-injected servers that
`opencode mcp list` omits:

```bash
bunx oh-my-openagent doctor --verbose
```

**Mitigation.** Scan your tool schemas before switching an agent to Gemini:

```bash
python3 scripts/check_tool_schema.py --file tools.json
```

**Consequence for configuration.** Where this reproduces, any agent or category
whose *primary* is a Gemini model may be non-functional while tools are enabled,
and any Gemini entry in a fallback chain is a dead rung. Verify before relying
on one.

## 2. `doctor` reports working providers as unavailable (FALSE POSITIVE)

`oh-my-openagent doctor` may report:

```
Model override uses unavailable provider
   Provider(s) not found in OpenCode model cache: <provider>
```

for a provider that works perfectly. The check consults OpenCode's **model
cache**; a provider that is reachable but absent from that cache is reported as
missing.

**How to tell a false positive from a real one:** call the model directly.

```bash
opencode run -m <provider>/<model> --format json "reply with exactly: OK"
```

If that returns text, the provider works and the warning is noise. Refreshing
capabilities (`oh-my-openagent refresh-model-capabilities`) may clear it.

## 3. `fallback_models` is deprecated in favour of `models`

`doctor` flags every occurrence:

```
Deprecated reasoning config key
   Fix: Replace fallback_models with models, or run: oh-my-openagent config migrate
```

It is a warning, not a break — existing configs keep working — but it fires once
per agent that uses the old key, which drowns out real findings.

```bash
python3 scripts/lint_omo_config.py <config.jsonc>          # static: flags every occurrence
python3 scripts/doctor_check.py --version <pinned>         # authoritative: what OMO itself reports
bunx oh-my-openagent config migrate --dry-run              # preview the rewrite
```

## 4. The upstream leaderboard scraper needs patching

The vendored scraper had two breakages against the current site. Both are fixed
here and documented in `vendor/aa-scraper/PATCHES.md`:

- its default `target_url` 404s (the site restructured its leaderboard routes)
- its first-column extractor only reads `<img>` logos, so on the models
  leaderboard — which renders the name as anchor text — **every** model name came
  back empty (0 of 286 rows populated)

Additionally its default locale formatting rewrote decimals (`85.5` -> `85,5`),
which breaks numeric sorting downstream; the vendored config disables it.
