"""Provider-neutral execution boundary for public evidence routes."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Mapping

from .evidence_normalization import (
    blocked_result,
    failure_result,
    normalize_evidence_response,
    normalize_fixture_response,
)
from .evidence_types import (
    EvidenceResult,
    EvidenceStatus,
    ProviderTransportError,
)
from .provider_policy import (
    AccessMode,
    DeploymentAuthorization,
    DisclosureApproval,
    EvidenceRequest,
    PatientDataContract,
    ProviderPolicyDecision,
    ProviderPolicyState,
    current_policy_time,
    evaluate_live_provider_request,
)


LiveEvidenceTransport = Callable[[EvidenceRequest], Mapping[str, object]]
PolicyClock = Callable[[], datetime]


class ProviderGateway:
    """The only execution boundary for live, direct, and fixture evidence routes."""

    def __init__(self, *, clock: PolicyClock = current_policy_time) -> None:
        self._clock = clock

    def retrieve_live(
        self,
        *,
        provider: str,
        operation: str,
        request: EvidenceRequest,
        transport: LiveEvidenceTransport,
        deployment_authorization: DeploymentAuthorization | None,
        patient_data_contract: PatientDataContract | None = None,
        disclosure_approval: DisclosureApproval | None = None,
    ) -> EvidenceResult:
        decision = evaluate_live_provider_request(
            provider,
            request,
            operation=operation,
            current_time=self._clock(),
            deployment_authorization=deployment_authorization,
            patient_data_contract=patient_data_contract,
            disclosure_approval=disclosure_approval,
        )
        if not decision.allowed:
            return blocked_result(
                provider=provider,
                access_mode=AccessMode.LIVE_PROVIDER,
                request=request,
                policy=decision,
            )
        return self._execute(
            provider=provider,
            access_mode=AccessMode.LIVE_PROVIDER,
            request=request,
            transport=transport,
            policy=decision,
        )

    def retrieve_direct(
        self,
        *,
        provider: str,
        request: EvidenceRequest,
        transport: LiveEvidenceTransport,
        exact_egress_approved: bool,
    ) -> EvidenceResult:
        decision = ProviderPolicyDecision(
            ProviderPolicyState.ALLOWED
            if not request.patient_influenced or exact_egress_approved is True
            else ProviderPolicyState.BLOCKED_MISSING_EXACT_EGRESS_APPROVAL
        )
        if not decision.allowed:
            return blocked_result(
                provider=provider,
                access_mode=AccessMode.DIRECT_PRIMARY_SOURCE,
                request=request,
                policy=decision,
            )
        return self._execute(
            provider=provider,
            access_mode=AccessMode.DIRECT_PRIMARY_SOURCE,
            request=request,
            transport=transport,
            policy=decision,
        )

    def retrieve_fixture(
        self, *, request: EvidenceRequest, raw: Mapping[str, object]
    ) -> EvidenceResult:
        return normalize_fixture_response(request, raw)

    @staticmethod
    def _execute(
        *,
        provider: str,
        access_mode: AccessMode,
        request: EvidenceRequest,
        transport: LiveEvidenceTransport,
        policy: ProviderPolicyDecision,
    ) -> EvidenceResult:
        try:
            raw = transport(request)
            return normalize_evidence_response(
                provider=provider,
                access_mode=access_mode,
                request=request,
                raw=raw,
                policy=policy,
            )
        except ProviderTransportError as exc:
            status = exc.status
            retry_after = exc.retry_after_seconds
        except TimeoutError:
            status = EvidenceStatus.TIMEOUT
            retry_after = None
        except PermissionError:
            status = EvidenceStatus.AUTHENTICATION_FAILED
            retry_after = None
        except (ConnectionError, OSError):
            status = EvidenceStatus.NETWORK_ERROR
            retry_after = None
        except Exception:
            status = EvidenceStatus.SERVER_ERROR
            retry_after = None
        return failure_result(
            provider=provider,
            access_mode=access_mode,
            request=request,
            status=status,
            policy=policy,
            retry_after_seconds=retry_after,
        )
