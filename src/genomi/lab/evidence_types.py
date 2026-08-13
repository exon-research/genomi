"""Typed provider evidence, provenance, coverage, and failure contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .provider_policy import (
    AccessMode,
    EvidenceRequest,
    ProviderPolicyDecision,
    ProviderPolicyState,
    SourceFamily,
)


class EvidenceStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    DATA_RETURNED = "data_returned"
    IN_SCOPE_EMPTY = "in_scope_empty"
    OUT_OF_SCOPE_FOR_INPUT = "out_of_scope_for_input"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    AUTHENTICATION_FAILED = "authentication_failed"
    QUOTA_EXCEEDED = "quota_exceeded"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    SERVER_ERROR = "server_error"
    SOURCE_UNAVAILABLE = "source_unavailable"
    NOT_FOUND = "not_found"


OPERATIONAL_FAILURE_STATUSES = frozenset(
    {
        EvidenceStatus.AUTHENTICATION_FAILED,
        EvidenceStatus.QUOTA_EXCEEDED,
        EvidenceStatus.RATE_LIMITED,
        EvidenceStatus.TIMEOUT,
        EvidenceStatus.NETWORK_ERROR,
        EvidenceStatus.SERVER_ERROR,
        EvidenceStatus.SOURCE_UNAVAILABLE,
        EvidenceStatus.NOT_FOUND,
    }
)
FALLBACK_ELIGIBLE_STATUSES = frozenset(
    {
        EvidenceStatus.BLOCKED_BY_POLICY,
        EvidenceStatus.IN_SCOPE_EMPTY,
        EvidenceStatus.OUT_OF_SCOPE_FOR_INPUT,
        *OPERATIONAL_FAILURE_STATUSES,
    }
)


class SourceDocumentState(str, Enum):
    FULL_TEXT_PEER_REVIEWED = "full_text_peer_reviewed"
    PEER_REVIEWED_PUBLICATION = "peer_reviewed_publication"
    ABSTRACT_ONLY = "abstract_only"
    PREPRINT = "preprint"
    TRIAL_REGISTRATION = "trial_registration"
    REGULATORY_DOCUMENT = "regulatory_document"
    STRUCTURED_DATABASE = "structured_database"
    OTHER = "other"


class SourceReviewState(str, Enum):
    NOT_CHECKED = "not_checked"
    NONE_REPORTED_IN_CURRENT_SOURCE = "none_reported_in_current_source"
    PRESENT = "present"


@dataclass(frozen=True)
class UntrustedEvidenceText:
    text: str
    trust: str = "untrusted_external_evidence"
    instructions_actionable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "trust": self.trust,
            "instructions_actionable": self.instructions_actionable,
        }


@dataclass(frozen=True)
class SourceLicense:
    status: str = "not_provided"
    identifier: str | None = None
    uri: str | None = None
    short_excerpt_storage_permitted: bool | None = None
    full_text_storage_permitted: bool | None = None
    figure_storage_permitted: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            key: value
            for key, value in {
                "status": self.status,
                "identifier": self.identifier,
                "uri": self.uri,
                "short_excerpt_storage_permitted": self.short_excerpt_storage_permitted,
                "full_text_storage_permitted": self.full_text_storage_permitted,
                "figure_storage_permitted": self.figure_storage_permitted,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class SourceCurrency:
    current_source_checked_at: str | None = None
    correction_status: SourceReviewState = SourceReviewState.NOT_CHECKED
    retraction_status: SourceReviewState = SourceReviewState.NOT_CHECKED
    correction_ids: tuple[str, ...] = ()
    retraction_ids: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()
    linked_publication_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "current_source_checked_at": self.current_source_checked_at,
            "correction_status": self.correction_status.value,
            "retraction_status": self.retraction_status.value,
            "correction_ids": list(self.correction_ids),
            "retraction_ids": list(self.retraction_ids),
            "superseded_by": list(self.superseded_by),
            "linked_publication_ids": list(self.linked_publication_ids),
            "conflict_ids": list(self.conflict_ids),
        }


@dataclass(frozen=True)
class EvidenceProvenance:
    provider: str
    access_mode: AccessMode
    provider_result_id: str | None
    provider_version: str | None
    provider_repository: str | None
    provider_commit: str | None
    provider_model: str | None
    original_source_id: str
    original_source_uri: str | None
    original_source_version: str | None
    publication_date: str | None
    indexed_at: str | None
    retrieved_at: str | None
    source_license: SourceLicense
    source_currency: SourceCurrency

    def to_dict(self) -> dict[str, object]:
        result = {
            key: value
            for key, value in {
                "provider": self.provider,
                "access_mode": self.access_mode.value,
                "provider_result_id": self.provider_result_id,
                "provider_version": self.provider_version,
                "provider_repository": self.provider_repository,
                "provider_commit": self.provider_commit,
                "provider_model": self.provider_model,
                "original_source_id": self.original_source_id,
                "original_source_uri": self.original_source_uri,
                "original_source_version": self.original_source_version,
                "publication_date": self.publication_date,
                "indexed_at": self.indexed_at,
                "retrieved_at": self.retrieved_at,
            }.items()
            if value is not None
        }
        result["source_license"] = self.source_license.to_dict()
        result["source_currency"] = self.source_currency.to_dict()
        return result


@dataclass(frozen=True)
class EvidenceRecord:
    source_family: SourceFamily
    source_id: str
    identifiers: tuple[tuple[str, str], ...]
    title: UntrustedEvidenceText
    excerpt: UntrustedEvidenceText | None
    supporting_spans: tuple[UntrustedEvidenceText, ...]
    figure_references: tuple[str, ...]
    provenance: EvidenceProvenance
    source_document_state: SourceDocumentState

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "source_family": self.source_family.value,
            "source_id": self.source_id,
            "identifiers": dict(self.identifiers),
            "title": self.title.to_dict(),
            "supporting_spans": [item.to_dict() for item in self.supporting_spans],
            "figure_references": list(self.figure_references),
            "provenance": self.provenance.to_dict(),
            "source_document_state": self.source_document_state.value,
            "independent_clinical_claim_ready": False,
            "content_retention": {
                "short_excerpt_retained": bool(
                    self.excerpt is not None or self.supporting_spans
                ),
                "full_text_retained": False,
                "figures_retained": False,
            },
        }
        if self.excerpt is not None:
            result["excerpt"] = self.excerpt.to_dict()
        return result


@dataclass(frozen=True)
class ProviderFailure:
    status: EvidenceStatus
    retryable: bool
    retry_after_seconds: int | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "status": self.status.value,
            "retryable": self.retryable,
        }
        if self.retry_after_seconds is not None:
            result["retry_after_seconds"] = self.retry_after_seconds
        return result


@dataclass(frozen=True)
class EvidenceCoverage:
    query_terms: tuple[str, ...]
    filters: tuple[tuple[str, str], ...]
    consulted: tuple[str, ...]
    misses: tuple[str, ...]
    partial_failures: tuple[ProviderFailure, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "query_terms": list(self.query_terms),
            "filters": dict(self.filters),
            "consulted": list(self.consulted),
            "misses": list(self.misses),
            "partial_failures": [item.to_dict() for item in self.partial_failures],
        }


@dataclass(frozen=True)
class EvidenceRouteAttempt:
    provider: str
    access_mode: AccessMode
    status: EvidenceStatus
    policy_state: ProviderPolicyState
    coverage: EvidenceCoverage
    failure: ProviderFailure | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "provider": self.provider,
            "access_mode": self.access_mode.value,
            "status": self.status.value,
            "policy_state": self.policy_state.value,
            "coverage": self.coverage.to_dict(),
        }
        if self.failure is not None:
            result["failure"] = self.failure.to_dict()
        return result


@dataclass(frozen=True)
class EvidenceResult:
    provider: str
    access_mode: AccessMode
    request: EvidenceRequest
    status: EvidenceStatus
    records: tuple[EvidenceRecord, ...]
    policy: ProviderPolicyDecision
    coverage: EvidenceCoverage
    failure: ProviderFailure | None = None
    route_attempts: tuple[EvidenceRouteAttempt, ...] = ()
    job_id: str | None = None
    resume_operation: str | None = None
    poll_after_seconds: int | None = None

    @property
    def source_family(self) -> SourceFamily:
        return self.request.source_family

    def attempt(self) -> EvidenceRouteAttempt:
        return EvidenceRouteAttempt(
            provider=self.provider,
            access_mode=self.access_mode,
            status=self.status,
            policy_state=self.policy.state,
            coverage=self.coverage,
            failure=self.failure,
        )

    def with_route_attempts(
        self, attempts: tuple[EvidenceRouteAttempt, ...]
    ) -> EvidenceResult:
        return replace(self, route_attempts=attempts)

    def to_dict(self) -> dict[str, object]:
        from .evidence_envelope import provider_evidence_envelope

        records = [record.to_dict() for record in self.records]
        result: dict[str, object] = {
            "provider": self.provider,
            "access_mode": self.access_mode.value,
            "source_family": self.source_family.value,
            "status": self.status.value,
            "request": self.request.to_dict(),
            "coverage": self.coverage.to_dict(),
            "records": records,
            "policy": self.policy.to_dict(),
            "route_attempts": [attempt.to_dict() for attempt in self.route_attempts],
            "evidence_envelope": provider_evidence_envelope(self, records),
        }
        if self.failure is not None:
            result["failure"] = self.failure.to_dict()
        if self.job_id is not None:
            result["job_id"] = self.job_id
        if self.resume_operation is not None:
            result["resume_operation"] = self.resume_operation
        if self.poll_after_seconds is not None:
            result["poll_after_seconds"] = self.poll_after_seconds
        return result


class ProviderTransportError(RuntimeError):
    """A transport failure reduced to an allowlisted, credential-free state."""

    def __init__(
        self,
        status: EvidenceStatus,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        if status not in OPERATIONAL_FAILURE_STATUSES:
            raise ValueError("transport errors require an operational failure status")
        super().__init__(status.value)
        self.status = status
        self.retry_after_seconds = retry_after_seconds
