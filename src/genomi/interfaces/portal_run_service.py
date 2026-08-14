from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from . import (
    portal_active_context,
    portal_agents,
    portal_project_permissions,
    portal_run_events,
    portal_run_logs,
    portal_runs,
    portal_store,
)

JsonObject = dict[str, Any]
PortalRunCancelState = Literal["active", "missing", "not_active", "terminal"]


@dataclass(frozen=True)
class PortalRunCancelResult:
    state: PortalRunCancelState
    run_id: str
    run_status: JsonObject | None = None


def reconcile_stale_persisted_runs(
    run_id: str | None = None,
    *,
    root: str | Path | None = None,
) -> list[JsonObject]:
    frame_runs = portal_store.reconcile_stale_processing_runs(
        known_run_ids=portal_run_events.active_run_ids(),
        run_id=run_id,
        root=root,
    )
    review_runs = portal_store.reconcile_stale_conversation_reviews(
        known_run_ids=portal_run_events.active_run_ids(),
        run_id=run_id,
        root=root,
    )
    return [*frame_runs, *review_runs]


def get_run_status(run_id: str, *, root: str | Path | None = None) -> JsonObject | None:
    run = portal_run_events.get_run(run_id)
    if run is not None:
        return portal_run_events.run_status(run)
    reconcile_stale_persisted_runs(run_id=run_id, root=root)
    return portal_store.persisted_run_status(run_id, root=root)


def cancel_run_by_id(run_id: str, *, root: str | Path | None = None) -> PortalRunCancelResult:
    clean_run_id = str(run_id or "").strip()
    run = portal_run_events.get_run(clean_run_id)
    if run is not None:
        if run.status in portal_run_events.TERMINAL_RUN_STATUSES:
            return PortalRunCancelResult("terminal", clean_run_id, portal_run_events.run_status(run))
        portal_runs.cancel_run(run)
        return PortalRunCancelResult("active", clean_run_id, portal_run_events.run_status(run))

    status = get_run_status(clean_run_id, root=root)
    if status is None:
        return PortalRunCancelResult("missing", clean_run_id)
    if bool(status.get("terminal")):
        return PortalRunCancelResult("terminal", clean_run_id, status)
    return PortalRunCancelResult("not_active", clean_run_id, status)


def start_project_request(
    *,
    project_id: str,
    message: str,
    agent_id: str,
    selected_evidence: list[JsonObject] | None = None,
    genome_context_mode: str | None = None,
    started_from_selected_material: bool = False,
    source_frame_id: str | None = None,
) -> JsonObject | None:
    frame = portal_store.create_frame(
        project_id=project_id,
        request=message,
        agent_id=agent_id,
        selected_evidence=selected_evidence,
        genome_context_mode=genome_context_mode,
        started_from_selected_material=started_from_selected_material,
        source_frame_id=source_frame_id,
    )
    if frame is None:
        return None
    run = portal_run_events.create_run(
        kind="host_agent",
        agent_id=agent_id,
        message=message,
        selected_evidence=selected_evidence,
        genome_context_mode=_clean_genome_context_mode(genome_context_mode),
        conversation_history=[],
        active_context=portal_active_context.active_context_for_project(project_id),
        approved_tools=portal_project_permissions.approved_tools(project_id),
        project_id=project_id,
        frame_id=str(frame["id"]),
    )
    try:
        attached = portal_store.attach_run(str(frame["id"]), run_id=run.id, agent_id=agent_id)
    except Exception as exc:
        _terminalize_unstarted_run(run, f"Assistant run could not be attached: {exc}")
        return {"runId": run.id, "frameId": frame["id"], "rootFrameId": frame["root_frame_id"], "status": run.status}
    if attached is None:
        _terminalize_unstarted_run(run, "Assistant run could not be attached to the conversation.")
        return {"runId": run.id, "frameId": frame["id"], "rootFrameId": frame["root_frame_id"], "status": run.status}
    try:
        _start_run_thread(run)
    except Exception as exc:
        _terminalize_unstarted_run(run, f"Assistant run could not be started: {exc}")
    return {"runId": run.id, "frameId": frame["id"], "rootFrameId": frame["root_frame_id"], "status": run.status}


