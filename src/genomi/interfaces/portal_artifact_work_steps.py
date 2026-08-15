from __future__ import annotations

from typing import Any
from urllib.parse import quote

from . import portal_execution_cells, portal_turns

JsonObject = dict[str, Any]

WORK_STEP_KIND = "artifact_producing_work_step"


def producing_work_step(
    *,
    project_id: str,
    artifact_title: str,
    artifact_kind: str,
    renderer: str,
    operation: str,
    result: JsonObject,
    summary_lines: list[str],
    origin: JsonObject | None,
    created_at: str,
) -> JsonObject:
    status = _safe_text(result.get("status")) or "completed"
    public = {
        "kind": WORK_STEP_KIND,
        "title": "Produced artifact",
        "status": status,
        "summary": _summary(artifact_title, summary_lines, operation),
        "created_at": _safe_text(created_at),
        "artifact": {
            "title": _safe_text(artifact_title),
            "kind": _safe_text(artifact_kind),
        },
        "source": {
            "label": _source_label(origin),
            "operation": _safe_text(operation),
            "renderer": _safe_text(renderer),
        },
        "origin": _origin(origin),
        "workspace_route": _workspace_route(project_id, origin),
    }
    return public_producing_work_step(public) or {"kind": WORK_STEP_KIND, "title": "Produced artifact", "status": status}


def public_producing_work_step(value: Any) -> JsonObject | None:
    source = value if isinstance(value, dict) else {}
    if _safe_text(source.get("kind")) != WORK_STEP_KIND:
        return None
    public: JsonObject = {
        "kind": WORK_STEP_KIND,
        "title": _safe_text(source.get("title")) or "Produced artifact",
        "status": _safe_text(source.get("status")) or "completed",
        "summary": _safe_text(source.get("summary")),
        "created_at": _safe_text(source.get("created_at")),
        "artifact": _safe_object(source.get("artifact"), ("title", "kind")),
        "source": _safe_object(source.get("source"), ("label", "operation", "renderer")),
        "origin": _safe_object(source.get("origin"), ("frame_id", "run_id", "message_id")),
        "execution_cell": _safe_execution_cell(source.get("execution_cell")),
        "workspace_route": _safe_route(source.get("workspace_route")),
    }
    return _compact(public)


def with_execution_anchor(
    value: Any,
    *,
    project_id: str,
    frame_id: str,
    run_id: str,
    event_id: int,
) -> JsonObject | None:
    step = public_producing_work_step(value)
    if step is None:
        return None
    clean_run_id = _safe_text(run_id)
    clean_frame_id = _safe_text(frame_id) or _safe_text(step.get("origin", {}).get("frame_id") if isinstance(step.get("origin"), dict) else "")
    clean_project_id = _safe_text(project_id)
    safe_event_id = _safe_event_id(event_id)
    if not clean_run_id or not clean_frame_id or not clean_project_id or safe_event_id <= 0:
        return step
    cell_id = portal_execution_cells.artifact_event_cell_id(clean_run_id, safe_event_id)
    origin = dict(step.get("origin") if isinstance(step.get("origin"), dict) else {})
    origin["frame_id"] = clean_frame_id
    origin["run_id"] = clean_run_id
    step["origin"] = _compact(origin)
    step["execution_cell"] = {
        "id": cell_id,
        "kind": "artifact",
        "event_ids": [safe_event_id],
    }
    step["workspace_route"] = _workspace_route_with_step(clean_project_id, clean_frame_id, clean_run_id, cell_id)
    return public_producing_work_step(step)


def _summary(artifact_title: str, summary_lines: list[str], operation: str) -> str:
    title = _safe_text(artifact_title)
    for line in summary_lines:
        text = _safe_text(line)
        if text and text != title:
            return _clip(text, 220)
    if title:
        return _clip(f"{title} was created.", 220)
    op = _safe_text(operation)
    return _clip(f"Artifact created by {op}." if op else "Artifact created.", 220)


def _source_label(origin: JsonObject | None) -> str:
    clean_origin = origin if isinstance(origin, dict) else {}
    if _safe_text(clean_origin.get("producing_run_id")):
        return "Assistant run"
    if _safe_text(clean_origin.get("frame_id")):
        return "Origin conversation"
    return "GenomiLab workspace"


def _origin(origin: JsonObject | None) -> JsonObject:
    clean_origin = origin if isinstance(origin, dict) else {}
    return _compact(
        {
            "frame_id": _safe_text(clean_origin.get("frame_id")),
            "run_id": _safe_text(clean_origin.get("producing_run_id")),
            "message_id": _safe_text(clean_origin.get("producing_assistant_message_id")),
        }
    )


def _workspace_route(project_id: str, origin: JsonObject | None) -> str:
    clean_project_id = _safe_text(project_id)
    clean_origin = origin if isinstance(origin, dict) else {}
    frame_id = _safe_text(clean_origin.get("frame_id"))
    if not clean_project_id or not frame_id:
        return ""
    route = f"/projects/{quote(clean_project_id, safe='')}/frames/{quote(frame_id, safe='')}"
    run_id = _safe_text(clean_origin.get("producing_run_id"))
    if run_id:
        route += f"?highlight_run={quote(run_id, safe='')}"
    return route


def _safe_object(value: Any, keys: tuple[str, ...]) -> JsonObject:
    source = value if isinstance(value, dict) else {}
    return _compact({key: _safe_text(source.get(key)) for key in keys})


def _safe_route(value: Any) -> str:
    text = _safe_text(value)
    return text if text.startswith("/projects/") else ""


def _safe_execution_cell(value: Any) -> JsonObject:
    source = value if isinstance(value, dict) else {}
    cell_id = _safe_text(source.get("id"))
    kind = _safe_text(source.get("kind")) or "artifact"
    event_ids = [_safe_event_id(item) for item in source.get("event_ids", [])] if isinstance(source.get("event_ids"), list) else []
    public: JsonObject = {
        "id": cell_id,
        "kind": kind,
        "event_ids": [item for item in event_ids if item > 0],
    }
    return _compact(public)


def _safe_event_id(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_text(value: Any) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()


def _workspace_route_with_step(project_id: str, frame_id: str, run_id: str, cell_id: str) -> str:
    route = f"/projects/{quote(project_id, safe='')}/frames/{quote(frame_id, safe='')}"
    route += f"?highlight_run={quote(run_id, safe='')}"
    route += f"&highlight_step={quote(cell_id, safe='')}"
    return route


def _clip(value: str, limit: int) -> str:
    text = _safe_text(value)
    return text[:limit].rstrip()


def _compact(value: JsonObject) -> JsonObject:
    return {
        key: item
        for key, item in value.items()
        if item not in (None, "", [], {})
    }
