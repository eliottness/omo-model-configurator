"""Synthetic fixtures only: no AA measurements or captured HTML are distributed."""

from pathlib import Path
import hashlib
import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from src.components.config import load_config
from src.main import main


def test_default_model_scope_includes_retired_models(monkeypatch) -> None:
    monkeypatch.delenv("TARGET_URL", raising=False)
    config = load_config(str(Path(__file__).parents[1] / "config.yaml"))
    assert parse_qs(urlsplit(config["target_url"]).query)["status"] == ["all"]


def test_failed_fetch_never_accepts_an_existing_cache(tmp_path: Path) -> None:
    cache = tmp_path / "leaderboard.csv"
    cache.write_text("Model,Score\nSynthetic Old Model,7\n", encoding="utf-8")
    with patch("src.main.setup_logger"), patch(
        "src.main.load_config",
        return_value={"target_url": "https://example.test", "output_csv_path": str(cache)},
    ), patch("src.main.fetch_html", return_value=None):
        result = main()
    assert result == 1
    assert cache.read_text(encoding="utf-8") == "Model,Score\nSynthetic Old Model,7\n"


def test_failed_write_returns_failure(tmp_path: Path) -> None:
    with patch("src.main.setup_logger"), patch(
        "src.main.load_config",
        return_value={
            "target_url": "https://example.test",
            "output_csv_path": str(tmp_path / "result.csv"),
        },
    ), patch("src.main.fetch_html", return_value="<table></table>"), patch(
        "src.main.parse_leaderboard", return_value=[["Model"], ["Synthetic Model"]],
    ), patch("src.main.write_to_csv", side_effect=OSError("synthetic disk failure")):
        assert main() == 1


def test_successful_scrape_records_local_provenance(tmp_path: Path) -> None:
    cache = tmp_path / "leaderboard.csv"
    html = """<table><thead><tr>
    <th>Model</th><th>Artificial Analysis Intelligence Index</th>
    <th>Cost per Task USD</th><th>Input Price USD/1M Tokens</th>
    <th>Output Price USD/1M Tokens</th><th>Median Tokens/s</th>
    </tr></thead><tbody><tr><td>Synthetic Model</td><td>7*</td>
    <td>$0.01</td><td>$0.02</td><td>$0.03</td><td>4</td>
    </tr></tbody></table>"""
    with patch("src.main.setup_logger"), patch(
        "src.main.load_config", return_value={
            "target_url": "https://example.test/models?status=all",
            "output_csv_path": str(cache),
            "output_add_timestamp": False,
            "output_localize_numbers": False,
            "output_manifest": True,
        },
    ), patch("src.main.fetch_html", return_value=html):
        assert main() == 0

    manifest_path = cache.with_suffix(".csv.manifest.json")
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(cache.read_bytes()).hexdigest()
    assert manifest["csv_sha256"] == digest
    assert manifest["row_count"] == 1
    assert manifest["status_filter"] == "all"
    assert manifest["source_html_sha256"] == hashlib.sha256(html.encode()).hexdigest()
    assert (tmp_path / "snapshots" / f"{digest}.csv").read_bytes() == cache.read_bytes()
    assert json.loads(
        (tmp_path / "snapshots" / f"{digest}.csv.manifest.json").read_text()
    ) == manifest


def test_model_url_records_the_scope_actually_scraped() -> None:
    from src.components.snapshot import normalize_model_url

    result = normalize_model_url(
        "https://artificialanalysis.ai/leaderboards/models?status=current&sort=score"
    )
    assert parse_qs(urlsplit(result).query) == {"status": ["all"], "sort": ["score"]}


def test_invalid_table_does_not_replace_previous_cache(tmp_path: Path) -> None:
    cache = tmp_path / "leaderboard.csv"
    cache.write_text("previous local data", encoding="utf-8")
    with patch("src.main.setup_logger"), patch(
        "src.main.load_config", return_value={
            "target_url": "https://example.test/models?status=all",
            "output_csv_path": str(cache),
            "output_add_timestamp": False,
            "output_manifest": True,
        },
    ), patch("src.main.fetch_html", return_value="<table></table>"), patch(
        "src.main.parse_leaderboard", return_value=[["Model"], [""]],
    ):
        assert main() == 1
    assert cache.read_text(encoding="utf-8") == "previous local data"
