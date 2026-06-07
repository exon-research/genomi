from __future__ import annotations

from typing import Any

JsonObject = dict[str, Any]

EMPTY_NATIVE_STATUSES = frozenset(
    {
        "requires_library_install",
        "source_unavailable",
        "out_of_scope_for_input",
        "skipped_missing_library",
        "skipped_tool_unavailable",
        "insufficient_overlap",
        "domain_id_required",
        "unknown_domain",
        "domain_out_of_scope_by_construction",
        "invalid_evidence_tier",
    }
)
EMPTY_PGX_STATUSES = EMPTY_NATIVE_STATUSES | frozenset(
    {
        "position_aware_pharmcat_export_required",
        "no_pharmcat_vcf_records",
        "active_genome_index_input_unavailable",
        "explicit_pharmcat_executable_unavailable",
        "no_pharmcat_artifacts",
    }
)
EMPTY_PRS_STATUSES = frozenset(
    {
        "requires_score_import",
        "requires_library_install",
        "out_of_scope_for_input",
        "source_unavailable",
    }
)
EMPTY_COVERAGE_STATES = frozenset({"in_scope_empty", "out_of_scope_for_input"})


_BLOCKED_SETUP_STATUSES = frozenset(
    {
        "requires_library_install",
        "blocked_missing_library",
        "skipped_missing_library",
        "skipped_tool_unavailable",
        "tool_unavailable",
        "explicit_pharmcat_executable_unavailable",
    }
)
_OUT_OF_SCOPE_STATUSES = frozenset(
    {
        "out_of_scope_for_input",
        "domain_id_required",
        "unknown_domain",
        "domain_out_of_scope_by_construction",
        "invalid_evidence_tier",
    }
)
_CHECKED_EMPTY_STATUSES = frozenset({"in_scope_empty", "not_observed_in_consulted_scope"})
_NO_PHARMCAT_RESULT_STATUSES = frozenset(
    {
        "no_pharmcat_vcf_records",
        "active_genome_index_input_unavailable",
        "no_pharmcat_artifacts",
    }
)


def normalize_dashboard_panel_states(panel_states: Any, panel_keys: tuple[str, ...]) -> list[JsonObject]:
    if not isinstance(panel_states, list):
        return []
    allowed = set(panel_keys)
    normalized: list[JsonObject] = []
    for item in panel_states:
        if not isinstance(item, dict):
            continue
        panel = item.get("panel")
        if panel not in allowed:
            continue
        state: JsonObject = {"panel": panel}
        for key in ("status", "source_operation"):
            value = item.get(key)
            if value not in (None, "", []):
                state[key] = str(value)
        for key in ("job_id", "message", "created_at", "started_at", "heartbeat_at"):
            value = item.get(key)
            if value not in (None, "", []):
                state[key] = str(value)
        check = item.get("check")
        if isinstance(check, dict):
            state["check"] = check
        error = item.get("error")
        if isinstance(error, dict):
            state["error"] = error
        seconds_since_heartbeat = item.get("seconds_since_heartbeat")
        if isinstance(seconds_since_heartbeat, (int, float)):
            state["seconds_since_heartbeat"] = seconds_since_heartbeat
        row_count = item.get("row_count")
        if isinstance(row_count, int):
            state["row_count"] = row_count
        if "source_path_available" in item:
            state["source_path_available"] = bool(item.get("source_path_available"))
        normalized.append(state)
    return normalized


def normalize_requested_dashboard_panels(panels_requested: Any, panel_keys: tuple[str, ...]) -> list[str]:
    if not isinstance(panels_requested, list):
        return []
    allowed = set(panel_keys)
    seen: set[str] = set()
    normalized: list[str] = []
    for panel in panels_requested:
        if panel in allowed and panel not in seen:
            seen.add(panel)
            normalized.append(panel)
    return normalized


def build_dashboard_metadata(
    *,
    panel_states: Any,
    panels_requested: Any,
    panels_rendered: list[str],
    panel_keys: tuple[str, ...],
    rendered_at: str,
) -> JsonObject:
    normalized_states = normalize_dashboard_panel_states(panel_states, panel_keys)
    requested = normalize_requested_dashboard_panels(panels_requested, panel_keys)
    metadata: JsonObject = {"renderedAt": rendered_at}
    if normalized_states:
        metadata["panelStates"] = normalized_states
    if requested:
        metadata["panelsRequested"] = requested

    unavailable = _unavailable_panels(
        normalized_states=normalized_states,
        panels_requested=requested,
        panels_rendered=panels_rendered,
        panel_keys=panel_keys,
    )
    if unavailable:
        metadata["unavailablePanels"] = unavailable
    return metadata


def _unavailable_panels(
    *,
    normalized_states: list[JsonObject],
    panels_requested: list[str],
    panels_rendered: list[str],
    panel_keys: tuple[str, ...],
) -> list[JsonObject]:
    rendered = set(panels_rendered)
    requested = set(panels_requested)
    states_by_panel = {
        str(state["panel"]): state
        for state in normalized_states
        if state.get("panel") in panel_keys
    }
    unavailable: list[JsonObject] = []
    for panel in panel_keys:
        if panel in rendered:
            continue
        state = states_by_panel.get(panel)
        if panels_requested and panel not in requested:
            unavailable.append({"panel": panel, "state": "not_selected"})
            continue
        source_status = str(state.get("status") or "") if state else ""
        item: JsonObject = {"panel": panel, "state": _unavailable_state(panel, source_status)}
        if source_status:
            item["source_status"] = source_status
        for key in ("job_id", "message", "check", "heartbeat_at", "seconds_since_heartbeat", "error"):
            value = state.get(key) if state else None
            if value not in (None, "", []):
                item[key] = value
        unavailable.append(item)
    return unavailable


def _unavailable_state(panel: str, source_status: str) -> str:
    if source_status == "in_progress":
        return "running"
    if source_status == "failed":
        return "failed"
    if source_status == "position_aware_pharmcat_export_required":
        return "blocked_position_aware_export"
    if source_status == "requires_score_import":
        return "missing_scores"
    if source_status == "insufficient_overlap":
        return "insufficient_overlap"
    if source_status in _BLOCKED_SETUP_STATUSES:
        return "blocked_setup"
    if source_status == "source_unavailable":
        return "source_unavailable"
    if source_status in _OUT_OF_SCOPE_STATUSES:
        return "out_of_scope"
    if source_status in _CHECKED_EMPTY_STATUSES:
        return "checked_empty"
    if panel == "pgx" and source_status in _NO_PHARMCAT_RESULT_STATUSES:
        return "no_pharmcat_results"
    return "no_renderable_evidence"
