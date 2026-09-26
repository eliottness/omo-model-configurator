"""All benchmark values and runtime evidence in these fixtures are synthetic."""

from __future__ import annotations

import csv
import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_config.py"


def prepare(tmp_path: Path) -> tuple[Path, Path, Path]:
    engine = tmp_path / "engine"
    engine_files = {
        "package.json": json.dumps({"type": "module", "version": "synthetic"}),
        "dist/core/auth-storage.js": "export const AuthStorage = {inMemory() { return {}; }};",
        "dist/core/model-runtime.js": """
          export const ModelRuntime = {async create(options) {
            if (options.allowModelNetwork || options.refreshOnCreate) throw Error("network");
            return {getModel(provider, id) {
              if (provider !== "example" || !["alpha", "beta", "fallback"].includes(id)) return;
              return {provider, id, reasoning: true, input: ["text"]};
            }};
          }};
        """,
        "dist/core/extensions/builtin/prompt-preset/presets.js":
            'export function resolvePresetName() { return "synthetic"; }',
    }
    for name, content in engine_files.items():
        path = engine / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    config = tmp_path / "omo.jsonc"
    config.write_text(
        '// Keep this comment.\n{\n'
        '  "[native]": {"categories": {"quick": {"models": [\n'
        '    {"model": "example/alpha", "reasoning": "low"},\n'
        '    "example/fallback"\n'
        '  ]}}},\n'
        '  "[opencode]": {"agents": {"old": {"model": "example/alpha"}}}\n'
        '}\n',
        encoding="utf-8",
    )
    leaderboard = tmp_path / "leaderboard.csv"
    with leaderboard.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "Model", "Artificial Analysis Intelligence Index", "Cost per Task USD",
            "Input Price USD/1M Tokens", "Output Price USD/1M Tokens", "Median Tokens/s",
        ])
        for label in ("Alpha (low)", "Beta (low)", "Fallback"):
            writer.writerow([label, "7", "0.01", "0.02", "0.03", "4"])
    leaderboard.with_suffix(".csv.manifest.json").write_text(json.dumps({
        "schema_version": 1, "local_only": True, "status_filter": "all",
        "source_url": "https://example.test/?status=all",
        "observed_at": "2026-01-01T00:00:00+00:00", "row_count": 3,
        "csv_sha256": hashlib.sha256(leaderboard.read_bytes()).hexdigest(),
        "benchmark_revision": "synthetic-v1",
    }), encoding="utf-8")
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps({
        "runtime": {"surface": "native", "engine_version": "synthetic"},
        "models": [
            {"model": f"example/{name}", "registry_admitted": True, "preset": "synthetic"}
            for name in ("alpha", "beta", "fallback")
        ],
    }), encoding="utf-8")
    return config, leaderboard, probe


