from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs

from . import portal_run_failures, portal_run_logs, portal_turns, portal_workspaces

JsonObject = dict[str, Any]
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "canceled", "stale_after_restart", "awaiting_permission"}
_RUNS: dict[str, "PortalRun"] = {}
_RUNS_LOCK = threading.Lock()
_LOGGER = logging.getLogger(__name__)


@dataclass
class PortalEvent:
    id: int
    event: str
    data: JsonObject
    timestamp: float


@dataclass
class PortalRun:
    id: str
    kind: str
    message: str
    agent_id: str | None = None
    selected_evidence: list[JsonObject] = field(default_factory=list)
    conversation_history: list[JsonObject] = field(default_factory=list)
    approved_tools: list[str] = field(default_factory=list)
    genome_context_mode: str = "auto"
    active_context: JsonObject | None = None
    project_id: str | None = None
    frame_id: str | None = None
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[PortalEvent] = field(default_factory=list)
    next_event_id: int = 1
    condition: threading.Condition = field(default_factory=threading.Condition)
    process: subprocess.Popen[str] | None = None
    error: str | None = None
    output: str = ""
    durable_log_error: str | None = None

    def emit(self, event: str, data: JsonObject) -> PortalEvent:
        with self.condition:
            record = PortalEvent(self.next_event_id, event, data, time.time())
            self.next_event_id += 1
            self.events.append(record)
            self.updated_at = record.timestamp
            try:
                portal_run_logs.append_run_event(
                    self.id,
                    event_id=record.id,
                    event=record.event,
                    timestamp=record.timestamp,
                    data=public_event_data(record.event, record.data),
                    project_id=self.project_id,
                    frame_id=self.frame_id,
                )
            except Exception as exc:
                self.durable_log_error = f"{type(exc).__name__}: {portal_turns.prompt_safe_text(str(exc))}"
                _LOGGER.exception(
                    "Failed to append durable portal run event log for run %s event %s.",
                    self.id,
                    record.id,
                )
            self.condition.notify_all()
            return record

    def finish(self, status: str, *, error: str | None = None) -> None:
        """Close the run and report the outcome the conversation should show.

        A terminal error is provider machinery; the reader gets the classified
        sentence instead, and the raw payload stays in the work trail.
        """

        self.status = status
        self.updated_at = time.time()
        if error:
            self.error = error
        visible_error = error
        if error and str(status or "").strip().lower() in portal_run_failures.FAILED_RUN_STATUSES:
            visible_error = portal_run_failures.failure_message_text(error, status=status)
        self.emit("end", {"status": status, "error": visible_error})


def create_run(
    *,
    kind: str,
    message: str,
    agent_id: str | None = None,
    selected_evidence: list[JsonObject] | None = None,
    conversation_history: list[JsonObject] | None = None,
    approved_tools: list[str] | None = None,
    genome_context_mode: str | None = None,
    active_context: JsonObject | None = None,
    project_id: str | None = None,
    frame_id: str | None = None,
) -> PortalRun:
    run = PortalRun(
        id=uuid.uuid4().hex,
        kind=kind,
        agent_id=agent_id,
        message=message,
        selected_evidence=list(selected_evidence or []),
        conversation_history=list(conversation_history or []),
        approved_tools=list(approved_tools or []),
        genome_context_mode=_clean_genome_context_mode(genome_context_mode),
        active_context=dict(active_context) if isinstance(active_context, dict) else None,
        project_id=project_id,
        frame_id=frame_id,
    )
    with _RUNS_LOCK:
        _RUNS[run.id] = run
    data: JsonObject = {
        "status": "queued",
        "kind": kind,
        "workspace": portal_workspaces.run_workspace_metadata(project_id),
    }
    if agent_id:
        data["agentId"] = agent_id
    run.emit("status", data)
    return run


def _clean_genome_context_mode(value: str | None) -> str:
    clean = str(value or "").strip().lower().replace("_", "-")
    return "public" if clean in {"public", "public-only", "public_sources", "public-sources"} else "auto"


def get_run(run_id: str) -> PortalRun | None:
    with _RUNS_LOCK:
        return _RUNS.get(run_id)


def active_run_ids() -> set[str]:
    with _RUNS_LOCK:
        return {
            run_id
            for run_id, run in _RUNS.items()
            if run.status not in TERMINAL_RUN_STATUSES
        }


def known_run_ids() -> set[str]:
    with _RUNS_LOCK:
        return set(_RUNS)


def discard_run(run_id: str) -> None:
    with _RUNS_LOCK:
        _RUNS.pop(run_id, None)


