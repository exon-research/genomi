from __future__ import annotations

import hashlib
import json
from typing import Any

from ....evidence import envelope as _env
from ....evidence.candidate_evidence import (
    DIRECT_SOURCE_MATCH,
    EXACT_TRAIT_MATCH,
    SAME_GENE_OR_LOCUS,
    answerability_for_lane,
    evidence_support_level_for_score,
    empty_lanes,
    evidence_view,
    lane,
)
from ....evidence.task_profiles import PGX_MEDICATION_REVIEW
from ._common import JsonObject, _clean, _compact_text, _normalize_gene, _normalize_rsid

MEDICATION_REVIEW_MATRIX_POLICY_ID = "pgx_medication_review_matrix_v1"

_PUBLIC_SOURCE_IDS = {"clinpgx", "pgxdb", "fda_pgx"}


def build_medication_review_matrix(
    *,
    query: JsonObject,
    evidence_items: list[JsonObject],
    sample_context_requested: bool,
    interpretation_readiness: JsonObject,
) -> JsonObject:
    rows = [
        _row_from_evidence_item(
            query=query,
            item=item,
            evidence_items=evidence_items,
            sample_context_requested=sample_context_requested,
            interpretation_readiness=interpretation_readiness,
        )
        for item in evidence_items
    ]
    rows = _dedupe_rows([row for row in rows if row is not None])
    return {
        "policy_id": MEDICATION_REVIEW_MATRIX_POLICY_ID,
        "row_count": len(rows),
        "rows": rows,
        "traceability": _traceability(rows),
    }


def medication_review_evidence_view(
    *,
    query: JsonObject,
    medication_review_matrix: JsonObject,
    status: str,
    unanswered_answer_components: Any,
    source_availability: JsonObject,
) -> JsonObject:
    rows = [
        _candidate_row_from_medication_row(row)
        for row in medication_review_matrix.get("rows") or []
        if isinstance(row, dict)
    ]
    rows.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("candidate_id") or "")))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index if row["score"] > 0 else None
        row["why_not_selected"] = [] if index == 1 and row["score"] > 0 else ["Lower PGx evidence-row rank than the selected review row."]
    selected = rows[0] if rows and rows[0].get("rank") == 1 else None
    decision_policy = {
        "policy_id": "pgx_medication_review_row_candidate_matrix_v1",
        "matrix_policy_id": medication_review_matrix.get("policy_id"),
        "ranking_order": [
            "drug-gene or drug-variant source rows with sample support",
            "drug-gene or drug-variant source rows without sample support",
            "sample-only PGx evidence rows requiring source linkage",
            "drug label and stored review rows",
        ],
        "rule": "Each candidate row is derived from one medication_review_matrix row and remains informational evidence, not prescribing action.",
    }
    return evidence_view(
        task_profile=PGX_MEDICATION_REVIEW,
        query=query,
        candidate_matrix=rows,
        top_observed_candidate=selected,
        evidence_policy=decision_policy,
        warnings=_warnings(rows, status, unanswered_answer_components, source_availability),
    )


