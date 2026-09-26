"""Local-only cache validation and provenance; never uploads collected data."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

REQUIRED_COLUMNS: Final = frozenset({
    "Model", "Artificial Analysis Intelligence Index", "Cost per Task USD",
    "Input Price USD/1M Tokens", "Output Price USD/1M Tokens", "Median Tokens/s",
})


class InvalidSnapshotError(ValueError):
    """The scraped table is incomplete and must not replace a local cache."""


def normalize_model_url(url: str) -> str:
    """Record the same all-status scope that the models browser actually selects."""
    parts = urlsplit(url)
    if parts.hostname not in {"artificialanalysis.ai", "www.artificialanalysis.ai"}:
        return url
    if parts.path.rstrip("/") != "/leaderboards/models":
        return url
    query = [(key, value) for key, value in parse_qsl(parts.query) if key != "status"]
    query.append(("status", "all"))
    return urlunsplit(parts._replace(query=urlencode(query)))


def validate_model_table(data: list[list[str]]) -> None:
    if len(data) < 2:
        raise InvalidSnapshotError("model table has no data rows")
    headers = data[0]
    if not REQUIRED_COLUMNS.issubset(headers):
        missing = sorted(REQUIRED_COLUMNS.difference(headers))
        raise InvalidSnapshotError(f"model table is missing columns: {missing}")
    if len(set(headers)) != len(headers):
        raise InvalidSnapshotError("model table has duplicate column names")
    model_index = headers.index("Model")
    for index, row in enumerate(data[1:], start=1):
        if len(row) != len(headers) or not row[model_index].strip():
            raise InvalidSnapshotError(f"invalid model row {index}")


def atomic_write(path: Path, content: bytes) -> None:
    """Replace one local artifact only after its complete contents are written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".cache-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def record_local_snapshot(
    csv_path: Path, source_url: str, source_html: str, data: list[list[str]],
) -> None:
    """Cache an immutable copy and a hash-bound manifest alongside the latest CSV."""
    raw = csv_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    cached = csv_path.parent / "snapshots" / f"{digest}.csv"
    if not cached.exists():
        atomic_write(cached, raw)
    elif cached.read_bytes() != raw:
        raise InvalidSnapshotError("immutable local cache content differs from its digest")
    manifest = {
        "schema_version": 1,
        "local_only": True,
        "source_url": source_url,
        "status_filter": parse_qs(urlsplit(source_url).query).get("status", ["unspecified"])[0],
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "csv_sha256": digest,
        "source_html_sha256": hashlib.sha256(source_html.encode("utf-8")).hexdigest(),
        "row_count": len(data) - 1,
        "columns": data[0],
        "benchmark_revision": None,
        "benchmark_revision_reason": "not-exposed-in-table",
    }
    encoded = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    historical_manifest = cached.with_suffix(cached.suffix + ".manifest.json")
    if not historical_manifest.exists():
        atomic_write(historical_manifest, encoded)
    atomic_write(csv_path.with_suffix(csv_path.suffix + ".manifest.json"), encoded)
