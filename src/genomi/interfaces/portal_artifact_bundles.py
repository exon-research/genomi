from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import portal_artifact_exports, portal_artifact_reproduction, portal_bundle_files, portal_state

JsonObject = dict[str, Any]
ArtifactBundle = portal_bundle_files.DownloadBundle


def project_artifact_bundle(
    project_id: str,
    artifact_id: str,
    root: str | Path | None = None,
) -> ArtifactBundle | None:
    source = portal_artifact_exports.project_artifact_bundle_source(project_id, artifact_id, root=root)
    if source is None:
        return None
    files, blobs = portal_bundle_files.artifact_version_bundle_files(
        source.version_files,
        archive_prefix="versions",
        token_fallback="artifact",
        use_archive_filename_in_metadata=False,
    )
    manifest = {
        "schema": "genomi_portal_artifact_bundle",
        "exported_at": source.metadata.get("exported_at"),
        "project_id": project_id,
        "artifact_id": artifact_id,
        "metadata_entry": "metadata.json",
        "files": files,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        portal_bundle_files.write_json(archive, "manifest.json", manifest)
        portal_bundle_files.write_json(archive, "metadata.json", source.metadata)
        for archive_entry, file_path in blobs:
            archive.write(file_path, archive_entry)
    return ArtifactBundle(
        body=buffer.getvalue(),
        filename=f"{portal_bundle_files.download_safe_token(artifact_id, fallback='artifact')}-bundle.zip",
    )


def project_artifact_script_bundle(
    project_id: str,
    artifact_id: str,
    version_id: str | None = None,
    root: str | Path | None = None,
) -> ArtifactBundle | None:
    source = _script_bundle_source(project_id, artifact_id, version_id, root=root)
    if source is None:
        return None
    artifact = source["artifact"]
    version = source["version"]
    recipe = source["recipe"]
    script = str(recipe.get("script") or "").strip()
    if not script:
        return None
    version_token = portal_bundle_files.download_safe_token(str(version.get("version_id") or ""), fallback="version")
    artifact_token = portal_bundle_files.download_safe_token(str(artifact.get("id") or artifact_id), fallback="artifact")
    manifest = {
        "schema": "genomi_portal_artifact_script_bundle",
        "exported_at": _now(),
        "project_id": project_id,
        "artifact_id": artifact.get("id"),
        "version_id": version.get("version_id"),
        "script_entry": "rebuild.sh",
        "recipe_entry": "rebuild-recipe.json",
        "readme_entry": "README.md",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        portal_bundle_files.write_json(archive, "manifest.json", manifest)
        portal_bundle_files.write_json(archive, "rebuild-recipe.json", recipe)
        archive.writestr("rebuild.sh", _shell_script(script).encode("utf-8"))
        archive.writestr("README.md", _script_bundle_readme(artifact, version, recipe).encode("utf-8"))
    return ArtifactBundle(
        body=buffer.getvalue(),
        filename=f"{artifact_token}-{version_token}-rebuild.zip",
    )


def _script_bundle_source(
    project_id: str,
    artifact_id: str,
    version_id: str | None,
    *,
    root: str | Path | None,
) -> JsonObject | None:
    state = portal_state.read_state(root)
    artifact = state["artifacts"].get(artifact_id)
    if not isinstance(artifact, dict) or artifact.get("project_id") != project_id:
        return None
    selected_version_id = str(version_id or artifact.get("latest_version_id") or "").strip()
    if not selected_version_id:
        return None
    version = state["artifact_versions"].get(selected_version_id)
    if not isinstance(version, dict):
        return None
    if version.get("project_id") != project_id or version.get("artifact_id") != artifact_id:
        return None
    recipe = portal_artifact_reproduction.public_reproduction(version.get("reproduction"))
    if not recipe or recipe.get("status") != portal_artifact_reproduction.READY_STATUS:
        return None
    return {"artifact": artifact, "version": version, "recipe": recipe}


def _shell_script(script: str) -> str:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    lines.extend(script.rstrip().splitlines())
    return "\n".join(lines) + "\n"


def _script_bundle_readme(artifact: JsonObject, version: JsonObject, recipe: JsonObject) -> str:
    title = str(artifact.get("title") or "Genomi artifact").strip()
    limitations = recipe.get("limitations") if isinstance(recipe.get("limitations"), list) else []
    lines = [
        f"# Rebuild script for {title}",
        "",
        "This bundle contains a public Genomi rebuild recipe for one artifact version.",
        "It recreates the Genomi operation result used by the portal renderer; it does not replay the assistant conversation.",
        "",
        f"- Artifact: {artifact.get('id')}",
        f"- Version: {version.get('version_id')}",
        f"- Operation: {recipe.get('operation')}",
        "",
        "## Files",
        "",
        "- `rebuild.sh`: shell script for the public Genomi operation.",
        "- `rebuild-recipe.json`: structured recipe metadata and parameters.",
        "- `manifest.json`: bundle manifest.",
    ]
    clean_limitations = [str(item).strip() for item in limitations if str(item).strip()]
    if clean_limitations:
        lines.extend(["", "## Limits", ""])
        lines.extend("- " + item for item in clean_limitations)
    return "\n".join(lines) + "\n"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
