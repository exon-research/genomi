from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from ..runtime import portal_routes
from . import (
    portal_artifact_origins,
    portal_artifact_presenters,
    portal_artifact_review,
    portal_artifact_versions,
    portal_artifact_work_steps,
    portal_conversation_reviews,
    portal_project_events,
    portal_run_failures,
    portal_state,
    portal_turns,
    portal_workspaces,
)

JsonObject = dict[str, Any]
ArtifactOriginError = portal_artifact_origins.ArtifactOriginError
VersionCreator = Callable[[str, str, str, str, JsonObject, JsonObject, JsonObject], JsonObject | None]


_MESSAGE_PROJECT_REFRESH_REASONS = {"appended", "created", "message_started", "completed"}
STALE_AFTER_RESTART_STATUS = "stale_after_restart"
STALE_AFTER_RESTART_ERROR = "Portal run was interrupted by a server restart before it could finish."
_PROCESSING_FRAME_STATUS = "processing"
_ACTIVE_MESSAGE_STREAM_STATUSES = {"running", "streaming"}
_TERMINAL_TOOL_EVENT_TYPES = {"error", "tool_result"}
DEFAULT_PROJECT_NAME = "GenomiLab Workspace"
MAX_PROJECT_NAME_LENGTH = 80
MAX_CONVERSATION_TITLE_LENGTH = 96
_PROJECT_GENOME_BINDING_KEY = "genome_binding"
_PRIVATE_PROJECT_KEYS = {
    _PROJECT_GENOME_BINDING_KEY,
    "assistant_permissions",
    "genomilab_binding",
}


def artifacts_dir(project_id: str, root: str | Path | None = None) -> Path:
    return portal_artifact_versions.artifacts_dir(project_id, root)


def list_projects(root: str | Path | None = None) -> list[JsonObject]:
    state = portal_state.read_state(root)
    projects = [_project_with_current_workspace_metadata(project) for project in state["projects"].values()]
    return sorted(projects, key=lambda project: str(project.get("updated_at") or ""), reverse=True)


def ensure_default_project(root: str | Path | None = None) -> JsonObject:
    def mutate(state: JsonObject) -> JsonObject:
        active_id = state.get("active_project_id")
        if isinstance(active_id, str) and active_id in state["projects"]:
            return state["projects"][active_id]
        project = _new_project(name=DEFAULT_PROJECT_NAME)
        state["projects"][project["project_id"]] = project
        state["active_project_id"] = project["project_id"]
        return project

    project = portal_state.mutate_state(mutate, root)
    _ensure_project_workspace(project, root=root)
    return _project_with_current_workspace_metadata(project)


def create_project(
    *,
    name: str = DEFAULT_PROJECT_NAME,
    root: str | Path | None = None,
) -> JsonObject:
    def mutate(state: JsonObject) -> JsonObject:
        project = _new_project(name=_clean_project_name(name))
        state["projects"][project["project_id"]] = project
        state["active_project_id"] = project["project_id"]
        return project

    project = portal_state.mutate_state(mutate, root)
    _ensure_project_workspace(project, root=root)
    return _project_with_current_workspace_metadata(project)


def select_project(project_id: str, root: str | Path | None = None) -> JsonObject | None:
    clean_project_id = str(project_id or "").strip()

    def mutate(state: JsonObject) -> JsonObject | None:
        project = state["projects"].get(clean_project_id)
        if not isinstance(project, dict):
            return None
        state["active_project_id"] = clean_project_id
        project["updated_at"] = _now()
        return project

    project = portal_state.mutate_state(mutate, root)
    if not isinstance(project, dict):
        return None
    _ensure_project_workspace(project, root=root)
    return _project_with_current_workspace_metadata(project)


def rename_project(project_id: str, name: str, root: str | Path | None = None) -> JsonObject | None:
    clean_project_id = str(project_id or "").strip()
    clean_name = _clean_project_name(name)

    def mutate(state: JsonObject) -> JsonObject | None:
        project = state["projects"].get(clean_project_id)
        if not isinstance(project, dict):
            return None
        project["name"] = clean_name
        project["updated_at"] = _now()
        return project

    project = portal_state.mutate_state(mutate, root)
    if not isinstance(project, dict):
        return None
    _ensure_project_workspace(project, root=root)
    return _project_with_current_workspace_metadata(project)


def get_project(project_id: str, root: str | Path | None = None) -> JsonObject | None:
    project = portal_state.read_state(root)["projects"].get(project_id)
    return _project_with_current_workspace_metadata(project) if isinstance(project, dict) else None


def project_genome_binding(project_id: str, root: str | Path | None = None) -> JsonObject | None:
    project = portal_state.read_state(root)["projects"].get(str(project_id or "").strip())
    binding = project.get(_PROJECT_GENOME_BINDING_KEY) if isinstance(project, dict) else None
    if not isinstance(binding, dict) or not str(binding.get("agi_id") or "").strip():
        return None
    return dict(binding)


def bind_project_genome(
    project_id: str,
    *,
    agi_id: str,
    user_id: str | None = None,
    root: str | Path | None = None,
) -> JsonObject | None:
    clean_project_id = str(project_id or "").strip()
    clean_agi_id = str(agi_id or "").strip()
    clean_user_id = str(user_id or "").strip()
    if not clean_project_id or not clean_agi_id:
        return None

    def mutate(state: JsonObject) -> JsonObject | None:
        project = state["projects"].get(clean_project_id)
        if not isinstance(project, dict):
            return None
        now = _now()
        binding = {
            "agi_id": clean_agi_id,
            "user_id": clean_user_id or None,
            "approved_at": now,
            "scope": "portal_project",
        }
        project[_PROJECT_GENOME_BINDING_KEY] = binding
        project["updated_at"] = now
        return dict(binding)

    binding = portal_state.mutate_state(mutate, root)
    if isinstance(binding, dict):
        portal_project_events.emit_project_event(
            clean_project_id,
            "project_changed",
            {"reason": "active_genome_changed"},
            root=root,
        )
        return binding
    return None


def list_project_frames(project_id: str, root: str | Path | None = None) -> JsonObject | None:
    state = portal_state.read_state(root)
    if project_id not in state["projects"]:
        return None
    frames: list[JsonObject] = []
    for frame in state["frames"].values():
        if frame.get("project_id") != project_id or frame.get("parent_frame_id") is not None:
            continue
        summary = _frame_summary(frame)
        messages = state["messages"].get(str(frame.get("id") or ""), [])
        summary["turn_count"] = len(
            [
                message
                for message in messages
                if isinstance(message, dict)
                and message.get("role") in {"user", "assistant"}
            ]
        )
        frames.append(summary)
    frames.sort(key=lambda frame: str(frame.get("updated_at") or ""), reverse=True)
    return {"project_id": project_id, "frames": frames}


def rename_frame(
    project_id: str,
    frame_id: str,
    title: str,
    root: str | Path | None = None,
) -> JsonObject | None:
    clean_project_id = str(project_id or "").strip()
    clean_frame_id = str(frame_id or "").strip()
    clean_title = _clean_conversation_title(title)
    if not clean_project_id or not clean_frame_id or not clean_title:
        return None

    def mutate(state: JsonObject) -> JsonObject | None:
        frame = state["frames"].get(clean_frame_id)
        if not isinstance(frame, dict) or frame.get("project_id") != clean_project_id:
            return None
        now = _now()
        frame["title"] = clean_title
        frame["updated_at"] = now
        project = state["projects"].get(clean_project_id)
        if isinstance(project, dict):
            project["updated_at"] = now
        return frame

    frame = portal_state.mutate_state(mutate, root)
    if not isinstance(frame, dict):
        return None
    _notify_project_workspace_changed(frame, ("frame",), reason="renamed", root=root)
    return _frame_summary(frame)


