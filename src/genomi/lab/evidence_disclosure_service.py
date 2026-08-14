"""Exact outbound-disclosure lifecycle for evidence-provider requests."""

from __future__ import annotations

from .approval_store import disclosure_payload_sha256
from .evidence_application_contract import EvidenceApplication
from .models import JsonObject
from .paperclip_contract import paperclip_operation_scope
from .provider_policy import (
    PAPERCLIP_PROVIDER,
    ProviderPolicyState,
    QueryOrigin,
    current_policy_time,
    disclosure_fingerprint,
    evaluate_live_provider_request,
    live_provider_policy_binding,
    provider_name,
)
from .service_errors import LabError
from .evidence_service_support import PAPERCLIP_DESTINATION as _PAPERCLIP_DESTINATION


class EvidenceDisclosureApplicationMixin:
    """Preview and approve the exact provider payload and destination."""

    def evidence_disclosure_candidate(
        self: EvidenceApplication, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        investigation = self.investigation(investigation_id)
        request, operation = self._parse_evidence_request(payload)
        adapter, direct_sources, fixtures = self._evidence_configuration()
        live_policy = evaluate_live_provider_request(
            PAPERCLIP_PROVIDER,
            request,
            operation=operation.value,
            current_time=current_policy_time(),
            deployment_authorization=adapter.deployment_authorization,
            patient_data_contract=adapter.patient_data_contract,
        )
        paperclip_manifest = adapter.capability_manifest()
        paperclip_state = paperclip_manifest.live_state
        paperclip_scope = paperclip_operation_scope(
            request.source_family, operation.value
        )
        paperclip_request_in_scope = bool(
            request.operation == operation.value
            and any(
                family is request.source_family and operation in operations
                for family, operations in paperclip_manifest.routes
            )
            and paperclip_scope
            and paperclip_scope.accepts(
                query=request.query,
                query_terms=request.query_terms,
                filters=dict(request.filters),
                allow_internal_filters=True,
            )
        )
        paperclip_eligible_after_approval = (
            paperclip_state == "authorized"
            and paperclip_request_in_scope
            and live_policy.state
            in {
                ProviderPolicyState.ALLOWED,
                ProviderPolicyState.BLOCKED_MISSING_EXACT_DISCLOSURE_APPROVAL,
            }
        )
        direct = direct_sources.get(request.source_family)
        routes: list[JsonObject] = [
            {
                "provider": PAPERCLIP_PROVIDER,
                "destination": _PAPERCLIP_DESTINATION,
                "access_mode": "live_provider",
                "current_policy_state": live_policy.state.value,
                "request_in_transport_scope": paperclip_request_in_scope,
                "eligible_after_exact_approval": paperclip_eligible_after_approval,
                "requires_exact_approval": request.patient_influenced,
            }
        ]
        if direct is not None:
            routes.append(
                {
                    **direct.manifest(),
                    "access_mode": "direct_primary_source",
                    "eligible_after_exact_approval": True,
                    "requires_exact_approval": request.patient_influenced,
                }
            )
        if request.source_family in fixtures:
            routes.append(
                {
                    "provider": "fixture",
                    "destination": "local_test_fixture",
                    "access_mode": "fixture",
                    "eligible_after_exact_approval": True,
                    "requires_exact_approval": False,
                }
            )
        selected = (
            PAPERCLIP_PROVIDER
            if paperclip_eligible_after_approval
            else direct.provider
            if direct is not None
            else "fixture"
            if request.source_family in fixtures
            else None
        )
        outbound_payload = self._provider_payload(request, operation)
        return {
            "status": "candidate",
            "investigation_id": investigation["investigation_id"],
            "query_origin": (
                QueryOrigin.PATIENT_CONTEXT_DERIVED.value
                if request.patient_influenced
                else QueryOrigin.PUBLIC_ONLY.value
            ),
            "selected_provider": selected,
            "routes": routes,
            "payload": outbound_payload,
            "payload_sha256": disclosure_payload_sha256(outbound_payload),
        }

    def approve_evidence_disclosure(
        self: EvidenceApplication, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        investigation = self.investigation(investigation_id)
        request, operation = self._parse_evidence_request(payload)
        if payload.get("approved") is not True:
            raise LabError(
                "evidence_disclosure_approval_required",
                "Explicit approval is required before this provider receives the query.",
            )
        candidate = self.evidence_disclosure_candidate(investigation_id, payload)
        if payload.get("payload_sha256") != candidate["payload_sha256"]:
            raise LabError(
                "evidence_disclosure_changed",
                "The evidence query changed after preview; review it again.",
                http_status=409,
            )
        recipient = provider_name(payload.get("recipient_provider"))
        adapter, direct_sources, _fixtures = self._evidence_configuration()
        direct = direct_sources.get(request.source_family)
        if recipient == PAPERCLIP_PROVIDER:
            policy = evaluate_live_provider_request(
                PAPERCLIP_PROVIDER,
                request,
                operation=operation.value,
                current_time=current_policy_time(),
                deployment_authorization=adapter.deployment_authorization,
                patient_data_contract=adapter.patient_data_contract,
            )
            if (
                policy.state
                not in {
                    ProviderPolicyState.ALLOWED,
                    ProviderPolicyState.BLOCKED_MISSING_EXACT_DISCLOSURE_APPROVAL,
                }
                or adapter.capability_manifest().live_state != "authorized"
            ):
                raise LabError(
                    "paperclip_live_unavailable",
                    "Live Paperclip use is not authorized and configured for this request.",
                    http_status=409,
                )
            destination = _PAPERCLIP_DESTINATION
            policy_versions = live_provider_policy_binding(
                PAPERCLIP_PROVIDER,
                request,
                deployment_authorization=adapter.deployment_authorization,
                patient_data_contract=adapter.patient_data_contract,
            )
        elif direct is not None and recipient == direct.provider:
            destination = direct.destination
            policy_versions = {"route": "direct_primary_source"}
        else:
            raise LabError(
                "evidence_provider_unavailable",
                "That evidence provider is not configured for this source family.",
                http_status=409,
            )
        outbound_payload = self._provider_payload(request, operation)
        try:
            receipt = self.store.create_outbound_disclosure_receipt(
                str(investigation["user_id"]),
                workspace_session_id=self.session_id,
                investigation_id=investigation_id,
                recipient_kind="evidence_provider",
                recipient_id=recipient,
                purpose=request.purpose,
                destination=destination,
                data_categories=[request.data_class.value],
                payload=outbound_payload,
                policy_versions=policy_versions,
                approved=True,
            )
        except ValueError as exc:
            raise LabError("invalid_evidence_disclosure", str(exc)) from exc
        return {
            "status": "approved",
            "provider": recipient,
            "request_fingerprint": disclosure_fingerprint(recipient, request),
            "disclosure_receipt": receipt,
        }
