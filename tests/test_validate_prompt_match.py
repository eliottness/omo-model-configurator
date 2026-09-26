from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "validate_prompt_match.py"
PROBE_PATH = Path(__file__).parents[1] / "scripts" / "runtime_probe.mjs"
ATLAS_VARIANTS = (
    "default",
    "gemini",
    "glm",
    "gpt",
    "kimi-k2-7",
    "kimi-k3",
    "kimi",
    "opus-4-7",
)
ULTRAWORK_VARIANTS = ("codex", "default", "gemini", "glm", "gpt", "planner")


@pytest.mark.parametrize(
    ("model_id", "expected_family"),
    [
        pytest.param("google/gemini-3.5-flash-lite", "fallback", id="gemini"),
        pytest.param("someprovider/zai-org/GLM-5.3", "glm-5-2", id="glm"),
        pytest.param("a/b/c/GLM-5.3-Flash", "glm-5-2", id="multi-segment"),
        pytest.param(
            "anthropic/claude-opus-5",
            "claude-opus-5",
            id="opus-5",
        ),
        pytest.param(
            "anthropic/claude-opus-4.8",
            "claude-opus-4-8",
            id="claude-dot-normalization",
        ),
    ],
)
def test_resolves_sisyphus_family_when_model_is_known(
    model_id: str,
    expected_family: str,
) -> None:
    from scripts.validate_prompt_match import resolve_sisyphus_prompt_family

    # Given a model ID from an upstream provider.
    # When the Sisyphus prompt family is resolved.
    family = resolve_sisyphus_prompt_family(model_id)

    # Then the first matching dispatch branch wins.
    assert family == expected_family


def test_atlas_uses_default_when_opus_5_has_no_variant() -> None:
    from scripts.validate_prompt_match import resolve_variant

    # Given Atlas's insertion-ordered variant names and an Opus 5 model.
    # When the variant is resolved.
    variant = resolve_variant("anthropic/claude-opus-5", ATLAS_VARIANTS)

    # Then the missing Opus 5 matcher falls through to default.
    assert variant == "default"


def test_gpt_oss_matches_gpt_variant() -> None:
    from scripts.validate_prompt_match import resolve_variant

    # Given a non-OpenAI model name containing the substring "gpt".
    # When Atlas's variants are resolved.
    variant = resolve_variant("gpt-oss-120b", ATLAS_VARIANTS)

    # Then the broad GPT detector selects the GPT variant.
    assert variant == "gpt"


def test_variant_resolution_uses_variant_insertion_order() -> None:
    from scripts.validate_prompt_match import resolve_variant

    # Given a model name matching both GLM and GPT detectors.
    # When Atlas's insertion-ordered variants are resolved.
    variant = resolve_variant("someprovider/glm-gpt-hybrid", ATLAS_VARIANTS)

    # Then GLM wins because its variant key appears first.
    assert variant == "glm"


def test_prometheus_prefers_planner_variant() -> None:
    from scripts.validate_prompt_match import resolve_variant

    # Given the Ultrawork table containing a planner variant.
    # When the Prometheus override is applied.
    variant = resolve_variant(
        "someprovider/GLM-5.3",
        ULTRAWORK_VARIANTS,
        agent="prometheus",
    )

    # Then planner wins before model matching.
    assert variant == "planner"


def test_cli_returns_one_and_warns_when_sisyphus_falls_back() -> None:
    # Given a Gemini model that has no Sisyphus branch.
    # When every prompt surface is queried through the CLI.
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "google/gemini-3.5-flash-lite"],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then CI sees a failure and the degraded surface is explicit.
    assert completed.returncode == 1
    assert "sisyphus: fallback [degraded]" in completed.stdout
    assert "WARNING:" in completed.stdout


def test_cli_returns_zero_when_no_surface_falls_back() -> None:
    # Given a GLM model covered by every model-routed surface.
    # When every prompt surface is queried through the CLI.
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "someprovider/zai-org/GLM-5.3"],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then the command succeeds and reports the collapsed Sisyphus family.
    assert completed.returncode == 0
    assert "sisyphus: glm-5-2 [matched]" in completed.stdout


def test_json_output_reports_match_state_per_surface() -> None:
    # Given an Opus 5 model and the Atlas-only JSON surface.
    # When JSON output is requested.
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "anthropic/claude-opus-5",
            "--agent",
            "atlas",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    # Then default is represented as degraded rather than a real match.
    assert payload["results"] == [
        {
            "surface": "atlas",
            "resolved": "default",
            "matched": False,
            "degraded": True,
        }
    ]


