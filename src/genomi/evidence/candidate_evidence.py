from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import envelope as _env

EVIDENCE_VIEW_SCHEMA_VERSION = "genomi-candidate-evidence-view-v1"

DIRECT_SOURCE_MATCH = "direct_source_match"
EXACT_TRAIT_MATCH = "exact_trait_match"
ONTOLOGY_SYNONYM_MATCH = "ontology_synonym_match"
NEARBY_TRAIT_MATCH = "nearby_trait_match"
SAME_GENE_OR_LOCUS = "same_gene_or_locus"
PATHWAY_PLAUSIBILITY = "pathway_plausibility"
LITERATURE_PLAUSIBILITY = "literature_plausibility"
AGENT_REASONING_ONLY = "agent_reasoning_only"
NEGATIVE_OR_CONFLICTING_EVIDENCE = "negative_or_conflicting_evidence"

EVIDENCE_LANES = (
    DIRECT_SOURCE_MATCH,
    EXACT_TRAIT_MATCH,
    ONTOLOGY_SYNONYM_MATCH,
    NEARBY_TRAIT_MATCH,
    SAME_GENE_OR_LOCUS,
    PATHWAY_PLAUSIBILITY,
    LITERATURE_PLAUSIBILITY,
    AGENT_REASONING_ONLY,
    NEGATIVE_OR_CONFLICTING_EVIDENCE,
)


@dataclass(frozen=True)
class EvidenceLane:
    name: str
    status: str
    score: float = 0.0
    source: str | None = None
    matched_text: str | None = None
    source_id: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "score": self.score,
        }
        if self.source:
            payload["source"] = self.source
        if self.matched_text:
            payload["matched_text"] = self.matched_text
        if self.source_id:
            payload["source_id"] = self.source_id
        if self.note:
            payload["note"] = self.note
        return payload


