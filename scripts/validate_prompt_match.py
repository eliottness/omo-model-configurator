#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///


from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, NoReturn, TypedDict

Detector = Callable[[str], bool]


def _extract_model_name(model: str) -> str:
    return model.split("/")[-1] if "/" in model else model


def _claude_name(name: str) -> str:
    return name.replace(".", "-")


def _is_gpt_model(name: str) -> bool:
    return "gpt" in name


# INFERRED, not verbatim: re-verify these three GPT detector bodies upstream.
def _is_gpt_5_5_model(name: str) -> bool:
    return re.search(r"gpt-5[.\-]5", name) is not None


def _is_gpt_5_6_model(name: str) -> bool:
    return re.search(r"gpt-5[.\-]6", name) is not None


def _is_gpt_native_sisyphus_model(name: str) -> bool:
    return re.search(r"gpt-5[.\-]4", name) is not None


def _is_claude_model(name: str, fragment: str) -> bool:
    return fragment in _claude_name(name)


def _is_kimi_k2_model(name: str) -> bool:
    return "kimi" in name or re.search(r"k2[-.]?p[567]", name) is not None


def _is_kimi_k2_7_model(name: str) -> bool:
    return (
        re.search(r"kimi-k2[.\-]?7", name) is not None
        or re.search(r"k2[-.]?p7", name) is not None
    )


def _is_kimi_k3_model(name: str) -> bool:
    return "kimi-k3" in name or re.search(r"k3[-.]?p?\d*$", name) is not None


def _is_minimax_model(name: str) -> bool:
    return "minimax" in name


def _is_glm_model(name: str) -> bool:
    return "glm" in name


def _is_grok_4_5_model(name: str) -> bool:
    return re.search(r"grok-4-5(?![0-9])", name) is not None


def _is_grok_4_6_model(name: str) -> bool:
    return re.search(r"grok-4-6(?![0-9])", name) is not None


def _is_gemini_model(name: str) -> bool:
    return "gemini" in name


DETECTORS: Final[tuple[tuple[str, Detector], ...]] = (
    ("isGptModel", _is_gpt_model),
    ("isGpt5_5Model", _is_gpt_5_5_model),
    ("isGpt5_6Model", _is_gpt_5_6_model),
    ("isGptNativeSisyphusModel", _is_gpt_native_sisyphus_model),
    ("isClaudeOpus47Model", lambda name: _is_claude_model(name, "claude-opus-4-7")),
    ("isClaudeOpus48Model", lambda name: _is_claude_model(name, "claude-opus-4-8")),
    ("isClaudeOpus5Model", lambda name: _is_claude_model(name, "claude-opus-5")),
    ("isClaudeFable5Model", lambda name: _is_claude_model(name, "claude-fable-5")),
    ("isKimiK2Model", _is_kimi_k2_model),
    ("isKimiK27Model", _is_kimi_k2_7_model),
    ("isKimiK3Model", _is_kimi_k3_model),
    ("isMiniMaxModel", _is_minimax_model),
    ("isGlmModel", _is_glm_model),
    ("isGrok45Model", _is_grok_4_5_model),
    ("isGrok46Model", _is_grok_4_6_model),
    ("isGeminiModel", _is_gemini_model),
)

SISYPHUS_DISPATCH: Final[tuple[tuple[str, Detector], ...]] = (
    ("kimi-k3", _is_kimi_k3_model),
    ("kimi-k2-7", _is_kimi_k2_7_model),
    ("kimi-k2-6", _is_kimi_k2_model),
    ("gpt-5-5", lambda name: _is_gpt_5_5_model(name) or _is_gpt_5_6_model(name)),
    ("gpt-5-4", _is_gpt_native_sisyphus_model),
    ("claude-fable-5", lambda name: _is_claude_model(name, "claude-fable-5")),
    ("claude-opus-5", lambda name: _is_claude_model(name, "claude-opus-5")),
    ("claude-opus-4-8", lambda name: _is_claude_model(name, "claude-opus-4-8")),
    ("claude-opus-4-7", lambda name: _is_claude_model(name, "claude-opus-4-7")),
    ("glm-5-2", _is_glm_model),
    ("grok-4", lambda name: _is_grok_4_5_model(name) or _is_grok_4_6_model(name)),
)

