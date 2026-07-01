from __future__ import annotations

from typing import Any

from ....evidence.candidate_evidence import (
    DIRECT_SOURCE_MATCH,
    NEARBY_TRAIT_MATCH,
    NEGATIVE_OR_CONFLICTING_EVIDENCE,
    SAME_GENE_OR_LOCUS,
    answerability_for_lane,
    evidence_support_level_for_score,
    empty_lanes,
    lane,
)
from ....evidence.store.candidate_groups import (
    CANDIDATE_REVIEW_GROUP_POLICY_ID,
    missing_interpretation_gates,
    review_group_counts_by_type,
)

CLINVAR_CONDITION_REVIEW_GROUP_TYPES = {
    "carrier_relevance",
    "observed_condition",
    "uncertain_or_conflicting",
    "risk_association",
    "benign_or_counterevidence",
    "quality_or_population_context",
}
REVIEW_GROUP_TYPES_BY_MODE = {
    "carrier_review": {"carrier_relevance"},
    "observed_condition_review": {
        "observed_condition",
        "uncertain_or_conflicting",
        "risk_association",
        "benign_or_counterevidence",
        "quality_or_population_context",
    },
    "rare_disease": CLINVAR_CONDITION_REVIEW_GROUP_TYPES,
    "cancer_risk": CLINVAR_CONDITION_REVIEW_GROUP_TYPES,
}


def filtered_review_groups(
    matrix: Any,
    *,
    mode: str,
    genes: list[str],
    condition: str | None,
    limit: int,
) -> dict[str, Any]:
    source = matrix if isinstance(matrix, dict) else {}
    allowed_types = REVIEW_GROUP_TYPES_BY_MODE.get(mode, REVIEW_GROUP_TYPES_BY_MODE["rare_disease"])
    groups = []
    for group in source.get("groups") or []:
        if not isinstance(group, dict):
            continue
        if str(group.get("group_type") or "") not in allowed_types:
            continue
        group = dict(group)
        group["target_match_status"] = _review_group_target_match_status(group, genes=genes, condition=condition)
        if group["target_match_status"] == "not_requested_target_mismatch":
            continue
        groups.append(group)
    groups.sort(key=_review_group_filter_sort_key)
    groups = groups[:limit]
    return {
        "policy_id": source.get("policy_id") or CANDIDATE_REVIEW_GROUP_POLICY_ID,
        "group_count": len(groups),
        "groups": groups,
        "group_counts_by_type": review_group_counts_by_type(groups),
    }


def review_group_rows(active_candidates: dict[str, Any]) -> list[dict[str, Any]]:
    matrix = active_candidates.get("candidate_review_groups")
    groups = matrix.get("groups") if isinstance(matrix, dict) else []
    rows: list[dict[str, Any]] = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        best_lane = _review_group_lane(group)
        score = _review_group_score(group, best_lane)
        lanes = empty_lanes()
        lanes[best_lane] = lane(
            best_lane,
            status="present",
            score=score,
            source="ClinVar candidate review group",
            matched_text=_review_group_text(group),
            note="review group requiring interpretation gates before clinical wording",
        )
        rows.append(
            {
                "candidate_id": group.get("group_id"),
                "candidate_type": "clinvar_review_group",
                "rank": None,
                "score": score,
                "evidence_support_level": evidence_support_level_for_score(score),
                "answerability": answerability_for_lane(best_lane),
                "best_evidence_lane": best_lane,
                "evidence_lanes": lanes,
                "supporting_evidence": [group],
                "counter_evidence": _review_group_counter_evidence(group),
            }
        )
    return rows


def _review_group_target_match_status(group: dict[str, Any], *, genes: list[str], condition: str | None) -> str:
    if not genes and not condition:
        return "no_target_filter"
    gene = str(group.get("gene") or "").upper()
    if genes and gene and gene in set(genes):
        return "requested_gene_match"
    if condition and group.get("condition"):
        condition_text = condition.casefold()
        if condition_text in str(group["condition"]).casefold():
            return "requested_condition_text_match"
    return "not_requested_target_mismatch"


def _review_group_filter_sort_key(group: dict[str, Any]) -> tuple[float, int, int, str, str]:
    best_lane = _review_group_lane(group)
    lane_order = {
        DIRECT_SOURCE_MATCH: 0,
        SAME_GENE_OR_LOCUS: 1,
        NEARBY_TRAIT_MATCH: 2,
        NEGATIVE_OR_CONFLICTING_EVIDENCE: 3,
    }
    return (
        -_review_group_score(group, best_lane),
        len(_missing_group_gates(group)),
        lane_order.get(best_lane, 9),
        str(group.get("gene") or ""),
        str(group.get("group_id") or ""),
    )


def _review_group_lane(group: dict[str, Any]) -> str:
    group_type = str(group.get("group_type") or "")
    if group_type in {"carrier_relevance", "observed_condition"}:
        return DIRECT_SOURCE_MATCH
    if group_type in {"uncertain_or_conflicting", "benign_or_counterevidence", "quality_or_population_context"}:
        return NEGATIVE_OR_CONFLICTING_EVIDENCE
    if group_type == "risk_association":
        return NEARBY_TRAIT_MATCH
    return SAME_GENE_OR_LOCUS


def _review_group_score(group: dict[str, Any], best_lane: str) -> float:
    group_type = str(group.get("group_type") or "")
    base = {
        "carrier_relevance": 0.92,
        "observed_condition": 0.88,
        "uncertain_or_conflicting": 0.55,
        "risk_association": 0.5,
        "drug_response": 0.45,
        "benign_or_counterevidence": 0.35,
        "quality_or_population_context": 0.25,
    }.get(group_type, 0.25)
    missing_gate_count = len(_missing_group_gates(group))
    if best_lane == NEGATIVE_OR_CONFLICTING_EVIDENCE:
        return max(0.2, base - missing_gate_count * 0.02)
    return max(0.0, base - missing_gate_count * 0.03)


def _review_group_text(group: dict[str, Any]) -> str:
    significance = ", ".join(
        f"{label}:{count}" for label, count in (group.get("clinical_significance_counts") or [])[:3]
    )
    return " ".join(
        str(part)
        for part in (
            group.get("group_type"),
            group.get("gene"),
            group.get("condition"),
            significance,
        )
        if part
    )[:500]


def _review_group_counter_evidence(group: dict[str, Any]) -> list[dict[str, Any]]:
    counter: list[dict[str, Any]] = []
    missing = _missing_group_gates(group)
    if missing:
        counter.append({"type": "missing_interpretation_gates", "gates": missing})
    group_type = str(group.get("group_type") or "")
    if group_type == "uncertain_or_conflicting":
        counter.append({"type": "uncertain_or_conflicting_classification"})
    if group_type == "benign_or_counterevidence":
        counter.append({"type": "benign_or_likely_benign_classification"})
    if group.get("population_flags"):
        counter.append({"type": "population_or_quality_context", "flags": group.get("population_flags")})
    return counter


def _missing_group_gates(group: dict[str, Any]) -> list[str]:
    return missing_interpretation_gates(group)
