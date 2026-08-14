from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from . import portal_result_presentations, portal_store
from .portal_result_presentation_model import PERSISTED_REDACTED_PRESENTATION_STATE

JsonObject = dict[str, Any]


def add_evidence_packet_artifact(
    project_id: str,
    result: JsonObject,
    *,
    frame_id: str | None = None,
    file_path: str | None = None,
    external_url: str | None = None,
    reproduction: JsonObject | None = None,
) -> JsonObject | None:
    return portal_store.add_artifact(
        project_id,
        kind="evidence_packet",
        renderer="evidence_packet",
        title=_packet_title(result),
        operation="research.build_target_packet",
        result=result,
        frame_id=frame_id,
        file_path=file_path,
        external_url=external_url,
        summary=_packet_summary(result),
        summary_lines=_packet_summary_lines(result),
        reproduction=reproduction,
        open_label="Open report",
    )


def write_evidence_packet_html(path: str | Path, result: JsonObject) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_packet_html(result), encoding="utf-8")


def _packet_title(result: JsonObject) -> str:
    target = _object(result.get("target"))
    label = target.get("gene") or target.get("drug") or target.get("condition") or target.get("topic") or target.get("target_id")
    return f"Evidence report: {label}" if label else "Evidence report"


def _packet_summary_lines(result: JsonObject) -> list[str]:
    envelope = _object(result.get("evidence_envelope"))
    stored = _object(result.get("stored_research"))
    source_catalog = _object(result.get("source_catalog"))
    source_count = _source_count(source_catalog)
    lines = [
        _human_state(envelope.get("finding_state") or result.get("status") or "evidence report"),
        f"{source_count} source{'s' if source_count != 1 else ''}",
    ]
    stored_count = stored.get("count")
    if isinstance(stored_count, int):
        lines.append(f"{stored_count} stored finding{'s' if stored_count != 1 else ''}")
    return lines


def _packet_summary(result: JsonObject) -> JsonObject:
    target = _object(result.get("target"))
    envelope = _object(result.get("evidence_envelope"))
    stored = _object(result.get("stored_research"))
    source_catalog = _object(result.get("source_catalog"))
    sources = [
        _compact_source(item)
        for item in _list(source_catalog.get("sources"))[:8]
        if isinstance(item, dict)
    ]
    operations = [
        _compact_operation(item)
        for item in _list(result.get("available_operations"))[:8]
        if isinstance(item, dict)
    ]
    options = [
        _compact_option(item)
        for item in _list(result.get("evidence_options"))[:8]
        if isinstance(item, dict)
    ]
    summary: JsonObject = {
        "headline": result.get("headline") or envelope.get("headline"),
        "purpose": result.get("purpose"),
        "target": target,
        "stored_research": {
            "count": stored.get("count"),
            "records": [],
        },
        "source_catalog": {
            "summary": {"source_count": _source_count(source_catalog)},
            "sources": sources,
        },
        "available_operations": operations,
        "evidence_options": options,
    }
    if envelope:
        summary["evidence_envelope"] = envelope
    if result.get("defaults_applied") is not None:
        summary["defaults_applied"] = result.get("defaults_applied")
    presentation = portal_result_presentations.presentation_for_tool_event(
        {
            "type": "tool_result",
            "name": "research.build_target_packet",
            "payload": summary,
        },
        payload=summary,
        presentation_state=PERSISTED_REDACTED_PRESENTATION_STATE,
        display_only=True,
    )
    if presentation is not None:
        summary["portal_presentation"] = presentation
    return summary


