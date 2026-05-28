from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ....evidence.candidate_evidence import (
    DIRECT_SOURCE_MATCH,
    EXACT_TRAIT_MATCH,
    LITERATURE_PLAUSIBILITY,
    NEARBY_TRAIT_MATCH,
    NEGATIVE_OR_CONFLICTING_EVIDENCE,
    ONTOLOGY_SYNONYM_MATCH,
    SAME_GENE_OR_LOCUS,
    answerability_for_lane,
    apply_evidence_view,
    evidence_support_level_for_score,
    empty_lanes,
    evidence_view,
    lane,
)
from ....evidence.sources import evidence_source_catalog
from ....evidence.task_profiles import (
    PHENOTYPE_DISEASE_PRIORITIZATION,
    PHENOTYPE_GENE_PRIORITIZATION,
)
from ....runtime.external import utc_now
from ....retrieval import semantic as retrieval_semantic

from ._base import (
    GENCC_SUBMISSIONS_URL,
    HPO_DISEASE_ANNOTATION_URL,
    HPO_GENE_ANNOTATION_URL,
    HPO_ID_RE,
    PHENOTYPE_NORMALIZATION_SCHEMA_VERSION,
    PHENOTYPE_PRIORITIZATION_SCHEMA_VERSION,
    _any_field_matches,
    _canonical_phrase,
    _clean_text,
    _collect_terms,
    _context_token_overlap,
    _dedupe,
    _extract_disease_ids,
    _first_hpo_id,
    _hpo_public_summary,
    _meaningful_tokens,
    _normalize_disease_ids,
    _normalize_diseases,
    _normalize_gene,
    _normalize_genes,
    _normalize_hpo_ids,
    _phenotype_term_usage,
    _prepare_source_records,
    _record_text,
    _stored_records,
    _strip_disease_ids,
    _value_supported_by_text,
)
from .annotations import (
    _hpo_disease_annotation_context,
    _hpo_gene_annotation_context,
)


def normalize_phenotypes(
    *,
    text: str | None = None,
    terms: Iterable[str] | None = None,
    hpo_ids: Iterable[str] | None = None,
    semantic_context: object = None,
) -> dict[str, Any]:
    """Normalize free-text phenotype inputs into safe public search targets."""
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    raw_terms = _collect_terms(text=text, terms=terms)
    for term in retrieval_semantic.search_terms(semantic, entity_types=("phenotype", "trait_or_condition")):
        if _clean_text(term) not in {_clean_text(value) for value in raw_terms}:
            raw_terms.append(term)
    explicit_ids = _normalize_hpo_ids(hpo_ids or [])
    ids_from_text = _normalize_hpo_ids(HPO_ID_RE.findall(" ".join([text or "", *raw_terms])))
    ids = _dedupe([*explicit_ids, *ids_from_text])
    normalized_terms = _dedupe([_clean_text(term) for term in raw_terms if not HPO_ID_RE.fullmatch(str(term).strip())])
    phenotype_terms = [
        {
            "input": term,
            "normalized": _canonical_phrase(term),
            "tokens": _meaningful_tokens(term),
            "hpo_id": _first_hpo_id(term),
            "status": "normalized_public_target",
        }
        for term in normalized_terms
    ]
    term_usage = _phenotype_term_usage(semantic)
    return {
        "schema": PHENOTYPE_NORMALIZATION_SCHEMA_VERSION,
        "status": "completed" if (ids or phenotype_terms) else "no_phenotype_terms",
        "query": {
            "text": _clean_text(text),
            "terms": normalized_terms,
            "hpo_ids": ids,
        },
        "normalized_phenotypes": phenotype_terms,
        "hpo_ids": ids,
        "safe_external_targets": {
            "phenotype_terms": [item["normalized"] for item in phenotype_terms],
            "hpo_ids": ids,
        },
        "source_review_plan": _source_review_plan("phenotype"),
        "semantic_context": term_usage,
        "notes": [
            "HPO IDs and phenotype terms are public targets.",
            "Normalization is lexical unless source records or ontology findings are supplied.",
            "Host semantic terms are retrieval inputs; term_matches report exact IDs or source-record hits.",
        ],
    }


