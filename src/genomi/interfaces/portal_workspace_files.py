from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import portal_store, portal_turns, portal_workspaces

JsonObject = dict[str, Any]
WorkspaceSnapshot = dict[str, "WorkspaceFileFingerprint"]
MAX_WORKSPACE_FILE_BYTES = 4 * 1024 * 1024
MAX_WORKSPACE_FILE_PREVIEW_BYTES = 256 * 1024
MAX_WORKSPACE_NOTEBOOK_PREVIEW_BYTES = 768 * 1024
MAX_IMPORTED_WORKSPACE_FILES = 24
MAX_NOTEBOOK_PREVIEW_CELLS = 24
MAX_NOTEBOOK_CELL_SOURCE_CHARS = 2400
_SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".hg", ".svn"}
_TEXT_EXTENSIONS = {".csv", ".json", ".jsonl", ".log", ".md", ".txt", ".tsv", ".vcf", ".yaml", ".yml"}
_HOST_AGENT_WORKSPACE_SOURCE = "host_agent_workspace"
_PORTAL_IMPORT_SOURCE = "portal_import"
_LINKED_WORKSPACE_FILE_SOURCES = {_HOST_AGENT_WORKSPACE_SOURCE, _PORTAL_IMPORT_SOURCE}


@dataclass(frozen=True)
class WorkspaceFileFingerprint:
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True)
class WorkspaceFileResolution:
    status: str
    path: Path | None = None


@dataclass(frozen=True)
class WorkspaceDocumentFile:
    status: str
    relative_path: str = ""
    name: str = ""
    content_type: str = ""
    body: bytes = b""
    reason: str = ""


def workspace_file_snapshot(workspace: str | Path) -> WorkspaceSnapshot:
    root = _workspace_root(workspace)
    if root is None:
        return {}
    return {
        rel_path: fingerprint
        for rel_path, path, fingerprint in _iter_workspace_files(root)
    }


def list_project_workspace_files(project_id: str, root: str | Path | None = None) -> JsonObject | None:
    clean_project_id = str(project_id or "").strip()
    if not clean_project_id or portal_store.get_project(clean_project_id, root=root) is None:
        return None
    workspace = portal_workspaces.project_workspace_dir(clean_project_id, root=root)
    workspace_root = _workspace_root(workspace)
    artifacts_by_filename = _workspace_artifacts_by_filename(clean_project_id, root=root)
    files = [
        _public_workspace_file(
            clean_project_id,
            rel_path,
            path,
            fingerprint,
            artifacts_by_filename.get(rel_path, []),
            root=root,
        )
        for rel_path, path, fingerprint in _iter_workspace_files(workspace_root)
    ] if workspace_root is not None else []
    return {
        "project_id": clean_project_id,
        "workspace": portal_workspaces.project_workspace_metadata(clean_project_id),
        "summary": {
            "total_files": len(files),
            "linked_artifacts": sum(1 for item in files if item.get("artifact_id")),
        },
        "files": files,
    }


