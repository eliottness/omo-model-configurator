#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

# --- How to run ---
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly:
#      uv run lint_omo_config.py CONFIG.jsonc [OPTIONS]
# 3. Or make executable and run:
#      chmod +x lint_omo_config.py && ./lint_omo_config.py CONFIG.jsonc [OPTIONS]
# ------------------

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Literal, NamedTuple, TypeAlias, TypedDict

Severity = Literal["error", "warning", "info"]
JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
ModelPair: TypeAlias = tuple[str, str | None]

VALID_REASONING: Final = frozenset({"off", "minimal", "low", "medium", "high", "xhigh", "max", "auto"})
SEVERITY_RANK: Final[dict[Severity, int]] = {"error": 3, "warning": 2, "info": 1}
RULES: Final[dict[str, tuple[Severity, str, str]]] = {
    "deprecated-fallback-models": ("warning", "fallback_models is deprecated.", "Rename fallback_models to models."),
    "invalid-reasoning-value": ("error", "The reasoning value is not supported.", "Use off, minimal, low, medium, high, xhigh, max, or auto."),
    "malformed-model-id": ("error", "The model identifier is empty or lacks a provider.", "Use provider/model form."),
    "duplicate-chain-entry": ("warning", "This model and reasoning pair already appears earlier in the chain.", "Remove the unreachable duplicate."),
    "single-entry-chain": ("info", "The model chain has no fallback coverage.", "Add another model when fallback coverage is required."),
    "unknown-model-id": ("warning", "The model identifier is absent from the known-models file.", "Choose a listed model or refresh the file."),
    "primary-duplicated-in-fallback": ("warning", "The primary model and reasoning pair is repeated in its fallback chain.", "Remove the primary pair from the chain."),
    "empty-chain": ("error", "The model chain is empty.", "Add at least two model entries."),
}


class Finding(TypedDict):
    rule_id: str
    severity: Severity
    location: str
    message: str
    suggestion: str


class LintState(NamedTuple):
    known_models: frozenset[str] | None
    findings: list[Finding]


class Chain(NamedTuple):
    entries: list[JsonValue]
    location: str
    primary: ModelPair | None


class ConfigFileError(Exception):
    pass


def _add(state: LintState, rule_id: str, location: str) -> None:
    severity, message, suggestion = RULES[rule_id]
    state.findings.append({"rule_id": rule_id, "severity": severity, "location": location, "message": message, "suggestion": suggestion})