def compare_disease_phenotype_evidence(
    evidence_db: str | Path | None = None,
    *,
    phenotype_text: str | None = None,
    phenotypes: Iterable[str] | None = None,
    hpo_ids: Iterable[str] | None = None,
    candidate_diseases: Iterable[str] | None = None,
    genes: Iterable[str] | None = None,
    source_records: Iterable[dict[str, Any]] | None = None,
    search_stored_research: bool = True,
    use_hpo_annotations: bool = True,
    download_hpo_annotations: bool = True,
    hpo_disease_file: str | Path | None = None,
    hpo_disease_url: str = HPO_DISEASE_ANNOTATION_URL,
    use_primary_gene_disease: bool = True,
    download_primary_gene_disease: bool = True,
    gencc_file: str | Path | None = None,
    gencc_url: str = GENCC_SUBMISSIONS_URL,
    limit: int = 25,
    semantic_context: object = None,
) -> dict[str, Any]:
    normalized = normalize_phenotypes(text=phenotype_text, terms=phenotypes, hpo_ids=hpo_ids, semantic_context=semantic_context)
    query = {
        "phenotype_text": _clean_text(phenotype_text),
        "phenotypes": [item["normalized"] for item in normalized["normalized_phenotypes"]],
        "hpo_ids": normalized["hpo_ids"],
        "candidate_diseases": _normalize_diseases(candidate_diseases or []),
        "genes": _normalize_genes(genes or []),
    }
    hpo_context = _hpo_disease_annotation_context(
        query,
        use_hpo_annotations=use_hpo_annotations,
        download_hpo_annotations=download_hpo_annotations,
        hpo_disease_file=hpo_disease_file,
        hpo_disease_url=hpo_disease_url,
        use_primary_gene_disease=use_primary_gene_disease,
        download_primary_gene_disease=download_primary_gene_disease,
        gencc_file=gencc_file,
        gencc_url=gencc_url,
        limit=limit,
    )
    records = _prepare_source_records(
        source_records,
        stored_records=_stored_records(
            evidence_db,
            query_terms=[*query["phenotypes"], *query["hpo_ids"], *query["candidate_diseases"], *query["genes"]],
            search_stored_research=search_stored_research,
            limit=limit,
        ),
        annotation_records=hpo_context["source_records"],
        query=query,
    )
    candidates = query["candidate_diseases"] or _derive_disease_candidates(records)
    matrix = _rank_candidates(
        candidates,
        query=query,
        records=records,
        profile=PHENOTYPE_DISEASE_PRIORITIZATION,
        candidate_type="disease_or_condition",
        mode="disease",
    )
    selected = matrix[0] if matrix and matrix[0].get("rank") == 1 else None
    discrimination = _disease_discrimination(matrix, query)
    selected_for_answer = None if discrimination["discrimination_required"] else selected
    direct = bool(selected_for_answer and selected_for_answer.get("answerability") == "direct_source_supported")
    view = evidence_view(
        task_profile=PHENOTYPE_DISEASE_PRIORITIZATION,
        query=query,
        candidate_matrix=matrix,
        top_observed_candidate=selected_for_answer,
        infer_top_observed_candidate=False,
        evidence_policy=_decision_policy("disease"),
        warnings=_warnings(records, selected, candidates, "disease"),
        evidence_state="ambiguous_discrimination" if discrimination["discrimination_required"] else None,
    )
    payload = {
        "schema": PHENOTYPE_PRIORITIZATION_SCHEMA_VERSION,
        "status": _status(records, selected, candidates),
        "query": query,
        "phenotype_normalization": normalized,
        "hpo_disease_annotation_evidence": _hpo_public_summary(hpo_context),
        "source_records": records,
        "summary": {**_summary(matrix, records), "discrimination_required": discrimination["discrimination_required"]},
        "discrimination": discrimination,
        "source_review_plan": _source_review_plan("disease"),
        "record_research_templates": _record_templates(query, mode="disease"),
        "next_actions": _next_actions(query, mode="disease", direct=direct),
    }
    return apply_evidence_view(payload, view, operation="phenotype.compare_disease_evidence")