def list_project_artifacts(project_id: str, root: str | Path | None = None) -> JsonObject | None:
    state = portal_state.read_state(root)
    if project_id not in state["projects"]:
        return None
    artifacts = [
        portal_artifact_presenters.public_artifact_summary(artifact, state)
        for artifact in state["artifacts"].values()
        if artifact.get("project_id") == project_id
    ]
    artifacts.sort(key=lambda artifact: str(artifact.get("updated_at") or ""), reverse=True)
    return {"project_id": project_id, "artifacts": artifacts}


def get_artifact(artifact_id: str, root: str | Path | None = None) -> JsonObject | None:
    return portal_state.read_state(root)["artifacts"].get(artifact_id)


def get_project_artifact(project_id: str, artifact_id: str, root: str | Path | None = None) -> JsonObject | None:
    artifact = portal_state.read_state(root)["artifacts"].get(artifact_id)
    if not isinstance(artifact, dict) or artifact.get("project_id") != project_id:
        return None
    return artifact


def list_artifact_versions(artifact_id: str, root: str | Path | None = None) -> JsonObject | None:
    state = portal_state.read_state(root)
    artifact = state["artifacts"].get(artifact_id)
    if artifact is None:
        return None
    versions = [
        portal_artifact_presenters.public_artifact_version_detail(version)
        for version in state["artifact_versions"].values()
        if version.get("artifact_id") == artifact_id
    ]
    versions.sort(key=lambda version: str(version.get("created_at") or ""), reverse=True)
    return {
        "artifact_id": artifact_id,
        "latest_version_id": artifact.get("latest_version_id"),
        "versions": versions,
    }


def list_project_artifact_versions(project_id: str, artifact_id: str, root: str | Path | None = None) -> JsonObject | None:
    state = portal_state.read_state(root)
    artifact = state["artifacts"].get(artifact_id)
    if not isinstance(artifact, dict) or artifact.get("project_id") != project_id:
        return None
    versions = [
        portal_artifact_presenters.public_artifact_version_detail(version)
        for version in state["artifact_versions"].values()
        if (
            isinstance(version, dict)
            and version.get("project_id") == project_id
            and version.get("artifact_id") == artifact_id
        )
    ]
    versions.sort(key=lambda version: str(version.get("created_at") or ""), reverse=True)
    return {
        "project_id": project_id,
        "artifact_id": artifact_id,
        "latest_version_id": artifact.get("latest_version_id"),
        "versions": versions,
    }


def get_artifact_version(version_id: str, root: str | Path | None = None) -> JsonObject | None:
    return portal_state.read_state(root)["artifact_versions"].get(version_id)


def get_project_artifact_version(project_id: str, artifact_id: str, version_id: str, root: str | Path | None = None) -> JsonObject | None:
    state = portal_state.read_state(root)
    artifact = state["artifacts"].get(artifact_id)
    if not isinstance(artifact, dict) or artifact.get("project_id") != project_id:
        return None
    version = state["artifact_versions"].get(version_id)
    if not isinstance(version, dict) or version.get("project_id") != project_id or version.get("artifact_id") != artifact_id:
        return None
    return version


def latest_artifact_file_path(artifact_id: str, root: str | Path | None = None) -> Path | None:
    state = portal_state.read_state(root)
    artifact = state["artifacts"].get(artifact_id)
    if not isinstance(artifact, dict):
        return None
    version_id = artifact.get("latest_version_id")
    if not isinstance(version_id, str) or not version_id:
        return None
    version = state["artifact_versions"].get(version_id)
    if not isinstance(version, dict) or version.get("artifact_id") != artifact_id:
        return None
    return portal_artifact_versions.artifact_version_file_path(version, root=root)


def latest_project_artifact_file_path(project_id: str, artifact_id: str, root: str | Path | None = None) -> Path | None:
    state = portal_state.read_state(root)
    artifact = state["artifacts"].get(artifact_id)
    if not isinstance(artifact, dict) or artifact.get("project_id") != project_id:
        return None
    version_id = artifact.get("latest_version_id")
    if not isinstance(version_id, str) or not version_id:
        return None
    version = state["artifact_versions"].get(version_id)
    if not isinstance(version, dict) or version.get("project_id") != project_id or version.get("artifact_id") != artifact_id:
        return None
    return portal_artifact_versions.artifact_version_file_path(version, root=root)


def artifact_version_file_path(version_id: str, root: str | Path | None = None) -> Path | None:
    version = portal_state.read_state(root)["artifact_versions"].get(version_id)
    return portal_artifact_versions.artifact_version_file_path(version, root=root) if isinstance(version, dict) else None


def project_artifact_version_file_path(project_id: str, artifact_id: str, version_id: str, root: str | Path | None = None) -> Path | None:
    version = get_project_artifact_version(project_id, artifact_id, version_id, root=root)
    return portal_artifact_versions.artifact_version_file_path(version, root=root) if isinstance(version, dict) else None


def public_artifact_version_summary(version: JsonObject) -> JsonObject:
    return portal_artifact_presenters.public_artifact_version_summary(version)


def public_artifact_version_detail(version: JsonObject) -> JsonObject:
    return portal_artifact_presenters.public_artifact_version_detail(version)


def public_artifact_summary(artifact: JsonObject, root: str | Path | None = None) -> JsonObject:
    return portal_artifact_presenters.public_artifact_summary(artifact, portal_state.read_state(root))


def public_artifact_detail(artifact: JsonObject, root: str | Path | None = None) -> JsonObject:
    return portal_artifact_presenters.public_artifact_detail(artifact, portal_state.read_state(root))


def run_project_artifact_version_review(
    project_id: str,
    artifact_id: str,
    version_id: str | None = None,
    *,
    root: str | Path | None = None,
) -> JsonObject | None:
    clean_version_id = str(version_id or "").strip()

    def mutate(state: JsonObject) -> JsonObject | None:
        artifact = state["artifacts"].get(artifact_id)
        if not isinstance(artifact, dict) or artifact.get("project_id") != project_id:
            return None
        target_version_id = clean_version_id or str(artifact.get("latest_version_id") or "").strip()
        if not target_version_id:
            return None
        version = state["artifact_versions"].get(target_version_id)
        if (
            not isinstance(version, dict)
            or version.get("project_id") != project_id
            or version.get("artifact_id") != artifact_id
        ):
            return None
        now = _now()
        review = portal_artifact_review.artifact_version_review(
            artifact_kind=str(artifact.get("kind") or ""),
            renderer=str(artifact.get("renderer") or ""),
            operation=str(artifact.get("operation") or ""),
            result={},
            summary=artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {},
            public_payload={
                "artifact": portal_artifact_presenters.public_artifact_summary(artifact, state),
                "version": portal_artifact_presenters.public_artifact_version_summary(version),
            },
            version=version,
            reproduction=version.get("reproduction") if isinstance(version.get("reproduction"), dict) else None,
            created_at=now,
        )
        review_run = portal_artifact_review.artifact_review_run(
            review=review,
            review_run_id=f"rev_{uuid.uuid4().hex[:12]}",
            version=version,
            started_at=now,
            completed_at=now,
        )
        version["review"] = review
        review_runs = version.get("review_runs") if isinstance(version.get("review_runs"), list) else []
        version["review_runs"] = [*review_runs, review_run][-12:]
        artifact["updated_at"] = now
        project = state["projects"].get(project_id)
        if isinstance(project, dict):
            project["updated_at"] = now
        return {"artifact": artifact, "version": version, "review_run": review_run}

    result = portal_state.mutate_state(mutate, root)
    if not isinstance(result, dict) or not isinstance(result.get("version"), dict):
        return None
    _notify_project_workspace_changed(result["artifact"], ("artifacts",), reason="reviewed", root=root)
    return {
        "review_run": result.get("review_run"),
        "version": portal_artifact_presenters.public_artifact_version_detail(result["version"]),
    }


