from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from . import portal_turns

JsonObject = dict[str, Any]

_TECHNICAL_TOOL_NAMES = {"bash", "skill", "toolsearch"}
_OPERATION_HEADLINE_RE = re.compile(r"^([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+):\s+")


def execution_cells_payload(records: list[JsonObject], *, run_id: str = "") -> JsonObject:
    cells = execution_cells_from_records(records, run_id=run_id)
    return {
        "schema": "genomi_portal_execution_cells",
        "run_id": portal_turns.prompt_safe_text(str(run_id or "")),
        "total": len(cells),
        "counts": _counts(cells),
        "items": cells,
    }


def execution_cells_from_records(records: list[JsonObject], *, run_id: str = "") -> list[JsonObject]:
    builders: list[_CellBuilder] = []
    by_tool_id: dict[str, _CellBuilder] = {}
    for record in records:
        event_name = portal_turns.prompt_safe_text(str(record.get("event") or "")).strip()
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        event_id = _event_id(record)
        project_id = portal_turns.prompt_safe_text(str(record.get("project_id") or "")).strip()
        frame_id = portal_turns.prompt_safe_text(str(record.get("frame_id") or "")).strip()

        if event_name == "agent":
            event_type = portal_turns.prompt_safe_text(str(data.get("type") or "")).strip()
            if event_type == "tool_call":
                tool_id = _tool_id(data, event_id)
                builder = _CellBuilder(
                    cell_id=_cell_id(run_id, "tool", tool_id),
                    kind="tool",
                    title=_operation_label(data),
                    operation=portal_turns.prompt_safe_text(str(data.get("name") or "")),
                    status="running",
                    project_id=project_id,
                    frame_id=frame_id,
                    visibility=_tool_visibility(data),
                )
                builder.add_record(record)
                builder.summary = _tool_call_summary(data)
                by_tool_id[tool_id] = builder
                builders.append(builder)
                continue
            if event_type in {"tool_result", "error"}:
                tool_id = _tool_id(data, event_id)
                builder = by_tool_id.get(tool_id)
                if builder is None:
                    builder = _CellBuilder(
                        cell_id=_cell_id(run_id, "tool", tool_id),
                        kind="tool",
                        title=_operation_label(data),
                        operation=portal_turns.prompt_safe_text(str(data.get("name") or "")),
                        status="running",
                        project_id=project_id,
                        frame_id=frame_id,
                        visibility=_tool_visibility(data),
                    )
                    by_tool_id[tool_id] = builder
                    builders.append(builder)
                builder.add_record(record)
                builder.status = "error" if event_type == "error" or data.get("isError") else "completed"
                builder.summary = _tool_result_summary(data)
                _promote_recovered_evidence_step(builder)
                continue
            if event_type == "diagnostic":
                builders.append(
                    _single_record_cell(
                        record,
                        run_id=run_id,
                        kind="diagnostic",
                        title=_diagnostic_title(data),
                        status="completed",
                        summary=_diagnostic_summary(data),
                        visibility="technical",
                    )
                )
                continue
            continue

        if event_name in {"stdout", "stderr"}:
            builders.append(
                _single_record_cell(
                    record,
                    run_id=run_id,
                    kind=event_name,
                    title=event_name.upper(),
                    status="completed",
                    summary=portal_turns.prompt_safe_text(str(data.get("chunk") or "")),
                    visibility="technical",
                )
            )
            continue
        if event_name in {"artifact", "artifact_error"}:
            builder = _single_record_cell(
                record,
                run_id=run_id,
                kind="artifact",
                title=_artifact_title(data, error=event_name == "artifact_error"),
                status="error" if event_name == "artifact_error" else "completed",
                summary=_artifact_summary(data),
            )
            builder.artifact = _artifact_reference(data)
            builders.append(builder)
            continue
        if event_name == "end":
            builders.append(
                _single_record_cell(
                    record,
                    run_id=run_id,
                    kind="run",
                    title="Run finished",
                    status=_status_from_end(data),
                    summary=_end_summary(data),
                )
            )
            continue
    return [builder.to_json(index) for index, builder in enumerate(builders, start=1)]