def compare_gene_hpo_evidence(
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
    hpo_gene_url: str = HPO_GENE_ANNOTATION_URL,
    limit: int = 25,
    semantic_context: object = None,
) -> dict[str, Any]:
    normalized = normalize_phenotypes(text=phenotype_text, terms=phenotypes, hpo_ids=hpo_ids, semantic_context=semantic_context)
    query = {
        "phenotype_text": _clean_text(phenotype_text),
        "phenotypes": [item["normalized"] for item in normalized["normalized_phenotypes"]],
        "hpo_ids": normalized["hpo_ids"],
        "condition": _clean_text(condition),
        "genes": _normalize_genes(genes or []),
    }
    hpo_context = _hpo_gene_annotation_context(
        query,
        use_hpo_annotations=use_hpo_annotations,
        download_hpo_annotations=download_hpo_annotations,
        hpo_gene_file=hpo_gene_file,
        hpo_gene_url=hpo_gene_url,
        limit=limit,
    )
    records = _prepare_source_records(
        source_records,
        stored_records=_stored_records(
            evidence_db,
            query_terms=[*query["phenotypes"], *query["hpo_ids"], *(query["genes"]), query["condition"]],
            search_stored_research=search_stored_research,
            limit=limit,
        ),
        annotation_records=hpo_context["source_records"],
        query=query,
    )
    candidates = query["genes"] or _derive_gene_candidates(records)
    matrix = _rank_candidates(
        candidates,
        query=query,
        records=records,
        profile=PHENOTYPE_GENE_PRIORITIZATION,
        candidate_type="gene_symbol",
        mode="gene",
    )
    selected = matrix[0] if matrix and matrix[0].get("rank") == 1 else None
    comparable = _comparable_gene_evidence(candidates, records, hpo_context, selected=selected)
    selected_for_answer = selected if comparable else None
    direct = bool(selected_for_answer and selected_for_answer.get("answerability") == "direct_source_supported")
    view = evidence_view(
        task_profile=PHENOTYPE_GENE_PRIORITIZATION,
        query=query,
        candidate_matrix=matrix,
        top_observed_candidate=selected_for_answer,
        infer_top_observed_candidate=False,
        evidence_policy=_decision_policy("gene"),
        warnings=_warnings(records, selected_for_answer, candidates, "gene") + _coverage_warnings(candidates, records, hpo_context, selected=selected),
    )
    payload = {
        "schema": PHENOTYPE_PRIORITIZATION_SCHEMA_VERSION,
        "status": _status(records, selected, candidates),
        "query": query,
        "phenotype_normalization": normalized,
        "hpo_annotation_evidence": _hpo_public_summary(hpo_context),
        "source_records": records,
        "summary": {**_summary(matrix, records), "comparable_candidate_evidence": comparable},
        "source_review_plan": _source_review_plan("gene"),
        "record_research_templates": _record_templates(query, mode="gene"),
        "next_actions": _next_actions(query, mode="gene", direct=direct),
    }
    return apply_evidence_view(payload, view, operation="phenotype.compare_gene_hpo_evidence")


def _rank_candidates(
    candidates: list[str],
    *,
    query: dict[str, Any],
    records: list[dict[str, Any]],
    profile: Any,
    candidate_type: str,
    mode: str,
) -> list[dict[str, Any]]:
    rows = [_candidate_row(candidate, query=query, records=records, profile=profile, candidate_type=candidate_type, mode=mode) for candidate in candidates]
    sort_key = _disease_rank_key if mode == "disease" else _gene_rank_key
    ranked = sorted(
        [row for row in rows if row["score"] > 0],
        key=sort_key,
    )
    ranks = {row["candidate_id"]: index + 1 for index, row in enumerate(ranked)}
    selected = ranked[0] if ranked else None
    for row in rows:
        row["rank"] = ranks.get(row["candidate_id"])
        row["why_not_selected"] = _why_not_selected(row, selected)
    return sorted(rows, key=lambda row: (row["rank"] is None, row["rank"] or 10**9, str(row["candidate_id"]).casefold()))


def _gene_rank_key(row: dict[str, Any]) -> tuple[float, int, float, int, str]:
    return (
        -float(row["score"]),
        -float(row.get("phenotype_overlap_density") or 0.0),
        -int(row.get("phenotype_overlap_count") or 0),
        int(row.get("phenotype_profile_hpo_count") or 0),
        str(row["candidate_id"]).casefold(),
    )


def _disease_rank_key(row: dict[str, Any]) -> tuple[float, float, int, int, str]:
    return (
        -float(row["score"]),
        -float(row.get("phenotype_overlap_density") or 0.0),
        -int(row.get("phenotype_overlap_count") or 0),
        int(row.get("phenotype_profile_hpo_count") or 0),
        str(row["candidate_id"]).casefold(),
    )


