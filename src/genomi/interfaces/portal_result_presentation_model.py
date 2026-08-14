from __future__ import annotations

from typing import Any

from . import portal_privacy

JsonObject = dict[str, Any]
PRESENTATION_SCHEMA = "genomi_portal_result_presentation"
PERSISTED_REDACTED_PRESENTATION_STATE = "persisted_redacted"


def presentation(
    *,
    operation: str,
    kind: str,
    kicker: str,
    title: str,
    summary: str,
    envelope: JsonObject,
    metrics: list[JsonObject | None],
    lanes: list[JsonObject | None],
    notice: JsonObject | None = None,
) -> JsonObject:
    model: JsonObject = {
        "schema": PRESENTATION_SCHEMA,
        "source": "server",
        "kind": kind,
        "operation": operation,
        "kicker": kicker,
        "title": title,
        "summary": summary,
        "evidenceEnvelope": envelope,
        "metrics": [metric for metric in metrics if metric],
        "lanes": [lane for lane in lanes if lane and lane.get("nodes")],
    }
    if notice:
        model["notice"] = notice
    return model


def lane(title: str, nodes: list[JsonObject | None], *, selectable: bool = True) -> JsonObject | None:
    clean_nodes = [node for node in nodes if node]
    if not clean_nodes:
        return None
    lane_model: JsonObject = {"title": title, "nodes": clean_nodes}
    if not selectable:
        lane_model["selectable"] = False
    return lane_model


def node(label: str, summary: str, value: Any) -> JsonObject | None:
    clean_label = label.strip() or "Evidence item"
    clean_summary = summary.strip() or format_value(value)
    if not clean_label and not clean_summary:
        return None
    return {
        "label": clean_label,
        "summary": clean_summary[:220],
        "context": context_line(clean_label, clean_summary, value),
        "value": value,
    }


def metric(label: str, value: Any) -> JsonObject | None:
    if empty(value):
        return None
    return {"label": label, "value": value}


def entry_lane(title: str, value: Any) -> JsonObject | None:
    nodes = [node(label, format_value(child), child) for label, child in entries(value, title)[:12]]
    return lane(title, nodes)


def evidence_state_lane(envelope: JsonObject) -> JsonObject | None:
    nodes: list[JsonObject | None] = []
    nodes.extend(evidence_state_nodes("Coverage", envelope.get("coverage")))
    nodes.extend(evidence_state_nodes("Observations", envelope.get("observations")))
    nodes.extend(evidence_state_nodes("Suggested follow-up", envelope.get("next_actions")))
    return lane("Coverage and limits", nodes[:12], selectable=False)


def evidence_state_nodes(section: str, value: Any) -> list[JsonObject | None]:
    return [
        node(f"{section}: {label}", format_value(child), {"section": section, "label": label, "value": child})
        for label, child in entries(value, section)
    ]


def entries(value: Any, title: str) -> list[tuple[str, Any]]:
    if isinstance(value, list):
        return [(item_label(item, index, title), item) for index, item in enumerate(value) if not empty(item)]
    if isinstance(value, dict):
        return [(humanize(key), child) for key, child in value.items() if not empty(child)]
    if empty(value):
        return []
    return [("Value", value)]


def item_label(value: Any, index: int, title: str) -> str:
    item = object_value(value)
    for key in ("action", "type", "source", "source_id", "gene", "drug", "rsid", "status", "title", "label"):
        if text(item.get(key)):
            return humanize(text(item[key]))
    singular = title[:-1] if title.endswith("s") and not title.endswith("ss") else title
    return f"{singular or 'Item'} {index + 1}"


def context_line(label: str, summary: str, value: Any) -> str:
    return f"{label}: {summary or format_value(value)}"


def summary_from_envelope(envelope: JsonObject) -> str:
    return text(envelope.get("headline"))


def readable_state(value: Any) -> str:
    clean = text(value).replace("_", " ").replace("-", " ").strip()
    return clean[:1].upper() + clean[1:] if clean else ""


def count_summary(value: Any, noun: str) -> str:
    count = len(value) if isinstance(value, list) else len(value) if isinstance(value, dict) else 0
    return f"{count} {noun}" if count else ""


def format_value(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts = []
        for key, child in value.items():
            if empty(child):
                continue
            parts.append(f"{humanize(str(key))}: {format_value(child)}")
            if len(parts) >= 4:
                break
        return "; ".join(parts)
    if isinstance(value, list):
        return f"{len(value)} item{'s' if len(value) != 1 else ''}"
    return str(value or "")


def humanize(value: str) -> str:
    clean = str(value or "").replace("_", " ").replace("-", " ").strip()
    return clean.title() if clean else ""


def safe_model(model: JsonObject | None) -> JsonObject | None:
    if not model:
        return None
    safe = portal_privacy.prompt_safe_value(model, max_list_items=24)
    return safe if isinstance(safe, dict) else None


def text(value: Any) -> str:
    return portal_privacy.prompt_safe_text(str(value or "")).strip()


def empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {} or value is False


def object_value(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {}


def array_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def string_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [] if empty(value) else [value]
    return [text(item) for item in values if text(item)]


def text_array(value: Any) -> list[str]:
    return [text(item) for item in array_value(value) if text(item)]