def run_status(run: PortalRun) -> JsonObject:
    status: JsonObject = {
        "id": run.id,
        "kind": run.kind,
        "status": run.status,
        "terminal": run.status in TERMINAL_RUN_STATUSES,
        "createdAt": int(run.created_at * 1000),
        "updatedAt": int(run.updated_at * 1000),
        "error": portal_turns.prompt_safe_text(run.error or "") or None,
        "workspace": portal_workspaces.run_workspace_metadata(run.project_id),
    }
    if run.agent_id:
        status["agentId"] = run.agent_id
    return status


def public_event_data(event: str, data: JsonObject) -> JsonObject:
    if event == "agent":
        event_type = str(data.get("type") or "")
        if event_type in {"tool_call", "tool_result", "error"}:
            return portal_turns.live_tool_event(data)
        if event_type == "text_delta":
            return {"type": "text_delta", "delta": portal_turns.prompt_safe_text(str(data.get("delta") or ""))}
        if event_type == "diagnostic":
            result: JsonObject = {
                "type": "diagnostic",
                "name": portal_turns.prompt_safe_text(str(data.get("name") or "")),
            }
            if data.get("message"):
                result["message"] = portal_turns.prompt_safe_text(str(data.get("message") or ""))
            if data.get("agentId"):
                result["agentId"] = portal_turns.prompt_safe_text(str(data.get("agentId") or ""))
            return result
    if event in {"stdout", "stderr"}:
        return {"chunk": portal_turns.prompt_safe_text(str(data.get("chunk") or ""))}
    if event in {"start", "status", "end", "artifact", "artifact_error"}:
        return portal_turns.prompt_safe_value(data)
    return portal_turns.prompt_safe_value(data)


def stream_run_events(handler: BaseHTTPRequestHandler, run_id: str, query: str) -> None:
    run = get_run(run_id)
    if run is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "run not found"}})
        return
    last_event_id = _last_event_id(handler, query)
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()
    while True:
        with run.condition:
            pending = [event for event in run.events if event.id > last_event_id]
            if not pending and run.status not in TERMINAL_RUN_STATUSES:
                run.condition.wait(timeout=15)
                pending = [event for event in run.events if event.id > last_event_id]
            if not pending and run.status in TERMINAL_RUN_STATUSES:
                return
        try:
            if not pending:
                handler.wfile.write(b": keepalive\n\n")
                handler.wfile.flush()
                continue
            for event in pending:
                _write_sse(handler, event)
                last_event_id = event.id
        except (BrokenPipeError, ConnectionResetError):
            return


def stream_terminal_run_status(
    handler: BaseHTTPRequestHandler,
    status: JsonObject,
    query: str,
    *,
    root: str | None = None,
) -> None:
    last_event_id = _last_event_id(handler, query)
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()
    try:
        records = portal_run_logs.read_run_event_records(str(status.get("id") or ""), root=root)
        max_logged_id = 0
        has_logged_terminal = False
        for record in records:
            max_logged_id = max(max_logged_id, int(record["id"]))
            if record.get("event") == "end":
                has_logged_terminal = True
            if int(record["id"]) > last_event_id:
                _write_sse(handler, _event_from_durable_record(record))
        if has_logged_terminal:
            return
        synthetic_id = max_logged_id + 1 if max_logged_id else 1
        if synthetic_id <= last_event_id:
            return
        error = status.get("error")
        _write_sse(
            handler,
            PortalEvent(
                id=synthetic_id,
                event="end",
                data={
                    "status": status.get("status"),
                    "error": portal_turns.prompt_safe_text(str(error)) if error else None,
                },
                timestamp=time.time(),
            ),
        )
    except (BrokenPipeError, ConnectionResetError):
        return


def _event_from_durable_record(record: JsonObject) -> PortalEvent:
    timestamp = 0.0
    try:
        timestamp = int(record.get("timestamp") or 0) / 1000
    except (TypeError, ValueError):
        timestamp = 0.0
    return PortalEvent(
        id=int(record["id"]),
        event=str(record["event"]),
        data=record.get("data") if isinstance(record.get("data"), dict) else {},
        timestamp=timestamp,
    )


def _write_sse(handler: BaseHTTPRequestHandler, event: PortalEvent) -> None:
    data = json.dumps(public_event_data(event.event, event.data), separators=(",", ":"))
    frame = f"id: {event.id}\nevent: {event.event}\ndata: {data}\n\n"
    handler.wfile.write(frame.encode("utf-8"))
    handler.wfile.flush()


def _last_event_id(handler: BaseHTTPRequestHandler, query: str) -> int:
    raw = handler.headers.get("Last-Event-ID") or _single_query_value(query, "after") or "0"
    try:
        return int(raw)
    except ValueError:
        return 0


def _single_query_value(query: str, key: str) -> str | None:
    values = parse_qs(query).get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)