def _row_from_evidence_item(
    *,
    query: JsonObject,
    item: JsonObject,
    evidence_items: list[JsonObject],
    sample_context_requested: bool,
    interpretation_readiness: JsonObject,
) -> JsonObject | None:
    evidence_id = str(item.get("evidence_id") or "")
    evidence_class = str(item.get("evidence_class") or "unknown")
    evidence_role = str(item.get("evidence_role") or "")
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    finding = item.get("finding") if isinstance(item.get("finding"), dict) else {}
    source_id = str(source.get("source_id") or "")

    row_type = _row_type(evidence_class=evidence_class, evidence_role=evidence_role, target=target, finding=finding, source_id=source_id)
    if row_type is None:
        return None

    drug = _clean(target.get("drug")) or _clean(query.get("drug"))
    gene = _normalize_gene(
        target.get("gene")
        or target.get("gene_or_biomarker")
        or _gene_from_called_star_alleles(finding.get("called_star_alleles"))
        or query.get("gene")
    )
    rsid = _normalize_rsid(target.get("rsid") or query.get("rsid"))
    variant_or_haplotype = _clean(target.get("variant_or_haplotype")) or _clean(rsid)
    diplotype = _clean(finding.get("possible_diplotype") or finding.get("known_diplotype"))
    phenotype = _clean(finding.get("predicted_phenotype") or finding.get("known_phenotype"))
    activity_score = finding.get("activity_score") or finding.get("known_activity_score")
    recommendation_text = _recommendation_text(finding)
    sample_evidence_matches = _matching_sample_evidence_matches(
        row_type=row_type,
        gene=gene,
        rsid=rsid,
        evidence_id=evidence_id,
        evidence_items=evidence_items,
    )
    sample_evidence_ids = _sample_evidence_ids(sample_evidence_matches)
    source_evidence_ids = _source_evidence_ids(
        row_type=row_type,
        evidence_id=evidence_id,
        source_id=source_id,
    )
    stored_research_evidence_ids = [evidence_id] if source_id == "stored_research" and evidence_id else []
    user_supplied_evidence_ids = [evidence_id] if source_id == "user_provided" and evidence_id else []
    sample_relevance = _sample_relevance(
        row_type=row_type,
        source_id=source_id,
        evidence_class=evidence_class,
        sample_context_requested=sample_context_requested,
        sample_evidence_matches=sample_evidence_matches,
        gene=gene,
        rsid=rsid,
    )
    row = {
        "row_type": row_type,
        "drug": drug,
        "gene": gene,
        "rsid": rsid,
        "variant_or_haplotype": variant_or_haplotype,
        "diplotype": diplotype,
        "phenotype": phenotype,
        "activity_score": activity_score,
        "recommendation_text": recommendation_text,
        "evidence_classes": [evidence_class],
        "source_evidence_ids": source_evidence_ids,
        "sample_evidence_ids": sample_evidence_ids,
        "stored_research_evidence_ids": stored_research_evidence_ids,
        "user_supplied_evidence_ids": user_supplied_evidence_ids,
        "source_counts": _source_counts(source_id),
        "sample_relevance": sample_relevance,
        "readiness": _row_readiness(row_type=row_type, sample_relevance=sample_relevance, source_evidence_ids=source_evidence_ids),
        "clinical_boundary": _clinical_boundary(interpretation_readiness),
    }
    row["row_id"] = _row_id(row)
    return row


def _row_type(*, evidence_class: str, evidence_role: str, target: JsonObject, finding: JsonObject, source_id: str) -> str | None:
    if source_id == "stored_research":
        return "stored_review"
    if source_id == "user_provided":
        return "sample_only"
    if evidence_role == "sample_pgx_evidence":
        if finding.get("possible_diplotype") or finding.get("known_diplotype"):
            return "drug_gene_diplotype"
        if finding.get("predicted_phenotype") or finding.get("known_phenotype") or finding.get("known_activity_score"):
            return "drug_gene_phenotype"
        return "sample_only"
    if evidence_class in {"fda_pharmacogenomic_biomarker_labeling", "fda_pharmacogenetic_association", "clinpgx_drug_label_annotation"}:
        return "drug_label"
    if target.get("rsid") or target.get("variant_or_haplotype"):
        return "drug_gene_variant"
    if finding.get("possible_diplotype"):
        return "drug_gene_diplotype"
    if target.get("gene") or target.get("gene_or_biomarker") or finding.get("summary"):
        return "drug_gene_phenotype"
    return None


def _matching_sample_evidence_matches(
    *,
    row_type: str,
    gene: str | None,
    rsid: str | None,
    evidence_id: str,
    evidence_items: list[JsonObject],
) -> list[JsonObject]:
    if row_type == "sample_only":
        return [{"evidence_id": evidence_id, "match_basis": "sample_row"}] if evidence_id else []
    matches: list[JsonObject] = []
    for item in evidence_items:
        if str(item.get("evidence_role") or "") != "sample_pgx_evidence":
            continue
        target = item.get("target") if isinstance(item.get("target"), dict) else {}
        item_finding = item.get("finding") if isinstance(item.get("finding"), dict) else {}
        item_gene = _normalize_gene(target.get("gene") or _gene_from_called_star_alleles(item_finding.get("called_star_alleles")))
        item_rsid = _normalize_rsid(target.get("rsid"))
        sample_id = str(item.get("evidence_id") or "")
        if not sample_id:
            continue
        if rsid and item_rsid == rsid:
            matches.append({"evidence_id": sample_id, "match_basis": "exact_rsid"})
        elif gene and item_gene == gene:
            matches.append({"evidence_id": sample_id, "match_basis": "gene_or_marker"})
    return _dedupe_sample_evidence_matches(matches)


def _sample_evidence_ids(matches: list[JsonObject]) -> list[str]:
    return sorted({str(match.get("evidence_id")) for match in matches if match.get("evidence_id")})


