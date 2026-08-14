from __future__ import annotations

from typing import Any

from . import portal_privacy

JsonObject = dict[str, Any]
MAX_SELECTED_EVIDENCE_ITEMS = 12
MAX_SELECTED_EVIDENCE_TEXT_CHARS = 4000
MAX_PERSISTED_TOOL_TEXT_CHARS = 1200
MAX_HANDOFF_LABELS = 3
_SELECTED_EVIDENCE_TEXT_METADATA_LIMITS = {
    "context_kind": 80,
    "finding_state": 120,
    "answer_readiness": 120,
    "summary": 1200,
    "source_operation": 240,
    "operation": 240,
    "tool": 240,
    "tool_name": 240,
    "tool_operation": 240,
    "tool_call_id": 160,
    "tool_result_id": 160,
    "call_id": 160,
    "result_id": 160,
    "artifact_id": 160,
    "panel_id": 160,
    "node_mode": 80,
    "selection_mode": 80,
    "status": 120,
}
_SELECTED_EVIDENCE_COUNT_METADATA_KEYS = {
    "node_count",
    "total_node_count",
    "visible_node_count",
    "selected_count",
}


def selected_evidence_from_payload(payload: JsonObject) -> list[JsonObject]:
    raw = payload.get("selectedEvidence")
    if raw is None:
        raw = payload.get("selected_evidence")
    if raw is None and isinstance(payload.get("input_data"), dict):
        raw = payload["input_data"].get("selected_evidence")
    return clean_selected_evidence(raw)


def clean_selected_evidence(value: Any) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    selected: list[JsonObject] = []
    for index, item in enumerate(value[:MAX_SELECTED_EVIDENCE_ITEMS], start=1):
        if not isinstance(item, dict):
            continue
        cleaned = _clean_selected_evidence_item(item, index)
        if cleaned:
            selected.append(cleaned)
    return selected


def prompt_safe_text(text: str) -> str:
    return portal_privacy.prompt_safe_text(text)


def prompt_safe_value(value: Any) -> Any:
    return portal_privacy.prompt_safe_value(value)


def selected_evidence_prompt_section(selected_evidence: list[JsonObject] | None) -> str:
    clean_evidence = clean_selected_evidence(selected_evidence)
    if not clean_evidence:
        return ""
    lines = [
        "# User-selected portal material",
        "These snippets were selected in the browser UI and are client-supplied material, not authoritative Genomi tool output. Re-check current Genomi tools before making evidence claims, AGI-specific claims, or negative inferences.",
    ]
    for item in clean_evidence:
        lines.append(f"\n## {item['label']}")
        lines.append(str(item["prompt_text"]))
    return "\n".join(lines).rstrip() + "\n\n"


def selected_material_handoff(
    selected_evidence: list[JsonObject] | None,
    *,
    source_frame_id: str | None = None,
) -> JsonObject:
    clean_evidence = clean_selected_evidence(selected_evidence)
    if not clean_evidence:
        return {}
    labels = _selected_material_labels(clean_evidence)
    handoff: JsonObject = {
        "kind": "selected_material",
        "material_count": len(clean_evidence),
        "labels": labels,
        "summary": _selected_material_handoff_summary(labels, len(clean_evidence)),
    }
    clean_source_frame_id = _bounded_public_text_with_limit(source_frame_id or "", 160)
    if clean_source_frame_id:
        handoff["source_frame_id"] = clean_source_frame_id
    return handoff


def public_selected_material_handoff(value: Any) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    summary = _bounded_public_text_with_limit(value.get("summary") or "", 180)
    if not summary:
        return {}
    labels = [
        _bounded_public_text_with_limit(label, 120)
        for label in value.get("labels", [])
        if _bounded_public_text_with_limit(label, 120)
    ][:MAX_HANDOFF_LABELS] if isinstance(value.get("labels"), list) else []
    material_count = value.get("material_count")
    count = material_count if isinstance(material_count, int) and material_count > 0 else len(labels)
    public: JsonObject = {
        "kind": "selected_material",
        "summary": summary,
        "material_count": count,
    }
    if labels:
        public["labels"] = labels
    return public


