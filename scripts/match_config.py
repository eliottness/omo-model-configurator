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
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
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
LABEL_PATTERN: Final = re.compile(r"^(?P<name>.*?)\s*\((?P<label>[^()]*)\)\s*$")
EFFORT_PATTERN: Final = re.compile(
    r"^(?P<effort>non-reasoning|minimal|low|medium|high|xhigh|max)"
    r"(?:\s+(?P<qualifier>.+))?$",
    re.IGNORECASE,
)
FAST_SUFFIX_PATTERN: Final = re.compile(r"-fast$", re.IGNORECASE)
NON_ALPHANUMERIC_PATTERN: Final = re.compile(r"[^a-z0-9]")
DASH_RUN_PATTERN: Final = re.compile(r"[-\u2010-\u2015]+")
ALPHA_RUN_PATTERN: Final = re.compile(r"[a-z]+")
DIGIT_RUN_PATTERN: Final = re.compile(r"\d+")
TRAILING_COMMA_PATTERN: Final = re.compile(r",(?=\s*[}\]])")
TIER_RANK: Final = {
    "non-reasoning": 0,
    "minimal": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "xhigh": 5,
    "max": 6,
}
REASONING_TIER: Final = {
    "off": "non-reasoning",
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
    "auto": None,
}
CHAIN_KEYS: Final = ("models", "fallback_models")
METRIC_FIELDS: Final = (
    "intelligence",
    "cost_per_task_usd",
    "input_price_usd_per_million_tokens",
    "output_price_usd_per_million_tokens",
    "median_tokens_per_second",
)


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
    config_path: str
    slot_index: int
    chain_key: str
    chain_index: int


@dataclass(frozen=True, slots=True)
class NumericCell:
    value: float | None
    estimated: bool


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    display_name: str
    base_name: str
    normalized_name: str
    reasoning_tier: str | None
    evaluation_qualifier: str | None
    intelligence: NumericCell
    cost_per_task_usd: NumericCell
    input_price_usd_per_million_tokens: NumericCell
    output_price_usd_per_million_tokens: NumericCell
    median_tokens_per_second: NumericCell


@dataclass(frozen=True, slots=True)
class CandidateSelection:
    row: LeaderboardRow | None
    effort_match_kind: str
    match_reason: str
    warning: str | None


@dataclass(frozen=True, slots=True)
class MetricMetadata:
    available: bool
    estimated: bool
    provenance: str


@dataclass(frozen=True, slots=True)
class MatchResult:
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
    model_match_kind: str
    effort_match_kind: str
    benchmark_reasoning_tier: str | None
    evaluation_qualifier: str | None
    candidate_benchmark_efforts: list[str]
    config_path: str
    slot_index: int
    chain_key: str
    chain_index: int
    intelligence: float | None
    cost_per_task_usd: float | None
    input_price_usd_per_million_tokens: float | None
    output_price_usd_per_million_tokens: float | None
    median_tokens_per_second: float | None
    metric_metadata: dict[str, MetricMetadata]
    benchmark_candidates: list[LeaderboardRow] = field(default_factory=list)


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
    cleaned = TRAILING_COMMA_PATTERN.sub(
        "", strip_jsonc_comments(path.read_text(encoding="utf-8"))
    )
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
    reasoning = entry.get("reasoning")
    return reasoning if reasoning is not None else entry.get("variant")


def parse_model_entry(
    value: JsonValue,
    configured_for: str,
    config_path: str,
    slot_index: int,
    chain_key: str,
    chain_index: int,
) -> ConfiguredModel:
    if isinstance(value, str):
        return ConfiguredModel(
            configured_for,
            value,
            "auto",
            config_path,
            slot_index,
            chain_key,
            chain_index,
        )
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
        configured_for,
        model,
        parse_reasoning(effective_reasoning(value)),
        config_path,
        slot_index,
        chain_key,
        chain_index,
    )


def extract_entity_models(
    entity: dict[str, JsonValue],
    configured_for: str,
    entity_path: str,
    slot_index: int,
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
                f"{entity_path}.model",
                slot_index,
                "model",
                0,
            )
        )
    for chain_key in CHAIN_KEYS:
        chain = entity.get(chain_key)
        if isinstance(chain, list):
            configured.extend(
                parse_model_entry(
                    entry,
                    configured_for,
                    f"{entity_path}.{chain_key}[{chain_index}]",
                    slot_index,
                    chain_key,
                    chain_index,
                )
                for chain_index, entry in enumerate(chain)
            )
    return configured


