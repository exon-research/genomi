from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ....evidence.candidate_evidence import (
    DIRECT_SOURCE_MATCH,
    EXACT_TRAIT_MATCH,
    LITERATURE_PLAUSIBILITY,
    NEARBY_TRAIT_MATCH,
    PATHWAY_PLAUSIBILITY,
    answerability_for_lane,
    apply_evidence_view,
    empty_lanes,
    evidence_support_level_for_score,
    evidence_view,
    lane,
)
from ....evidence.task_profiles import SCREEN_GENE_RETRIEVAL
from ....retrieval import semantic as retrieval_semantic
from ..evidence_acquisition import (
    direct_perturbation_support,
    normalize_screen_source_record,
    verified_context_matches,
    verified_gene_match,
)
from .helpers import (
    _SCREEN_SOURCE_TOKENS,
    _clean_text,
    _meaningful_tokens,
    _normalize_genes,
    _screen_semantic_usage,
    _semantic_screen_fields,
    _tokens,
)


def compare_screen_experiment_evidence(
    *,
    context: str,
    genes: Iterable[str],
    source_records: Iterable[dict[str, Any]] | None = None,
    organism: str | None = None,
    cell_line: str | None = None,
    perturbation: str | None = None,
    assay: str | None = None,
    phenotype: str | None = None,
    semantic_context: object = None,
) -> dict[str, Any]:
    """Rank candidate genes against explicit source records for screen-style tasks."""

    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    semantic_fields = _semantic_screen_fields(semantic)
    normalized_genes = _normalize_genes(genes)
    if not normalized_genes:
        raise ValueError("at least one candidate gene is required")
    query = {
        "context": _clean_text(context),
        "genes": normalized_genes,
        "organism": _clean_text(organism) or semantic_fields.get("organism", ""),
        "cell_line": _clean_text(cell_line) or semantic_fields.get("cell_line", ""),
        "perturbation": _clean_text(perturbation) or semantic_fields.get("perturbation", ""),
        "assay": _clean_text(assay) or semantic_fields.get("assay", ""),
        "phenotype": _clean_text(phenotype) or semantic_fields.get("phenotype", ""),
        "semantic_context_terms": retrieval_semantic.search_terms(semantic),
    }
    records = [
        normalize_screen_source_record(
            record,
            context=query["context"],
            genes=normalized_genes,
            organism=query["organism"],
            cell_line=query["cell_line"],
            perturbation=query["perturbation"],
            assay=query["assay"],
            phenotype=query["phenotype"],
        )
        for record in (source_records or [])
        if isinstance(record, dict)
    ]
    matrix = _candidate_matrix(normalized_genes, query, records)
    top_ranked = next((candidate for candidate in matrix if candidate["rank"] == 1), None)
    selected = top_ranked if top_ranked and top_ranked.get("answerability") == "direct_source_supported" else None
    status = _result_status(selected, records)
    if not records:
        status = "no_source_records"
    decision_policy = {
        "policy_id": "screen_gene_candidate_matrix_v1",
        "ranking_order": [
            "source-record gene match plus screen-context exactness",
            "source verification status",
            "source family strength",
            "context token overlap",
            "candidate identifier for deterministic tie-breaking",
        ],
        "rule": "Only source-verified screen or perturbation records can create direct evidence lanes; generic literature is capped below direct support.",
    }
    warnings = _selection_warnings(selected, matrix, records)
    evidence_state = _screen_evidence_state(status, records, matrix)
    coverage_state = _screen_coverage_state(records, matrix)
    source_coverage = _screen_source_coverage(status, records)
    view = evidence_view(
        task_profile=SCREEN_GENE_RETRIEVAL,
        query=query,
        candidate_matrix=matrix,
        top_observed_candidate=selected,
        infer_top_observed_candidate=False,
        evidence_policy=decision_policy,
        warnings=warnings,
        evidence_state=evidence_state,
        coverage_state=coverage_state,
        source_coverage=source_coverage,
    )
    payload = {
        "ok": True,
        "status": status,
        "query": query,
        "summary": {
            "candidate_gene_count": len(normalized_genes),
            "source_record_count": len(records),
            "supported_candidate_count": sum(1 for candidate in matrix if candidate["score"] > 0),
            "top_observed_candidate": selected["candidate_id"] if selected else None,
            "candidate_to_review": top_ranked["candidate_id"] if top_ranked else None,
            "top_observed_support_level": selected["evidence_support_level"] if selected else "none",
        },
        "task_profile": SCREEN_GENE_RETRIEVAL.to_dict(),
        "decision_policy": decision_policy,
        "coverage_state": coverage_state,
        "source_coverage": source_coverage,
    }
    if semantic.has_hints:
        payload["semantic_context"] = _screen_semantic_usage(semantic, records, query)
    return apply_evidence_view(payload, view, operation="functional_genomics.compare_gene_perturbation")


