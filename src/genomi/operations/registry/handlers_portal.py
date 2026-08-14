from __future__ import annotations

from .coerce import _optional_int, _optional_str, _str
from .errors import JsonObject, OperationError


def _genomi_start_portal_run(params: JsonObject) -> JsonObject:
    from ...interfaces import portal_run_service, portal_store, portal_turns

    message = portal_turns.message_from_payload(params)
    if not message:
        raise OperationError("invalid_params", "message is required")
    agent_id = _runnable_agent_id_from_params(params)
    project_id = _optional_str(params, "project_id")
    if project_id:
        if portal_store.get_project(project_id) is None:
            raise OperationError("portal_project_not_found", f"portal project not found: {project_id}")
    else:
        project = portal_store.ensure_default_project()
        project_id = str(project["project_id"])
    selected_evidence = portal_turns.selected_evidence_from_payload(params)
    frame_id = _optional_str(params, "frame_id")
    if frame_id:
        response = portal_run_service.start_frame_message(
            frame_id=frame_id,
            project_id=project_id,
            message=message,
            agent_id=agent_id,
            selected_evidence=selected_evidence,
        )
        if response is None:
            raise OperationError("portal_frame_not_found", f"portal frame not found: {frame_id}")
        if response.get("status") == "busy":
            raise OperationError("portal_frame_busy", f"portal frame is already processing: {frame_id}")
        if response.get("status") == "wrong_project":
            raise OperationError("portal_frame_wrong_project", "portal frame does not belong to the supplied project")
    else:
        response = portal_run_service.start_project_request(
            project_id=project_id,
            message=message,
            agent_id=agent_id,
            selected_evidence=selected_evidence,
            started_from_selected_material=_optional_bool(params, "started_from_selected_material"),
            source_frame_id=_optional_str(params, "source_frame_id"),
        )
        if response is None:
            raise OperationError("portal_project_not_found", f"portal project not found: {project_id}")
    run_id = str(response.get("runId") or "")
    return _portal_run_control_payload(
        "genomi_portal_run_start",
        run_status=portal_run_service.get_run_status(run_id) if run_id else None,
        run_id=run_id,
        project_id=project_id,
        frame_id=str(response.get("frameId") or ""),
        root_frame_id=str(response.get("rootFrameId") or ""),
        agent_id=agent_id,
    )


def _genomi_check_portal_run(params: JsonObject) -> JsonObject:
    from ...interfaces import portal_run_service

    run_id = _required_run_id(params)
    status = portal_run_service.get_run_status(run_id)
    if status is None:
        raise OperationError("portal_run_not_found", f"portal run not found: {run_id}")
    return _portal_run_control_payload(
        "genomi_portal_run_status",
        run_status=status,
        run_id=run_id,
    )


def _optional_bool(params: JsonObject, key: str) -> bool:
    value = params.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in {"true", "1", "yes", "on"}:
            return True
        if clean in {"false", "0", "no", "off", ""}:
            return False
    return False


def _genomi_cancel_portal_run(params: JsonObject) -> JsonObject:
    from ...interfaces import portal_run_service

    run_id = _required_run_id(params)
    cancel = portal_run_service.cancel_run_by_id(run_id)
    if cancel.state == "missing":
        raise OperationError("portal_run_not_found", f"portal run not found: {run_id}")
    if cancel.state == "not_active":
        raise OperationError("portal_run_not_active", f"portal run is not active and cannot be canceled: {run_id}")
    if cancel.state == "terminal":
        raise OperationError("portal_run_terminal", f"portal run is already terminal and cannot be canceled: {run_id}")
    return _portal_run_control_payload(
        "genomi_portal_run_cancel",
        run_status=cancel.run_status,
        run_id=run_id,
    )


def _genomi_describe_portal_workspace(params: JsonObject) -> JsonObject:
    from ...interfaces import (
        portal_active_context,
        portal_state,
        portal_store,
        portal_workspace_files,
    )

    state = portal_state.read_state()
    project_id = _optional_str(params, "project_id") or _active_project_id(state)
    projects = _project_summaries(state)
    if not project_id:
        return {
            "schema": "genomi_portal_workspace_summary",
            "status": "empty",
            "active_project_id": None,
            "project": None,
            "projects": projects,
            "frames": {"project_id": None, "frames": []},
            "artifacts": {"project_id": None, "artifacts": []},
            "workspace_files": None,
            "active_context": None,
        }
    project = state["projects"].get(project_id)
    if not isinstance(project, dict):
        raise OperationError("portal_project_not_found", f"portal project not found: {project_id}")
    frames = portal_store.list_project_frames(project_id) or {"project_id": project_id, "frames": []}
    artifacts = portal_store.list_project_artifacts(project_id) or {"project_id": project_id, "artifacts": []}
    return {
        "schema": "genomi_portal_workspace_summary",
        "status": "available",
        "active_project_id": state.get("active_project_id"),
        "project": _public_project(project),
        "projects": projects,
        "frames": frames,
        "artifacts": artifacts,
        "workspace_files": portal_workspace_files.list_project_workspace_files(project_id),
        "active_context": portal_active_context.active_context_for_project(project_id),
    }


