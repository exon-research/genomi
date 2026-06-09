from __future__ import annotations

from ...capabilities.decode import dashboard as decode_dashboard
from ...capabilities.decode import evidence_builder as decode_evidence_builder
from ...capabilities.functional_genomics import evidence_acquisition, geo, screen
from ...capabilities.journal import journal
from ...capabilities.research import intent_research
from ...active_genome_index.active_genome_index import ActiveGenomeIndexNeed
from .agi_access import open_agi, resolve_agi_record
from .coerce import (
    _bool,
    _int,
    _list_dict,
    _list_str,
    _path,
    _str,
    _with_context,
)
from .errors import JsonObject, OperationError

_DECODE_AGI_PANEL_OPERATIONS = {
    "active_genome_index.summarize",
    "clinvar.scan_candidates",
    "pharmacogenomics.run_pharmcat",
    "ancestry.estimate_population_context",
    "prs.calculate_score",
}
_DECODE_BUILD_PARAM_KEYS = {
    "nutrigenomics_domain_ids",
    "output",
    "panels",
    "risk_score_ids",
    "risk_score_limit",
}


def _screen_retrieve_experiment_records(params: JsonObject) -> JsonObject:
    return screen.retrieve_public_screen_records(
        context=_str(params, "context"),
        genes=_list_str(params, "genes"),
        organism=params.get("organism"),
        cell_line=params.get("cell_line"),
        perturbation=params.get("perturbation"),
        assay=params.get("assay"),
        phenotype=params.get("phenotype"),
        sources=_list_str(params, "perturbation_sources"),
        biogrid_orcs_access_key=params.get("biogrid_orcs_access_key"),
        depmap_gene_effect_url=params.get("depmap_gene_effect_url"),
        depmap_model_url=params.get("depmap_model_url"),
        limit=_int(params, "limit", 100),
        semantic_context=params.get("semantic_context"),
    )


def _screen_query_geo(params: JsonObject) -> JsonObject:
    return geo.query_geo_datasets(
        context=_str(params, "context"),
        genes=_list_str(params, "genes"),
        organism=params.get("organism"),
        cell_line=params.get("cell_line"),
        perturbation=params.get("perturbation"),
        assay=params.get("assay"),
        phenotype=params.get("phenotype"),
        accession=params.get("accession"),
        limit=_int(params, "limit", 25),
        semantic_context=params.get("semantic_context"),
        ncbi_api_key=params.get("ncbi_api_key"),
        ncbi_email=params.get("ncbi_email"),
        ncbi_tool=params.get("ncbi_tool"),
    )


def _screen_import_table_evidence_records(params: JsonObject) -> JsonObject:
    column_map = params.get("column_map") if isinstance(params.get("column_map"), dict) else None
    return evidence_acquisition.extract_screen_table_evidence_records(
        _path(params, "table"),
        context=_str(params, "context"),
        genes=_list_str(params, "genes"),
        column_map=column_map,
        delimiter=params.get("delimiter"),
        source_title=params.get("source_title"),
        source_url=params.get("source_url"),
        source_type=params.get("source_type"),
        organism=params.get("organism"),
        cell_line=params.get("cell_line"),
        perturbation=params.get("perturbation"),
        assay=params.get("assay"),
        phenotype=params.get("phenotype"),
        limit=_int(params, "limit", 500),
    )


def _screen_answer_gene(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True, allow_shared_db_without_vcf=True)
    return intent_research.answer_screen_gene_context(
        _path(resolved, "db"),
        context=_str(resolved, "context"),
        genes=_list_str(resolved, "genes"),
        source_records=_list_dict(resolved, "source_records"),
        organism=resolved.get("organism"),
        cell_line=resolved.get("cell_line"),
        perturbation=resolved.get("perturbation"),
        assay=resolved.get("assay"),
        phenotype=resolved.get("phenotype"),
        search_stored_research=_bool(resolved, "search_stored_research", True),
        retrieve_native=_bool(resolved, "retrieve_native", True),
        perturbation_sources=_list_str(resolved, "perturbation_sources"),
        biogrid_orcs_access_key=resolved.get("biogrid_orcs_access_key"),
        depmap_gene_effect_url=resolved.get("depmap_gene_effect_url"),
        depmap_model_url=resolved.get("depmap_model_url"),
        limit=_int(resolved, "limit", 25),
        semantic_context=resolved.get("semantic_context"),
    )


def _journal_error(exc: journal.JournalError) -> OperationError:
    return OperationError(exc.code, exc.message)


def _journal_append_entry(params: JsonObject) -> JsonObject:
    links = _list_dict(params, "evidence_links") or _list_dict(params, "links")
    single_link = params.get("link")
    if not links and isinstance(single_link, dict):
        links = [dict(single_link)]
    try:
        return journal.append_entry(
            scope=params.get("scope"),
            entry_id=params.get("entry_id"),
            entry_type=params.get("entry_type"),
            content=params.get("content"),
            title=params.get("title"),
            tags=params.get("tags"),
            target=params.get("target"),
            evidence_links=links,
            decision_status=params.get("decision_status"),
            created_by=params.get("created_by"),
            amendment_type=params.get("amendment_type"),
            rationale=params.get("rationale"),
        )
    except journal.JournalError as exc:
        raise _journal_error(exc) from exc


