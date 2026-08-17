from __future__ import annotations

import re

from typing import Any

from . import portal_agents, portal_privacy, portal_result_presentations, portal_selected_material

JsonObject = dict[str, Any]
PERSISTED_REDACTED_PRESENTATION_STATE = "persisted_redacted"
MAX_PERSISTED_TOOL_TEXT_CHARS = portal_selected_material.MAX_PERSISTED_TOOL_TEXT_CHARS
MESSAGE_PRESENTATION_KIND_FIELD = "message_presentation_kind"
_TOOL_INPUT_SUMMARY_KEYS = (
    "human_description",
    "description",
    "summary",
    "operation",
    "rsid",
    "query",
    "drug",
    "gene",
    "phenotype",
    "version_id",
)


def message_from_payload(payload: JsonObject) -> str:
    input_data = payload.get("input_data")
    if isinstance(input_data, dict):
        request = str(input_data.get("request") or "").strip()
        if request:
            return request
    return str(payload.get("message") or payload.get("request") or "").strip()


def display_request_text(request: str, selected_evidence: list[JsonObject] | None = None) -> str:
    clean = prompt_safe_text(str(request or "")).strip()
    if message_presentation_kind(selected_evidence) == "genome_context_control":
        return "Active genome included"
    return clean


def message_presentation_kind(selected_evidence: list[JsonObject] | None) -> str:
    if not isinstance(selected_evidence, list) or not selected_evidence:
        return ""
    evidence_items = [item for item in selected_evidence if isinstance(item, dict)]
    for item in selected_evidence:
        if not isinstance(item, dict):
            continue
        kind = str(item.get(MESSAGE_PRESENTATION_KIND_FIELD) or "").strip().lower()
        if kind == "genome_context_control" and evidence_items and all(
            str(entry.get("context_kind") or "").strip().lower() == "genome_context"
            for entry in evidence_items
        ):
            return kind
        if kind == "selected_material_control":
            return kind
    return ""


def selected_evidence_from_payload(payload: JsonObject) -> list[JsonObject]:
    raw = payload.get("selectedEvidence")
    if raw is None:
        raw = payload.get("selected_evidence")
    if raw is None and isinstance(payload.get("input_data"), dict):
        raw = payload["input_data"].get("selected_evidence")
    return clean_selected_evidence(raw)


def clean_selected_evidence(value: Any) -> list[JsonObject]:
    cleaned = portal_selected_material.clean_selected_evidence(value)
    presentation_kind = message_presentation_kind(value if isinstance(value, list) else None)
    if cleaned and presentation_kind:
        cleaned[0][MESSAGE_PRESENTATION_KIND_FIELD] = presentation_kind
    return cleaned


def selected_material_handoff(
    selected_evidence: list[JsonObject] | None,
    *,
    source_frame_id: str | None = None,
) -> JsonObject:
    return portal_selected_material.selected_material_handoff(selected_evidence, source_frame_id=source_frame_id)


def public_selected_material_handoff(value: Any) -> JsonObject:
    return portal_selected_material.public_selected_material_handoff(value)


def _prompt_safe_text(text: str) -> str:
    return portal_selected_material.prompt_safe_text(text)


def prompt_safe_text(text: str) -> str:
    return _prompt_safe_text(text)


def prompt_safe_value(value: Any) -> Any:
    return portal_selected_material.prompt_safe_value(value)


def conversation_history_prompt_section(history: list[JsonObject] | None) -> str:
    clean_history = _clean_conversation_history(history)
    if not clean_history:
        return ""
    lines = [
        "# Conversation so far",
        "Prior visible chat from this portal conversation. Use it for continuity only; it is not authoritative Genomi tool evidence.",
    ]
    for index, item in enumerate(clean_history, start=1):
        role = "User" if item["role"] == "user" else "Assistant"
        lines.append(f"## {index}. {role}")
        lines.append(item["text"])
        attached = item.get("attached_material")
        if isinstance(attached, list) and attached:
            labels = [
                str(entry.get("label") or "").strip()
                for entry in attached
                if isinstance(entry, dict) and str(entry.get("label") or "").strip()
            ]
            if labels:
                lines.append("Included evidence: " + "; ".join(labels[:3]))
    return "\n".join(lines).strip() + "\n\n"


def _clean_conversation_history(history: list[JsonObject] | None) -> list[JsonObject]:
    if not isinstance(history, list):
        return []
    clean: list[JsonObject] = []
    total_chars = 0
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        text = _prompt_safe_text(str(item.get("text") or "")).strip()
        if not text:
            continue
        text = text[:1200]
        total_chars += len(text)
        if total_chars > 7000:
            break
        record: JsonObject = {"role": role, "text": text}
        attached = item.get("attached_material")
        if isinstance(attached, list):
            record["attached_material"] = [
                {
                    "label": _bounded_public_text(entry.get("label") or "Included evidence") or "Included evidence",
                }
                for entry in attached[:3]
                if isinstance(entry, dict)
            ]
        clean.append(record)
    return clean


