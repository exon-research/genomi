"""Code-owned evidence assembly for the Genomi Dashboard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...evidence import envelope as evidence_envelope
from ...runtime import background_jobs
from .dashboard import PANEL_KEYS
from .panel_adapters import is_native_empty_panel, native_panel_rows

JsonObject = dict[str, Any]
OperationRunner = Callable[[str, JsonObject], JsonObject]

DEFAULT_PANELS: tuple[str, ...] = PANEL_KEYS
DEFAULT_PGX_REVIEW_TARGET_LIMIT = 12
DEFAULT_RISK_REVIEW_TYPES: tuple[str, ...] = ("carrier_review", "observed_condition_review")
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
_RUNNING_STATUSES = {"in_progress"}
_FAILED_STATUSES = {"failed"}


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
    pgx_job = _start_pgx_background_job(active_genome_index_context) if "pgx" in panels else None
    if pgx_job is not None:
        consulted_operations.append("pharmacogenomics.run_pharmcat")

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

    pharmcat_result: JsonObject | None = None
    if "pgx" in panels:
        if pgx_job is None:
            pharmcat_result = run("pharmacogenomics.run_pharmcat", {})
            _append_panel_result(evidence, panel_states, "pgx", "pharmacogenomics.run_pharmcat", pharmcat_result)
        else:
            pharmcat_result, job_state = _collect_background_panel_job(pgx_job)
            if pharmcat_result is not None:
                _append_panel_result(evidence, panel_states, "pgx", "pharmacogenomics.run_pharmcat", pharmcat_result)
            else:
                panel_states.append(_background_panel_state("pgx", "pharmacogenomics.run_pharmcat", job_state))
        for target in _pgx_review_targets(
            explicit_targets=safe_params.get("pgx_review_targets"),
            pharmcat_result=pharmcat_result,
            limit=_positive_int(safe_params.get("pgx_review_target_limit"), DEFAULT_PGX_REVIEW_TARGET_LIMIT),
        ):
            review_result = run("pharmacogenomics.review_medication", target)
            _append_panel_result(evidence, panel_states, "pgx", "pharmacogenomics.review_medication", review_result)

    if "risk" in panels:
        evidence["risk"] = []
        risk_review_types = _risk_review_types(safe_params)
        if clinvar_result is None and risk_review_types:
            clinvar_result = run("clinvar.scan_candidates", {})
        if risk_review_types and clinvar_result is not None:
            _record_panel_result_state(panel_states, "risk", "clinvar.scan_candidates", clinvar_result)
        _append_risk_score_results(
            evidence=evidence,
            panel_states=panel_states,
            run=run,
            risk_score_ids=_string_list(safe_params.get("risk_score_ids")),
            risk_score_limit=_positive_int(safe_params.get("risk_score_limit"), 5),
        )
        for request in _risk_review_requests(review_types=risk_review_types, clinvar_result=clinvar_result):
            review_result = run("phenotype.plan_risk_investigation", request)
            _append_panel_result(evidence, panel_states, "risk", "phenotype.plan_risk_investigation", review_result)

    if "ancestry" in panels:
        result = run("ancestry.estimate_population_context")
        _store_panel(evidence, panel_states, "ancestry", "ancestry.estimate_population_context", result)

    if "nutrigenomics" in panels:
        result = _build_nutrigenomics_panel(
            run=run,
            domain_ids=_string_list(safe_params.get("nutrigenomics_domain_ids")),
        )
        _store_panel(evidence, panel_states, "nutrigenomics", "nutrigenomics.retrieve_domain_markers", result)

    panels_with_evidence = [key for key in PANEL_KEYS if key in evidence and not _is_empty_panel_value(key, evidence[key])]
    if "variants_all" in panels and render_params.get("variants_all_source") and "variants_all" not in panels_with_evidence:
        panels_with_evidence.append("variants_all")
    panels_empty = [key for key in panels if key not in panels_with_evidence]
    panels_blocked = _unique([
        state["panel"]
        for state in panel_states
        if str(state.get("status") or "") in _BLOCKED_STATUSES
    ])
    panels_running = _unique([
        state["panel"]
        for state in panel_states
        if str(state.get("status") or "") in _RUNNING_STATUSES
    ])
    panels_failed = _unique([
        state["panel"]
        for state in panel_states
        if str(state.get("status") or "") in _FAILED_STATUSES
    ])
    result = {
        "status": "completed",
        "panels_requested": list(panels),
        "panels_ready": panels_with_evidence,
        "panels_empty": panels_empty,
        "panels_blocked": panels_blocked,
        "panels_running": panels_running,
        "panels_failed": panels_failed,
        "panel_states": panel_states,
        "render_params": render_params,
    }
    result["evidence_envelope"] = _evidence_envelope(
        panels=panels,
        panels_ready=panels_with_evidence,
        panels_empty=panels_empty,
        panels_blocked=panels_blocked,
        panels_running=panels_running,
        panels_failed=panels_failed,
        consulted_operations=consulted_operations,
    )
    return result


def _start_pgx_background_job(active: JsonObject | None) -> JsonObject | None:
    params = _background_active_genome_index_params(active)
    if params is None or not background_jobs.background_enabled():
        return None
    digest = background_jobs.operation_params_digest("pharmacogenomics.run_pharmcat", params)
    completed = background_jobs.find_latest_job(
        "pharmacogenomics.run_pharmcat",
        digest,
        statuses={"completed"},
    )
    if isinstance(completed, dict) and isinstance(completed.get("result"), dict):
        return completed
    try:
        return background_jobs.start_operation_job("pharmacogenomics.run_pharmcat", params)
    except Exception as exc:
        return {
            "status": "failed",
            "operation": "pharmacogenomics.run_pharmcat",
            "error": {"code": "background_job_start_failed", "message": str(exc)},
        }


def _background_active_genome_index_params(active: JsonObject | None) -> JsonObject | None:
    if not isinstance(active, dict):
        return None
    agi_id = active.get("agi_id")
    if agi_id not in (None, ""):
        return {"agi_id": str(agi_id)}
    agi_path = active.get("agi_path")
    if agi_path not in (None, ""):
        return {"agi_path": str(agi_path)}
    return None


def _collect_background_panel_job(job: JsonObject) -> tuple[JsonObject | None, JsonObject]:
    job_id = str(job.get("job_id") or "")
    current = background_jobs.wait_for_job(job_id, timeout_seconds=0.0) if job_id else job
    public_state = background_jobs.public_job_status(current, timeout_seconds=0.0)
    if current.get("status") == "completed" and isinstance(current.get("result"), dict):
        return current["result"], public_state
    return None, public_state


def _background_panel_state(panel: str, operation: str, job_state: JsonObject) -> JsonObject:
    state = _panel_state(panel, operation, str(job_state.get("status") or "in_progress"))
    for key in (
        "job_id",
        "check",
        "message",
        "created_at",
        "started_at",
        "heartbeat_at",
        "seconds_since_heartbeat",
        "error",
    ):
        value = job_state.get(key)
        if value not in (None, "", []):
            state[key] = value
    return state


def _pgx_review_targets(*, explicit_targets: Any, pharmcat_result: Any, limit: int) -> list[JsonObject]:
    targets: list[JsonObject] = []
    targets.extend(_explicit_pgx_review_targets(explicit_targets))
    targets.extend(_pharmcat_medication_review_targets(pharmcat_result))
    deduped: list[JsonObject] = []
    seen: set[tuple[str, ...]] = set()
    for target in targets:
        normalized = _normalize_pgx_review_target(target)
        if not normalized:
            continue
        key = _pgx_review_target_key(normalized)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if len(deduped) >= max(1, int(limit)):
            break
    return deduped


def _explicit_pgx_review_targets(value: Any) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _pharmcat_medication_review_targets(result: Any) -> list[JsonObject]:
    if not isinstance(result, dict):
        return []
    block = result.get("medication_review_targets")
    if not isinstance(block, dict):
        return []
    return [dict(item) for item in block.get("targets") or [] if isinstance(item, dict)]


def _normalize_pgx_review_target(target: JsonObject) -> JsonObject | None:
    allowed = {
        "drug",
        "gene",
        "rsid",
        "atc_code",
        "drugbank_id",
        "indication",
        "dose",
        "current_medications",
        "allergies_or_contraindications",
        "known_genotype",
        "known_diplotype",
        "known_phenotype",
        "known_activity_score",
        "known_pgx_source",
        "source_sample_pgx_row_id",
        "semantic_context",
        "limit",
    }
    normalized = {key: value for key, value in target.items() if key in allowed and value not in (None, "", [])}
    if not any(normalized.get(key) for key in ("drug", "gene", "rsid", "atc_code", "drugbank_id")):
        return None
    normalized.setdefault("include_active_genome_index", True)
    return normalized


def _pgx_review_target_key(target: JsonObject) -> tuple[str, ...]:
    return tuple(
        str(target.get(field) or "").casefold()
        for field in (
            "drug",
            "gene",
            "rsid",
            "atc_code",
            "drugbank_id",
            "known_diplotype",
            "known_phenotype",
            "known_activity_score",
            "source_sample_pgx_row_id",
        )
    )


def _risk_review_types(params: JsonObject) -> list[str]:
    if "risk_review_types" not in params or params.get("risk_review_types") in (None, ""):
        values = list(DEFAULT_RISK_REVIEW_TYPES)
    elif params.get("risk_review_types") == []:
        values = []
    else:
        raw = params.get("risk_review_types")
        values = [str(item) for item in (raw if isinstance(raw, list) else [raw]) if item not in (None, "")]
    allowed = {"carrier_review", "observed_condition_review", "rare_disease", "cancer_risk"}
    invalid = [value for value in values if value not in allowed]
    if invalid:
        raise ValueError(
            "risk_review_types contains unsupported phenotype review mode(s): "
            f"{', '.join(invalid)}. Valid values: {', '.join(sorted(allowed))}."
        )
    return _unique(values)


def _risk_review_requests(*, review_types: list[str], clinvar_result: JsonObject | None) -> list[JsonObject]:
    if not review_types:
        return []
    matches = _clinvar_matches_source(clinvar_result)
    requests: list[JsonObject] = []
    for review_type in review_types:
        params = {
            "investigation_type": review_type,
            "include_active_genome_index": True,
        }
        if matches:
            params["matches"] = matches
        requests.append(params)
    return requests


def _clinvar_matches_source(result: JsonObject | None) -> str | None:
    if not isinstance(result, dict):
        return None
    source = result.get("input") or result.get("matches")
    if source in (None, ""):
        return None
    return str(source)


def _append_risk_score_results(
    *,
    evidence: JsonObject,
    panel_states: list[JsonObject],
    run: Callable[[str, JsonObject | None], JsonObject],
    risk_score_ids: list[str],
    risk_score_limit: int,
) -> None:
    score_ids = list(risk_score_ids)
    if not score_ids:
        listed = run("prs.list_imported_scores")
        score_ids = _imported_score_ids(listed)[: max(1, risk_score_limit)]
    if not score_ids:
        _append_panel_result(evidence, panel_states, "risk", "prs.calculate_score", {"status": "requires_score_import"})
        return
    for score_id in score_ids:
        result = run("prs.calculate_score", {"pgs_id": score_id})
        _append_panel_result(evidence, panel_states, "risk", "prs.calculate_score", result)


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


def _append_panel_result(
    evidence: JsonObject,
    panel_states: list[JsonObject],
    panel: str,
    operation: str,
    result: JsonObject,
) -> None:
    evidence.setdefault(panel, [])
    if not isinstance(evidence[panel], list):
        evidence[panel] = [evidence[panel]]
    evidence[panel].append(result)
    panel_states.append(
        _panel_state(
            panel,
            operation,
            _panel_status(panel, result),
            row_count=_row_count(panel, result),
        )
    )


def _record_panel_result_state(
    panel_states: list[JsonObject],
    panel: str,
    operation: str,
    result: JsonObject,
) -> None:
    panel_states.append(
        _panel_state(
            panel,
            operation,
            _panel_status(panel, result),
            row_count=_row_count(panel, result),
        )
    )


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


def _is_empty_panel_value(panel: str, value: Any) -> bool:
    if value in (None, "", [], {}):
        return True
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
    panels_running: list[str],
    panels_failed: list[str],
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
            "panels_running": panels_running,
            "panels_failed": panels_failed,
        },
    }
    if panels_ready:
        return evidence_envelope.evidence_present(
            **common,
            answer_readiness=evidence_envelope.SCOPED_ANSWER_ONLY,
        )
    if panels_blocked or panels_running or panels_failed:
        return evidence_envelope.not_assessed(
            **common,
            reason="requested dashboard panels were blocked, running, or failed before renderable evidence was available",
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


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _string_list(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    raw = value if isinstance(value, list) else [value]
    return [str(item) for item in raw if item not in (None, "")]


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
