from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "lint_omo_config.py"


def run_linter(
    tmp_path: Path,
    config: str,
    extra_args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    config_path = tmp_path / "omo.jsonc"
    config_path.write_text(config, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(config_path), "--json", *extra_args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_reports_deprecated_fallback_models_at_agent_chain(tmp_path: Path) -> None:
    # Given
    config = (
        '{"[opencode]":{"agents":{"oracle":{"fallback_models":'
        '["exampleprovider/fallback"]}}}}'
    )

    # When
    result = run_linter(tmp_path, config)

    # Then
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    deprecated = [
        finding
        for finding in payload["findings"]
        if finding["rule_id"] == "deprecated-fallback-models"
    ]
    assert len(deprecated) == 1
    assert set(deprecated[0]) == {
        "rule_id",
        "severity",
        "location",
        "message",
        "suggestion",
    }
    assert deprecated[0]["severity"] == "warning"
    assert deprecated[0]["location"] == "[opencode].agents.oracle.fallback_models"
    assert payload["summary"]["warning"] == 1


def test_invalid_reasoning_exits_one(tmp_path: Path) -> None:
    # Given
    config = (
        '{"[opencode]":{"agents":{"oracle":{'
        '"model":"exampleprovider/primary","reasoning":"ultra"}}}}'
    )

    # When
    result = run_linter(tmp_path, config)

    # Then
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    invalid = [
        finding
        for finding in payload["findings"]
        if finding["rule_id"] == "invalid-reasoning-value"
    ]
    assert [(finding["severity"], finding["location"]) for finding in invalid] == [
        ("error", "[opencode].agents.oracle.reasoning")
    ]


def test_bare_model_name_is_malformed(tmp_path: Path) -> None:
    # Given
    config = '{"[opencode]":{"agents":{"oracle":{"model":"gpt-5.6-sol"}}}}'

    # When
    result = run_linter(tmp_path, config)

    # Then
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    malformed = [
        finding
        for finding in payload["findings"]
        if finding["rule_id"] == "malformed-model-id"
    ]
    assert [finding["location"] for finding in malformed] == [
        "[opencode].agents.oracle.model"
    ]


def test_duplicate_pair_in_category_chain_is_flagged(tmp_path: Path) -> None:
    # Given
    config = (
        '{"[opencode]":{"categories":{"deep":{"models":['
        '{"model":"exampleprovider/reasoner","reasoning":"high"},'
        '{"model":"exampleprovider/reasoner","reasoning":"high"}'
        ']}}}}'
    )

    # When
    result = run_linter(tmp_path, config)

    # Then
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    duplicates = [
        finding
        for finding in payload["findings"]
        if finding["rule_id"] == "duplicate-chain-entry"
    ]
    assert [finding["location"] for finding in duplicates] == [
        "[opencode].categories.deep.models[1]"
    ]


def test_empty_models_chain_is_an_error(tmp_path: Path) -> None:
    # Given
    config = '{"[opencode]":{"categories":{"deep":{"models":[]}}}}'

    # When
    result = run_linter(tmp_path, config)

    # Then
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    empty = [
        finding
        for finding in payload["findings"]
        if finding["rule_id"] == "empty-chain"
    ]
    assert [(finding["severity"], finding["location"]) for finding in empty] == [
        ("error", "[opencode].categories.deep.models")
    ]


def test_unknown_model_check_only_runs_with_known_models_file(tmp_path: Path) -> None:
    # Given
    config = (
        '{"[opencode]":{"agents":{"oracle":{'
        '"model":"exampleprovider/unlisted","reasoning":"high"}}}}'
    )
    known_models_path = tmp_path / "known-models.txt"
    known_models_path.write_text("exampleprovider/listed\n", encoding="utf-8")

    # When
    without_known_models = run_linter(tmp_path, config)
    with_known_models = run_linter(
        tmp_path,
        config,
        ("--known-models", str(known_models_path), "--min-severity", "warning"),
    )

    # Then
    without_payload = json.loads(without_known_models.stdout)
    assert all(
        finding["rule_id"] != "unknown-model-id"
        for finding in without_payload["findings"]
    )
    assert without_known_models.returncode == 0
    with_payload = json.loads(with_known_models.stdout)
    unknown = [
        finding
        for finding in with_payload["findings"]
        if finding["rule_id"] == "unknown-model-id"
    ]
    assert [finding["location"] for finding in unknown] == [
        "[opencode].agents.oracle.model"
    ]
    assert with_known_models.returncode == 1


def test_clean_config_has_no_findings(tmp_path: Path) -> None:
    # Given
    config = (
        '{"[opencode]":{'
        '"agents":{"oracle":{"model":"exampleprovider/primary","reasoning":"high"}},'
        '"categories":{"deep":{"models":['
        '"exampleprovider/first","exampleprovider/second"]}}}}'
    )

    # When
    result = run_linter(tmp_path, config)

    # Then
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "findings": [],
        "summary": {"error": 0, "warning": 0, "info": 0},
    }


def test_jsonc_comments_and_trailing_commas_parse(tmp_path: Path) -> None:
    # Given
    config = """
    {
      // A URL-like model remains intact while this comment is removed.
      "[opencode]": {
        "agents": {
          "oracle": {
            "model": "exampleprovider/primary", /* block comment */
            "reasoning": "high",
          },
        },
      },
    }
    """

    # When
    result = run_linter(tmp_path, config)

    # Then
    assert result.returncode == 0
    assert json.loads(result.stdout)["findings"] == []


def test_primary_repeated_in_own_fallback_chain_is_flagged(tmp_path: Path) -> None:
    # Given
    config = (
        '{"[opencode]":{"agents":{"oracle":{'
        '"model":"exampleprovider/primary","reasoning":"high",'
        '"fallback_models":['
        '{"model":"exampleprovider/primary","reasoning":"high"},'
        '"exampleprovider/secondary"]}}}}'
    )

    # When
    result = run_linter(tmp_path, config)

    # Then
    payload = json.loads(result.stdout)
    primary_duplicates = [
        finding
        for finding in payload["findings"]
        if finding["rule_id"] == "primary-duplicated-in-fallback"
    ]
    assert [finding["location"] for finding in primary_duplicates] == [
        "[opencode].agents.oracle.fallback_models[0]"
    ]


def test_single_entry_chain_reports_missing_fallback_coverage(tmp_path: Path) -> None:
    # Given
    config = (
        '{"[opencode]":{"categories":{"deep":{'
        '"models":["exampleprovider/only"]}}}}'
    )

    # When
    result = run_linter(tmp_path, config)

    # Then
    payload = json.loads(result.stdout)
    single = [
        finding
        for finding in payload["findings"]
        if finding["rule_id"] == "single-entry-chain"
    ]
    assert [(finding["severity"], finding["location"]) for finding in single] == [
        ("info", "[opencode].categories.deep.models")
    ]


def test_malformed_jsonc_exits_two(tmp_path: Path) -> None:
    # Given
    config = '{"[opencode]": {'

    # When
    result = run_linter(tmp_path, config)

    # Then
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["findings"] == []
    assert payload["summary"] == {"error": 0, "warning": 0, "info": 0}
    assert isinstance(payload["error"], str)


def test_variant_distinguishes_primary_from_fallback_entry(tmp_path: Path) -> None:
    # Given a primary and a fallback that differ only by `variant`
    config = (
        '{"[opencode]":{"agents":{"planner":{'
        '"model":"exampleprovider/alpha","variant":"high",'
        '"fallback_models":[{"model":"exampleprovider/alpha","variant":"low"}]'
        "}}}}"
    )

    # When
    result = run_linter(tmp_path, config)

    # Then they are not reported as the same pair
    payload = json.loads(result.stdout)
    duplicates = [
        finding
        for finding in payload["findings"]
        if finding["rule_id"] == "primary-duplicated-in-fallback"
    ]
    assert duplicates == []
