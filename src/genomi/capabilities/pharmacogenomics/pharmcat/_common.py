from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]
PHARMCAT_RUN_SCHEMA = "genomi-pharmcat-run-v1"
PHARMCAT_STATUS_SCHEMA = "genomi-pharmcat-status-v1"
PHARMCAT_IMPORT_SCHEMA = "genomi-pharmcat-artifact-import-v1"
PHARMCAT_DOCS = [
    {
        "title": "PharmCAT",
        "url": "https://pharmcat.clinpgx.org/",
        "type": "tool_home",
    },
    {
        "title": "Running the PharmCAT Pipeline",
        "url": "https://pharmcat.clinpgx.org/using/Running-PharmCAT-Pipeline/",
        "type": "pipeline_documentation",
    },
    {
        "title": "PharmCAT VCF Requirements",
        "url": "https://pharmcat.clinpgx.org/using/VCF-Requirements/",
        "type": "input_requirements",
    },
]


def sqlite_error_cls() -> type[BaseException]:
    import sqlite3 as _sqlite3

    return _sqlite3.Error


def _as_dicts(value: object) -> list[JsonObject]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _first_string(value: object) -> str | None:
    for item in _as_list(value):
        if isinstance(item, str) and item:
            return item
    return None


def _clean_report_text(value: object) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    return text or None


def _without_none(value: JsonObject) -> JsonObject:
    return {key: item for key, item in value.items() if item is not None and item != []}


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _artifact_fingerprint(path: Path, artifact_type: str) -> JsonObject:
    content_hash = _file_sha256(path)
    return _without_none(
        {
            "artifact_type": artifact_type,
            "name": path.name,
            "size_bytes": _size(path),
            "content_sha256": content_hash,
            "artifact_id": f"pharmcat_artifact_sha256:{content_hash}" if content_hash else None,
        }
    )


def _artifact_source_summary(summary: JsonObject) -> JsonObject | None:
    artifact = summary.get("artifact")
    if not isinstance(artifact, dict):
        return None
    return _without_none(
        {
            "artifact_type": artifact.get("artifact_type"),
            "name": artifact.get("name"),
            "size_bytes": artifact.get("size_bytes"),
            "content_sha256": artifact.get("content_sha256"),
            "artifact_id": artifact.get("artifact_id"),
        }
    )


def _int_or_original(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _tail(value: str | bytes | None, *, max_chars: int = 4000) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text[-max_chars:]


def _clean_base_filename(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = "".join(character if character.isalnum() or character in {"-", "_", "."} else "-" for character in str(value).strip())
    cleaned = "-".join(piece for piece in cleaned.split("-") if piece)
    return cleaned or None