def preview_project_workspace_file(project_id: str, relative_path: str | None, root: str | Path | None = None) -> JsonObject:
    clean_project_id = str(project_id or "").strip()
    rel_path = portal_turns.prompt_safe_text(str(relative_path or "")).strip()
    if not clean_project_id or portal_store.get_project(clean_project_id, root=root) is None:
        return _preview_status("missing_project", clean_project_id, rel_path, "Project not found.")
    if not rel_path:
        return _preview_status("missing_path", clean_project_id, rel_path, "Missing project file path.")
    workspace = portal_workspaces.project_workspace_dir(clean_project_id, root=root)
    workspace_root = _workspace_root(workspace)
    resolution = _resolve_workspace_file_path(workspace_root, rel_path)
    if resolution.path is None:
        return _preview_status(resolution.status, clean_project_id, rel_path, _preview_status_reason(resolution.status))
    path = resolution.path
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return _preview_status("not_found", clean_project_id, rel_path, _preview_status_reason("not_found"))
    except OSError:
        return _preview_status("unreadable", clean_project_id, rel_path, _preview_status_reason("unreadable"))
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    display = _workspace_file_display(rel_path, content_type, record_source="", opened_preview=True)
    base: JsonObject = {
        "project_id": clean_project_id,
        "relative_path": rel_path,
        "name": path.name,
        "content_type": content_type,
        "file_kind": display["file_kind"],
        "kind_label": display["kind_label"],
        "record_type": display["record_type"],
        "record_label": display["record_label"],
        "size_bytes": stat_result.st_size,
        "size_label": _format_size(stat_result.st_size),
        "modified_at": _iso_from_mtime_ns(stat_result.st_mtime_ns),
    }
    if _is_document_preview(path, content_type):
        if stat_result.st_size > MAX_WORKSPACE_FILE_BYTES:
            return {
                **base,
                "status": "unavailable",
                "preview_kind": "none",
                "reason": "Document is larger than the portal document preview limit.",
                "preview_limit_bytes": MAX_WORKSPACE_FILE_BYTES,
            }
        return {
            **base,
            "status": "available",
            "preview_kind": "document",
            "document_url": _workspace_file_document_url(clean_project_id, rel_path),
            "preview_limit_bytes": MAX_WORKSPACE_FILE_BYTES,
        }
    if _is_notebook_preview(path, content_type):
        if stat_result.st_size > MAX_WORKSPACE_NOTEBOOK_PREVIEW_BYTES:
            return {
                **base,
                "status": "unavailable",
                "preview_kind": "none",
                "reason": "Notebook is larger than the portal notebook preview limit.",
                "preview_limit_bytes": MAX_WORKSPACE_NOTEBOOK_PREVIEW_BYTES,
            }
    elif stat_result.st_size > MAX_WORKSPACE_FILE_PREVIEW_BYTES:
        return {
            **base,
            "status": "unavailable",
            "preview_kind": "none",
            "reason": "File is larger than the portal preview limit.",
            "preview_limit_bytes": MAX_WORKSPACE_FILE_PREVIEW_BYTES,
    }
    try:
        body = path.read_bytes()
    except OSError:
        return {
            **base,
            "status": "unreadable",
            "preview_kind": "none",
            "reason": _preview_status_reason("unreadable"),
            "preview_limit_bytes": MAX_WORKSPACE_FILE_PREVIEW_BYTES,
        }
    if _is_notebook_preview(path, content_type):
        return {
            **base,
            "status": "available",
            "preview_kind": "notebook",
            "notebook": _notebook_preview(body),
            "preview_limit_bytes": MAX_WORKSPACE_NOTEBOOK_PREVIEW_BYTES,
        }
    if _is_text_preview(path, content_type):
        text = portal_turns.prompt_safe_text(body.decode("utf-8", errors="replace"))
        return {
            **base,
            "status": "available",
            "preview_kind": "text",
            "text": text,
            "truncated": False,
            "preview_limit_bytes": MAX_WORKSPACE_FILE_PREVIEW_BYTES,
        }
    if content_type.startswith("image/"):
        return {
            **base,
            "status": "available",
            "preview_kind": "image",
            "data_url": f"data:{content_type};base64,{base64.b64encode(body).decode('ascii')}",
            "preview_limit_bytes": MAX_WORKSPACE_FILE_PREVIEW_BYTES,
        }
    return {
        **base,
        "status": "unavailable",
        "preview_kind": "none",
        "reason": "This file type is not previewable in the portal.",
        "preview_limit_bytes": MAX_WORKSPACE_FILE_PREVIEW_BYTES,
    }