def validate_artifact_origin_frame(project_id: str, frame_id: str, root: str | Path | None = None) -> str:
    return portal_artifact_origins.validate_frame_id(portal_state.read_state(root), project_id, frame_id)


def add_artifact(
    project_id: str,
    *,
    kind: str,
    renderer: str,
    title: str,
    operation: str,
    result: JsonObject,
    frame_id: str | None = None,
    file_path: str | None = None,
    external_url: str | None = None,
    summary: JsonObject | None = None,
    summary_lines: list[str] | None = None,
    reproduction: JsonObject | None = None,
    open_label: str | None = None,
    root: str | Path | None = None,
) -> JsonObject | None:
    def create_version(
        artifact_id: str,
        renderer_id: str,
        host_agent_id: str,
        created_at: str,
        artifact_summary: JsonObject,
        artifact_public_payload: JsonObject,
        producing_work_step: JsonObject,
    ) -> JsonObject | None:
        return portal_artifact_versions.create_artifact_version(
            project_id=project_id,
            artifact_id=artifact_id,
            artifact_kind=kind,
            renderer=renderer_id,
            operation=operation,
            result=result,
            summary=artifact_summary,
            public_payload=artifact_public_payload,
            host_agent_id=host_agent_id,
            file_path=file_path,
            created_at=created_at,
            reproduction=reproduction,
            producing_work_step=producing_work_step,
            root=root,
        )

    return _add_artifact(
        project_id,
        kind=kind,
        renderer=renderer,
        title=title,
        operation=operation,
        result=result,
        frame_id=frame_id,
        external_url=external_url,
        summary=summary,
        summary_lines=summary_lines,
        reproduction=reproduction,
        open_label=open_label,
        root=root,
        create_version=create_version,
    )


def add_artifact_from_bytes(
    project_id: str,
    *,
    kind: str,
    renderer: str,
    title: str,
    operation: str,
    result: JsonObject,
    original_filename: str,
    content_type: str,
    body: bytes,
    frame_id: str | None = None,
    external_url: str | None = None,
    summary: JsonObject | None = None,
    summary_lines: list[str] | None = None,
    reproduction: JsonObject | None = None,
    open_label: str | None = None,
    root: str | Path | None = None,
) -> JsonObject | None:
    def create_version(
        artifact_id: str,
        renderer_id: str,
        host_agent_id: str,
        created_at: str,
        artifact_summary: JsonObject,
        artifact_public_payload: JsonObject,
        producing_work_step: JsonObject,
    ) -> JsonObject:
        return portal_artifact_versions.create_artifact_version_from_bytes(
            project_id=project_id,
            artifact_id=artifact_id,
            artifact_kind=kind,
            renderer=renderer_id,
            operation=operation,
            result=result,
            summary=artifact_summary,
            public_payload=artifact_public_payload,
            host_agent_id=host_agent_id,
            original_filename=original_filename,
            content_type=content_type,
            body=body,
            created_at=created_at,
            reproduction=reproduction,
            producing_work_step=producing_work_step,
            root=root,
        )

    return _add_artifact(
        project_id,
        kind=kind,
        renderer=renderer,
        title=title,
        operation=operation,
        result=result,
        frame_id=frame_id,
        external_url=external_url,
        summary=summary,
        summary_lines=summary_lines,
        reproduction=reproduction,
        open_label=open_label,
        root=root,
        create_version=create_version,
    )


def _add_artifact(
    project_id: str,
    *,
    kind: str,
    renderer: str,
    title: str,
    operation: str,
    result: JsonObject,
    frame_id: str | None,
    external_url: str | None,
    summary: JsonObject | None,
    summary_lines: list[str] | None,
    reproduction: JsonObject | None,
    open_label: str | None,
    root: str | Path | None,
    create_version: VersionCreator,
) -> JsonObject | None:
    renderer_id = renderer.strip()
    if not renderer_id:
        raise ValueError("artifact renderer required")

    created_version: JsonObject | None = None

    def mutate(state: JsonObject) -> JsonObject | None:
        nonlocal created_version
        project = state["projects"].get(project_id)
        if project is None:
            return None
        now = _now()
        origin = portal_artifact_origins.origin_snapshot(state, project_id, frame_id)
        origin_frame = state["frames"].get(str(frame_id or "").strip())
        host_agent_id = str(origin_frame.get("agent_id") or "").strip() if isinstance(origin_frame, dict) else ""
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        raw_artifact_summary = summary or _default_artifact_summary(result)
        raw_artifact_summary_lines = _clean_summary_lines(
            summary_lines,
            prompt_safe=False,
        ) or _default_artifact_summary_lines(result, operation, prompt_safe=False)
        raw_open_label = _clean_open_label(open_label, prompt_safe=False)
        artifact_title = _clean_artifact_title(title) or "Artifact"
        artifact_summary = _safe_summary(raw_artifact_summary)
        artifact_summary_lines = _clean_summary_lines(raw_artifact_summary_lines)
        artifact_open_label = _clean_open_label(raw_open_label)
        producing_work_step = portal_artifact_work_steps.producing_work_step(
            project_id=project_id,
            artifact_title=artifact_title,
            artifact_kind=kind,
            renderer=renderer_id,
            operation=operation,
            result=result,
            summary_lines=artifact_summary_lines,
            origin=origin,
            created_at=now,
        )
        artifact_public_payload = {
            "title": title,
            "summary": raw_artifact_summary,
            "summary_lines": raw_artifact_summary_lines,
            "open_label": raw_open_label,
        }
        created_version = create_version(
            artifact_id,
            renderer_id,
            host_agent_id,
            now,
            artifact_summary,
            artifact_public_payload,
            producing_work_step,
        )
        if created_version is not None:
            state["artifact_versions"][created_version["version_id"]] = created_version
        open_url = _safe_external_artifact_url(external_url)
        preview_url = portal_routes.project_artifact_file_endpoint(project_id, artifact_id) if created_version is not None else None
        artifact = {
            "id": artifact_id,
            "project_id": project_id,
            "kind": kind,
            "renderer": renderer_id,
            "title": artifact_title,
            "operation": operation,
            "status": result.get("status") or "unknown",
            "url": open_url or preview_url,
            "preview_url": preview_url,
            "summary": artifact_summary,
            "summary_lines": artifact_summary_lines,
            "open_label": artifact_open_label,
            "latest_version_id": created_version.get("version_id") if created_version is not None else None,
            "version_count": 1 if created_version is not None else 0,
            "created_at": now,
            "updated_at": now,
        }
        if origin is not None:
            artifact["origin"] = origin
        state["artifacts"][artifact["id"]] = artifact
        project["artifact_count"] = len(
            [item for item in state["artifacts"].values() if item.get("project_id") == project_id]
        )
        project["updated_at"] = now
        return artifact

    try:
        artifact = portal_state.mutate_state(mutate, root)
    except Exception:
        if created_version is not None:
            portal_artifact_versions.remove_artifact_version_blob(created_version, root=root)
        raise
    if isinstance(artifact, dict):
        _notify_project_workspace_changed(artifact, ("artifacts",), reason="created", root=root)
    return artifact


