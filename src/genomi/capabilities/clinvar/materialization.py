"""Per-Active Genome Index materialization registry.

Tracks which libraries have been materialized for a given active-genome-index
record. Each manifest answers: "for this agi_id + library_id + library_version +
inputs_hash, are the artifacts complete?"

Used by evidence tools so they can decide between:
  - serve from a complete manifest (cheap),
  - resume a queued/running job (return materialization_pending envelope),
  - kick off materialization (return materialization_pending),
  - report missing library (return blocked_missing_library envelope).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ...runtime.external import utc_now
from ...runtime.paths import genomi_data_root

MANIFEST_SCHEMA = "genomi-library-materialization-manifest-v1"
MATERIALIZATION_DIR_NAME = "materialization"

# Status values
QUEUED = "queued"
RUNNING = "running"
COMPLETE = "complete"
FAILED = "failed"
STALE = "stale"

ACTIVE_STATUSES = {QUEUED, RUNNING}
TERMINAL_STATUSES = {COMPLETE, FAILED, STALE}


# --- library descriptors ----------------------------------------------------

# Per-library materialization descriptors. Each entry says: what version
# token belongs to this library, and what artifact paths (relative to the
# materialization dir) prove completion.
#
# This is intentionally a small static table — adding a new evidence library
# means adding a row here and a build function in the evidence module that
# owns it.

_LIBRARY_DESCRIPTORS: dict[str, dict[str, Any]] = {
    "clinvar-grch38": {
        "title": "ClinVar exact-match materialization (GRCh38)",
        "default_version": "v1",
        "artifact_globs": ["clinvar-matches.sqlite", "clinvar-matches.manifest.json"],
    },
    "clinvar-grch37": {
        "title": "ClinVar exact-match materialization (GRCh37)",
        "default_version": "v1",
        "artifact_globs": ["clinvar-matches.sqlite", "clinvar-matches.manifest.json"],
    },
    "genotype-support": {
        "title": "Genotype support / reference-backed coverage",
        "default_version": "v1",
        "artifact_globs": ["genotype-support.sqlite", "callability.json"],
    },
    "hpo-public": {
        "title": "HPO public lookup materialization",
        "default_version": "v1",
        "artifact_globs": ["hpo-lookup.sqlite"],
    },
    "gencc-public": {
        "title": "GenCC public lookup materialization",
        "default_version": "v1",
        "artifact_globs": ["gencc-lookup.sqlite"],
    },
    "region-annotation": {
        "title": "Region annotation materialization",
        "default_version": "v1",
        "artifact_globs": ["region-annotation.sqlite"],
    },
    "panel-scan": {
        "title": "Panel scan materialization",
        "default_version": "v1",
        "artifact_globs": ["panel-scan.json"],
    },
    "pgx-artifacts": {
        "title": "Pharmacogenomic artifact materialization",
        "default_version": "v1",
        "artifact_globs": ["pgx-artifacts.json"],
    },
}


def known_library_ids() -> list[str]:
    return sorted(_LIBRARY_DESCRIPTORS)


def library_descriptor(library_id: str) -> dict[str, Any] | None:
    return _LIBRARY_DESCRIPTORS.get(library_id)


# --- manifest paths --------------------------------------------------------

def materialization_root(*, root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / MATERIALIZATION_DIR_NAME


def agi_materialization_dir(agi_id: str, *, root: str | Path | None = None) -> Path:
    safe = _safe_segment(agi_id) or "default"
    return materialization_root(root=root) / safe


def manifest_path(
    *,
    agi_id: str,
    library_id: str,
    inputs_hash: str,
    root: str | Path | None = None,
) -> Path:
    return agi_materialization_dir(agi_id, root=root) / library_id / f"{inputs_hash}.json"


# --- hashing ---------------------------------------------------------------

def inputs_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


# --- manifest API ----------------------------------------------------------

def read_manifest(path: str | Path) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    return value


def write_manifest(path: str | Path, manifest: dict[str, Any]) -> None:
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload = {**manifest, "updated_at": utc_now()}
    tmp = resolved.with_suffix(resolved.suffix + f".tmp-{os.getpid()}-{uuid.uuid4().hex}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(resolved)


def init_manifest(
    *,
    agi_id: str,
    library_id: str,
    library_version: str | None = None,
    inputs: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
    job_id: str | None = None,
    artifact_paths: Iterable[str] | None = None,
    status: str = QUEUED,
    root: str | Path | None = None,
) -> dict[str, Any]:
    desc = library_descriptor(library_id) or {}
    version = library_version or desc.get("default_version") or "v1"
    inputs_payload = {
        "agi_id": agi_id,
        "library_id": library_id,
        "library_version": version,
        "inputs": inputs or {},
        "parameters": parameters or {},
    }
    digest = inputs_hash(inputs_payload)
    target = manifest_path(agi_id=agi_id, library_id=library_id, inputs_hash=digest, root=root)
    now = utc_now()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "agi_id": agi_id,
        "library_id": library_id,
        "library_version": version,
        "library_title": desc.get("title"),
        "inputs_hash": digest,
        "inputs": inputs or {},
        "parameters": parameters or {},
        "status": status,
        "job_id": job_id,
        "started_at": now if status != QUEUED else None,
        "completed_at": None,
        "failed_at": None,
        "error": None,
        "artifact_paths": list(artifact_paths or []),
        "manifest_path": str(target),
        "created_at": now,
        "updated_at": now,
    }
    write_manifest(target, manifest)
    return manifest


def update_manifest(manifest: dict[str, Any], **updates: Any) -> dict[str, Any]:
    target = manifest.get("manifest_path")
    if not target:
        raise ValueError("manifest is missing manifest_path")
    merged = {**manifest, **updates, "updated_at": utc_now()}
    write_manifest(target, merged)
    return merged


def mark_running(manifest: dict[str, Any], *, job_id: str | None = None) -> dict[str, Any]:
    updates: dict[str, Any] = {"status": RUNNING, "started_at": manifest.get("started_at") or utc_now()}
    if job_id is not None:
        updates["job_id"] = job_id
    return update_manifest(manifest, **updates)


def mark_complete(manifest: dict[str, Any], *, artifact_paths: Iterable[str] | None = None) -> dict[str, Any]:
    updates: dict[str, Any] = {"status": COMPLETE, "completed_at": utc_now()}
    if artifact_paths is not None:
        updates["artifact_paths"] = list(artifact_paths)
    return update_manifest(manifest, **updates)


def mark_failed(manifest: dict[str, Any], error: dict[str, Any] | str) -> dict[str, Any]:
    err = error if isinstance(error, dict) else {"message": str(error)}
    return update_manifest(manifest, status=FAILED, failed_at=utc_now(), error=err)


def mark_stale(manifest: dict[str, Any], *, reason: str | None = None) -> dict[str, Any]:
    return update_manifest(manifest, status=STALE, error={"stale_reason": reason} if reason else None)


def lookup_latest(
    *,
    agi_id: str,
    library_id: str,
    root: str | Path | None = None,
) -> dict[str, Any] | None:
    folder = agi_materialization_dir(agi_id, root=root) / library_id
    if not folder.exists():
        return None
    candidates: list[dict[str, Any]] = []
    for path in folder.glob("*.json"):
        manifest = read_manifest(path)
        if manifest is None:
            continue
        candidates.append(manifest)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[0]


def lookup_or_init(
    *,
    agi_id: str,
    library_id: str,
    inputs: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
    library_version: str | None = None,
    root: str | Path | None = None,
) -> tuple[dict[str, Any], bool]:
    """Return (manifest, created_now).

    Looks up by inputs_hash. If present and complete or active, reuse. If
    failed or stale, the caller can decide whether to re-init.
    """

    desc = library_descriptor(library_id) or {}
    version = library_version or desc.get("default_version") or "v1"
    digest = inputs_hash(
        {
            "agi_id": agi_id,
            "library_id": library_id,
            "library_version": version,
            "inputs": inputs or {},
            "parameters": parameters or {},
        }
    )
    target = manifest_path(agi_id=agi_id, library_id=library_id, inputs_hash=digest, root=root)
    existing = read_manifest(target)
    if existing is not None:
        # detect artifact drift; if marked complete but artifacts are gone,
        # rebuild — flip to stale and let the caller resume.
        if existing.get("status") == COMPLETE:
            present = [Path(p) for p in existing.get("artifact_paths") or []]
            if present and not all(p.exists() for p in present):
                return mark_stale(existing, reason="artifacts_missing"), False
        return existing, False
    manifest = init_manifest(
        agi_id=agi_id,
        library_id=library_id,
        library_version=version,
        inputs=inputs,
        parameters=parameters,
        root=root,
    )
    return manifest, True


# --- library-use snapshots for envelopes -----------------------------------

def library_use_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    status = manifest.get("status") or QUEUED
    state = {
        QUEUED: "materializing",
        RUNNING: "materializing",
        COMPLETE: "complete",
        FAILED: "failed",
        STALE: "stale",
    }.get(status, "not_materialized")
    return {
        "library": manifest.get("library_id"),
        "state": state,
        "title": manifest.get("library_title"),
        "materialization_id": manifest.get("inputs_hash"),
        "materialization_progress": {
            "status": status,
            "started_at": manifest.get("started_at"),
            "completed_at": manifest.get("completed_at"),
            "agi_id": manifest.get("agi_id"),
            "library_version": manifest.get("library_version"),
            "job_id": manifest.get("job_id"),
        },
    }


# --- internal --------------------------------------------------------------

def _safe_segment(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(value))[:80]
