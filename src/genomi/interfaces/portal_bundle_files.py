from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import portal_artifact_exports

JsonObject = dict[str, Any]
ZipBlob = tuple[str, Path]
BUNDLE_CONTENT_TYPE = "application/zip"


@dataclass(frozen=True)
class DownloadBundle:
    body: bytes
    filename: str
    content_type: str = BUNDLE_CONTENT_TYPE


def write_json(archive: zipfile.ZipFile, name: str, payload: JsonObject) -> None:
    archive.writestr(name, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def artifact_version_bundle_files(
    version_files: tuple[portal_artifact_exports.ArtifactBundleFileSource, ...],
    *,
    archive_prefix: str,
    token_fallback: str,
    use_archive_filename_in_metadata: bool,
) -> tuple[list[JsonObject], list[ZipBlob]]:
    files: list[JsonObject] = []
    blobs: list[ZipBlob] = []
    for version_file in version_files:
        entry, blob = artifact_version_file_entry(
            version_file,
            archive_prefix=archive_prefix,
            token_fallback=token_fallback,
            use_archive_filename_in_metadata=use_archive_filename_in_metadata,
        )
        files.append(entry)
        if blob is not None:
            blobs.append(blob)
    return files, blobs


def artifact_version_file_entry(
    version_file: portal_artifact_exports.ArtifactBundleFileSource,
    *,
    archive_prefix: str,
    token_fallback: str,
    use_archive_filename_in_metadata: bool,
) -> tuple[JsonObject, ZipBlob | None]:
    version = version_file.version
    version_id = str(version.get("version_id") or "").strip()
    storage_filename = safe_storage_name(str(version.get("filename") or ""))
    archive_filename = storage_filename or f"{download_safe_token(version_id, fallback=token_fallback)}.artifact"
    entry: JsonObject = {
        "version_id": version_id,
        "filename": archive_filename if use_archive_filename_in_metadata else storage_filename,
        "content_type": version.get("content_type"),
        "checksum": version.get("checksum"),
        "size_bytes": version.get("size_bytes"),
        "included": False,
    }
    file_path = version_file.file_path
    if file_path is None or not file_path.is_file():
        return drop_none_values(entry), None
    archive_entry = f"{archive_prefix}/{download_safe_token(version_id, fallback=token_fallback)}/{archive_filename}"
    entry["archive_entry"] = archive_entry
    entry["included"] = True
    return drop_none_values(entry), (archive_entry, file_path)


def safe_storage_name(value: str) -> str:
    if not value or value in {".", ".."}:
        return ""
    path = Path(value)
    if path.is_absolute() or path.name != value:
        return ""
    return value


def download_safe_token(value: str, *, fallback: str) -> str:
    clean = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value).strip("-_")
    return clean[:80] or fallback


def drop_none_values(payload: JsonObject) -> JsonObject:
    return {key: value for key, value in payload.items() if value is not None}
