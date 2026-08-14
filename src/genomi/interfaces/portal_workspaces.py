from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..runtime.paths import genomi_data_root

_SAFE_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def project_workspace_metadata(project_id: str) -> dict[str, str]:
    workspace_id = project_workspace_id(project_id)
    return {
        "scope": "project",
        "owner": "genomi_webui",
        "storage": "genomi_home_workspace",
        "workspace_id": workspace_id,
        "path_hint": f"$GENOMI_HOME/workspace/{workspace_id}",
        "status": "ready",
    }


def agent_workspace_metadata() -> dict[str, str]:
    return {
        "scope": "agent",
        "owner": "host_agent",
        "storage": "host_agent_current_working_directory",
        "workspace_id": "host_agent",
        "status": "controlled_by_host_agent",
    }


def run_workspace_metadata(project_id: str | None) -> dict[str, str]:
    clean_project_id = str(project_id or "").strip()
    if clean_project_id:
        return project_workspace_metadata(clean_project_id)
    return agent_workspace_metadata()


def project_workspaces_root(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / "workspace"


def project_workspace_dir(project_id: str, root: str | Path | None = None) -> Path:
    return project_workspaces_root(root) / project_workspace_id(project_id)


def ensure_project_workspace(project_id: str, root: str | Path | None = None) -> Path:
    workspace = project_workspace_dir(project_id, root)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def project_workspace_prompt_section(project_id: str | None) -> str:
    clean_project_id = str(project_id or "").strip()
    if not clean_project_id:
        return ""
    metadata = project_workspace_metadata(clean_project_id)
    return (
        "# Project workspace\n"
        "- This run was opened from Genomi Web UI.\n"
        f"- Current working directory: {metadata['path_hint']}.\n"
        "- Genomi owns this project workspace for the visible browser project.\n"
        "- Files you create or update in this directory can appear as project files, generated records, and reproducible artifacts in the web UI.\n\n"
    )


def project_workspace_id(project_id: str) -> str:
    clean = str(project_id or "").strip()
    if not clean:
        raise ValueError("project_id is required")
    if _SAFE_WORKSPACE_ID.fullmatch(clean):
        return clean
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]
    return f"project-{digest}"