def audit(tmp_path: Path) -> tuple[Path, Path]:
    config, leaderboard, probe = prepare(tmp_path)
    output = tmp_path / "audit-output"
    original = config.read_bytes()
    result = subprocess.run([
        sys.executable, str(SCRIPT), "audit", "--config", str(config),
        "--leaderboard", str(leaderboard), "--harness", "native",
        "--probe-file", str(probe), "--replace", "example/alpha=example/beta",
        "--engine-root", str(tmp_path / "engine"),
        "--output", str(output),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert config.read_bytes() == original
    return config, output / "plan.json"


def test_audit_is_read_only_and_plan_targets_only_active_override(tmp_path: Path) -> None:
    config, plan_path = audit(tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["config_sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert plan["changes"] == [{
        "path": ["[native]", "categories", "quick", "models", 0, "model"],
        "before": "example/alpha", "after": "example/beta",
    }]
    assert plan["status"] == "ready"
    assert plan["local_only"] is True


def test_apply_verifies_in_isolation_and_preserves_comments(tmp_path: Path) -> None:
    config, plan = audit(tmp_path)
    config.chmod(0o640)
    command = (
        "import os,pathlib; "
        "p=pathlib.Path(os.environ['HOME']); "
        "assert str(p)!=os.environ['AUDIT_ORIGINAL_HOME']; "
        "assert pathlib.Path.cwd()!=p; "
        "assert pathlib.Path.cwd().is_relative_to(p); "
        "(p/'probe-write').write_text('isolated')"
    )
    result = subprocess.run([
        sys.executable, str(SCRIPT), "apply", "--plan", str(plan), "--approve",
        "--verify-command", sys.executable, "-c", command,
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    updated = config.read_text(encoding="utf-8")
    assert updated.startswith("// Keep this comment.")
    assert updated.count("example/beta") == 1
    assert updated.count("example/alpha") == 1
    assert list(tmp_path.glob("omo.jsonc.bak-*"))
    assert stat.S_IMODE(config.stat().st_mode) == 0o640
    assert not (Path.home() / "probe-write").exists()


def test_apply_refuses_changed_baseline(tmp_path: Path) -> None:
    config, plan = audit(tmp_path)
    config.write_text(config.read_text(encoding="utf-8") + "// Concurrent edit.\n")
    original = config.read_bytes()
    result = subprocess.run([
        sys.executable, str(SCRIPT), "apply", "--plan", str(plan), "--approve",
        "--verify-command", sys.executable, "-c", "pass",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "changed" in result.stderr.lower()
    assert config.read_bytes() == original


def test_failed_isolated_verification_never_changes_real_config(tmp_path: Path) -> None:
    config, plan = audit(tmp_path)
    original = config.read_bytes()
    result = subprocess.run([
        sys.executable, str(SCRIPT), "apply", "--plan", str(plan), "--approve",
        "--verify-command", sys.executable, "-c", "raise SystemExit(3)",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert config.read_bytes() == original


def test_verification_migration_requires_a_new_plan(tmp_path: Path) -> None:
    config, plan = audit(tmp_path)
    original = config.read_bytes()
    command = (
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
        "p.write_text(p.read_text()+'\\n// simulated runtime migration\\n')"
    )
    result = subprocess.run([
        sys.executable, str(SCRIPT), "apply", "--plan", str(plan), "--approve",
        "--verify-command", sys.executable, "-c", command, "{config}",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert config.read_bytes() == original


def test_read_only_audit_accepts_trailing_commas(tmp_path: Path) -> None:
    config, leaderboard, probe = prepare(tmp_path)
    config.write_text(config.read_text().replace("\n}\n", ",\n}\n"))
    result = subprocess.run([
        sys.executable, str(SCRIPT), "audit", "--config", str(config),
        "--leaderboard", str(leaderboard), "--probe-file", str(probe),
        "--harness", "native", "--output", str(tmp_path / "audit-output"),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_apply_rejects_tampered_inactive_harness_path(tmp_path: Path) -> None:
    config, plan_path = audit(tmp_path)
    original = config.read_bytes()
    plan = json.loads(plan_path.read_text())
    plan["changes"][0]["path"] = ["[opencode]", "agents", "old", "model"]
    plan_path.write_text(json.dumps(plan))
    result = subprocess.run([
        sys.executable, str(SCRIPT), "apply", "--plan", str(plan_path), "--approve",
        "--verify-command", sys.executable, "-c", "pass",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert config.read_bytes() == original


def test_apply_rechecks_runtime_even_for_captured_audit_evidence(tmp_path: Path) -> None:
    config, plan = audit(tmp_path)
    original = config.read_bytes()
    (tmp_path / "engine" / "package.json").write_text(
        json.dumps({"type": "module", "version": "changed"})
    )
    result = subprocess.run([
        sys.executable, str(SCRIPT), "apply", "--plan", str(plan), "--approve",
        "--verify-command", sys.executable, "-c", "pass",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert config.read_bytes() == original


def test_audit_blocks_registry_evidence_from_another_harness(tmp_path: Path) -> None:
    config, leaderboard, probe = prepare(tmp_path)
    evidence = json.loads(probe.read_text())
    evidence["runtime"]["surface"] = "opencode"
    probe.write_text(json.dumps(evidence))
    result = subprocess.run([
        sys.executable, str(SCRIPT), "audit", "--config", str(config),
        "--leaderboard", str(leaderboard), "--probe-file", str(probe),
        "--harness", "native", "--replace", "example/alpha=example/beta",
        "--output", str(tmp_path / "audit-output"),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    plan = json.loads((tmp_path / "audit-output" / "plan.json").read_text())
    assert plan["status"] == "blocked"


def test_native_audit_findings_do_not_target_the_inactive_harness(tmp_path: Path) -> None:
    config, leaderboard, probe = prepare(tmp_path)
    config.write_text(config.read_text().replace('"models"', '"fallback_models"'))
    original = config.read_bytes()
    result = subprocess.run([
        sys.executable, str(SCRIPT), "audit", "--config", str(config),
        "--leaderboard", str(leaderboard), "--probe-file", str(probe),
        "--harness", "native", "--output", str(tmp_path / "audit-output"),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "audit-output" / "report.json").read_text())
    assert report["findings"]
    assert all(item["location"].startswith("[native]") for item in report["findings"])
    assert config.read_bytes() == original
