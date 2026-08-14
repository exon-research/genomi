from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import portal_artifact_presenters, portal_artifact_versions, portal_state

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class ArtifactBundleFileSource:
    version: JsonObject
    file_path: Path | None


@dataclass(frozen=True)
class ArtifactBundleSource:
    metadata: JsonObject
    version_files: tuple[ArtifactBundleFileSource, ...]


_ARTIFACT_METADATA_EXPORT_FIELDS = (
    "id",
    "project_id",
    "kind",
    "renderer",
    "title",
    "operation",
    "status",
    "starred",
    "hidden",
    "url",
    "preview_url",
    "open_label",
    "summary",
    "summary_lines",
    "origin_context",
    "provenance_messages",
)
_ARTIFACT_VERSION_METADATA_EXPORT_FIELDS = (
    "version_id",
    "artifact_id",
    "project_id",
    "created_at",
    "content_type",
    "filename",
    "checksum",
    "size_bytes",
    "is_intermediate",
    "file_url",
    "environment",
    "reproduction",
    "review",
)


def project_artifact_metadata_bundle(project_id: str, artifact_id: str, root: str | Path | None = None) -> JsonObject | None:
    state = portal_state.read_state(root)
    read_model = _project_artifact_versions_read_model(state, project_id, artifact_id)
    if read_model is None:
        return None
    return _metadata_bundle_from_read_model(state, project_id, artifact_id, read_model)


def project_artifact_bundle_source(project_id: str, artifact_id: str, root: str | Path | None = None) -> ArtifactBundleSource | None:
    state = portal_state.read_state(root)
    return project_artifact_bundle_source_from_state(state, project_id, artifact_id, root=root)


def project_artifact_bundle_source_from_state(
    state: JsonObject,
    project_id: str,
    artifact_id: str,
    *,
    root: str | Path | None = None,
) -> ArtifactBundleSource | None:
    read_model = _project_artifact_versions_read_model(state, project_id, artifact_id)
    if read_model is None:
        return None
    metadata = _metadata_bundle_from_read_model(state, project_id, artifact_id, read_model)
    version_files = tuple(
        ArtifactBundleFileSource(
            version=_artifact_version_metadata_export(public_version),
            file_path=portal_artifact_versions.artifact_version_file_path(raw_version, root=root),
        )
        for public_version, raw_version in zip(read_model["versions"], read_model["raw_versions"], strict=True)
    )
    return ArtifactBundleSource(metadata=metadata, version_files=version_files)


def _metadata_bundle_from_read_model(
    state: JsonObject,
    project_id: str,
    artifact_id: str,
    read_model: JsonObject,
) -> JsonObject:
    versions = [_artifact_version_metadata_export(version) for version in read_model["versions"]]
    return {
        "schema": "genomi_portal_artifact_metadata",
        "exported_at": _now(),
        "project_id": project_id,
        "artifact_id": artifact_id,
        "artifact": _artifact_metadata_export(read_model["artifact"], state),
        "versions": {
            "latest_version_id": read_model["latest_version_id"],
            "version_count": len(versions),
            "items": versions,
        },
    }


def _project_artifact_versions_read_model(state: JsonObject, project_id: str, artifact_id: str) -> JsonObject | None:
    artifact = state["artifacts"].get(artifact_id)
    if not isinstance(artifact, dict) or artifact.get("project_id") != project_id:
        return None
    raw_versions = [
        version
        for version in state["artifact_versions"].values()
        if (
            isinstance(version, dict)
            and version.get("project_id") == project_id
            and version.get("artifact_id") == artifact_id
        )
    ]
    raw_versions.sort(key=lambda version: str(version.get("created_at") or ""), reverse=True)
    return {
        "artifact": artifact,
        "latest_version_id": artifact.get("latest_version_id"),
        "raw_versions": raw_versions,
        "versions": [portal_artifact_presenters.public_artifact_version_detail(version) for version in raw_versions],
    }


def _artifact_metadata_export(artifact: JsonObject, state: JsonObject) -> JsonObject:
    public = portal_artifact_presenters.public_artifact_summary(artifact, state)
    provenance_messages = portal_artifact_presenters.artifact_provenance_messages(artifact, state)
    if provenance_messages is not None:
        public["provenance_messages"] = provenance_messages
    return _allowlisted_public_fields(public, _ARTIFACT_METADATA_EXPORT_FIELDS)


def _artifact_version_metadata_export(version: JsonObject) -> JsonObject:
    return _allowlisted_public_fields(version, _ARTIFACT_VERSION_METADATA_EXPORT_FIELDS)


def _allowlisted_public_fields(source: JsonObject, fields: tuple[str, ...]) -> JsonObject:
    return {field: source[field] for field in fields if field in source}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
