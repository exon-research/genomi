from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ....evidence.candidate_evidence import (
    LITERATURE_PLAUSIBILITY,
    SAME_GENE_OR_LOCUS,
)
from ....evidence.candidate_evidence import (
    source_local_ordering as evidence_source_local_ordering,
)
from ....retrieval import semantic as retrieval_semantic
from ...gwas import gwas
from .. import phenotype, targets

from ._base import (
    DRUG_TARGET_PRIOR,
    EVIDENCE_PRIORS,
    GENE_IDENTIFICATION_SCHEMA_VERSION,
    GWAS_PRIOR,
    LOCUS_TO_GENE_PRIOR,
    OPENTARGETS_GRAPHQL_API_URL,
    PHENOTYPE_PRIOR,
    _candidate_records_found,
    _clean_text,
    _coverage_note,
    _normalize_genes,
    _record_count,
    _source_review_plan,
    _strip_large_top_level,
)
from .trait_records import retrieve_trait_gene_records
from .locus import (
    _causal_gene_context,
    _compare_locus_to_gene_evidence,
    _downgrade_gwas_association_for_causal_context,
    _evidence_route,
    _explicit_gwas_gene_field_context,
    _filter_locus_source_records,
    _prior_fit,
)


def compare_candidate_evidence(
    evidence_db: str | Path | None = None,
    *,
    phenotype_text: str | None = None,
    task_text: str | None = None,
    hpo_ids: Iterable[str] | None = None,
    genes: Iterable[str] | None = None,
    drug: str | None = None,
    drug_class: str | None = None,
    mechanism: str | None = None,
    source_records: Iterable[dict[str, Any]] | None = None,
    phenotype_source_records: Iterable[dict[str, Any]] | None = None,
    gwas_source_records: Iterable[dict[str, Any]] | None = None,
    locus_source_records: Iterable[dict[str, Any]] | None = None,
    target_source_records: Iterable[dict[str, Any]] | None = None,
    search_stored_research: bool = True,
    use_hpo_annotations: bool = True,
    download_hpo_annotations: bool = True,
    hpo_gene_file: str | Path | None = None,
    hpo_gene_url: str = phenotype.HPO_GENE_ANNOTATION_URL,
    include_gwas: bool = True,
    gwas_api_url: str = gwas.GWAS_CATALOG_V2_API_URL,
    association_limit: int = 200,
    use_opentargets: bool = True,
    opentargets_api_url: str = OPENTARGETS_GRAPHQL_API_URL,
    limit: int = 25,
    semantic_context: object = None,
) -> dict[str, Any]:
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    normalized_genes = _normalize_genes(genes or [])
    query_phenotype = _clean_text(phenotype_text)
    supplied_hpo_ids = [str(item).strip() for item in (hpo_ids or []) if str(item).strip()]
    source_records_list = list(source_records or [])
    phenotype_source_records_list = list(phenotype_source_records) if phenotype_source_records is not None else None
    gwas_source_records_list = list(gwas_source_records) if gwas_source_records is not None else None
    locus_source_records_list = list(locus_source_records) if locus_source_records is not None else None
    target_source_records_list = list(target_source_records) if target_source_records is not None else None
    drug_context = {
        "drug": _clean_text(drug),
        "drug_class": _clean_text(drug_class),
        "mechanism": _clean_text(mechanism),
    }
    query_task_text = _clean_text(task_text)
    causal_gene_context = _causal_gene_context(query_task_text, query_phenotype) and not _explicit_gwas_gene_field_context(query_task_text)
    if not normalized_genes:
        raise ValueError("candidate evidence comparison requires candidate genes")
    if not query_phenotype and not supplied_hpo_ids and not any(drug_context.values()):
        raise ValueError("candidate evidence comparison requires phenotype, HPO IDs, drug, drug_class, or mechanism")

    evidence_route = _evidence_route(
        phenotype_text=query_phenotype,
        task_text=query_task_text,
        hpo_ids=supplied_hpo_ids,
        genes=normalized_genes,
        drug_context=drug_context,
        source_records=source_records_list,
        gwas_source_records=gwas_source_records_list,
        locus_source_records=locus_source_records_list,
        target_source_records=target_source_records_list,
    )
    active_priors = set(evidence_route["active_source_priors"])
    trait_gene_records = None
    if causal_gene_context and query_phenotype:
        trait_gene_records = retrieve_trait_gene_records(
            trait=query_phenotype,
            genes=normalized_genes,
            use_opentargets=use_opentargets,
            opentargets_api_url=opentargets_api_url,
            limit=limit,
            semantic_context=semantic_context,
        )
    component_results = _component_results(
        evidence_db,
        phenotype_text=query_phenotype,
        hpo_ids=supplied_hpo_ids,
        genes=normalized_genes,
        drug_context=drug_context,
        source_records=source_records_list,
        phenotype_source_records=phenotype_source_records_list,
        gwas_source_records=gwas_source_records_list,
        locus_source_records=locus_source_records_list,
        target_source_records=target_source_records_list,
        search_stored_research=search_stored_research,
        use_hpo_annotations=use_hpo_annotations,
        download_hpo_annotations=download_hpo_annotations,
        hpo_gene_file=hpo_gene_file,
        hpo_gene_url=hpo_gene_url,
        include_gwas=include_gwas,
        gwas_api_url=gwas_api_url,
        association_limit=association_limit,
        limit=limit,
        active_priors=active_priors,
        semantic_context=semantic_context,
    )
    if causal_gene_context and "gwas_catalog" in component_results:
        component_results["gwas_catalog"] = _downgrade_gwas_association_for_causal_context(component_results["gwas_catalog"])
    evidence_panels = {
        prior: _evidence_prior_panel(prior, normalized_genes, component_results.get(definition["component"]))
        for prior, definition in EVIDENCE_PRIORS.items()
        if prior in active_priors
    }
    prior_fit = _prior_fit(
        phenotype_text=query_phenotype,
        task_text=query_task_text,
        hpo_ids=supplied_hpo_ids,
        drug_context=drug_context,
        evidence_panels=evidence_panels,
        source_records=source_records_list,
        phenotype_source_records=phenotype_source_records_list,
        gwas_source_records=gwas_source_records_list,
        locus_source_records=locus_source_records_list,
        target_source_records=target_source_records_list,
    )
    status = "evidence_panels_returned" if any(panel["ranking"] for panel in evidence_panels.values()) else "no_matching_evidence_panels"
    if evidence_route["mode"] == "single_prior":
        status = "single_prior_evidence_returned" if any(panel["ranking"] for panel in evidence_panels.values()) else "single_prior_no_matching_evidence"
    comparison_state = _comparison_evidence_state(evidence_panels)
    coverage_state = _comparison_coverage_state(comparison_state)
    return {
        "status": status,
        "agent_decision_required": True,
        "evidence_state": comparison_state,
        "coverage_state": coverage_state,
        "evidence_route": evidence_route,
        "prior_fit": prior_fit,
        "decision_evidence": {
            prior: panel["decision_evidence"]
            for prior, panel in evidence_panels.items()
        },
        "evidence_panels": evidence_panels,
        "trait_gene_records": trait_gene_records,
        "candidate_evidence_matrix": _candidate_evidence_matrix(normalized_genes, evidence_panels),
        "cross_prior_summary": _cross_prior_summary(evidence_panels, prior_fit),
        "coverage": _cross_prior_coverage(evidence_panels),
        "source_coverage": _comparison_source_coverage(evidence_panels),
        "warnings": _warnings(evidence_panels, trait_gene_records),
        "details": {
            "schema": GENE_IDENTIFICATION_SCHEMA_VERSION,
            "query": {
                "phenotype": query_phenotype,
                "task_text": query_task_text,
                "hpo_ids": supplied_hpo_ids,
                "genes": normalized_genes,
                **{key: value for key, value in drug_context.items() if value},
            },
            "component_results": _component_details(component_results),
            "source_review_plan": _source_review_plan(query_phenotype, drug_context),
            "evidence_route": evidence_route,
            "causal_gene_context": causal_gene_context,
            "semantic_context": retrieval_semantic.term_usage_payload(
                semantic,
                streams=retrieval_semantic.retrieval_streams(
                    raw_query=semantic.raw_query,
                    host_terms=retrieval_semantic.search_terms(semantic),
                    exact_ids=normalized_genes,
                    source_native_filters=[query_phenotype, *supplied_hpo_ids],
                ),
            ) if semantic.has_hints else None,
        },
        "telemetry": {
            "tool_family": "candidate_gene",
            "evidence_route_mode": evidence_route["mode"],
            "trait_gene_records_status": trait_gene_records.get("status") if isinstance(trait_gene_records, dict) else None,
            "returned_answer": False,
            "agent_decision_required": True,
            "records_examined": sum(_record_count(result) for result in component_results.values()),
            "candidate_records_found": sum(_candidate_records_found(result) for result in component_results.values()),
        },
    }