def start_frame_message(
    *,
    frame_id: str,
    project_id: str,
    message: str,
    agent_id: str,
    selected_evidence: list[JsonObject] | None = None,
    genome_context_mode: str | None = None,
) -> JsonObject | None:
    frame = portal_store.get_frame(frame_id)
    if frame is None:
        return None
    if frame.get("project_id") != project_id:
        return {"status": "wrong_project"}
    previous_run_id = str(frame.get("run_id") or "")
    if frame.get("status") == "processing" and previous_run_id:
        reconcile_stale_persisted_runs(run_id=previous_run_id)
        frame = portal_store.get_frame(frame_id)
        if frame is None:
            return None
    if frame.get("status") == "processing":
        return {"status": "busy"}
    conversation_history = portal_store.frame_conversation_history(frame_id)

    run = portal_run_events.create_run(
        kind="host_agent",
        agent_id=agent_id,
        message=message,
        selected_evidence=selected_evidence,
        genome_context_mode=_clean_genome_context_mode(genome_context_mode),
        conversation_history=conversation_history,
        active_context=portal_active_context.active_context_for_project(project_id),
        approved_tools=portal_project_permissions.approved_tools(project_id),
        project_id=project_id,
        frame_id=frame_id,
    )
    started = portal_store.begin_frame_message(
        frame_id,
        text=message,
        selected_evidence=selected_evidence,
        genome_context_mode=genome_context_mode,
        agent_id=agent_id,
        run_id=run.id,
        project_id=project_id,
    )
    if started is None:
        _discard_rejected_run(run)
        return None
    if started.get("status") in {"busy", "wrong_project"}:
        _discard_rejected_run(run)
        return {"status": started.get("status")}
    persisted_frame = started.get("frame") if isinstance(started.get("frame"), dict) else {}
    run.project_id = str(persisted_frame.get("project_id") or "")
    _start_run_thread(run)
    return {"runId": run.id, "frameId": frame_id, "rootFrameId": persisted_frame.get("root_frame_id") or frame_id, "status": run.status}


def start_frame_review(
    *,
    frame_id: str,
    project_id: str,
    agent_id: str | None = None,
) -> JsonObject | None:
    frame = portal_store.get_frame_for_project(frame_id, project_id)
    if frame is None:
        return None
    if frame.get("status") == "processing":
        return {"status": "busy"}
    source_messages = portal_store.frame_review_source_messages(frame_id)
    if not any(item.get("role") == "assistant" for item in source_messages):
        return {"status": "no_answer"}
    reviewer_agent_id = str(agent_id or frame.get("agent_id") or portal_agents.default_agent_id() or "").strip()
    if not reviewer_agent_id:
        return {"status": "unavailable"}
    run = portal_run_events.create_run(
        kind="conversation_review",
        agent_id=reviewer_agent_id,
        message="Review this conversation.",
        conversation_history=source_messages,
        genome_context_mode="public",
        active_context=None,
        project_id=project_id,
        frame_id=frame_id,
    )
    pending = portal_store.begin_frame_review(
        frame_id,
        project_id=project_id,
        review_run_id=run.id,
        source_message_ids=[str(item.get("message_id") or "") for item in source_messages],
    )
    if pending is None:
        _discard_rejected_run(run)
        return None
    if pending.get("status") == "busy":
        _discard_rejected_run(run)
        return {"status": "busy"}
    _start_run_thread(run)
    return {
        "runId": run.id,
        "frameId": frame_id,
        "rootFrameId": frame.get("root_frame_id") or frame_id,
        "status": run.status,
        "review": pending,
    }


