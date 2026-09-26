"""Locate active model references and edit their JSONC tokens without reformatting."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final, Iterator, TypeAlias

from runtime_config import JsonObject, JsonValue, normalize_harness, resolve_config_view

PathPart: TypeAlias = str | int
ConfigPath: TypeAlias = tuple[PathPart, ...]
TOKEN: Final = re.compile(
    r'\s+|//[^\r\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[{}\[\]:,]|'
    r'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null',
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class Change:
    path: ConfigPath
    before: str
    after: str


def model_paths(view: JsonObject) -> Iterator[tuple[ConfigPath, str]]:
    selection = view.get("model_profile")
    if isinstance(selection, str) and "/" in selection:
        yield ("model_profile",), selection
    for section in ("agents", "categories"):
        entities = view.get(section)
        if not isinstance(entities, dict):
            continue
        for name, entity in entities.items():
            if not isinstance(entity, dict):
                continue
            prefix: ConfigPath = (section, name)
            model = entity.get("model")
            canonical = entity.get("models")
            if isinstance(model, str) and not canonical:
                yield (*prefix, "model"), model
            keys = ("models",) if canonical else ("fallback_models",)
            for key in keys:
                chain = entity.get(key)
                if not isinstance(chain, list):
                    continue
                for index, item in enumerate(chain):
                    if isinstance(item, str):
                        yield (*prefix, key, index), item
                    elif isinstance(item, dict) and isinstance(item.get("model"), str):
                        yield (*prefix, key, index, "model"), item["model"]


def source_layers(config: JsonObject, harness: str, profile: str | None) -> list[tuple[ConfigPath, JsonObject]]:
    blocks = ("[senpi]", "[native]") if normalize_harness(harness) == "native" else ("[opencode]",)
    layers: list[tuple[ConfigPath, JsonObject]] = [((), config)]
    for block in blocks:
        value = config.get(block)
        if isinstance(value, dict):
            layers.append(((block,), value))
    profiles = config.get("profiles")
    selected = profiles.get(profile) if isinstance(profiles, dict) and profile else None
    if isinstance(selected, dict):
        prefix: ConfigPath = ("profiles", profile)
        layers.append((prefix, selected))
        for block in blocks:
            value = selected.get(block)
            if isinstance(value, dict):
                layers.append(((*prefix, block), value))
    return layers


def origin_path(path: ConfigPath, layers: list[tuple[ConfigPath, JsonObject]]) -> ConfigPath:
    for prefix, layer in reversed(layers):
        value: JsonValue = layer
        inside_array = False
        for key in path:
            if isinstance(value, dict) and isinstance(key, str) and key in value:
                value = value[key]
            elif isinstance(value, list) and isinstance(key, int) and 0 <= key < len(value):
                value = value[key]
                inside_array = True
            elif isinstance(value, dict) and not inside_array:
                break
            else:
                raise ValueError(f"model reference is shadowed at {path}")
        else:
            return (*prefix, *path)
    raise ValueError(f"no source location for {path}")


def create_changes(config: JsonObject, harness: str, profile: str | None, replacements: dict[str, str]) -> list[Change]:
    view = resolve_config_view(config, harness, profile)
    layers = source_layers(config, harness, profile)
    return [
        Change(origin_path(path, layers), model, replacements[model])
        for path, model in model_paths(view)
        if model in replacements and replacements[model] != model
    ]


def string_spans(text: str) -> dict[ConfigPath, tuple[int, int]]:
    """Parse JSONC structure while preserving original offsets of string values."""
    tokens: list[tuple[str, int, int]] = []
    position = 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if match is None:
            raise ValueError(f"invalid JSONC token at offset {position}")
        token = match.group()
        if not token.isspace() and not token.startswith(("//", "/*")):
            tokens.append((token, position, match.end()))
        position = match.end()
    cursor = 0
    spans: dict[ConfigPath, tuple[int, int]] = {}

    def take(expected: str | None = None) -> tuple[str, int, int]:
        nonlocal cursor
        if cursor >= len(tokens):
            raise ValueError("unexpected end of JSONC")
        token = tokens[cursor]
        if expected is not None and token[0] != expected:
            raise ValueError(f"expected {expected} at offset {token[1]}")
        cursor += 1
        return token

    def value(path: ConfigPath) -> None:
        token, start, end = take()
        if token == "{":
            seen: set[str] = set()
            while cursor < len(tokens) and tokens[cursor][0] != "}":
                key = json.loads(take()[0])
                if not isinstance(key, str) or key in seen:
                    raise ValueError("non-string or duplicate object key")
                seen.add(key)
                take(":")
                value((*path, key))
                if tokens[cursor][0] != ",":
                    break
                take(",")
            take("}")
        elif token == "[":
            index = 0
            while cursor < len(tokens) and tokens[cursor][0] != "]":
                value((*path, index))
                index += 1
                if tokens[cursor][0] != ",":
                    break
                take(",")
            take("]")
        elif token.startswith('"'):
            spans[path] = (start, end)
        else:
            json.loads(token)

    value(())
    if cursor != len(tokens):
        raise ValueError("extra tokens after configuration")
    return spans


def apply_changes(text: str, changes: list[Change]) -> str:
    spans = string_spans(text)
    edits: list[tuple[int, int, str]] = []
    for change in changes:
        if change.path not in spans:
            raise ValueError(f"model path no longer exists: {change.path}")
        start, end = spans[change.path]
        if json.loads(text[start:end]) != change.before:
            raise ValueError(f"model value changed at {change.path}")
        edits.append((start, end, json.dumps(change.after)))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text
