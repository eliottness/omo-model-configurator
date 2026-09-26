#!/usr/bin/env node

import { readFile } from "node:fs/promises"
import { resolve } from "node:path"
import { pathToFileURL } from "node:url"

function parseArguments(argv) {
  const options = { engineRoot: undefined, modelsPath: null, models: [] }
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    if (argument === "--engine-root") {
      options.engineRoot = argv[index + 1]
      index += 1
    } else if (argument === "--models-path") {
      options.modelsPath = argv[index + 1]
      index += 1
    } else if (argument === "--model") {
      options.models.push(argv[index + 1])
      index += 1
    } else {
      throw new Error(`unsupported argument: ${argument}`)
    }
  }
  if (options.engineRoot === undefined) {
    throw new Error("--engine-root is required")
  }
  if (options.models.length === 0) {
    throw new Error("at least one --model provider/id is required")
  }
  return options
}

function splitModel(value) {
  const separator = value.indexOf("/")
  if (separator <= 0 || separator === value.length - 1) {
    throw new Error(`invalid model selector: ${value}`)
  }
  return { provider: value.slice(0, separator), id: value.slice(separator + 1) }
}

function moduleUrl(engineRoot, relativePath) {
  return pathToFileURL(resolve(engineRoot, relativePath)).href
}

function capabilities(model) {
  return {
    reasoning: model.reasoning === true,
    input: Array.isArray(model.input) ? [...model.input] : [],
    context_window: typeof model.contextWindow === "number" ? model.contextWindow : null,
    max_tokens: typeof model.maxTokens === "number" ? model.maxTokens : null,
    api: model.api ?? null,
    thinking_levels: model.thinkingLevelMap ?? null,
    compatibility: model.compat ?? null,
  }
}

async function probe(options) {
  const engineRoot = resolve(options.engineRoot)
  const manifest = JSON.parse(await readFile(resolve(engineRoot, "package.json"), "utf8"))
  const [{ ModelRuntime }, { AuthStorage }, { resolvePresetName }] = await Promise.all([
    import(moduleUrl(engineRoot, "dist/core/model-runtime.js")),
    import(moduleUrl(engineRoot, "dist/core/auth-storage.js")),
    import(moduleUrl(engineRoot, "dist/core/extensions/builtin/prompt-preset/presets.js")),
  ])
  if (
    typeof ModelRuntime?.create !== "function"
    || typeof AuthStorage?.inMemory !== "function"
    || typeof resolvePresetName !== "function"
  ) {
    throw new Error("installed engine does not expose the required native probe surface")
  }
  const runtime = await ModelRuntime.create({
    credentials: AuthStorage.inMemory(),
    modelsPath: options.modelsPath,
    allowModelNetwork: false,
    refreshOnCreate: false,
  })
  const models = options.models.map((selector) => {
    const { provider, id } = splitModel(selector)
    const model = runtime.getModel(provider, id)
    return {
      model: selector,
      registry_admitted: model !== undefined,
      preset: model === undefined ? null : (resolvePresetName(model, { promptPreset: "auto" }) ?? null),
      capabilities: model === undefined
        ? { reasoning: false, input: [], context_window: null, max_tokens: null }
        : capabilities(model),
      credential_ready: null,
      credential_source: null,
      credential_status: "not-probed",
      live_entitlement: "not-probed",
    }
  })
  return {
    runtime: {
      surface: "native",
      engine_version: typeof manifest.version === "string" ? manifest.version : null,
    },
    models,
  }
}

async function main() {
  try {
    const payload = await probe(parseArguments(process.argv.slice(2)))
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    process.stderr.write(`${JSON.stringify({ error: message, surface: "unsupported" })}\n`)
    process.exitCode = 2
  }
}

await main()