def attach_artifact_producing_event(
    artifact_id: str,
    *,
    run_id: str,
    event_id: int,
    root: str | Path | None = None,
) -> JsonObject | None:
    clean_artifact_id = str(artifact_id or "").strip()
    clean_run_id = portal_turns.prompt_safe_text(str(run_id or "")).strip()
    if not clean_artifact_id or not clean_run_id:
        return None

    def mutate(state: JsonObject) -> JsonObject | None:
        artifact = state["artifacts"].get(clean_artifact_id)
        if not isinstance(artifact, dict):
            return None
        version_id = str(artifact.get("latest_version_id") or "").strip()
        version = state["artifact_versions"].get(version_id)
        if not isinstance(version, dict):
            return None
        origin = artifact.get("origin") if isinstance(artifact.get("origin"), dict) else {}
        anchored = portal_artifact_work_steps.with_execution_anchor(
            version.get("producing_work_step"),
            project_id=str(artifact.get("project_id") or ""),
            frame_id=str(origin.get("frame_id") or ""),
            run_id=clean_run_id,
            event_id=event_id,
        )
        if anchored is None:
            return None
        version["producing_work_step"] = anchored
        return artifact

    artifact = portal_state.mutate_state(mutate, root)
    if isinstance(artifact, dict):
        _notify_project_workspace_changed(artifact, ("artifacts",), reason="updated", root=root)
    return artifact


def rename_project_artifact(
    project_id: str,
    artifact_id: str,
    *,
    title: str,
    root: str | Path | None = None,
) -> JsonObject | None:
    clean_title = _clean_artifact_title(title)
    if not clean_title:
        return None

    def rename(artifact: JsonObject) -> None:
        artifact["title"] = clean_title

    return _mutate_project_artifact(
        project_id,
        artifact_id,
        rename,
        root=root,
    )


def set_project_artifact_starred(
    project_id: str,
    artifact_id: str,
    starred: bool,
    *,
    root: str | Path | None = None,
) -> JsonObject | None:
    def set_starred(artifact: JsonObject) -> None:
        artifact["starred"] = bool(starred)

    return _mutate_project_artifact(
        project_id,
        artifact_id,
        set_starred,
        root=root,
    )


def set_project_artifact_hidden(
    project_id: str,
    artifact_id: str,
    hidden: bool,
    *,
    root: str | Path | None = None,
) -> JsonObject | None:
    def set_hidden(artifact: JsonObject) -> None:
        artifact["hidden"] = bool(hidden)

    return _mutate_project_artifact(
        project_id,
        artifact_id,
        set_hidden,
        root=root,
    )


def _mutate_project_artifact(
    project_id: str,
    artifact_id: str,
    update: Callable[[JsonObject], None],
    *,
    root: str | Path | None = None,
) -> JsonObject | None:
    def mutate(state: JsonObject) -> JsonObject | None:
        artifact = state["artifacts"].get(artifact_id)
        if not isinstance(artifact, dict) or artifact.get("project_id") != project_id:
            return None
        now = _now()
        update(artifact)
        artifact["updated_at"] = now
        project = state["projects"].get(project_id)
        if isinstance(project, dict):
            project["updated_at"] = now
        return artifact

    artifact = portal_state.mutate_state(mutate, root)
    if isinstance(artifact, dict):
        _notify_project_workspace_changed(artifact, ("artifacts",), reason="updated", root=root)
    return artifact


def delete_project_artifact(
    project_id: str,
    artifact_id: str,
    *,
    root: str | Path | None = None,
) -> JsonObject | None:
    def mutate(state: JsonObject) -> JsonObject | None:
        artifact = state["artifacts"].get(artifact_id)
        if not isinstance(artifact, dict) or artifact.get("project_id") != project_id:
            return None
        versions = [
            version
            for version in state["artifact_versions"].values()
            if isinstance(version, dict)
            and version.get("project_id") == project_id
            and version.get("artifact_id") == artifact_id
        ]
        state["artifacts"].pop(artifact_id, None)
        for version in versions:
            version_id = version.get("version_id")
            if isinstance(version_id, str):
                state["artifact_versions"].pop(version_id, None)
        now = _now()
        project = state["projects"].get(project_id)
        if isinstance(project, dict):
            project["artifact_count"] = len(
                [item for item in state["artifacts"].values() if item.get("project_id") == project_id]
            )
            project["updated_at"] = now
        return {"artifact": artifact, "versions": versions}

    result = portal_state.mutate_state(mutate, root)
    if not isinstance(result, dict) or not isinstance(result.get("artifact"), dict):
        return None
    for version in result.get("versions") or []:
        if isinstance(version, dict):
            portal_artifact_versions.remove_artifact_version_blob(version, root=root)
    _notify_project_workspace_changed(
        {"project_id": project_id, "id": artifact_id},
        ("artifacts",),
        reason="deleted",
        root=root,
    )
    return result["artifact"]


def create_frame(
    *,
    project_id: str,
    request: str,
    agent_id: str,
    selected_evidence: list[JsonObject] | None = None,
    genome_context_mode: str | None = None,
    started_from_selected_material: bool = False,
    source_frame_id: str | None = None,
    root: str | Path | None = None,
) -> JsonObject | None:
    clean_evidence = portal_turns.clean_selected_evidence(selected_evidence)
    clean_genome_context_mode = _clean_genome_context_mode(genome_context_mode)
    requested_source_frame_id = portal_turns.prompt_safe_text(str(source_frame_id or "")).strip()

    def mutate(state: JsonObject) -> JsonObject | None:
        project = state["projects"].get(project_id)
        if project is None:
            return None
        clean_source_frame_id = _validated_source_frame_id(
            state,
            project_id=project_id,
            source_frame_id=requested_source_frame_id,
        )
        input_data: JsonObject = {
            "request": request,
            "selected_evidence": clean_evidence,
            "genome_context_mode": clean_genome_context_mode,
        }
        if started_from_selected_material:
            handoff = portal_turns.selected_material_handoff(
                clean_evidence,
                source_frame_id=clean_source_frame_id,
            )
            if handoff:
                input_data["started_from"] = handoff
        frame_id = str(uuid.uuid4())
        now = _now()
        frame = {
            "id": frame_id,
            "root_frame_id": frame_id,
            "parent_frame_id": None,
            "project_id": project_id,
            "title": _default_conversation_title(request, clean_evidence),
            "agent_id": agent_id,
            "run_id": None,
            "status": "queued",
            "input_data": input_data,
            "output_data": {},
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "message_count": 1,
        }
        state["frames"][frame_id] = frame
        state["messages"][frame_id] = [
            _message(
                "user",
                text=request,
                selected_evidence=clean_evidence,
                genome_context_mode=clean_genome_context_mode,
            )
        ]
        project["conversation_count"] = int(project.get("conversation_count") or 0) + 1
        project["updated_at"] = now
        return frame

    frame = portal_state.mutate_state(mutate, root)
    if isinstance(frame, dict):
        _notify_project_workspace_changed(frame, ("frame", "messages"), reason="created", root=root)
    return frame


def get_frame(frame_id: str, root: str | Path | None = None) -> JsonObject | None:
    return portal_state.read_state(root)["frames"].get(frame_id)


def get_frame_by_run_id(run_id: str, root: str | Path | None = None) -> JsonObject | None:
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return None
    for frame in portal_state.read_state(root)["frames"].values():
        if not isinstance(frame, dict):
            continue
        output_data = frame.get("output_data") if isinstance(frame.get("output_data"), dict) else {}
        if frame.get("run_id") == clean_run_id or output_data.get("stale_run_id") == clean_run_id:
            return frame
    return None


def frame_review_source_messages(frame_id: str, root: str | Path | None = None) -> list[JsonObject]:
    state = portal_state.read_state(root)
    if frame_id not in state["frames"]:
        return []
    return portal_conversation_reviews.source_messages(state["messages"].get(frame_id, []))