def lane(
    name: str,
    *,
    status: str,
    score: float = 0.0,
    source: str | None = None,
    matched_text: str | None = None,
    source_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if name not in EVIDENCE_LANES:
        raise ValueError(f"unknown evidence lane {name!r}")
    return EvidenceLane(
        name=name,
        status=status,
        score=score,
        source=source,
        matched_text=matched_text,
        source_id=source_id,
        note=note,
    ).to_dict()


def empty_lanes(*, note: str | None = None) -> dict[str, dict[str, Any]]:
    return {
        name: lane(name, status="absent", note=note)
        for name in EVIDENCE_LANES
    }


def answerability_for_lane(lane_name: str | None) -> str:
    if lane_name in {DIRECT_SOURCE_MATCH, EXACT_TRAIT_MATCH, ONTOLOGY_SYNONYM_MATCH}:
        return "direct_source_supported"
    if lane_name in {NEARBY_TRAIT_MATCH, SAME_GENE_OR_LOCUS}:
        return "adjacent_source_supported"
    if lane_name in {PATHWAY_PLAUSIBILITY, LITERATURE_PLAUSIBILITY}:
        return "plausibility_only"
    return "not_supported"


def evidence_support_level_for_score(score: float) -> str:
    if score >= 0.9:
        return "high"
    if score >= 0.55:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def selected_from_matrix(candidate_matrix: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((candidate for candidate in candidate_matrix if candidate.get("rank") == 1), None)


def grouped_candidate_ids(candidate_matrix: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "direct_match_candidates": [
            str(candidate.get("candidate_id"))
            for candidate in candidate_matrix
            if candidate.get("answerability") == "direct_source_supported"
        ],
        "adjacent_match_candidates": [
            str(candidate.get("candidate_id"))
            for candidate in candidate_matrix
            if candidate.get("answerability") == "adjacent_source_supported"
        ],
        "plausibility_only_candidates": [
            str(candidate.get("candidate_id"))
            for candidate in candidate_matrix
            if candidate.get("answerability") == "plausibility_only"
        ],
        "unmatched_candidates": [
            str(candidate.get("candidate_id"))
            for candidate in candidate_matrix
            if candidate.get("answerability") == "not_supported"
        ],
    }


def source_local_ordering(
    rankings: list[dict[str, Any]],
    *,
    valid_for: str,
    not_valid_for: str | None = None,
    scope: str = "source_local_evidence_ordering",
) -> dict[str, Any]:
    return _source_local_ordering_payload(
        rankings,
        valid_for=valid_for,
        not_valid_for=not_valid_for,
        scope=scope,
    )


def _source_local_ordering_payload(
    rankings: list[dict[str, Any]],
    *,
    valid_for: str,
    not_valid_for: str | None = None,
    scope: str = "source_local_evidence_ordering",
) -> dict[str, Any]:
    return {
        "scope": scope,
        "valid_for": valid_for,
        "not_valid_for": not_valid_for,
        "ordered_candidates": rankings,
    }


def decision_evidence(
    candidate_matrix: list[dict[str, Any]],
    *,
    top_observed_candidate: dict[str, Any] | None = None,
    infer_top_observed_candidate: bool = True,
) -> dict[str, Any]:
    ranked = [
        candidate
        for candidate in candidate_matrix
        if candidate.get("rank") is not None
    ]
    top_observed = (
        top_observed_candidate
        if top_observed_candidate is not None
        else (selected_from_matrix(candidate_matrix) if infer_top_observed_candidate else None)
    )
    return {
        "top_observed_candidate": top_observed.get("candidate_id") if top_observed else None,
        "top_observed_evidence": _candidate_decision_evidence(top_observed) if top_observed else None,
        "ranked_candidate_evidence": [_candidate_decision_evidence(candidate) for candidate in ranked],
    }


def evidence_view(
    *,
    task_profile: dict[str, Any] | Any,
    candidate_matrix: list[dict[str, Any]],
    evidence_policy: dict[str, Any],
    query: dict[str, Any] | None = None,
    top_observed_candidate: dict[str, Any] | None = None,
    infer_top_observed_candidate: bool = True,
    warnings: list[str] | None = None,
    evidence_state: str | None = None,
    coverage_state: str | None = None,
    source_local_ordering: dict[str, Any] | None = None,
    source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inferred_top = (
        top_observed_candidate
        if top_observed_candidate is not None
        else (selected_from_matrix(candidate_matrix) if infer_top_observed_candidate else None)
    )
    profile_payload = task_profile.to_dict() if hasattr(task_profile, "to_dict") else dict(task_profile)
    rankings = [
        candidate
        for candidate in candidate_matrix
        if candidate.get("rank") is not None
    ]
    coverage_state = coverage_state or ("data_returned" if rankings else "in_scope_empty")
    if coverage_state != "data_returned":
        inferred_top = None
    exposed_matrix = candidate_matrix if coverage_state == "data_returned" else []
    exposed_rankings = rankings if coverage_state == "data_returned" else []
    grouped = grouped_candidate_ids(exposed_matrix)
    if coverage_state != "data_returned":
        grouped["unmatched_candidates"] = [
            str(candidate.get("candidate_id"))
            for candidate in candidate_matrix
            if isinstance(candidate, dict) and candidate.get("candidate_id") is not None
        ]
    top_observed = inferred_top
    evidence_for_decision = decision_evidence(
        exposed_matrix,
        top_observed_candidate=top_observed,
        infer_top_observed_candidate=False,
    )
    if source_local_ordering is None:
        source_local_ordering = _source_local_ordering_payload(
            exposed_rankings,
            valid_for="source_local_candidate_ranking",
            not_valid_for="host_agent_answer_selection",
        )
    if evidence_state is None:
        evidence_state = "decision_grade_evidence" if top_observed else "not_decision_grade"
    return {
        "schema": EVIDENCE_VIEW_SCHEMA_VERSION,
        "query": query or {},
        "task_profile": profile_payload,
        "evidence_policy": evidence_policy,
        "agent_decision_required": True,
        "coverage_state": coverage_state,
        "top_observed_candidate": top_observed.get("candidate_id") if top_observed else None,
        "top_observed": top_observed,
        "evidence_state": evidence_state,
        "source_local_ordering": source_local_ordering,
        "decision_evidence": evidence_for_decision,
        "candidate_matrix": exposed_matrix,
        "rankings": exposed_rankings,
        **grouped,
        "coverage": {
            "candidate_count": len(candidate_matrix),
            "ranked_candidate_count": len(exposed_rankings),
            "top_observed_candidate": top_observed.get("candidate_id") if top_observed else None,
            "top_observed_support_level": top_observed.get("evidence_support_level", "none") if top_observed else "none",
            "answerability_counts": _answerability_counts(exposed_matrix),
        },
        "source_coverage": source_coverage or {},
        "warnings": warnings or [],
    }


def apply_evidence_view(
    payload: dict[str, Any],
    view: dict[str, Any],
    *,
    expose_agent_fields: bool = True,
    operation: str | None = None,
    envelope: dict[str, Any] | None = None,
    personal_context: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    library_uses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload["evidence_view"] = view
    if envelope is None:
        envelope = envelope_from_evidence_view(
            view,
            operation=operation or str(payload.get("operation") or "unspecified"),
            personal_context=personal_context,
            coverage=coverage,
            library_uses=library_uses,
        )
    payload["evidence_envelope"] = envelope
    if not expose_agent_fields:
        return payload
    payload["candidate_matrix"] = view["candidate_matrix"]
    payload["rankings"] = view["rankings"]
    payload["decision_evidence"] = view["decision_evidence"]
    payload["top_observed_candidate"] = view["top_observed_candidate"]
    payload["top_observed"] = view["top_observed"]
    if "evidence_state" in payload:
        payload.setdefault("candidate_evidence_state", view.get("evidence_state"))
    else:
        payload["evidence_state"] = view.get("evidence_state")
    payload.setdefault("coverage_state", view.get("coverage_state"))
    payload["source_local_ordering"] = view.get("source_local_ordering")
    payload["direct_match_candidates"] = view["direct_match_candidates"]
    payload["adjacent_match_candidates"] = view["adjacent_match_candidates"]
    payload["plausibility_only_candidates"] = view["plausibility_only_candidates"]
    payload["unmatched_candidates"] = view["unmatched_candidates"]
    payload.setdefault("coverage", view["coverage"])
    if view.get("source_coverage"):
        payload.setdefault("source_coverage", view["source_coverage"])
    payload["warnings"] = _merge_warnings(payload.get("warnings"), view.get("warnings"))
    return payload


def envelope_from_evidence_view(
    view: dict[str, Any],
    *,
    operation: str,
    personal_context: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    library_uses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Derive an EvidenceEnvelope from a candidate evidence view.

    Default mapping:
      - coverage_state == "data_returned" with ranked candidates -> evidence_present, scoped_answer_only
      - coverage_state == "in_scope_empty" -> not_observed_in_consulted_scope, scoped_answer_only
      - other coverage states -> not_assessed, cannot_answer_yet

    Callers that need a different finding/readiness (eg. missing library)
    should build the envelope themselves and pass it via apply_evidence_view.
    """

    coverage_state = view.get("coverage_state") or "in_scope_empty"
    rankings = view.get("rankings") or []
    source_coverage = view.get("source_coverage") or {}

    consulted = []
    unavailable = []
    if isinstance(source_coverage, dict):
        for key in ("consulted", "checked", "queried", "available"):
            for item in source_coverage.get(key) or []:
                if isinstance(item, str):
                    consulted.append(item)
                elif isinstance(item, dict) and item.get("source_id"):
                    consulted.append(str(item["source_id"]))
        for key in ("unavailable", "missing", "not_integrated"):
            for item in source_coverage.get(key) or []:
                if isinstance(item, str):
                    unavailable.append(item)
                elif isinstance(item, dict) and item.get("source_id"):
                    unavailable.append(str(item["source_id"]))

    coverage_payload = coverage or _env._coverage(
        libraries=library_uses or [],
        consulted_sources=consulted,
        unavailable_sources=unavailable,
    )

    observations = {
        "observation_count": len(rankings),
        "candidate_count": len(view.get("candidate_matrix") or []),
        "top_observed_candidate": view.get("top_observed_candidate"),
        "top_observed_support_level": (view.get("coverage") or {}).get("top_observed_support_level"),
    }
    query_scope = dict(view.get("query") or {})

    if coverage_state == "data_returned" and rankings:
        return _env.evidence_present(
            operation=operation,
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=coverage_payload,
            observations=observations,
            answer_readiness=_env.SCOPED_ANSWER_ONLY,
        )
    if coverage_state == "in_scope_empty" or not rankings:
        return _env.empty_consulted_scope(
            operation=operation,
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=coverage_payload,
            observations=observations,
        )
    return _env.not_assessed(
        operation=operation,
        reason=f"unexpected coverage_state={coverage_state!r}",
        query_scope=query_scope,
        personal_context=personal_context,
        coverage=coverage_payload,
        observations=observations,
    )


def _candidate_decision_evidence(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    supporting_evidence = candidate.get("supporting_evidence") if isinstance(candidate.get("supporting_evidence"), list) else []
    counter_evidence = candidate.get("counter_evidence") if isinstance(candidate.get("counter_evidence"), list) else []
    return {
        "candidate": candidate.get("candidate_id"),
        "rank": candidate.get("rank"),
        "score": candidate.get("score"),
        "evidence_support_level": candidate.get("evidence_support_level"),
        "answerability": candidate.get("answerability"),
        "best_evidence_lane": candidate.get("best_evidence_lane"),
        "evidence_lanes": candidate.get("evidence_lanes"),
        "evidence_trace": _candidate_evidence_trace(candidate, supporting_evidence, counter_evidence),
        "supporting_evidence": supporting_evidence,
        "counter_evidence": counter_evidence,
        "why_not_selected": candidate.get("why_not_selected") or [],
    }


def _candidate_evidence_trace(
    candidate: dict[str, Any],
    supporting_evidence: list[dict[str, Any]],
    counter_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "candidate": candidate.get("candidate_id"),
        "score_basis": {
            "rank": candidate.get("rank"),
            "score": candidate.get("score"),
            "evidence_support_level": candidate.get("evidence_support_level"),
            "answerability": candidate.get("answerability"),
            "best_evidence_lane": candidate.get("best_evidence_lane"),
            "best_source_family": candidate.get("best_source_family"),
        },
        "present_evidence_lanes": _present_evidence_lanes(candidate.get("evidence_lanes")),
        "supporting_evidence_count": len(supporting_evidence),
        "counter_evidence_count": len(counter_evidence),
        "supporting_record_ids": _record_ids(supporting_evidence),
        "counter_record_ids": _record_ids(counter_evidence),
    }


def _present_evidence_lanes(evidence_lanes: Any) -> list[dict[str, Any]]:
    if not isinstance(evidence_lanes, dict):
        return []
    present: list[dict[str, Any]] = []
    for name, lane_payload in evidence_lanes.items():
        if not isinstance(lane_payload, dict):
            continue
        if lane_payload.get("status") == "absent" and not _numeric_score(lane_payload.get("score")):
            continue
        present.append(
            {
                "lane": name,
                "status": lane_payload.get("status"),
                "score": lane_payload.get("score"),
                "source": lane_payload.get("source"),
                "source_id": lane_payload.get("source_id"),
                "note": lane_payload.get("note"),
            }
        )
    return present


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


def _candidate_by_id(candidate_matrix: list[dict[str, Any]], candidate_id: str) -> dict[str, Any] | None:
    return next((candidate for candidate in candidate_matrix if str(candidate.get("candidate_id")) == candidate_id), None)


def _numeric_score(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _merge_warnings(existing: Any, added: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for values in (existing, added):
        for item in values or []:
            text = str(item)
            if text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return merged


def _answerability_counts(candidate_matrix: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "direct_source_supported": 0,
        "adjacent_source_supported": 0,
        "plausibility_only": 0,
        "not_supported": 0,
    }
    for candidate in candidate_matrix:
        answerability = str(candidate.get("answerability") or "not_supported")
        counts[answerability] = counts.get(answerability, 0) + 1
    return counts