def read_project_workspace_document_file(project_id: str, relative_path: str | None, root: str | Path | None = None) -> WorkspaceDocumentFile:
    clean_project_id = str(project_id or "").strip()
    rel_path = portal_turns.prompt_safe_text(str(relative_path or "")).strip()
    if not clean_project_id or portal_store.get_project(clean_project_id, root=root) is None:
        return WorkspaceDocumentFile("missing_project", rel_path, Path(rel_path).name if rel_path else "", reason="Project not found.")
    if not rel_path:
        return WorkspaceDocumentFile("missing_path", reason="Missing project file path.")
    workspace = portal_workspaces.project_workspace_dir(clean_project_id, root=root)
    workspace_root = _workspace_root(workspace)
    resolution = _resolve_workspace_file_path(workspace_root, rel_path)
    if resolution.path is None:
        return WorkspaceDocumentFile(
            resolution.status,
            rel_path,
            Path(rel_path).name if rel_path else "",
            reason=_preview_status_reason(resolution.status),
        )
    path = resolution.path
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not _is_document_preview(path, content_type):
        return WorkspaceDocumentFile(
            "unsupported_type",
            rel_path,
            path.name,
            content_type,
            reason="This project file is not a portal document preview.",
        )
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return WorkspaceDocumentFile("not_found", rel_path, path.name, content_type, reason=_preview_status_reason("not_found"))
    except OSError:
        return WorkspaceDocumentFile("unreadable", rel_path, path.name, content_type, reason=_preview_status_reason("unreadable"))
    if stat_result.st_size > MAX_WORKSPACE_FILE_BYTES:
        return WorkspaceDocumentFile(
            "unavailable",
            rel_path,
            path.name,
            content_type,
            reason="Document is larger than the portal document preview limit.",
        )
    try:
        body = path.read_bytes()
    except OSError:
        return WorkspaceDocumentFile("unreadable", rel_path, path.name, content_type, reason=_preview_status_reason("unreadable"))
    return WorkspaceDocumentFile("available", rel_path, path.name, content_type, body)


def materialize_run_workspace_files(
    *,
    project_id: str,
    frame_id: str | None,
    run_id: str,
    workspace: str | Path,
    before: WorkspaceSnapshot | None,
) -> list[JsonObject]:
    clean_project_id = str(project_id or "").strip()
    if not clean_project_id:
        return []
    root = _workspace_root(workspace)
    if root is None:
        return []
    baseline = before or {}
    created: list[JsonObject] = []
    for rel_path, path, fingerprint in _iter_workspace_files(root):
        if len(created) >= MAX_IMPORTED_WORKSPACE_FILES:
            break
        if baseline.get(rel_path) == fingerprint:
            continue
        if fingerprint.size_bytes > MAX_WORKSPACE_FILE_BYTES:
            continue
        artifact = _materialize_workspace_file(
            project_id=clean_project_id,
            frame_id=frame_id,
            run_id=run_id,
            rel_path=rel_path,
            path=path,
            size_bytes=fingerprint.size_bytes,
        )
        if artifact is not None:
            created.append(artifact)
    return created


def _materialize_workspace_file(
    *,
    project_id: str,
    frame_id: str | None,
    run_id: str,
    rel_path: str,
    path: Path,
    size_bytes: int,
) -> JsonObject | None:
    try:
        body = path.read_bytes()
    except OSError:
        return None
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    checksum = _sha256_bytes(body)
    return portal_store.add_artifact_from_bytes(
        project_id,
        kind="project_file",
        renderer="project_file",
        title=rel_path,
        operation="portal.agent_file",
        result={
            "status": "completed",
            "source": "host_agent_workspace",
            "filename": rel_path,
            "run_id": portal_turns.prompt_safe_text(str(run_id or "")).strip(),
        },
        original_filename=path.name,
        content_type=content_type,
        body=body,
        frame_id=frame_id,
        summary={
            "kind": "project_file",
            "source": "host_agent_workspace",
            "filename": rel_path,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "sha256": checksum,
        },
        summary_lines=[
            "Produced file",
            rel_path,
            content_type,
            _format_size(size_bytes),
        ],
        open_label="Open file",
    )


def _iter_workspace_files(root: Path) -> list[tuple[str, Path, WorkspaceFileFingerprint]]:
    files: list[tuple[str, Path, WorkspaceFileFingerprint]] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = sorted(dirname for dirname in dirnames if not _skip_path_part(dirname))
        for filename in sorted(filenames):
            if _skip_path_part(filename):
                continue
            path = Path(dirpath) / filename
            if not _candidate_file(root, path):
                continue
            try:
                stat = path.stat()
                rel_path = path.relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            if not rel_path or rel_path.startswith("../"):
                continue
            files.append((rel_path, path, WorkspaceFileFingerprint(size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)))
    return files


