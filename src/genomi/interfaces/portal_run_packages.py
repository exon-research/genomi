from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import (
    portal_active_context,
    portal_context,
    portal_execution_cells,
    portal_frame_exports,
    portal_run_events,
    portal_run_logs,
    portal_run_service,
    portal_state,
    portal_store,
    portal_turns,
    portal_workspace_files,
)

JsonObject = dict[str, Any]
RUN_EVENT_LIMIT = 200


def run_result_package(run_id: str, root: str | Path | None = None) -> JsonObject | None:
    clean_run_id = portal_turns.prompt_safe_text(str(run_id or "")).strip()
    if not clean_run_id:
        return None
    run_status = portal_run_service.get_run_status(clean_run_id, root=root)
    if run_status is None:
        return None
    run = portal_run_events.get_run(clean_run_id)
    state = portal_state.read_state(root)
    frame = _frame_for_run(state, clean_run_id, run_frame_id=str(run.frame_id or "") if run else "")
    project_id = _project_id_for_run(run, frame)
    project = _public_project(state, project_id)
    frame_id = str(frame.get("id") or "") if isinstance(frame, dict) else ""
    events = _run_events_payload(clean_run_id, run, root=root)
    return {
        "schema": "genomi_portal_run_result_package",
        "exported_at": _now(),
        "run": run_status,
        "project": project,
        "frame": portal_store.public_frame(frame) if isinstance(frame, dict) else None,
        "messages": _messages_payload(frame_id, root=root),
        "artifacts": _artifacts_payload(project_id, frame_id, root=root),
        "workspace_files": _workspace_files_payload(project_id, root=root),
        "events": events,
        "execution_cells": portal_execution_cells.execution_cells_payload(
            list(events.get("items") or []),
            run_id=clean_run_id,
        ),
        "genome_context": portal_context.prompt_context_payload(),
        "active_context": portal_active_context.active_context_for_project(project_id),
    }


def _frame_for_run(state: JsonObject, run_id: str, *, run_frame_id: str = "") -> JsonObject | None:
    if run_frame_id:
        frame = state["frames"].get(run_frame_id)
        if isinstance(frame, dict):
            return frame
    for frame in state["frames"].values():
        if not isinstance(frame, dict):
            continue
        if str(frame.get("run_id") or "") == run_id:
            return frame
        output = frame.get("output_data") if isinstance(frame.get("output_data"), dict) else {}
        if str(output.get("stale_run_id") or "") == run_id:
            return frame
    return None


def _project_id_for_run(run: portal_run_events.PortalRun | None, frame: JsonObject | None) -> str:
    if run and run.project_id:
        return portal_turns.prompt_safe_text(str(run.project_id)).strip()
    if isinstance(frame, dict):
        return portal_turns.prompt_safe_text(str(frame.get("project_id") or "")).strip()
    return ""


def _public_project(state: JsonObject, project_id: str) -> JsonObject | None:
    project = state["projects"].get(project_id)
    if not isinstance(project, dict):
        return None
    return {
        key: portal_turns.prompt_safe_value(project.get(key))
        for key in (
            "project_id",
            "name",
            "workspace",
            "conversation_count",
            "artifact_count",
            "created_at",
            "updated_at",
        )
        if key in project
    }


def _messages_payload(frame_id: str, root: str | Path | None = None) -> JsonObject:
    if not frame_id:
        return {"frame_id": None, "total": 0, "messages": []}
    payload = portal_store.list_frame_messages(frame_id, root=root)
    if payload is None:
        return {"frame_id": frame_id, "total": 0, "messages": []}
    return payload


def _artifacts_payload(project_id: str, frame_id: str, root: str | Path | None = None) -> JsonObject:
    if not project_id or not frame_id:
        return {"project_id": project_id or None, "frame_id": frame_id or None, "count": 0, "items": []}
    source = portal_frame_exports.project_frame_bundle_source(project_id, frame_id, root=root)
    if source is None:
        return {"project_id": project_id, "frame_id": frame_id, "count": 0, "items": []}
    items = [
        artifact_source.bundle_source.metadata
        for artifact_source in source.artifacts
        if isinstance(artifact_source.bundle_source.metadata, dict)
    ]
    return {
        "project_id": project_id,
        "frame_id": frame_id,
        "count": len(items),
        "items": items,
    }


def _workspace_files_payload(project_id: str, root: str | Path | None = None) -> JsonObject | None:
    if not project_id:
        return None
    return portal_workspace_files.list_project_workspace_files(project_id, root=root)


def _run_events_payload(
    run_id: str,
    run: portal_run_events.PortalRun | None,
    *,
    root: str | Path | None = None,
) -> JsonObject:
    logged = portal_run_logs.run_events_payload(run_id, limit=RUN_EVENT_LIMIT, root=root)
    if logged.get("available"):
        return logged
    if run is not None:
        return _memory_run_events_payload(run)
    return _empty_run_events_payload(RUN_EVENT_LIMIT)


def _memory_run_events_payload(run: portal_run_events.PortalRun) -> JsonObject:
    events = run.events[-RUN_EVENT_LIMIT:]
    return {
        "available": True,
        "source": "memory",
        "limit": RUN_EVENT_LIMIT,
        "truncated": len(run.events) > len(events),
        "total": len(run.events),
        "items": [
            {
                "id": event.id,
                "event": event.event,
                "timestamp": int(event.timestamp * 1000),
                "data": portal_run_events.public_event_data(event.event, event.data),
            }
            for event in events
        ],
    }


def _empty_run_events_payload(limit: int) -> JsonObject:
    return {
        "available": False,
        "source": "none",
        "limit": max(0, int(limit)),
        "truncated": False,
        "total": 0,
        "items": [],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
