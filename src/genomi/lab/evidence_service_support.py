"""Evidence request parsing, provider configuration, and result identity."""

from __future__ import annotations

import hashlib
from typing import Mapping

from .evidence_application_contract import DirectEvidenceRoute, EvidenceApplication
from .evidence_types import EvidenceResult, EvidenceStatus
from .models import JsonObject, compact_json
from .paperclip_adapter import (
    PAPERCLIP_JOB_RESUME_OPERATION,
    PaperclipAdapter,
    PaperclipOperation,
)
from .provider_policy import (
    AccessMode,
    EvidenceRequest,
    PAPERCLIP_PROVIDER,
    SourceFamily,
    required_text,
)
from .service_errors import LabError


PAPERCLIP_DESTINATION = "gxl_paperclip_hosted_service"
_CREDENTIAL_FIELDS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
)
_REQUEST_FIELDS = frozenset(
    {
        "filters",
        "operation",
        "purpose",
        "query",
        "query_terms",
        "source_family",
    }
)


class EvidenceApplicationSupportMixin:
    """Shared parsing and provider-policy mechanics for evidence operations."""

    @staticmethod
    def _persisted_provider_result(execution: JsonObject) -> JsonObject:
        result = execution.get("result")
        if not isinstance(result, dict):
            return {}
        capability_result = result.get("capability_result")
        if isinstance(capability_result, dict):
            result = capability_result
        provider_result = result.get("provider_result")
        return provider_result if isinstance(provider_result, dict) else {}

    @staticmethod
    def _validate_background_job_owner(
        result: EvidenceResult,
        direct: DirectEvidenceRoute | None,
        *,
        paperclip_job_available: bool = False,
        expected_job_id: str | None = None,
        expected_resume_operation: str | None = None,
    ) -> None:
        if result.status is not EvidenceStatus.IN_PROGRESS:
            return
        if expected_job_id is not None and result.job_id != expected_job_id:
            raise LabError(
                "capability_job_binding_mismatch",
                "The evidence provider returned a different job.",
                http_status=409,
            )
        if (
            expected_resume_operation is not None
            and result.resume_operation != expected_resume_operation
        ):
            raise LabError(
                "capability_job_binding_mismatch",
                "The evidence provider changed the resume operation.",
                http_status=409,
            )
        expected_operation = (
            PAPERCLIP_JOB_RESUME_OPERATION
            if result.provider == PAPERCLIP_PROVIDER
            and result.access_mode is AccessMode.LIVE_PROVIDER
            and paperclip_job_available
            else direct.background_job_resume_operation
            if direct is not None
            and result.provider == direct.provider
            and result.access_mode is AccessMode.DIRECT_PRIMARY_SOURCE
            else None
        )
        if result.resume_operation != expected_operation:
            raise LabError(
                "capability_job_resume_unsupported",
                "The evidence provider did not declare an allowlisted job owner.",
                http_status=409,
            )

    def _evidence_configuration(
        self: EvidenceApplication,
    ) -> tuple[
        PaperclipAdapter,
        dict[SourceFamily, DirectEvidenceRoute],
        dict[SourceFamily, Mapping[str, object]],
    ]:
        adapter = getattr(self, "_evidence_paperclip", None)
        if not isinstance(adapter, PaperclipAdapter):
            adapter = PaperclipAdapter()
            setattr(self, "_evidence_paperclip", adapter)
        direct = getattr(self, "_evidence_direct_sources", None)
        if not isinstance(direct, dict):
            direct = {}
            setattr(self, "_evidence_direct_sources", direct)
        fixtures = getattr(self, "_evidence_fixtures", None)
        if not isinstance(fixtures, dict):
            fixtures = {}
            setattr(self, "_evidence_fixtures", fixtures)
        return adapter, direct, fixtures

    @staticmethod
    def _parse_evidence_request(
        payload: JsonObject,
    ) -> tuple[EvidenceRequest, PaperclipOperation]:
        if not isinstance(payload, dict):
            raise LabError(
                "invalid_evidence_request", "Evidence request must be an object."
            )
        EvidenceApplicationSupportMixin._reject_credentials(payload)
        allowed = _REQUEST_FIELDS | {
            "approved",
            "recipient_provider",
            "paperclip_disclosure_receipt_id",
            "direct_disclosure_receipt_id",
            "payload_sha256",
            "approval_sha256",
        }
        unknown = sorted(str(key) for key in payload if key not in allowed)
        if unknown:
            raise LabError(
                "invalid_evidence_request",
                f"Unsupported evidence request field: {unknown[0]}",
            )
        try:
            raw_terms = payload.get("query_terms") or ()
            if not isinstance(raw_terms, (list, tuple)):
                raise ValueError("query_terms must be an array")
            operation = PaperclipOperation(payload.get("operation"))
            request = EvidenceRequest(
                query=payload.get("query"),
                query_terms=tuple(raw_terms),
                filters=payload.get("filters") or (),
                source_family=SourceFamily(payload.get("source_family")),
                purpose=payload.get("purpose"),
                operation=operation.value,
                # This capability is investigation-scoped. Even a query made
                # only of public biomedical terms was selected in a private
                # patient investigation, so callers cannot downgrade its
                # lineage to bypass the egress gate.
                patient_influenced=True,
            )
        except (TypeError, ValueError) as exc:
            raise LabError("invalid_evidence_request", str(exc)) from exc
        return request, operation

    @staticmethod
    def _provider_payload(
        request: EvidenceRequest, operation: PaperclipOperation
    ) -> JsonObject:
        normalized_operation = PaperclipOperation(operation).value
        if normalized_operation != request.operation:
            raise ValueError("operation does not match the evidence request")
        request_payload = request.to_dict()
        request_payload.pop("operation")
        return {
            "operation": normalized_operation,
            "request": request_payload,
        }

    @staticmethod
    def _optional_receipt_id(value: object, field: str) -> str | None:
        if value in (None, ""):
            return None
        try:
            return required_text(value, field, 200)
        except ValueError as exc:
            raise LabError("invalid_evidence_request", str(exc)) from exc

    def _require_evidence_receipt(
        self: EvidenceApplication,
        *,
        investigation: JsonObject,
        investigation_id: str,
        provider: str,
        purpose: str,
        destination: str,
        data_categories: list[str],
        policy_versions: JsonObject,
        payload: JsonObject,
        receipt_id: str,
    ) -> JsonObject:
        try:
            receipt = self.store.require_outbound_disclosure(
                receipt_id,
                workspace_session_id=self.session_id,
                user_id=str(investigation["user_id"]),
                investigation_id=investigation_id,
                recipient_kind="evidence_provider",
                recipient_id=provider,
                purpose=purpose,
                destination=destination,
                data_categories=data_categories,
                payload=payload,
                policy_versions=policy_versions,
            )
            return receipt
        except ValueError as exc:
            raise LabError(
                "evidence_disclosure_renewal_required",
                "Approve this exact evidence-provider query for the current session.",
                http_status=409,
            ) from exc

    @staticmethod
    def _ledger_evidence(
        result: EvidenceResult, operation: PaperclipOperation
    ) -> JsonObject:
        normalized = result.to_dict()
        normalized["gateway"] = {
            "owner": "GenomiLab",
            "provider_neutral": True,
            "provider_credentials_exposed": False,
        }
        return normalized

    @staticmethod
    def _provider_deduplication_key(
        result: EvidenceResult, operation: PaperclipOperation
    ) -> str:
        """Identify a normalized provider result without volatile retrieval time."""

        record_identities = []
        for record in result.records:
            provenance = record.provenance
            record_identities.append(
                {
                    "source_id": record.source_id,
                    "source_version": provenance.original_source_version,
                    "provider_result_id": provenance.provider_result_id,
                    "provider_version": provenance.provider_version,
                    "provider_commit": provenance.provider_commit,
                }
            )
        material = {
            "operation": operation.value,
            "request": result.request.to_dict(),
            "provider": result.provider,
            "access_mode": result.access_mode.value,
            "status": result.status.value,
            "job_id": result.job_id,
            "resume_operation": result.resume_operation,
            "records": record_identities,
        }
        return (
            "provider:"
            + hashlib.sha256(compact_json(material).encode("utf-8")).hexdigest()
        )

    @staticmethod
    def _reject_credentials(payload: object) -> None:
        def walk(value: object) -> None:
            if isinstance(value, dict):
                for raw_key, item in value.items():
                    key = str(raw_key).strip().lower().replace("-", "_")
                    if key in _CREDENTIAL_FIELDS or key.endswith(
                        (
                            "_api_key",
                            "_api_token",
                            "_access_token",
                            "_token_id",
                            "_token_secret",
                            "_password",
                            "_secret",
                        )
                    ):
                        raise LabError(
                            "provider_credentials_not_accepted",
                            "Provider credentials are configured only in the GenomiLab host.",
                        )
                    walk(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        walk(payload)
