from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from . import portal_turns
from ..runtime.paths import genomi_data_root

JsonObject = dict[str, Any]
PROJECT_EVENT_REPLAY_LIMIT = 512
_PROJECT_EVENT_DIR = "project-events"


@dataclass
class ProjectEvent:
    id: int
    event: str
    data: JsonObject
    timestamp: float


@dataclass
class ProjectEventLog:
    project_id: str
    data_root: Path
    events: deque[ProjectEvent] = field(default_factory=lambda: deque(maxlen=PROJECT_EVENT_REPLAY_LIMIT))
    next_event_id: int = 1
    condition: threading.Condition = field(default_factory=threading.Condition)

    def emit(self, event: str, data: JsonObject) -> None:
        with self.condition:
            record = ProjectEvent(self.next_event_id, event, _public_event_data(data), time.time())
            self.next_event_id += 1
            self.events.append(record)
            _append_event_record(self.project_id, record, self.events, root=self.data_root)
            self.condition.notify_all()


_PROJECTS: dict[tuple[str, str], ProjectEventLog] = {}
_PROJECTS_LOCK = threading.Lock()


def emit_project_event(
    project_id: str | None,
    event: str,
    data: JsonObject | None = None,
    *,
    root: str | Path | None = None,
) -> None:
    clean_project_id = str(project_id or "").strip()
    if not clean_project_id:
        return
    _event_log(clean_project_id, root=root).emit(event, {"project_id": clean_project_id, **(data or {})})


def discard_project_events(project_id: str, *, root: str | Path | None = None) -> None:
    clean_project_id = str(project_id or "").strip()
    if not clean_project_id:
        return
    key = _event_log_key(clean_project_id, root=root)
    with _PROJECTS_LOCK:
        _PROJECTS.pop(key, None)
    try:
        project_event_log_path(clean_project_id, root=root).unlink()
    except FileNotFoundError:
        return


def read_project_event_records(project_id: str, root: str | Path | None = None) -> list[JsonObject]:
    clean_project_id = str(project_id or "").strip()
    if not clean_project_id:
        return []
    log = _load_event_log(clean_project_id, root=root)
    return [_event_to_json(event) for event in log.events]


def stream_project_events(
    handler: BaseHTTPRequestHandler,
    project_id: str,
    query: str,
    *,
    root: str | Path | None = None,
) -> None:
    log = _event_log(project_id, root=root)
    last_event_id = _last_event_id(handler, query)
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "keep-alive")
    handler.close_connection = True
    handler.end_headers()
    try:
        _write_ready(handler, project_id)
    except (BrokenPipeError, ConnectionResetError):
        return
    while True:
        with log.condition:
            pending = [event for event in log.events if event.id > last_event_id]
            if not pending:
                log.condition.wait(timeout=15)
                pending = [event for event in log.events if event.id > last_event_id]
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


def _event_log(project_id: str, *, root: str | Path | None = None) -> ProjectEventLog:
    key = _event_log_key(project_id, root=root)
    with _PROJECTS_LOCK:
        log = _PROJECTS.get(key)
        if log is None:
            log = _load_event_log(project_id, root=root)
            _PROJECTS[key] = log
        return log


def _load_event_log(project_id: str, *, root: str | Path | None = None) -> ProjectEventLog:
    data_root = genomi_data_root(root)
    log = ProjectEventLog(project_id=project_id, data_root=data_root)
    path = project_event_log_path(project_id, root=data_root)
    if not path.is_file():
        return log
    max_id = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                record = _event_from_json(line)
                if record is None:
                    continue
                log.events.append(record)
                max_id = max(max_id, record.id)
    except OSError:
        return log
    log.next_event_id = max_id + 1 if max_id else 1
    return log


def _append_event_record(
    project_id: str,
    event: ProjectEvent,
    events: deque[ProjectEvent],
    *,
    root: str | Path | None = None,
) -> None:
    path = project_event_log_path(project_id, root=root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if event.id > PROJECT_EVENT_REPLAY_LIMIT and event.id % PROJECT_EVENT_REPLAY_LIMIT == 0:
            _rewrite_event_log(path, events)
            return
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_event_to_json(event), separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        return


def _rewrite_event_log(path: Path, events: deque[ProjectEvent]) -> None:
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(_event_to_json(event), separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _event_from_json(line: str) -> ProjectEvent | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        event_id = int(payload.get("id"))
        timestamp = float(payload.get("timestamp"))
    except (TypeError, ValueError):
        return None
    event = str(payload.get("event") or "").strip()
    data = payload.get("data")
    if event_id <= 0 or not event or not isinstance(data, dict):
        return None
    return ProjectEvent(
        id=event_id,
        event=event,
        data=_public_event_data(data),
        timestamp=timestamp,
    )


def _event_to_json(event: ProjectEvent) -> JsonObject:
    return {
        "id": event.id,
        "event": event.event,
        "data": event.data,
        "timestamp": event.timestamp,
    }


def project_event_log_path(project_id: str, root: str | Path | None = None) -> Path:
    safe_project_id = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in str(project_id or ""))
    if not safe_project_id:
        safe_project_id = "project"
    return genomi_data_root(root) / "portal" / _PROJECT_EVENT_DIR / f"{safe_project_id}.jsonl"


def _event_log_key(project_id: str, *, root: str | Path | None = None) -> tuple[str, str]:
    return (str(genomi_data_root(root)), project_id)


def _write_ready(handler: BaseHTTPRequestHandler, project_id: str) -> None:
    data = json.dumps({"project_id": portal_turns.prompt_safe_text(project_id)}, separators=(",", ":"))
    frame = f"event: ready\ndata: {data}\n\n"
    handler.wfile.write(frame.encode("utf-8"))
    handler.wfile.flush()


def _write_sse(handler: BaseHTTPRequestHandler, event: ProjectEvent) -> None:
    data = json.dumps(event.data, separators=(",", ":"))
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


def _public_event_data(data: JsonObject) -> JsonObject:
    return portal_turns.prompt_safe_value(data)
