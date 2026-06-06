"""Code-owned evidence assembly for the Genomi Dashboard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...evidence import envelope as evidence_envelope
from .dashboard import PANEL_KEYS
from .panel_adapters import is_native_empty_panel, native_panel_rows

JsonObject = dict[str, Any]
OperationRunner = Callable[[str, JsonObject], JsonObject]

DEFAULT_PANELS: tuple[str, ...] = PANEL_KEYS
_BLOCKED_STATUSES = {
    "requires_library_install",
    "requires_score_import",
    "source_unavailable",
    "out_of_scope_for_input",
    "skipped_missing_library",
    "skipped_tool_unavailable",
    "tool_unavailable",
    "position_aware_pharmcat_export_required",
    "no_pharmcat_vcf_records",
    "active_genome_index_input_unavailable",
    "explicit_pharmcat_executable_unavailable",
    "no_pharmcat_artifacts",
    "not_assessed",
    "blocked_missing_library",
    "materialization_incomplete",
}


def build_dashboard_evidence(
    *,
    params: JsonObject | None = None,
    run_operation: OperationRunner,
    active_genome_index_context: JsonObject | None = None,
) -> JsonObject:
    """Gather native panel evidence through existing operations.

    This function owns decode orchestration without becoming an AGI reader. The
    supplied operation runner performs the usual registry auth/readiness gates.
    """

    safe_params = dict(params or {})
    panels = _selected_panels(safe_params.get("panels"))
    evidence: JsonObject = {}
    render_params: JsonObject = {"evidence": evidence}
    panel_states: list[JsonObject] = []
    consulted_operations: list[str] = []

    def run(operation: str, op_params: JsonObject | None = None) -> JsonObject:
        consulted_operations.append(operation)
        return run_operation(operation, dict(op_params or {}))

    if "overview" in panels:
        result = run("active_genome_index.summarize")
        result = _overview_with_active_context(result, active_genome_index_context)
        _store_panel(evidence, panel_states, "overview", "active_genome_index.summarize", result)

    clinvar_result: JsonObject | None = None
    if {"variants", "variants_all"} & set(panels):
        clinvar_result = run("clinvar.scan_candidates", {})
        if "variants" in panels:
            _store_panel(evidence, panel_states, "variants", "clinvar.scan_candidates", clinvar_result)
        if "variants_all" in panels:
            source = _variants_all_source(clinvar_result)
            if source:
                render_params["variants_all_source"] = source
                panel_states.append(
                    _panel_state(
                        "variants_all",
                        "clinvar.scan_candidates",
                        "deferred_source",
                        source_path_available=True,
                    )
                )
            else:
                _store_panel(evidence, panel_states, "variants_all", "clinvar.scan_candidates", clinvar_result)

    if "pgx" in panels:
        if _bool_param(safe_params, "include_pgx", True):
            pgx_params: JsonObject = {}
            if safe_params.get("pgx_timeout_seconds") is not None:
                pgx_params["timeout_seconds"] = int(safe_params["pgx_timeout_seconds"])
            result = run("pharmacogenomics.run_pharmcat", pgx_params)
            _store_panel(evidence, panel_states, "pgx", "pharmacogenomics.run_pharmcat", result)
        else:
            panel_states.append(_panel_state("pgx", None, "skipped_by_parameter"))

    if "risk" in panels:
        risk_results = _build_risk_panel(
            run=run,
            risk_score_ids=_string_list(safe_params.get("risk_score_ids")),
            risk_score_limit=int(safe_params.get("risk_score_limit") or 5),
        )
        evidence["risk"] = risk_results
        panel_states.append(
            _panel_state(
                "risk",
                "prs.calculate_score",
                _list_panel_status("risk", risk_results),
                row_count=len([item for item in risk_results if not is_native_empty_panel("risk", [item])]),
            )
        )

    if "ancestry" in panels:
        result = run("ancestry.estimate_population_context")
        _store_panel(evidence, panel_states, "ancestry", "ancestry.estimate_population_context", result)

    if "nutrigenomics" in panels:
        result = _build_nutrigenomics_panel(
            run=run,
            domain_ids=_string_list(safe_params.get("nutrigenomics_domain_ids")),
        )
        _store_panel(evidence, panel_states, "nutrigenomics", "nutrigenomics.retrieve_domain_markers", result)

    if "journal" in panels:
        result = run("journal.search_entries", {"limit": int(safe_params.get("journal_limit") or 8)})
        evidence["journal"] = result
        panel_states.append(
            _panel_state(
                "journal",
                "journal.search_entries",
                "data_returned" if result.get("entries") else "in_scope_empty",
                row_count=len(result.get("entries") or []),
            )
        )

    panels_with_evidence = [key for key in PANEL_KEYS if key in evidence and not _is_empty_panel_value(key, evidence[key])]
    if "variants_all" in panels and render_params.get("variants_all_source") and "variants_all" not in panels_with_evidence:
        panels_with_evidence.append("variants_all")
    panels_empty = [key for key in panels if key not in panels_with_evidence]
    panels_blocked = [
        state["panel"]
        for state in panel_states
        if str(state.get("status") or "") in _BLOCKED_STATUSES
    ]
    result = {
        "status": "completed",
        "panels_requested": list(panels),
        "panels_ready": panels_with_evidence,
        "panels_empty": panels_empty,
        "panels_blocked": panels_blocked,
        "panel_states": panel_states,
        "render_params": render_params,
    }
    result["evidence_envelope"] = _evidence_envelope(
        panels=panels,
        panels_ready=panels_with_evidence,
        panels_empty=panels_empty,
        panels_blocked=panels_blocked,
        consulted_operations=consulted_operations,
    )
    return result


def _build_risk_panel(
    *,
    run: Callable[[str, JsonObject | None], JsonObject],
    risk_score_ids: list[str],
    risk_score_limit: int,
) -> list[JsonObject]:
    score_ids = list(risk_score_ids)
    if not score_ids:
        listed = run("prs.list_imported_scores")
        score_ids = _imported_score_ids(listed)[: max(1, risk_score_limit)]
    if not score_ids:
        return [{"status": "requires_score_import"}]
    return [run("prs.calculate_score", {"pgs_id": score_id}) for score_id in score_ids]


def _build_nutrigenomics_panel(
    *,
    run: Callable[[str, JsonObject | None], JsonObject],
    domain_ids: list[str],
) -> JsonObject:
    selected_domains = list(domain_ids)
    if not selected_domains:
        listed = run("nutrigenomics.list_domains")
        selected_domains = _nutrigenomics_domain_ids(listed)
    markers: list[JsonObject] = []
    domain_results: list[JsonObject] = []
    for domain_id in selected_domains:
        result = run("nutrigenomics.retrieve_domain_markers", {"domain_id": domain_id})
        domain_results.append(result)
        markers.extend(item for item in result.get("markers") or [] if isinstance(item, dict))
    coverage_state = "data_returned" if markers else "in_scope_empty"
    return {
        "capability": "nutrigenomics",
        "coverage_state": coverage_state,
        "domains": selected_domains,
        "markers": markers,
        "domain_results": domain_results,
    }


def _store_panel(
    evidence: JsonObject,
    panel_states: list[JsonObject],
    panel: str,
    operation: str,
    result: JsonObject,
) -> None:
    evidence[panel] = result
    panel_states.append(
        _panel_state(
            panel,
            operation,
            _panel_status(panel, result),
            row_count=_row_count(panel, result),
        )
    )


def _overview_with_active_context(result: JsonObject, active: JsonObject | None) -> JsonObject:
    if not isinstance(active, dict):
        return result
    context = {
        key: active.get(key)
        for key in (
            "agi_source_format",
            "agi_source_kind",
            "sample_slug",
            "genome_build",
        )
        if active.get(key) not in (None, "", [], "auto")
    }
    if not context:
        return result
    return {**result, **context}


def _panel_state(
    panel: str,
    operation: str | None,
    status: str,
    *,
    row_count: int | None = None,
    source_path_available: bool | None = None,
) -> JsonObject:
    state: JsonObject = {"panel": panel, "status": status}
    if operation:
        state["source_operation"] = operation
    if row_count is not None:
        state["row_count"] = row_count
    if source_path_available is not None:
        state["source_path_available"] = bool(source_path_available)
    return state


def _panel_status(panel: str, value: Any) -> str:
    if _is_empty_panel_value(panel, value):
        if isinstance(value, dict):
            status = str(value.get("status") or value.get("coverage_state") or "")
            if status in _BLOCKED_STATUSES:
                return status
            envelope = value.get("evidence_envelope") if isinstance(value.get("evidence_envelope"), dict) else {}
            finding_state = str(envelope.get("finding_state") or "")
            if finding_state in _BLOCKED_STATUSES:
                return finding_state
            if status:
                return status
        return "in_scope_empty"
    return "data_returned"


def _list_panel_status(panel: str, values: list[JsonObject]) -> str:
    if not values:
        return "in_scope_empty"
    statuses = [str(item.get("status") or "") for item in values if isinstance(item, dict)]
    for status in statuses:
        if status in _BLOCKED_STATUSES:
            return status
    if all(is_native_empty_panel(panel, [item]) for item in values):
        return "in_scope_empty"
    return "data_returned"


def _is_empty_panel_value(panel: str, value: Any) -> bool:
    if value in (None, "", [], {}):
        return True
    if panel == "journal" and isinstance(value, dict):
        entries = value.get("entries")
        return isinstance(entries, list) and not entries
    return is_native_empty_panel(panel, value)


def _row_count(panel: str, value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    rows = native_panel_rows(panel, value)
    return len(rows) if rows is not None else None


def _selected_panels(value: Any) -> tuple[str, ...]:
    if value in (None, "", []):
        return DEFAULT_PANELS
    requested = _string_list(value)
    invalid = [panel for panel in requested if panel not in PANEL_KEYS]
    if invalid:
        raise ValueError(
            "panels contains unknown dashboard panel(s): "
            f"{', '.join(invalid)}. Valid panels: {', '.join(PANEL_KEYS)}."
        )
    return tuple(panel for panel in PANEL_KEYS if panel in set(requested))


def _variants_all_source(result: JsonObject | None) -> str | None:
    if not isinstance(result, dict):
        return None
    source = result.get("input") or result.get("matches")
    return str(source) if source not in (None, "") and str(result.get("status") or "") in {"completed", "cached"} else None


def _evidence_envelope(
    *,
    panels: tuple[str, ...],
    panels_ready: list[str],
    panels_empty: list[str],
    panels_blocked: list[str],
    consulted_operations: list[str],
) -> JsonObject:
    common = {
        "operation": "decode.build_dashboard_evidence",
        "query_scope": {"panels": list(panels)},
        "personal_context": {"uses_personal_dna": True, "source": "active_genome_index"},
        "coverage": {"consulted_sources": _unique(consulted_operations), "libraries": [], "unavailable_sources": []},
        "observations": {
            "panels_ready": panels_ready,
            "panels_empty": panels_empty,
            "panels_blocked": panels_blocked,
        },
    }
    if panels_ready:
        return evidence_envelope.evidence_present(
            **common,
            answer_readiness=evidence_envelope.SCOPED_ANSWER_ONLY,
        )
    if panels_blocked:
        return evidence_envelope.not_assessed(
            **common,
            reason="requested dashboard panels were blocked by missing setup or unavailable sources",
        )
    return evidence_envelope.empty_consulted_scope(**common)


def _imported_score_ids(result: JsonObject) -> list[str]:
    ids: list[str] = []
    for item in result.get("scores") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("pgs_id") or item.get("score_id") or item.get("id")
        if value not in (None, ""):
            ids.append(str(value))
    return _unique(ids)


def _nutrigenomics_domain_ids(result: JsonObject) -> list[str]:
    ids: list[str] = []
    for item in result.get("domains") or []:
        if isinstance(item, dict) and item.get("domain_id"):
            ids.append(str(item["domain_id"]))
    return _unique(ids)


def _string_list(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    raw = value if isinstance(value, list) else [value]
    return [str(item) for item in raw if item not in (None, "")]


def _bool_param(params: JsonObject, key: str, default: bool) -> bool:
    return bool(params[key]) if key in params else default


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