def history_tool_event(event: JsonObject) -> JsonObject:
    event_type = str(event.get("type") or "tool_event")
    if event_type == "tool_call":
        return {
            "type": "tool_call",
            "id": _clean_optional_text(event.get("id")),
            "name": _clean_optional_text(event.get("name")) or "tool",
            "input": {"summary": _tool_input_summary(event.get("input"))},
            "ledger": _tool_ledger_model(event),
            "persisted_display_only": True,
        }
    if event_type == "tool_result":
        result: JsonObject = {
            "type": "tool_result",
            "id": _clean_optional_text(event.get("id")),
            "name": _clean_optional_text(event.get("name")),
            "isError": bool(event.get("isError")),
            "content": _tool_result_summary(event),
            "ledger": _tool_ledger_model(event),
            "presentation_state": PERSISTED_REDACTED_PRESENTATION_STATE,
            "persisted_display_only": True,
        }
        permission_request = _tool_permission_request(event)
        if permission_request is not None:
            result["permission_request"] = permission_request
        payload = _persisted_presented_payload(event)
        if payload is not None:
            result["payload"] = payload
            presentation = portal_result_presentations.presentation_for_tool_event(
                event,
                payload=payload,
                presentation_state=PERSISTED_REDACTED_PRESENTATION_STATE,
                display_only=True,
            )
            if presentation is not None:
                result["portal_presentation"] = presentation
        return result
    if event_type == "error":
        result: JsonObject = {
            "type": "error",
            "id": _clean_optional_text(event.get("id")),
            "name": _clean_optional_text(event.get("name")) or "error",
            "message": _bounded_public_text(event.get("message") or event.get("content") or "Tool error"),
        }
        permission_request = _tool_permission_request(event)
        if permission_request is not None:
            result["permission_request"] = permission_request
        result["ledger"] = _tool_ledger_model(event)
        result["persisted_display_only"] = True
        return result
    if event_type == "diagnostic":
        return {
            "type": "diagnostic",
            "id": _clean_optional_text(event.get("id")),
            "name": _clean_optional_text(event.get("name")) or "host_agent_trace",
            "message": _bounded_public_text(event.get("message") or event.get("content") or event.get("agentId") or ""),
            "ledger": _tool_ledger_model(event),
            "persisted_display_only": True,
        }
    return {
        "type": event_type,
        "content": "Tool event captured during the live run; detailed local payload was not persisted.",
        "persisted_display_only": True,
    }


def live_tool_event(event: JsonObject) -> JsonObject:
    event_type = str(event.get("type") or "tool_event")
    if event_type == "tool_call":
        return {
            "type": "tool_call",
            "id": _clean_optional_text(event.get("id")),
            "name": _clean_optional_text(event.get("name")) or "tool",
            "input": prompt_safe_value(event.get("input") if event.get("input") is not None else {}),
        }
    if event_type == "tool_result":
        result: JsonObject = {
            "type": "tool_result",
            "id": _clean_optional_text(event.get("id")),
            "name": _clean_optional_text(event.get("name")),
            "isError": bool(event.get("isError")),
            "content": _bounded_public_text(event.get("content") or event.get("message") or ""),
        }
        permission_request = _tool_permission_request(event)
        if permission_request is not None:
            result["permission_request"] = permission_request
        if event.get("payload") is not None:
            payload = prompt_safe_value(event.get("payload"))
            result["payload"] = payload
            presentation = portal_result_presentations.presentation_for_tool_event(event, payload=payload)
            if presentation is not None:
                result["portal_presentation"] = presentation
        return result
    if event_type == "error":
        result = {
            "type": "error",
            "id": _clean_optional_text(event.get("id")),
            "name": _clean_optional_text(event.get("name")) or "error",
            "message": _bounded_public_text(event.get("message") or event.get("content") or "Tool error"),
        }
        permission_request = _tool_permission_request(event)
        if permission_request is not None:
            result["permission_request"] = permission_request
        return result
    return prompt_safe_value(event)


def _persisted_presented_payload(event: JsonObject) -> JsonObject | None:
    return portal_result_presentations.persisted_payload_for_tool_event(event)


def _tool_permission_request(event: JsonObject) -> JsonObject | None:
    request = event.get("permission_request")
    if isinstance(request, dict):
        return prompt_safe_value(request)
    detected = portal_agents.permission_request_from_message(
        str(event.get("content") or event.get("message") or "")
    )
    return prompt_safe_value(detected) if detected is not None else None