def compare_gwas_catalog_gene_evidence(
    phenotype_text: str,
    genes: Iterable[str],
    *,
    api_url: str = gwas.GWAS_CATALOG_V2_API_URL,
    association_limit: int = 200,
    source_records: Iterable[dict[str, Any]] | None = None,
    task_text: str | None = None,
    evidence_intent: str | None = None,
    semantic_context: object = None,
) -> dict[str, Any]:
    result = gwas.compare_gwas_gene_evidence(
        phenotype_text,
        genes,
        api_url=api_url,
        association_limit=association_limit,
        source_records=source_records,
        task_text=task_text,
        evidence_intent=evidence_intent,
        semantic_context=semantic_context,
    )
    return source_prior_evidence_response(GWAS_PRIOR, result)


def compare_drug_target_gene_evidence(
    evidence_db: str | Path | None = None,
    *,
    drug: str | None = None,
    drug_class: str | None = None,
    indication: str | None = None,
    mechanism: str | None = None,
    genes: Iterable[str] | None = None,
    source_records: Iterable[dict[str, Any]] | None = None,
    search_stored_research: bool = True,
    limit: int = 25,
    semantic_context: object = None,
) -> dict[str, Any]:
    result = targets.compare_target_gene_evidence(
        evidence_db,
        drug=drug,
        drug_class=drug_class,
        indication=indication,
        mechanism=mechanism,
        genes=genes,
        source_records=source_records,
        search_stored_research=search_stored_research,
        limit=limit,
        semantic_context=semantic_context,
    )
    return source_prior_evidence_response(DRUG_TARGET_PRIOR, result)


