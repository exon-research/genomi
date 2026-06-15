from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ....evidence import search_research_findings
from ....evidence.candidate_evidence import (
    DIRECT_SOURCE_MATCH,
    EXACT_TRAIT_MATCH,
    LITERATURE_PLAUSIBILITY,
    NEARBY_TRAIT_MATCH,
    NEGATIVE_OR_CONFLICTING_EVIDENCE,
    SAME_GENE_OR_LOCUS,
    answerability_for_lane,
    apply_evidence_view,
    evidence_support_level_for_score,
    empty_lanes,
    evidence_view,
    lane,
)
from ....evidence.sources import evidence_source_catalog
from ....evidence.task_profiles import DRUG_TARGET_GENE_PRIORITIZATION
from ....retrieval import semantic as retrieval_semantic
from ....runtime.external import utc_now

from ._base import (
    ASSOCIATION_ONLY_SOURCE_TOKENS,
    DRUG_TARGET_SOURCE_IDS,
    DRUG_TARGET_SOURCE_TOKENS,
    _any_field_matches,
    _as_list,
    _clean_text,
    _context_token_overlap,
    _dedupe,
    _dedupe_records,
    _normalize_gene,
    _normalize_genes,
    _normalize_terms,
    _record_digest,
    _tokens,
    _value_supported_by_text,
)
from .disease_targets import (
    _record_context_values,
    _semantic_drug_target_fields,
)


