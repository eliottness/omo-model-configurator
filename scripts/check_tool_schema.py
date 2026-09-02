#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///


"""Find JSON-Schema constructs that break strict tool-schema providers.

Google/Gemini rejects non-string ``enum`` and ``const`` values; other providers
reject union ``type`` arrays and parameter-level composition keywords. Run this
over a tool schema before pointing an agent at a stricter provider.

See docs/known-issues.md for an unresolved Gemini failure this checker was
written to help narrow down.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, NoReturn, TypeAlias, TypedDict

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
Severity: TypeAlias = Literal["error", "warning"]
FindingGroups: TypeAlias = tuple[tuple["Finding", ...], tuple["Finding", ...]]

MAX_SCHEMA_DEPTH: Final = 100
COMPOSITION_KEYWORDS: Final = ("oneOf", "anyOf", "allOf")
GEMINI_PROVIDERS: Final = ("Google/Gemini",)
STRICT_PROVIDERS: Final = ("strict JSON-Schema providers",)
ALL_PROVIDERS: Final = ("all providers",)


class FindingRecord(TypedDict):
    path: str
    kind: str
    severity: Severity
    detail: str
    affected_providers: list[str]


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    kind: str
    severity: Severity
    detail: str
    affected_providers: tuple[str, ...]

    def to_record(self) -> FindingRecord:
        return {
            "path": self.path,
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
            "affected_providers": list(self.affected_providers),
        }


@dataclass(frozen=True, slots=True)
class ScanLocation:
    path: str = ""
    depth: int = 0

    def child(self, token: str) -> ScanLocation:
        escaped = token.replace("~", "~0").replace("/", "~1")
        return ScanLocation(f"{self.path}/{escaped}", self.depth + 1)


def assert_never(value: NoReturn) -> NoReturn:
    raise AssertionError(f"unhandled JSON value: {value!r}")


def json_type_name(value: JsonValue) -> str:
    match value:
        case None:
            return "null"
        case bool():
            return "boolean"
        case str():
            return "string"
        case int() | float():
            return "number"
        case list():
            return "array"
        case dict():
            return "object"
        case unreachable:
            assert_never(unreachable)


def describe_value(value: JsonValue) -> str:
    return f"{json_type_name(value)} {json.dumps(value, separators=(',', ':'))}"


class SchemaScanner:
    """Recursively collect findings while bounding traversal depth."""

    def __init__(self, max_depth: int = MAX_SCHEMA_DEPTH) -> None:
        self._max_depth = max_depth
        self._findings: list[Finding] = []

    def scan(self, document: JsonValue) -> tuple[Finding, ...]:
        self._walk(document, ScanLocation())
        return tuple(self._findings)

    def _walk(self, node: JsonValue, location: ScanLocation) -> None:
        if location.depth > self._max_depth:
            self._add(Finding(location.path, "max_depth_exceeded", "warning", "traversal depth exceeded", ALL_PROVIDERS))
            return
        match node:
            case dict() as mapping:
                self._inspect(mapping, location)
                for key, value in mapping.items():
                    self._walk(value, location.child(key))
            case list() as items:
                for index, value in enumerate(items):
                    self._walk(value, location.child(str(index)))
            case str() | bool() | int() | float() | None:
                return
            case unreachable:
                assert_never(unreachable)

    def _inspect(self, mapping: dict[str, JsonValue], location: ScanLocation) -> None:
        if "enum" in mapping:
            self._inspect_enum(mapping["enum"], location.child("enum"))
        if "const" in mapping:
            self._inspect_const(mapping["const"], location.child("const"))
        if "type" in mapping:
            match mapping["type"]:
                case list():
                    self._add(Finding(location.child("type").path, "type_array", "warning", "union type array", STRICT_PROVIDERS))
                case str() | bool() | int() | float() | dict() | None:
                    pass
                case unreachable:
                    assert_never(unreachable)
        for keyword in COMPOSITION_KEYWORDS:
            if keyword in mapping:
                detail = f"{keyword} at a parameter level may be rejected or flattened"
                self._add(Finding(location.child(keyword).path, "composition", "warning", detail, STRICT_PROVIDERS))
        self._inspect_additional_properties(mapping, location)
        self._inspect_properties(mapping, location)

    def _inspect_enum(self, value: JsonValue, location: ScanLocation) -> None:
        match value:
            case list() as entries:
                if not entries:
                    self._add(Finding(location.path, "empty_enum", "error", "enum must not be empty", ALL_PROVIDERS))
                for index, entry in enumerate(entries):
                    match entry:
                        case str():
                            pass
                        case bool() | int() | float() | list() | dict() | None:
                            detail = f"enum entries must be strings; found {describe_value(entry)}"
                            self._add(Finding(location.child(str(index)).path, "non_string_enum", "error", detail, GEMINI_PROVIDERS))
                        case unreachable:
                            assert_never(unreachable)
            case str() | bool() | int() | float() | dict() | None:
                detail = f"enum must be an array; found {json_type_name(value)}"
                self._add(Finding(location.path, "non_array_enum", "error", detail, ALL_PROVIDERS))
            case unreachable:
                assert_never(unreachable)

    def _inspect_const(self, value: JsonValue, location: ScanLocation) -> None:
        match value:
            case str():
                pass
            case bool() | int() | float() | list() | dict() | None:
                detail = f"const values must be strings; found {describe_value(value)}"
                self._add(Finding(location.path, "non_string_const", "error", detail, GEMINI_PROVIDERS))
            case unreachable:
                assert_never(unreachable)

    def _inspect_additional_properties(self, mapping: dict[str, JsonValue], location: ScanLocation) -> None:
        if "additionalProperties" not in mapping:
            return
        match mapping["additionalProperties"]:
            case dict():
                path = location.child("additionalProperties").path
                detail = "additionalProperties is a schema object rather than a boolean"
                self._add(Finding(path, "schema_additional_properties", "warning", detail, STRICT_PROVIDERS))
            case str() | bool() | int() | float() | list() | None:
                pass
            case unreachable:
                assert_never(unreachable)

    def _inspect_properties(self, mapping: dict[str, JsonValue], location: ScanLocation) -> None:
        if "properties" not in mapping:
            return
        match mapping["properties"]:
            case dict() as properties:
                for name, schema in properties.items():
                    match schema:
                        case dict() as property_schema:
                            if "type" not in property_schema:
                                path = location.child("properties").child(name).child("type").path
                                self._add(Finding(path, "missing_type", "warning", "property has no type", STRICT_PROVIDERS))
                        case str() | bool() | int() | float() | list() | None:
                            pass
                        case unreachable:
                            assert_never(unreachable)
            case str() | bool() | int() | float() | list() | None:
                pass
            case unreachable:
                assert_never(unreachable)

    def _add(self, finding: Finding) -> None:
        self._findings.append(finding)


def group_findings(findings: Sequence[Finding]) -> FindingGroups:
    errors: list[Finding] = []
    warnings: list[Finding] = []
    for finding in findings:
        match finding.severity:
            case "error":
                errors.append(finding)
            case "warning":
                warnings.append(finding)
            case unreachable:
                assert_never(unreachable)
    return tuple(errors), tuple(warnings)


def print_human(groups: FindingGroups) -> None:
    for title, findings in (("ERRORS", groups[0]), ("WARNINGS", groups[1])):
        print(f"{title} ({len(findings)})")
        print("PATH | KIND | DETAIL | AFFECTED PROVIDERS\n- | - | - | -")
        for finding in findings:
            providers = ", ".join(finding.affected_providers)
            print(f"{finding.path or '/'} | {finding.kind} | {finding.detail} | {providers}")
        print()


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan tool JSON schemas for constructs rejected by strict model providers.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, dest="file_path", help="read JSON from a schema file")
    source.add_argument("--stdin", action="store_true", help="read JSON from standard input")
    parser.add_argument("--json", action="store_true", dest="machine_output", help="emit grouped JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = create_parser().parse_args(argv)
    file_path: Path | None = options.file_path
    machine_output: bool = options.machine_output
    try:
        raw = file_path.read_text(encoding="utf-8") if file_path else sys.stdin.read()
        document: JsonValue = json.loads(raw)
    except json.JSONDecodeError as error:
        print(f"JSON parse error: {error.msg} at line {error.lineno} column {error.colno}", file=sys.stderr)
        return 2
    except RecursionError:
        print("JSON parse error: input nesting exceeds the parser limit", file=sys.stderr)
        return 2
    except (OSError, UnicodeError) as error:
        print(f"Input error: {error}", file=sys.stderr)
        return 2

    groups = group_findings(SchemaScanner().scan(document))
    if machine_output:
        report = {
            "errors": [finding.to_record() for finding in groups[0]],
            "warnings": [finding.to_record() for finding in groups[1]],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(groups)
    return 1 if groups[0] else 0


if __name__ == "__main__":
    raise SystemExit(main())
