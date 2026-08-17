"""Immutable identity for one built Active Genome Index revision.

An ``agi_id`` identifies the logical genome/index across rebuilds.  An
``agi_snapshot_id`` identifies one exact build revision.  The latter is minted
once from immutable build inputs written into the AGI metadata and can therefore
be reproduced after a restart without making two explicit rebuilds of the same
source look like the same revision.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from ..runtime.external import utc_now
from ..runtime.paths import vcf_content_hash


AGI_SNAPSHOT_ID_PREFIX = "agi-snapshot-sha256"
AGI_SNAPSHOT_METADATA_FIELDS = (
    "agi_snapshot_id",
    "agi_build_revision",
    "agi_snapshot_created_at",
    "source_content_sha256",
    "genome_build",
    "schema_version",
)


def source_content_sha256(source_path: str | Path) -> str:
    """Return a content digest for a file or an unpacked ``.genome`` bundle."""

    path = Path(source_path)
    if path.is_file():
        digest = vcf_content_hash(path)
        if digest:
            return digest
        raise OSError(f"could not hash Active Genome Index source: {path}")
    if path.is_dir():
        return _directory_content_sha256(path)
    raise FileNotFoundError(path)


def mint_agi_snapshot_identity(
    *,
    source_content_sha256: str,
    genome_build: str,
    schema_version: int,
    build_revision: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Mint and return the persisted inputs and ID for one AGI build revision."""

    revision = build_revision or uuid.uuid4().hex
    snapshot_created_at = created_at or utc_now()
    identity = {
        "agi_build_revision": revision,
        "agi_snapshot_created_at": snapshot_created_at,
        "source_content_sha256": str(source_content_sha256),
        "genome_build": str(genome_build or "auto"),
        "schema_version": int(schema_version),
    }
    return {
        "agi_snapshot_id": derive_agi_snapshot_id(**identity),
        **identity,
    }


def derive_agi_snapshot_id(
    *,
    agi_build_revision: str,
    agi_snapshot_created_at: str,
    source_content_sha256: str,
    genome_build: str,
    schema_version: int,
) -> str:
    """Derive the stable public ID from the exact persisted revision inputs."""

    payload = {
        "agi_build_revision": str(agi_build_revision),
        "agi_snapshot_created_at": str(agi_snapshot_created_at),
        "genome_build": str(genome_build or "auto"),
        "schema_version": int(schema_version),
        "source_content_sha256": str(source_content_sha256),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{AGI_SNAPSHOT_ID_PREFIX}-{hashlib.sha256(encoded).hexdigest()}"


def agi_snapshot_identity_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Select a complete AGI snapshot identity from decoded SQLite metadata."""

    if any(metadata.get(field) in (None, "") for field in AGI_SNAPSHOT_METADATA_FIELDS):
        return {}
    identity = {field: metadata[field] for field in AGI_SNAPSHOT_METADATA_FIELDS}
    expected = derive_agi_snapshot_id(
        agi_build_revision=str(identity["agi_build_revision"]),
        agi_snapshot_created_at=str(identity["agi_snapshot_created_at"]),
        source_content_sha256=str(identity["source_content_sha256"]),
        genome_build=str(identity["genome_build"]),
        schema_version=int(identity["schema_version"]),
    )
    if identity["agi_snapshot_id"] != expected:
        return {}
    return identity


def read_agi_snapshot_identity(agi_path: str | Path) -> dict[str, Any]:
    """Read the immutable revision identity from a built AGI metadata table."""

    from ._agi_schema import connect_existing_readonly

    with connect_existing_readonly(agi_path) as connection:
        metadata = {
            str(row["key"]): json.loads(row["value"])
            for row in connection.execute(
                "select key, value from metadata where key in (?, ?, ?, ?, ?, ?)",
                AGI_SNAPSHOT_METADATA_FIELDS,
            )
        }
    return agi_snapshot_identity_from_metadata(metadata)


def _directory_content_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"genomi-source-directory-v1\0")
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "AGI_SNAPSHOT_ID_PREFIX",
    "AGI_SNAPSHOT_METADATA_FIELDS",
    "agi_snapshot_identity_from_metadata",
    "derive_agi_snapshot_id",
    "mint_agi_snapshot_identity",
    "read_agi_snapshot_identity",
    "source_content_sha256",
]
