"""Offline tests for doctor_check: parsing, false-positive classification, exit codes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "doctor_check.py"


def _run(fixture: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--from-file", str(fixture), *extra],
        capture_output=True, text=True,
    )


def _write(tmp_path: Path, results: list[dict[str, object]]) -> Path:
    payload = {
        "results": results,
        "systemInfo": {},
        "tools": {},
        "summary": {},
        "exitCode": 0,
        "target": "opencode",
    }
    p = tmp_path / "doctor.json"
    p.write_text(json.dumps(payload))
    return p


def test_clean_report_exits_zero(tmp_path: Path) -> None:
    f = _write(tmp_path, [{"name": "System", "status": "pass", "message": "ok",
                           "details": [], "issues": []}])
    r = _run(f)
    assert r.returncode == 0, r.stdout + r.stderr


def test_model_cache_warning_classified_as_known_false_positive(tmp_path: Path) -> None:
    """The 'unavailable provider' warning fires for providers absent from OpenCode's
    model cache even when they work. It must not be reported as actionable."""
    f = _write(tmp_path, [{
        "name": "Configuration", "status": "warn", "message": "1 warning",
        "details": [], "issues": [{
            "title": "Model override uses unavailable provider",
            "description": "Provider(s) not found in OpenCode model cache: someprovider",
            "severity": "warning", "affects": ["model resolution"],
        }],
    }])
    r = _run(f, "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["known_false_positive_count"] == 1
    assert out["actionable_count"] == 0
    fp = out["known_false_positives"][0]
    assert "verify" in fp["how_to_verify"].lower()
    assert "someprovider" in fp["how_to_verify"]


def test_deprecated_reasoning_key_is_actionable(tmp_path: Path) -> None:
    f = _write(tmp_path, [{
        "name": "Deprecated Reasoning Keys", "status": "warn", "message": "1 warning",
        "details": [], "issues": [{
            "title": "Deprecated reasoning config key",
            "description": "Replace fallback_models with models",
            "severity": "warning", "affects": ["agents.oracle.fallback_models"],
        }],
    }])
    r = _run(f, "--json")
    out = json.loads(r.stdout)
    assert out["actionable_count"] == 1
    assert out["known_false_positive_count"] == 0


def test_error_severity_exits_one(tmp_path: Path) -> None:
    f = _write(tmp_path, [{
        "name": "Models", "status": "fail", "message": "boom", "details": [],
        "issues": [{"title": "Broken", "description": "d", "severity": "error",
                    "affects": ["x"]}],
    }])
    assert _run(f).returncode == 1


def test_strict_promotes_actionable_warnings_to_failure(tmp_path: Path) -> None:
    f = _write(tmp_path, [{
        "name": "Deprecated Reasoning Keys", "status": "warn", "message": "w",
        "details": [], "issues": [{"title": "Deprecated reasoning config key",
                                   "description": "d", "severity": "warning",
                                   "affects": ["a"]}],
    }])
    assert _run(f).returncode == 0
    assert _run(f, "--strict").returncode == 1


def test_strict_does_not_fail_on_known_false_positive_only(tmp_path: Path) -> None:
    """--strict must still tolerate a report whose only finding is a known FP."""
    f = _write(tmp_path, [{
        "name": "Configuration", "status": "warn", "message": "w", "details": [],
        "issues": [{"title": "Model override uses unavailable provider",
                    "description": "Provider(s) not found in OpenCode model cache: p",
                    "severity": "warning", "affects": ["model resolution"]}],
    }])
    assert _run(f, "--strict").returncode == 0


def test_malformed_json_exits_two(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    r = _run(p)
    assert r.returncode == 2
    assert "json" in (r.stdout + r.stderr).lower()


def test_reports_pinned_version_in_command(tmp_path: Path) -> None:
    """Version pinning must be visible so results are reproducible."""
    f = _write(tmp_path, [{"name": "System", "status": "pass", "message": "ok",
                           "details": [], "issues": []}])
    r = _run(f, "--json", "--version", "4.19.4")
    out = json.loads(r.stdout)
    assert out["pinned_version"] == "4.19.4"
