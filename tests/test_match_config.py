from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "match_config.py"
EXAMPLE_CONFIG_PATH = Path(__file__).parents[1] / "examples" / "example-omo.jsonc"
CSV_FIELDS = (
    "Model",
    "Artificial Analysis Intelligence Index",
    "Cost per Task USD",
    "Input Price USD/1M Tokens",
    "Output Price USD/1M Tokens",
    "Median Tokens/s",
)


class MatchResult(TypedDict):
    configured_for: str
    config_model_id: str
    reasoning: str
    matched_leaderboard_row: str
    match_kind: str
    speed_tier_stripped: bool
    intelligence: float | None
    cost_per_task_usd: float | None
    input_price_usd_per_million_tokens: float | None
    output_price_usd_per_million_tokens: float | None
    median_tokens_per_second: float | None


class MatchOutput(TypedDict):
    matches: list[MatchResult]
    summary: dict[str, int]


def leaderboard_row(model: str, intelligence: str = "80") -> dict[str, str]:
    return {
        "Model": model,
        "Artificial Analysis Intelligence Index": intelligence,
        "Cost per Task USD": "0.40",
        "Input Price USD/1M Tokens": "1.25",
        "Output Price USD/1M Tokens": "5.00",
        "Median Tokens/s": "75",
    }


def run_match(
    config_text: str,
    leaderboard_rows: list[dict[str, str]],
    tmp_path: Path,
) -> MatchOutput:
    config_path = tmp_path / "omo.jsonc"
    leaderboard_path = tmp_path / "leaderboard.csv"
    config_path.write_text(config_text, encoding="utf-8")
    with leaderboard_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(leaderboard_rows)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--config",
            str(config_path),
            "--leaderboard",
            str(leaderboard_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_exact_tier_match_when_requested_tier_exists(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {
          "planner": {"model": "exampleprovider/GLM-5.3-fast", "reasoning": "max"}
        }
      }
    }"""
    rows = [
        leaderboard_row("GLM-5.3 (high)", "82"),
        leaderboard_row("GLM-5.3 (max)", "88"),
    ]

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    assert output["matches"][0]["matched_leaderboard_row"] == "GLM-5.3 (max)"
    assert output["matches"][0]["match_kind"] == "exact"
    assert output["matches"][0]["speed_tier_stripped"] is True


def test_approximate_tier_match_when_requested_tier_is_missing(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {
          "reviewer": {"model": "exampleprovider/alpha-model", "reasoning": "high"}
        }
      }
    }"""
    rows = [
        leaderboard_row("Alpha Model (low)", "70"),
        leaderboard_row("Alpha Model (medium)", "76"),
    ]

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    assert output["matches"][0]["matched_leaderboard_row"] == "Alpha Model (medium)"
    assert output["matches"][0]["match_kind"] == "approx-tier"


def test_multi_segment_provider_path_uses_last_segment(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {
          "researcher": {"model": "exampleprovider/example-org/GLM-5.3", "reasoning": "max"}
        }
      }
    }"""

    # When
    output = run_match(config, [leaderboard_row("GLM-5.3 (max)")], tmp_path)

    # Then
    assert output["matches"][0]["match_kind"] == "exact"


def test_dot_and_hyphen_versions_normalize_equivalently(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {
          "researcher": {"model": "exampleprovider/GLM-5.3", "reasoning": "max"}
        }
      }
    }"""

    # When
    output = run_match(config, [leaderboard_row("GLM-5-3 (max)")], tmp_path)

    # Then
    assert output["matches"][0]["matched_leaderboard_row"] == "GLM-5-3 (max)"


def test_bare_string_entries_are_parsed_for_agents_and_categories(
    tmp_path: Path,
) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {
          "builder": {"fallback_models": ["exampleprovider/alpha-model"]}
        },
        "categories": {
          "quick": {"models": ["exampleprovider/beta-model"]}
        }
      }
    }"""
    rows = [leaderboard_row("Alpha Model (max)"), leaderboard_row("Beta Model (max)")]

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    assert {result["configured_for"] for result in output["matches"]} == {
        "agent:builder",
        "category:quick",
    }
    assert {result["reasoning"] for result in output["matches"]} == {"auto"}


def test_unmatched_model_is_reported_instead_of_dropped(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "categories": {
          "general": {
            "models": [
              {"model": "exampleprovider/known-model", "reasoning": "low"},
              {"model": "exampleprovider/unlisted-model", "reasoning": "medium"}
            ]
          }
        }
      }
    }"""

    # When
    output = run_match(config, [leaderboard_row("Known Model (low)")], tmp_path)

    # Then
    unmatched = next(
        result
        for result in output["matches"]
        if result["config_model_id"].endswith("unlisted-model")
    )
    assert unmatched["matched_leaderboard_row"] == "NOT_BENCHMARKED"
    assert unmatched["match_kind"] == "not-benchmarked"
    assert output["summary"] == {"exact": 1, "approx-tier": 0, "not-benchmarked": 1}


def test_jsonc_comments_and_trailing_commas_parse_successfully(tmp_path: Path) -> None:
    # Given
    config = """{
      // A line comment must be ignored.
      "[opencode]": {
        /* A block comment must also be ignored. */
        "agents": {
          "planner": {
            "model": "exampleprovider/alpha-model",
            "reasoning": "max",
          },
        },
      },
    }"""

    # When
    output = run_match(config, [leaderboard_row("Alpha Model (max)")], tmp_path)

    # Then
    assert output["summary"]["exact"] == 1


def test_example_config_exercises_all_supported_entry_shapes(tmp_path: Path) -> None:
    # Given
    assert EXAMPLE_CONFIG_PATH.exists()
    config = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
    rows = [
        leaderboard_row("GPT-5.6 Sol (high)", "91"),
        leaderboard_row("Claude Opus 5 (xhigh)", "93"),
        leaderboard_row("GLM-5.3 (max)", "89"),
    ]

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    assert output["summary"] == {"exact": 3, "approx-tier": 2, "not-benchmarked": 1}
    assert {result["configured_for"] for result in output["matches"]} == {
        "agent:planner",
        "agent:reviewer",
        "category:deep",
    }