def _dedupe_sample_evidence_matches(matches: list[JsonObject]) -> list[JsonObject]:
    best_basis = {"exact_rsid": 0, "sample_row": 1, "gene_or_marker": 2}
    by_id: dict[str, JsonObject] = {}
    for match in matches:
        evidence_id = str(match.get("evidence_id") or "")
        if not evidence_id:
            continue
        existing = by_id.get(evidence_id)
        if existing is None or best_basis.get(str(match.get("match_basis")), 9) < best_basis.get(str(existing.get("match_basis")), 9):
            by_id[evidence_id] = dict(match)
    return sorted(by_id.values(), key=lambda item: str(item.get("evidence_id") or ""))


def _source_evidence_ids(*, row_type: str, evidence_id: str, source_id: str) -> list[str]:
    if row_type == "sample_only" and source_id != "stored_research":
        return []
    return [evidence_id] if evidence_id and source_id in _PUBLIC_SOURCE_IDS | {"stored_research"} else []


def _source_counts(source_id: str) -> JsonObject:
    counts = {"ClinPGx": 0, "PGxDB": 0, "FDA": 0, "stored_research": 0}
    if source_id == "clinpgx":
        counts["ClinPGx"] = 1
    elif source_id == "pgxdb":
        counts["PGxDB"] = 1
    elif source_id == "fda_pgx":
        counts["FDA"] = 1
    elif source_id == "stored_research":
        counts["stored_research"] = 1
    return counts


def _sample_relevance(
    *,
    row_type: str,
    source_id: str,
    evidence_class: str,
    sample_context_requested: bool,
    sample_evidence_matches: list[JsonObject],
    gene: str | None,
    rsid: str | None,
) -> JsonObject:
    match_bases = {str(match.get("match_basis") or "") for match in sample_evidence_matches}
    sample_evidence_ids = _sample_evidence_ids(sample_evidence_matches)
    if source_id == "user_provided":
        state = "user_supplied_pgx"
    elif source_id == "stored_research" and evidence_class.startswith("pharmcat_sample_pgx"):
        state = "stored_private_review"
    elif row_type == "sample_only":
        state = "sample_target_observed"
    elif "exact_rsid" in match_bases:
        state = "sample_target_observed"
    elif sample_evidence_ids:
        state = "sample_marker_observed"
    elif not sample_context_requested and (gene or rsid):
        state = "sample_context_not_requested"
    elif not sample_context_requested:
        state = "public_only"
    else:
        state = "sample_not_observed_in_consulted_scope"
    return {
        "state": state,
        "matched_sample_evidence_ids": sample_evidence_ids,
    }


def _row_readiness(*, row_type: str, sample_relevance: JsonObject, source_evidence_ids: list[str]) -> str:
    state = str(sample_relevance.get("state") or "")
    if state in {"sample_target_observed", "sample_marker_observed", "stored_private_review"} and source_evidence_ids:
        return _env.NEEDS_CLINICAL_CONFIRMATION
    if state == "user_supplied_pgx" and source_evidence_ids:
        return _env.NEEDS_CLINICAL_CONFIRMATION
    if source_evidence_ids:
        return _env.SCOPED_ANSWER_ONLY
    if row_type in {"sample_only", "drug_gene_diplotype", "drug_gene_phenotype"}:
        return _env.CANNOT_ANSWER_YET
    return _env.SCOPED_ANSWER_ONLY


def _clinical_boundary(interpretation_readiness: JsonObject) -> list[str]:
    values = [
        str(item)
        for item in interpretation_readiness.get("requires_before_personal_actionability") or []
        if item
    ]
    if not values:
        values = [
            "sample identity",
            "clinical indication",
            "current medications and contraindications",
            "clinician or pharmacist confirmation",
        ]
    return values


def _recommendation_text(finding: JsonObject) -> str | None:
    text = (
        finding.get("summary")
        or finding.get("recommendation")
        or finding.get("known_phenotype")
        or finding.get("predicted_phenotype")
        or finding.get("marker_support_status")
    )
    return _compact_text(text, max_chars=900) if text else None