MODEL_MATCHERS: Final[Mapping[str, Detector]] = MappingProxyType(
    {
        "gpt": _is_gpt_model,
        "gemini": _is_gemini_model,
        "kimi-k3": _is_kimi_k3_model,
        "kimi-k2-7": _is_kimi_k2_7_model,
        "kimi": _is_kimi_k2_model,
        "glm": _is_glm_model,
        "opus-4-7": lambda name: _is_claude_model(name, "claude-opus-4-7"),
        "minimax": _is_minimax_model,
    }
)
ATLAS_VARIANTS: Final = (
    "default",
    "gemini",
    "glm",
    "gpt",
    "kimi-k2-7",
    "kimi-k3",
    "kimi",
    "opus-4-7",
)
ULTRAWORK_VARIANTS: Final = ("codex", "default", "gemini", "glm", "gpt", "planner")

LANDMINE_NOTES: Final = (
    "isGptModel matches every name containing 'gpt', including gpt-oss-120b.",
    "isKimiK3Model's k3[-.]?p?\\d*$ pattern can hijack any name ending in k3<digits>.",
    "All GLM versions collapse to the Sisyphus glm-5-2 prompt family.",
)


def resolve_sisyphus_prompt_family(model: str) -> str:
    """Return the first Sisyphus prompt family matching a model ID."""
    name = _extract_model_name(model).lower()
    for family, detector in SISYPHUS_DISPATCH:
        if detector(name):
            return family
    return "fallback"


def resolve_variant(
    model: str,
    variants: Iterable[str],
    agent: str | None = None,
) -> str:
    """Resolve an insertion-ordered prompt variant for a model ID."""
    variant_names = tuple(variants)
    if agent == "prometheus" and "planner" in variant_names:
        return "planner"

    name = _extract_model_name(model).lower()
    for variant in variant_names:
        matcher = MODEL_MATCHERS.get(variant)
        if matcher is not None and matcher(name):
            return variant
    if "default" in variant_names:
        return "default"
    return variant_names[0]


class Surface(str, Enum):
    SISYPHUS = "sisyphus"
    ATLAS = "atlas"
    ULTRAWORK = "ultrawork"
    PROMETHEUS = "prometheus"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SurfaceResolution:
    surface: Surface
    resolved: str
    matched: bool

    @property
    def degraded(self) -> bool:
        return not self.matched


class JsonResolution(TypedDict):
    surface: str
    resolved: str
    matched: bool
    degraded: bool


class JsonExplanation(TypedDict):
    extracted_name: str
    matched_detectors: list[str]
    landmines: list[str]


class JsonPayload(TypedDict, total=False):
    model: str
    results: list[JsonResolution]
    warnings: list[str]
    explain: JsonExplanation


def assert_never(value: NoReturn) -> NoReturn:
    raise AssertionError(f"unreachable surface: {value}")


def _resolve_surface(model: str, surface: Surface) -> SurfaceResolution:
    match surface:
        case Surface.SISYPHUS:
            resolved = resolve_sisyphus_prompt_family(model)
        case Surface.ATLAS:
            resolved = resolve_variant(model, ATLAS_VARIANTS)
        case Surface.ULTRAWORK:
            resolved = resolve_variant(model, ULTRAWORK_VARIANTS)
        case Surface.PROMETHEUS:
            resolved = resolve_variant(model, ULTRAWORK_VARIANTS, agent="prometheus")
        case unreachable:
            assert_never(unreachable)
    return SurfaceResolution(surface, resolved, resolved not in {"fallback", "default"})


def _warning(resolution: SurfaceResolution) -> str:
    return (
        f"WARNING: {resolution.surface.value} resolved to {resolution.resolved}; "
        "prompt selection is degraded."
    )


class Arguments(argparse.Namespace):
    model_id: str
    agent: Surface | None
    json_output: bool
    explain: bool
    harness: str
    role: str | None
    probe_file: Path | None
    engine_root: Path | None
    models_path: Path | None