def _journal_search_entries(params: JsonObject) -> JsonObject:
    try:
        return journal.search_entries(
            scope=params.get("scope"),
            text=params.get("text") or params.get("query"),
            target=params.get("target"),
            tag=params.get("tag"),
            tags=params.get("tags"),
            entry_type=params.get("entry_type"),
            limit=_int(params, "limit", 25),
            semantic_context=params.get("semantic_context"),
        )
    except journal.JournalError as exc:
        raise _journal_error(exc) from exc


def _journal_summarize_notebook(params: JsonObject) -> JsonObject:
    try:
        return journal.summarize_notebook(
            scope=params.get("scope"),
            limit=_int(params, "limit", 8),
        )
    except journal.JournalError as exc:
        raise _journal_error(exc) from exc


def _journal_export_memory_artifact(params: JsonObject) -> JsonObject:
    try:
        return journal.export_memory_artifact(
            scope=params.get("scope"),
            include_private_evidence=_bool(params, "include_private_evidence"),
        )
    except journal.JournalError as exc:
        raise _journal_error(exc) from exc


def _run_decode_panel_operation(name: str, params: JsonObject | None = None) -> JsonObject:
    from .table import call_operation

    return call_operation(name, params or {})


def _decode_panel_runner_for_target(agi_id: str | None):
    def _run(name: str, params: JsonObject | None = None) -> JsonObject:
        safe_params = dict(params or {})
        if agi_id and name in _DECODE_AGI_PANEL_OPERATIONS:
            safe_params.setdefault("agi_id", agi_id)
        return _run_decode_panel_operation(name, safe_params)

    return _run


def _decode_build_dashboard_evidence(params: JsonObject) -> JsonObject:
    resolved = _with_context(params)
    target = resolve_agi_record(params)
    if target is None:
        raise OperationError(
            "active_genome_index_required",
            "Select or parse an Active Genome Index before building Genomi Dashboard evidence.",
        )
    reader = open_agi(
        need=ActiveGenomeIndexNeed.REFERENCE,
        action="building Genomi Dashboard evidence from Active Genome Index artifacts",
        params=params,
    )
    reader.ensure_ready()
    target = resolve_agi_record(params, require_approved=True) or target
    target_agi_id = str(target.get("agi_id") or "") or None
    try:
        return decode_evidence_builder.build_dashboard_evidence(
            params=resolved,
            run_operation=_decode_panel_runner_for_target(target_agi_id),
            active_genome_index_context=target,
        )
    except ValueError as exc:
        raise OperationError("invalid_params", str(exc)) from exc


def _decode_render_dashboard(params: JsonObject) -> JsonObject:
    resolved = _with_context(params)
    # The dashboard writes a transient view artifact and consumes personal
    # evidence. Require an Active Genome Index, then auth-gate via open_agi
    # (approves a supplied source, raises approval_required for a
    # selected-but-unapproved AGI) — the one central session gate.
    target = resolve_agi_record(params)
    if target is None:
        raise OperationError(
            "active_genome_index_required",
            "Select or parse an Active Genome Index before rendering the Genomi Dashboard.",
        )
    reader = open_agi(
        need=ActiveGenomeIndexNeed.REFERENCE,
        action="rendering the Genomi Dashboard from Active Genome Index evidence",
        params=params,
    )
    reader.ensure_ready()
    target = resolve_agi_record(params, require_approved=True) or target

    output = resolved.get("output")
    if not output:
        work_dir = target.get("work_dir") if isinstance(target, dict) else None
        output = str(decode_dashboard.default_output_path(work_dir))

    build_result = _decode_build_dashboard_evidence(_decode_build_params(resolved))
    render_params = build_result.get("render_params") if isinstance(build_result, dict) else None
    if not isinstance(render_params, dict) or not isinstance(render_params.get("evidence"), dict):
        raise OperationError(
            "invalid_dashboard_evidence",
            "decode.build_dashboard_evidence did not return renderable evidence.",
        )
    evidence = render_params["evidence"]
    variants_all_source = render_params.get("variants_all_source")

    try:
        result = decode_dashboard.render_dashboard(
            evidence=evidence,
            mode="full",
            output=output,
            variants_all_source=variants_all_source,
            panel_states=build_result.get("panel_states", []),
            panels_requested=build_result.get("panels_requested", []),
            start_server=True,
        )
    except decode_dashboard.DashboardRenderError as exc:
        raise OperationError(exc.code, exc.message) from exc
    if build_result is not None:
        result["evidence_build"] = {
            "panels_ready": build_result.get("panels_ready", []),
            "panels_empty": build_result.get("panels_empty", []),
            "panels_blocked": build_result.get("panels_blocked", []),
            "panels_running": build_result.get("panels_running", []),
            "panels_failed": build_result.get("panels_failed", []),
            "panel_states": build_result.get("panel_states", []),
        }
        envelope = _decode_render_envelope(build_result)
        if envelope is not None:
            result["evidence_envelope"] = envelope
    return result


def _decode_render_envelope(build_result: JsonObject) -> JsonObject | None:
    envelope = build_result.get("evidence_envelope")
    if not isinstance(envelope, dict):
        return None
    rendered = dict(envelope)
    rendered["operation"] = "decode.render_dashboard"
    finding_state = str(rendered.get("finding_state") or "not_assessed")
    answer_readiness = str(rendered.get("answer_readiness") or "cannot_answer_yet")
    rendered["headline"] = f"decode.render_dashboard: {finding_state} · {answer_readiness}"
    return rendered


def _decode_build_params(params: JsonObject) -> JsonObject:
    return {
        key: value
        for key, value in params.items()
        if key in _DECODE_BUILD_PARAM_KEYS
    }
