from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import (
    portal_artifact_exports,
    portal_artifact_origins,
    portal_artifact_presenters,
    portal_state,
    portal_store,
)

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class FrameBundleArtifactSource:
    artifact_id: str
    metadata_entry: str
    bundle_source: portal_artifact_exports.ArtifactBundleSource


@dataclass(frozen=True)
class FrameBundleSource:
    metadata: JsonObject
    messages: JsonObject
    artifacts: tuple[FrameBundleArtifactSource, ...]


def project_frame_bundle_source(project_id: str, frame_id: str, root: str | Path | None = None) -> FrameBundleSource | None:
    state = portal_state.read_state(root)
    frame = state["frames"].get(frame_id)
    if not isinstance(frame, dict) or frame.get("project_id") != project_id:
        return None
    messages = _frame_messages_payload(state, project_id, frame_id)
    artifacts = _frame_artifact_sources(state, project_id, frame_id, root=root)
    metadata = {
        "schema": "genomi_portal_frame_metadata",
        "exported_at": _now(),
        "project_id": project_id,
        "frame_id": frame_id,
        "frame": portal_store.public_frame(frame),
        "messages": {
            "entry": "messages.json",
            "total": messages["total"],
        },
        "artifacts": {
            "count": len(artifacts),
            "items": [_frame_artifact_metadata_entry(source) for source in artifacts],
        },
    }
    return FrameBundleSource(metadata=metadata, messages=messages, artifacts=artifacts)


def _frame_messages_payload(state: JsonObject, project_id: str, frame_id: str) -> JsonObject:
    raw_messages = state["messages"].get(frame_id, [])
    messages = raw_messages if isinstance(raw_messages, list) else []
    return {
        "schema": "genomi_portal_frame_messages",
        "project_id": project_id,
        "frame_id": frame_id,
        "total": len(messages),
        "items": [portal_artifact_presenters.public_message(message, frame_id=frame_id) for message in messages],
    }


def _frame_artifact_sources(
    state: JsonObject,
    project_id: str,
    frame_id: str,
    *,
    root: str | Path | None,
) -> tuple[FrameBundleArtifactSource, ...]:
    sources: list[tuple[str, FrameBundleArtifactSource]] = []
    for artifact in state["artifacts"].values():
        if not isinstance(artifact, dict) or artifact.get("project_id") != project_id:
            continue
        origin = portal_artifact_origins.origin_from_artifact(artifact, state)
        if not isinstance(origin, dict) or origin.get("frame_id") != frame_id:
            continue
        artifact_id = str(artifact.get("id") or "").strip()
        if not artifact_id:
            continue
        bundle_source = portal_artifact_exports.project_artifact_bundle_source_from_state(
            state,
            project_id,
            artifact_id,
            root=root,
        )
        if bundle_source is None:
            continue
        updated_at = str(artifact.get("updated_at") or "")
        sources.append(
            (
                updated_at,
                FrameBundleArtifactSource(
                    artifact_id=artifact_id,
                    metadata_entry=f"artifacts/{_download_safe_token(artifact_id)}/metadata.json",
                    bundle_source=bundle_source,
                ),
            )
        )
    return tuple(source for _updated_at, source in sorted(sources, key=lambda item: item[0], reverse=True))


def _frame_artifact_metadata_entry(source: FrameBundleArtifactSource) -> JsonObject:
    artifact = source.bundle_source.metadata.get("artifact") if isinstance(source.bundle_source.metadata, dict) else {}
    versions = source.bundle_source.metadata.get("versions") if isinstance(source.bundle_source.metadata, dict) else {}
    return {
        "artifact_id": source.artifact_id,
        "metadata_entry": source.metadata_entry,
        "title": artifact.get("title") if isinstance(artifact, dict) else None,
        "kind": artifact.get("kind") if isinstance(artifact, dict) else None,
        "renderer": artifact.get("renderer") if isinstance(artifact, dict) else None,
        "operation": artifact.get("operation") if isinstance(artifact, dict) else None,
        "latest_version_id": versions.get("latest_version_id") if isinstance(versions, dict) else None,
        "version_count": versions.get("version_count") if isinstance(versions, dict) else None,
    }


def _download_safe_token(value: str) -> str:
    clean = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value).strip("-_")
    return clean[:80] or "item"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