def strip_jsonc(source: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(source):
        character = source[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if source.startswith("//", index):
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        if source.startswith("/*", index):
            index += 2
            while index < len(source) and not source.startswith("*/", index):
                if source[index] in "\r\n":
                    output.append(source[index])
                index += 1
            index += 2 if index < len(source) else 0
            continue
        output.append(character)
        index += 1
    return _remove_trailing_commas("".join(output))


def _remove_trailing_commas(source: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    for index, character in enumerate(source):
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
            output.append(character)
            continue
        if character == ",":
            lookahead = index + 1
            while lookahead < len(source) and source[lookahead].isspace():
                lookahead += 1
            if lookahead < len(source) and source[lookahead] in "}]":
                continue
        output.append(character)
    return "".join(output)


def load_config(path: Path) -> JsonObject:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigFileError(f"{path}: {error}") from error
    try:
        parsed: JsonValue = json.loads(strip_jsonc(source))
    except json.JSONDecodeError as error:
        raise ConfigFileError(f"{path}: malformed JSONC: {error.msg}") from error
    if not isinstance(parsed, dict):
        raise ConfigFileError(f"{path}: configuration root must be an object")
    return parsed


def load_known_models(path: Path) -> frozenset[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ConfigFileError(f"{path}: {error}") from error
    return frozenset(line.strip() for line in lines if line.strip())


def lint_config(config: JsonObject, known_models: frozenset[str] | None = None) -> list[Finding]:
    state = LintState(known_models, [])
    _find_deprecated_keys(config, "", state)
    opencode = config.get("[opencode]")
    if not isinstance(opencode, dict):
        return state.findings
    agents = opencode.get("agents")
    if isinstance(agents, dict):
        for name, entity in agents.items():
            if isinstance(entity, dict):
                _lint_agent(entity, f"[opencode].agents.{name}", state)
    categories = opencode.get("categories")
    if isinstance(categories, dict):
        for name, entity in categories.items():
            if isinstance(entity, dict):
                _lint_chains((entity, f"[opencode].categories.{name}", None), state)
    return state.findings


def _find_deprecated_keys(value: JsonValue, location: str, state: LintState) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}" if location else key
            if key == "fallback_models":
                _add(state, "deprecated-fallback-models", child_location)
            _find_deprecated_keys(child, child_location, state)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _find_deprecated_keys(child, f"{location}[{index}]", state)


def _lint_agent(entity: JsonObject, location: str, state: LintState) -> None:
    primary: ModelPair | None = None
    if "model" in entity:
        model = entity["model"]
        _lint_model(model, f"{location}.model", state)
        reasoning = entity.get("reasoning")
        if "reasoning" in entity:
            _lint_reasoning(reasoning, f"{location}.reasoning", state)
        if isinstance(model, str) and (reasoning is None or isinstance(reasoning, str)):
            primary = (model, reasoning)
    _lint_chains((entity, location, primary), state)


def _lint_chains(target: tuple[JsonObject, str, ModelPair | None], state: LintState) -> None:
    entity, location, primary = target
    for chain_key in ("models", "fallback_models"):
        chain_value = entity.get(chain_key)
        if not isinstance(chain_value, list):
            continue
        chain = Chain(chain_value, f"{location}.{chain_key}", primary)
        if not chain.entries:
            _add(state, "empty-chain", chain.location)
        elif len(chain.entries) == 1:
            _add(state, "single-entry-chain", chain.location)
        _lint_chain(chain, state)


def _lint_chain(chain: Chain, state: LintState) -> None:
    seen: set[ModelPair] = set()
    for index, entry in enumerate(chain.entries):
        location = f"{chain.location}[{index}]"
        pair = _lint_entry(entry, location, state)
        if pair is None:
            continue
        if pair in seen:
            _add(state, "duplicate-chain-entry", location)
        else:
            seen.add(pair)
        if chain.primary is not None and pair == chain.primary:
            _add(state, "primary-duplicated-in-fallback", location)


def _lint_entry(entry: JsonValue, location: str, state: LintState) -> ModelPair | None:
    if isinstance(entry, str):
        _lint_model(entry, location, state)
        return (entry, None)
    if not isinstance(entry, dict):
        _lint_model(entry, location, state)
        return None
    model = entry.get("model")
    reasoning = entry.get("reasoning")
    _lint_model(model, f"{location}.model", state)
    if "reasoning" in entry:
        _lint_reasoning(reasoning, f"{location}.reasoning", state)
    if isinstance(model, str) and (reasoning is None or isinstance(reasoning, str)):
        return (model, reasoning)
    return None


def _lint_model(value: JsonValue | None, location: str, state: LintState) -> None:
    if not isinstance(value, str) or not value.strip() or "/" not in value.strip():
        _add(state, "malformed-model-id", location)
        return
    if state.known_models is not None and value not in state.known_models:
        _add(state, "unknown-model-id", location)


def _lint_reasoning(value: JsonValue | None, location: str, state: LintState) -> None:
    if not isinstance(value, str) or value not in VALID_REASONING:
        _add(state, "invalid-reasoning-value", location)


def summarize(findings: Sequence[Finding]) -> dict[Severity, int]:
    return {severity: sum(finding["severity"] == severity for finding in findings) for severity in SEVERITY_RANK}


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lint an OMO JSONC configuration.")
    parser.add_argument("config_path", type=Path)
    parser.add_argument("--known-models", type=Path, dest="known_models_path")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--min-severity", choices=("error", "warning", "info"), default="error")
    return parser.parse_args(argv)


def _print_report(findings: Sequence[Finding], json_output: bool, error: str | None = None) -> None:
    summary = summarize(findings)
    if json_output:
        payload = {"findings": findings, "summary": summary}
        if error is not None:
            payload["error"] = error
        print(json.dumps(payload, indent=2))
        return
    for finding in findings:
        print(f"{finding['severity']}: {finding['location']}: {finding['rule_id']}: {finding['message']}")
        print(f"  suggestion: {finding['suggestion']}")
    print(f"Summary: error={summary['error']} warning={summary['warning']} info={summary['info']}")
    if error is not None:
        print(f"error: {error}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    options = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = load_config(options.config_path)
        known_models = load_known_models(options.known_models_path) if options.known_models_path else None
    except ConfigFileError as error:
        _print_report([], options.json_output, str(error))
        return 2
    findings = lint_config(config, known_models)
    _print_report(findings, options.json_output)
    threshold = SEVERITY_RANK[options.min_severity]
    return int(any(SEVERITY_RANK[item["severity"]] >= threshold for item in findings))


if __name__ == "__main__":
    raise SystemExit(main())
