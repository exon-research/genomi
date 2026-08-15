"""Immutable on-disk artifacts for registered Active Genome Index revisions.

Builders may use a stable work path so cache lookup and force-rebuild behavior
remain simple.  A registered AGI never reads that mutable work path directly:
registration snapshots the completed SQLite state into a revision-addressed
file, and runtime readers resolve the registered revision artifact instead.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ._agi_schema import connect_existing_readonly
from .identity import read_agi_snapshot_identity


REVISION_DIRECTORY_NAME = ".active-genome-index-revisions"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ActiveGenomeIndexArtifactIntegrityError(ValueError):
    """The immutable AGI artifact no longer matches its registered digest."""


def compute_agi_artifact_sha256(agi_path: str | Path) -> str:
    """Return the SHA-256 of the exact, self-contained SQLite artifact bytes."""

    path = Path(agi_path).expanduser()
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ActiveGenomeIndexArtifactIntegrityError(
            "The registered Active Genome Index artifact cannot be read."
        ) from exc
    return digest.hexdigest()


def verify_immutable_agi_revision(
    agi_path: str | Path,
    *,
    expected_artifact_sha256: str,
    expected_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Verify exact artifact bytes before returning its embedded identity.

    The snapshot metadata identifies a build, but it does not cover every
    SQLite row or page.  A registry-pinned digest therefore remains the final
    read boundary: row edits, page replacement, truncation, and corruption all
    fail closed even when the metadata table was left untouched.
    """

    expected_digest = str(expected_artifact_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(expected_digest):
        raise ActiveGenomeIndexArtifactIntegrityError(
            "The registered Active Genome Index revision has no valid artifact digest."
        )
    actual_digest = compute_agi_artifact_sha256(agi_path)
    if not hmac.compare_digest(actual_digest, expected_digest):
        raise ActiveGenomeIndexArtifactIntegrityError(
            "The registered Active Genome Index artifact failed its integrity check."
        )
    try:
        identity = read_agi_snapshot_identity(agi_path)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise ActiveGenomeIndexArtifactIntegrityError(
            "The registered Active Genome Index artifact is unreadable."
        ) from exc
    snapshot_id = str(expected_snapshot_id or "").strip()
    if snapshot_id and str(identity.get("agi_snapshot_id") or "") != snapshot_id:
        raise ActiveGenomeIndexArtifactIntegrityError(
            "The registered Active Genome Index artifact contains a different snapshot."
        )
    return {**identity, "agi_artifact_sha256": actual_digest}


def require_mutable_agi_build_path(agi_path: str | Path) -> Path:
    """Reject attempts to build into or append to immutable revision storage."""

    path = Path(agi_path).expanduser()
    if REVISION_DIRECTORY_NAME in path.resolve(strict=False).parts:
        raise ValueError(
            "Immutable Active Genome Index revisions are read-only; use the AGI build path for a rebuild"
        )
    return path


def materialize_immutable_agi_revision(agi_build_path: str | Path) -> dict[str, Any]:
    """Create or validate the immutable artifact for one built AGI revision.

    SQLite's backup API gives us a transactionally consistent single-file
    snapshot even when the work database uses WAL.  Publication is atomic and
    the resulting file is read-only.  Re-registering the same revision is
    idempotent and never rewrites the published artifact.
    """

    source_path = Path(agi_build_path).expanduser().resolve(strict=True)
    identity = read_agi_snapshot_identity(source_path)
    snapshot_id = str(identity.get("agi_snapshot_id") or "")
    if not snapshot_id:
        raise ValueError(
            f"Active Genome Index at {source_path} has no valid snapshot identity"
        )

    if _is_revision_artifact(source_path, snapshot_id=snapshot_id):
        return {
            **identity,
            "agi_artifact_sha256": compute_agi_artifact_sha256(source_path),
            "agi_revision_path": str(source_path),
        }

    revision_path = immutable_agi_revision_path(source_path, snapshot_id)
    revision_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _private_directory_permissions(revision_path.parent):
        if revision_path.exists():
            _assert_revision_identity(revision_path, snapshot_id=snapshot_id)
            _make_read_only(revision_path)
            return {
                **identity,
                "agi_artifact_sha256": compute_agi_artifact_sha256(revision_path),
                "agi_revision_path": str(revision_path),
            }

        temporary_path = revision_path.with_name(
            f".{revision_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with connect_existing_readonly(source_path) as source_connection:
                destination = sqlite3.connect(temporary_path)
                try:
                    source_connection.backup(destination)
                    destination.commit()
                finally:
                    destination.close()
            _assert_revision_identity(temporary_path, snapshot_id=snapshot_id)
            os.chmod(temporary_path, 0o400)
            try:
                os.link(temporary_path, revision_path)
            except FileExistsError:
                _assert_revision_identity(revision_path, snapshot_id=snapshot_id)
            else:
                _fsync_directory(revision_path.parent)
        finally:
            temporary_path.unlink(missing_ok=True)

    _assert_revision_identity(revision_path, snapshot_id=snapshot_id)
    _make_read_only(revision_path)
    return {
        **identity,
        "agi_artifact_sha256": compute_agi_artifact_sha256(revision_path),
        "agi_revision_path": str(revision_path),
    }


def immutable_agi_revision_path(
    agi_build_path: str | Path,
    agi_snapshot_id: str,
) -> Path:
    """Return the content-addressed storage path for a registered revision."""

    build_path = Path(agi_build_path).expanduser().resolve(strict=False)
    snapshot_id = str(agi_snapshot_id or "").strip()
    if not snapshot_id or "/" in snapshot_id or "\\" in snapshot_id:
        raise ValueError("agi_snapshot_id must be a non-empty path-safe value")
    return (
        build_path.parent
        / REVISION_DIRECTORY_NAME
        / build_path.name
        / f"{snapshot_id}.sqlite"
    )


def _is_revision_artifact(path: Path, *, snapshot_id: str) -> bool:
    return (
        path.name == f"{snapshot_id}.sqlite"
        and path.parent.parent.name == REVISION_DIRECTORY_NAME
    )


def _assert_revision_identity(path: Path, *, snapshot_id: str) -> None:
    try:
        identity = read_agi_snapshot_identity(path)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise ValueError(
            f"Immutable Active Genome Index revision is unreadable: {path}"
        ) from exc
    if str(identity.get("agi_snapshot_id") or "") != snapshot_id:
        raise ValueError(
            "Immutable Active Genome Index revision path contains a different snapshot"
        )


class _private_directory_permissions:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> None:
        os.chmod(self.path, 0o700)

    def __exit__(self, *_: object) -> None:
        return None


def _make_read_only(path: Path) -> None:
    os.chmod(path, 0o400)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "ActiveGenomeIndexArtifactIntegrityError",
    "REVISION_DIRECTORY_NAME",
    "compute_agi_artifact_sha256",
    "immutable_agi_revision_path",
    "materialize_immutable_agi_revision",
    "require_mutable_agi_build_path",
    "verify_immutable_agi_revision",
]
