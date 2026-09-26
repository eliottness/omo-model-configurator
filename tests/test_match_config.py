from __future__ import annotations

import csv
import json
import os
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
    matched_leaderboard_row: str | None
    match_kind: str
    match_reason: str
    warning: str | None
    speed_tier_stripped: bool
    configured_model_name: str
    leaderboard_model_name: str | None
    benchmark_reasoning_tier: str | None
    evaluation_qualifier: str | None
    config_path: str
    slot_index: int
    chain_key: str
    chain_index: int
    intelligence: float | None
    cost_per_task_usd: float | None
    input_price_usd_per_million_tokens: float | None
    output_price_usd_per_million_tokens: float | None
    median_tokens_per_second: float | None
    metric_metadata: dict[str, "MetricMetadata"]


class MetricMetadata(TypedDict):
    available: bool
    estimated: bool
    provenance: str


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
    *,
    harness: str = "opencode",
    profile: str | None = None,
    runtime_module: str | None = None,
) -> MatchOutput:
    config_path = tmp_path / "omo.jsonc"
    leaderboard_path = tmp_path / "leaderboard.csv"
    config_path.write_text(config_text, encoding="utf-8")
    with leaderboard_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(leaderboard_rows)

    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "--config",
        str(config_path),
        "--leaderboard",
        str(leaderboard_path),
        "--harness",
        harness,
        "--json",
    ]
    if profile is not None:
        command.extend(["--profile", profile])
    environment = os.environ.copy()
    if runtime_module is not None:
        runtime_path = tmp_path / "runtime_config.py"
        runtime_path.write_text(runtime_module, encoding="utf-8")
        environment["PYTHONPATH"] = str(tmp_path)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_exact_tier_match_when_requested_tier_exists(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {
          "planner": {"model": "exampleprovider/GLM-5.3", "reasoning": "max"}
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
    assert output["matches"][0]["speed_tier_stripped"] is False


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
    assert output["matches"][0]["match_kind"] == "approximate-effort"
    assert output["matches"][0]["match_reason"] == "requested-effort-unavailable"


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
    assert unmatched["matched_leaderboard_row"] is None
    assert unmatched["match_kind"] == "unmatched"
    assert unmatched["match_reason"] == "row-absent-from-input"
    assert "does not establish" in (unmatched["warning"] or "")
    assert output["summary"] == {"exact": 1, "unmatched": 1}


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
        leaderboard_row("Claude Opus 4.8 (high)", "93"),
        leaderboard_row("gpt-oss-120B (xhigh)", "80"),
        leaderboard_row("GLM-5.3 (max)", "89"),
        leaderboard_row("Gemini 3.5 Flash Lite", "70"),
    ]

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    assert output["summary"] == {"exact": 4, "effort-unresolved": 1, "unmatched": 1}
    assert {result["configured_for"] for result in output["matches"]} == {
        "agent:planner",
        "agent:reviewer",
        "category:deep",
    }


def test_agent_models_chain_is_read(tmp_path: Path) -> None:
    # Given an agent chain using the recommended `models` key
    config = """{
      "[opencode]": {
        "agents": {
          "planner": {
            "models": [
              {"model": "exampleprovider/alpha", "reasoning": "high"},
              {"model": "exampleprovider/beta", "reasoning": "high"}
            ]
          }
        }
      }
    }"""
    rows = [leaderboard_row("alpha (high)", "80"), leaderboard_row("beta (high)", "70")]

    # When
    output = run_match(config, rows, tmp_path)

    # Then both rungs are reported, not silently dropped
    assert len(output["matches"]) == 2


def test_category_fallback_models_chain_is_read(tmp_path: Path) -> None:
    # Given a category chain using the deprecated `fallback_models` key
    config = """{
      "[opencode]": {
        "categories": {
          "deep": {
            "fallback_models": [{"model": "exampleprovider/alpha", "reasoning": "high"}]
          }
        }
      }
    }"""
    rows = [leaderboard_row("alpha (high)", "80")]

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    assert len(output["matches"]) == 1


def test_both_chain_keys_produce_identical_matches(tmp_path: Path) -> None:
    # Given the same chain expressed with each accepted key
    template = """{{
      "[opencode]": {{
        "agents": {{"planner": {{"{key}": [
          {{"model": "exampleprovider/alpha", "reasoning": "high"}}
        ]}}}}
      }}
    }}"""
    rows = [leaderboard_row("alpha (high)", "80")]

    # When
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    with_models = run_match(template.format(key="models"), rows, dir_a)
    with_fallback = run_match(template.format(key="fallback_models"), rows, dir_b)

    # Then the measurements stay identical, while source paths remain accurate.
    assert with_models["summary"] == with_fallback["summary"]
    left, right = with_models["matches"][0], with_fallback["matches"][0]
    assert left["chain_key"] == "models"
    assert right["chain_key"] == "fallback_models"
    assert left["config_path"].endswith(".models[0]")
    assert right["config_path"].endswith(".fallback_models[0]")
    assert {k: v for k, v in left.items() if k not in {"chain_key", "config_path"}} == {
        k: v for k, v in right.items() if k not in {"chain_key", "config_path"}
    }


def test_variant_is_honored_like_reasoning(tmp_path: Path) -> None:
    # Given the upstream-documented `variant` key instead of `reasoning`
    config = """{
      "[opencode]": {
        "agents": {"planner": {"model": "exampleprovider/alpha", "variant": "low"}}
      }
    }"""
    rows = [leaderboard_row("alpha (low)", "60"), leaderboard_row("alpha (max)", "90")]

    # When
    output = run_match(config, rows, tmp_path)

    # Then the low tier matches exactly instead of snapping to max
    match = output["matches"][0]
    assert match["matched_leaderboard_row"] == "alpha (low)"
    assert match["match_kind"] == "exact"


def test_minimal_reasoning_matches_minimal_tier_exactly(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {"planner": {"model": "exampleprovider/alpha", "reasoning": "minimal"}}
      }
    }"""
    rows = [
        leaderboard_row("alpha (minimal)", "55"),
        leaderboard_row("alpha (low)", "60"),
    ]

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    assert output["matches"][0]["match_kind"] == "exact"
    assert output["matches"][0]["benchmark_reasoning_tier"] == "minimal"


def test_minimal_to_low_comparison_is_explicitly_approximate(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {"planner": {"model": "exampleprovider/alpha", "reasoning": "minimal"}}
      }
    }"""

    # When
    output = run_match(config, [leaderboard_row("alpha (low)", "60")], tmp_path)

    # Then
    match = output["matches"][0]
    assert match["match_kind"] == "approximate-effort"
    assert match["match_reason"] == "requested-effort-unavailable"
    assert match["benchmark_reasoning_tier"] == "low"