def _candidate_file(root: Path, path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    for part in rel.parts:
        if _skip_path_part(part):
            return False
    return True


def _skip_path_part(part: str) -> bool:
    return not part or part in {".", ".."} or part.startswith(".") or part in _SKIP_DIRS


def _workspace_root(workspace: str | Path) -> Path | None:
    try:
        root = Path(workspace).resolve()
    except OSError:
        return None
    if not root.is_dir():
        return None
    return root


def _resolve_workspace_file_path(root: Path | None, relative_path: str) -> WorkspaceFileResolution:
    if root is None:
        return WorkspaceFileResolution("not_found")
    try:
        rel = Path(relative_path)
    except (TypeError, ValueError):
        return WorkspaceFileResolution("path_escape")
    if rel.is_absolute():
        return WorkspaceFileResolution("path_escape")
    parts = rel.parts
    if not parts:
        return WorkspaceFileResolution("missing_path")
    if any(part in {"", ".", ".."} for part in parts):
        return WorkspaceFileResolution("path_escape")
    if any(_skip_path_part(part) for part in parts):
        return WorkspaceFileResolution("not_found")
    candidate = root
    for part in parts:
        candidate = candidate / part
        try:
            is_symlink = candidate.is_symlink()
        except (OSError, ValueError):
            return WorkspaceFileResolution("path_escape")
        if is_symlink:
            return WorkspaceFileResolution("path_escape")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return WorkspaceFileResolution("path_escape")
    try:
        stat_result = candidate.stat()
    except FileNotFoundError:
        return WorkspaceFileResolution("not_found")
    except (OSError, ValueError):
        return WorkspaceFileResolution("unreadable")
    if not stat.S_ISREG(stat_result.st_mode):
        return WorkspaceFileResolution("not_found")
    return WorkspaceFileResolution("available", candidate)


def _preview_status(status: str, project_id: str, relative_path: str, reason: str) -> JsonObject:
    payload: JsonObject = {
        "status": status,
        "preview_kind": "none",
        "reason": reason,
        "preview_limit_bytes": MAX_WORKSPACE_FILE_PREVIEW_BYTES,
    }
    clean_project_id = portal_turns.prompt_safe_text(str(project_id or "")).strip()
    clean_relative_path = portal_turns.prompt_safe_text(str(relative_path or "")).strip()
    if clean_project_id:
        payload["project_id"] = clean_project_id
    if clean_relative_path:
        content_type = mimetypes.guess_type(clean_relative_path)[0] or "application/octet-stream"
        display = _workspace_file_display(clean_relative_path, content_type, record_source="", opened_preview=True)
        payload["relative_path"] = clean_relative_path
        payload["name"] = Path(clean_relative_path).name
        payload["content_type"] = content_type
        payload["file_kind"] = display["file_kind"]
        payload["kind_label"] = display["kind_label"]
        payload["record_type"] = display["record_type"]
        payload["record_label"] = display["record_label"]
    return payload


def _preview_status_reason(status: str) -> str:
    return {
        "missing_path": "Missing project file path.",
        "missing_project": "Project not found.",
        "path_escape": "Project file path is outside or aliases the project boundary.",
        "not_found": "Project file not found.",
        "unreadable": "Project file could not be read for preview.",
        "unavailable": "Project file preview is unavailable.",
    }.get(status, "Project file preview failed.")


def _is_text_preview(path: Path, content_type: str) -> bool:
    clean_type = str(content_type or "").lower()
    if clean_type.startswith("text/"):
        return True
    if clean_type in {"application/json", "application/x-ndjson", "application/xml"}:
        return True
    return path.suffix.lower() in _TEXT_EXTENSIONS


def _is_document_preview(path: Path, content_type: str) -> bool:
    return str(content_type or "").lower() == "application/pdf" or path.suffix.lower() == ".pdf"


def _is_notebook_preview(path: Path, content_type: str) -> bool:
    clean_type = str(content_type or "").lower()
    return path.suffix.lower() == ".ipynb" or clean_type in {"application/x-ipynb+json", "application/vnd.jupyter"}


def _workspace_file_document_url(project_id: str, relative_path: str) -> str:
    return f"/api/projects/{quote(project_id, safe='')}/workspace/file?path={quote(relative_path, safe='')}"


def _notebook_preview(body: bytes) -> JsonObject:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "status": "unreadable",
            "summary": "Notebook could not be parsed.",
            "cell_count": 0,
            "cells": [],
        }
    if not isinstance(payload, dict):
        return {
            "status": "unreadable",
            "summary": "Notebook content is not a notebook object.",
            "cell_count": 0,
            "cells": [],
        }
    cells = payload.get("cells") if isinstance(payload.get("cells"), list) else []
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    language = _notebook_language(metadata)
    preview_cells = [_notebook_cell_preview(index, cell) for index, cell in enumerate(cells[:MAX_NOTEBOOK_PREVIEW_CELLS], start=1)]
    code_count = sum(1 for cell in cells if isinstance(cell, dict) and cell.get("cell_type") == "code")
    markdown_count = sum(1 for cell in cells if isinstance(cell, dict) and cell.get("cell_type") == "markdown")
    return {
        "status": "available",
        "nbformat": int(payload.get("nbformat") or 0) if isinstance(payload.get("nbformat"), int) else None,
        "language": language,
        "cell_count": len(cells),
        "code_cell_count": code_count,
        "markdown_cell_count": markdown_count,
        "shown_cell_count": len(preview_cells),
        "truncated": len(cells) > len(preview_cells),
        "summary": _notebook_summary(len(cells), code_count, markdown_count, language),
        "cells": preview_cells,
    }