def begin_frame_review(
    frame_id: str,
    *,
    project_id: str,
    review_run_id: str,
    source_message_ids: list[str],
    root: str | Path | None = None,
) -> JsonObject | None:
    def mutate(state: JsonObject) -> JsonObject | None:
        frame = state["frames"].get(frame_id)
        if not isinstance(frame, dict) or frame.get("project_id") != project_id:
            return None
        reviews = frame.get("review_runs") if isinstance(frame.get("review_runs"), list) else []
        if any(isinstance(item, dict) and item.get("status") == "running" for item in reviews):
            return {"status": "busy"}
        now = _now()
        review = portal_conversation_reviews.pending_review(
            review_run_id=review_run_id,
            source_message_ids=source_message_ids,
            started_at=now,
        )
        frame["review_runs"] = [*reviews, review][-8:]
        frame["updated_at"] = now
        project = state["projects"].get(project_id)
        if isinstance(project, dict):
            project["updated_at"] = now
        return review

    result = portal_state.mutate_state(mutate, root)
    if isinstance(result, dict) and result.get("status") != "busy":
        _notify_project_workspace_changed(
            {"id": frame_id, "project_id": project_id},
            ("messages",),
            reason="review_started",
            root=root,
        )
    return result


def complete_frame_review(
    frame_id: str,
    *,
    review_run_id: str,
    output: str,
    root: str | Path | None = None,
) -> JsonObject | None:
    return _finish_frame_review(frame_id, review_run_id=review_run_id, output=output, error=None, root=root)


def fail_frame_review(
    frame_id: str,
    *,
    review_run_id: str,
    error: str,
    root: str | Path | None = None,
) -> JsonObject | None:
    return _finish_frame_review(frame_id, review_run_id=review_run_id, output=None, error=error, root=root)


def _finish_frame_review(
    frame_id: str,
    *,
    review_run_id: str,
    output: str | None,
    error: str | None,
    root: str | Path | None,
) -> JsonObject | None:
    def mutate(state: JsonObject) -> JsonObject | None:
        frame = state["frames"].get(frame_id)
        if not isinstance(frame, dict):
            return None
        reviews = frame.get("review_runs") if isinstance(frame.get("review_runs"), list) else []
        current = next(
            (
                item
                for item in reversed(reviews)
                if isinstance(item, dict) and item.get("review_run_id") == review_run_id
            ),
            None,
        )
        if current is None:
            return None
        now = _now()
        source_message_ids = current.get("source_message_ids") if isinstance(current.get("source_message_ids"), list) else []
        started_at = str(current.get("started_at") or now)
        if error is None:
            review = portal_conversation_reviews.completed_review(
                review_run_id=review_run_id,
                output=str(output or ""),
                source_message_ids=source_message_ids,
                started_at=started_at,
                completed_at=now,
            )
        else:
            review = portal_conversation_reviews.failed_review(
                review_run_id=review_run_id,
                source_message_ids=source_message_ids,
                started_at=started_at,
                completed_at=now,
                error=error,
            )
        frame["review_runs"] = [review if item is current else item for item in reviews][-8:]
        frame["updated_at"] = now
        project_id = str(frame.get("project_id") or "")
        project = state["projects"].get(project_id)
        if isinstance(project, dict):
            project["updated_at"] = now
        return {"review": review, "project_id": project_id}

    result = portal_state.mutate_state(mutate, root)
    if not isinstance(result, dict) or not isinstance(result.get("review"), dict):
        return None
    _notify_project_workspace_changed(
        {"id": frame_id, "project_id": result.get("project_id")},
        ("messages",),
        reason="review_completed" if error is None else "review_failed",
        root=root,
    )
    return portal_conversation_reviews.public_review(result["review"])


def reconcile_stale_processing_runs(
    *,
    known_run_ids: set[str],
    run_id: str | None = None,
    root: str | Path | None = None,
) -> list[JsonObject]:
    known_ids = {str(item) for item in known_run_ids if str(item)}
    requested_run_id = str(run_id or "").strip()
    changed: list[JsonObject] = []

    def mutate(state: JsonObject) -> list[JsonObject]:
        now = _now()
        for frame in state["frames"].values():
            if not isinstance(frame, dict):
                continue
            frame_run_id = str(frame.get("run_id") or "")
            if not frame_run_id or frame_run_id in known_ids:
                continue
            if requested_run_id and frame_run_id != requested_run_id:
                continue
            if frame.get("status") != _PROCESSING_FRAME_STATUS:
                continue
            _mark_frame_stale_after_restart(state, frame, run_id=frame_run_id, now=now)
            changed.append(_frame_summary(frame))
        return changed

    result = portal_state.mutate_state(mutate, root)
    for frame in result:
        _notify_project_workspace_changed(frame, ("frame", "messages"), reason=STALE_AFTER_RESTART_STATUS, root=root)
    return result


def reconcile_stale_conversation_reviews(
    *,
    known_run_ids: set[str],
    run_id: str | None = None,
    root: str | Path | None = None,
) -> list[JsonObject]:
    known_ids = {str(item) for item in known_run_ids if str(item)}
    requested_run_id = str(run_id or "").strip()
    changed: list[JsonObject] = []

    def mutate(state: JsonObject) -> list[JsonObject]:
        now = _now()
        for frame in state["frames"].values():
            if not isinstance(frame, dict):
                continue
            reviews = frame.get("review_runs") if isinstance(frame.get("review_runs"), list) else []
            next_reviews = list(reviews)
            frame_changed = False
            for index, review in enumerate(reviews):
                if not isinstance(review, dict) or review.get("status") != "running":
                    continue
                review_id = str(review.get("review_run_id") or "").strip()
                if not review_id or review_id in known_ids:
                    continue
                if requested_run_id and review_id != requested_run_id:
                    continue
                source_ids = review.get("source_message_ids") if isinstance(review.get("source_message_ids"), list) else []
                next_reviews[index] = portal_conversation_reviews.failed_review(
                    review_run_id=review_id,
                    source_message_ids=source_ids,
                    started_at=str(review.get("started_at") or now),
                    completed_at=now,
                    error="Review was interrupted by a server restart.",
                )
                frame_changed = True
                changed.append({"frame_id": frame.get("id"), "review_run_id": review_id})
            if frame_changed:
                frame["review_runs"] = next_reviews[-8:]
                frame["updated_at"] = now
        return changed

    result = portal_state.mutate_state(mutate, root)
    for item in result:
        frame = get_frame(str(item.get("frame_id") or ""), root)
        if isinstance(frame, dict):
            _notify_project_workspace_changed(frame, ("messages",), reason="review_interrupted", root=root)
    return result


def stale_run_status(run_id: str, root: str | Path | None = None) -> JsonObject | None:
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return None
    state = portal_state.read_state(root)
    for frame in state["frames"].values():
        if not isinstance(frame, dict):
            continue
        output_data = frame.get("output_data") if isinstance(frame.get("output_data"), dict) else {}
        stale_run_id = str(output_data.get("stale_run_id") or "")
        if frame.get("run_id") != clean_run_id and stale_run_id != clean_run_id:
            continue
        if frame.get("status") != STALE_AFTER_RESTART_STATUS and stale_run_id != clean_run_id:
            continue
        return _stale_run_status(frame, clean_run_id)
    return None


def persisted_run_status(run_id: str, root: str | Path | None = None) -> JsonObject | None:
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return None
    state = portal_state.read_state(root)
    for frame in state["frames"].values():
        if not isinstance(frame, dict):
            continue
        reviews = frame.get("review_runs") if isinstance(frame.get("review_runs"), list) else []
        review = next(
            (
                item
                for item in reversed(reviews)
                if isinstance(item, dict) and item.get("review_run_id") == clean_run_id
            ),
            None,
        )
        if review is not None:
            review_status = str(review.get("status") or "unknown")
            status = "succeeded" if review_status == "completed" else review_status
            return {
                "id": clean_run_id,
                "kind": "conversation_review",
                "status": status,
                "terminal": review_status in {"completed", "failed"},
                "createdAt": _iso_timestamp_ms(review.get("started_at")),
                "updatedAt": _iso_timestamp_ms(review.get("completed_at") or review.get("started_at")),
                "error": review.get("error"),
            }
        output_data = frame.get("output_data") if isinstance(frame.get("output_data"), dict) else {}
        stale_run_id = str(output_data.get("stale_run_id") or "")
        if frame.get("run_id") != clean_run_id and stale_run_id != clean_run_id:
            continue
        if frame.get("status") == _PROCESSING_FRAME_STATUS:
            return None
        return _persisted_run_status(frame, clean_run_id)
    return None