def test_double_dash_missing_marker_is_treated_as_absent(tmp_path: Path) -> None:
    # Given the marker Artificial Analysis actually emits for a missing value,
    # which appears in every row of a real scrape
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/alpha", "reasoning": "high"}}
      }
    }"""
    rows = [leaderboard_row("alpha (high)")]
    rows[0]["Median Tokens/s"] = "--"

    # When
    output = run_match(config, rows, tmp_path)

    # Then the row still matches and the cell is null, rather than crashing
    assert output["matches"][0]["match_kind"] == "exact"
    assert output["matches"][0]["median_tokens_per_second"] is None


def test_estimate_marker_is_parsed_as_a_number(tmp_path: Path) -> None:
    # Given AA's trailing-asterisk estimate marker
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/alpha", "reasoning": "high"}}
      }
    }"""
    rows = [leaderboard_row("alpha (high)")]
    rows[0]["Artificial Analysis Intelligence Index"] = "46*"

    # When
    output = run_match(config, rows, tmp_path)

    # Then the value survives as a number with its estimate marker preserved
    assert output["matches"][0]["intelligence"] == 46.0
    assert output["matches"][0]["metric_metadata"]["intelligence"] == {
        "available": True,
        "estimated": True,
        "provenance": "estimated-benchmark-row",
    }