class _CellBuilder:
    def __init__(
        self,
        *,
        cell_id: str,
        kind: str,
        title: str,
        status: str,
        operation: str = "",
        project_id: str = "",
        frame_id: str = "",
        visibility: str = "user",
    ) -> None:
        self.cell_id = cell_id
        self.kind = kind
        self.title = title
        self.status = status
        self.operation = operation
        self.project_id = project_id
        self.frame_id = frame_id
        self.visibility = visibility if visibility in {"user", "technical"} else "user"
        self.summary = ""
        self.records: list[JsonObject] = []
        self.artifact: JsonObject | None = None

    def add_record(self, record: JsonObject) -> None:
        self.records.append(_public_record(record))
        if not self.project_id:
            self.project_id = portal_turns.prompt_safe_text(str(record.get("project_id") or "")).strip()
        if not self.frame_id:
            self.frame_id = portal_turns.prompt_safe_text(str(record.get("frame_id") or "")).strip()

    def to_json(self, ordinal: int) -> JsonObject:
        event_ids = [_event_id(record) for record in self.records]
        payload: JsonObject = {
            "id": self.cell_id,
            "ordinal": ordinal,
            "kind": self.kind,
            "title": portal_turns.prompt_safe_text(self.title),
            "status": portal_turns.prompt_safe_text(self.status),
            "operation": portal_turns.prompt_safe_text(self.operation),
            "summary": portal_turns.prompt_safe_text(self.summary),
            "event_ids": event_ids,
            "event_range": {
                "first": min(event_ids) if event_ids else None,
                "last": max(event_ids) if event_ids else None,
            },
            "project_id": self.project_id or None,
            "frame_id": self.frame_id or None,
            "records": self.records,
        }
        if self.visibility != "user":
            payload["visibility"] = self.visibility
        if self.artifact:
            payload["artifact"] = self.artifact
        return payload


def _single_record_cell(
    record: JsonObject,
    *,
    run_id: str,
    kind: str,
    title: str,
    status: str,
    summary: str = "",
    visibility: str = "user",
) -> _CellBuilder:
    event_id = _event_id(record)
    builder = _CellBuilder(
        cell_id=_cell_id(run_id, kind, str(event_id)),
        kind=kind,
        title=title,
        status=status,
        project_id=portal_turns.prompt_safe_text(str(record.get("project_id") or "")).strip(),
        frame_id=portal_turns.prompt_safe_text(str(record.get("frame_id") or "")).strip(),
        visibility=visibility,
    )
    builder.summary = summary
    builder.add_record(record)
    return builder


def _public_record(record: JsonObject) -> JsonObject:
    return {
        "id": _event_id(record),
        "event": portal_turns.prompt_safe_text(str(record.get("event") or "")),
        "timestamp": _timestamp(record),
        "data": portal_turns.prompt_safe_value(record.get("data") if isinstance(record.get("data"), dict) else {}),
    }


