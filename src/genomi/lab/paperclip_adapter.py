"""Typed, fail-closed GXL Paperclip adapter with direct-source fallback."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping

from .evidence_gateway import ProviderGateway
from .evidence_normalization import blocked_result
from .evidence_types import (
    FALLBACK_ELIGIBLE_STATUSES,
    EvidenceResult,
    EvidenceStatus,
)
from .provider_policy import (
    AccessMode,
    DeploymentAuthorization,
    DisclosureApproval,
    EvidenceRequest,
    PAPERCLIP_PROVIDER,
    PatientDataContract,
    ProviderPolicyDecision,
    ProviderPolicyState,
    disclosure_fingerprint,
)


class PaperclipOperation(str, Enum):
    SEARCH = "search"
    LOOKUP = "lookup"
    READ_EXTRACT = "read_extract"
    INSPECT_FIGURE = "inspect_figure"
    VERIFY_CLAIM = "verify_claim"


PaperclipSecretProvider = Callable[[], str]
PaperclipTransport = Callable[
    [PaperclipOperation, EvidenceRequest, str], Mapping[str, object]
]
DirectSourceTransport = Callable[
    [PaperclipOperation, EvidenceRequest], Mapping[str, object]
]
PaperclipJobTransport = Callable[
    [PaperclipOperation, EvidenceRequest, str, str], Mapping[str, object]
]
DirectSourceJobTransport = Callable[
    [PaperclipOperation, EvidenceRequest, str], Mapping[str, object]
]
PAPERCLIP_JOB_RESUME_OPERATION = "paperclip.check_background_job"


@dataclass(frozen=True)
class PaperclipCapabilityManifest:
    live_state: str
    operations: tuple[PaperclipOperation, ...] = tuple(PaperclipOperation)
    arbitrary_execute_available: bool = False
    ambient_credentials_allowed: bool = False
    credential_source: str = "explicit_secret_provider_only"
    patient_data_requires_independent_contract: bool = True
    exact_disclosure_required: bool = True
    preferred_when_eligible: bool = True
    provider_credentials_exposed: bool = False
    background_job_check_available: bool = False
    background_job_resume_operation: str = PAPERCLIP_JOB_RESUME_OPERATION

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": PAPERCLIP_PROVIDER,
            "live_state": self.live_state,
            "operations": [operation.value for operation in self.operations],
            "arbitrary_execute_available": self.arbitrary_execute_available,
            "ambient_credentials_allowed": self.ambient_credentials_allowed,
            "credential_source": self.credential_source,
            "patient_data_requires_independent_contract": (
                self.patient_data_requires_independent_contract
            ),
            "exact_disclosure_required": self.exact_disclosure_required,
            "preferred_when_eligible": self.preferred_when_eligible,
            "provider_credentials_exposed": self.provider_credentials_exposed,
            "background_job_check_available": self.background_job_check_available,
            "background_job_resume_operation": self.background_job_resume_operation,
        }


class PaperclipAdapter:
    """Use Paperclip only when authorized; otherwise retain typed alternatives."""

    def __init__(
        self,
        *,
        deployment_authorization: DeploymentAuthorization | None = None,
        patient_data_contract: PatientDataContract | None = None,
        secret_provider: PaperclipSecretProvider | None = None,
        live_transport: PaperclipTransport | None = None,
        live_job_transport: PaperclipJobTransport | None = None,
    ) -> None:
        self.deployment_authorization = deployment_authorization
        self.patient_data_contract = patient_data_contract
        self._secret_provider = secret_provider
        self._live_transport = live_transport
        self._live_job_transport = live_job_transport
        self._gateway = ProviderGateway()

    def capability_manifest(self) -> PaperclipCapabilityManifest:
        authorized = bool(
            self.deployment_authorization
            and self.deployment_authorization.live_use_authorized
        )
        configured = self._secret_provider is not None and self._live_transport is not None
        return PaperclipCapabilityManifest(
            live_state=(
                "authorized"
                if authorized and configured
                else "authorized_unavailable"
                if authorized
                else "hard_disabled"
            ),
            background_job_check_available=bool(
                authorized
                and self._secret_provider is not None
                and self._live_job_transport is not None
            ),
        )

    def retrieve(
        self,
        *,
        operation: PaperclipOperation,
        request: EvidenceRequest,
        disclosure_approval: DisclosureApproval | None = None,
        direct_source_provider: str | None = None,
        direct_source_transport: DirectSourceTransport | None = None,
        direct_source_egress_approved: bool = False,
        fixture: Mapping[str, object] | None = None,
    ) -> EvidenceResult:
        operation = PaperclipOperation(operation)
        live_result = self._retrieve_live(
            operation=operation,
            request=request,
            disclosure_approval=disclosure_approval,
        )
        attempts = [live_result.attempt()]
        if live_result.status not in FALLBACK_ELIGIBLE_STATUSES:
            return live_result.with_route_attempts(tuple(attempts))
        if direct_source_transport is not None and direct_source_provider:
            direct_result = self._gateway.retrieve_direct(
                provider=direct_source_provider,
                request=request,
                transport=lambda approved_request: direct_source_transport(
                    operation, approved_request
                ),
                exact_egress_approved=direct_source_egress_approved,
            )
            attempts.append(direct_result.attempt())
            if direct_result.status not in FALLBACK_ELIGIBLE_STATUSES:
                return direct_result.with_route_attempts(tuple(attempts))
            live_result = direct_result
        if fixture is not None:
            fixture_result = self._gateway.retrieve_fixture(request=request, raw=fixture)
            attempts.append(fixture_result.attempt())
            return fixture_result.with_route_attempts(tuple(attempts))
        return live_result.with_route_attempts(tuple(attempts))

    def resume_live_job(
        self,
        *,
        operation: PaperclipOperation,
        request: EvidenceRequest,
        job_id: str,
        resume_operation: str,
        approved: bool,
    ) -> EvidenceResult:
        """Poll an exact Paperclip job; never submit the original query again."""

        if resume_operation != PAPERCLIP_JOB_RESUME_OPERATION:
            raise ValueError("Paperclip job resume operation is not allowlisted")
        approval = (
            DisclosureApproval(
                provider=PAPERCLIP_PROVIDER,
                approval_id="persisted-capability-job-approval",
                request_fingerprint=disclosure_fingerprint(
                    PAPERCLIP_PROVIDER, request
                ),
            )
            if approved
            else None
        )

        def transport(approved_request: EvidenceRequest) -> Mapping[str, object]:
            if self._secret_provider is None or self._live_job_transport is None:
                return {
                    "status": EvidenceStatus.SOURCE_UNAVAILABLE.value,
                    "source_family": approved_request.source_family.value,
                    "records": [],
                }
            credential = self._secret_provider()
            if not isinstance(credential, str) or not credential:
                return {
                    "status": EvidenceStatus.AUTHENTICATION_FAILED.value,
                    "source_family": approved_request.source_family.value,
                    "records": [],
                }
            return self._live_job_transport(
                PaperclipOperation(operation), approved_request, job_id, credential
            )

        return self._gateway.retrieve_live(
            provider=PAPERCLIP_PROVIDER,
            request=request,
            transport=transport,
            deployment_authorization=self.deployment_authorization,
            patient_data_contract=self.patient_data_contract,
            disclosure_approval=approval,
        )

    def _retrieve_live(
        self,
        *,
        operation: PaperclipOperation,
        request: EvidenceRequest,
        disclosure_approval: DisclosureApproval | None,
    ) -> EvidenceResult:
        def transport(approved_request: EvidenceRequest) -> Mapping[str, object]:
            if self._secret_provider is None or self._live_transport is None:
                return {
                    "status": EvidenceStatus.SOURCE_UNAVAILABLE.value,
                    "source_family": approved_request.source_family.value,
                    "records": [],
                }
            credential = self._secret_provider()
            if not isinstance(credential, str) or not credential:
                return {
                    "status": EvidenceStatus.AUTHENTICATION_FAILED.value,
                    "source_family": approved_request.source_family.value,
                    "records": [],
                }
            return self._live_transport(operation, approved_request, credential)

        return self._gateway.retrieve_live(
            provider=PAPERCLIP_PROVIDER,
            request=request,
            transport=transport,
            deployment_authorization=self.deployment_authorization,
            patient_data_contract=self.patient_data_contract,
            disclosure_approval=disclosure_approval,
        )


def hard_disabled_paperclip_result(request: EvidenceRequest) -> EvidenceResult:
    return blocked_result(
        provider=PAPERCLIP_PROVIDER,
        access_mode=AccessMode.LIVE_PROVIDER,
        request=request,
        policy=ProviderPolicyDecision(
            ProviderPolicyState.BLOCKED_MISSING_DEPLOYMENT_AUTHORIZATION
        ),
    )
