from __future__ import annotations

from pathlib import Path
from typing import Any

from . import portal_agents, portal_project_events, portal_state

JsonObject = dict[str, Any]
PROJECT_PERMISSION_KEY = "assistant_permissions"


def approved_tools(project_id: str | None, *, root: str | Path | None = None) -> list[str]:
    clean_project_id = str(project_id or "").strip()
    if not clean_project_id:
        return []
    project = portal_state.read_state(root)["projects"].get(clean_project_id)
    values = project.get(PROJECT_PERMISSION_KEY) if isinstance(project, dict) else None
    if not isinstance(values, list):
        return []
    approved: list[str] = []
    for value in values:
        tool = portal_agents.clean_approved_tool(value)
        if tool and tool not in approved:
            approved.append(tool)
    return approved


def allow_tool(project_id: str, tool: Any, *, root: str | Path | None = None) -> list[str] | None:
    clean_project_id = str(project_id or "").strip()
    clean_tool = portal_agents.clean_approved_tool(tool)
    if not clean_project_id or not clean_tool:
        return None

    def mutate(state: JsonObject) -> list[str] | None:
        project = state["projects"].get(clean_project_id)
        if not isinstance(project, dict):
            return None
        current = project.get(PROJECT_PERMISSION_KEY)
        values = list(current) if isinstance(current, list) else []
        if clean_tool not in values:
            values.append(clean_tool)
        project[PROJECT_PERMISSION_KEY] = values
        return values

    allowed = portal_state.mutate_state(mutate, root)
    if allowed is not None:
        portal_project_events.emit_project_event(
            clean_project_id,
            "project_changed",
            {"reason": "assistant_permission_changed"},
            root=root,
        )
    return allowed


def resolve_request(
    frame_id: str,
    *,
    run_id: str,
    tool: Any,
    root: str | Path | None = None,
) -> bool:
    clean_frame_id = str(frame_id or "").strip()
    clean_run_id = str(run_id or "").strip()
    clean_tool = portal_agents.clean_approved_tool(tool)
    if not clean_frame_id or not clean_run_id or not clean_tool:
        return False

    def mutate(state: JsonObject) -> JsonObject | None:
        frame = state["frames"].get(clean_frame_id)
        if not isinstance(frame, dict):
            return None
        for message in state["messages"].get(clean_frame_id, []):
            if not isinstance(message, dict) or message.get("role") != "tool" or message.get("run_id") != clean_run_id:
                continue
            event = message.get("event")
            permission = event.get("permission_request") if isinstance(event, dict) else None
            if not isinstance(permission, dict):
                continue
            if portal_agents.clean_approved_tool(permission.get("tool")) != clean_tool:
                continue
            permission["status"] = "allowed"
            permission["scope"] = "workspace"
            return frame
        return None

    frame = portal_state.mutate_state(mutate, root)
    if not isinstance(frame, dict):
        return False
    project_id = str(frame.get("project_id") or "").strip()
    if project_id:
        portal_project_events.emit_project_event(
            project_id,
            "messages_changed",
            {"frame_id": clean_frame_id, "reason": "permission_resolved"},
            root=root,
        )
    return True