def resolve_runtime_view(
    config: dict[str, JsonValue], harness: str, profile: str | None
) -> dict[str, JsonValue]:
    if __package__:
        from .runtime_config import resolve_config_view
    else:
        from runtime_config import resolve_config_view
    resolved = resolve_config_view(config, harness, profile)
    if not isinstance(resolved, dict):
        raise DataFormatError("runtime config view must be an object")
    return resolved


def config_view_path(harness: str, profile: str | None) -> str:
    if harness == "opencode" and profile is None:
        return "[opencode]"
    return harness if profile is None else f"{harness}[{profile}]"


def extract_configured_models(
    config: dict[str, JsonValue],
    harness: str = "opencode",
    profile: str | None = None,
) -> list[ConfiguredModel]:
    view = resolve_runtime_view(config, harness, profile)
    root_path = config_view_path(harness, profile)
    configured: list[ConfiguredModel] = []
    slot_index = 0
    main_profile = view.get("model_profile")
    if isinstance(main_profile, str) and "/" in main_profile:
        configured.append(parse_model_entry(
            main_profile, "session:main", f"{root_path}.model_profile",
            slot_index, "model_profile", 0,
        ))
        slot_index += 1
    for section, prefix in (("agents", "agent"), ("categories", "category")):
        for name, value in as_mapping(view.get(section)).items():
            configured.extend(
                extract_entity_models(
                    as_mapping(value),
                    f"{prefix}:{name}",
                    f"{root_path}.{section}.{name}",
                    slot_index,
                )
            )
            slot_index += 1
    return configured


def token_key(name: str) -> str:
    lowered = name.lower()
    words = "".join(sorted(ALPHA_RUN_PATTERN.findall(lowered)))
    digits = ".".join(DIGIT_RUN_PATTERN.findall(lowered))
    return f"{words}|{digits}"


def normalize_model_name(name: str) -> str:
    return NON_ALPHANUMERIC_PATTERN.sub("", name.lower())


def split_model_label(display_name: str) -> tuple[str, str | None, str | None]:
    label_match = LABEL_PATTERN.match(display_name)
    if label_match is None:
        return display_name, None, None
    base_name = label_match.group("name").strip()
    label = label_match.group("label").strip()
    comma_parts = [part.strip() for part in label.split(",")]
    effort_match = EFFORT_PATTERN.match(comma_parts[0])
    if effort_match is None:
        return base_name, None, label or None
    reasoning_tier = effort_match.group("effort").lower()
    qualifiers = [
        qualifier
        for qualifier in [effort_match.group("qualifier"), *comma_parts[1:]]
        if qualifier
    ]
    return base_name, reasoning_tier, ", ".join(qualifiers) or None