def test_explain_reports_detectors_and_landmine_notes() -> None:
    # Given a model caught by the broad GPT substring detector.
    # When explanation output is requested.
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "gpt-oss-120b",
            "--agent",
            "atlas",
            "--explain",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then the matching detector and all required landmine categories are visible.
    assert "matched detectors: isGptModel" in completed.stdout
    assert "gpt-oss-120b" in completed.stdout
    assert "k3" in completed.stdout
    assert "glm-5-2" in completed.stdout


def test_native_probe_reports_registry_preset_capabilities_and_credential_state(
    tmp_path: Path,
) -> None:
    # Given a minimal installed-runtime-shaped module tree with no credentials.
    engine_root = tmp_path / "engine"
    preset_dir = (
        engine_root
        / "dist"
        / "core"
        / "extensions"
        / "builtin"
        / "prompt-preset"
    )
    preset_dir.mkdir(parents=True)
    (engine_root / "package.json").write_text(
        '{"name":"runtime-engine","version":"1.2.3","type":"module"}',
        encoding="utf-8",
    )
    (engine_root / "dist" / "core" / "auth-storage.js").write_text(
        "export class AuthStorage { static inMemory() { return {}; } }\n",
        encoding="utf-8",
    )
    (engine_root / "dist" / "core" / "model-runtime.js").write_text(
        """
export class ModelRuntime {
  static async create(options) {
    if (options.allowModelNetwork !== false || options.refreshOnCreate !== false) {
      throw new Error("network policy was not disabled");
    }
    return new ModelRuntime();
  }
  getModel(provider, id) {
    if (provider !== "openai" || id !== "gpt-6-sol") return undefined;
    return {
      provider,
      id,
      name: "GPT-6 Sol",
      reasoning: true,
      input: ["text", "image"],
      contextWindow: 400000,
      maxTokens: 128000
    };
  }
  getProviderAuthStatus() { return { configured: false }; }
}
""",
        encoding="utf-8",
    )
    (preset_dir / "presets.js").write_text(
        """
export function resolvePresetName(model) {
  return model.id === "gpt-6-sol" ? "gpt-6-astra" : undefined;
}
""",
        encoding="utf-8",
    )

    # When the read-only probe inspects an admitted model.
    completed = subprocess.run(
        [
            "node",
            str(PROBE_PATH),
            "--engine-root",
            str(engine_root),
            "--model",
            "openai/gpt-6-sol",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then admission, preset, capabilities, and credential readiness stay distinct.
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["runtime"]["engine_version"] == "1.2.3"
    assert payload["models"] == [
        {
            "model": "openai/gpt-6-sol",
            "registry_admitted": True,
            "preset": "gpt-6-astra",
            "capabilities": {
                "context_window": 400000,
                "input": ["text", "image"],
                "max_tokens": 128000,
                "reasoning": True,
                "api": None,
                "thinking_levels": None,
                "compatibility": None,
            },
            "credential_ready": None,
            "credential_source": None,
            "credential_status": "not-probed",
            "live_entitlement": "not-probed",
        }
    ]


def test_native_validation_uses_runtime_preset_not_sisyphus_fallback(
    tmp_path: Path,
) -> None:
    # Given captured native probe evidence for a search-role model.
    probe = tmp_path / "probe.json"
    probe.write_text(
        json.dumps(
            {
                "runtime": {"surface": "native", "engine_version": "1.2.3"},
                "models": [
                    {
                        "model": "openai/gpt-6-sol",
                        "registry_admitted": True,
                        "preset": "gpt-6-astra",
                        "capabilities": {},
                        "credential_ready": False,
                        "credential_source": None,
                        "live_entitlement": "not-probed",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    # When native validation runs for a role irrelevant to OpenCode Sisyphus.
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "openai/gpt-6-sol",
            "--harness",
            "native",
            "--role",
            "search",
            "--probe-file",
            str(probe),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then exact native admission and preset evidence succeeds.
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["results"] == [
        {
            "surface": "native",
            "resolved": "gpt-6-astra",
            "matched": True,
            "degraded": False,
        }
    ]


def test_native_search_does_not_require_an_orchestrator_model_preset(tmp_path: Path) -> None:
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps({
        "runtime": {"surface": "native", "engine_version": "synthetic"},
        "models": [{"model": "example/search-small", "registry_admitted": True, "preset": None}],
    }))
    result = subprocess.run([
        sys.executable, str(SCRIPT_PATH), "example/search-small",
        "--harness", "native", "--role", "explore", "--probe-file", str(probe),
        "--json",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["results"][0]["resolved"] == "default"
    assert payload["results"][0]["matched"] is False
    assert payload["results"][0]["degraded"] is False
