from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from . import portal_bundle_files, portal_frame_exports

JsonObject = dict[str, Any]
FrameBundle = portal_bundle_files.DownloadBundle


def project_frame_bundle(
    project_id: str,
    frame_id: str,
    root: str | Path | None = None,
) -> FrameBundle | None:
    source = portal_frame_exports.project_frame_bundle_source(project_id, frame_id, root=root)
    if source is None:
        return None
    manifest, artifact_blobs = _manifest_and_blobs(source, project_id, frame_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        portal_bundle_files.write_json(archive, "manifest.json", manifest)
        portal_bundle_files.write_json(archive, "frame.json", source.metadata)
        portal_bundle_files.write_json(archive, "messages.json", source.messages)
        for artifact_source in source.artifacts:
            portal_bundle_files.write_json(
                archive,
                artifact_source.metadata_entry,
                artifact_source.bundle_source.metadata,
            )
        for archive_entry, file_path in artifact_blobs:
            archive.write(file_path, archive_entry)
    return FrameBundle(
        body=buffer.getvalue(),
        filename=f"{portal_bundle_files.download_safe_token(frame_id, fallback='frame')}-bundle.zip",
    )


def _manifest_and_blobs(
    source: portal_frame_exports.FrameBundleSource,
    project_id: str,
    frame_id: str,
) -> tuple[JsonObject, list[tuple[str, Path]]]:
    artifact_entries: list[JsonObject] = []
    blobs: list[tuple[str, Path]] = []
    for artifact_source in source.artifacts:
        artifact_files, artifact_blobs = _artifact_file_entries(artifact_source)
        artifact_entries.append(
            {
                "artifact_id": artifact_source.artifact_id,
                "metadata_entry": artifact_source.metadata_entry,
                "files": artifact_files,
            }
        )
        blobs.extend(artifact_blobs)
    return (
        {
            "schema": "genomi_portal_frame_bundle",
            "exported_at": source.metadata.get("exported_at"),
            "project_id": project_id,
            "frame_id": frame_id,
            "frame_entry": "frame.json",
            "messages_entry": "messages.json",
            "artifacts": artifact_entries,
        },
        blobs,
    )


def _artifact_file_entries(
    artifact_source: portal_frame_exports.FrameBundleArtifactSource,
) -> tuple[list[JsonObject], list[tuple[str, Path]]]:
    artifact_token = portal_bundle_files.download_safe_token(artifact_source.artifact_id, fallback="frame")
    return portal_bundle_files.artifact_version_bundle_files(
        artifact_source.bundle_source.version_files,
        archive_prefix=f"artifacts/{artifact_token}/versions",
        token_fallback="frame",
        use_archive_filename_in_metadata=True,
    )