def compare_phenotype_annotation_gene_evidence(
    evidence_db: str | Path | None = None,
    *,
    phenotype_text: str | None = None,
    phenotypes: Iterable[str] | None = None,
    hpo_ids: Iterable[str] | None = None,
    condition: str | None = None,
    genes: Iterable[str] | None = None,
    source_records: Iterable[dict[str, Any]] | None = None,
    search_stored_research: bool = True,
    use_hpo_annotations: bool = True,
    download_hpo_annotations: bool = True,
    hpo_gene_file: str | Path | None = None,
    hpo_gene_url: str = phenotype.HPO_GENE_ANNOTATION_URL,
    limit: int = 25,
    semantic_context: object = None,
) -> dict[str, Any]:
    result = phenotype.compare_gene_hpo_evidence(
        evidence_db,
        phenotype_text=phenotype_text,
        phenotypes=phenotypes,
        hpo_ids=hpo_ids,
        condition=condition,
        genes=genes,
        source_records=source_records,
        search_stored_research=search_stored_research,
        use_hpo_annotations=use_hpo_annotations,
        download_hpo_annotations=download_hpo_annotations,
        hpo_gene_file=hpo_gene_file,
        hpo_gene_url=hpo_gene_url,
        limit=limit,
        semantic_context=semantic_context,
    )
    return source_prior_evidence_response(PHENOTYPE_PRIOR, result)


def source_prior_evidence_response(source_prior: str, result: dict[str, Any]) -> dict[str, Any]:
    panel = _evidence_prior_panel(source_prior, _result_genes(result), result)
    top_ranked = next((row for row in panel.get("ranking") or [] if row.get("rank") == 1), None)
    return {
        "status": result.get("status"),
        "agent_decision_required": True,
        "source_prior": source_prior,
        "evidence_support_level": (top_ranked or {}).get("evidence_support_level", "none"),
        "top_observed_candidate": (top_ranked or {}).get("candidate"),
        "coverage_state": result.get("coverage_state") or ("data_returned" if panel.get("ranking") else "in_scope_empty"),
        "source_local_ordering": panel["source_local_ordering"],
        "ranking": panel["ranking"],
        "decision_evidence": panel["decision_evidence"],
        "evidence_records": panel["evidence_records"],
        "unmatched_candidates": panel["unmatched_candidates"],
        "coverage": panel["coverage"],
        "limitations": panel["limitations"],
        "conflicts": panel["conflicts"],
        "warnings": result.get("warnings") or [],
        "details": {
            "evidence_view": result.get("evidence_view"),
            "candidate_matrix": result.get("candidate_matrix"),
            "source_result": _strip_large_top_level(result),
        },
        "telemetry": {
            "tool_family": "candidate_gene",
            "source_prior": source_prior,
            "returned_answer": False,
            "agent_decision_required": True,
            "records_examined": _record_count(result),
            "candidate_records_found": _candidate_records_found(result),
        },
    }


