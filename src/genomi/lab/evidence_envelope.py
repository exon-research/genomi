"""Canonical evidence-envelope projection for provider results."""

from __future__ import annotations

from ..evidence import envelope as evidence_envelope
from .evidence_types import (
    OPERATIONAL_FAILURE_STATUSES,
    EvidenceResult,
    EvidenceStatus,
)


def provider_evidence_envelope(
    result: EvidenceResult, records: list[dict[str, object]]
) -> dict[str, object]:
    operation = f"evidence_provider.{result.source_family.value}"
    query_scope = {
        "provider": result.provider,
        "access_mode": result.access_mode.value,
        "source_family": result.source_family.value,
        "query_terms": list(result.request.query_terms),
        "filters": dict(result.request.filters),
    }
    attempts = result.route_attempts or (result.attempt(),)
    consulted = list(
        dict.fromkeys(
            source for attempt in attempts for source in attempt.coverage.consulted
        )
    )
    unavailable = list(
        dict.fromkeys(
            attempt.provider
            for attempt in attempts
            if attempt.status
            in OPERATIONAL_FAILURE_STATUSES | {EvidenceStatus.BLOCKED_BY_POLICY}
        )
    )
    failures = [
        attempt.failure.to_dict()
        for attempt in attempts
        if attempt.failure is not None
    ]
    failures.extend(
        failure.to_dict()
        for attempt in attempts
        for failure in attempt.coverage.partial_failures
    )
    coverage = {
        "libraries": [],
        "consulted_sources": consulted,
        "unavailable_sources": unavailable,
        "materialization": [],
        "query_terms": list(result.coverage.query_terms),
        "filters": dict(result.coverage.filters),
        "consulted_coverage": consulted,
        "misses": list(result.coverage.misses),
        "failures": failures,
    }
    observations = {
        "observation_count": len(records),
        "source_document_states": sorted(
            {str(record["source_document_state"]) for record in records}
        ),
        "independent_clinical_claim_ready": False,
    }
    personal_context = {
        "uses_personal_dna": False,
        "patient_influenced_query": result.request.patient_influenced,
    }
    if result.status is EvidenceStatus.DATA_RETURNED:
        return evidence_envelope.evidence_present(
            operation=operation,
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=coverage,
            observations=observations,
            answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
            guidance=[
                "evidence_present:require_primary_source_and_clinical_confirmation"
            ],
        )
    if result.status is EvidenceStatus.IN_SCOPE_EMPTY:
        return evidence_envelope.empty_consulted_scope(
            operation=operation,
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=coverage,
            observations=observations,
            guidance=[
                "not_observed_in_consulted_scope:do_not_imply_wider_evidence_absence"
            ],
        )
    return evidence_envelope.not_assessed(
        operation=operation,
        reason=result.status.value,
        query_scope=query_scope,
        personal_context=personal_context,
        coverage=coverage,
        observations=observations,
        guidance=["not_assessed:do_not_use_for_clinical_claim"],
    )