def _packet_html(result: JsonObject) -> str:
    target = _object(result.get("target"))
    envelope = _object(result.get("evidence_envelope"))
    source_catalog = _object(result.get("source_catalog"))
    stored = _object(result.get("stored_research"))
    sources = _list(source_catalog.get("sources"))[:12]
    source_count = _source_count(source_catalog)
    target_label = _escape(target.get("target_id") or target.get("gene") or target.get("drug") or target.get("condition") or target.get("topic") or "target")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(_packet_title(result))}</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #07110d; color: #e8f5ee; }}
    body {{ margin: 0; background: radial-gradient(circle at 20% 0%, rgba(73, 198, 141, .12), transparent 34%), #07110d; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 32px; }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: 0; }}
    p {{ color: #a9b8b0; line-height: 1.5; }}
    .hero {{ border: 1px solid rgba(91, 219, 154, .28); border-radius: 8px; padding: 24px; background: rgba(11, 28, 20, .86); }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-top: 18px; }}
    .metric, section {{ border: 1px solid rgba(255,255,255,.10); border-radius: 8px; background: rgba(255,255,255,.035); }}
    .metric {{ padding: 12px; }}
    .metric span, .card span {{ display: block; color: #7c8d84; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
    .metric strong {{ display: block; margin-top: 6px; color: #65d694; font-size: 20px; }}
    section {{ margin-top: 18px; padding: 18px; }}
    h2 {{ margin: 0 0 12px; font-size: 15px; text-transform: uppercase; color: #8bdcae; letter-spacing: .08em; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }}
    .card {{ border: 1px solid rgba(255,255,255,.10); border-radius: 7px; padding: 12px; background: rgba(4, 12, 9, .62); }}
    .card strong {{ display: block; margin-top: 5px; color: #f4fff8; }}
    code {{ color: #7ee2a4; word-break: break-word; }}
  </style>
</head>
<body>
  <main>
    <div class="hero">
      <h1>{_escape(_packet_title(result))}</h1>
      <p>{_escape(_report_purpose(result.get("purpose")))}</p>
      <div class="metrics">
        {_metric("Target", target_label)}
        {_metric("Evidence support", _human_state(envelope.get("finding_state") or "unknown"))}
        {_metric("Answer boundary", _human_state(envelope.get("answer_readiness") or "unknown"))}
        {_metric("Sources", source_count)}
        {_metric("Stored", stored.get("count") if stored.get("count") is not None else 0)}
      </div>
    </div>
    {_card_section("Relevant Sources", [_source_card(item) for item in sources])}
  </main>
</body>
</html>
"""


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><span>{_escape(label)}</span><strong>{_escape(value)}</strong></div>'


def _report_purpose(value: Any) -> str:
    text = str(value or "Target-centric evidence report for focused Genomi research.")
    return text.replace("Target-centric packet", "Target-centric evidence report")


def _human_state(value: Any) -> str:
    text = str(value or "").replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else ""


def _card_section(title: str, cards: list[str]) -> str:
    if not cards:
        return ""
    return f'<section><h2>{_escape(title)}</h2><div class="grid">{"".join(cards)}</div></section>'


def _source_card(item: Any) -> str:
    source = _object(item)
    return (
        '<div class="card">'
        f'<span>{_escape(source.get("source_id") or "source")}</span>'
        f'<strong>{_escape(source.get("title") or "Untitled source")}</strong>'
        f'<p>{_escape(source.get("best_for") or source.get("adapter_status") or "")}</p>'
        "</div>"
    )


def _object(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _compact_source(source: JsonObject) -> JsonObject:
    return {
        "source_id": source.get("source_id"),
        "title": source.get("title"),
        "adapter_status": source.get("adapter_status"),
        "best_for": source.get("best_for"),
    }


def _compact_operation(operation: JsonObject) -> JsonObject:
    return {
        "name": operation.get("name"),
        "tool": operation.get("tool"),
        "relevance": operation.get("relevance"),
        "params": _safe_public_params(operation.get("params")),
    }


def _compact_option(option: JsonObject) -> JsonObject:
    return {
        "component": option.get("component"),
        "state": option.get("state"),
        "available_operation": option.get("available_operation"),
        "inputs": option.get("inputs"),
    }


def _safe_public_params(value: Any) -> JsonObject:
    params = _object(value)
    safe: JsonObject = {}
    for key, child in params.items():
        key_text = str(key)
        if key_text in {"db", "path", "file_path", "source", "shared_evidence_db", "source_evidence_db", "agi_path"}:
            continue
        if isinstance(child, str) and _looks_private_path(child):
            continue
        safe[key_text] = child
    return safe


def _looks_private_path(value: str) -> bool:
    raw = value.strip()
    return raw.startswith(("/", "~")) or "/Users/" in raw or "/home/" in raw or "/tmp/" in raw or "/private/" in raw


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _source_count(source_catalog: JsonObject) -> int:
    source_summary = _object(source_catalog.get("summary"))
    value = source_summary.get("source_count")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return len(_list(source_catalog.get("sources")))


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)