def _component_results(
    evidence_db: str | Path | None,
    *,
    phenotype_text: str,
    hpo_ids: list[str],
    genes: list[str],
    drug_context: dict[str, str],
    source_records: Iterable[dict[str, Any]] | None,
    phenotype_source_records: Iterable[dict[str, Any]] | None,
    gwas_source_records: Iterable[dict[str, Any]] | None,
    locus_source_records: Iterable[dict[str, Any]] | None,
    target_source_records: Iterable[dict[str, Any]] | None,
    search_stored_research: bool,
    use_hpo_annotations: bool,
    download_hpo_annotations: bool,
    hpo_gene_file: str | Path | None,
    hpo_gene_url: str,
    include_gwas: bool,
    gwas_api_url: str,
    association_limit: int,
    limit: int,
    active_priors: set[str] | None = None,
    semantic_context: object = None,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    requested_priors = active_priors or set(EVIDENCE_PRIORS)
    phenotype_records = phenotype_source_records if phenotype_source_records is not None else source_records
    if PHENOTYPE_PRIOR in requested_priors and (phenotype_text or hpo_ids):
        results["phenotype"] = phenotype.compare_gene_hpo_evidence(
            evidence_db,
            phenotype_text=phenotype_text,
            hpo_ids=hpo_ids,
            genes=genes,
            source_records=phenotype_records,
            search_stored_research=search_stored_research,
            use_hpo_annotations=use_hpo_annotations,
            download_hpo_annotations=download_hpo_annotations,
            hpo_gene_file=hpo_gene_file,
            hpo_gene_url=hpo_gene_url,
            limit=limit,
            semantic_context=semantic_context,
        )
    if GWAS_PRIOR in requested_priors and include_gwas and phenotype_text:
        results["gwas_catalog"] = gwas.compare_gwas_gene_evidence(
            phenotype_text,
            genes,
            association_limit=association_limit,
            api_url=gwas_api_url,
            source_records=gwas_source_records,
            semantic_context=semantic_context,
        )
    locus_records = list(locus_source_records) if locus_source_records is not None else _filter_locus_source_records(source_records)
    if LOCUS_TO_GENE_PRIOR in requested_priors and locus_records:
        results["locus_to_gene"] = _compare_locus_to_gene_evidence(genes, locus_records)
    if DRUG_TARGET_PRIOR in requested_priors and any(drug_context.values()):
        results["drug_target"] = targets.compare_target_gene_evidence(
            evidence_db,
            drug=drug_context["drug"],
            drug_class=drug_context["drug_class"],
            indication=phenotype_text,
            mechanism=drug_context["mechanism"],
            genes=genes,
            source_records=target_source_records if target_source_records is not None else source_records,
            search_stored_research=search_stored_research,
            limit=limit,
            semantic_context=semantic_context,
        )
    return results


def _evidence_prior_panel(source_prior: str, genes: list[str], result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        ordering = evidence_source_local_ordering(
            [],
            valid_for=EVIDENCE_PRIORS[source_prior]["title"],
            not_valid_for="Answer selection; this source prior was not requested.",
        )
        return {
            "status": "not_requested",
            "source_prior": source_prior,
            "ranking": [],
            "source_local_ordering": ordering,
            "decision_evidence": {
                "top_observed_candidate": None,
                "top_observed_evidence": None,
                "ranked_candidate_evidence": [],
            },
            "evidence_records": [],
            "unmatched_candidates": genes,
            "coverage": {"records_examined": 0, "candidate_records_found": 0},
            "limitations": [EVIDENCE_PRIORS[source_prior]["title"] + " was not requested for this query."],
            "conflicts": [],
        }
    matrix = result.get("candidate_matrix") if isinstance(result.get("candidate_matrix"), list) else []
    ranking = [_ranking_row(source_prior, row) for row in matrix if isinstance(row, dict) and row.get("rank") is not None]
    ranking.sort(key=lambda row: (row["rank"], str(row["candidate"]).casefold()))
    evidence_records = _panel_evidence_records(source_prior, matrix)
    answer_supported = _panel_answer_supported(source_prior, ranking, result)
    decision_records = _panel_decision_evidence(source_prior, ranking, matrix, answer_supported=answer_supported)
    ordering = _panel_source_local_ordering(source_prior, ranking, result)
    return {
        "status": _panel_status(result, ranking),
        "source_prior": source_prior,
        "ranking": ranking,
        "source_local_ordering": ordering,
        "decision_evidence": decision_records,
        "evidence_records": evidence_records,
        "unmatched_candidates": [
            str(row.get("candidate_id"))
            for row in matrix
            if isinstance(row, dict) and row.get("rank") is None
        ],
        "coverage": {
            "records_examined": _record_count(result),
            "candidate_records_found": _candidate_records_found(result),
            "coverage_note": _coverage_note(result),
        },
        "limitations": _panel_limitations(source_prior, ranking, result),
        "conflicts": [],
    }


def _ranking_row(source_prior: str, row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("supporting_evidence") if isinstance(row.get("supporting_evidence"), list) else []
    best_record = evidence[0] if evidence and isinstance(evidence[0], dict) else {}
    return {
        "candidate": row.get("candidate_id"),
        "rank": row.get("rank"),
        "support": _support_label(source_prior, row),
        "score": row.get("score", 0),
        "evidence_support_level": row.get("evidence_support_level", "none"),
        "evidence_count": len(evidence),
        "evidence_discriminators": _row_evidence_discriminators(source_prior, row),
        "best_record": best_record,
        "why_ranked_here": _why_ranked_here(source_prior, row, best_record),
        "limitations": _limitations(source_prior, row),
    }


def _panel_evidence_records(source_prior: str, matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in matrix:
        if not isinstance(row, dict):
            continue
        candidate = row.get("candidate_id")
        evidence = row.get("supporting_evidence") if isinstance(row.get("supporting_evidence"), list) else []
        for index, record in enumerate(evidence, start=1):
            if not isinstance(record, dict):
                continue
            records.append(
                {
                    "candidate": candidate,
                    "source_prior": source_prior,
                    "support": _support_label(source_prior, row),
                    "record_index": index,
                    "record": record,
                }
            )
    return records


def _panel_decision_evidence(
    source_prior: str,
    ranking: list[dict[str, Any]],
    matrix: list[dict[str, Any]],
    *,
    answer_supported: bool = True,
) -> dict[str, Any]:
    rows_by_candidate = {
        str(row.get("candidate_id")): row
        for row in matrix
        if isinstance(row, dict)
    }
    ranked_evidence = []
    for ranked in ranking:
        candidate = str(ranked.get("candidate"))
        source_row = rows_by_candidate.get(candidate, {})
        ranked_evidence.append(
            {
                "candidate": candidate,
                "source_prior": source_prior,
                "rank": ranked.get("rank"),
                "score": ranked.get("score"),
                "evidence_support_level": ranked.get("evidence_support_level"),
                "support": ranked.get("support"),
                "why_ranked_here": ranked.get("why_ranked_here") or [],
                "evidence_discriminators": ranked.get("evidence_discriminators") or {},
                "evidence_trace": _ranked_evidence_trace(source_prior, ranked, source_row),
                "supporting_evidence": source_row.get("supporting_evidence") or [],
                "counter_evidence": source_row.get("counter_evidence") or [],
                "limitations": ranked.get("limitations") or [],
            }
        )
    top = ranked_evidence[0] if ranked_evidence else None
    if not answer_supported:
        top = None
    return {
        "top_observed_candidate": top.get("candidate") if top else None,
        "top_observed_evidence": top,
        "ranked_candidate_evidence": ranked_evidence,
    }


def _panel_answer_supported(source_prior: str, ranking: list[dict[str, Any]], result: dict[str, Any]) -> bool:
    evidence_state = _panel_evidence_state(source_prior, ranking, result)
    return bool(ranking) and evidence_state == "decision_grade_evidence"


def _panel_evidence_state(source_prior: str, ranking: list[dict[str, Any]], result: dict[str, Any]) -> str:
    status = str(result.get("status") or "")
    if status == "source_unavailable":
        return "source_unavailable"
    if status in {"wrong_evidence_regime", "association_only_not_causal_gene_evidence"}:
        return "wrong_evidence_regime"
    if not ranking:
        return "no_evidence_in_genomi"
    if source_prior == GWAS_PRIOR and str(result.get("summary", {}).get("evidence_regime") or "") == "association_only_not_causal":
        return "wrong_evidence_regime"
    if all(str(row.get("evidence_support_level") or "none") in {"none", "low"} or row.get("support") in {SAME_GENE_OR_LOCUS, LITERATURE_PLAUSIBILITY} for row in ranking):
        return "ambiguous_or_weak_evidence"
    return "decision_grade_evidence"


def _panel_source_local_ordering(source_prior: str, ranking: list[dict[str, Any]], result: dict[str, Any]) -> dict[str, Any]:
    if result.get("source_local_ordering") and isinstance(result.get("source_local_ordering"), dict):
        return dict(result["source_local_ordering"])
    not_valid_for = "Host-agent answer selection unless this source prior matches the task and decision_evidence.top_observed_candidate is set."
    if source_prior == GWAS_PRIOR:
        not_valid_for = "Causal-gene selection; GWAS Catalog gene fields are association annotations, not causal-gene assignments."
    return evidence_source_local_ordering(
        ranking,
        valid_for=EVIDENCE_PRIORS[source_prior]["title"],
        not_valid_for=not_valid_for,
    )


def _ranked_evidence_trace(source_prior: str, ranked: dict[str, Any], source_row: dict[str, Any]) -> dict[str, Any]:
    supporting_evidence = source_row.get("supporting_evidence") if isinstance(source_row.get("supporting_evidence"), list) else []
    counter_evidence = source_row.get("counter_evidence") if isinstance(source_row.get("counter_evidence"), list) else []
    return {
        "candidate": ranked.get("candidate"),
        "source_prior": source_prior,
        "score_basis": {
            "rank": ranked.get("rank"),
            "score": ranked.get("score"),
            "evidence_support_level": ranked.get("evidence_support_level"),
            "support": ranked.get("support"),
            "why_ranked_here": ranked.get("why_ranked_here") or [],
            "evidence_discriminators": ranked.get("evidence_discriminators") or {},
        },
        "supporting_evidence_count": len(supporting_evidence),
        "counter_evidence_count": len(counter_evidence),
        "supporting_record_ids": _record_ids(supporting_evidence),
        "counter_record_ids": _record_ids(counter_evidence),
    }


def _record_ids(records: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        value = record.get("record_id") or record.get("source_id") or record.get("association_id") or record.get("id")
        if value is None:
            continue
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        ids.append(text)
    return ids


def _panel_limitations(source_prior: str, ranking: list[dict[str, Any]], result: dict[str, Any]) -> list[str]:
    limitations = {limitation for row in ranking for limitation in row.get("limitations", [])}
    if not ranking:
        limitations.add(_coverage_note(result))
    if source_prior == GWAS_PRIOR:
        limitations.add("GWAS Catalog associations do not by themselves identify causal genes.")
    elif source_prior == LOCUS_TO_GENE_PRIOR:
        limitations.add("Locus-to-gene evidence links a locus or variant to a candidate gene; it does not by itself prove disease causality.")
    elif source_prior == DRUG_TARGET_PRIOR:
        limitations.add("Drug-target mechanism evidence answers drug-target questions, not phenotype association questions.")
    elif source_prior == PHENOTYPE_PRIOR:
        limitations.add("Phenotype annotation evidence answers curation/overlap questions, not drug mechanism questions.")
    return sorted(limitations)


def _support_label(source_prior: str, row: dict[str, Any]) -> str:
    if source_prior == GWAS_PRIOR:
        return str(row.get("best_evidence_lane") or "gwas_catalog_association")
    if source_prior == LOCUS_TO_GENE_PRIOR:
        return str(row.get("best_evidence_lane") or row.get("best_source_family") or "locus_to_gene")
    if source_prior == DRUG_TARGET_PRIOR:
        return str(row.get("best_source_family") or row.get("best_evidence_lane") or "drug_target_mechanism")
    if source_prior == PHENOTYPE_PRIOR:
        return str(row.get("best_evidence_lane") or "phenotype_annotation")
    return str(row.get("best_evidence_lane") or "source_evidence")


def _why_ranked_here(source_prior: str, row: dict[str, Any], best_record: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("answerability") == "direct_source_supported":
        reasons.append("candidate has direct source-supported evidence under this prior")
    elif row.get("answerability") == "adjacent_source_supported":
        reasons.append("candidate has adjacent source support under this prior")
    elif row.get("answerability") == "plausibility_only":
        reasons.append("candidate has plausibility evidence under this prior")
    if row.get("phenotype_overlap_count") is not None:
        reasons.append(f"phenotype overlap count: {row['phenotype_overlap_count']}")
    source_gene_match = row.get("source_gene_match") if isinstance(row.get("source_gene_match"), dict) else {}
    if source_gene_match.get("field"):
        reasons.append(f"candidate is named in GWAS Catalog {source_gene_match['field']}")
    phenotype_detail = row.get("phenotype_match_detail") if isinstance(row.get("phenotype_match_detail"), dict) else {}
    if phenotype_detail.get("matched_hpo_ids"):
        reasons.append("matched HPO IDs: " + ", ".join(phenotype_detail["matched_hpo_ids"]))
    if phenotype_detail.get("matched_phenotypes"):
        reasons.append("matched phenotype terms: " + ", ".join(phenotype_detail["matched_phenotypes"]))
    pvalue = best_record.get("p_value") if best_record.get("p_value") is not None else best_record.get("pvalue")
    if pvalue is not None:
        reasons.append(f"best p-value: {pvalue}")
    if not reasons:
        reasons.append("ranked by source-specific scoring for this prior")
    return reasons


def _row_evidence_discriminators(source_prior: str, row: dict[str, Any]) -> dict[str, Any]:
    discriminators: dict[str, Any] = {
        "best_evidence_lane": row.get("best_evidence_lane"),
        "best_source_family": row.get("best_source_family"),
        "best_source_origin": row.get("best_source_origin"),
    }
    if source_prior == GWAS_PRIOR and isinstance(row.get("source_gene_match"), dict):
        discriminators["source_gene_match"] = row["source_gene_match"]
    if source_prior == PHENOTYPE_PRIOR and isinstance(row.get("phenotype_match_detail"), dict):
        discriminators["phenotype_match_detail"] = row["phenotype_match_detail"]
    return {key: value for key, value in discriminators.items() if value not in (None, {}, [])}


def _limitations(source_prior: str, row: dict[str, Any]) -> list[str]:
    limitations: list[str] = []
    if source_prior == GWAS_PRIOR:
        limitations.append("GWAS association evidence is not causal mechanism evidence")
    if source_prior == LOCUS_TO_GENE_PRIOR:
        limitations.append("locus-to-gene evidence is not phenotype or therapeutic mechanism evidence")
    if source_prior == PHENOTYPE_PRIOR:
        limitations.append("phenotype overlap is not a diagnosis")
    if source_prior == DRUG_TARGET_PRIOR:
        limitations.append("drug-target evidence does not establish clinical efficacy or personal response")
    if row.get("answerability") != "direct_source_supported":
        limitations.append("not direct-source-supported for an identifier-only answer")
    return limitations


def _panel_status(result: dict[str, Any], ranking: list[dict[str, Any]]) -> str:
    status = str(result.get("status") or "")
    if status == "source_unavailable":
        return "unavailable"
    if ranking:
        return "available"
    if status.startswith("no_") or status == "no_supported_candidate":
        return "no_matching_records"
    return status or "available"


def _cross_prior_summary(evidence_panels: dict[str, dict[str, Any]], prior_fit: dict[str, Any] | None = None) -> dict[str, Any]:
    top_candidates = {
        prior: panel["ranking"][0]["candidate"]
        for prior, panel in evidence_panels.items()
        if panel.get("ranking")
    }
    answer_supported = {
        prior: panel["decision_evidence"]["top_observed_candidate"]
        for prior, panel in evidence_panels.items()
        if isinstance(panel.get("decision_evidence"), dict) and panel["decision_evidence"].get("top_observed_candidate")
    }
    conflicts = _cross_prior_conflicts(evidence_panels)
    summary = {
        "priors_returning_rankings": list(top_candidates),
        "priors_disagree": bool(conflicts),
        "top_candidates_by_prior": top_candidates,
        "answer_supported_top_candidates_by_prior": answer_supported,
        "conflicts": conflicts,
    }
    if prior_fit:
        summary["context_aligned_prior"] = prior_fit.get("context_aligned_prior")
        summary["context_fit_support_level"] = prior_fit.get("support_level")
    return summary


def _cross_prior_conflicts(evidence_panels: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    top_by_prior = {
        prior: panel["ranking"][0]["candidate"]
        for prior, panel in evidence_panels.items()
        if panel.get("ranking")
    }
    if len(set(top_by_prior.values())) <= 1:
        return []
    return [
        {
            "type": "top_candidate_disagreement",
            "top_candidates_by_prior": top_by_prior,
            "agent_action": "Choose the evidence prior required by the question before answering.",
        }
    ]


def _candidate_evidence_matrix(genes: list[str], evidence_panels: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for gene in genes:
        row = {"candidate": gene, "priors": {}}
        for prior, panel in evidence_panels.items():
            ranking = next((item for item in panel.get("ranking", []) if item.get("candidate") == gene), None)
            row["priors"][prior] = {
                "rank": ranking.get("rank") if ranking else None,
                "support": ranking.get("support") if ranking else "not_supported",
                "evidence_support_level": ranking.get("evidence_support_level") if ranking else "none",
                "evidence_count": ranking.get("evidence_count") if ranking else 0,
                "evidence_discriminators": ranking.get("evidence_discriminators") if ranking else {},
                "limitations": ranking.get("limitations") if ranking else [],
            }
        matrix.append(row)
    return matrix


def _cross_prior_coverage(evidence_panels: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        prior: panel.get("coverage", {})
        for prior, panel in evidence_panels.items()
    }


def _comparison_evidence_state(evidence_panels: dict[str, dict[str, Any]]) -> str:
    if not evidence_panels:
        return "no_priors_requested"
    if not any(panel.get("ranking") for panel in evidence_panels.values()):
        return "no_evidence_in_genomi"
    answer_supported = [
        prior
        for prior, panel in evidence_panels.items()
        if isinstance(panel.get("decision_evidence"), dict) and panel["decision_evidence"].get("top_observed_candidate")
    ]
    if answer_supported:
        return "source_local_evidence_available"
    return "weak_or_wrong_regime_evidence_only"


def _comparison_coverage_state(evidence_state: str) -> str:
    if evidence_state in {"source_local_evidence_available", "weak_or_wrong_regime_evidence_only"}:
        return "data_returned"
    if evidence_state == "no_evidence_in_genomi":
        return "in_scope_empty"
    return "out_of_scope_for_input"


def _comparison_source_coverage(evidence_panels: dict[str, dict[str, Any]]) -> dict[str, Any]:
    consulted_empty: list[str] = []
    consulted_unavailable: list[str] = []
    for prior, panel in evidence_panels.items():
        status = str(panel.get("status") or "")
        if status == "unavailable":
            consulted_unavailable.append(prior)
        elif status == "not_requested":
            continue
        elif status in {"no_matching_records"} or not panel.get("ranking"):
            consulted_empty.append(prior)
    return {
        "sources_consulted_and_empty": consulted_empty,
        "sources_consulted_but_unavailable": consulted_unavailable,
        "sources_not_integrated": [
            "OpenTargets Genetics trait-to-gene prioritisation",
            "GeneCards trait-gene summaries",
            "OMIM/Orphanet disease-gene curation outside loaded HPO files",
            "paper-supplement screen tables outside supplied source records",
        ],
    }


def _warnings(evidence_panels: dict[str, dict[str, Any]], trait_gene_records: dict[str, Any] | None = None) -> list[str]:
    warnings: list[str] = []
    if not any(panel["ranking"] for panel in evidence_panels.values()):
        warnings.append("No evidence prior returned a ranked candidate.")
    if _cross_prior_summary(evidence_panels)["priors_disagree"]:
        warnings.append("Evidence priors disagree; choose the prior that matches the question before answering.")
    if isinstance(trait_gene_records, dict):
        status = trait_gene_records.get("status")
        evidence_state = trait_gene_records.get("evidence_state")
        if evidence_state == "association_only_not_causal":
            warnings.append("Causal-gene context has only association-only evidence; do not answer from mapped/reported/nearest-gene support alone.")
        elif status == "no_trait_gene_records":
            warnings.append("Causal-gene context has no native trait-to-gene records in integrated sources.")
    return warnings


def _component_details(component_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for name, result in component_results.items():
        details[name] = {
            "status": result.get("status"),
            "summary": result.get("summary"),
            "evidence_view": result.get("evidence_view"),
            "candidate_matrix": result.get("candidate_matrix"),
        }
    return details


def _result_genes(result: dict[str, Any]) -> list[str]:
    query = result.get("query") if isinstance(result.get("query"), dict) else {}
    genes = query.get("genes")
    if isinstance(genes, list):
        return _normalize_genes(genes)
    matrix = result.get("candidate_matrix") if isinstance(result.get("candidate_matrix"), list) else []
    return _normalize_genes(row.get("candidate_id") for row in matrix if isinstance(row, dict))
