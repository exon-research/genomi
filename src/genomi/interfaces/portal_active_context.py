from __future__ import annotations

import threading
import time
from typing import Any

from . import portal_turns

JsonObject = dict[str, Any]
ACTIVE_CONTEXT_TTL_SECONDS = 10 * 60
_ACTIVE_CONTEXTS: dict[str, JsonObject] = {}
_LOCK = threading.Lock()
_TEXT_LIMITS = {
    "route": 320,
    "workspace_section": 80,
    "panel": 120,
    "frame_id": 160,
    "artifact_id": 160,
    "artifact_version_id": 160,
    "artifact_tab_id": 80,
    "artifact_tab_label": 80,
    "artifact_title": 180,
}


def update_project_active_context(project_id: str, payload: JsonObject) -> JsonObject:
    clean_project_id = _clean_text(project_id, 160)
    context = _clean_active_context(clean_project_id, payload)
    with _LOCK:
        _ACTIVE_CONTEXTS[clean_project_id] = context
    return _public_context(context) or {}


def active_context_for_project(project_id: str | None) -> JsonObject | None:
    clean_project_id = _clean_text(project_id, 160)
    if not clean_project_id:
        return None
    with _LOCK:
        context = _ACTIVE_CONTEXTS.get(clean_project_id)
        if not context:
            return None
        if time.time() - float(context.get("updated_at_epoch") or 0) > ACTIVE_CONTEXT_TTL_SECONDS:
            _ACTIVE_CONTEXTS.pop(clean_project_id, None)
            return None
        return _public_context(context)


def clear_project_active_context(project_id: str) -> None:
    clean_project_id = _clean_text(project_id, 160)
    if not clean_project_id:
        return
    with _LOCK:
        _ACTIVE_CONTEXTS.pop(clean_project_id, None)


def active_context_prompt_section(active_context: JsonObject | None) -> str:
    context = _public_context(active_context)
    if not context:
        return ""
    lines = [
        "# Current visible portal view",
        "This browser UI state is non-authoritative orientation only. Do not treat it as Genomi evidence unless the user explicitly included material or a Genomi tool returned it.",
    ]
    _append_line(lines, "Panel", context.get("panel"))
    _append_line(lines, "Visible artifact", context.get("artifact_title"))
    _append_line(lines, "Visible artifact tab", context.get("artifact_tab_label") or _tab_label(context.get("artifact_tab_id")))
    return "\n".join(lines) + "\n\n"


def _clean_active_context(project_id: str, payload: JsonObject) -> JsonObject:
    now = time.time()
    context: JsonObject = {
        "status": "available",
        "project_id": project_id,
        "updated_at": int(now * 1000),
        "updated_at_epoch": now,
    }
    for key, limit in _TEXT_LIMITS.items():
        value = _clean_text(payload.get(key) or _camel_value(payload, key), limit)
        if value:
            context[key] = value
    return context


def _public_context(value: JsonObject | None) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    public = {
        key: item
        for key, item in value.items()
        if key != "updated_at_epoch" and item not in (None, "")
    }
    return public or None


def _camel_value(payload: JsonObject, snake_key: str) -> Any:
    parts = snake_key.split("_")
    camel = parts[0] + "".join(part.title() for part in parts[1:])
    return payload.get(camel)


def _append_line(lines: list[str], label: str, value: Any) -> None:
    text = _first_text(value)
    if text:
        lines.append(f"- {label}: {text}")


def _clean_text(value: Any, limit: int) -> str:
    text = portal_turns.prompt_safe_text(str(value or "")).strip()
    if not text:
        return ""
    return text[:limit]


def _first_text(value: Any) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()


def _tab_label(value: Any) -> str:
    text = _first_text(value)
    labels = {
        "preview": "Preview",
        "evidence": "Evidence report",
        "messages": "Origin chat",
        "trace": "Work trail",
        "review": "Review",
        "rebuild": "Rebuild recipe",
        "environment": "Source limits",
        "technical": "Technical details",
    }
    return labels.get(text, text)