def _clean_selected_evidence_item(item: JsonObject, index: int) -> JsonObject | None:
    fallback_text = prompt_safe_text(str(item.get("prompt_text") or item.get("text") or "")).strip()
    selected_nodes = _clean_selected_nodes(item.get("selected_nodes"))
    if not fallback_text and not selected_nodes:
        return None
    label = _bounded_public_text(item.get("label") or item.get("id") or f"Selected evidence {index}") or f"Selected evidence {index}"
    prompt_text = (
        _prompt_text_for_typed_evidence(label, selected_nodes)
        if selected_nodes
        else fallback_text[:MAX_SELECTED_EVIDENCE_TEXT_CHARS]
    )
    cleaned: JsonObject = {
        "id": _bounded_public_text(item.get("id") or f"selected-evidence-{index}") or f"selected-evidence-{index}",
        "label": label,
        "prompt_text": prompt_text,
        "client_supplied": True,
    }
    _copy_selected_evidence_metadata(cleaned, item)
    if selected_nodes:
        cleaned["selected_nodes"] = selected_nodes
        cleaned["selected_node_count"] = len(selected_nodes)
    return cleaned


def _clean_selected_nodes(value: Any) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    nodes: list[JsonObject] = []
    for index, item in enumerate(value[:16], start=1):
        if isinstance(item, str):
            text = prompt_safe_text(item.strip())
            if text:
                nodes.append({"label": f"Node {index}", "text": text[:MAX_SELECTED_EVIDENCE_TEXT_CHARS]})
            continue
        if not isinstance(item, dict):
            continue
        text = prompt_safe_text(str(item.get("text") or item.get("value") or "")).strip()
        if not text:
            continue
        label = _bounded_public_text(item.get("label") or f"Node {index}") or f"Node {index}"
        node: JsonObject = {"label": label, "text": text[:MAX_SELECTED_EVIDENCE_TEXT_CHARS]}
        value = item.get("value")
        if isinstance(value, str) and value.strip() and value.strip() != text:
            node["value"] = prompt_safe_text(value.strip())[:MAX_SELECTED_EVIDENCE_TEXT_CHARS]
        nodes.append(node)
    return nodes


def _copy_selected_evidence_metadata(cleaned: JsonObject, item: JsonObject) -> None:
    # Rebuild from this allow-list; raw envelopes and browser payload blobs are intentionally not copied.
    for key, limit in _SELECTED_EVIDENCE_TEXT_METADATA_LIMITS.items():
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            cleaned[key] = _bounded_public_text_with_limit(value, limit)
    for key in _SELECTED_EVIDENCE_COUNT_METADATA_KEYS:
        value = item.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            cleaned[key] = min(value, 1_000_000)


def _selected_material_labels(selected_evidence: list[JsonObject]) -> list[str]:
    labels: list[str] = []
    for item in selected_evidence:
        label = _bounded_public_text_with_limit(item.get("label") or "", 120)
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= MAX_HANDOFF_LABELS:
            break
    return labels


def _selected_material_handoff_summary(labels: list[str], material_count: int) -> str:
    if not labels:
        return f"Started from {material_count} selected item" + ("" if material_count == 1 else "s")
    if material_count == 1:
        return _bounded_public_text_with_limit(f"Started from {labels[0]}", 180)
    hidden_count = max(material_count - len(labels), 0)
    shown = ", ".join(labels)
    suffix = f", +{hidden_count} more" if hidden_count else ""
    return _bounded_public_text_with_limit(f"Started from {material_count} selected items: {shown}{suffix}", 180)


def _prompt_text_for_typed_evidence(label: str, selected_nodes: list[JsonObject]) -> str:
    lines = [f"Selected portal material: {label}"]
    for node in selected_nodes[:8]:
        lines.append(f"{node['label']}: {node['text']}")
    return "\n".join(lines)[:MAX_SELECTED_EVIDENCE_TEXT_CHARS]


def _bounded_public_text(value: Any) -> str:
    return prompt_safe_text(str(value)).strip()[:MAX_PERSISTED_TOOL_TEXT_CHARS]


def _bounded_public_text_with_limit(value: Any, limit: int) -> str:
    return prompt_safe_text(str(value)).strip()[:limit]
