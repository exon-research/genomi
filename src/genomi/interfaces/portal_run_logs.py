from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from ..runtime.paths import genomi_data_root
from . import portal_turns

JsonObject = dict[str, Any]
RUN_EVENT_REPLAY_LIMIT = 200
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_LOCK = threading.RLock()


def append_run_event(
    run_id: str,
    *,
    event_id: int,
    event: str,
    timestamp: float,
    data: JsonObject,
    project_id: str | None = None,
    frame_id: str | None = None,
    root: str | Path | None = None,
) -> None:
    clean_run_id = _clean_run_id(run_id)
    if not clean_run_id:
        return
    record: JsonObject = {
        "id": int(event_id),
        "event": portal_turns.prompt_safe_text(str(event or "")) or "message",
        "timestamp": int(float(timestamp) * 1000),
        "data": portal_turns.prompt_safe_value(data),
    }
    clean_project_id = _clean_id(project_id or "")
    clean_frame_id = _clean_id(frame_id or "")
    if clean_project_id:
        record["project_id"] = clean_project_id
    if clean_frame_id:
        record["frame_id"] = clean_frame_id
    line = json.dumps(record, separators=(",", ":"), sort_keys=True)
    path = run_event_log_path(clean_run_id, root=root)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())


def run_events_payload(
    run_id: str,
    *,
    limit: int = RUN_EVENT_REPLAY_LIMIT,
    root: str | Path | None = None,
) -> JsonObject:
    safe_limit = max(0, int(limit))
    clean_run_id = _clean_run_id(run_id)
    if not clean_run_id:
        return _events_payload([], source="none", limit=safe_limit, available=False)
    records = read_run_event_records(clean_run_id, root=root)
    if not records:
        return _events_payload([], source="none", limit=safe_limit, available=False)
    return _events_payload(records, source="durable_log", limit=safe_limit, available=True)


def read_run_event_records(run_id: str, root: str | Path | None = None) -> list[JsonObject]:
    clean_run_id = _clean_run_id(run_id)
    if not clean_run_id:
        return []
    return _read_records(clean_run_id, root=root)


def _events_payload(records: list[JsonObject], *, source: str, limit: int, available: bool) -> JsonObject:
    safe_limit = max(0, int(limit))
    events = records[-safe_limit:] if safe_limit else []
    return {
        "available": available,
        "source": source,
        "limit": safe_limit,
        "truncated": len(records) > len(events),
        "total": len(records),
        "items": events,
    }


def discard_run_log(run_id: str, root: str | Path | None = None) -> None:
    clean_run_id = _clean_run_id(run_id)
    if not clean_run_id:
        return
    try:
        run_event_log_path(clean_run_id, root=root).unlink()
    except FileNotFoundError:
        return


def run_event_log_path(run_id: str, root: str | Path | None = None) -> Path:
    clean_run_id = _clean_run_id(run_id)
    if not clean_run_id:
        raise ValueError("unsafe portal run id")
    return genomi_data_root(root) / "portal" / "run-events" / f"{clean_run_id}.jsonl"


def _read_records(run_id: str, root: str | Path | None = None) -> list[JsonObject]:
    path = run_event_log_path(run_id, root=root)
    if not path.is_file():
        return []
    records: list[JsonObject] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        record = _public_record(value)
        if record is not None:
            records.append(record)
    return records


def _public_record(value: Any) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    try:
        event_id = int(value.get("id"))
    except (TypeError, ValueError):
        return None
    event = portal_turns.prompt_safe_text(str(value.get("event") or "")).strip()
    if not event:
        return None
    data = value.get("data") if isinstance(value.get("data"), dict) else {}
    timestamp = value.get("timestamp")
    try:
        timestamp_ms = int(timestamp)
    except (TypeError, ValueError):
        timestamp_ms = 0
    record = {
        "id": event_id,
        "event": event,
        "timestamp": timestamp_ms,
        "data": portal_turns.prompt_safe_value(data),
    }
    project_id = _clean_id(str(value.get("project_id") or ""))
    frame_id = _clean_id(str(value.get("frame_id") or ""))
    if project_id:
        record["project_id"] = project_id
    if frame_id:
        record["frame_id"] = frame_id
    return record


def _clean_run_id(value: str) -> str:
    clean = _clean_id(value)
    if not _RUN_ID_RE.fullmatch(clean):
        return ""
    return clean


def _clean_id(value: str) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()