def test_word_order_difference_still_matches(tmp_path: Path) -> None:
    # Given a config id and a leaderboard name that differ only in word order,
    # which is how AA publishes several Claude models
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/claude-haiku-4-5"}}
      }
    }"""
    rows = [leaderboard_row("Claude 4.5 Haiku")]

    # When
    output = run_match(config, rows, tmp_path)

    # Then it is not reported as unbenchmarked
    assert output["matches"][0]["matched_leaderboard_row"] == "Claude 4.5 Haiku"


def test_reordered_version_numbers_do_not_match(tmp_path: Path) -> None:
    # Given two distinct models whose tokens are permutations of each other,
    # word-order tolerance must not collapse them
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/GLM-5.3", "reasoning": "max"}}
      }
    }"""
    rows = [leaderboard_row("GLM-3.5 (max)")]

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    assert output["matches"][0]["match_kind"] == "unmatched"


def test_with_fallback_label_preserves_effort_and_qualifier(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/claude-opus-5-5", "reasoning": "max"}}
      }
    }"""

    # When
    output = run_match(
        config,
        [leaderboard_row("Claude Opus 5.5 (max with fallback)")],
        tmp_path,
    )

    # Then
    match = output["matches"][0]
    assert match["match_kind"] == "exact"
    assert match["benchmark_reasoning_tier"] == "max"
    assert match["evaluation_qualifier"] == "with fallback"


def test_non_reasoning_compound_label_keeps_qualifier_separate(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/claude-sonnet-4-6", "reasoning": "off"}}
      }
    }"""

    # When
    output = run_match(
        config,
        [leaderboard_row("Claude Sonnet 4.6 (Non-reasoning, high)")],
        tmp_path,
    )

    # Then
    match = output["matches"][0]
    assert match["match_kind"] == "exact"
    assert match["benchmark_reasoning_tier"] == "non-reasoning"
    assert match["evaluation_qualifier"] == "high"


def test_different_evaluation_policies_are_not_ranked_as_equivalent(tmp_path: Path) -> None:
    config = """{"[opencode]": {"agents": {
      "a": {"model": "p/alpha", "reasoning": "max"}
    }}}"""
    output = run_match(config, [
        leaderboard_row("Alpha (max)", "7"),
        leaderboard_row("Alpha (max with fallback)", "9"),
    ], tmp_path)
    match = output["matches"][0]
    assert match["matched_leaderboard_row"] is None
    assert match["match_reason"] == "evaluation-policy-ambiguous"
    assert len(match["benchmark_candidates"]) == 2


def test_unlabeled_row_is_not_silently_non_reasoning(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/alpha", "reasoning": "off"}}
      }
    }"""

    # When
    output = run_match(config, [leaderboard_row("Alpha")], tmp_path)

    # Then
    match = output["matches"][0]
    assert match["match_kind"] == "effort-unresolved"
    assert match["match_reason"] == "benchmark-effort-unlabeled"
    assert match["benchmark_reasoning_tier"] is None


def test_pro_suffix_is_part_of_model_identity(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/gpt-6-sol-pro", "reasoning": "medium"}}
      }
    }"""

    # When
    output = run_match(
        config, [leaderboard_row("GPT-6 Sol (medium)")], tmp_path
    )

    # Then
    match = output["matches"][0]
    assert match["match_kind"] == "unmatched"
    assert match["configured_model_name"] == "gpt-6-sol-pro"
    assert match["leaderboard_model_name"] is None


