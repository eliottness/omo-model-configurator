from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Literal, NoReturn, TypeAlias, TypedDict

import pytest

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
Severity: TypeAlias = Literal["error", "warning"]


class FindingRecord(TypedDict):
    path: str
    kind: str
    severity: Severity
    detail: str
    affected_providers: list[str]


class Report(TypedDict):
    errors: list[FindingRecord]
    warnings: list[FindingRecord]
    note: str


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_tool_schema.py"


def assert_never(value: NoReturn) -> NoReturn:
    raise AssertionError(f"unhandled severity: {value!r}")


def run_from_stdin(payload: str, *, machine_output: bool = True) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT), "--stdin"]
    if machine_output:
        args.append("--json")
    return subprocess.run(args, input=payload, text=True, capture_output=True, check=False)


def parse_report(result: subprocess.CompletedProcess[str]) -> Report:
    report: Report = json.loads(result.stdout)
    return report


def test_non_string_enum_in_tool_file_is_an_error_at_exact_path(tmp_path: Path) -> None:
    # Given
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "name": "example",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "boolean", "enum": [True, False]}},
                },
            }
        ),
        encoding="utf-8",
    )

    # When
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(schema_file), "--json"],
        text=True,
        capture_output=True,
        check=False,
    )

    # Then
    assert result.returncode == 1
    errors = parse_report(result)["errors"]
    assert [(finding["path"], finding["kind"], finding["severity"]) for finding in errors] == [
        ("/parameters/properties/value/enum/0", "non_string_enum", "error"),
        ("/parameters/properties/value/enum/1", "non_string_enum", "error"),
    ]


def test_clean_schema_has_no_findings() -> None:
    # Given
    payload = json.dumps(
        {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": ["small", "large"]}},
            "additionalProperties": False,
        }
    )

    # When
    result = run_from_stdin(payload)

    # Then
    assert result.returncode == 0
    report = parse_report(result)
    assert report["errors"] == []
    assert report["warnings"] == []


def test_type_array_is_flagged() -> None:
    # Given
    payload = json.dumps({"type": "object", "properties": {"value": {"type": ["string", "null"]}}})

    # When
    result = run_from_stdin(payload)

    # Then
    assert result.returncode == 0
    assert [(finding["path"], finding["kind"]) for finding in parse_report(result)["warnings"]] == [("/properties/value/type", "type_array")]


def test_non_string_const_is_flagged_as_error() -> None:
    # Given
    payload = json.dumps({"type": "object", "properties": {"enabled": {"type": "boolean", "const": True}}})

    # When
    result = run_from_stdin(payload)

    # Then
    assert result.returncode == 1
    assert [(finding["path"], finding["kind"]) for finding in parse_report(result)["errors"]] == [("/properties/enabled/const", "non_string_const")]


def test_property_without_type_is_flagged_as_warning() -> None:
    # Given
    payload = json.dumps({"type": "object", "properties": {"value": {"description": "untyped"}}})

    # When
    result = run_from_stdin(payload)

    # Then
    assert result.returncode == 0
    assert [(finding["path"], finding["kind"]) for finding in parse_report(result)["warnings"]] == [("/properties/value/type", "missing_type")]


def test_deeply_nested_non_string_enum_is_found() -> None:
    # Given
    payload = json.dumps(
        {
            "type": "object",
            "properties": {
                "level1": {
                    "type": "object",
                    "properties": {
                        "level2": {
                            "type": "object",
                            "properties": {
                                "level3": {
                                    "type": "object",
                                    "properties": {"value": {"type": "integer", "enum": [7]}},
                                }
                            },
                        }
                    },
                }
            },
        }
    )

    # When
    result = run_from_stdin(payload)

    # Then
    assert result.returncode == 1
    assert parse_report(result)["errors"][0]["path"] == ("/properties/level1/properties/level2/properties/level3/properties/value/enum/0")


def test_malformed_json_exits_two_with_parse_error() -> None:
    # Given
    payload = '{"type": "object"'

    # When
    result = run_from_stdin(payload)

    # Then
    assert result.returncode == 2
    assert "JSON parse error" in result.stderr


@pytest.mark.parametrize(
    ("document", "expected_path"),
    [
        (
            {"name": "direct", "parameters": {"type": "string", "enum": [True]}},
            "/parameters/enum/0",
        ),
        (
            {"function": {"name": "wrapped", "parameters": {"type": "string", "enum": [True]}}},
            "/function/parameters/enum/0",
        ),
        ({"type": "string", "enum": [True]}, "/enum/0"),
    ],
)
def test_supported_tool_entry_shapes_are_scanned(document: JsonValue, expected_path: str) -> None:
    # Given
    payload = json.dumps(document)

    # When
    result = run_from_stdin(payload)

    # Then
    assert result.returncode == 1
    assert parse_report(result)["errors"][0]["path"] == expected_path


@pytest.mark.parametrize(
    ("schema", "expected_kind", "expected_severity"),
    [
        ({"type": "string", "enum": []}, "empty_enum", "error"),
        ({"type": "string", "enum": "not-an-array"}, "non_array_enum", "error"),
        ({"type": "string", "oneOf": [{"type": "string"}]}, "composition", "warning"),
        ({"type": "string", "anyOf": [{"type": "string"}]}, "composition", "warning"),
        ({"type": "string", "allOf": [{"type": "string"}]}, "composition", "warning"),
        (
            {"type": "object", "additionalProperties": {"type": "string"}},
            "schema_additional_properties",
            "warning",
        ),
    ],
)
def test_other_strict_provider_hazards_are_grouped_by_severity(schema: JsonValue, expected_kind: str, expected_severity: Severity) -> None:
    # Given
    payload = json.dumps(schema)

    # When
    result = run_from_stdin(payload)

    # Then
    report = parse_report(result)
    match expected_severity:
        case "error":
            findings = report["errors"]
        case "warning":
            findings = report["warnings"]
        case unreachable:
            assert_never(unreachable)
    assert [finding["kind"] for finding in findings] == [expected_kind]