def parse_number(value: str | None, column: str) -> NumericCell:
    if value is None or not value.strip():
        return NumericCell(None, False)
    text = value.strip()
    if text.lower() in {"n/a", "na"} or DASH_RUN_PATTERN.fullmatch(text):
        return NumericCell(None, False)
    estimated = text.endswith("*")
    cleaned = (
        text.rstrip("*").replace("$", "").replace(",", "").replace("%", "").strip()
    )
    if not cleaned:
        return NumericCell(None, estimated)
    try:
        return NumericCell(float(cleaned), estimated)
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
            base_name, reasoning_tier, qualifier = split_model_label(display_name)
            rows.append(
                LeaderboardRow(
                    display_name=display_name,
                    base_name=base_name,
                    normalized_name=normalize_model_name(base_name),
                    reasoning_tier=reasoning_tier,
                    evaluation_qualifier=qualifier,
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


def row_intelligence(row: LeaderboardRow) -> float:
    return (
        row.intelligence.value
        if row.intelligence.value is not None
        else float("-inf")
    )


def choose_candidate(
    candidates: list[LeaderboardRow], reasoning: str
) -> CandidateSelection:
    requested_tier = REASONING_TIER[reasoning]
    if requested_tier is None:
        if len(candidates) == 1 and candidates[0].reasoning_tier is None:
            return CandidateSelection(
                candidates[0], "unresolved", "benchmark-effort-unlabeled",
                "AA publishes one unlabeled row; its metrics are retained without "
                "claiming an effort-level equivalence.",
            )
        return CandidateSelection(
            None,
            "unresolved",
            "configured-effort-auto",
            "Configured effort is auto and no effective effort was provided; "
            "no benchmark effort was guessed.",
        )
    exact = [
        candidate
        for candidate in candidates
        if candidate.reasoning_tier == requested_tier
    ]
    if exact:
        if len({row.evaluation_qualifier for row in exact}) > 1:
            return CandidateSelection(
                None, "unresolved", "evaluation-policy-ambiguous",
                "Matching effort rows use different evaluation policies; no policy was guessed.",
            )
        return CandidateSelection(
            max(exact, key=row_intelligence), "exact", "matched-effort", None
        )
    ranked = [
        candidate for candidate in candidates if candidate.reasoning_tier is not None
    ]
    if ranked:
        nearest = min(
            ranked,
            key=lambda row: (
                abs(TIER_RANK[row.reasoning_tier or "non-reasoning"]
                    - TIER_RANK[requested_tier]),
                -TIER_RANK[row.reasoning_tier or "non-reasoning"],
            ),
        )
        nearest_policies = {
            row.evaluation_qualifier for row in ranked
            if row.reasoning_tier == nearest.reasoning_tier
        }
        if len(nearest_policies) > 1:
            return CandidateSelection(
                None, "unresolved", "evaluation-policy-ambiguous",
                "Nearest effort rows use different evaluation policies; no policy was guessed.",
            )
        return CandidateSelection(
            nearest,
            "approximate",
            "requested-effort-unavailable",
            f"Requested effort {requested_tier!r} is absent from matching rows; "
            f"showing {nearest.reasoning_tier!r} as an explicit approximation.",
        )
    if len(candidates) == 1:
        return CandidateSelection(
            candidates[0],
            "unresolved",
            "benchmark-effort-unlabeled",
            "The matching benchmark row has no recognized effort label; "
            "its metrics do not establish effort equivalence.",
        )
    return CandidateSelection(
        None,
        "unresolved",
        "benchmark-effort-ambiguous",
        "Multiple matching benchmark rows have no recognized effort labels; "
        "no row was selected.",
    )


def metric_metadata(cell: NumericCell, proxy: bool) -> MetricMetadata:
    if cell.value is None:
        return MetricMetadata(False, cell.estimated, "missing-benchmark-cell")
    if proxy:
        return MetricMetadata(True, cell.estimated, "base-model-proxy")
    provenance = "estimated-benchmark-row" if cell.estimated else "benchmark-row"
    return MetricMetadata(True, cell.estimated, provenance)


def unavailable_metadata(provenance: str) -> dict[str, MetricMetadata]:
    return {
        field: MetricMetadata(False, False, provenance) for field in METRIC_FIELDS
    }


def join_warnings(*warnings: str | None) -> str | None:
    present = [warning for warning in warnings if warning]
    return " ".join(present) or None


def make_result(
    configured: ConfiguredModel,
    configured_model_name: str,
    candidates: list[LeaderboardRow],
    selection: CandidateSelection,
    proxy: bool,
) -> MatchResult:
    candidate_efforts = sorted(
        {
            candidate.reasoning_tier
            for candidate in candidates
            if candidate.reasoning_tier is not None
        },
        key=lambda effort: TIER_RANK[effort],
    )
    row = selection.row
    if row is None:
        return MatchResult(
            configured.configured_for,
            configured.model_id,
            configured.reasoning,
            None,
            "effort-unresolved",
            selection.match_reason,
            selection.warning,
            proxy,
            configured_model_name,
            None,
            "base-model-proxy" if proxy else "exact-identity",
            selection.effort_match_kind,
            None,
            None,
            candidate_efforts,
            configured.config_path,
            configured.slot_index,
            configured.chain_key,
            configured.chain_index,
            None,
            None,
            None,
            None,
            None,
            unavailable_metadata("unavailable-effort-unresolved"),
        )
    proxy_warning = (
        "Metrics come from the base-model benchmark row and were not measured "
        "for the configured -fast model."
        if proxy
        else None
    )
    if proxy:
        match_kind = "base-model-proxy"
    elif selection.effort_match_kind == "exact":
        match_kind = "exact"
    elif selection.effort_match_kind == "approximate":
        match_kind = "approximate-effort"
    else:
        match_kind = "effort-unresolved"
    cells = {
        "intelligence": row.intelligence,
        "cost_per_task_usd": row.cost_per_task_usd,
        "input_price_usd_per_million_tokens": (
            row.input_price_usd_per_million_tokens
        ),
        "output_price_usd_per_million_tokens": (
            row.output_price_usd_per_million_tokens
        ),
        "median_tokens_per_second": row.median_tokens_per_second,
    }
    return MatchResult(
        configured.configured_for,
        configured.model_id,
        configured.reasoning,
        row.display_name,
        match_kind,
        selection.match_reason,
        join_warnings(selection.warning, proxy_warning),
        proxy,
        configured_model_name,
        row.base_name,
        "base-model-proxy" if proxy else "exact-identity",
        selection.effort_match_kind,
        row.reasoning_tier,
        row.evaluation_qualifier,
        candidate_efforts,
        configured.config_path,
        configured.slot_index,
        configured.chain_key,
        configured.chain_index,
        row.intelligence.value,
        row.cost_per_task_usd.value,
        row.input_price_usd_per_million_tokens.value,
        row.output_price_usd_per_million_tokens.value,
        row.median_tokens_per_second.value,
        {
            field: metric_metadata(cell, proxy) for field, cell in cells.items()
        },
    )


def unmatched_result(
    configured: ConfiguredModel, configured_model_name: str
) -> MatchResult:
    return MatchResult(
        configured.configured_for,
        configured.model_id,
        configured.reasoning,
        None,
        "unmatched",
        "row-absent-from-input",
        "No matching row exists in the supplied leaderboard retrieval; this does "
        "not establish that Artificial Analysis lacks data for the model.",
        False,
        configured_model_name,
        None,
        "unmatched",
        "not-applicable",
        None,
        None,
        [],
        configured.config_path,
        configured.slot_index,
        configured.chain_key,
        configured.chain_index,
        None,
        None,
        None,
        None,
        None,
        unavailable_metadata("unavailable-row-absent"),
    )


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
        candidates = by_name.get(normalize_model_name(model_name), []) or by_tokens.get(
            token_key(model_name), []
        )
        proxy = False
        if not candidates and FAST_SUFFIX_PATTERN.search(model_name):
            base_model_name = FAST_SUFFIX_PATTERN.sub("", model_name)
            candidates = by_name.get(
                normalize_model_name(base_model_name), []
            ) or by_tokens.get(token_key(base_model_name), [])
            proxy = bool(candidates)
        if not candidates:
            results.append(unmatched_result(configured, model_name))
            continue
        selection = choose_candidate(candidates, configured.reasoning)
        results.append(replace(
            make_result(configured, model_name, candidates, selection, proxy),
            benchmark_candidates=candidates,
        ))
    return results


def summarize(results: list[MatchResult]) -> dict[str, int]:
    return dict(Counter(result.match_kind for result in results))


def format_number(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def render_table(results: list[MatchResult], summary: dict[str, int]) -> str:
    headers = (
        "PATH",
        "CONFIG MODEL ID",
        "EFFORT",
        "LEADERBOARD ROW",
        "MATCH KIND",
        "REASON",
        "AAII",
        "COST/TASK",
        "TOK/S",
    )
    data = [
        (
            result.config_path,
            result.config_model_id,
            result.reasoning,
            result.matched_leaderboard_row or "-",
            result.match_kind,
            result.match_reason,
            format_number(result.intelligence),
            format_number(result.cost_per_task_usd),
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
    warnings = [
        f"{result.config_path}: {result.warning}"
        for result in results
        if result.warning is not None
    ]
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Match configured models against an Artificial Analysis CSV."
    )
    parser.add_argument(
        "--config", required=True, type=Path, help="Path to the OMO JSONC config"
    )
    parser.add_argument(
        "--leaderboard", required=True, type=Path, help="Path to the leaderboard CSV"
    )
    parser.add_argument(
        "--harness",
        choices=("auto", "opencode", "native", "senpi"),
        default="auto",
        help="Runtime harness (default: detect installed native/OpenCode runtime)",
    )
    parser.add_argument(
        "--profile", help="Optional runtime profile resolved by runtime_config"
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of a table"
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        config = load_jsonc(arguments.config)
        harness = arguments.harness
        if harness == "auto":
            from runtime_config import detect_runtime
            detected = detect_runtime()
            if not detected.supported:
                raise DataFormatError("No supported runtime detected; pass --harness explicitly")
            harness = detected.harness
        configured_models = extract_configured_models(
            config, harness, arguments.profile
        )
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
