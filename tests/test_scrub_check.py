from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_NAME = "scripts/scrub_check.sh"
FORBIDDEN_LIST = REPO_ROOT / "forbidden_strings.txt"


def a_forbidden_string() -> str:
    """Take a real pattern from the list.

    Derived rather than hard-coded so this file does not itself contain a
    forbidden string, which would trip the very gate it is testing.
    """
    patterns = [
        line.strip()
        for line in FORBIDDEN_LIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert patterns, "forbidden_strings.txt is empty"
    return patterns[0]


def build_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(FORBIDDEN_LIST, root / "forbidden_strings.txt")
    shutil.copy(REPO_ROOT / SCRIPT_NAME, root / SCRIPT_NAME)
    (root / ".gitignore").write_text(".venv/\ndata/\n", encoding="utf-8")
    (root / "README.md").write_text("neutral content\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def run_gate(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(root / SCRIPT_NAME)], check=False, capture_output=True, text=True
    )


def test_gitignored_virtualenv_does_not_fail_gate(tmp_path: Path) -> None:
    # Given the .venv that the documented --setup step creates, holding a
    # forbidden string it could never publish
    root = build_repo(tmp_path)
    venv = root / "vendor" / "aa-scraper" / ".venv"
    venv.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(
        f"home = {a_forbidden_string()}/somebody/bin\n", encoding="utf-8"
    )

    # When
    result = run_gate(root)

    # Then the gate ignores files that can never be published
    assert result.returncode == 0, result.stderr


def test_untracked_but_publishable_file_fails_gate(tmp_path: Path) -> None:
    # Given a not-yet-staged file that would be published
    root = build_repo(tmp_path)
    (root / "leak.md").write_text(
        f"home = {a_forbidden_string()}/somebody\n", encoding="utf-8"
    )

    # When
    result = run_gate(root)

    # Then the gate still catches it
    assert result.returncode == 1


def test_clean_repo_passes(tmp_path: Path) -> None:
    # Given a tree with nothing forbidden in it
    root = build_repo(tmp_path)

    # When
    result = run_gate(root)

    # Then
    assert result.returncode == 0, result.stderr


def test_force_added_local_data_is_rejected(tmp_path: Path) -> None:
    root = build_repo(tmp_path)
    data = root / "data" / "leaderboard.csv"
    data.parent.mkdir()
    data.write_text("Model,Score\nSynthetic fixture,1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-f", str(data)], check=True)

    result = run_gate(root)

    assert result.returncode == 1
    assert "local-only" in result.stderr


def test_exported_csv_outside_cache_is_rejected(tmp_path: Path) -> None:
    root = build_repo(tmp_path)
    (root / "export.csv").write_text(
        "Model,Score\nSynthetic fixture,1\n", encoding="utf-8"
    )

    result = run_gate(root)

    assert result.returncode == 1
