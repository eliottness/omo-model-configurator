#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""# noqa: SIZE_OK - requested single-file CLI for bare-clone portability."""


from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

MODEL_COLUMN: Final = "Model"
INTELLIGENCE_COLUMN: Final = "Artificial Analysis Intelligence Index"
COST_COLUMN: Final = "Cost per Task USD"
INPUT_PRICE_COLUMN: Final = "Input Price USD/1M Tokens"
OUTPUT_PRICE_COLUMN: Final = "Output Price USD/1M Tokens"
TOKENS_COLUMN: Final = "Median Tokens/s"
REQUIRED_COLUMNS: Final = (
    MODEL_COLUMN,
    INTELLIGENCE_COLUMN,
    COST_COLUMN,
    INPUT_PRICE_COLUMN,
    OUTPUT_PRICE_COLUMN,
    TOKENS_COLUMN,
)
TIER_PATTERN: Final = re.compile(
    r"^(?P<name>.*?)\s*\((?P<tier>max|xhigh|high|medium|low|non-reasoning)\)\s*$",
    re.IGNORECASE,
)
SPEED_SUFFIX_PATTERN: Final = re.compile(r"-(?:fast|pro)$", re.IGNORECASE)
NON_ALPHANUMERIC_PATTERN: Final = re.compile(r"[^a-z0-9]")
DASH_RUN_PATTERN: Final = re.compile(r"[-\u2010-\u2015]+")
ALPHA_RUN_PATTERN: Final = re.compile(r"[a-z]+")
DIGIT_RUN_PATTERN: Final = re.compile(r"\d+")
TRAILING_COMMA_PATTERN: Final = re.compile(r",(?=\s*[}\]])")
TIER_RANK: Final = {
    "non-reasoning": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "xhigh": 4,
    "max": 5,
}
REASONING_TIER: Final = {
    "off": "non-reasoning",
    # No leaderboard row is ever published as a "minimal" tier; REASONING_RANK
    # already treats minimal and low as the same rank, so map it to low.
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
    "auto": "auto",
}
CHAIN_KEYS: Final = ("models", "fallback_models")
REASONING_RANK: Final = {
    "off": 0,
    "minimal": 1,
    "low": 1,
    "medium": 2,
    "high": 3,
    "xhigh": 4,
    "max": 5,
    "auto": 5,
}


@dataclass(frozen=True, slots=True)
class PathMissingError(Exception):
    path: Path

    def __str__(self) -> str:
        return f"path does not exist: {self.path}"


@dataclass(frozen=True, slots=True)
class DataFormatError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class ConfiguredModel:
    configured_for: str
    model_id: str
    reasoning: str


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    display_name: str
    base_name: str
    normalized_name: str
    reasoning_tier: str
    speed_tier_stripped: bool
    intelligence: float | None
    cost_per_task_usd: float | None
    input_price_usd_per_million_tokens: float | None
    output_price_usd_per_million_tokens: float | None
    median_tokens_per_second: float | None


@dataclass(frozen=True, slots=True)
class MatchResult:
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


