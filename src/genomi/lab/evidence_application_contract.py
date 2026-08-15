"""Canonical application and repository contracts for evidence workflows."""

from __future__ import annotations

from typing import Mapping, Protocol

from .evidence_types import EvidenceResult
from .models import JsonObject
from .paperclip_adapter import (
    DirectSourceJobTransport,
    DirectSourceTransport,
    PaperclipAdapter,
    PaperclipOperation,
)
from .provider_policy import EvidenceRequest, SourceFamily


class EvidenceStore(Protocol):
    """Persistence operations used by the provider-neutral evidence boundary."""

    def create_outbound_disclosure_receipt(
        self, user_id: str, **kwargs: object
    ) -> JsonObject: ...

    def active_outbound_disclosure_receipt_ids(
        self, **kwargs: object
    ) -> list[str]: ...

    def require_outbound_disclosure(
        self, disclosure_receipt_id: str, **kwargs: object
    ) -> JsonObject: ...

    def consent_receipt(self, consent_receipt_id: str) -> JsonObject: ...

    def commit_evidence(
        self,
        investigation_id: str,
        *,
        source_family: object,
        operation: object,
        evidence: JsonObject,
        deduplication_key: object,
        expected_plan_version_id: object = None,
        expected_disclosure_receipt_id: object = None,
        expected_consent_receipt_id: object = None,
    ) -> JsonObject: ...


class DirectEvidenceRoute(Protocol):
    """Configured direct-primary-source route used by evidence workflows."""

    source_family: SourceFamily
    provider: str
    destination: str
    transport: DirectSourceTransport
    background_job_transport: DirectSourceJobTransport | None
    background_job_resume_operation: str | None

    def manifest(self) -> JsonObject: ...

    def resume_job(
        self,
        *,
        operation: PaperclipOperation,
        request: EvidenceRequest,
        job_id: str,
        resume_operation: str,
        approved: bool,
    ) -> EvidenceResult: ...


class EvidenceApplication(Protocol):
    """One GenomiLab service authorized to run evidence workflows."""

    store: EvidenceStore
    session_id: str

    def investigation(self, investigation_id: str) -> JsonObject: ...

    def evidence_disclosure_candidate(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject: ...

    def _evidence_configuration(
        self,
    ) -> tuple[
        PaperclipAdapter,
        dict[SourceFamily, DirectEvidenceRoute],
        dict[SourceFamily, Mapping[str, object]],
    ]: ...

    def _parse_evidence_request(
        self, payload: JsonObject
    ) -> tuple[EvidenceRequest, PaperclipOperation]: ...

    def _provider_payload(
        self, request: EvidenceRequest, operation: PaperclipOperation
    ) -> JsonObject: ...

    def _optional_receipt_id(self, value: object, field: str) -> str | None: ...

    def _require_evidence_receipt(self, **kwargs: object) -> JsonObject: ...

    def _persisted_provider_result(self, execution: JsonObject) -> JsonObject: ...

    def _validate_background_job_owner(
        self,
        result: EvidenceResult,
        direct: DirectEvidenceRoute | None,
        *,
        paperclip_job_available: bool = False,
        expected_job_id: str | None = None,
        expected_resume_operation: str | None = None,
    ) -> None: ...

    def _ledger_evidence(
        self, result: EvidenceResult, operation: PaperclipOperation
    ) -> JsonObject: ...

    def _provider_deduplication_key(
        self, result: EvidenceResult, operation: PaperclipOperation
    ) -> str: ...

    def _commit_or_report_evidence_result(
        self,
        investigation_id: str,
        *,
        result: EvidenceResult,
        operation: PaperclipOperation,
        expected_plan_version_id: str | None = None,
        expected_disclosure_receipt_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> JsonObject: ...


__all__ = ["DirectEvidenceRoute", "EvidenceApplication", "EvidenceStore"]