def _event_id(record: JsonObject) -> int:
    try:
        return int(record.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def _timestamp(record: JsonObject) -> int:
    try:
        return int(record.get("timestamp") or 0)
    except (TypeError, ValueError):
        return 0


def _tool_id(data: JsonObject, event_id: int) -> str:
    return portal_turns.prompt_safe_text(str(data.get("id") or data.get("call_id") or event_id)).strip() or str(event_id)


def _cell_id(run_id: str, kind: str, local_id: str) -> str:
    return execution_cell_id(run_id, kind, local_id)


def execution_cell_id(run_id: str, kind: str, local_id: str) -> str:
    parts = [
        portal_turns.prompt_safe_text(str(run_id or "")).strip() or "run",
        portal_turns.prompt_safe_text(kind).strip() or "cell",
        portal_turns.prompt_safe_text(str(local_id or "")).strip() or "event",
    ]
    return ":".join(parts)


def artifact_event_cell_id(run_id: str, event_id: int | str) -> str:
    return execution_cell_id(run_id, "artifact", str(event_id or "event"))


def _operation_label(data: JsonObject) -> str:
    name = portal_turns.prompt_safe_text(str(data.get("name") or "")).strip()
    return name or "Tool call"


def _tool_visibility(data: JsonObject) -> str:
    name = portal_turns.prompt_safe_text(str(data.get("name") or "")).strip().lower()
    if name.startswith("mcp__"):
        return "technical"
    return "technical" if name in _TECHNICAL_TOOL_NAMES else "user"


def _promote_recovered_evidence_step(builder: _CellBuilder) -> None:
    if builder.operation.strip().lower() != "bash":
        return
    match = _OPERATION_HEADLINE_RE.match(builder.summary.strip())
    if not match:
        return
    operation = match.group(1)
    builder.operation = operation
    builder.title = operation
    builder.visibility = "user"


def _tool_call_summary(data: JsonObject) -> str:
    name = _operation_label(data)
    input_value = data.get("input")
    if isinstance(input_value, dict):
        for key in ("rsid", "gene", "drug", "query", "topic", "source"):
            value = input_value.get(key)
            if isinstance(value, str) and value.strip():
                return f"{name}: {portal_turns.prompt_safe_text(value)}"
    return f"{name} started"


def _tool_result_summary(data: JsonObject) -> str:
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    headline = payload.get("headline")
    if isinstance(headline, str) and headline.strip():
        return portal_turns.prompt_safe_text(headline)[:360]
    for key in ("headline", "summary", "content", "message"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return portal_turns.prompt_safe_text(value)[:360]
    return "Tool result recorded"


def _diagnostic_title(data: JsonObject) -> str:
    name = portal_turns.prompt_safe_text(str(data.get("name") or "")).strip()
    return "Diagnostic" + (": " + name if name else "")


def _diagnostic_summary(data: JsonObject) -> str:
    name = portal_turns.prompt_safe_text(str(data.get("name") or "")).strip()
    if name == "spawn_agent":
        return "Assistant runtime started."
    if name == "host_agent_context_load":
        return "Focused guidance loaded for the assistant."
    return "Assistant diagnostic recorded."


def _artifact_summary(data: JsonObject) -> str:
    artifact = _artifact_object(data)
    title = (
        artifact.get("title")
        or data.get("title")
        or data.get("artifact_title")
        or artifact.get("id")
        or data.get("artifact_id")
        or ""
    )
    text = portal_turns.prompt_safe_text(str(title or "")).strip()
    return text or "Artifact event recorded"


def _artifact_title(data: JsonObject, *, error: bool = False) -> str:
    if error:
        return "Artifact error"
    return _artifact_summary(data) or "Artifact"


def _artifact_object(data: JsonObject) -> JsonObject:
    artifact = data.get("artifact") if isinstance(data.get("artifact"), dict) else {}
    return artifact


def _artifact_reference(data: JsonObject) -> JsonObject | None:
    artifact = _artifact_object(data)
    artifact_id = _first_public_text(artifact.get("id"), data.get("artifact_id"))
    project_id = _first_public_text(artifact.get("project_id"), data.get("project_id"))
    if not artifact_id and not project_id:
        return None
    version_id = _first_public_text(artifact.get("latest_version_id"), data.get("version_id"))
    route = _artifact_workspace_route(project_id, artifact_id, version_id)
    public = {
        "id": artifact_id or None,
        "project_id": project_id or None,
        "title": _first_public_text(artifact.get("title"), data.get("title"), data.get("artifact_title")) or None,
        "kind": _first_public_text(artifact.get("kind"), data.get("kind")) or None,
        "status": _first_public_text(artifact.get("status"), data.get("status")) or None,
        "latest_version_id": version_id or None,
        "version_count": artifact.get("version_count") if isinstance(artifact.get("version_count"), int) else None,
        "workspace_route": route or None,
    }
    return {key: value for key, value in public.items() if value not in (None, "")}


def _artifact_workspace_route(project_id: str, artifact_id: str, version_id: str) -> str:
    if not project_id or not artifact_id:
        return ""
    route = f"/projects/{quote(project_id, safe='')}/artifacts/{quote(artifact_id, safe='')}"
    if version_id:
        route += f"/versions/{quote(version_id, safe='')}"
    return route


def _first_public_text(*values: Any) -> str:
    for value in values:
        text = portal_turns.prompt_safe_text(str(value or "")).strip()
        if text:
            return text
    return ""


def _status_from_end(data: JsonObject) -> str:
    status = portal_turns.prompt_safe_text(str(data.get("status") or "")).strip()
    if not status:
        return "completed"
    return "error" if status in {"failed", "canceled", "stale_after_restart"} else status


def _end_summary(data: JsonObject) -> str:
    error = portal_turns.prompt_safe_text(str(data.get("error") or "")).strip()
    if error:
        return error
    status = portal_turns.prompt_safe_text(str(data.get("status") or "")).strip()
    return "Run finished" + (": " + status if status else "")


def _counts(cells: list[JsonObject]) -> JsonObject:
    counts: JsonObject = {"completed": 0, "running": 0, "errors": 0}
    for cell in cells:
        status = str(cell.get("status") or "").lower()
        if "error" in status or "fail" in status or "cancel" in status or "stale" in status:
            counts["errors"] += 1
        elif "running" in status or "queued" in status or "stream" in status:
            counts["running"] += 1
        else:
            counts["completed"] += 1
    return counts