def public_frame(frame: JsonObject) -> JsonObject:
    summary = _frame_summary(frame)
    input_data = frame.get("input_data") if isinstance(frame.get("input_data"), dict) else {}
    selected_evidence = portal_turns.clean_selected_evidence(input_data.get("selected_evidence"))
    if selected_evidence:
        summary["selected_evidence"] = selected_evidence
    output_data = frame.get("output_data") if isinstance(frame.get("output_data"), dict) else {}
    public_output: JsonObject = {}
    if isinstance(output_data.get("error"), str) and output_data["error"].strip():
        public_output["error"] = portal_turns.prompt_safe_text(str(output_data["error"]))
    if output_data.get("stale_run_id"):
        public_output["stale_run_id"] = output_data.get("stale_run_id")
    if output_data.get("stale_run_status"):
        public_output["stale_run_status"] = output_data.get("stale_run_status")
    if public_output:
        summary["output"] = public_output
    return summary


def get_frame_for_project(frame_id: str, project_id: str, root: str | Path | None = None) -> JsonObject | None:
    frame = get_frame(frame_id, root)
    if frame is None or frame.get("project_id") != project_id:
        return None
    return frame


def list_frame_messages(frame_id: str, root: str | Path | None = None) -> JsonObject | None:
    state = portal_state.read_state(root)
    if frame_id not in state["frames"]:
        return None
    frame = state["frames"].get(frame_id) if isinstance(state["frames"].get(frame_id), dict) else {}
    messages = state["messages"].get(frame_id, [])
    return {
        "frame_id": frame_id,
        "from": 0,
        "total": len(messages),
        "messages": [portal_artifact_presenters.public_message(message, frame_id=frame_id) for message in messages],
        "reviews": portal_conversation_reviews.public_reviews(frame.get("review_runs")),
    }


