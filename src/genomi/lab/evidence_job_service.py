"""Resumption and reauthorization of evidence-provider background jobs."""

from __future__ import annotations

from .approval_store import disclosure_payload_sha256
from .evidence_application_contract import EvidenceApplication
from .evidence_types import EvidenceStatus
from .models import JsonObject
from .paperclip_adapter import PAPERCLIP_JOB_RESUME_OPERATION, PaperclipOperation
from .provider_policy import (
    AccessMode,
    EvidenceRequest,
    PAPERCLIP_PROVIDER,
    SourceFamily,
    provider_name,
)
from .service_errors import LabError
from .evidence_service_support import PAPERCLIP_DESTINATION as _PAPERCLIP_DESTINATION


class EvidenceJobApplicationMixin:
    """Continue only the exact provider job captured by durable execution state."""

    def resume_public_evidence_job(
        self: EvidenceApplication,
        investigation_id: str,
        *,
        execution: JsonObject,
        job_id: str,
        resume_operation: str,
    ) -> JsonObject:
        """Poll the exact provider route captured by an in-progress execution."""

        expected_consent_receipt_id = str(execution.get("consent_receipt_id") or "")
        self._require_active_execution_consent(
            investigation_id,
            expected_consent_receipt_id=expected_consent_receipt_id,
        )
        provider_result = self._persisted_provider_result(execution)
        if (
            provider_result.get("status") != EvidenceStatus.IN_PROGRESS.value
            or provider_result.get("job_id") != job_id
            or provider_result.get("resume_operation") != resume_operation
        ):
            raise LabError(
                "capability_job_binding_mismatch",
                "The evidence job does not match its persisted provider result.",
                http_status=409,
            )
        raw_request = provider_result.get("request")
        gateway = provider_result.get("gateway")
        if not isinstance(raw_request, dict) or not isinstance(gateway, dict):
            return {
                "status": "invalid_background_result",
                "message": "The persisted evidence job has no usable request contract.",
                "retry_after_approval": False,
            }
        try:
            request = EvidenceRequest(
                query=raw_request.get("query"),
                query_terms=tuple(raw_request.get("query_terms") or ()),
                filters=raw_request.get("filters") or {},
                source_family=SourceFamily(raw_request.get("source_family")),
                purpose=raw_request.get("purpose"),
                patient_influenced=True,
            )
            operation = PaperclipOperation(gateway.get("operation"))
            access_mode = AccessMode(provider_result.get("access_mode"))
        except (TypeError, ValueError) as exc:
            return {
                "status": "invalid_background_result",
                "message": str(exc),
                "retry_after_approval": False,
            }
        provider = provider_name(provider_result.get("provider"))
        active_attempt = next(
            (
                attempt
                for attempt in execution.get("attempts") or []
                if isinstance(attempt, dict)
                and int(attempt.get("attempt_number") or 0)
                == int(execution.get("active_attempt_number") or 0)
            ),
            None,
        )
        approved = bool(
            isinstance(active_attempt, dict)
            and active_attempt.get("approval_provider") == provider
            and active_attempt.get("approval_payload_sha256")
        )
        try:
            approval_payload_sha256 = (
                str(active_attempt.get("approval_payload_sha256") or "")
                if isinstance(active_attempt, dict)
                else ""
            )
            receipt = self._require_active_job_disclosure(
                investigation_id=investigation_id,
                provider=provider,
                access_mode=access_mode,
                request=request,
                operation=operation,
                expected_payload_sha256=approval_payload_sha256,
            )
        except ValueError as exc:
            raise LabError(
                "evidence_disclosure_renewal_required",
                "The original evidence disclosure is no longer active for this session.",
                http_status=409,
            ) from exc
        approved = approved and bool(receipt)
        adapter, direct_sources, _fixtures = self._evidence_configuration()
        try:
            if (
                provider == PAPERCLIP_PROVIDER
                and access_mode is AccessMode.LIVE_PROVIDER
            ):
                if resume_operation != PAPERCLIP_JOB_RESUME_OPERATION:
                    raise ValueError(
                        "Paperclip job resume operation is not allowlisted"
                    )
                result = adapter.resume_live_job(
                    operation=operation,
                    request=request,
                    job_id=job_id,
                    resume_operation=resume_operation,
                    approved=approved,
                )
            elif access_mode is AccessMode.DIRECT_PRIMARY_SOURCE:
                direct = direct_sources.get(request.source_family)
                if direct is None or direct.provider != provider:
                    return {
                        "status": "source_unavailable",
                        "message": "The original direct evidence source is no longer configured.",
                        "retry_after_approval": False,
                    }
                result = direct.resume_job(
                    operation=operation,
                    request=request,
                    job_id=job_id,
                    resume_operation=resume_operation,
                    approved=approved,
                )
            else:
                raise ValueError(
                    "the persisted evidence route cannot own background work"
                )
        except ValueError as exc:
            return {
                "status": "source_unavailable",
                "message": str(exc),
                "retry_after_approval": False,
            }
        self._validate_background_job_owner(
            result,
            direct_sources.get(request.source_family),
            paperclip_job_available=(
                adapter.capability_manifest().background_job_check_available
            ),
            expected_job_id=job_id,
            expected_resume_operation=resume_operation,
        )
        expected_plan_version_id = str(execution.get("plan_version_id") or "")
        if result.status is not EvidenceStatus.IN_PROGRESS:
            current = self.investigation(investigation_id)
            current_plan = current.get("current_plan_version")
            if (
                not expected_plan_version_id
                or not isinstance(current_plan, dict)
                or current_plan.get("plan_version_id") != expected_plan_version_id
                or current_plan.get("review_status") != "accepted"
            ):
                raise LabError(
                    "capability_plan_superseded",
                    "The evidence result arrived after its accepted plan changed.",
                    http_status=409,
                )
            try:
                receipt = self._require_active_job_disclosure(
                    investigation_id=investigation_id,
                    provider=provider,
                    access_mode=access_mode,
                    request=request,
                    operation=operation,
                    expected_payload_sha256=approval_payload_sha256,
                )
            except ValueError as exc:
                raise LabError(
                    "evidence_disclosure_renewal_required",
                    "The evidence disclosure changed while the provider job was running.",
                    http_status=409,
                ) from exc
        return self._commit_or_report_evidence_result(
            investigation_id,
            result=result,
            operation=operation,
            expected_plan_version_id=expected_plan_version_id,
            expected_disclosure_receipt_id=str(
                receipt.get("disclosure_receipt_id") or ""
            ),
            expected_consent_receipt_id=expected_consent_receipt_id,
        )

    def _require_active_execution_consent(
        self: EvidenceApplication,
        investigation_id: str,
        *,
        expected_consent_receipt_id: str,
    ) -> JsonObject:
        investigation = self.investigation(investigation_id)
        if (
            not expected_consent_receipt_id
            or investigation.get("active_consent_receipt_id")
            != expected_consent_receipt_id
        ):
            raise LabError(
                "private_context_renewal_required",
                "This provider job belongs to a prior molecular-context consent.",
                http_status=409,
            )
        try:
            receipt = self.store.consent_receipt(expected_consent_receipt_id)
        except KeyError as exc:
            raise LabError(
                "private_context_renewal_required",
                "This provider job's molecular-context consent is unavailable.",
                http_status=409,
            ) from exc
        if (
            receipt.get("revoked_at")
            or receipt.get("workspace_session_id") != self.session_id
            or receipt.get("investigation_id") != investigation_id
            or receipt.get("patient_molecular_snapshot_id")
            != investigation.get("patient_molecular_snapshot_id")
        ):
            raise LabError(
                "private_context_renewal_required",
                "This provider job's molecular-context consent is no longer active.",
                http_status=409,
            )
        return receipt

    def _require_active_job_disclosure(
        self: EvidenceApplication,
        *,
        investigation_id: str,
        provider: str,
        access_mode: AccessMode,
        request: EvidenceRequest,
        operation: PaperclipOperation,
        expected_payload_sha256: str,
    ) -> JsonObject:
        investigation = self.investigation(investigation_id)
        outbound_payload = self._provider_payload(request, operation)
        if disclosure_payload_sha256(outbound_payload) != expected_payload_sha256:
            raise ValueError("the persisted approval payload does not match the job")
        adapter, direct_sources, _fixtures = self._evidence_configuration()
        if provider == PAPERCLIP_PROVIDER and access_mode is AccessMode.LIVE_PROVIDER:
            destination = _PAPERCLIP_DESTINATION
            policy_versions: JsonObject = {}
            if adapter.deployment_authorization is not None:
                policy_versions["deployment_authorization_id"] = (
                    adapter.deployment_authorization.authorization_id
                )
            if adapter.patient_data_contract is not None:
                policy_versions["patient_data_contract_id"] = (
                    adapter.patient_data_contract.contract_id
                )
        elif access_mode is AccessMode.DIRECT_PRIMARY_SOURCE:
            direct = direct_sources.get(request.source_family)
            if direct is None or direct.provider != provider:
                raise ValueError("the original direct provider is unavailable")
            destination = direct.destination
            policy_versions = {"route": "direct_primary_source"}
        else:
            raise ValueError("the original provider route is unsupported")
        receipt_ids = self.store.active_outbound_disclosure_receipt_ids(
            workspace_session_id=self.session_id,
            user_id=investigation["user_id"],
            investigation_id=investigation_id,
            recipient_kind="evidence_provider",
            recipient_id=provider,
            payload_sha256=expected_payload_sha256,
        )
        for receipt_id in receipt_ids:
            try:
                return self.store.require_outbound_disclosure(
                    receipt_id,
                    workspace_session_id=self.session_id,
                    user_id=str(investigation["user_id"]),
                    investigation_id=investigation_id,
                    recipient_kind="evidence_provider",
                    recipient_id=provider,
                    purpose=request.purpose,
                    destination=destination,
                    data_categories=["patient_influenced_query"],
                    payload=outbound_payload,
                    policy_versions=policy_versions,
                )
            except ValueError:
                continue
        raise ValueError("no active exact disclosure receipt exists")