def _disease_discrimination(matrix: list[dict[str, Any]], query: dict[str, Any], *, density_margin: float = 0.10) -> dict[str, Any]:
    ranked = [row for row in matrix if row.get("rank") is not None and float(row.get("score") or 0.0) > 0]
    ranked.sort(key=lambda row: (int(row.get("rank") or 10**9), str(row.get("candidate_id")).casefold()))
    if len(ranked) < 2:
        return {"discrimination_required": False, "tier_candidates": [], "reason": None}
    top_density = float(ranked[0].get("phenotype_overlap_density") or 0.0)
    second_density = float(ranked[1].get("phenotype_overlap_density") or 0.0)
    if top_density <= 0 or abs(top_density - second_density) > density_margin:
        return {"discrimination_required": False, "tier_candidates": [], "reason": None}
    tier = [
        row
        for row in ranked
        if abs(top_density - float(row.get("phenotype_overlap_density") or 0.0)) <= density_margin
    ][:5]
    requested_hpo = [str(item).upper() for item in (query.get("hpo_ids") or [])]
    profile_by_candidate = {str(row["candidate_id"]): set(_candidate_profile_hpo_ids(row)) for row in tier}
    matched_by_candidate = {
        str(row["candidate_id"]): set((row.get("phenotype_match_detail") or {}).get("matched_hpo_ids") or [])
        for row in tier
    }
    return {
        "discrimination_required": True,
        "reason": "Top disease candidates have near-tied HPO overlap density; ranking alone should not decide the disease.",
        "density_margin": density_margin,
        "tier_candidates": [
            {
                "candidate": row.get("candidate_id"),
                "rank": row.get("rank"),
                "score": row.get("score"),
                "evidence_support_level": row.get("evidence_support_level"),
                "phenotype_overlap_density": row.get("phenotype_overlap_density"),
                "phenotype_overlap_count": row.get("phenotype_overlap_count"),
                "phenotype_profile_hpo_count": row.get("phenotype_profile_hpo_count"),
                "matched_patient_hpo_ids": sorted(matched_by_candidate[str(row["candidate_id"])]),
                "patient_hpo_ids_absent_from_candidate": sorted(set(requested_hpo) - profile_by_candidate[str(row["candidate_id"])]),
                "patient_hpo_ids_discriminating_for_candidate": sorted(
                    matched_by_candidate[str(row["candidate_id"])]
                    - set().union(*(values for key, values in matched_by_candidate.items() if key != str(row["candidate_id"])))
                ),
                "candidate_profile_hpo_ids_not_shared_with_tier": sorted(
                    profile_by_candidate[str(row["candidate_id"])]
                    - set().union(*(values for key, values in profile_by_candidate.items() if key != str(row["candidate_id"])))
                ),
            }
            for row in tier
        ],
    }