def compare_target_gene_evidence(
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
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    inferred = _semantic_drug_target_fields(semantic)
    query = {
        "drug": _clean_text(drug) or inferred.get("drug", ""),
        "drug_class": _clean_text(drug_class) or inferred.get("drug_class", ""),
        "indication": _clean_text(indication) or inferred.get("indication", ""),
        "mechanism": _clean_text(mechanism) or inferred.get("mechanism", ""),
        "genes": _normalize_genes(genes or []),
    }
    if not any([query["drug"], query["drug_class"], query["mechanism"]]):
        raise ValueError("Drug-target candidate selection requires drug, drug_class, or mechanism.")
    if not (query["genes"] or source_records):
        raise ValueError("Drug-target candidate selection requires candidate genes or source records.")
    records = _prepare_source_records(
        source_records,
        stored_records=_stored_records(
            evidence_db,
            query_terms=[
                query["drug"],
                query["drug_class"],
                query["indication"],
                query["mechanism"],
                *(query["genes"]),
                *retrieval_semantic.search_terms(semantic),
            ],
            search_stored_research=search_stored_research,
            limit=limit,
        ),
        query=query,
    )
    candidates = query["genes"] or _derive_gene_candidates(records)
    matrix = _rank_candidates(candidates, query=query, records=records)
    selected = matrix[0] if matrix and matrix[0].get("rank") == 1 else None
    direct = bool(selected and selected.get("answerability") == "direct_source_supported")
    view = evidence_view(
        task_profile=DRUG_TARGET_GENE_PRIORITIZATION,
        query=query,
        candidate_matrix=matrix,
        top_observed_candidate=selected,
        evidence_policy=_decision_policy(),
        warnings=_warnings(records, selected, candidates),
    )
    payload = {
        "status": _status(records, selected, candidates),
        "query": query,
        "source_records": records,
        "summary": _summary(matrix, records),
        "source_review_plan": _source_review_plan(),
        "record_research_templates": _record_templates(query),
        "next_actions": _next_actions(query, direct=direct),
    }
    if semantic.has_hints:
        payload["semantic_context"] = retrieval_semantic.term_usage_payload(
            semantic,
            term_matches=retrieval_semantic.matched_terms(
                semantic,
                _record_context_values(records),
                match_type="matched_drug_target_source_record_field",
                source="drug-target source records",
            ),
            streams=retrieval_semantic.retrieval_streams(
                raw_query=semantic.raw_query,
                host_terms=retrieval_semantic.search_terms(semantic),
                exact_ids=query["genes"],
                source_native_filters=[
                    value
                    for value in (query["drug"], query["drug_class"], query["indication"], query["mechanism"])
                    if value
                ],
            ),
        )
    return apply_evidence_view(payload, view, operation="phenotype.compare_drug_target_evidence")


def _rank_candidates(candidates: list[str], *, query: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [_candidate_row(gene, query=query, records=records) for gene in candidates]
    ranked = sorted(
        [row for row in rows if row["score"] > 0],
        key=lambda row: (-float(row["score"]), str(row["candidate_id"]).casefold()),
    )
    ranks = {row["candidate_id"]: index + 1 for index, row in enumerate(ranked)}
    selected = ranked[0] if ranked else None
    for row in rows:
        row["rank"] = ranks.get(row["candidate_id"])
        row["why_not_selected"] = _why_not_selected(row, selected)
    return sorted(rows, key=lambda row: (row["rank"] is None, row["rank"] or 10**9, str(row["candidate_id"]).casefold()))


def _candidate_row(gene: str, *, query: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [_score_record(gene, query=query, record=record) for record in records]
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
        "counter_evidence": _counter_evidence(scored),
        "why_not_selected": [],
    }


def _score_record(gene: str, *, query: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    verified_gene = _gene_verified(gene, record)
    mentioned_gene = _gene_mentioned(gene, record)
    context = _query_context(record, query)
    source_family = record.get("verification", {}).get("source_family") or "source_record"
    matched_text = record.get("finding") or record.get("text") or record.get("title") or ""
    source_title = record.get("source_title") or record.get("title") or "source record"
    negative = _negative_record(record)

    if negative and (verified_gene or mentioned_gene):
        score = DRUG_TARGET_GENE_PRIORITIZATION.ranking_weights[NEGATIVE_OR_CONFLICTING_EVIDENCE]
        evidence_lane = NEGATIVE_OR_CONFLICTING_EVIDENCE
        reason = "candidate appears in a source record with conflicting or negative target context"
    elif verified_gene and context["direct_target_context"] and source_family == "drug_target_source":
        score = DRUG_TARGET_GENE_PRIORITIZATION.ranking_weights[DIRECT_SOURCE_MATCH]
        evidence_lane = DIRECT_SOURCE_MATCH
        reason = "candidate gene is source-verified as a drug target or mechanism gene for the requested context"
    elif verified_gene and context["verified_count"] and source_family == "drug_target_source":
        score = DRUG_TARGET_GENE_PRIORITIZATION.ranking_weights[EXACT_TRAIT_MATCH]
        evidence_lane = EXACT_TRAIT_MATCH
        reason = "candidate gene is source-verified with requested drug, mechanism, class, or indication context"
    elif verified_gene and context["verified_count"] and source_family == "association_source":
        score = DRUG_TARGET_GENE_PRIORITIZATION.ranking_weights[SAME_GENE_OR_LOCUS]
        evidence_lane = SAME_GENE_OR_LOCUS
        reason = "candidate gene has source-verified association context, but not direct drug-target evidence"
    elif verified_gene:
        score = DRUG_TARGET_GENE_PRIORITIZATION.ranking_weights[SAME_GENE_OR_LOCUS]
        evidence_lane = SAME_GENE_OR_LOCUS
        reason = "candidate gene is source-verified, but direct drug-target context is missing"
    elif mentioned_gene and context["token_overlap"]:
        score = DRUG_TARGET_GENE_PRIORITIZATION.ranking_weights[NEARBY_TRAIT_MATCH]
        evidence_lane = NEARBY_TRAIT_MATCH
        reason = "candidate is mentioned with nearby drug or indication context, but source verification is incomplete"
    elif mentioned_gene:
        score = DRUG_TARGET_GENE_PRIORITIZATION.ranking_weights[LITERATURE_PLAUSIBILITY]
        evidence_lane = LITERATURE_PLAUSIBILITY
        reason = "candidate is mentioned in a source record without direct drug-target support"
    else:
        score = 0.0
        evidence_lane = None
        reason = "candidate gene was not supported by this source record"

    return {
        "candidate_id": gene,
        "record_id": record["record_id"],
        "score": score,
        "evidence_lane": evidence_lane,
        "reason": reason,
        "source_family": source_family,
        "source_title": source_title,
        "source_url": record.get("source_url"),
        "matched_text": matched_text,
        "verified_context": context["verified_context"],
        "verified_context_count": context["verified_count"],
        "direct_target_context": context["direct_target_context"],
        "token_overlap": context["token_overlap"],
        "verification_status": record.get("verification", {}).get("status"),
        "negative_or_conflicting": negative,
    }


def _prepare_source_records(
    source_records: Iterable[dict[str, Any]] | None,
    *,
    stored_records: list[dict[str, Any]],
    query: dict[str, Any],
) -> list[dict[str, Any]]:
    records = [
        _normalize_source_record(record, source_origin="provided_source_record", query=query)
        for record in (source_records or [])
        if isinstance(record, dict)
    ]
    records.extend(_normalize_source_record(_stored_research_to_source_record(record), source_origin="stored_reviewed_research", query=query) for record in stored_records)
    return _dedupe_records(records)


def _normalize_source_record(record: dict[str, Any], *, source_origin: str, query: dict[str, Any]) -> dict[str, Any]:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    finding = record.get("finding") if isinstance(record.get("finding"), dict) else {}
    verified_fields = _verified_fields(record)
    support_spans = _valid_support_spans(record)
    verified_fields = _merge_verified_fields(verified_fields, _verified_fields_from_spans(support_spans))
    text = _clean_text(
        " ".join(
            str(item or "")
            for item in (
                record.get("text"),
                record.get("snippet"),
                record.get("abstract"),
                finding.get("text"),
                finding.get("summary"),
            )
        )
    )
    title = _clean_text(record.get("title") or source.get("title") or record.get("source_title"))
    source_type = _clean_text(record.get("source_type") or source.get("type") or record.get("type"))
    source_id = _clean_text(record.get("source_id") or source.get("source_id"))
    source_title = _clean_text(record.get("source_title") or source.get("title") or title)
    source_url = record.get("source_url") or source.get("url") or record.get("url")
    source_text = " ".join([text, title, source_type, source_title, source_id, _verified_field_text(verified_fields)])
    normalized = {
        **record,
        "record_id": str(record.get("record_id") or record.get("finding_id") or record.get("id") or _record_digest(record)),
        "source_title": source_title or title or "source record",
        "source_url": source_url,
        "source_type": source_type,
        "source_id": source_id,
        "title": title,
        "text": text,
        "finding": _clean_text(record.get("finding") if not isinstance(record.get("finding"), dict) else finding.get("text") or finding.get("summary")),
        "genes": _normalize_genes([*_as_list(record.get("genes")), record.get("gene"), *(verified_fields.get("genes") or [])]),
        "drugs": _normalize_terms([*_as_list(record.get("drugs")), record.get("drug"), *(verified_fields.get("drugs") or [])]),
        "drug_classes": _normalize_terms([*_as_list(record.get("drug_classes")), record.get("drug_class"), *(verified_fields.get("drug_classes") or [])]),
        "indications": _normalize_terms([*_as_list(record.get("indications")), record.get("indication"), record.get("condition"), *(verified_fields.get("indications") or [])]),
        "mechanisms": _normalize_terms([*_as_list(record.get("mechanisms")), record.get("mechanism"), record.get("moa"), *(verified_fields.get("mechanisms") or [])]),
    }
    normalized["verification"] = {
        "status": _verification_status(verified_fields, support_spans),
        "source_origin": source_origin,
        "source_family": _source_family(source_id, source_type, source_text, verified_fields),
        "verified_fields": verified_fields,
        "support_spans": support_spans,
        "query_context_support": _query_context_support(query, verified_fields, source_text),
        "limitations": _verification_limitations(query, verified_fields, source_url),
    }
    return normalized


def _verified_fields(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("verified_fields")
    if not isinstance(raw, dict):
        raw = {}
    output: dict[str, Any] = {
        "genes": _normalize_genes([*_as_list(raw.get("genes")), raw.get("gene")]),
        "drugs": _normalize_terms([*_as_list(raw.get("drugs")), raw.get("drug")]),
        "drug_classes": _normalize_terms([*_as_list(raw.get("drug_classes")), raw.get("drug_class")]),
        "indications": _normalize_terms([*_as_list(raw.get("indications")), raw.get("indication"), raw.get("condition")]),
        "mechanisms": _normalize_terms([*_as_list(raw.get("mechanisms")), raw.get("mechanism"), raw.get("moa")]),
        "target_relationships": _normalize_terms([*_as_list(raw.get("target_relationships")), raw.get("target_relationship"), raw.get("evidence_type")]),
    }
    return {key: value for key, value in output.items() if value}


def _valid_support_spans(record: dict[str, Any]) -> list[dict[str, str]]:
    spans = record.get("support_spans")
    if not isinstance(spans, list):
        return []
    valid: list[dict[str, str]] = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        field = _clean_text(span.get("field")).lower()
        value = _clean_text(span.get("value"))
        source_text = _clean_text(span.get("source_text") or span.get("text") or span.get("excerpt"))
        if field not in {
            "gene",
            "genes",
            "drug",
            "drugs",
            "drug_class",
            "drug_classes",
            "indication",
            "indications",
            "condition",
            "mechanism",
            "mechanisms",
            "moa",
            "target_relationship",
            "target_relationships",
            "evidence_type",
        }:
            continue
        if not value or not source_text or not _value_supported_by_text(value, source_text):
            continue
        normalized_field = {
            "gene": "genes",
            "drug": "drugs",
            "drug_class": "drug_classes",
            "condition": "indications",
            "indication": "indications",
            "mechanism": "mechanisms",
            "moa": "mechanisms",
            "target_relationship": "target_relationships",
            "evidence_type": "target_relationships",
        }.get(field, field)
        valid.append({"field": normalized_field, "value": value, "source_text": source_text})
    return valid


def _verified_fields_from_spans(spans: list[dict[str, str]]) -> dict[str, Any]:
    fields: dict[str, list[str]] = {
        "genes": [],
        "drugs": [],
        "drug_classes": [],
        "indications": [],
        "mechanisms": [],
        "target_relationships": [],
    }
    for span in spans:
        fields.setdefault(span["field"], []).append(span["value"])
    return {
        "genes": _normalize_genes(fields.get("genes", [])),
        "drugs": _normalize_terms(fields.get("drugs", [])),
        "drug_classes": _normalize_terms(fields.get("drug_classes", [])),
        "indications": _normalize_terms(fields.get("indications", [])),
        "mechanisms": _normalize_terms(fields.get("mechanisms", [])),
        "target_relationships": _normalize_terms(fields.get("target_relationships", [])),
    }


def _merge_verified_fields(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {
        "genes": _normalize_genes([*(left.get("genes") or []), *(right.get("genes") or [])]),
        "drugs": _normalize_terms([*(left.get("drugs") or []), *(right.get("drugs") or [])]),
        "drug_classes": _normalize_terms([*(left.get("drug_classes") or []), *(right.get("drug_classes") or [])]),
        "indications": _normalize_terms([*(left.get("indications") or []), *(right.get("indications") or [])]),
        "mechanisms": _normalize_terms([*(left.get("mechanisms") or []), *(right.get("mechanisms") or [])]),
        "target_relationships": _normalize_terms([*(left.get("target_relationships") or []), *(right.get("target_relationships") or [])]),
    }


def _stored_records(
    evidence_db: str | Path | None,
    *,
    query_terms: Iterable[str | None],
    search_stored_research: bool,
    limit: int,
) -> list[dict[str, Any]]:
    if evidence_db is None or not search_stored_research:
        return []
    records: list[dict[str, Any]] = []
    remaining = max(0, int(limit or 25))
    for query in _stored_search_queries(query_terms):
        if remaining <= 0:
            break
        try:
            result = search_research_findings(evidence_db, query, scope="shared", limit=remaining)
        except (OSError, ValueError, sqlite3.Error):
            continue
        for record in result.get("records") or []:
            if isinstance(record, dict):
                records.append(record)
                remaining -= 1
                if remaining <= 0:
                    break
    return records


def _stored_research_to_source_record(record: dict[str, Any]) -> dict[str, Any]:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    finding = record.get("finding") if isinstance(record.get("finding"), dict) else {}
    target = record.get("target") if isinstance(record.get("target"), dict) else {}
    raw = {
        "record_id": record.get("finding_id"),
        "genes": [target.get("gene")] if target.get("gene") else [],
        "drugs": [target.get("drug")] if target.get("drug") else [],
        "indications": [target.get("condition")] if target.get("condition") else [],
        "source_title": source.get("title"),
        "source_url": source.get("url"),
        "source_type": source.get("type"),
        "source_id": source.get("source_id"),
        "finding": finding.get("text") or finding.get("summary"),
        "finding_type": finding.get("type"),
        "searched_query": record.get("searched_query"),
        "captured_by": record.get("captured_by"),
        "captured_at": record.get("captured_at"),
    }
    for key in ("verified_fields", "support_spans", "verification_status"):
        if key in record:
            raw[key] = record[key]
    return raw


def _query_context(record: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    support = record.get("verification", {}).get("query_context_support") or {}
    verified_context = [
        key
        for key, value in support.items()
        if value in {"verified_drug", "verified_drug_class", "verified_indication", "verified_mechanism"}
    ]
    relationships = record.get("verification", {}).get("verified_fields", {}).get("target_relationships") or []
    source_family = record.get("verification", {}).get("source_family")
    direct_target_context = bool(verified_context and source_family == "drug_target_source" and _direct_relationship(relationships, record))
    source_text = " ".join(str(record.get(key) or "") for key in ("text", "finding", "title", "source_type", "source_title"))
    token_overlap = _context_token_overlap(query, source_text)
    return {
        "verified_context": verified_context,
        "verified_count": len(verified_context),
        "direct_target_context": direct_target_context,
        "token_overlap": token_overlap,
    }


def _query_context_support(query: dict[str, Any], verified_fields: dict[str, Any], source_text: str) -> dict[str, str]:
    support: dict[str, str] = {}
    for key, field, status in (
        ("drug", "drugs", "verified_drug"),
        ("drug_class", "drug_classes", "verified_drug_class"),
        ("indication", "indications", "verified_indication"),
        ("mechanism", "mechanisms", "verified_mechanism"),
    ):
        value = query.get(key)
        if not value:
            continue
        verified_values = verified_fields.get(field) or []
        support[f"{key}:{value}"] = status if _any_field_matches(value, verified_values) else ("mentioned_unverified" if _value_supported_by_text(value, source_text) else "not_supported")
    return support


def _direct_relationship(relationships: Iterable[str], record: dict[str, Any]) -> bool:
    text = " ".join([*(relationships or []), str(record.get("finding_type") or ""), str(record.get("source_type") or ""), str(record.get("finding") or ""), str(record.get("text") or "")]).casefold()
    direct_terms = (
        "drug target",
        "target",
        "mechanism",
        "moa",
        "inhibitor",
        "agonist",
        "antagonist",
        "binds",
        "binding",
        "program",
        "bioactivity",
    )
    association_only = ("association score", "genetic association", "gwas-catalog", "tractability")
    return any(term in text for term in direct_terms) and not all(term in text for term in association_only)


def _source_family(source_id: str, source_type: str, text: str, verified_fields: dict[str, Any]) -> str:
    tokens = set(_tokens(" ".join([source_id, source_type, text, " ".join(verified_fields.get("target_relationships") or [])])))
    source_id_norm = source_id.casefold()
    if source_id_norm == "opentargets":
        return "association_source"
    if source_id_norm in DRUG_TARGET_SOURCE_IDS or tokens & DRUG_TARGET_SOURCE_TOKENS:
        return "drug_target_source"
    if tokens & ASSOCIATION_ONLY_SOURCE_TOKENS:
        return "association_source"
    if tokens & {"literature", "pubmed", "pmid", "doi"}:
        return "literature_source"
    return "source_record"


def _gene_verified(gene: str, record: dict[str, Any]) -> bool:
    return _normalize_gene(gene) in {item.upper() for item in record.get("verification", {}).get("verified_fields", {}).get("genes") or []}


def _gene_mentioned(gene: str, record: dict[str, Any]) -> bool:
    normalized = _normalize_gene(gene)
    if normalized in {item.upper() for item in record.get("genes") or []}:
        return True
    return bool(re.search(rf"\b{re.escape(normalized)}\b", _record_text(record), flags=re.I))


def _negative_record(record: dict[str, Any]) -> bool:
    text = " ".join(str(record.get(key) or "") for key in ("finding", "text", "finding_type", "source_type")).casefold()
    return any(term in text for term in ("conflicting", "negative", "not a target", "no target", "failed", "insufficient evidence"))


def _source_review_plan() -> dict[str, Any]:
    source_ids = ["chembl", "drugbank", "pharmaprojects", "opentargets", "pubmed_or_primary_literature"]
    catalog = evidence_source_catalog()
    by_id = {source["source_id"]: source for source in catalog.get("sources") or []}
    return {
        "safe_external_targets": ["drug names", "drug classes", "indications", "mechanisms", "candidate genes"],
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
        "write_back_rule": "Record direct drug-target or mechanism findings with support spans before identifier-only answers.",
    }


def _decision_policy() -> dict[str, Any]:
    return {
        "policy_id": "drug_target_gene_prioritization_v1",
        "ranking_order": [
            "source-verified drug-target or mechanism gene evidence",
            "source-verified drug, class, indication, or mechanism context",
            "same-gene source support",
            "nearby source context",
            "generic literature plausibility",
        ],
        "rule": "Association-only evidence, including Open Targets target-disease scores, cannot outrank direct drug-target or mechanism evidence.",
    }


def _warnings(records: list[dict[str, Any]], selected: dict[str, Any] | None, candidates: list[str]) -> list[str]:
    warnings = []
    if not candidates:
        warnings.append("missing_candidate_genes:ranking_requires_candidates")
    if not records:
        warnings.append("missing_source_records:ranking_requires_drug_target_source_records")
    if selected and selected.get("answerability") != "direct_source_supported":
        warnings.append("selected_candidate_without_direct_source_support:keep_lower_support")
    if any(record.get("verification", {}).get("source_family") == "association_source" for record in records):
        warnings.append("association_only_source_records:capped_below_direct_drug_target_evidence")
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
        "direct_source_record_count": sum(1 for record in records if record.get("verification", {}).get("source_family") == "drug_target_source"),
        "top_observed_candidate": selected.get("candidate_id") if selected else None,
        "top_observed_support_level": selected.get("evidence_support_level") if selected else "none",
    }


def _next_actions(query: dict[str, Any], *, direct: bool) -> list[dict[str, Any]]:
    if direct:
        return [
            {
                "operation": "research.record",
                "params": {"payload": "<reviewed finding>", "scope": "shared"},
                "reason": "persist direct target evidence before user-facing interpretation",
            }
        ]
    return [
        {
            "operation": "research.list_sources",
            "params": {"target_type": "gene"},
            "reason": "identify drug-target and mechanism sources to review",
        },
        {
            "operation": "research.record",
            "params": {"payload": "<reviewed finding>", "scope": "shared"},
            "reason": "store ChEMBL, DrugBank, Pharmaprojects, or direct mechanism findings with support spans",
        },
    ]


def _record_templates(query: dict[str, Any]) -> list[dict[str, Any]]:
    templates = []
    for gene in query.get("genes") or ["<GENE>"]:
        templates.append(
            {
                "target": {"type": "gene", "gene": gene},
                "source": {"title": "", "url": "", "type": "", "accessed_at": utc_now()},
                "searched_query": " ".join(str(item) for item in (query.get("drug"), query.get("drug_class"), query.get("indication"), gene) if item),
                "finding": {"type": "drug_target", "text": "", "summary": ""},
                "verified_fields": {},
                "support_spans": [],
                "captured_by": "agent",
            }
        )
    return templates


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
        "direct_target_context": item["direct_target_context"],
        "token_overlap": item["token_overlap"],
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
    return ["Ranked lower by deterministic candidate tie-breaker."]


def _verification_status(verified_fields: dict[str, Any], support_spans: list[dict[str, str]]) -> str:
    if any(verified_fields.values()) and support_spans:
        return "verified"
    if any(verified_fields.values()) or support_spans:
        return "partially_verified"
    return "unverified"


def _verification_limitations(query: dict[str, Any], verified_fields: dict[str, Any], source_url: Any) -> list[str]:
    limitations = []
    if not source_url:
        limitations.append("source_url_missing")
    if query.get("drug") and not verified_fields.get("drugs"):
        limitations.append("requested_drug_not_source_verified")
    if query.get("drug_class") and not verified_fields.get("drug_classes"):
        limitations.append("requested_drug_class_not_source_verified")
    if query.get("indication") and not verified_fields.get("indications"):
        limitations.append("requested_indication_not_source_verified")
    if query.get("mechanism") and not verified_fields.get("mechanisms"):
        limitations.append("requested_mechanism_not_source_verified")
    return limitations


def _record_text(record: dict[str, Any]) -> str:
    return " ".join(str(record.get(key) or "") for key in ("text", "finding", "title", "source_type", "source_title"))


def _verified_field_text(verified_fields: dict[str, Any]) -> str:
    chunks: list[str] = []
    for value in verified_fields.values():
        if isinstance(value, list):
            chunks.extend(str(item) for item in value)
        else:
            chunks.append(str(value))
    return " ".join(chunks)


def _stored_search_queries(query_terms: Iterable[str | None]) -> list[str]:
    queries = []
    for value in query_terms:
        text = _clean_text(value)
        if not text:
            continue
        queries.append(" ".join(text.split()[:6]))
    return _dedupe(queries)
