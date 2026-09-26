#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Local audit, hash-bound upgrade plan, and explicitly approved isolated apply."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from config_plan import Change, apply_changes, create_changes
from match_config import (
    MatchResult, extract_configured_models, load_jsonc, load_leaderboard, match_models, summarize,
)
from runtime_config import (
    detect_runtime, model_profile_inventory, normalize_harness, probe_native_models,
    resolve_config_view,
)
from lint_omo_config import lint_config, strip_jsonc

LOCAL_MARKER = "<!-- LOCAL_ONLY_AA_DATA -->"


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_private(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, payload: dict) -> None:
    write_private(path, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))


def report_metric(match: MatchResult, field: str) -> str:
    value = getattr(match, field)
    if value is not None:
        return f"{value:g}" + ("*" if match.metric_metadata[field].estimated else "")
    if match.matched_leaderboard_row is not None:
        return "missing in input row"
    if match.benchmark_candidates:
        return f"{len(match.benchmark_candidates)} available variants"
    return match.match_reason


def snapshot_evidence(path: Path) -> dict:
    manifest = path.with_suffix(path.suffix + ".manifest.json")
    if not manifest.is_file():
        raise ValueError("local cache manifest is missing; refresh the leaderboard")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if payload.get("csv_sha256") != digest(path.read_bytes()):
        raise ValueError("local leaderboard changed or is partial: manifest hash mismatch")
    if payload.get("status_filter") != "all":
        raise ValueError("leaderboard does not prove all-model coverage; scrape status=all")
    return payload


