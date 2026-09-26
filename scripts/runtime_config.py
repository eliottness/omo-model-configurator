#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

from __future__ import annotations

import re
import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeAlias, TypedDict

Harness = Literal["native", "opencode"]
JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]

CONTROL_KEYS: Final = frozenset(
    {
        "profiles",
        "[codex]",
        "[native]",
        "[omo]",
        "[opencode]",
        "[senpi]",
    }
)
UNSAFE_KEYS: Final = frozenset({"__proto__", "constructor", "prototype"})
NATIVE_VERSION_RE: Final = re.compile(
    r"omo\s+(?P<product>\S+)(?:\s+\(engine:\s+senpi\s+(?P<engine>[^)]+)\))?"
)


@dataclass(frozen=True, slots=True)
class RuntimeDetection:
    harness: Harness
    command: tuple[str, ...]
    product_version: str | None
    engine_version: str | None
    exit_code: int | None
    stdout: str
    stderr: str
    supported: bool
    error: str | None = None


class ModelProfileInventory(TypedDict):
    active: str | None
    configured: list[str]


def normalize_harness(harness: str) -> Harness:
    """Normalize the public harness aliases accepted by audit commands."""
    normalized = harness.strip().lower()
    match normalized:
        case "native" | "senpi":
            return "native"
        case "opencode":
            return "opencode"
        case _:
            message = f"unsupported harness: {harness}"
            raise ValueError(message)


def _as_object(value: JsonValue | None) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _without_controls(config: Mapping[str, JsonValue]) -> JsonObject:
    return {
        key: deepcopy(value)
        for key, value in config.items()
        if key not in CONTROL_KEYS and key not in UNSAFE_KEYS
    }


def _merge(base: Mapping[str, JsonValue], override: Mapping[str, JsonValue]) -> JsonObject:
    merged = _without_unsafe(base)
    for key, value in override.items():
        if key in UNSAFE_KEYS:
            continue
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge(current, value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _without_unsafe(config: Mapping[str, JsonValue]) -> JsonObject:
    result: JsonObject = {}
    for key, value in config.items():
        if key in UNSAFE_KEYS:
            continue
        if isinstance(value, dict):
            result[key] = _without_unsafe(value)
        elif isinstance(value, list):
            result[key] = [
                _without_unsafe(item) if isinstance(item, dict) else deepcopy(item)
                for item in value
            ]
        else:
            result[key] = deepcopy(value)
    return result


def _harness_layers(config: Mapping[str, JsonValue], harness: Harness) -> tuple[JsonObject, ...]:
    match harness:
        case "native":
            return (
                _as_object(config.get("[senpi]")),
                _as_object(config.get("[native]")),
            )
        case "opencode":
            return (_as_object(config.get("[opencode]")),)


def resolve_config_view(
    config: Mapping[str, JsonValue],
    harness: str,
    profile: str | None = None,
) -> JsonObject:
    """Resolve the effective shared, harness, and selected-profile configuration."""
    canonical = normalize_harness(harness)
    profiles = _as_object(config.get("profiles"))
    selected = _as_object(profiles.get(profile)) if profile is not None else {}
    layers = (
        _without_controls(config),
        *_harness_layers(config, canonical),
        _without_controls(selected),
        *_harness_layers(selected, canonical),
    )
    resolved: JsonObject = {}
    for layer in layers:
        resolved = _merge(resolved, layer)
    return _without_controls(resolved)


def model_profile_inventory(
    config: Mapping[str, JsonValue],
    harness: str,
    profile: str | None = None,
) -> ModelProfileInventory:
    """List explicit main-session profile state without inferring a default choice."""
    resolved = resolve_config_view(config, harness, profile)
    active = resolved.get("model_profile")
    configured = resolved.get("model_profiles")
    return {
        "active": active if isinstance(active, str) else None,
        "configured": sorted(configured) if isinstance(configured, dict) else [],
    }


def _run_version(command: Sequence[str], harness: Harness) -> RuntimeDetection:
    executable = shutil.which(command[0])
    if executable is None:
        return RuntimeDetection(
            harness=harness,
            command=tuple(command),
            product_version=None,
            engine_version=None,
            exit_code=None,
            stdout="",
            stderr="",
            supported=False,
            error=f"{command[0]} not found on PATH",
        )
    completed = subprocess.run(
        [executable, *command[1:]],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    product_version: str | None = None
    engine_version: str | None = None
    if harness == "native":
        match = NATIVE_VERSION_RE.search(f"{stdout}\n{stderr}")
        if match is not None:
            product_version = match.group("product")
            engine_version = match.group("engine")
    else:
        product_version = stdout.splitlines()[0].strip() if stdout else None
    return RuntimeDetection(
        harness=harness,
        command=tuple(command),
        product_version=product_version,
        engine_version=engine_version,
        exit_code=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        supported=completed.returncode == 0 and product_version is not None,
        error=None,
    )


def detect_runtime(
    preferred: str | None = None,
    native_command: Sequence[str] = ("omo", "--version"),
    opencode_command: Sequence[str] = ("opencode", "--version"),
) -> RuntimeDetection:
    """Detect an installed native or OpenCode runtime without changing configuration."""
    if preferred is not None:
        harness = normalize_harness(preferred)
        return _run_version(
            native_command if harness == "native" else opencode_command,
            harness,
        )
    native = _run_version(native_command, "native")
    if native.supported:
        return native
    opencode = _run_version(opencode_command, "opencode")
    if opencode.supported:
        return opencode
    return native


def native_engine_root(explicit: Path | None = None) -> Path:
    """Locate the installed engine without downloading or starting a session."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    candidates = [
        Path(os.environ.get("BUN_INSTALL", str(Path.home() / ".bun")))
        / "install/global/node_modules/@code-yeongyu/senpi",
    ]
    executable = shutil.which("omo")
    if executable:
        for parent in Path(executable).resolve().parents:
            candidates.extend(
                [parent / "@code-yeongyu/senpi",
                 parent / "node_modules/@code-yeongyu/senpi"]
            )
    for candidate in candidates:
        if (candidate / "dist/core/model-runtime.js").is_file():
            return candidate
    raise FileNotFoundError("native engine not found; pass --engine-root")


def probe_native_models(
    models: Sequence[str],
    engine_root: Path | None = None,
    models_path: Path | None = None,
) -> JsonObject:
    """Read installed admission/preset metadata with network and auth storage off."""
    runner = shutil.which("bun") or shutil.which("node")
    if runner is None:
        raise FileNotFoundError("bun or node is required for native inspection")
    command = [
        runner, str(Path(__file__).with_name("runtime_probe.mjs")),
        "--engine-root", str(native_engine_root(engine_root)),
    ]
    if models_path is not None:
        command.extend(["--models-path", str(models_path.expanduser())])
    for model in models:
        command.extend(["--model", model])
    result = subprocess.run(
        command, capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode:
        raise RuntimeError(
            f"native probe exited {result.returncode}: {result.stderr.strip()}"
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("native probe did not return an object")
    return payload