def _parse_args(argv: Sequence[str] | None = None) -> Arguments:
    parser = argparse.ArgumentParser(
        description="Show which OMO prompt family or variant a model ID selects."
    )
    parser.add_argument("model_id", metavar="model-id")
    parser.add_argument("--agent", choices=tuple(Surface), type=Surface)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--harness", choices=("opencode", "native", "senpi"), default="opencode")
    parser.add_argument("--role", help="Actual native role; not an OpenCode surface")
    parser.add_argument("--probe-file", type=Path, help="Previously captured native probe JSON")
    parser.add_argument("--engine-root", type=Path)
    parser.add_argument("--models-path", type=Path)
    arguments = Arguments()
    parser.parse_args(argv, namespace=arguments)
    return arguments


def _explanation(model: str) -> JsonExplanation:
    name = _extract_model_name(model).lower()
    return {
        "extracted_name": name,
        "matched_detectors": [label for label, detector in DETECTORS if detector(name)],
        "landmines": list(LANDMINE_NOTES),
    }


def _run(arguments: Arguments) -> int:
    if arguments.harness in {"native", "senpi"}:
        return _run_native(arguments)
    surfaces = tuple(Surface) if arguments.agent is None else (arguments.agent,)
    results = tuple(_resolve_surface(arguments.model_id, surface) for surface in surfaces)
    warnings = [_warning(result) for result in results if result.degraded]

    if arguments.json_output:
        payload: JsonPayload = {
            "model": arguments.model_id,
            "results": [
                {
                    "surface": result.surface.value,
                    "resolved": result.resolved,
                    "matched": result.matched,
                    "degraded": result.degraded,
                }
                for result in results
            ],
            "warnings": warnings,
        }
        if arguments.explain:
            payload["explain"] = _explanation(arguments.model_id)
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for result in results:
            status = "matched" if result.matched else "degraded"
            print(f"{result.surface.value}: {result.resolved} [{status}]")
        for warning in warnings:
            print(warning)
        if arguments.explain:
            explanation = _explanation(arguments.model_id)
            detectors = ", ".join(explanation["matched_detectors"]) or "none"
            print(f"extracted model name: {explanation['extracted_name']}")
            print(f"matched detectors: {detectors}")
            print("landmines:")
            for note in explanation["landmines"]:
                print(f"- {note}")

    return 1 if any(result.resolved == "fallback" for result in results) else 0


def _run_native(arguments: Arguments) -> int:
    from runtime_config import probe_native_models

    try:
        payload = (
            json.loads(arguments.probe_file.read_text(encoding="utf-8"))
            if arguments.probe_file
            else probe_native_models(
                [arguments.model_id], arguments.engine_root, arguments.models_path
            )
        )
        models = payload.get("models", [])
        evidence = next(
            (item for item in models if item.get("model") == arguments.model_id),
            None,
        )
        if evidence is None:
            raise ValueError("probe contains no evidence for the requested model")
        admitted = evidence.get("registry_admitted") is True
        preset = evidence.get("preset")
        matched = admitted and isinstance(preset, str) and bool(preset)
        expected_default = admitted and arguments.role in {"explore", "librarian", "search", "quick"}
        result = {
            "model": arguments.model_id,
            "runtime": payload.get("runtime"),
            "role": arguments.role,
            "authority": "installed-runtime",
            "results": [{
                "surface": "native",
                "resolved": preset if preset else ("default" if expected_default else "no-model-preset"),
                "matched": matched,
                "degraded": not (matched or expected_default),
            }],
            "evidence": evidence,
            "warnings": [] if matched else [
                "Model is absent from the registry." if not admitted else
                "No model-specific preset; role prompt compatibility is not verified."
            ],
        }
        if arguments.json_output:
            print(json.dumps(result, indent=2))
        else:
            print(f"native: {result['results'][0]['resolved']}")
            for warning in result["warnings"]:
                print(f"WARNING: {warning}")
        return 0 if matched or expected_default else (1 if not admitted else 2)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: unsupported native inspection: {error}", file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run the prompt-family validation CLI."""
    return _run(_parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
