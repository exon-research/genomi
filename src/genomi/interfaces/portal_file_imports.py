from __future__ import annotations

import base64
import binascii
import hashlib
import os
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

from . import portal_store, portal_turns, portal_workspaces

JsonObject = dict[str, Any]
MAX_IMPORT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ImportFile:
    filename: str
    content_type: str
    body: bytes
    frame_id: str = ""


def import_project_file(
    project_id: str,
    payload: JsonObject,
    *,
    root: str | Path | None = None,
) -> tuple[HTTPStatus, JsonObject]:
    clean_project_id = str(project_id or "").strip()
    if not clean_project_id or portal_store.get_project(clean_project_id, root=root) is None:
        return HTTPStatus.NOT_FOUND, _error("not_found", "project not found")
    request_or_error = _import_file_from_payload(payload)
    if isinstance(request_or_error, dict):
        return HTTPStatus.BAD_REQUEST, request_or_error
    request = request_or_error
    if len(request.body) > MAX_IMPORT_BYTES:
        return HTTPStatus.REQUEST_ENTITY_TOO_LARGE, _error(
            "file_too_large",
            f"Imported files must be {MAX_IMPORT_BYTES} bytes or smaller.",
        )
    try:
        workspace_relative_path = _write_import_to_workspace(clean_project_id, request, root=root)
    except OSError:
        return HTTPStatus.INTERNAL_SERVER_ERROR, _error(
            "workspace_write_failed",
            "File could not be saved to the project workspace.",
        )
    try:
        artifact = _store_imported_file(clean_project_id, request, workspace_relative_path, root=root)
    except portal_store.ArtifactOriginError:
        return HTTPStatus.BAD_REQUEST, _error(
            "conversation_not_found",
            "That conversation is not part of this project.",
        )
    if artifact is None:
        return HTTPStatus.NOT_FOUND, _error("not_found", "project not found")
    return HTTPStatus.CREATED, {
        "artifact": portal_store.public_artifact_detail(artifact, root=root),
        "imported": {
            "filename": request.filename,
            "workspace_relative_path": workspace_relative_path,
            "content_type": request.content_type,
            "size_bytes": len(request.body),
            "sha256": _sha256_bytes(request.body),
        },
    }


def _store_imported_file(
    project_id: str,
    request: ImportFile,
    workspace_relative_path: str,
    *,
    root: str | Path | None,
) -> JsonObject | None:
    return portal_store.add_artifact_from_bytes(
        project_id,
        kind="project_file",
        renderer="project_file",
        title=workspace_relative_path,
        operation="portal.import_file",
        result=_import_result(request, workspace_relative_path),
        original_filename=request.filename,
        content_type=request.content_type,
        body=request.body,
        frame_id=request.frame_id or None,
        summary={
            "kind": "project_file",
            "source": "portal_import",
            "filename": workspace_relative_path,
            "original_filename": request.filename,
            "content_type": request.content_type,
            "size_bytes": len(request.body),
            "sha256": _sha256_bytes(request.body),
        },
        summary_lines=[
            "Imported file",
            workspace_relative_path,
            request.content_type,
            _format_size(len(request.body)),
        ],
        open_label="Open file",
        root=root,
    )


def _import_file_from_payload(payload: JsonObject) -> ImportFile | JsonObject:
    filename = _safe_filename(payload.get("filename"))
    if not filename:
        return _error("bad_request", "filename required")
    body = _decode_body(payload)
    if body is None:
        return _error("bad_request", "contentBase64 required")
    if not body:
        return _error("bad_request", "file content required")
    return ImportFile(
        filename=filename,
        content_type=_safe_content_type(payload.get("contentType")),
        body=body,
        frame_id=portal_turns.prompt_safe_text(str(payload.get("frameId") or "")).strip(),
    )


def _decode_body(payload: JsonObject) -> bytes | None:
    raw = payload.get("contentBase64")
    if not isinstance(raw, str) or not raw.strip():
        return None
    encoded = raw.split(",", 1)[1] if raw.startswith("data:") and "," in raw else raw
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


def _write_import_to_workspace(
    project_id: str,
    request: ImportFile,
    *,
    root: str | Path | None = None,
) -> str:
    workspace = portal_workspaces.ensure_project_workspace(project_id, root=root)
    destination = _unique_workspace_import_path(workspace, request.filename, request.body)
    _atomic_write_bytes(destination, request.body)
    return destination.relative_to(workspace).as_posix()


def _unique_workspace_import_path(workspace: Path, filename: str, body: bytes) -> Path:
    source_name = Path(filename).name
    stem = Path(source_name).stem or "file"
    suffix = Path(source_name).suffix
    for index in range(1, 1000):
        candidate_name = source_name if index == 1 else f"{stem}-{index}{suffix}"
        candidate = workspace / candidate_name
        try:
            candidate.relative_to(workspace)
        except ValueError:
            continue
        if candidate.is_symlink():
            continue
        if candidate.is_file():
            try:
                if candidate.read_bytes() == body:
                    return candidate
            except OSError:
                pass
            continue
        if not candidate.exists():
            return candidate
    raise OSError("Could not allocate a project workspace import filename.")


def _atomic_write_bytes(destination: Path, body: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, destination)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _import_result(request: ImportFile, workspace_relative_path: str) -> JsonObject:
    return {
        "status": "completed",
        "import": {
            "filename": request.filename,
            "workspace_relative_path": workspace_relative_path,
            "content_type": request.content_type,
            "size_bytes": len(request.body),
            "sha256": _sha256_bytes(request.body),
        },
    }


def _safe_filename(value: Any) -> str:
    raw = portal_turns.prompt_safe_text(str(value or "")).strip()
    if not raw or raw in {".", ".."}:
        return ""
    name = Path(raw).name
    if name != raw or name in {".", ".."} or name.startswith("."):
        return ""
    return name[:160]


def _safe_content_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw or "/" not in raw or any(char.isspace() for char in raw):
        return "application/octet-stream"
    return portal_turns.prompt_safe_text(raw).strip() or "application/octet-stream"


def _sha256_bytes(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def _format_size(size_bytes: int) -> str:
    return f"{size_bytes} byte" + ("" if size_bytes == 1 else "s")


def _error(code: str, message: str) -> JsonObject:
    return {"error": {"code": code, "message": message}}