def strip_jsonc_comments(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
        elif character == '"':
            in_string = True
            output.append(character)
            index += 1
        elif character == "/" and following == "/":
            newline = text.find("\n", index + 2)
            index = len(text) if newline == -1 else newline
        elif character == "/" and following == "*":
            closing = text.find("*/", index + 2)
            if closing == -1:
                raise DataFormatError("unterminated JSONC block comment")
            index = closing + 2
        else:
            output.append(character)
            index += 1
    return "".join(output)


def load_jsonc(path: Path) -> dict[str, JsonValue]:
    ensure_path_exists(path)
    text = path.read_text(encoding="utf-8")
    cleaned = TRAILING_COMMA_PATTERN.sub("", strip_jsonc_comments(text))
    try:
        parsed: JsonValue = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise DataFormatError(f"invalid JSONC in {path}: {error.msg}") from error
    if not isinstance(parsed, dict):
        raise DataFormatError(f"OMO config root must be an object: {path}")
    return parsed


def ensure_path_exists(path: Path) -> None:
    if not path.exists():
        raise PathMissingError(path)


def as_mapping(value: JsonValue | None) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def parse_reasoning(value: JsonValue | None) -> str:
    reasoning = value if isinstance(value, str) else "auto"
    if reasoning not in REASONING_TIER:
        raise DataFormatError(f"unsupported reasoning tier: {reasoning}")
    return reasoning


def effective_reasoning(entry: dict[str, JsonValue]) -> JsonValue | None:
    """Return `reasoning`, falling back to the equivalent `variant` key."""
    reasoning = entry.get("reasoning")
    return reasoning if reasoning is not None else entry.get("variant")


def parse_model_entry(value: JsonValue, configured_for: str) -> ConfiguredModel:
    if isinstance(value, str):
        return ConfiguredModel(configured_for, value, "auto")
    if not isinstance(value, dict):
        raise DataFormatError(
            f"model entry for {configured_for} must be a string or object"
        )
    model = value.get("model")
    if not isinstance(model, str):
        raise DataFormatError(
            f"model entry for {configured_for} is missing a string model"
        )
    return ConfiguredModel(
        configured_for, model, parse_reasoning(effective_reasoning(value))
    )


def extract_entity_models(
    entity: dict[str, JsonValue], configured_for: str
) -> list[ConfiguredModel]:
    configured: list[ConfiguredModel] = []
    model = entity.get("model")
    if model is not None:
        configured.append(
            parse_model_entry(
                {
                    "model": model,
                    "reasoning": entity.get("reasoning"),
                    "variant": entity.get("variant"),
                },
                configured_for,
            )
        )
    for chain_key in CHAIN_KEYS:
        chain = entity.get(chain_key)
        if isinstance(chain, list):
            configured.extend(
                parse_model_entry(entry, configured_for) for entry in chain
            )
    return configured


def extract_configured_models(config: dict[str, JsonValue]) -> list[ConfiguredModel]:
    opencode = as_mapping(config.get("[opencode]"))
    configured: list[ConfiguredModel] = []
    for section, prefix in (("agents", "agent"), ("categories", "category")):
        for name, value in as_mapping(opencode.get(section)).items():
            configured.extend(
                extract_entity_models(as_mapping(value), f"{prefix}:{name}")
            )
    return configured


def token_key(name: str) -> str:
    """Word-order-insensitive key for a model name.

    AA publishes some models with the version ahead of the tier word ("Claude
    4.5 Haiku") where the config id puts it after ("claude-haiku-4-5"). Sorting
    the alphabetic tokens makes that ordering irrelevant, while numeric tokens
    keep their original order so GLM-5.3 and GLM-3.5 stay distinct.
    """
    lowered = SPEED_SUFFIX_PATTERN.sub("", name.lower())
    words = "".join(sorted(ALPHA_RUN_PATTERN.findall(lowered)))
    digits = ".".join(DIGIT_RUN_PATTERN.findall(lowered))
    return f"{words}|{digits}"


def normalize_model_name(name: str) -> tuple[str, bool]:
    lowered = name.lower()
    without_speed_suffix, substitutions = SPEED_SUFFIX_PATTERN.subn("", lowered)
    return NON_ALPHANUMERIC_PATTERN.sub("", without_speed_suffix), substitutions > 0


def parse_number(value: str | None, column: str) -> float | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    # Artificial Analysis writes a missing cell as a dash run ("-", "--") or an
    # en/em dash, and marks an estimated figure with a trailing asterisk.
    if text.lower() in {"n/a", "na"} or DASH_RUN_PATTERN.fullmatch(text):
        return None
    cleaned = (
        text.rstrip("*").replace("$", "").replace(",", "").replace("%", "").strip()
    )
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError as error:
        raise DataFormatError(
            f"invalid numeric value in {column}: {value!r}"
        ) from error


def load_leaderboard(path: Path) -> list[LeaderboardRow]:
    ensure_path_exists(path)
    rows: list[LeaderboardRow] = []
    with path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        if not fieldnames or fieldnames[0] != MODEL_COLUMN:
            raise DataFormatError(f"leaderboard first column must be {MODEL_COLUMN!r}")
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            raise DataFormatError(
                f"leaderboard is missing columns: {', '.join(missing)}"
            )
        for raw_row in reader:
            display_name = raw_row[MODEL_COLUMN]
            if display_name is None:
                raise DataFormatError("leaderboard row has no model name")
            tier_match = TIER_PATTERN.match(display_name)
            base_name = tier_match.group("name") if tier_match else display_name
            reasoning_tier = (
                tier_match.group("tier").lower() if tier_match else "non-reasoning"
            )
            normalized_name, speed_stripped = normalize_model_name(base_name)
            rows.append(
                LeaderboardRow(
                    display_name=display_name,
                    base_name=base_name,
                    normalized_name=normalized_name,
                    reasoning_tier=reasoning_tier,
                    speed_tier_stripped=speed_stripped,
                    intelligence=parse_number(
                        raw_row[INTELLIGENCE_COLUMN], INTELLIGENCE_COLUMN
                    ),
                    cost_per_task_usd=parse_number(raw_row[COST_COLUMN], COST_COLUMN),
                    input_price_usd_per_million_tokens=parse_number(
                        raw_row[INPUT_PRICE_COLUMN], INPUT_PRICE_COLUMN
                    ),
                    output_price_usd_per_million_tokens=parse_number(
                        raw_row[OUTPUT_PRICE_COLUMN], OUTPUT_PRICE_COLUMN
                    ),
                    median_tokens_per_second=parse_number(
                        raw_row[TOKENS_COLUMN], TOKENS_COLUMN
                    ),
                )
            )
    return rows


def choose_candidate(
    candidates: list[LeaderboardRow], reasoning: str
) -> tuple[LeaderboardRow, str]:
    requested_tier = REASONING_TIER[reasoning]
    exact = [
        candidate
        for candidate in candidates
        if candidate.reasoning_tier == requested_tier
    ]
    if exact:
        return max(exact, key=lambda row: row.intelligence or float("-inf")), "exact"
    requested_rank = REASONING_RANK[reasoning]
    nearest = min(
        candidates,
        key=lambda row: (
            abs(TIER_RANK[row.reasoning_tier] - requested_rank),
            -TIER_RANK[row.reasoning_tier],
        ),
    )
    return nearest, "approx-tier"


def match_models(
    configured_models: list[ConfiguredModel],
    leaderboard_rows: list[LeaderboardRow],
) -> list[MatchResult]:
    by_name: dict[str, list[LeaderboardRow]] = {}
    by_tokens: dict[str, list[LeaderboardRow]] = {}
    for row in leaderboard_rows:
        by_name.setdefault(row.normalized_name, []).append(row)
        by_tokens.setdefault(token_key(row.base_name), []).append(row)
    results: list[MatchResult] = []
    for configured in configured_models:
        model_name = configured.model_id.split("/")[-1]
        normalized_name, speed_stripped = normalize_model_name(model_name)
        candidates = by_name.get(normalized_name, []) or by_tokens.get(
            token_key(model_name), []
        )
        if not candidates:
            results.append(
                MatchResult(
                    configured.configured_for,
                    configured.model_id,
                    configured.reasoning,
                    "NOT_BENCHMARKED",
                    "not-benchmarked",
                    speed_stripped,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            )
            continue
        candidate, match_kind = choose_candidate(candidates, configured.reasoning)
        results.append(
            MatchResult(
                configured.configured_for,
                configured.model_id,
                configured.reasoning,
                candidate.display_name,
                match_kind,
                speed_stripped or candidate.speed_tier_stripped,
                candidate.intelligence,
                candidate.cost_per_task_usd,
                candidate.input_price_usd_per_million_tokens,
                candidate.output_price_usd_per_million_tokens,
                candidate.median_tokens_per_second,
            )
        )
    return sorted(
        results,
        key=lambda result: (
            result.intelligence if result.intelligence is not None else float("-inf")
        ),
        reverse=True,
    )


def summarize(results: list[MatchResult]) -> dict[str, int]:
    return {
        "exact": sum(result.match_kind == "exact" for result in results),
        "approx-tier": sum(result.match_kind == "approx-tier" for result in results),
        "not-benchmarked": sum(
            result.match_kind == "not-benchmarked" for result in results
        ),
    }


def format_number(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def render_table(results: list[MatchResult], summary: dict[str, int]) -> str:
    headers = (
        "AGENT/CATEGORY",
        "CONFIG MODEL ID",
        "REASONING",
        "LEADERBOARD ROW",
        "MATCH KIND",
        "SPEED SUFFIX",
        "INTELLIGENCE",
        "COST/TASK",
        "INPUT/1M",
        "OUTPUT/1M",
        "TOK/S",
    )
    data = [
        (
            result.configured_for,
            result.config_model_id,
            result.reasoning,
            result.matched_leaderboard_row,
            result.match_kind,
            "stripped" if result.speed_tier_stripped else "-",
            format_number(result.intelligence),
            format_number(result.cost_per_task_usd),
            format_number(result.input_price_usd_per_million_tokens),
            format_number(result.output_price_usd_per_million_tokens),
            format_number(result.median_tokens_per_second),
        )
        for result in results
    ]
    widths = [
        max(len(row[index]) for row in [headers, *data])
        for index in range(len(headers))
    ]
    lines = [
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(headers))
    ]
    lines.append("  ".join("-" * width for width in widths))
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in data
    )
    lines.append(
        "Summary: " + ", ".join(f"{kind}={count}" for kind, count in summary.items())
    )
    return "\n".join(lines)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Match configured OMO models against an Artificial Analysis leaderboard CSV."
    )
    parser.add_argument(
        "--config", required=True, type=Path, help="Path to the OMO JSONC config"
    )
    parser.add_argument(
        "--leaderboard", required=True, type=Path, help="Path to the leaderboard CSV"
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of a table"
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        config = load_jsonc(arguments.config)
        configured_models = extract_configured_models(config)
        results = match_models(
            configured_models, load_leaderboard(arguments.leaderboard)
        )
    except (PathMissingError, DataFormatError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    summary = summarize(results)
    if arguments.json:
        print(
            json.dumps(
                {"matches": [asdict(result) for result in results], "summary": summary},
                indent=2,
            )
        )
    else:
        print(render_table(results, summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