def _genomi_retrieve_portal_run_result_package(params: JsonObject) -> JsonObject:
    from ...interfaces import portal_run_packages, portal_turns

    run_id = portal_turns.prompt_safe_text(_str(params, "run_id", "")).strip()
    if not run_id:
        raise OperationError("invalid_params", "run_id is required")
    package = portal_run_packages.run_result_package(run_id)
    if package is None:
        raise OperationError("portal_run_not_found", f"portal run not found: {run_id}")
    return package


def _genomi_retrieve_portal_run_event_page(params: JsonObject) -> JsonObject:
    from ...interfaces import portal_run_event_pages

    run_id = _required_run_id(params)
    page = portal_run_event_pages.run_event_page(
        run_id,
        after_event_id=_optional_int(params, "after_event_id"),
        limit=_optional_int(params, "limit"),
    )
    if page is None:
        raise OperationError("portal_run_not_found", f"portal run not found: {run_id}")
    return page


def _runnable_agent_id_from_params(params: JsonObject) -> str:
    from ...interfaces import portal_agents

    requested = _optional_str(params, "agent_id")
    if requested:
        agents = {str(agent["id"]): agent for agent in portal_agents.detect_agents()}
        if agents.get(requested, {}).get("runnable"):
            return requested
        raise OperationError("no_agent_available", f"requested portal agent is not runnable: {requested}")
    agent_id = portal_agents.default_agent_id()
    if not agent_id:
        raise OperationError("no_agent_available", "No supported assistant CLI was found on PATH.")
    return agent_id


def _required_run_id(params: JsonObject) -> str:
    from ...interfaces import portal_turns

    run_id = portal_turns.prompt_safe_text(_str(params, "run_id", "")).strip()
    if not run_id:
        raise OperationError("invalid_params", "run_id is required")
    return run_id


def _portal_run_control_payload(
    schema: str,
    *,
    run_status: JsonObject | None,
    run_id: str,
    project_id: str | None = None,
    frame_id: str | None = None,
    root_frame_id: str | None = None,
    agent_id: str | None = None,
) -> JsonObject:
    run = run_status or {"id": run_id, "status": "unknown", "terminal": False}
    result: JsonObject = {
        "schema": schema,
        "status": str(run.get("status") or "unknown"),
        "terminal": bool(run.get("terminal")),
        "run_id": run_id,
        "run": run,
        "next_actions": _portal_run_next_actions(run_id, terminal=bool(run.get("terminal"))),
    }
    if isinstance(run.get("workspace"), dict):
        result["workspace"] = run["workspace"]
    if project_id:
        result["project_id"] = project_id
    if frame_id:
        result["frame_id"] = frame_id
    if root_frame_id:
        result["root_frame_id"] = root_frame_id
    if agent_id:
        result["agent_id"] = agent_id
    return result


def _portal_run_next_actions(run_id: str, *, terminal: bool) -> list[JsonObject]:
    actions: list[JsonObject] = []
    if not terminal:
        actions.append({"operation": "genomi.check_portal_run", "params": {"run_id": run_id}})
        actions.append({"operation": "genomi.cancel_portal_run", "params": {"run_id": run_id}})
    actions.append({"operation": "genomi.retrieve_portal_run_event_page", "params": {"run_id": run_id}})
    actions.append({"operation": "genomi.retrieve_portal_run_result_package", "params": {"run_id": run_id}})
    return actions


def _active_project_id(state: JsonObject) -> str:
    active_project_id = state.get("active_project_id")
    if isinstance(active_project_id, str) and active_project_id in state["projects"]:
        return active_project_id
    projects = _project_summaries(state)
    return str(projects[0].get("project_id") or "") if projects else ""


def _project_summaries(state: JsonObject) -> list[JsonObject]:
    projects = [
        _public_project(project)
        for project in state["projects"].values()
        if isinstance(project, dict)
    ]
    projects.sort(key=lambda project: str(project.get("updated_at") or ""), reverse=True)
    return projects


def _public_project(project: JsonObject) -> JsonObject:
    from ...interfaces import portal_turns, portal_workspaces

    public = {
        key: portal_turns.prompt_safe_value(project.get(key))
        for key in (
            "project_id",
            "name",
            "conversation_count",
            "artifact_count",
            "created_at",
            "updated_at",
        )
        if key in project
    }
    project_id = str(project.get("project_id") or "").strip()
    if project_id:
        public["workspace"] = portal_workspaces.project_workspace_metadata(project_id)
    return public
