from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Callable

from ..runtime.paths import genomi_data_root
from . import (
    portal_artifact_environment,
    portal_artifact_reproduction,
    portal_artifact_review,
    portal_artifact_work_steps,
)

JsonObject = dict[str, Any]
VersionBlobWriter = Callable[[BinaryIO], None]


def artifacts_dir(project_id: str, root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / "portal" / "artifacts" / project_id


def create_artifact_version(
    *,
    project_id: str,
    artifact_id: str,
    artifact_kind: str,
    renderer: str,
    operation: str,
    result: JsonObject,
    summary: JsonObject,
    public_payload: JsonObject,
    host_agent_id: str,
    file_path: str | None,
    created_at: str,
    reproduction: JsonObject | None = None,
    producing_work_step: JsonObject | None = None,
    root: str | Path | None = None,
) -> JsonObject | None:
    raw_path = file_path.strip() if isinstance(file_path, str) and file_path.strip() else ""
    if not raw_path:
        return None
    source = Path(raw_path)
    if not source.is_file():
        return None

    def write_blob(writer: BinaryIO) -> None:
        with source.open("rb") as reader:
            shutil.copyfileobj(reader, writer)

    return _create_artifact_version(
        project_id=project_id,
        artifact_id=artifact_id,
        artifact_kind=artifact_kind,
        renderer=renderer,
        operation=operation,
        result=result,
        summary=summary,
        public_payload=public_payload,
        host_agent_id=host_agent_id,
        original_filename=source.name,
        content_type=None,
        created_at=created_at,
        write_blob=write_blob,
        reproduction=reproduction,
        producing_work_step=producing_work_step,
        root=root,
    )


def create_artifact_version_from_bytes(
    *,
    project_id: str,
    artifact_id: str,
    artifact_kind: str,
    renderer: str,
    operation: str,
    result: JsonObject,
    summary: JsonObject,
    public_payload: JsonObject,
    host_agent_id: str,
    original_filename: str,
    content_type: str,
    body: bytes,
    created_at: str,
    reproduction: JsonObject | None = None,
    producing_work_step: JsonObject | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    def write_blob(writer: BinaryIO) -> None:
        writer.write(body)

    return _create_artifact_version(
        project_id=project_id,
        artifact_id=artifact_id,
        artifact_kind=artifact_kind,
        renderer=renderer,
        operation=operation,
        result=result,
        summary=summary,
        public_payload=public_payload,
        host_agent_id=host_agent_id,
        original_filename=original_filename,
        content_type=_safe_content_type(content_type),
        created_at=created_at,
        write_blob=write_blob,
        reproduction=reproduction,
        producing_work_step=producing_work_step,
        root=root,
    )


def _create_artifact_version(
    *,
    project_id: str,
    artifact_id: str,
    artifact_kind: str,
    renderer: str,
    operation: str,
    result: JsonObject,
    summary: JsonObject,
    public_payload: JsonObject,
    host_agent_id: str,
    original_filename: str,
    content_type: str | None,
    created_at: str,
    write_blob: VersionBlobWriter,
    reproduction: JsonObject | None = None,
    producing_work_step: JsonObject | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    version_id = f"ver_{uuid.uuid4().hex[:12]}"
    filename = _snapshot_filename(version_id, original_filename)
    version_content_type = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    destination = artifacts_dir(project_id, root) / "versions" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as writer:
            write_blob(writer)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(tmp, destination)
        checksum = f"sha256:{_sha256_file(destination)}"
        size_bytes = destination.stat().st_size
    except Exception:
        _unlink_best_effort(tmp)
        _unlink_best_effort(destination)
        raise
    version = {
        "version_id": version_id,
        "artifact_id": artifact_id,
        "project_id": project_id,
        "created_at": created_at,
        "filename": filename,
        "content_type": version_content_type,
        "checksum": checksum,
        "size_bytes": size_bytes,
        "is_intermediate": False,
    }
    public_reproduction = portal_artifact_reproduction.public_reproduction(reproduction)
    if public_reproduction is not None:
        version["reproduction"] = public_reproduction
    public_work_step = portal_artifact_work_steps.public_producing_work_step(producing_work_step)
    if public_work_step is not None:
        version["producing_work_step"] = public_work_step
    version["environment"] = portal_artifact_environment.artifact_environment_snapshot(
        artifact_kind=artifact_kind,
        renderer=renderer,
        operation=operation,
        created_at=created_at,
        host_agent_id=host_agent_id,
        root=root,
    )
    version["review"] = portal_artifact_review.artifact_version_review(
        artifact_kind=artifact_kind,
        renderer=renderer,
        operation=operation,
        result=result,
        summary=summary,
        public_payload=public_payload,
        version=version,
        reproduction=public_reproduction,
        created_at=created_at,
    )
    return version


def artifact_version_file_path(version: JsonObject, *, root: str | Path | None = None) -> Path | None:
    project_id = version.get("project_id")
    filename = version.get("filename")
    if not isinstance(project_id, str) or not _safe_storage_name(project_id):
        return None
    if not isinstance(filename, str) or not _safe_storage_name(filename):
        return None
    version_dir = (artifacts_dir(project_id, root) / "versions").resolve()
    candidate = (version_dir / filename).resolve()
    try:
        candidate.relative_to(version_dir)
    except ValueError:
        return None
    return candidate


def remove_artifact_version_blob(version: JsonObject, *, root: str | Path | None = None) -> None:
    path = artifact_version_file_path(version, root=root)
    if path is not None:
        _unlink_best_effort(path)


def _safe_storage_name(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    path = Path(value)
    return not path.is_absolute() and path.name == value


def _safe_content_type(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw or "/" not in raw or any(char.isspace() for char in raw):
        return "application/octet-stream"
    return raw


def _unlink_best_effort(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _snapshot_filename(version_id: str, original_name: str) -> str:
    suffix = Path(original_name).suffix
    return f"{version_id}{suffix or '.artifact'}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
