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
    assert out["suspected_count"] == 1
    assert out["actionable_count"] == 0
    fp = out["suspected"][0]
    assert fp["status"] == "suspected"
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
    assert out["suspected_count"] == 0


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


def test_strict_requires_evidence_for_suspected_cache_warning(tmp_path: Path) -> None:
    """A cache-warning pattern alone does not prove that the provider works."""
    f = _write(tmp_path, [{
        "name": "Configuration", "status": "warn", "message": "w", "details": [],
        "issues": [{"title": "Model override uses unavailable provider",
                    "description": "Provider(s) not found in OpenCode model cache: p",
                    "severity": "warning", "affects": ["model resolution"]}],
    }])
    assert _run(f, "--strict").returncode == 1


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


def test_probe_confirmation_upgrades_cache_warning_from_suspected(
    tmp_path: Path,
) -> None:
    # Given a cache warning and evidence from the same harness registry.
    fixture = _write(tmp_path, [{
        "name": "Configuration",
        "status": "warn",
        "message": "w",
        "details": [],
        "issues": [{
            "title": "Model override uses unavailable provider",
            "description": "Provider(s) not found in OpenCode model cache: someprovider",
            "severity": "warning",
            "affects": ["model resolution"],
        }],
    }])
    probe = tmp_path / "probe.json"
    probe.write_text(
        json.dumps(
            {
                "runtime": {"surface": "opencode"},
                "models": [
                    {
                        "model": "someprovider/model",
                        "registry_admitted": True,
                        "credential_ready": False,
                        "live_entitlement": "not-probed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # When the wrapper receives that probe evidence.
    result = _run(fixture, "--json", "--probe-file", str(probe))

    # Then the finding is confirmed as registry-cache noise, not live entitlement.
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["suspected_count"] == 0
    assert output["confirmed_noise_count"] == 1
    assert output["confirmed_noise"][0]["status"] == "registry-confirmed"
    assert output["confirmed_noise"][0]["live_entitlement"] == "not-probed"


def test_other_harness_registry_does_not_confirm_cache_warning() -> None:
    from scripts.doctor_check import build_report

    payload = {"target": "opencode", "results": [{
        "name": "Configuration", "issues": [{
            "title": "Model override uses unavailable provider",
            "description": "Provider(s) not found in OpenCode model cache: example",
            "severity": "warning", "affects": [],
        }],
    }]}
    probe = {
        "runtime": {"surface": "native"},
        "models": [{"model": "example/model", "registry_admitted": True}],
    }
    report = build_report(payload, None, probe).as_dict()
    assert report["suspected_count"] == 1
    assert report["confirmed_noise_count"] == 0


def test_native_doctor_command_uses_installed_omo_not_opencode_bunx() -> None:
    from scripts.doctor_check import doctor_command

    # Given the native harness and a native version pin.
    # When the diagnostic command is selected.
    command = doctor_command("native", "5.0.0-0.beta.86", "opencode")

    # Then native omo doctor is dispatched without the incompatible OpenCode parser.
    assert command == ["omo", "doctor"]
