"""Allowlisted normalization of provider and primary-source evidence."""

from __future__ import annotations

from typing import Mapping
from urllib.parse import urlparse

from .evidence_types import (
    OPERATIONAL_FAILURE_STATUSES,
    EvidenceCoverage,
    EvidenceProvenance,
    EvidenceRecord,
    EvidenceResult,
    EvidenceStatus,
    ProviderFailure,
    SourceCurrency,
    SourceDocumentState,
    SourceLicense,
    SourceReviewState,
    UntrustedEvidenceText,
)
from .provider_policy import (
    AccessMode,
    EvidenceRequest,
    ProviderPolicyDecision,
    ProviderPolicyState,
    SourceFamily,
    provider_name,
    required_text,
)


def optional_text(value: object, field: str, maximum: int = 4_000) -> str | None:
    if value in (None, ""):
        return None
    return required_text(value, field, maximum)


def _safe_uri(value: object, field: str) -> str | None:
    uri = optional_text(value, field, 4_000)
    if uri is None:
        return None
    parsed = urlparse(uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute HTTP(S) URI")
    return uri


def _string_tuple(value: object, field: str, maximum: int = 1_000) -> tuple[str, ...]:
    if value in (None, (), []):
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    return tuple(
        dict.fromkeys(required_text(item, field, maximum) for item in value)
    )


def _boolean_or_none(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _retryable(status: EvidenceStatus) -> bool:
    return status in {
        EvidenceStatus.QUOTA_EXCEEDED,
        EvidenceStatus.RATE_LIMITED,
        EvidenceStatus.TIMEOUT,
        EvidenceStatus.NETWORK_ERROR,
        EvidenceStatus.SERVER_ERROR,
        EvidenceStatus.SOURCE_UNAVAILABLE,
    }


def _retry_after(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("retry_after_seconds must be a non-negative integer")
    return value


def provider_failure(
    status: EvidenceStatus, retry_after_seconds: object = None
) -> ProviderFailure | None:
    if status not in OPERATIONAL_FAILURE_STATUSES:
        return None
    return ProviderFailure(
        status=status,
        retryable=_retryable(status),
        retry_after_seconds=_retry_after(retry_after_seconds),
    )


def failure_result(
    *,
    provider: str,
    access_mode: AccessMode,
    request: EvidenceRequest,
    status: EvidenceStatus,
    policy: ProviderPolicyDecision | None = None,
    retry_after_seconds: int | None = None,
) -> EvidenceResult:
    if status not in OPERATIONAL_FAILURE_STATUSES:
        raise ValueError("failure_result requires an operational failure status")
    return EvidenceResult(
        provider=provider_name(provider),
        access_mode=AccessMode(access_mode),
        request=request,
        status=status,
        records=(),
        policy=policy or ProviderPolicyDecision(ProviderPolicyState.ALLOWED),
        coverage=EvidenceCoverage(
            query_terms=request.query_terms,
            filters=request.filters,
            consulted=(),
            misses=(),
        ),
        failure=provider_failure(status, retry_after_seconds),
    )


def blocked_result(
    *,
    provider: str,
    access_mode: AccessMode,
    request: EvidenceRequest,
    policy: ProviderPolicyDecision,
) -> EvidenceResult:
    return EvidenceResult(
        provider=provider_name(provider),
        access_mode=AccessMode(access_mode),
        request=request,
        status=EvidenceStatus.BLOCKED_BY_POLICY,
        records=(),
        policy=policy,
        coverage=EvidenceCoverage(
            query_terms=request.query_terms,
            filters=request.filters,
            consulted=(),
            misses=(),
        ),
    )


def _source_license(item: Mapping[str, object]) -> SourceLicense:
    raw = item.get("source_license") or {}
    if not isinstance(raw, Mapping):
        raise ValueError("source_license must be an object")
    status = (
        optional_text(raw.get("status"), "source_license.status", 100)
        or "not_provided"
    )
    return SourceLicense(
        status=status,
        identifier=optional_text(
            raw.get("identifier"), "source_license.identifier", 500
        ),
        uri=_safe_uri(raw.get("uri"), "source_license.uri"),
        short_excerpt_storage_permitted=_boolean_or_none(
            raw.get("short_excerpt_storage_permitted"),
            "source_license.short_excerpt_storage_permitted",
        ),
        full_text_storage_permitted=_boolean_or_none(
            raw.get("full_text_storage_permitted"),
            "source_license.full_text_storage_permitted",
        ),
        figure_storage_permitted=_boolean_or_none(
            raw.get("figure_storage_permitted"),
            "source_license.figure_storage_permitted",
        ),
    )


def _source_currency(item: Mapping[str, object]) -> SourceCurrency:
    raw = item.get("source_currency") or {}
    if not isinstance(raw, Mapping):
        raise ValueError("source_currency must be an object")
    return SourceCurrency(
        current_source_checked_at=optional_text(
            raw.get("current_source_checked_at"),
            "source_currency.current_source_checked_at",
            100,
        ),
        correction_status=SourceReviewState(
            raw.get("correction_status", SourceReviewState.NOT_CHECKED.value)
        ),
        retraction_status=SourceReviewState(
            raw.get("retraction_status", SourceReviewState.NOT_CHECKED.value)
        ),
        correction_ids=_string_tuple(raw.get("correction_ids"), "correction_id"),
        retraction_ids=_string_tuple(raw.get("retraction_ids"), "retraction_id"),
        superseded_by=_string_tuple(raw.get("superseded_by"), "superseded_by"),
        linked_publication_ids=_string_tuple(
            raw.get("linked_publication_ids"), "linked_publication_id"
        ),
        conflict_ids=_string_tuple(raw.get("conflict_ids"), "conflict_id"),
    )


def _identifiers(
    item: Mapping[str, object], source_id: str
) -> tuple[tuple[str, str], ...]:
    raw = item.get("identifiers") or {}
    if not isinstance(raw, Mapping):
        raise ValueError("identifiers must be an object")
    identifiers = {
        required_text(key, "identifier name", 100).lower(): required_text(
            value, f"identifiers.{key}", 1_000
        )
        for key, value in raw.items()
    }
    for key in ("doi", "pmid", "pmcid", "registry_id", "database_id", "accession"):
        value = optional_text(item.get(key), key, 1_000)
        if value is not None:
            identifiers[key] = value
    identifiers.setdefault("source_id", source_id)
    return tuple(sorted(identifiers.items()))


def _partial_failures(value: object) -> tuple[ProviderFailure, ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        raise ValueError("coverage.partial_failures must be an array")
    failures: list[ProviderFailure] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise ValueError(f"coverage.partial_failures[{index}] must be an object")
        status = EvidenceStatus(raw.get("status"))
        failure = provider_failure(status, raw.get("retry_after_seconds"))
        if failure is None:
            raise ValueError("partial failures require an operational failure status")
        failures.append(failure)
    return tuple(failures)


def normalize_evidence_response(
    *,
    provider: str,
    access_mode: AccessMode,
    request: EvidenceRequest,
    raw: Mapping[str, object],
    policy: ProviderPolicyDecision | None = None,
) -> EvidenceResult:
    """Normalize the allowlisted result shape and discard executable extras."""

    if not isinstance(raw, Mapping):
        raise ValueError("provider response must be an object")
    normalized_provider = provider_name(provider)
    response_family = SourceFamily(raw.get("source_family", request.source_family.value))
    if response_family is not request.source_family:
        raise ValueError("provider response source_family does not match the request")
    status = EvidenceStatus(raw.get("status", EvidenceStatus.DATA_RETURNED.value))
    if status is EvidenceStatus.BLOCKED_BY_POLICY:
        raise ValueError("providers cannot assert GenomiLab policy state")
    raw_records = raw.get("records", [])
    if not isinstance(raw_records, list):
        raise ValueError("provider response records must be a list")
    if status is EvidenceStatus.DATA_RETURNED and not raw_records:
        raise ValueError("data_returned requires at least one record")
    if status is not EvidenceStatus.DATA_RETURNED and raw_records:
        raise ValueError(f"{status.value} cannot include records")
    job_id = optional_text(raw.get("job_id"), "job_id", 500)
    resume_operation = optional_text(
        raw.get("resume_operation"), "resume_operation", 200
    )
    poll_after_seconds = _retry_after(raw.get("poll_after_seconds"))
    if status is EvidenceStatus.IN_PROGRESS:
        if job_id is None or resume_operation is None:
            raise ValueError("in_progress requires job_id and resume_operation")
    elif any(
        value is not None
        for value in (job_id, resume_operation, poll_after_seconds)
    ):
        raise ValueError("background-job fields require in_progress status")

    raw_coverage = raw.get("coverage") or {}
    if not isinstance(raw_coverage, Mapping):
        raise ValueError("coverage must be an object")
    consulted = _string_tuple(raw_coverage.get("consulted"), "coverage.consulted")
    if not consulted and status in {
        EvidenceStatus.DATA_RETURNED,
        EvidenceStatus.IN_SCOPE_EMPTY,
    }:
        consulted = (f"{normalized_provider}:{request.source_family.value}",)
    misses = _string_tuple(raw_coverage.get("misses"), "coverage.misses")
    if not misses and status is EvidenceStatus.IN_SCOPE_EMPTY:
        misses = request.query_terms
    coverage = EvidenceCoverage(
        query_terms=request.query_terms,
        filters=request.filters,
        consulted=consulted,
        misses=misses,
        partial_failures=_partial_failures(raw_coverage.get("partial_failures")),
    )
    provider_result_id = optional_text(
        raw.get("provider_result_id"), "provider_result_id", 500
    )
    provider_version = optional_text(
        raw.get("provider_version"), "provider_version", 500
    )
    provider_repository = optional_text(
        raw.get("provider_repository"), "provider_repository", 1_000
    )
    provider_commit = optional_text(
        raw.get("provider_commit"), "provider_commit", 500
    )
    provider_model = optional_text(raw.get("provider_model"), "provider_model", 500)
    records: list[EvidenceRecord] = []
    for index, item in enumerate(raw_records):
        if not isinstance(item, Mapping):
            raise ValueError(f"records[{index}] must be an object")
        source_id = required_text(
            item.get("source_id"), f"records[{index}].source_id", 1_000
        )
        title = required_text(item.get("title"), f"records[{index}].title", 4_000)
        excerpt = optional_text(
            item.get("excerpt"), f"records[{index}].excerpt", 20_000
        )
        default_document_state = {
            SourceFamily.LITERATURE: SourceDocumentState.ABSTRACT_ONLY,
            SourceFamily.TRIAL_REGISTRY: SourceDocumentState.TRIAL_REGISTRATION,
            SourceFamily.REGULATORY: SourceDocumentState.REGULATORY_DOCUMENT,
            SourceFamily.UNIPROT: SourceDocumentState.STRUCTURED_DATABASE,
            SourceFamily.PDB: SourceDocumentState.STRUCTURED_DATABASE,
            SourceFamily.CHEMBL: SourceDocumentState.STRUCTURED_DATABASE,
        }[request.source_family]
        document_state = SourceDocumentState(
            item.get("source_document_state", default_document_state.value)
        )
        if (
            request.source_family is SourceFamily.TRIAL_REGISTRY
            and document_state is not SourceDocumentState.TRIAL_REGISTRATION
        ):
            raise ValueError("trial-registry records must remain trial registrations")
        source_license = _source_license(item)
        excerpt_permitted = source_license.short_excerpt_storage_permitted is True
        spans = (
            tuple(
                UntrustedEvidenceText(text)
                for text in _string_tuple(
                    item.get("supporting_spans"), "supporting_span", 10_000
                )
            )
            if excerpt_permitted
            else ()
        )
        provenance = EvidenceProvenance(
            provider=normalized_provider,
            access_mode=AccessMode(access_mode),
            provider_result_id=provider_result_id,
            provider_version=provider_version,
            provider_repository=optional_text(
                item.get("provider_repository"), "provider_repository", 1_000
            )
            or provider_repository,
            provider_commit=optional_text(
                item.get("provider_commit"), "provider_commit", 500
            )
            or provider_commit,
            provider_model=optional_text(
                item.get("provider_model"), "provider_model", 500
            )
            or provider_model,
            original_source_id=source_id,
            original_source_uri=_safe_uri(item.get("source_uri"), "source_uri"),
            original_source_version=optional_text(
                item.get("source_version"), "source_version", 500
            ),
            publication_date=optional_text(
                item.get("publication_date"), "publication_date", 100
            ),
            indexed_at=optional_text(item.get("indexed_at"), "indexed_at", 100),
            retrieved_at=optional_text(
                item.get("retrieved_at"), "retrieved_at", 100
            ),
            source_license=source_license,
            source_currency=_source_currency(item),
        )
        records.append(
            EvidenceRecord(
                source_family=request.source_family,
                source_id=source_id,
                identifiers=_identifiers(item, source_id),
                title=UntrustedEvidenceText(title),
                excerpt=(
                    UntrustedEvidenceText(excerpt)
                    if excerpt is not None and excerpt_permitted
                    else None
                ),
                supporting_spans=spans,
                figure_references=_string_tuple(
                    item.get("figure_references"), "figure_reference"
                ),
                provenance=provenance,
                source_document_state=document_state,
            )
        )
    return EvidenceResult(
        provider=normalized_provider,
        access_mode=AccessMode(access_mode),
        request=request,
        status=status,
        records=tuple(records),
        policy=policy or ProviderPolicyDecision(ProviderPolicyState.ALLOWED),
        coverage=coverage,
        failure=provider_failure(status, raw.get("retry_after_seconds")),
        job_id=job_id,
        resume_operation=resume_operation,
        poll_after_seconds=poll_after_seconds,
    )


def normalize_fixture_response(
    request: EvidenceRequest, raw: Mapping[str, object]
) -> EvidenceResult:
    return normalize_evidence_response(
        provider="fixture",
        access_mode=AccessMode.FIXTURE,
        request=request,
        raw=raw,
    )


def normalize_direct_source_response(
    provider: str, request: EvidenceRequest, raw: Mapping[str, object]
) -> EvidenceResult:
    return normalize_evidence_response(
        provider=provider,
        access_mode=AccessMode.DIRECT_PRIMARY_SOURCE,
        request=request,
        raw=raw,
    )