def _gene_from_called_star_alleles(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if not isinstance(item, dict):
            continue
        star_allele = str(item.get("star_allele") or "")
        if "*" in star_allele:
            return star_allele.split("*", 1)[0] or None
    return None


def _row_id(row: JsonObject) -> str:
    identity = {
        "row_type": row.get("row_type"),
        "drug": row.get("drug"),
        "gene": row.get("gene"),
        "rsid": row.get("rsid"),
        "variant_or_haplotype": row.get("variant_or_haplotype"),
        "diplotype": row.get("diplotype"),
        "phenotype": row.get("phenotype"),
        "evidence_classes": row.get("evidence_classes"),
        "source_evidence_ids": row.get("source_evidence_ids"),
        "sample_evidence_ids": row.get("sample_evidence_ids"),
        "stored_research_evidence_ids": row.get("stored_research_evidence_ids"),
        "user_supplied_evidence_ids": row.get("user_supplied_evidence_ids"),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"pgxrow_{digest[:16]}"


def _dedupe_rows(rows: list[JsonObject]) -> list[JsonObject]:
    by_id: dict[str, JsonObject] = {}
    for row in rows:
        by_id.setdefault(str(row.get("row_id")), row)
    return list(by_id.values())


def _traceability(rows: list[JsonObject]) -> JsonObject:
    source_ids: set[str] = set()
    sample_ids: set[str] = set()
    stored_ids: set[str] = set()
    user_ids: set[str] = set()
    state_counts: dict[str, int] = {}
    row_type_counts: dict[str, int] = {}
    for row in rows:
        source_ids.update(str(item) for item in row.get("source_evidence_ids") or [] if item)
        sample_ids.update(str(item) for item in row.get("sample_evidence_ids") or [] if item)
        stored_ids.update(str(item) for item in row.get("stored_research_evidence_ids") or [] if item)
        user_ids.update(str(item) for item in row.get("user_supplied_evidence_ids") or [] if item)
        state = str((row.get("sample_relevance") or {}).get("state") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
        row_type = str(row.get("row_type") or "unknown")
        row_type_counts[row_type] = row_type_counts.get(row_type, 0) + 1
    return {
        "row_ids": [row["row_id"] for row in rows if row.get("row_id")],
        "unique_row_id_count": len({row.get("row_id") for row in rows if row.get("row_id")}),
        "source_evidence_ids": sorted(source_ids),
        "sample_evidence_ids": sorted(sample_ids),
        "stored_research_evidence_ids": sorted(stored_ids),
        "user_supplied_evidence_ids": sorted(user_ids),
        "sample_relevance_state_counts": state_counts,
        "row_type_counts": row_type_counts,
    }


def _candidate_row_from_medication_row(row: JsonObject) -> JsonObject:
    sample_state = str((row.get("sample_relevance") or {}).get("state") or "")
    has_source = bool(row.get("source_evidence_ids"))
    has_sample = bool(row.get("sample_evidence_ids") or row.get("user_supplied_evidence_ids") or row.get("stored_research_evidence_ids"))
    if has_source and sample_state in {"sample_target_observed", "sample_marker_observed", "stored_private_review", "user_supplied_pgx"}:
        best_lane = DIRECT_SOURCE_MATCH
        score = 0.9
    elif has_source:
        best_lane = EXACT_TRAIT_MATCH
        score = 0.7
    elif has_sample:
        best_lane = SAME_GENE_OR_LOCUS
        score = 0.55
    else:
        best_lane = None
        score = 0.0
    lanes = empty_lanes()
    if best_lane:
        lanes[best_lane] = lane(
            best_lane,
            status="present",
            score=score,
            source="PGx medication review matrix",
            matched_text=_candidate_matched_text(row),
            source_id=row.get("row_id"),
        )
    return {
        "candidate_id": row.get("row_id"),
        "candidate_type": "pgx_medication_review_row",
        "rank": None,
        "score": score,
        "evidence_support_level": evidence_support_level_for_score(score),
        "answerability": answerability_for_lane(best_lane),
        "best_evidence_lane": best_lane,
        "evidence_lanes": lanes,
        "supporting_evidence": [row],
        "counter_evidence": [{"type": "clinical_boundary", "requires": row.get("clinical_boundary") or []}],
        "why_not_selected": [],
    }


def _candidate_matched_text(row: JsonObject) -> str:
    parts = [
        row.get("drug"),
        row.get("gene"),
        row.get("rsid") or row.get("diplotype") or row.get("phenotype"),
        row.get("recommendation_text"),
    ]
    return " ".join(str(part) for part in parts if part)[:500]


def _warnings(
    rows: list[JsonObject],
    status: str,
    unanswered_answer_components: Any,
    source_availability: JsonObject,
) -> list[str]:
    warnings = []
    if not rows:
        warnings.append("no_pgx_medication_review_rows:review_source_coverage")
    if status != "completed":
        warnings.append(f"{status}:inspect_evidence_envelope")
    if unanswered_answer_components:
        warnings.append("unresolved_pgx_evidence_components:inspect_unanswered_components")
    if str(source_availability.get("status") or "").startswith("source_unavailable"):
        warnings.append("live_pgx_public_source_unavailable:report_answerability_gap")
    return warnings