def audit(options: argparse.Namespace) -> int:
    config_path = options.config.expanduser().resolve()
    raw = config_path.read_bytes()
    config = load_jsonc(config_path)
    harness = options.harness
    runtime = None
    if harness == "auto":
        detected = detect_runtime()
        if not detected.supported:
            raise ValueError("runtime detection failed; specify --harness")
        harness = detected.harness
        runtime = asdict(detected)
    harness = normalize_harness(harness)
    leaderboard = options.leaderboard.expanduser().resolve()
    snapshot = snapshot_evidence(leaderboard)
    rows = load_leaderboard(leaderboard)
    if len(rows) != snapshot.get("row_count"):
        raise ValueError("local cache row count differs from its manifest")
    replacements: dict[str, str] = {}
    for replacement in options.replace:
        before, separator, after = replacement.partition("=")
        if not separator or "/" not in before or "/" not in after:
            raise ValueError("--replace requires provider/old=provider/new")
        replacements[before] = after
    changes = create_changes(config, harness, options.profile, replacements)
    if replacements and not changes:
        raise ValueError("no active model references match the requested replacements")
    proposed_text = apply_changes(raw.decode("utf-8"), changes)
    proposed = json.loads(strip_jsonc(proposed_text))
    current_models = extract_configured_models(config, harness, options.profile)
    proposed_models = extract_configured_models(proposed, harness, options.profile)
    matches = match_models(current_models, rows)
    proposed_matches = match_models(proposed_models, rows)
    candidate_ids = sorted({change.after for change in changes})
    all_ids = sorted({model.model_id for model in current_models + proposed_models})
    if options.probe_file:
        probe = json.loads(options.probe_file.read_text(encoding="utf-8"))
    elif harness == "native":
        probe = probe_native_models(all_ids, options.engine_root, options.models_path)
    else:
        probe = {"runtime": {"surface": "opencode"}, "models": []}
    evidence_by_model = {item["model"]: item for item in probe.get("models", [])}
    blockers = []
    if probe.get("runtime", {}).get("surface") != harness:
        blockers.append("registry evidence belongs to a different or unspecified harness")
    utility_slots = {"agent:explore", "agent:librarian", "category:quick"}
    preset_optional = {
        candidate for candidate in candidate_ids
        if all(model.configured_for in utility_slots for model in proposed_models
               if model.model_id == candidate)
    }
    for candidate in candidate_ids:
        evidence = evidence_by_model.get(candidate, {})
        if evidence.get("registry_admitted") is not True or (
            candidate not in preset_optional and not evidence.get("preset")
        ):
            blockers.append(f"candidate runtime admission/preset not verified: {candidate}")
    for match in proposed_matches:
        if match.model_match_kind == "unmatched":
            blockers.append(f"model absent from collected AA rows: {match.config_model_id}")
    view = resolve_config_view(proposed, harness, options.profile)
    findings = lint_config({"[opencode]": view})
    if harness == "native":
        for finding in findings:
            finding["location"] = finding["location"].replace("[opencode]", "[native]", 1)
    blockers.extend(finding["message"] for finding in findings if finding["severity"] == "error")
    plan = {
        "schema_version": 1, "local_only": True, "config_path": str(config_path),
        "config_sha256": digest(raw), "harness": harness, "profile": options.profile,
        "leaderboard_path": str(leaderboard), "leaderboard_sha256": snapshot["csv_sha256"],
        "runtime": {**(runtime or {}), **probe.get("runtime", {})},
        "probe_source": "captured" if options.probe_file else "installed",
        "engine_root": str(options.engine_root.expanduser().resolve()) if options.engine_root else None,
        "models_path": str(options.models_path.expanduser().resolve()) if options.models_path else None,
        "preset_optional_models": sorted(preset_optional),
        "changes": [asdict(change) for change in changes],
        "status": "blocked" if blockers else "ready", "blockers": blockers,
    }
    inactive = {
        key: config[key] for key in ("[opencode]", "[native]", "[senpi]")
        if key in config and (
            (harness == "native" and key == "[opencode]")
            or (harness == "opencode" and key != "[opencode]")
        )
    }
    report = {
        "schema_version": 1, "local_only": True, "plan": plan,
        "snapshot": snapshot, "runtime_probe": probe, "findings": findings,
        "model_profile": model_profile_inventory(config, harness, options.profile),
        "inactive_harnesses": inactive,
        "current": [asdict(match) for match in matches],
        "proposed": [asdict(match) for match in proposed_matches],
        "summary": summarize(matches),
        "live_entitlement": "not-probed",
    }
    output = options.output.expanduser()
    write_json(output / "plan.json", plan)
    write_json(output / "report.json", report)
    lines = [
        LOCAL_MARKER, "# Local model upgrade audit", "",
        "Do not commit or upload this report: it contains AA measurements.",
        "", f"Harness: `{harness}`. Plan: **{plan['status']}**.", "",
        "| Slot / chain position | Current | Proposed | Presets (current -> proposed) | AAII (current -> proposed) | AA cost/task (current -> proposed) | Benchmark row / evidence | Verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for old, new in zip(matches, proposed_matches):
        row = new.matched_leaderboard_row or new.match_reason
        score = f"{report_metric(old, 'intelligence')} -> {report_metric(new, 'intelligence')}"
        cost = f"{report_metric(old, 'cost_per_task_usd')} -> {report_metric(new, 'cost_per_task_usd')}"
        presets = [
            str(evidence_by_model[model].get("preset") or "default")
            if evidence_by_model.get(model, {}).get("registry_admitted") is True
            else "registry not verified"
            for model in (old.config_model_id, new.config_model_id)
        ]
        verdict = "keep" if old.config_model_id == new.config_model_id else (
            "blocked" if blockers else "swap (requested)"
        )
        lines.append(
            f"| `{old.configured_for}:{old.chain_key}[{old.chain_index}]` | `{old.config_model_id}` | "
            f"`{new.config_model_id}` | {' -> '.join(presets)} | {score} | {cost} | "
            f"{row}; {new.match_kind}: {new.match_reason} | {verdict} |"
        )
    lines.extend(["", "Full effort variants, qualifiers, estimates, inactive slots, and provenance are in report.json."])
    lines.extend(f"- Blocked: {blocker}" for blocker in blockers)
    write_private(output / "report.md", ("\n".join(lines) + "\n").encode("utf-8"))
    print(json.dumps({"status": plan["status"], "output": str(output), "changes": len(changes),
                      "model_coverage_gaps": sum(m.model_match_kind == "unmatched" for m in matches)}))
    return 1 if blockers else 0


def apply(options: argparse.Namespace) -> int:
    if not options.approve or not options.verify_command:
        raise ValueError("apply requires --approve and --verify-command")
    plan = json.loads(options.plan.read_text(encoding="utf-8"))
    if plan.get("schema_version") != 1 or plan.get("status") != "ready":
        raise ValueError("plan is unsupported or blocked")
    config_path = Path(plan["config_path"])
    if config_path.is_symlink():
        raise ValueError("refusing to replace a symlinked configuration")
    raw = config_path.read_bytes()
    original_mode = stat.S_IMODE(config_path.stat().st_mode)
    if digest(raw) != plan["config_sha256"]:
        raise ValueError("configuration changed since the audit; generate a new plan")
    leaderboard = Path(plan["leaderboard_path"])
    if snapshot_evidence(leaderboard)["csv_sha256"] != plan["leaderboard_sha256"]:
        raise ValueError("leaderboard changed since the audit")
    changes = [Change(tuple(item["path"]), item["before"], item["after"]) for item in plan["changes"]]
    if not changes:
        raise ValueError("plan contains no changes")
    replacements = {change.before: change.after for change in changes}
    expected = create_changes(load_jsonc(config_path), plan["harness"], plan["profile"], replacements)
    if changes != expected:
        raise ValueError("plan changes do not match active model-reference locations")
    updated = apply_changes(raw.decode("utf-8"), changes).encode("utf-8")
    if plan["harness"] == "native":
        fresh = probe_native_models(
            sorted({change.after for change in changes}),
            Path(plan["engine_root"]) if plan["engine_root"] else None,
            Path(plan["models_path"]) if plan["models_path"] else None,
        )
        if fresh["runtime"]["engine_version"] != plan["runtime"].get("engine_version"):
            raise ValueError("runtime version changed since the audit; generate a new plan")
        if any(
            not row["registry_admitted"] or (
                not row["preset"] and row["model"] not in plan.get("preset_optional_models", [])
            )
            for row in fresh["models"]
        ):
            raise ValueError("candidate runtime support changed since the audit")
    with TemporaryDirectory(prefix="omo-config-verify-") as temporary:
        home = Path(temporary).resolve()
        workspace = home / "workspace"
        workspace.mkdir()
        isolated_config = home / ".omo" / "omo.jsonc"
        write_private(isolated_config, updated)
        agent_dir = home / ".omo" / "agent"
        agent_dir.mkdir()
        if options.credentials_from:
            for name in ("auth.json", "models.json", "models-store.json", "settings.json"):
                source = options.credentials_from.expanduser() / name
                if source.is_file():
                    write_private(agent_dir / name, source.read_bytes())
        environment = {
            **os.environ, "HOME": str(home), "USERPROFILE": str(home),
            "AUDIT_ORIGINAL_HOME": str(Path.home()), "XDG_CONFIG_HOME": str(home / ".config"),
            "OMO_CODING_AGENT_DIR": str(agent_dir), "PI_CODING_AGENT_DIR": str(agent_dir),
            "SENPI_CODING_AGENT_DIR": str(agent_dir),
        }
        for model in sorted({change.after for change in changes}):
            command = [
                part.replace("{model}", model).replace("{config}", str(isolated_config))
                for part in options.verify_command
            ]
            result = subprocess.run(
                command, cwd=workspace, env=environment, capture_output=True, text=True,
                check=False, timeout=options.verification_timeout,
            )
            if result.returncode:
                raise ValueError(f"isolated verification failed with exit {result.returncode}: {result.stderr[-500:]}")
            if isolated_config.read_bytes() != updated:
                raise ValueError("verification changed the candidate configuration; review runtime migrations")
    if config_path.read_bytes() != raw:
        raise ValueError("configuration changed during verification; nothing applied")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    backup = config_path.with_name(config_path.name + ".bak-" + stamp)
    with backup.open("xb") as stream:
        os.chmod(backup, 0o600)
        stream.write(raw)
    if backup.read_bytes() != raw:
        raise ValueError("backup verification failed")
    write_private(config_path, updated, original_mode)
    if config_path.read_bytes() != updated:
        raise ValueError(f"post-apply verification failed; recovery copy: {backup}")
    receipt = {
        "schema_version": 1, "local_only": True, "backup": str(backup),
        "before_sha256": digest(raw), "after_sha256": digest(updated),
        "changes": len(changes), "verification": "isolated-command-exit-zero",
    }
    write_json(options.plan.parent / "apply-receipt.json", receipt)
    print(json.dumps(receipt))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("audit", help="Write local-only reports; never edit configuration")
    inspect.add_argument("--config", type=Path, required=True)
    inspect.add_argument("--leaderboard", type=Path, required=True)
    inspect.add_argument("--harness", choices=("auto", "native", "senpi", "opencode"), default="auto")
    inspect.add_argument("--profile")
    inspect.add_argument("--probe-file", type=Path)
    inspect.add_argument("--engine-root", type=Path)
    inspect.add_argument("--models-path", type=Path)
    inspect.add_argument("--replace", action="append", default=[])
    inspect.add_argument("--output", type=Path, default=Path("audit-output"))
    execute = commands.add_parser("apply", help="Apply an approved hash-bound plan after isolated verification")
    execute.add_argument("--plan", type=Path, required=True)
    execute.add_argument("--approve", action="store_true")
    execute.add_argument("--credentials-from", type=Path, help="Explicit private copy of agent credentials for isolated live checks")
    execute.add_argument("--verification-timeout", type=int, default=120)
    execute.add_argument("--verify-command", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    try:
        return audit(options) if options.command == "audit" else apply(options)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, KeyError, IndexError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
