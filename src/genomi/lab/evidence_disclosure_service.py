"""Exact outbound-disclosure lifecycle for evidence-provider requests."""

from __future__ import annotations

import hashlib

from .approval_store import disclosure_payload_sha256
from .evidence_application_contract import EvidenceApplication
from .models import JsonObject, compact_json
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
        paperclip_state = paperclip_manifest.investigation_live_state
        paperclip_scope = paperclip_operation_scope(
            request.source_family, operation.value
        )
        paperclip_request_in_scope = bool(
            request.operation == operation.value
            and any(
                family is request.source_family and operation in operations
                for family, operations in paperclip_manifest.investigation_routes
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
        paperclip_policy_binding = live_provider_policy_binding(
            PAPERCLIP_PROVIDER,
            request,
            deployment_authorization=adapter.deployment_authorization,
            patient_data_contract=adapter.patient_data_contract,
        )
        paperclip_contract_present = bool(
            paperclip_policy_binding.get("patient_data_contract_id")
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
                "policy_binding": paperclip_policy_binding,
                "retention_training_state": (
                    {
                        "retention": "governed_by_pinned_patient_data_contract",
                        "training": "prohibited_by_required_patient_data_contract",
                    }
                    if paperclip_contract_present
                    else {
                        "retention": "not_authorized_for_patient_investigations",
                        "training": (
                            "provider_terms_may_allow_service_improvement_or_training"
                        ),
                    }
                ),
            }
        ]
        if direct is not None:
            routes.append(
                {
                    **direct.manifest(),
                    "access_mode": "direct_primary_source",
                    "eligible_after_exact_approval": True,
                    "requires_exact_approval": request.patient_influenced,
                    "retention_training_state": {
                        "retention": "not_disclosed_by_route",
                        "training": "not_disclosed_by_route",
                    },
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
                    "retention_training_state": {
                        "retention": "local_test_fixture_only",
                        "training": "not_applicable",
                    },
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
        query_origin = (
            QueryOrigin.PATIENT_CONTEXT_DERIVED.value
            if request.patient_influenced
            else QueryOrigin.PUBLIC_ONLY.value
        )
        for route in routes:
            route["approval_sha256"] = hashlib.sha256(
                compact_json(
                    {
                        "investigation_id": investigation["investigation_id"],
                        "query_origin": query_origin,
                        "recipient_provider": route.get("provider"),
                        "route": route,
                        "payload": outbound_payload,
                    }
                ).encode("utf-8")
            ).hexdigest()
        candidate = {
            "status": "candidate",
            "investigation_id": investigation["investigation_id"],
            "query_origin": query_origin,
            "selected_provider": selected,
            "routes": routes,
            "payload": outbound_payload,
            "payload_sha256": disclosure_payload_sha256(outbound_payload),
        }
        selected_route = next(
            (
                route
                for route in routes
                if route.get("provider") == selected
            ),
            None,
        )
        candidate["approval_sha256"] = (
            selected_route.get("approval_sha256")
            if isinstance(selected_route, dict)
            else None
        )
        return candidate

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
        reviewed_route = next(
            (
                route
                for route in candidate["routes"]
                if route.get("provider") == recipient
            ),
            None,
        )
        if not isinstance(reviewed_route, dict) or payload.get(
            "approval_sha256"
        ) != reviewed_route.get("approval_sha256"):
            raise LabError(
                "evidence_disclosure_changed",
                (
                    "The provider destination, policy, or data-handling terms "
                    "changed after preview; review them again."
                ),
                http_status=409,
            )
        if reviewed_route.get("eligible_after_exact_approval") is not True:
            raise LabError(
                "evidence_provider_unavailable",
                "That provider route is not eligible for this exact request.",
                http_status=409,
            )
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
                or adapter.capability_manifest().investigation_live_state
                != "authorized"
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
