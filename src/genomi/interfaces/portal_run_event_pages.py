from __future__ import annotations

from pathlib import Path
from typing import Any

from . import portal_run_events, portal_run_logs, portal_run_service, portal_turns

JsonObject = dict[str, Any]
DEFAULT_RUN_EVENT_PAGE_LIMIT = 200
MAX_RUN_EVENT_PAGE_LIMIT = 500


def run_event_page(
    run_id: str,
    *,
    after_event_id: int | None = None,
    limit: int | None = None,
    root: str | Path | None = None,
) -> JsonObject | None:
    clean_run_id = portal_turns.prompt_safe_text(str(run_id or "")).strip()
    if not clean_run_id:
        return None
    run_status = portal_run_service.get_run_status(clean_run_id, root=root)
    run = portal_run_events.get_run(clean_run_id)
    if run_status is None and run is None:
        return None
    records = portal_run_logs.read_run_event_records(clean_run_id, root=root)
    source = "durable_log"
    if not records and run is not None:
        records = _memory_run_event_records(run)
        source = "memory"
    elif not records:
        source = "none"
    safe_after = max(0, int(after_event_id or 0))
    safe_limit = _bounded_limit(limit)
    pending = [record for record in records if int(record.get("id") or 0) > safe_after]
    items = pending[:safe_limit] if safe_limit else []
    latest_event_id = max((int(record.get("id") or 0) for record in records), default=0)
    next_after = int(items[-1].get("id") or safe_after) if items else safe_after
    return {
        "schema": "genomi_portal_run_event_page",
        "run_id": clean_run_id,
        "run": run_status,
        "available": bool(records),
        "source": source,
        "after_event_id": safe_after,
        "limit": safe_limit,
        "returned": len(items),
        "total": len(records),
        "truncated": len(pending) > len(items),
        "latest_event_id": latest_event_id,
        "next_after_event_id": next_after,
        "items": items,
    }


def _memory_run_event_records(run: portal_run_events.PortalRun) -> list[JsonObject]:
    return [
        {
            "id": event.id,
            "event": event.event,
            "timestamp": int(event.timestamp * 1000),
            "data": portal_run_events.public_event_data(event.event, event.data),
            **({"project_id": run.project_id} if run.project_id else {}),
            **({"frame_id": run.frame_id} if run.frame_id else {}),
        }
        for event in run.events
    ]


def _bounded_limit(limit: int | None) -> int:
    value = DEFAULT_RUN_EVENT_PAGE_LIMIT if limit is None else int(limit)
    return max(0, min(value, MAX_RUN_EVENT_PAGE_LIMIT))