def frame_conversation_history(
    frame_id: str,
    *,
    max_messages: int = 8,
    max_text_chars: int = 1200,
    root: str | Path | None = None,
) -> list[JsonObject]:
    state = portal_state.read_state(root)
    if frame_id not in state["frames"]:
        return []
    records: list[JsonObject] = []
    for message in state["messages"].get(frame_id, []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        text = portal_turns.prompt_safe_text(str(message.get("text") or "")).strip()
        if not text:
            continue
        record: JsonObject = {
            "role": role,
            "text": text[:max_text_chars],
        }
        attachments = _history_attachment_summaries(message.get("selected_evidence"))
        if attachments:
            record["attached_material"] = attachments
        records.append(record)
    limit = max(0, int(max_messages))
    return records[-limit:] if limit else []


def _history_attachment_summaries(value: Any) -> list[JsonObject]:
    summaries: list[JsonObject] = []
    for item in portal_turns.clean_selected_evidence(value)[:3]:
        label = portal_turns.prompt_safe_text(str(item.get("label") or "Included evidence")).strip()
        text = portal_turns.prompt_safe_text(str(item.get("summary") or item.get("prompt_text") or "")).strip()
        summary: JsonObject = {"label": label[:120] or "Included evidence"}
        if text:
            summary["summary"] = text[:240]
        summaries.append(summary)
    return summaries


def append_message(
    frame_id: str,
    *,
    role: str,
    text: str | None = None,
    event: JsonObject | None = None,
    run_id: str | None = None,
    root: str | Path | None = None,
) -> JsonObject | None:
    def mutate(state: JsonObject) -> JsonObject | None:
        frame = state["frames"].get(frame_id)
        if frame is None:
            return None
        message = _message(role, text=text, event=event, run_id=run_id)
        state["messages"].setdefault(frame_id, []).append(message)
        frame["message_count"] = len(state["messages"][frame_id])
        frame["updated_at"] = message["created_at"]
        project = state["projects"].get(str(frame.get("project_id")))
        if project is not None:
            project["updated_at"] = message["created_at"]
        return message

    message = portal_state.mutate_state(mutate, root)
    if isinstance(message, dict):
        frame = get_frame(frame_id, root)
        if isinstance(frame, dict):
            _notify_project_workspace_changed(
                frame,
                ("messages",),
                reason="appended",
                message_id=str(message.get("id") or ""),
                root=root,
            )
    return message


def begin_frame_message(
    frame_id: str,
    *,
    text: str,
    selected_evidence: list[JsonObject] | None = None,
    genome_context_mode: str | None = None,
    agent_id: str,
    run_id: str,
    recover_stale_run: bool = False,
    project_id: str | None = None,
    root: str | Path | None = None,
) -> JsonObject | None:
    clean_evidence = portal_turns.clean_selected_evidence(selected_evidence)
    clean_genome_context_mode = _clean_genome_context_mode(genome_context_mode)

    def mutate(state: JsonObject) -> JsonObject | None:
        frame = state["frames"].get(frame_id)
        if frame is None:
            return None
        if project_id and frame.get("project_id") != project_id:
            return {"status": "wrong_project", "frame": _frame_summary(frame)}
        previous_run_id = str(frame.get("run_id") or "")
        if frame.get("status") == _PROCESSING_FRAME_STATUS and not recover_stale_run:
            return {"status": "busy", "frame": _frame_summary(frame)}
        now = _now()
        if recover_stale_run and previous_run_id:
            _mark_frame_stale_after_restart(state, frame, run_id=previous_run_id, now=now)
        message = _message(
            "user",
            text=text,
            selected_evidence=clean_evidence,
            genome_context_mode=clean_genome_context_mode,
        )
        state["messages"].setdefault(frame_id, []).append(message)
        frame["run_id"] = run_id
        frame["agent_id"] = agent_id
        frame["status"] = _PROCESSING_FRAME_STATUS
        frame["updated_at"] = now
        frame["completed_at"] = None
        frame["message_count"] = len(state["messages"][frame_id])
        project = state["projects"].get(str(frame.get("project_id")))
        if project is not None:
            project["updated_at"] = now
        return {"status": "accepted", "frame": frame, "message": message}

    result = portal_state.mutate_state(mutate, root)
    if isinstance(result, dict) and result.get("status") == "accepted" and isinstance(result.get("frame"), dict):
        frame = result["frame"]
        message = result.get("message") if isinstance(result.get("message"), dict) else {}
        _notify_project_workspace_changed(
            frame,
            ("frame", "messages"),
            reason="message_started",
            message_id=str(message.get("id") or ""),
            root=root,
        )
    return result


def upsert_assistant_message(
    frame_id: str,
    *,
    run_id: str,
    text: str,
    stream_status: str = "streaming",
    root: str | Path | None = None,
) -> JsonObject | None:
    def mutate(state: JsonObject) -> JsonObject | None:
        frame = state["frames"].get(frame_id)
        if frame is None:
            return None
        now = _now()
        messages = state["messages"].setdefault(frame_id, [])
        message = _find_assistant_run_message(messages, run_id)
        if message is None:
            message = _message("assistant", text=text)
            message["run_id"] = run_id
            messages.append(message)
        else:
            message["text"] = text
        message["stream_status"] = stream_status
        message["updated_at"] = now
        frame["message_count"] = len(messages)
        frame["updated_at"] = now
        project = state["projects"].get(str(frame.get("project_id")))
        if project is not None:
            project["updated_at"] = now
        return message

    message = portal_state.mutate_state(mutate, root)
    if isinstance(message, dict):
        frame = get_frame(frame_id, root)
        if isinstance(frame, dict):
            _notify_project_workspace_changed(
                frame,
                ("messages",),
                reason="assistant_stream",
                message_id=str(message.get("id") or ""),
                root=root,
            )
    return message


def attach_run(frame_id: str, *, run_id: str, agent_id: str, root: str | Path | None = None) -> JsonObject | None:
    def mutate(state: JsonObject) -> JsonObject | None:
        frame = state["frames"].get(frame_id)
        if frame is None:
            return None
        frame["run_id"] = run_id
        frame["agent_id"] = agent_id
        frame["status"] = "processing"
        frame["updated_at"] = _now()
        return frame

    frame = portal_state.mutate_state(mutate, root)
    if isinstance(frame, dict):
        _notify_project_workspace_changed(frame, ("frame",), reason="run_attached", root=root)
    return frame


def finish_frame(
    frame_id: str,
    *,
    status: str,
    output: str = "",
    error: str | None = None,
    run_id: str | None = None,
    root: str | Path | None = None,
) -> JsonObject | None:
    def mutate(state: JsonObject) -> JsonObject | None:
        frame = state["frames"].get(frame_id)
        if frame is None:
            return None
        now = _now()
        failure = _terminal_run_failure(status, error, output)
        visible_text = output or (failure.message_text() if failure else "")
        if visible_text:
            messages = state["messages"].setdefault(frame_id, [])
            message = _find_assistant_run_message(messages, run_id) if run_id else None
            if message is None:
                message = _message("assistant", text=visible_text)
                if run_id:
                    message["run_id"] = run_id
                messages.append(message)
            else:
                message["text"] = visible_text
            message["stream_status"] = status
            message["updated_at"] = now
        frame["message_count"] = len(state["messages"].get(frame_id, []))
        frame["status"] = status
        frame["completed_at"] = now
        frame["updated_at"] = now
        frame_error = failure.headline if failure else portal_turns.prompt_safe_text(error or "")
        frame["output_data"] = {"error": frame_error or None}
        project = state["projects"].get(str(frame.get("project_id")))
        if project is not None:
            project["updated_at"] = now
        return frame

    frame = portal_state.mutate_state(mutate, root)
    if isinstance(frame, dict):
        _notify_project_workspace_changed(frame, ("frame", "messages"), reason="completed", root=root)
    return frame


def _terminal_run_failure(status: str, error: str | None, output: str) -> portal_run_failures.RunFailure | None:
    """The conversation-visible outcome for a run that ended without an answer."""

    clean_status = str(status or "").strip().lower()
    if clean_status not in portal_run_failures.FAILED_RUN_STATUSES:
        return None
    if output.strip():
        return None
    return portal_run_failures.classify_run_failure(error or "", status=clean_status)


def _mark_frame_stale_after_restart(state: JsonObject, frame: JsonObject, *, run_id: str, now: str) -> None:
    frame["status"] = STALE_AFTER_RESTART_STATUS
    frame["completed_at"] = now
    frame["updated_at"] = now
    frame["output_data"] = {
        "error": STALE_AFTER_RESTART_ERROR,
        "stale_run_id": run_id,
        "stale_run_status": STALE_AFTER_RESTART_STATUS,
    }
    messages = state["messages"].setdefault(str(frame.get("id") or ""), [])
    _mark_messages_stale_after_restart(messages, run_id=run_id, now=now)
    frame["message_count"] = len(messages)
    project = state["projects"].get(str(frame.get("project_id")))
    if project is not None:
        project["updated_at"] = now


def _mark_messages_stale_after_restart(messages: list[JsonObject], *, run_id: str, now: str) -> None:
    terminal_tool_ids = _terminal_tool_event_ids(messages, run_id)
    appended_error_for_unidentified_call = False
    for message in list(messages):
        if message.get("run_id") != run_id:
            continue
        if message.get("stream_status") in _ACTIVE_MESSAGE_STREAM_STATUSES:
            message["stream_status"] = STALE_AFTER_RESTART_STATUS
            message["updated_at"] = now
        event = message.get("event")
        if not isinstance(event, dict) or event.get("type") != "tool_call":
            continue
        ledger = event.get("ledger")
        if isinstance(ledger, dict) and ledger.get("status") == "running":
            ledger["status"] = STALE_AFTER_RESTART_STATUS
            ledger["summary"] = STALE_AFTER_RESTART_ERROR
        event_id = _tool_event_id(event)
        if event_id and event_id in terminal_tool_ids:
            continue
        if not event_id and appended_error_for_unidentified_call:
            continue
        stale_error = _message(
            "tool",
            event={
                "type": "error",
                "id": event_id,
                "name": event.get("name") or "tool",
                "message": STALE_AFTER_RESTART_ERROR,
            },
            run_id=run_id,
        )
        stale_error["created_at"] = now
        messages.append(stale_error)
        if event_id:
            terminal_tool_ids.add(event_id)
        else:
            appended_error_for_unidentified_call = True


def _terminal_tool_event_ids(messages: list[JsonObject], run_id: str) -> set[str]:
    ids: set[str] = set()
    for message in messages:
        if message.get("run_id") != run_id:
            continue
        event = message.get("event")
        if not isinstance(event, dict) or event.get("type") not in _TERMINAL_TOOL_EVENT_TYPES:
            continue
        event_id = _tool_event_id(event)
        if event_id:
            ids.add(event_id)
    return ids


def _tool_event_id(event: JsonObject) -> str:
    return str(event.get("id") or "").strip()


def _stale_run_status(frame: JsonObject, run_id: str) -> JsonObject:
    output_data = frame.get("output_data") if isinstance(frame.get("output_data"), dict) else {}
    status: JsonObject = {
        "id": run_id,
        "kind": "host_agent",
        "status": STALE_AFTER_RESTART_STATUS,
        "terminal": True,
        "createdAt": _iso_timestamp_ms(frame.get("created_at")),
        "updatedAt": _iso_timestamp_ms(frame.get("updated_at")),
        "error": portal_turns.prompt_safe_text(str(output_data.get("error") or STALE_AFTER_RESTART_ERROR)),
    }
    agent_id = frame.get("agent_id")
    if isinstance(agent_id, str) and agent_id:
        status["agentId"] = agent_id
    return status


def _persisted_run_status(frame: JsonObject, run_id: str) -> JsonObject:
    output_data = frame.get("output_data") if isinstance(frame.get("output_data"), dict) else {}
    frame_status = str(frame.get("status") or "").strip()
    run_status = _run_status_from_frame_status(frame_status)
    status: JsonObject = {
        "id": run_id,
        "kind": "host_agent",
        "status": run_status,
        "terminal": run_status != _PROCESSING_FRAME_STATUS,
        "createdAt": _iso_timestamp_ms(frame.get("created_at")),
        "updatedAt": _iso_timestamp_ms(frame.get("updated_at")),
        "error": portal_turns.prompt_safe_text(str(output_data.get("error") or "")) or None,
    }
    agent_id = frame.get("agent_id")
    if isinstance(agent_id, str) and agent_id:
        status["agentId"] = agent_id
    return status


def _run_status_from_frame_status(status: str) -> str:
    if status == "completed":
        return "succeeded"
    return status or "unknown"


def _iso_timestamp_ms(value: Any) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def _find_assistant_run_message(messages: list[JsonObject], run_id: str | None) -> JsonObject | None:
    if not run_id:
        return None
    for message in reversed(messages):
        if message.get("role") == "assistant" and message.get("run_id") == run_id:
            return message
    return None


def _notify_project_workspace_changed(
    target: JsonObject,
    changes: tuple[str, ...],
    *,
    reason: str,
    message_id: str = "",
    root: str | Path | None = None,
) -> None:
    project_id = str(target.get("project_id") or "")
    if not project_id:
        return
    project_reason = ""
    if "frame" in changes:
        portal_project_events.emit_project_event(
            project_id,
            "frame_changed",
            {"frame_id": target.get("id"), "reason": reason},
            root=root,
        )
        project_reason = "frame_" + reason
    if "messages" in changes:
        payload: JsonObject = {"frame_id": target.get("id"), "reason": reason}
        if message_id:
            payload["message_id"] = message_id
        portal_project_events.emit_project_event(project_id, "messages_changed", payload, root=root)
        if not project_reason and reason in _MESSAGE_PROJECT_REFRESH_REASONS:
            project_reason = "messages_" + reason
    if "artifacts" in changes:
        portal_project_events.emit_project_event(
            project_id,
            "artifacts_changed",
            {"artifact_id": target.get("id"), "reason": reason},
            root=root,
        )
        project_reason = "artifact_" + reason
    if project_reason:
        portal_project_events.emit_project_event(project_id, "project_changed", {"reason": project_reason}, root=root)


def _new_project(*, name: str) -> JsonObject:
    now = _now()
    project_id = f"proj_{uuid.uuid4().hex[:12]}"
    return {
        "project_id": project_id,
        "name": _clean_project_name(name),
        "workspace": portal_workspaces.project_workspace_metadata(project_id),
        "conversation_count": 0,
        "artifact_count": 0,
        "created_at": now,
        "updated_at": now,
    }


def _project_with_current_workspace_metadata(project: JsonObject) -> JsonObject:
    project_id = str(project.get("project_id") or "").strip()
    if not project_id:
        return dict(project)
    public_project = {
        key: value
        for key, value in project.items()
        if key not in _PRIVATE_PROJECT_KEYS
    }
    return {
        **public_project,
        "workspace": portal_workspaces.project_workspace_metadata(project_id),
    }


def _ensure_project_workspace(project: JsonObject | None, *, root: str | Path | None = None) -> None:
    if not isinstance(project, dict):
        return
    project_id = str(project.get("project_id") or "").strip()
    if not project_id:
        return
    portal_workspaces.ensure_project_workspace(project_id, root=root)


def _clean_project_name(value: str) -> str:
    safe = portal_turns.prompt_safe_text(str(value or "")).strip()
    if not safe:
        return DEFAULT_PROJECT_NAME
    return safe[:MAX_PROJECT_NAME_LENGTH].strip() or DEFAULT_PROJECT_NAME


def _clean_conversation_title(value: str) -> str:
    safe = " ".join(portal_turns.prompt_safe_text(str(value or "")).split())
    return safe[:MAX_CONVERSATION_TITLE_LENGTH].strip()


def _default_conversation_title(request: str, selected_evidence: list[JsonObject] | None = None) -> str:
    display = portal_turns.display_request_text(str(request or ""), selected_evidence)
    return _clean_conversation_title(display) or "New conversation"


def _default_artifact_summary(result: JsonObject) -> JsonObject:
    summary: JsonObject = {}
    for key in ("headline", "defaults_applied"):
        if result.get(key) is not None:
            summary[key] = result.get(key)
    return summary


def _safe_summary(value: JsonObject) -> JsonObject:
    safe = portal_turns.prompt_safe_value(value if isinstance(value, dict) else {})
    return safe if isinstance(safe, dict) else {}


def _clean_summary_lines(lines: list[str] | None, *, prompt_safe: bool = True) -> list[str]:
    if not lines:
        return []
    cleaned: list[str] = []
    for line in lines:
        text = str(line).strip()
        if not text:
            continue
        if prompt_safe:
            text = portal_turns.prompt_safe_text(text).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _clean_artifact_title(value: str) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()[:180]


def _clean_open_label(value: str | None, *, prompt_safe: bool = True) -> str:
    text = str(value or "Open result").strip() or "Open result"
    if prompt_safe:
        text = portal_turns.prompt_safe_text(text).strip()
    return text[:80] or "Open result"


def _default_artifact_summary_lines(result: JsonObject, operation: str, *, prompt_safe: bool = True) -> list[str]:
    lines: list[str] = []
    status = result.get("status")
    if status:
        lines.append(str(status))
    headline = result.get("headline")
    if isinstance(headline, str) and headline:
        lines.append(headline)
    if operation:
        lines.append(operation)
    if prompt_safe:
        lines = _clean_summary_lines(lines)
    return lines or ["Artifact ready"]


def _safe_external_artifact_url(value: str | None) -> str | None:
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.username or parsed.password:
        return None
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return None
    return raw


def _frame_summary(frame: JsonObject) -> JsonObject:
    input_data = frame.get("input_data")
    request = input_data.get("request") if isinstance(input_data, dict) else None
    safe_request = portal_turns.prompt_safe_text(request) if isinstance(request, str) else ""
    selected_evidence = portal_turns.clean_selected_evidence(
        input_data.get("selected_evidence") if isinstance(input_data, dict) else None
    )
    display_request = portal_turns.display_request_text(safe_request, selected_evidence)
    title = _clean_conversation_title(str(frame.get("title") or "")) or _default_conversation_title(
        safe_request,
        selected_evidence,
    )
    summary: JsonObject = {
        "id": frame.get("id"),
        "root_frame_id": frame.get("root_frame_id"),
        "project_id": frame.get("project_id"),
        "agent_id": frame.get("agent_id"),
        "run_id": frame.get("run_id"),
        "status": frame.get("status"),
        "request": safe_request,
        "display_request": display_request,
        "title": title,
        "message_count": frame.get("message_count") or 0,
        "created_at": frame.get("created_at"),
        "updated_at": frame.get("updated_at"),
        "completed_at": frame.get("completed_at"),
    }
    started_from = portal_turns.public_selected_material_handoff(
        input_data.get("started_from") if isinstance(input_data, dict) else None
    )
    if started_from:
        summary["started_from"] = started_from
    return summary


def _validated_source_frame_id(
    state: JsonObject,
    *,
    project_id: str,
    source_frame_id: str,
) -> str:
    if not source_frame_id:
        return ""
    source_frame = state["frames"].get(source_frame_id) if isinstance(state.get("frames"), dict) else None
    if not isinstance(source_frame, dict):
        return ""
    if source_frame.get("project_id") != project_id:
        return ""
    return source_frame_id


def _message(
    role: str,
    *,
    text: str | None = None,
    event: JsonObject | None = None,
    selected_evidence: list[JsonObject] | None = None,
    genome_context_mode: str | None = None,
    run_id: str | None = None,
) -> JsonObject:
    message: JsonObject = {
        "id": str(uuid.uuid4()),
        "role": role,
        "created_at": _now(),
    }
    if text is not None:
        message["text"] = text
    if run_id:
        message["run_id"] = portal_turns.prompt_safe_text(str(run_id))
    clean_genome_context_mode = _clean_genome_context_mode(genome_context_mode)
    message["genome_context_mode"] = clean_genome_context_mode
    if event is not None:
        message["event"] = portal_turns.history_tool_event(event) if role == "tool" else portal_turns.prompt_safe_value(event)
    clean_evidence = portal_turns.clean_selected_evidence(selected_evidence)
    if clean_evidence:
        message["selected_evidence"] = clean_evidence
    return message


def _clean_genome_context_mode(value: str | None) -> str:
    clean = str(value or "").strip().lower().replace("_", "-")
    return "public" if clean in {"public", "public-only", "public-sources"} else "auto"




def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