def _candidate_profile_hpo_ids(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for record in row.get("supporting_evidence") or []:
        if not isinstance(record, dict):
            continue
        fields = record.get("source_verified_fields") if isinstance(record.get("source_verified_fields"), dict) else {}
        values.extend(str(item).upper() for item in fields.get("hpo_ids") or [] if item)
    return _dedupe(values)


def _candidate_row(
    candidate: str,
    *,
    query: dict[str, Any],
    records: list[dict[str, Any]],
    profile: Any,
    candidate_type: str,
    mode: str,
) -> dict[str, Any]:
    scored = [_score_record(candidate, query=query, record=record, profile=profile, mode=mode) for record in records]
    supported = [item for item in scored if item["score"] > 0]
    best = max(
        supported,
        key=lambda item: (
            float(item["score"]),
            int(item["verified_context_count"]),
            item["source_family"],
            item["record_id"],
        ),
        default=None,
    )
    best_lane = best["evidence_lane"] if best else None
    score = float(best["score"]) if best else 0.0
    phenotype_overlap = _phenotype_overlap_terms(supported)
    phenotype_match_detail = _phenotype_match_detail(supported, query)
    phenotype_profile_hpo_count = _phenotype_profile_hpo_count(supported, phenotype_overlap)
    phenotype_overlap_density = (
        round(len(phenotype_overlap) / phenotype_profile_hpo_count, 4)
        if phenotype_profile_hpo_count
        else 0.0
    )
    if mode == "gene" and phenotype_overlap and best_lane in {DIRECT_SOURCE_MATCH, EXACT_TRAIT_MATCH, ONTOLOGY_SYNONYM_MATCH, SAME_GENE_OR_LOCUS}:
        aggregate_score = min(0.99, 0.55 + 0.12 * len(phenotype_overlap))
        if aggregate_score > score or best_lane == DIRECT_SOURCE_MATCH:
            score = max(score if best_lane != DIRECT_SOURCE_MATCH else 0.0, aggregate_score)
            best_lane = DIRECT_SOURCE_MATCH
    lanes = empty_lanes()
    if best and best_lane:
        lanes[best_lane] = lane(
            best_lane,
            status="present",
            score=score,
            source=best["source_title"],
            source_id=best["record_id"],
            matched_text=best["matched_text"],
            note=best["reason"],
        )
    return {
        "candidate_id": candidate,
        "candidate_type": candidate_type,
        "rank": None,
        "score": score,
        "evidence_support_level": evidence_support_level_for_score(score),
        "answerability": answerability_for_lane(best_lane),
        "best_evidence_lane": best_lane,
        "phenotype_overlap_count": len(phenotype_overlap),
        "phenotype_profile_hpo_count": phenotype_profile_hpo_count,
        "phenotype_overlap_density": phenotype_overlap_density,
        "phenotype_overlap_terms": phenotype_overlap,
        "phenotype_match_detail": phenotype_match_detail,
        "candidate_identifiers": _candidate_identifiers(candidate, supported, mode=mode),
        "best_source_family": best["source_family"] if best else None,
        "best_source_origin": best["source_origin"] if best else None,
        "evidence_lanes": lanes,
        "supporting_evidence": [_evidence_summary(item) for item in sorted(supported, key=lambda item: -float(item["score"]))],
        "counter_evidence": _counter_evidence(scored),
        "why_not_selected": [],
    }


def _score_record(candidate: str, *, query: dict[str, Any], record: dict[str, Any], profile: Any, mode: str) -> dict[str, Any]:
    candidate_match = _candidate_verified(candidate, record, mode=mode)
    candidate_mentioned = _candidate_mentioned(candidate, record, mode=mode)
    context = _phenotype_context(record, query)
    source_family = record.get("verification", {}).get("source_family") or "source_record"
    source_title = record.get("source_title") or record.get("title") or "source record"
    matched_text = record.get("finding") or record.get("text") or record.get("title") or ""
    negative = _negative_record(record)

    if negative and (candidate_match or candidate_mentioned):
        score = profile.ranking_weights.get(NEGATIVE_OR_CONFLICTING_EVIDENCE, 0.2)
        evidence_lane = NEGATIVE_OR_CONFLICTING_EVIDENCE
        reason = "candidate appears in a source record with conflicting or negative context"
    elif mode == "disease" and candidate_match and context["verified_count"] and source_family in {"rare_disease_source", "ontology_source"}:
        score = profile.ranking_weights[DIRECT_SOURCE_MATCH]
        evidence_lane = DIRECT_SOURCE_MATCH
        reason = "candidate disease and requested phenotype context are source-verified"
    elif mode == "gene" and candidate_match and context["verified_count"] and source_family in {"rare_disease_source", "ontology_source"}:
        score = profile.ranking_weights[DIRECT_SOURCE_MATCH]
        evidence_lane = DIRECT_SOURCE_MATCH
        reason = "candidate gene and phenotype or disease context are source-verified by rare-disease evidence"
    elif candidate_match and _condition_match(record, query):
        score = profile.ranking_weights[EXACT_TRAIT_MATCH]
        evidence_lane = EXACT_TRAIT_MATCH
        reason = "candidate is source-verified with the requested condition context"
    elif candidate_match and context["ontology_count"]:
        score = profile.ranking_weights.get(ONTOLOGY_SYNONYM_MATCH, 0.55)
        evidence_lane = ONTOLOGY_SYNONYM_MATCH
        reason = "candidate is source-verified with ontology or synonym phenotype support"
    elif mode == "gene" and candidate_match:
        score = profile.ranking_weights.get(SAME_GENE_OR_LOCUS, 0.55)
        evidence_lane = SAME_GENE_OR_LOCUS
        reason = "candidate gene is source-verified, but phenotype context is incomplete"
    elif candidate_mentioned and (context["token_overlap"] or _condition_match(record, query)):
        score = profile.ranking_weights[NEARBY_TRAIT_MATCH]
        evidence_lane = NEARBY_TRAIT_MATCH
        reason = "candidate is mentioned with nearby phenotype or condition tokens, but source verification is incomplete"
    elif candidate_mentioned:
        score = profile.ranking_weights[LITERATURE_PLAUSIBILITY]
        evidence_lane = LITERATURE_PLAUSIBILITY
        reason = "candidate is mentioned in a source record without direct phenotype support"
    else:
        score = 0.0
        evidence_lane = None
        reason = "candidate was not supported by this source record"

    return {
        "candidate_id": candidate,
        "record_id": record["record_id"],
        "score": score,
        "evidence_lane": evidence_lane,
        "reason": reason,
        "source_family": source_family,
        "source_origin": record.get("verification", {}).get("source_origin"),
        "source_title": source_title,
        "source_url": record.get("source_url"),
        "matched_text": matched_text,
        "verified_context": context["verified_context"],
        "matched_query_terms": context["verified_context"] + context["token_overlap"],
        "verified_context_count": context["verified_count"],
        "token_overlap": context["token_overlap"],
        "verification_status": record.get("verification", {}).get("status"),
        "query_context_support": record.get("verification", {}).get("query_context_support") or {},
        "source_verified_fields": record.get("verification", {}).get("verified_fields") or {},
        "support_spans": record.get("verification", {}).get("support_spans") or [],
        "hpo_annotation_profile": record.get("hpo_annotation_profile") or {},
        "verification_limitations": record.get("verification", {}).get("limitations") or [],
        "negative_or_conflicting": negative,
    }


def _phenotype_context(record: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    verification = record.get("verification", {})
    support = verification.get("query_context_support") or {}
    verified_context = [
        key
        for key, value in support.items()
        if value in {"verified_hpo", "verified_term", "verified_condition"}
    ]
    ontology_context = [key for key, value in support.items() if value in {"verified_hpo", "verified_term"}]
    source_text = " ".join(str(record.get(key) or "") for key in ("text", "finding", "title", "source_type", "source_title"))
    token_overlap = _context_token_overlap(query, source_text)
    return {
        "verified_context": verified_context,
        "verified_count": len(verified_context),
        "ontology_count": len(ontology_context),
        "token_overlap": token_overlap,
    }


def _phenotype_overlap_terms(scored_records: list[dict[str, Any]]) -> list[str]:
    hpo_terms: list[str] = []
    phenotype_terms: list[str] = []
    for record in scored_records:
        if record.get("source_family") not in {"ontology_source", "rare_disease_source"}:
            continue
        for item in record.get("verified_context") or []:
            text = str(item)
            if text.startswith("hpo:"):
                hpo_terms.append(text)
            elif text.startswith("phenotype:"):
                phenotype_terms.append(text)
    return _dedupe(hpo_terms) if hpo_terms else _dedupe(phenotype_terms)


def _phenotype_profile_hpo_count(scored_records: list[dict[str, Any]], phenotype_overlap: list[str]) -> int:
    hpo_ids: list[str] = []
    for record in scored_records:
        fields = record.get("source_verified_fields") or {}
        hpo_ids.extend(fields.get("hpo_ids") or [])
    normalized = _normalize_hpo_ids(hpo_ids)
    if normalized:
        return len(normalized)
    return len(phenotype_overlap)


def _candidate_identifiers(candidate: str, scored_records: list[dict[str, Any]], *, mode: str) -> list[str]:
    if mode != "disease":
        return []
    identifiers: list[str] = []
    for record in scored_records:
        fields = record.get("source_verified_fields") or {}
        identifiers.extend(str(item) for item in fields.get("disease_ids") or [] if item)
    return _dedupe(identifiers)


def _phenotype_match_detail(scored_records: list[dict[str, Any]], query: dict[str, Any]) -> dict[str, Any]:
    matched_context = _dedupe(
        context
        for record in scored_records
        for context in (record.get("verified_context") or [])
    )
    matched_hpo_ids = _dedupe(
        context.split(":", 1)[1].upper()
        for context in matched_context
        if context.startswith("hpo:")
    )
    matched_phenotypes = _dedupe(
        context.split(":", 1)[1]
        for context in matched_context
        if context.startswith("phenotype:")
    )
    matched_conditions = _dedupe(
        context.split(":", 1)[1]
        for context in matched_context
        if context.startswith("condition:")
    )
    requested_hpo_ids = [str(item).upper() for item in (query.get("hpo_ids") or [])]
    requested_phenotypes = list(query.get("phenotypes") or [])
    requested_conditions = [query["condition"]] if query.get("condition") else []
    return {
        "requested_hpo_ids": requested_hpo_ids,
        "matched_hpo_ids": matched_hpo_ids,
        "unmatched_hpo_ids": [item for item in requested_hpo_ids if item not in set(matched_hpo_ids)],
        "requested_phenotypes": requested_phenotypes,
        "matched_phenotypes": matched_phenotypes,
        "unmatched_phenotypes": [item for item in requested_phenotypes if item not in set(matched_phenotypes)],
        "requested_conditions": requested_conditions,
        "matched_conditions": matched_conditions,
        "unmatched_conditions": [item for item in requested_conditions if item not in set(matched_conditions)],
        "matched_verified_context": matched_context,
        "matched_context_count": len(matched_context),
    }


def _comparable_gene_evidence(
    candidates: list[str],
    records: list[dict[str, Any]],
    hpo_context: dict[str, Any],
    *,
    selected: dict[str, Any] | None = None,
) -> bool:
    if len(candidates) <= 1:
        return True
    supported = {
        gene
        for record in records
        for gene in (record.get("verification", {}).get("verified_fields", {}).get("genes") or [])
    }
    if all(gene in supported for gene in candidates):
        return True
    return bool(hpo_context.get("status") == "searched" and selected and selected.get("best_source_origin") == "public_annotation_source")


def _coverage_warnings(candidates: list[str], records: list[dict[str, Any]], hpo_context: dict[str, Any], *, selected: dict[str, Any] | None = None) -> list[str]:
    if _comparable_gene_evidence(candidates, records, hpo_context, selected=selected):
        return []
    supported = {
        gene
        for record in records
        for gene in (record.get("verification", {}).get("verified_fields", {}).get("genes") or [])
    }
    missing = [gene for gene in candidates if gene not in supported]
    return [
        "Candidate evidence coverage is incomplete; the ranked rows reflect supplied or stored records and should not be used for an identifier-only answer.",
        "Uncovered candidate genes: " + ", ".join(missing[:10]),
    ]


def _candidate_verified(candidate: str, record: dict[str, Any], *, mode: str) -> bool:
    verified_fields = record.get("verification", {}).get("verified_fields") or {}
    if mode == "gene":
        return _normalize_gene(candidate) in {item.upper() for item in verified_fields.get("genes") or []}
    candidate_ids = set(_extract_disease_ids([candidate]))
    verified_ids = set(_normalize_disease_ids(verified_fields.get("disease_ids") or []))
    if candidate_ids and candidate_ids & verified_ids:
        return True
    return _any_field_matches(_strip_disease_ids(candidate), verified_fields.get("diseases") or [])


def _candidate_mentioned(candidate: str, record: dict[str, Any], *, mode: str) -> bool:
    if mode == "gene":
        gene = _normalize_gene(candidate)
        if gene in {item.upper() for item in record.get("genes") or []}:
            return True
        return bool(re.search(rf"\b{re.escape(gene)}\b", _record_text(record), flags=re.I))
    candidate_ids = set(_extract_disease_ids([candidate]))
    record_ids = set(_normalize_disease_ids(record.get("disease_ids") or []))
    if candidate_ids and candidate_ids & record_ids:
        return True
    disease_name = _strip_disease_ids(candidate)
    return _any_field_matches(disease_name, record.get("diseases") or []) or _value_supported_by_text(disease_name, _record_text(record))


def _condition_match(record: dict[str, Any], query: dict[str, Any]) -> bool:
    condition = query.get("condition")
    if not condition:
        return False
    verified_fields = record.get("verification", {}).get("verified_fields") or {}
    return _any_field_matches(condition, verified_fields.get("diseases") or []) or _value_supported_by_text(condition, _record_text(record))


def _negative_record(record: dict[str, Any]) -> bool:
    text = " ".join(str(record.get(key) or "") for key in ("finding", "text", "finding_type", "source_type")).casefold()
    return any(term in text for term in ("conflicting", "negative", "not associated", "excluded", "insufficient evidence"))


def _source_review_plan(mode: str) -> dict[str, Any]:
    source_ids = ["hpo", "mondo", "orphanet", "omim", "genereviews", "gencc", "clingen_gene_validity", "genecards", "malacards"]
    catalog = evidence_source_catalog()
    by_id = {source["source_id"]: source for source in catalog.get("sources") or []}
    return {
        "mode": mode,
        "safe_external_targets": ["phenotype terms", "HPO IDs", "candidate diseases", "candidate genes"],
        "source_order": [
            {
                "source_id": source_id,
                "title": by_id[source_id]["title"],
                "best_for": by_id[source_id]["best_for"],
                "limitations": by_id[source_id]["limitations"],
                "official_url": by_id[source_id].get("official_url"),
            }
            for source_id in source_ids
            if source_id in by_id
        ],
        "write_back_rule": "Record narrow reviewed source findings before treating a disease or gene as supported.",
    }


def _decision_policy(mode: str) -> dict[str, Any]:
    if mode == "disease":
        return {
            "policy_id": "phenotype_disease_prioritization_v1",
            "ranking_order": [
                "source-verified disease plus requested phenotype/HPO evidence",
                "source-verified condition match",
                "ontology synonym or HPO support",
                "nearby source context",
                "generic literature plausibility",
            ],
            "rule": "Do not convert lexical phenotype overlap into diagnosis without direct source support.",
        }
    return {
        "policy_id": "phenotype_gene_prioritization_v1",
        "ranking_order": [
            "source-verified gene plus requested phenotype/disease context",
            "source-verified gene-condition match",
            "same-gene source support",
            "nearby phenotype context",
            "generic literature plausibility",
        ],
        "rule": "Do not let broad association or popularity evidence outrank direct rare-disease source support.",
    }


def _warnings(records: list[dict[str, Any]], selected: dict[str, Any] | None, candidates: list[str], mode: str) -> list[str]:
    warnings = []
    if not candidates:
        warnings.append(f"No candidate {mode}s were supplied or derived from source records.")
    if not records:
        warnings.append("No source records were supplied or found; ranking cannot create direct support.")
    if selected and selected.get("answerability") != "direct_source_supported":
        warnings.append("Selected candidate is not direct-source-supported; do not provide an identifier-only answer.")
    return warnings


def _status(records: list[dict[str, Any]], selected: dict[str, Any] | None, candidates: list[str]) -> str:
    if selected and selected.get("answerability") == "direct_source_supported":
        return "direct_source_supported"
    if selected:
        return "candidate_review_needed"
    if candidates:
        return "no_supported_candidate"
    if records:
        return "no_candidate_derived"
    return "no_source_records"


def _summary(matrix: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    selected = matrix[0] if matrix and matrix[0].get("rank") == 1 else None
    return {
        "candidate_count": len(matrix),
        "source_record_count": len(records),
        "verified_source_record_count": sum(1 for record in records if record.get("verification", {}).get("status") in {"verified", "partially_verified"}),
        "top_observed_candidate": selected.get("candidate_id") if selected else None,
        "top_observed_support_level": selected.get("evidence_support_level") if selected else "none",
    }


def _next_actions(query: dict[str, Any], *, mode: str, direct: bool) -> list[dict[str, Any]]:
    if direct:
        return [
            {
                "operation": "research.record",
                "params": {"payload": "<reviewed finding>", "scope": "shared"},
                "reason": "persist source-backed phenotype evidence before report synthesis",
            }
        ]
    actions = [
        {
            "operation": "research.list_sources",
            "params": {"target_type": "condition" if mode == "disease" else "gene"},
            "reason": "identify authoritative phenotype, disease, and gene-disease sources to review",
        },
        {
            "operation": "research.record",
            "params": {"payload": "<reviewed finding>", "scope": "shared"},
            "reason": "store HPO, Orphanet, OMIM, MONDO, GeneReviews, ClinGen, or GenCC findings with support spans",
        },
    ]
    if mode == "gene" and query.get("genes"):
        actions.append(
            {
                "operation": "variant.gather_gene_context",
                "params": {"gene": query["genes"][0]},
                "reason": "refresh deterministic gene-level context after source review",
            }
        )
    return actions


def _record_templates(query: dict[str, Any], *, mode: str) -> list[dict[str, Any]]:
    targets = query.get("candidate_diseases") if mode == "disease" else query.get("genes")
    templates = []
    for target in targets or []:
        target_payload = {"type": "condition", "condition": target} if mode == "disease" else {"type": "gene", "gene": target}
        templates.append(
            {
                "target": target_payload,
                "source": {"title": "", "url": "", "type": "", "accessed_at": utc_now()},
                "searched_query": " ".join([target, *(query.get("hpo_ids") or []), *(query.get("phenotypes") or [])[:3]]).strip(),
                "finding": {"type": "phenotype_association", "text": "", "summary": ""},
                "verified_fields": {},
                "support_spans": [],
                "captured_by": "agent",
            }
        )
    return templates


def _derive_disease_candidates(records: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for record in records:
        values.extend(record.get("verification", {}).get("verified_fields", {}).get("diseases") or [])
        values.extend(record.get("diseases") or [])
    return _normalize_diseases(values)


def _derive_gene_candidates(records: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for record in records:
        values.extend(record.get("verification", {}).get("verified_fields", {}).get("genes") or [])
        values.extend(record.get("genes") or [])
    return _normalize_genes(values)


def _counter_evidence(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": item["source_title"],
            "source_url": item.get("source_url"),
            "record_id": item["record_id"],
            "finding": item["reason"],
        }
        for item in scored
        if item.get("negative_or_conflicting") and item.get("score", 0) > 0
    ][:5]


def _evidence_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": item["source_title"],
        "source_url": item.get("source_url"),
        "record_id": item["record_id"],
        "source_family": item["source_family"],
        "evidence_lane": item["evidence_lane"],
        "matched_text": item["matched_text"],
        "verified_context": item["verified_context"],
        "token_overlap": item["token_overlap"],
        "query_context_support": item.get("query_context_support") or {},
        "source_verified_fields": item.get("source_verified_fields") or {},
        "support_spans": item.get("support_spans") or [],
        "hpo_annotation_profile": item.get("hpo_annotation_profile") or {},
        "verification_limitations": item.get("verification_limitations") or [],
        "verification_status": item.get("verification_status"),
        "finding": item["reason"],
    }


def _why_not_selected(candidate: dict[str, Any], selected: dict[str, Any] | None) -> list[str]:
    if not selected:
        return ["No candidate had source-record support."]
    if candidate["candidate_id"] == selected["candidate_id"]:
        return []
    if candidate["score"] <= 0:
        return ["No supplied source record supported this candidate."]
    if candidate["score"] < selected["score"]:
        return [f"Evidence lane {candidate['best_evidence_lane']} is weaker than selected lane {selected['best_evidence_lane']}."]
    if int(candidate.get("phenotype_overlap_count") or 0) < int(selected.get("phenotype_overlap_count") or 0):
        return ["Same evidence-lane strength as selected candidate, but fewer matched patient HPO or phenotype terms."]
    return ["Ranked lower by deterministic candidate tie-breaker."]