def test_fast_suffix_is_labeled_base_model_proxy_never_exact(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/gpt-6-luna-fast", "reasoning": "low"}}
      }
    }"""

    # When
    output = run_match(
        config, [leaderboard_row("GPT-6 Luna (low)")], tmp_path
    )

    # Then
    match = output["matches"][0]
    assert match["match_kind"] == "base-model-proxy"
    assert match["configured_model_name"] == "gpt-6-luna-fast"
    assert match["leaderboard_model_name"] == "GPT-6 Luna"
    assert match["speed_tier_stripped"] is True
    assert match["metric_metadata"]["intelligence"]["provenance"] == (
        "base-model-proxy"
    )
    assert "not measured for the configured -fast model" in (match["warning"] or "")


def test_auto_effort_remains_unresolved_instead_of_snapping_to_max(
    tmp_path: Path,
) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/alpha"}}
      }
    }"""
    rows = [
        leaderboard_row("Alpha (low)", "60"),
        leaderboard_row("Alpha (max)", "90"),
    ]

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    match = output["matches"][0]
    assert match["match_kind"] == "effort-unresolved"
    assert match["match_reason"] == "configured-effort-auto"
    assert match["matched_leaderboard_row"] is None
    assert match["intelligence"] is None


def test_missing_metric_cell_is_distinct_from_missing_model_row(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {"a": {"model": "p/alpha", "reasoning": "high"}}
      }
    }"""
    rows = [leaderboard_row("Alpha (high)")]
    rows[0]["Median Tokens/s"] = "--"

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    match = output["matches"][0]
    assert match["match_kind"] == "exact"
    assert match["metric_metadata"]["median_tokens_per_second"] == {
        "available": False,
        "estimated": False,
        "provenance": "missing-benchmark-cell",
    }


def test_slot_and_chain_order_and_paths_are_preserved(tmp_path: Path) -> None:
    # Given
    config = """{
      "[opencode]": {
        "agents": {
          "first": {"models": [
            {"model": "p/low-score", "reasoning": "high"},
            {"model": "p/high-score", "reasoning": "high"}
          ]},
          "second": {"model": "p/mid-score", "reasoning": "high"}
        }
      }
    }"""
    rows = [
        leaderboard_row("Low Score (high)", "10"),
        leaderboard_row("High Score (high)", "90"),
        leaderboard_row("Mid Score (high)", "50"),
    ]

    # When
    output = run_match(config, rows, tmp_path)

    # Then
    matches = output["matches"]
    assert [match["config_model_id"] for match in matches] == [
        "p/low-score",
        "p/high-score",
        "p/mid-score",
    ]
    assert [match["slot_index"] for match in matches] == [0, 0, 1]
    assert [match["chain_index"] for match in matches] == [0, 1, 0]
    assert matches[0]["config_path"] == "[opencode].agents.first.models[0]"
    assert matches[2]["config_path"] == "[opencode].agents.second.model"


def test_harness_and_profile_are_resolved_by_runtime_helper(tmp_path: Path) -> None:
    # Given
    config = """{
      "profiles": {
        "work": {
          "[native]": {
            "agents": {
              "a": {"model": "p/alpha", "reasoning": "high"}
            }
          }
        }
      }
    }"""

    # When
    output = run_match(
        config,
        [leaderboard_row("Alpha (high)")],
        tmp_path,
        harness="native",
        profile="work",
    )

    # Then
    assert output["matches"][0]["match_kind"] == "exact"
    assert output["matches"][0]["config_path"] == "native[work].agents.a.model"


def test_auto_effort_keeps_a_single_unlabeled_measurement(tmp_path: Path) -> None:
    config = '{"[native]":{"agents":{"search":{"model":"p/example-flash"}}}}'
    output = run_match(
        config, [leaderboard_row("Example Flash", "73")], tmp_path, harness="native",
    )
    result = output["matches"][0]
    assert result["matched_leaderboard_row"] == "Example Flash"
    assert result["intelligence"] == 73
    assert result["benchmark_reasoning_tier"] is None
    assert result["match_reason"] == "benchmark-effort-unlabeled"