def _tool_input_summary(value: Any) -> str:
    if isinstance(value, dict):
        for key in _TOOL_INPUT_SUMMARY_KEYS:
            child = value.get(key)
            if isinstance(child, str) and child.strip():
                return _bounded_public_text(child)
        if isinstance(value.get("command"), str):
            return _bounded_public_text(str(value["command"]).splitlines()[0])
        safe_keys = sorted(str(key) for key in value if str(key).lower() not in portal_privacy.SENSITIVE_FIELD_NAMES)
        if safe_keys:
            return "Input fields: " + ", ".join(safe_keys[:8])
    if value not in (None, "", {}):
        return _bounded_public_text(value)
    return "Input captured during the live run; local details were not persisted."


def _tool_result_summary(event: JsonObject) -> str:
    presentation_summary = portal_result_presentations.persisted_summary_for_tool_event(event)
    if presentation_summary:
        return _bounded_public_text(presentation_summary)
    payload = event.get("payload")
    if isinstance(payload, dict):
        for key in ("headline", "status", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _bounded_public_text(value)
        envelope = payload.get("evidence_envelope")
        if isinstance(envelope, dict):
            readiness = envelope.get("answer_readiness")
            finding = envelope.get("finding_state")
            summary = " · ".join(str(item) for item in (finding, readiness) if item)
            if summary:
                return _bounded_public_text(summary)
    content = event.get("content") or event.get("message")
    if content and not _looks_like_serialized_payload(content):
        return _bounded_public_text(content)
    return "Tool result captured during the live run; detailed payload was not persisted."


def _looks_like_serialized_payload(value: Any) -> bool:
    """Whether this is a payload rather than a description of what happened.

    A persisted summary is what the reader sees on the step forever, so raw
    file bytes and serialized results must not become one: a work trail was
    showing `1590- 1 1591- ] 1592- ], 1593- "population_flags"` as the
    description of a research step.
    """

    text = str(value or "").strip()
    if not text:
        return True
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    stripped = first_line.strip()
    if stripped[:1] in {"{", "[", '"'}:
        return True
    if re.search(r'"\s*:', stripped):
        return True
    return bool(re.match(r"^\d+[-\s]", stripped) and re.search(r"[{}\[\]]", stripped))


def _tool_ledger_model(event: JsonObject) -> JsonObject:
    existing = event.get("ledger")
    if isinstance(existing, dict):
        preserved: JsonObject = {}
        for key in ("operation", "status", "summary", "headline", "answer_readiness", "finding_state"):
            value = existing.get(key)
            if isinstance(value, str) and value.strip():
                preserved[key] = _bounded_public_text(value)
        preserved["presentation_state"] = PERSISTED_REDACTED_PRESENTATION_STATE
        preserved["display_only"] = True
        return preserved
    event_type = str(event.get("type") or "tool_event")
    operation = _clean_optional_text(event.get("name")) or "tool"
    status = "running" if event_type == "tool_call" else "error" if event_type == "error" or event.get("isError") else "completed"
    summary = _tool_input_summary(event.get("input")) if event_type == "tool_call" else _tool_result_summary(event)
    ledger: JsonObject = {
        "operation": operation,
        "status": status,
        "summary": summary,
        "display_only": True,
    }
    if event_type == "tool_result":
        ledger["presentation_state"] = PERSISTED_REDACTED_PRESENTATION_STATE
    payload = event.get("payload")
    if isinstance(payload, dict):
        headline = (
            portal_result_presentations.persisted_summary_for_tool_event(event)
            or payload.get("headline")
            or payload.get("message")
            or payload.get("status")
        )
        if isinstance(headline, str) and headline.strip():
            ledger["headline"] = _bounded_public_text(headline)
        envelope = payload.get("evidence_envelope")
        if isinstance(envelope, dict):
            readiness = envelope.get("answer_readiness")
            finding = envelope.get("finding_state")
            if isinstance(readiness, str) and readiness.strip():
                ledger["answer_readiness"] = _bounded_public_text(readiness)
            if isinstance(finding, str) and finding.strip():
                ledger["finding_state"] = _bounded_public_text(finding)
    return ledger


def _bounded_public_text(value: Any) -> str:
    return _prompt_safe_text(str(value)).strip()[:MAX_PERSISTED_TOOL_TEXT_CHARS]


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _bounded_public_text(value)
    return text or None


def selected_evidence_prompt_section(selected_evidence: list[JsonObject] | None) -> str:
    return portal_selected_material.selected_evidence_prompt_section(selected_evidence)