def _screen_coverage_state(records: list[dict[str, Any]], matrix: list[dict[str, Any]]) -> str:
    if not records:
        return "out_of_scope_for_input"
    if any(candidate.get("rank") is not None for candidate in matrix):
        return "data_returned"
    return "in_scope_empty"


def _screen_evidence_state(status: str, records: list[dict[str, Any]], matrix: list[dict[str, Any]]) -> str:
    if status == "completed":
        return "decision_grade_evidence"
    if not records:
        return "no_source_records_supplied"
    if not any(candidate.get("score") for candidate in matrix):
        return "no_matching_perturbation_context"
    return "weak_or_wrong_context_screen_evidence"


def _screen_source_coverage(status: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sources_consulted_and_empty": [],
        "sources_consulted_but_unavailable": [],
        "sources_not_integrated": [
            "PubMed paper discovery",
            "GEO/ArrayExpress supplemental screen tables",
            "Mendeley, Zenodo, and journal supplementary screen table discovery",
        ],
        "perturbation_context_status": status,
    }


def _candidate_matrix(
    genes: list[str],
    query: dict[str, str],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = [_candidate_row(gene, query, records) for gene in genes]
    ranked = sorted(
        [candidate for candidate in candidates if candidate["score"] > 0],
        key=lambda candidate: (-float(candidate["score"]), candidate["candidate_id"].casefold()),
    )
    rank_by_candidate = {candidate["candidate_id"]: index + 1 for index, candidate in enumerate(ranked)}
    selected = ranked[0] if ranked else None
    for candidate in candidates:
        candidate["rank"] = rank_by_candidate.get(candidate["candidate_id"])
        candidate["why_not_selected"] = _why_not_selected(candidate, selected)
    return sorted(candidates, key=lambda candidate: (candidate["rank"] is None, candidate["rank"] or 10**9, candidate["candidate_id"].casefold()))


def _candidate_row(gene: str, query: dict[str, str], records: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = [_score_record(gene, query, record) for record in records]
    supported = [item for item in evidence if item["score"] > 0]
    best = max(
        supported,
        key=lambda item: (float(item["score"]), int(item["context_match_count"]), item["source_family"], item["record_id"]),
        default=None,
    )
    lanes = empty_lanes()
    best_lane = best["evidence_lane"] if best else None
    score = float(best["score"]) if best else 0.0
    if best and best_lane:
        lanes[best_lane] = lane(
            best_lane,
            status="present",
            score=score,
            source=best["source_title"],
            matched_text=best["matched_text"],
            source_id=best["record_id"],
            note=best["reason"],
        )
        if best_lane == DIRECT_SOURCE_MATCH:
            lanes[DIRECT_SOURCE_MATCH] = lane(
                DIRECT_SOURCE_MATCH,
                status="present",
                score=max(score, 1.0 if best_lane == DIRECT_SOURCE_MATCH else score),
                source=best["source_title"],
                matched_text=best["matched_text"],
                source_id=best["record_id"],
                note="candidate is named in a source record with screen-relevant context",
            )
    return {
        "candidate_id": gene,
        "candidate_type": "gene_symbol",
        "rank": None,
        "score": score,
        "evidence_support_level": evidence_support_level_for_score(score),
        "answerability": answerability_for_lane(best_lane),
        "best_evidence_lane": best_lane,
        "best_source_family": best["source_family"] if best else None,
        "evidence_lanes": lanes,
        "supporting_evidence": [_evidence_summary(item) for item in sorted(supported, key=lambda item: -float(item["score"]))],
        "counter_evidence": [],
        "why_not_selected": [],
    }


def _score_record(gene: str, query: dict[str, str], record: dict[str, Any]) -> dict[str, Any]:
    gene_match = gene.casefold() in {item.casefold() for item in record["genes"]}
    text = " ".join(str(record.get(key) or "") for key in ("text", "title", "finding", "source_type"))
    source_family = record.get("verification", {}).get("source_family") or _source_family(record, text)
    exact_context = verified_context_matches(record)
    token_overlap = _context_token_overlap(query, text)
    matched_text = record.get("finding") or record.get("text") or record.get("title") or ""
    gene_is_verified = verified_gene_match(gene, record)
    if gene_match and gene_is_verified and source_family == "functional_genomics_perturbation_source" and exact_context:
        score = SCREEN_GENE_RETRIEVAL.ranking_weights[DIRECT_SOURCE_MATCH]
        evidence_lane = DIRECT_SOURCE_MATCH
        reason = "candidate gene and requested perturbation context are source-verified in a functional-genomics record"
    elif gene_match and gene_is_verified and exact_context:
        score = SCREEN_GENE_RETRIEVAL.ranking_weights[EXACT_TRAIT_MATCH]
        evidence_lane = EXACT_TRAIT_MATCH
        reason = "candidate gene and requested context are source-verified, but the source is not a direct perturbation record"
    elif gene_match and token_overlap:
        score = SCREEN_GENE_RETRIEVAL.ranking_weights[NEARBY_TRAIT_MATCH]
        evidence_lane = NEARBY_TRAIT_MATCH
        reason = "candidate gene appears in a source record with nearby unverified context-token overlap"
    elif gene_match and source_family == "literature_source":
        score = SCREEN_GENE_RETRIEVAL.ranking_weights[LITERATURE_PLAUSIBILITY]
        evidence_lane = LITERATURE_PLAUSIBILITY
        reason = "candidate gene appears in a literature source without matching perturbation context"
    elif gene_match:
        score = SCREEN_GENE_RETRIEVAL.ranking_weights[PATHWAY_PLAUSIBILITY]
        evidence_lane = PATHWAY_PLAUSIBILITY
        reason = "candidate gene appears in a source record without matching perturbation context"
    else:
        score = 0.0
        evidence_lane = None
        reason = "candidate gene was not named in this source record"
    return {
        "candidate_id": gene,
        "record_id": record["record_id"],
        "score": score,
        "evidence_lane": evidence_lane,
        "reason": reason,
        "source_family": source_family,
        "source_title": record.get("source_title") or record.get("title") or "source record",
        "source_url": record.get("source_url"),
        "matched_text": matched_text,
        "context_matches": exact_context,
        "context_match_count": len(exact_context),
        "token_overlap": token_overlap,
        "verification_status": record.get("verification", {}).get("status"),
        "direct_perturbation_support": direct_perturbation_support(record),
    }


def _evidence_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": item["source_title"],
        "source_url": item.get("source_url"),
        "record_id": item["record_id"],
        "source_family": item["source_family"],
        "evidence_lane": item["evidence_lane"],
        "matched_text": item["matched_text"],
        "context_matches": item["context_matches"],
        "token_overlap": item["token_overlap"],
        "verification_status": item.get("verification_status"),
        "direct_perturbation_support": item.get("direct_perturbation_support"),
        "finding": item["reason"],
    }


def _selection_warnings(
    selected: dict[str, Any] | None,
    matrix: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> list[str]:
    if not records:
        return ["No source records were supplied; the operation cannot rank genes from evidence."]
    if not selected:
        return ["No candidate gene was named in the supplied source records."]
    warnings = []
    if selected["answerability"] != "direct_source_supported":
        warnings.append("Selected candidate is not backed by direct perturbation-source context; treat as lower support.")
    direct_count = sum(1 for candidate in matrix if candidate["answerability"] == "direct_source_supported")
    if direct_count > 1:
        warnings.append("Multiple candidate genes had direct source support; inspect supporting_evidence before finalizing.")
    return warnings


def _why_not_selected(candidate: dict[str, Any], selected: dict[str, Any] | None) -> list[str]:
    if not selected:
        return ["No candidate had supplied source-record support."]
    if candidate["candidate_id"] == selected["candidate_id"]:
        return []
    if candidate["score"] <= 0:
        return ["No supplied source record named this candidate with usable context."]
    if candidate["score"] < selected["score"]:
        return [
            f"Evidence lane {candidate['best_evidence_lane']} is weaker than selected lane {selected['best_evidence_lane']}."
        ]
    return ["Ranked lower by deterministic candidate tie-breaker."]


def _source_family(record: dict[str, Any], text: str) -> str:
    tokens = set(_tokens(" ".join([text, str(record.get("source_type") or ""), str(record.get("assay") or "")])))
    if tokens & _SCREEN_SOURCE_TOKENS:
        return "functional_genomics_perturbation_source"
    if any(record.get(key) for key in ("pmid", "pubmed_id", "doi")):
        return "literature_source"
    return "source_record"


def _exact_context_matches(query: dict[str, str], record: dict[str, Any], text: str) -> list[str]:
    matches = []
    searchable = " ".join(
        [
            text,
            str(record.get("cell_line") or ""),
            str(record.get("perturbation") or ""),
            str(record.get("assay") or ""),
            str(record.get("phenotype") or ""),
        ]
    ).casefold()
    for key in ("organism", "cell_line", "perturbation", "assay", "phenotype"):
        value = query.get(key) or ""
        if value and value.casefold() in searchable:
            matches.append(key)
    return matches


def _context_token_overlap(query: dict[str, str], text: str) -> list[str]:
    query_text = " ".join(
        str(query.get(key) or "")
        for key in ("context", "organism", "cell_line", "perturbation", "assay", "phenotype", "semantic_context_terms")
    )
    query_tokens = set(_meaningful_tokens(query_text))
    source_tokens = set(_meaningful_tokens(text))
    return sorted(query_tokens & source_tokens)


def _result_status(selected: dict[str, Any] | None, records: list[dict[str, Any]]) -> str:
    if not records:
        return "no_source_records"
    if not selected:
        return "insufficient_source_evidence"
    if selected["answerability"] == "direct_source_supported":
        return "completed"
    return "insufficient_source_evidence"