def _notebook_language(metadata: JsonObject) -> str:
    language_info = metadata.get("language_info") if isinstance(metadata.get("language_info"), dict) else {}
    kernelspec = metadata.get("kernelspec") if isinstance(metadata.get("kernelspec"), dict) else {}
    return portal_turns.prompt_safe_text(str(language_info.get("name") or kernelspec.get("language") or kernelspec.get("name") or "")).strip()


def _notebook_summary(cell_count: int, code_count: int, markdown_count: int, language: str) -> str:
    parts = [f"{cell_count} cell" + ("" if cell_count == 1 else "s")]
    if code_count:
        parts.append(f"{code_count} code")
    if markdown_count:
        parts.append(f"{markdown_count} markdown")
    if language:
        parts.append(language)
    return " · ".join(parts)


def _notebook_cell_preview(index: int, cell: Any) -> JsonObject:
    if not isinstance(cell, dict):
        return {"index": index, "cell_type": "unknown", "source": "", "line_count": 0, "output_count": 0, "truncated": False}
    cell_type = portal_turns.prompt_safe_text(str(cell.get("cell_type") or "unknown")).strip() or "unknown"
    source = _notebook_source_text(cell.get("source"))
    output_count = len(cell.get("outputs")) if isinstance(cell.get("outputs"), list) else 0
    line_count = len(source.splitlines()) if source else 0
    truncated = len(source) > MAX_NOTEBOOK_CELL_SOURCE_CHARS
    if truncated:
        source = source[:MAX_NOTEBOOK_CELL_SOURCE_CHARS].rstrip() + "\n..."
    return {
        "index": index,
        "cell_type": cell_type,
        "source": source,
        "line_count": line_count,
        "output_count": output_count,
        "truncated": truncated,
    }


def _notebook_source_text(source: Any) -> str:
    if isinstance(source, list):
        text = "".join(str(part) for part in source)
    else:
        text = str(source or "")
    return portal_turns.prompt_safe_text(text.replace("\r\n", "\n").replace("\r", "\n"))


