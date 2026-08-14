"""Provider-neutral GenomiLab evidence retrieval application boundary."""

from __future__ import annotations

from typing import Mapping

from .evidence_application_contract import EvidenceApplication
from .evidence_disclosure_service import EvidenceDisclosureApplicationMixin
from .evidence_job_service import EvidenceJobApplicationMixin
from .evidence_source import DirectEvidenceSource as DirectEvidenceSource
from .evidence_store import EvidenceCommitGuardError
from .evidence_types import EvidenceResult, EvidenceStatus
from .models import JsonObject
from .paperclip_adapter import PaperclipAdapter, PaperclipOperation
from .provider_policy import (
    AccessMode,
    DisclosureApproval,
    PAPERCLIP_PROVIDER,
    ProviderPolicyState,
    SourceFamily,
    current_policy_time,
    disclosure_fingerprint,
    evaluate_live_provider_request,
    live_provider_policy_binding,
)
from .service_errors import LabError
from .evidence_service_support import (
    PAPERCLIP_DESTINATION as _PAPERCLIP_DESTINATION,
    EvidenceApplicationSupportMixin,
)


class EvidenceApplicationMixin(
    EvidenceDisclosureApplicationMixin,
    EvidenceJobApplicationMixin,
    EvidenceApplicationSupportMixin,
):
    """Configure routes, retrieve evidence, and commit normalized results."""

    def configure_evidence_gateway(
        self: EvidenceApplication,
        *,
        paperclip_adapter: PaperclipAdapter | None = None,
        direct_sources: Mapping[SourceFamily | str, DirectEvidenceSource] | None = None,
        fixtures: Mapping[SourceFamily | str, Mapping[str, object]] | None = None,
    ) -> None:
        """Install host-owned adapters; this operation is not exposed to the portal."""

        setattr(self, "_evidence_paperclip", paperclip_adapter or PaperclipAdapter())
        normalized_direct: dict[SourceFamily, DirectEvidenceSource] = {}
        for raw_family, route in (direct_sources or {}).items():
            family = SourceFamily(raw_family)
            if route.source_family is not family:
                raise ValueError("direct source family does not match its route key")
            normalized_direct[family] = route
        setattr(self, "_evidence_direct_sources", normalized_direct)
        setattr(
            self,
            "_evidence_fixtures",
            {
                SourceFamily(raw_family): dict(raw_fixture)
                for raw_family, raw_fixture in (fixtures or {}).items()
            },
        )

    def evidence_capability_manifest(self: EvidenceApplication) -> JsonObject:
        adapter, direct_sources, fixtures = self._evidence_configuration()
        paperclip = adapter.capability_manifest().to_dict()
        return {
            "gateway": "GenomiLab",
            "provider_neutral": True,
            "provider_credentials_exposed": False,
            "operations": list(paperclip["operations"]),
            "paperclip": paperclip,
            "direct_sources": [
                direct_sources[family].manifest()
                for family in sorted(direct_sources, key=lambda item: item.value)
            ],
            "fixture_source_families": sorted(family.value for family in fixtures),
        }

    def retrieve_public_evidence(
        self: EvidenceApplication,
        investigation_id: str,
        payload: JsonObject,
        *,
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> JsonObject:
        investigation = self.investigation(investigation_id)
        request, operation = self._parse_evidence_request(payload)
        adapter, direct_sources, fixtures = self._evidence_configuration()
        outbound_payload = self._provider_payload(request, operation)
        paperclip_receipt_id = self._optional_receipt_id(
            payload.get("paperclip_disclosure_receipt_id"),
            "paperclip_disclosure_receipt_id",
        )
        direct_receipt_id = self._optional_receipt_id(
            payload.get("direct_disclosure_receipt_id"),
            "direct_disclosure_receipt_id",
        )
        data_categories = [request.data_class.value]
        paperclip_approval: DisclosureApproval | None = None
        if paperclip_receipt_id is not None:
            expected_policy_versions = live_provider_policy_binding(
                PAPERCLIP_PROVIDER,
                request,
                deployment_authorization=adapter.deployment_authorization,
                patient_data_contract=adapter.patient_data_contract,
            )
            self._require_evidence_receipt(
                investigation=investigation,
                investigation_id=investigation_id,
                provider=PAPERCLIP_PROVIDER,
                purpose=request.purpose,
                destination=_PAPERCLIP_DESTINATION,
                data_categories=data_categories,
                policy_versions=expected_policy_versions,
                payload=outbound_payload,
                receipt_id=paperclip_receipt_id,
            )
            paperclip_approval = DisclosureApproval(
                provider=PAPERCLIP_PROVIDER,
                approval_id=paperclip_receipt_id,
                request_fingerprint=disclosure_fingerprint(PAPERCLIP_PROVIDER, request),
            )
        direct = direct_sources.get(request.source_family)
        direct_approved = False
        if direct_receipt_id is not None:
            if direct is None:
                raise LabError(
                    "evidence_provider_unavailable",
                    "No direct evidence provider is configured for this source family.",
                    http_status=409,
                )
            self._require_evidence_receipt(
                investigation=investigation,
                investigation_id=investigation_id,
                provider=direct.provider,
                purpose=request.purpose,
                destination=direct.destination,
                data_categories=data_categories,
                policy_versions={"route": "direct_primary_source"},
                payload=outbound_payload,
                receipt_id=direct_receipt_id,
            )
            direct_approved = True
        result = adapter.retrieve(
            operation=operation,
            request=request,
            disclosure_approval=paperclip_approval,
            direct_source_provider=direct.provider if direct else None,
            direct_source_transport=direct.transport if direct else None,
            direct_source_egress_approved=direct_approved,
            fixture=fixtures.get(request.source_family),
        )
        self._validate_background_job_owner(
            result,
            direct,
            paperclip_job_available=(
                adapter.capability_manifest().background_job_check_available
            ),
        )
        if result.status is not EvidenceStatus.IN_PROGRESS:
            attempts = result.route_attempts or (result.attempt(),)
            paperclip_attempted = any(
                attempt.provider == PAPERCLIP_PROVIDER
                and attempt.access_mode is AccessMode.LIVE_PROVIDER
                and attempt.policy_state is ProviderPolicyState.ALLOWED
                for attempt in attempts
            )
            direct_attempted = bool(
                direct is not None
                and any(
                    attempt.provider == direct.provider
                    and attempt.access_mode is AccessMode.DIRECT_PRIMARY_SOURCE
                    and attempt.policy_state is ProviderPolicyState.ALLOWED
                    for attempt in attempts
                )
            )
            current_adapter, current_direct_sources, _current_fixtures = (
                self._evidence_configuration()
            )
            if paperclip_attempted and paperclip_receipt_id is not None:
                current_policy = evaluate_live_provider_request(
                    PAPERCLIP_PROVIDER,
                    request,
                    operation=operation.value,
                    current_time=current_policy_time(),
                    deployment_authorization=current_adapter.deployment_authorization,
                    patient_data_contract=current_adapter.patient_data_contract,
                    disclosure_approval=paperclip_approval,
                )
                if not current_policy.allowed:
                    raise LabError(
                        "evidence_disclosure_renewal_required",
                        "The evidence-provider policy changed while the query was running.",
                        http_status=409,
                    )
                current_policy_versions = live_provider_policy_binding(
                    PAPERCLIP_PROVIDER,
                    request,
                    deployment_authorization=current_adapter.deployment_authorization,
                    patient_data_contract=current_adapter.patient_data_contract,
                )
                self._require_evidence_receipt(
                    investigation=self.investigation(investigation_id),
                    investigation_id=investigation_id,
                    provider=PAPERCLIP_PROVIDER,
                    purpose=request.purpose,
                    destination=_PAPERCLIP_DESTINATION,
                    data_categories=data_categories,
                    policy_versions=current_policy_versions,
                    payload=outbound_payload,
                    receipt_id=paperclip_receipt_id,
                )
            if (
                direct_attempted
                and direct_receipt_id is not None
                and direct is not None
            ):
                current_direct = current_direct_sources.get(request.source_family)
                if current_direct is None or current_direct.provider != direct.provider:
                    raise LabError(
                        "evidence_disclosure_renewal_required",
                        "The direct evidence-provider route changed while the query was running.",
                        http_status=409,
                    )
                self._require_evidence_receipt(
                    investigation=self.investigation(investigation_id),
                    investigation_id=investigation_id,
                    provider=current_direct.provider,
                    purpose=request.purpose,
                    destination=current_direct.destination,
                    data_categories=data_categories,
                    policy_versions={"route": "direct_primary_source"},
                    payload=outbound_payload,
                    receipt_id=direct_receipt_id,
                )
        committed_receipt_id = (
            paperclip_receipt_id
            if result.provider == PAPERCLIP_PROVIDER
            and result.access_mode is AccessMode.LIVE_PROVIDER
            else direct_receipt_id
            if result.access_mode is AccessMode.DIRECT_PRIMARY_SOURCE
            else None
        )
        return self._commit_or_report_evidence_result(
            investigation_id,
            result=result,
            operation=operation,
            expected_plan_version_id=expected_plan_version_id,
            expected_disclosure_receipt_id=committed_receipt_id,
            expected_consent_receipt_id=expected_consent_receipt_id,
        )

    def _commit_or_report_evidence_result(
        self: EvidenceApplication,
        investigation_id: str,
        *,
        result: EvidenceResult,
        operation: PaperclipOperation,
        expected_plan_version_id: str | None = None,
        expected_disclosure_receipt_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> JsonObject:
        normalized = self._ledger_evidence(result, operation)
        if result.status is EvidenceStatus.IN_PROGRESS:
            return {
                "status": "in_progress",
                "job_id": result.job_id,
                "resume_operation": result.resume_operation,
                **(
                    {"poll_after_seconds": result.poll_after_seconds}
                    if result.poll_after_seconds is not None
                    else {}
                ),
                "provider_result": normalized,
            }
        deduplication_key = self._provider_deduplication_key(result, operation)
        try:
            record = self.store.commit_evidence(
                investigation_id,
                source_family=result.request.source_family.value,
                operation=f"public_evidence.{operation.value}",
                evidence=normalized,
                deduplication_key=deduplication_key,
                expected_plan_version_id=expected_plan_version_id,
                expected_disclosure_receipt_id=expected_disclosure_receipt_id,
                expected_consent_receipt_id=expected_consent_receipt_id,
            )
        except EvidenceCommitGuardError as exc:
            if exc.code == "disclosure_revoked":
                raise LabError(
                    "evidence_disclosure_renewal_required",
                    "The evidence disclosure was revoked before the result could be committed.",
                    http_status=409,
                ) from exc
            if exc.code == "consent_revoked":
                raise LabError(
                    "private_context_renewal_required",
                    "The molecular-context consent changed before evidence could be committed.",
                    http_status=409,
                ) from exc
            raise LabError(
                "capability_plan_superseded",
                "The evidence result no longer belongs to the current accepted plan.",
                http_status=409,
            ) from exc
        status = (
            "committed"
            if result.status
            in {
                EvidenceStatus.DATA_RETURNED,
                EvidenceStatus.IN_SCOPE_EMPTY,
                EvidenceStatus.OUT_OF_SCOPE_FOR_INPUT,
            }
            else result.status.value
        )
        return {
            "status": status,
            "evidence_record": record,
            "provider_result": normalized,
        }
