from __future__ import annotations

from typing import Any

from .portal_result_presentation_model import (
    PERSISTED_REDACTED_PRESENTATION_STATE,
    array_value as _array,
    count_summary as _count_summary,
    empty as _empty,
    evidence_state_lane as _evidence_state_lane,
    format_value as _format_value,
    humanize as _humanize,
    lane as _lane,
    metric as _metric,
    node as _node,
    object_value as _object,
    presentation as _presentation,
    readable_state as _readable_state,
    string_list as _string_list,
    summary_from_envelope as _summary_from_envelope,
    text as _text,
)

JsonObject = dict[str, Any]
TARGET_PACKET_OPERATION = "research.build_target_packet"
_TARGET_PACKET_SECTIONS = (
    "stored_research",
    "source_catalog",
    "available_operations",
    "evidence_options",
)


def target_packet_presentation(
    operation: str,
    payload: JsonObject,
    *,
    presentation_state: str = "",
    display_only: bool = False,
) -> JsonObject | None:
    if operation != TARGET_PACKET_OPERATION or not _is_target_packet_payload(payload):
        return None
    target = _object(payload.get("target"))
    stored = _object(payload.get("stored_research"))
    source_catalog = _object(payload.get("source_catalog"))
    catalog_summary = _object(source_catalog.get("summary"))
    records = _array(stored.get("records"))
    sources = _array(source_catalog.get("sources"))
    options = _array(payload.get("evidence_options"))
    envelope = _object(payload.get("evidence_envelope"))
    title = _target_label(target)
    return _presentation(
        operation=operation,
        kind="target_packet",
        kicker="Target evidence report",
        title=title,
        summary=_target_summary(payload, envelope),
        envelope=envelope,
        metrics=[
            _metric("Sources", catalog_summary.get("source_count") if catalog_summary.get("source_count") is not None else len(sources)),
            _metric("Stored findings", stored.get("count") if stored.get("count") is not None else len(records)),
            _metric("Answer boundary", _readable_state(envelope.get("answer_readiness"))),
            _metric("Evidence support", _readable_state(envelope.get("finding_state"))),
            _metric("Default assumptions", _count_summary(payload.get("defaults_applied"), "applied")),
        ],
        lanes=[
            _lane("Target", [_node(title, _text(target.get("target_type") or target.get("target_id")) or "Research target", target)]),
            _lane("Reviewed research", [_node(_research_record_label(item), _research_record_summary(item), item) for item in records[:8]]),
            _lane("Source catalog", [_node(_source_label(item), _source_summary(item), item) for item in sources[:8]]),
            _lane("Evidence readiness", [_option_node(item) for item in options[:8]], selectable=False),
            _evidence_state_lane(envelope),
        ],
        notice=_redacted_notice() if display_only or presentation_state == PERSISTED_REDACTED_PRESENTATION_STATE else None,
    )


def target_packet_tool_summary(payload: JsonObject) -> str:
    envelope = _object(payload.get("evidence_envelope"))
    operation = _text(envelope.get("operation"))
    if operation != TARGET_PACKET_OPERATION:
        return ""
    label = _target_label(_object(payload.get("target")))
    return f"Target evidence report for {label}" if label and label != "Research target" else "Target evidence report ready"


def _is_target_packet_payload(payload: JsonObject) -> bool:
    return bool(
        _object(payload.get("target"))
        and (any(key in payload for key in _TARGET_PACKET_SECTIONS) or isinstance(payload.get("purpose"), str))
    )


def _option_node(value: Any) -> JsonObject | None:
    item = _object(value)
    label = _text(item.get("component") or item.get("state")) or "Evidence readiness"
    summary = " · ".join(
        part
        for part in (
            _readable_state(item.get("state")),
            _format_value(item.get("inputs")) if not _empty(item.get("inputs")) else "",
        )
        if part
    )
    return _node(_humanize(label), summary or _format_value(item), value)


def _target_label(target: JsonObject) -> str:
    for key in ("gene", "drug", "condition", "topic", "target_id", "target_type"):
        text = _text(target.get(key))
        if text:
            return text
    if target.get("chrom") and target.get("pos"):
        allele = f"{_text(target.get('ref'))}>{_text(target.get('alt'))}" if target.get("ref") and target.get("alt") else ""
        return " ".join(part for part in (_text(target.get("genome_build")), f"{target.get('chrom')}:{target.get('pos')}", allele) if part)
    return "Research target"


def _source_label(value: Any) -> str:
    item = _object(value)
    return " · ".join(part for part in (_text(item.get("source_id")), _text(item.get("title"))) if part) or "Evidence source"


def _source_summary(value: Any) -> str:
    item = _object(value)
    return " · ".join(
        part
        for part in (
            _readable_state(item.get("adapter_status")),
            _text(item.get("best_for")),
            " · ".join(_string_list(item.get("evidence_types"))[:4]),
        )
        if part
    ) or _format_value(value)


def _research_record_label(value: Any) -> str:
    item = _object(value)
    for key in ("finding_id", "title", "source_title", "target_id", "scope"):
        text = _text(item.get(key))
        if text:
            return text
    return "Reviewed finding"


def _research_record_summary(value: Any) -> str:
    item = _object(value)
    finding = _object(item.get("finding"))
    source = _object(item.get("source"))
    return " · ".join(
        part
        for part in (
            _text(finding.get("summary")),
            _text(finding.get("text")),
            _text(source.get("title")),
            _text(item.get("scope")),
        )
        if part
    ) or _format_value(value)


def _target_summary(payload: JsonObject, envelope: JsonObject) -> str:
    purpose = _text(payload.get("purpose"))
    if purpose:
        return purpose
    headline = _summary_from_envelope(envelope)
    if headline and TARGET_PACKET_OPERATION not in headline:
        return headline
    return "Target, source coverage, and stored research are grouped for review."


def _redacted_notice() -> JsonObject:
    return {
        "title": "Persisted redacted history",
        "text": "This saved view includes only persisted public lanes. Re-check the source before using evidence.",
    }