def _sha256_bytes(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def _format_size(size_bytes: int) -> str:
    return f"{size_bytes} byte" + ("" if size_bytes == 1 else "s")


def _workspace_file_display(
    relative_path: str,
    content_type: str,
    *,
    record_source: str,
    opened_preview: bool = False,
) -> JsonObject:
    file_kind = _workspace_file_kind(relative_path, content_type)
    record_type = _workspace_file_record_type(record_source=record_source, opened_preview=opened_preview)
    return {
        "file_kind": file_kind,
        "kind_label": _workspace_file_kind_label(file_kind),
        "record_type": record_type,
        "record_label": _workspace_file_record_label(record_type),
    }


def _workspace_file_kind(relative_path: str, content_type: str) -> str:
    clean_type = str(content_type or "").lower()
    name = str(relative_path or "").lower()
    if clean_type == "application/pdf" or name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".ipynb") or clean_type in {"application/x-ipynb+json", "application/vnd.jupyter"}:
        return "notebook"
    if clean_type == "text/markdown" or name.endswith((".md", ".markdown")):
        return "markdown"
    if clean_type.startswith("image/"):
        return "image"
    if name.endswith((".py", ".r", ".sh", ".js", ".ts", ".sql")):
        return "code"
    if clean_type in {"text/csv", "text/tab-separated-values"} or name.endswith((".csv", ".tsv")):
        return "table"
    if clean_type.startswith("text/") or name.endswith((".txt", ".log")):
        return "text"
    if clean_type == "application/json" or clean_type.endswith("+json") or name.endswith((".json", ".jsonl")):
        return "data"
    return "file"


def _workspace_file_kind_label(file_kind: str) -> str:
    return {
        "pdf": "PDF document",
        "notebook": "Notebook",
        "markdown": "Markdown",
        "image": "Image",
        "code": "Code",
        "table": "Table",
        "data": "Data",
        "text": "Text",
    }.get(file_kind, "File")


def _workspace_file_record_type(*, record_source: str, opened_preview: bool) -> str:
    if record_source == _HOST_AGENT_WORKSPACE_SOURCE:
        return "generated_record"
    if record_source == _PORTAL_IMPORT_SOURCE:
        return "imported_file"
    return "research_record" if opened_preview else "research_file"


def _workspace_file_record_label(record_type: str) -> str:
    if record_type == "generated_record":
        return "Generated record"
    if record_type == "imported_file":
        return "Imported file"
    if record_type == "research_record":
        return "Research record"
    return "Research file"


def _public_workspace_file(
    project_id: str,
    rel_path: str,
    path: Path,
    fingerprint: WorkspaceFileFingerprint,
    artifact_candidates: list[JsonObject],
    *,
    root: str | Path | None = None,
) -> JsonObject:
    safe_path = portal_turns.prompt_safe_text(rel_path).strip()
    directory = Path(safe_path).parent.as_posix()
    if directory == ".":
        directory = ""
    content_type = mimetypes.guess_type(safe_path)[0] or "application/octet-stream"
    matched_artifact = _matching_workspace_artifact(artifact_candidates, path, fingerprint)
    record_source = _artifact_workspace_file_source(matched_artifact) if matched_artifact is not None else ""
    display = _workspace_file_display(safe_path, content_type, record_source=record_source)
    item: JsonObject = {
        "relative_path": safe_path,
        "name": Path(safe_path).name,
        "directory": directory,
        "content_type": content_type,
        "file_kind": display["file_kind"],
        "kind_label": display["kind_label"],
        "record_type": display["record_type"],
        "record_label": display["record_label"],
        "size_bytes": fingerprint.size_bytes,
        "size_label": _format_size(fingerprint.size_bytes),
        "modified_at": _iso_from_mtime_ns(fingerprint.mtime_ns),
    }
    if matched_artifact is not None:
        artifact_id = str(matched_artifact.get("id") or "").strip()
        if artifact_id:
            item["artifact_id"] = artifact_id
            item["artifact_title"] = str(matched_artifact.get("title") or safe_path)
            if matched_artifact.get("preview_url"):
                item["artifact_preview_url"] = matched_artifact["preview_url"]
            origin_context = matched_artifact.get("origin_context") if isinstance(matched_artifact.get("origin_context"), dict) else {}
            if origin_context and record_source == _HOST_AGENT_WORKSPACE_SOURCE:
                item["origin_context"] = _public_workspace_file_origin_context(
                    origin_context,
                    project_id=project_id,
                    root=root,
                )
    return item


def _artifact_matches_workspace_file(
    artifact: JsonObject,
    path: Path,
    fingerprint: WorkspaceFileFingerprint,
) -> bool:
    if _artifact_workspace_file_source(artifact) not in _LINKED_WORKSPACE_FILE_SOURCES:
        return False
    expected_size = _artifact_workspace_file_size(artifact)
    if expected_size is None or expected_size != fingerprint.size_bytes:
        return False
    expected_checksum = _artifact_workspace_file_checksum(artifact)
    if not expected_checksum:
        return False
    try:
        return _sha256_bytes(path.read_bytes()) == expected_checksum
    except OSError:
        return False