def approve_run_permission_and_retry(
    *,
    run_id: str,
    permission: Any,
    root: str | Path | None = None,
) -> JsonObject:
    clean_run_id = str(run_id or "").strip()
    approved_tool = _approved_tool_from_permission(permission)
    if not clean_run_id or not approved_tool:
        return {"status": "bad_request", "message": "Permission approval requires a valid requested tool."}
    source_run = portal_run_events.get_run(clean_run_id)
    if source_run is not None and source_run.status not in portal_run_events.TERMINAL_RUN_STATUSES:
        if not _run_requested_tool(source_run, approved_tool):
            return {"status": "busy", "message": "The assistant is still working."}
        portal_runs.pause_run_for_permission(source_run)
    frame = portal_store.get_frame_by_run_id(clean_run_id, root=root)
    if frame is None:
        return {"status": "missing", "message": "Run not found."}
    frame_id = str(frame.get("id") or "")
    project_id = str(frame.get("project_id") or "")
    if not frame_id or not project_id:
        return {"status": "missing", "message": "Run frame is unavailable."}
    if frame.get("status") == "processing":
        return {"status": "busy", "message": "The conversation is already processing."}
    input_data = frame.get("input_data") if isinstance(frame.get("input_data"), dict) else {}
    message = str(input_data.get("request") or "").strip()
    if not message:
        return {"status": "bad_request", "message": "Original request is unavailable."}
    agent_id = str((source_run and source_run.agent_id) or frame.get("agent_id") or "").strip()
    if not agent_id:
        return {"status": "bad_request", "message": "Original assistant runtime is unavailable."}
    if portal_project_permissions.allow_tool(project_id, approved_tool, root=root) is None:
        return {"status": "missing", "message": "Workspace is unavailable."}
    portal_project_permissions.resolve_request(
        frame_id,
        run_id=clean_run_id,
        tool=approved_tool,
        root=root,
    )
    selected_evidence = _retry_selected_evidence(source_run, input_data)
    genome_context_mode = _retry_genome_context_mode(source_run, input_data)
    approved_tools = _approved_tools_for_retry(
        source_run,
        approved_tool,
        project_id=project_id,
        root=root,
    )
    run = portal_run_events.create_run(
        kind="host_agent",
        agent_id=agent_id,
        message=message,
        selected_evidence=selected_evidence,
        genome_context_mode=genome_context_mode,
        conversation_history=_retry_conversation_history(source_run, frame_id, message, root=root),
        approved_tools=approved_tools,
        active_context=portal_active_context.active_context_for_project(project_id),
        project_id=project_id,
        frame_id=frame_id,
    )
    attached = portal_store.attach_run(frame_id, run_id=run.id, agent_id=agent_id, root=root)
    if attached is None:
        _discard_rejected_run(run)
        return {"status": "missing", "message": "Conversation is unavailable."}
    _start_run_thread(run)
    return {
        "status": run.status,
        "runId": run.id,
        "frameId": frame_id,
        "rootFrameId": frame.get("root_frame_id") or frame_id,
        "approvedTool": approved_tool,
    }


def _start_run_thread(run: portal_run_events.PortalRun) -> None:
    threading.Thread(target=portal_runs.run_agent, args=(run,), name=f"genomi-portal-run-{run.id}", daemon=True).start()


def _discard_rejected_run(run: portal_run_events.PortalRun) -> None:
    portal_run_events.discard_run(run.id)
    portal_run_logs.discard_run_log(run.id)


def _terminalize_unstarted_run(run: portal_run_events.PortalRun, error: str) -> None:
    run.finish("failed", error=error)
    portal_store.finish_frame(
        str(run.frame_id or ""),
        status="failed",
        error=error,
        run_id=run.id,
    )


def _approved_tool_from_permission(permission: Any) -> str:
    if isinstance(permission, dict):
        return portal_agents.clean_approved_tool(permission.get("tool") or permission.get("name") or permission.get("value"))
    return portal_agents.clean_approved_tool(permission)


def _approved_tools_for_retry(
    source_run: portal_run_events.PortalRun | None,
    approved_tool: str,
    *,
    project_id: str | None = None,
    root: str | Path | None = None,
) -> list[str]:
    permission_project_id = project_id or (source_run.project_id if source_run is not None else None)
    values = portal_project_permissions.approved_tools(permission_project_id, root=root)
    for tool in source_run.approved_tools if source_run is not None else []:
        if tool not in values:
            values.append(tool)
    if approved_tool not in values:
        values.append(approved_tool)
    return values


def _run_requested_tool(run: portal_run_events.PortalRun, tool: str) -> bool:
    for event in run.events:
        if event.event != "agent":
            continue
        permission = event.data.get("permission_request")
        if isinstance(permission, dict) and portal_agents.clean_approved_tool(permission.get("tool")) == tool:
            return True
    return False


def _retry_selected_evidence(source_run: portal_run_events.PortalRun | None, input_data: JsonObject) -> list[JsonObject]:
    if source_run is not None:
        return list(source_run.selected_evidence)
    selected_evidence = input_data.get("selected_evidence")
    return list(selected_evidence) if isinstance(selected_evidence, list) else []


def _retry_genome_context_mode(source_run: portal_run_events.PortalRun | None, input_data: JsonObject) -> str:
    if source_run is not None:
        return _clean_genome_context_mode(source_run.genome_context_mode)
    return _clean_genome_context_mode(input_data.get("genome_context_mode") if isinstance(input_data, dict) else None)


def _clean_genome_context_mode(value: Any) -> str:
    clean = str(value or "").strip().lower().replace("_", "-")
    return "public" if clean in {"public", "public-only", "public-sources"} else "auto"


def _retry_conversation_history(
    source_run: portal_run_events.PortalRun | None,
    frame_id: str,
    current_request: str,
    *,
    root: str | Path | None = None,
) -> list[JsonObject]:
    if source_run is not None:
        return list(source_run.conversation_history)
    history = portal_store.frame_conversation_history(frame_id, root=root)
    if history and history[-1].get("role") == "user" and history[-1].get("text") == current_request:
        return history[:-1]
    return history
