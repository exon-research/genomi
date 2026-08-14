from __future__ import annotations

from typing import Any

from . import portal_store

JsonObject = dict[str, Any]


def add_decode_dashboard_artifact(project_id: str, result: JsonObject, *, frame_id: str | None = None) -> JsonObject | None:
    serve = result.get("serve") if isinstance(result.get("serve"), dict) else {}
    external_url = serve.get("url") if isinstance(serve.get("url"), str) else None
    dashboard_path = result.get("dashboard_path") if isinstance(result.get("dashboard_path"), str) else None
    return portal_store.add_artifact(
        project_id,
        kind="decode_dashboard",
        renderer="decode_dashboard",
        title="Genomi Report",
        operation="decode.render_dashboard",
        result=result,
        frame_id=frame_id,
        file_path=dashboard_path,
        external_url=external_url,
        summary=_dashboard_summary(result),
        summary_lines=_dashboard_summary_lines(result),
        open_label="Open report",
    )


def _dashboard_summary_lines(result: JsonObject) -> list[str]:
    lines: list[str] = [str(result.get("status") or "unknown")]
    rendered = result.get("panels_rendered")
    empty = result.get("panels_empty")
    if isinstance(rendered, list):
        lines.append(f"{len(rendered)} section{'s' if len(rendered) != 1 else ''} rendered")
    if isinstance(empty, list):
        lines.append(f"{len(empty)} empty")
    headline = result.get("headline")
    if isinstance(headline, str) and headline:
        lines.append(headline)
    return lines


def _dashboard_summary(result: JsonObject) -> JsonObject:
    summary: JsonObject = {}
    for key in ("headline", "panels_rendered", "panels_empty", "defaults_applied"):
        if result.get(key) is not None:
            summary[key] = result.get(key)
    evidence_build = result.get("evidence_build")
    if isinstance(evidence_build, dict):
        summary["evidence_build"] = {
            key: evidence_build.get(key)
            for key in ("panels_ready", "panels_blocked", "panels_empty", "panels_running", "panels_failed", "panel_states")
            if evidence_build.get(key) is not None
        }
    return summary