def _matching_workspace_artifact(
    artifacts: list[JsonObject],
    path: Path,
    fingerprint: WorkspaceFileFingerprint,
) -> JsonObject | None:
    for artifact in artifacts:
        if _artifact_matches_workspace_file(artifact, path, fingerprint):
            return artifact
    return None


def _artifact_workspace_file_source(artifact: JsonObject | None) -> str:
    if not isinstance(artifact, dict):
        return ""
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    return portal_turns.prompt_safe_text(str(summary.get("source") or "")).strip()


def _artifact_workspace_file_size(artifact: JsonObject) -> int | None:
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    latest_version = artifact.get("latest_version") if isinstance(artifact.get("latest_version"), dict) else {}
    summary_size = _int_or_none(summary.get("size_bytes"))
    if summary_size is not None:
        return summary_size
    return _int_or_none(latest_version.get("size_bytes"))


def _artifact_workspace_file_checksum(artifact: JsonObject) -> str:
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    latest_version = artifact.get("latest_version") if isinstance(artifact.get("latest_version"), dict) else {}
    return portal_turns.prompt_safe_text(
        str(summary.get("sha256") or latest_version.get("checksum") or "")
    ).strip()


def _int_or_none(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _public_workspace_file_origin_context(
    origin_context: JsonObject,
    *,
    project_id: str,
    root: str | Path | None = None,
) -> JsonObject:
    public: JsonObject = {}
    frame_id = portal_turns.prompt_safe_text(str(origin_context.get("frame_id") or "")).strip()
    if frame_id:
        public["frame_id"] = frame_id
        frame_title = _origin_frame_title(frame_id, project_id=project_id, root=root)
        if frame_title:
            public["frame_title"] = frame_title
    run_ids = origin_context.get("run_ids") if isinstance(origin_context.get("run_ids"), list) else []
    safe_run_ids = [
        portal_turns.prompt_safe_text(str(run_id or "")).strip()
        for run_id in run_ids
        if portal_turns.prompt_safe_text(str(run_id or "")).strip()
    ]
    if safe_run_ids:
        public["run_ids"] = safe_run_ids[:8]
    producing_run_id = portal_turns.prompt_safe_text(str(origin_context.get("producing_run_id") or "")).strip()
    if producing_run_id:
        public["producing_run_id"] = producing_run_id
    producing_message_id = portal_turns.prompt_safe_text(
        str(origin_context.get("producing_assistant_message_id") or "")
    ).strip()
    if producing_message_id:
        public["producing_assistant_message_id"] = producing_message_id
    return public


def _origin_frame_title(
    frame_id: str,
    *,
    project_id: str,
    root: str | Path | None = None,
) -> str:
    frame = portal_store.get_frame(frame_id, root=root)
    if not isinstance(frame, dict) or frame.get("project_id") != project_id:
        return ""
    public_frame = portal_store.public_frame(frame)
    return portal_turns.prompt_safe_text(
        str(public_frame.get("title") or public_frame.get("display_request") or public_frame.get("request") or "")
    ).strip()[:160]


def _workspace_artifacts_by_filename(project_id: str, root: str | Path | None = None) -> dict[str, list[JsonObject]]:
    payload = portal_store.list_project_artifacts(project_id, root=root)
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else []
    by_filename: dict[str, list[JsonObject]] = {}
    for artifact in artifacts if isinstance(artifacts, list) else []:
        if not isinstance(artifact, dict):
            continue
        summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
        if summary.get("source") not in _LINKED_WORKSPACE_FILE_SOURCES:
            continue
        filename = portal_turns.prompt_safe_text(str(summary.get("filename") or "")).strip()
        if filename:
            by_filename.setdefault(filename, []).append(artifact)
    return by_filename


def _iso_from_mtime_ns(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000, timezone.utc).isoformat().replace("+00:00", "Z")
