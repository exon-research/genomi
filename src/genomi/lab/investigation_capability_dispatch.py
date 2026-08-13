"""Capability-family dispatch and parameter contracts for investigations."""

from __future__ import annotations

from .capability_registry import CapabilityFamily, capability_definition
from .disease_evidence_capabilities import (
    execute_local_disease_evidence_request,
    validate_local_disease_evidence_request,
)
from .disease_evidence_external import validate_external_evidence_request
from .disease_relation_contract import validate_disease_relation_parameters
from .hypothesis_contract import GAP_KINDS
from .investigation_capability_protocols import (
    CapabilityApplication as _CapabilityApplication,
)
from .investigation_capability_support import _is_exact_hypothesis_template_case
from .models import JsonObject, compact_json
from .provider_policy import PAPERCLIP_PROVIDER
from .service_errors import LabError


class CapabilityDispatchMixin:
    """Execute and validate one request against its registered family contract."""

    def _execute_capability_request(
        self: _CapabilityApplication,
        investigation_id: str,
        request: JsonObject,
        *,
        approval: JsonObject | None,
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> JsonObject:
        capability = str(request["capability"])
        definition = capability_definition(capability)
        params = dict(request.get("parameters") or {})
        if definition.family is CapabilityFamily.PROFILE_PROJECTION:
            profile = self.investigation_profile(investigation_id)
            if (
                expected_plan_version_id is not None
                or expected_consent_receipt_id is not None
            ):
                self.require_capability_commit_authority(
                    investigation_id,
                    expected_plan_version_id=expected_plan_version_id,
                    expected_consent_receipt_id=expected_consent_receipt_id,
                )
            return {
                "status": "projected",
                "molecular_profile": profile,
            }
        if definition.family is CapabilityFamily.GENOMI_VARIANT:
            return self.invoke_investigation_genome(
                investigation_id,
                operation="variant.resolve",
                params=params,
                expected_plan_version_id=expected_plan_version_id,
                expected_consent_receipt_id=expected_consent_receipt_id,
            )
        if definition.family is CapabilityFamily.LOCAL_DISEASE_EVIDENCE:
            catalog = self.investigation_capability_catalog(investigation_id)
            entry = catalog.get(capability)
            if not isinstance(entry, dict):
                raise ValueError("local disease-evidence capability is unavailable")
            return execute_local_disease_evidence_request(
                self,
                investigation_id,
                capability,
                params,
                entry,
                expected_plan_version_id=expected_plan_version_id,
                expected_consent_receipt_id=expected_consent_receipt_id,
            )
        if definition.family is CapabilityFamily.SOURCE_PUBLIC_EVIDENCE:
            catalog = self.investigation_capability_catalog(investigation_id)
            params = validate_external_evidence_request(
                capability,
                params,
                catalog.get(capability),
            )
        if definition.family in {
            CapabilityFamily.PUBLIC_EVIDENCE,
            CapabilityFamily.SOURCE_PUBLIC_EVIDENCE,
        }:
            accepted = self._accepted_current_plan(investigation_id)
            current_plan = accepted.get("current_plan_version")
            current_plan_version_id = (
                str(current_plan.get("plan_version_id") or "")
                if isinstance(current_plan, dict)
                else ""
            )
            if not current_plan_version_id:
                raise LabError(
                    "plan_acceptance_required",
                    "Public evidence retrieval requires the current accepted plan.",
                    http_status=409,
                )
            if (
                expected_plan_version_id is not None
                and current_plan_version_id != expected_plan_version_id
            ):
                raise LabError(
                    "capability_plan_superseded",
                    "The accepted plan changed while the capability was running.",
                    http_status=409,
                )
            expected_plan_version_id = (
                expected_plan_version_id or current_plan_version_id
            )
            candidate = self.evidence_disclosure_candidate(investigation_id, params)
            if candidate.get("selected_provider") == "fixture":
                return self.retrieve_public_evidence(
                    investigation_id,
                    params,
                    expected_plan_version_id=expected_plan_version_id,
                    expected_consent_receipt_id=expected_consent_receipt_id,
                )
            if approval is None:
                return {"status": "approval_required", "candidate": candidate}
            approval_payload = {
                **params,
                "approved": True,
                "recipient_provider": approval.get("recipient_provider"),
                "payload_sha256": approval.get("payload_sha256"),
            }
            approved = self.approve_evidence_disclosure(
                investigation_id, approval_payload
            )
            receipt = approved["disclosure_receipt"]
            receipt_field = (
                "paperclip_disclosure_receipt_id"
                if approved["provider"] == PAPERCLIP_PROVIDER
                else "direct_disclosure_receipt_id"
            )
            return self.retrieve_public_evidence(
                investigation_id,
                {
                    **params,
                    receipt_field: receipt["disclosure_receipt_id"],
                },
                expected_plan_version_id=expected_plan_version_id,
                expected_consent_receipt_id=expected_consent_receipt_id,
            )
        if definition.family is CapabilityFamily.DISEASE_RELATION:
            relation = self.store.commit_disease_relation(
                investigation_id,
                params,
                expected_plan_version_id=expected_plan_version_id,
                expected_consent_receipt_id=expected_consent_receipt_id,
            )
            return {"status": "registered", "disease_relation": relation}
        if definition.family in {CapabilityFamily.HYPOTHESIS, CapabilityFamily.GAP}:
            if (
                definition.family is CapabilityFamily.GAP
                and params.get("kind") not in GAP_KINDS
            ):
                raise ValueError("gap registration requires an evidence-gap kind")
            hypothesis = self.store.commit_hypothesis(
                investigation_id,
                kind=params.get("kind"),
                statement=params.get("statement"),
                evidence_record_ids=params.get("evidence_record_ids"),
                profile_revision_ids=params.get("profile_revision_ids"),
                status=params.get("status", "candidate"),
                supersedes_hypothesis_id=params.get("supersedes_hypothesis_id"),
                expected_plan_version_id=expected_plan_version_id,
                expected_consent_receipt_id=expected_consent_receipt_id,
            )
            return {"status": "registered", "hypothesis": hypothesis}
        raise ValueError("unsupported investigation capability")

    @staticmethod
    def _validate_capability_parameters(
        capability: str, parameters: object, catalog: JsonObject
    ) -> None:
        if not isinstance(parameters, dict):
            raise ValueError("capability parameters must be an object")
        family = capability_definition(capability).family
        if family is CapabilityFamily.PROFILE_PROJECTION:
            if parameters:
                raise ValueError("profile projection does not accept parameters")
            return
        if family is CapabilityFamily.LOCAL_DISEASE_EVIDENCE:
            validate_local_disease_evidence_request(
                capability,
                parameters,
                catalog.get(capability),
            )
            return
        if family is CapabilityFamily.SOURCE_PUBLIC_EVIDENCE:
            validate_external_evidence_request(
                capability,
                parameters,
                catalog.get(capability),
            )
            return
        if family is CapabilityFamily.GENOMI_VARIANT:
            expected = catalog[capability].get("parameters") or {}
            if compact_json(parameters) != compact_json(expected):
                raise ValueError(
                    "Genomi variant request exceeds the approved genomic scope"
                )
            return
        if family is CapabilityFamily.PUBLIC_EVIDENCE:
            allowed = {
                "operation",
                "query",
                "query_terms",
                "filters",
                "source_family",
                "purpose",
            }
            if set(parameters) != allowed:
                raise ValueError(
                    "public-evidence request fields do not match the typed contract"
                )
            expected = catalog[capability].get("parameters") or {}
            if compact_json(parameters) != compact_json(expected):
                raise ValueError(
                    "public-evidence request exceeds the current disease scope"
                )
            return
        if family is CapabilityFamily.DISEASE_RELATION:
            normalized = validate_disease_relation_parameters(parameters)
            entry = catalog.get(capability)
            contract = entry.get("parameters") if isinstance(entry, dict) else None
            if not isinstance(contract, dict):
                raise ValueError("disease-relation capability contract is unavailable")
            templates = entry.get("exact_request_templates")
            if not isinstance(templates, list) or not any(
                isinstance(template, dict)
                and compact_json(normalized) == compact_json(template)
                for template in templates
            ):
                raise ValueError(
                    "disease-relation request must match one exact catalog template"
                )
            if normalized["disease_scope"] != contract.get("disease_scope"):
                raise ValueError(
                    "disease-relation scope must match the investigation disease scope"
                )
            eligible_source_ids = set(
                contract.get("eligible_source_evidence_record_ids") or []
            )
            if normalized["direction"] == "context_only":
                eligible_source_ids.update(
                    contract.get("eligible_context_source_evidence_record_ids") or []
                )
            if not set(normalized["source_evidence_record_ids"]).issubset(
                eligible_source_ids
            ):
                raise ValueError(
                    "disease-relation sources must be eligible public evidence records"
                )
            if not set(normalized["profile_revision_ids"]).issubset(
                set(contract.get("eligible_profile_revision_ids") or [])
            ):
                raise ValueError(
                    "disease-relation profile anchors must belong to the pinned snapshot"
                )
            return
        allowed = {
            "kind",
            "statement",
            "evidence_record_ids",
            "profile_revision_ids",
            "status",
            "supersedes_hypothesis_id",
        }
        required = allowed - {"supersedes_hypothesis_id"}
        if not required.issubset(parameters) or not set(parameters).issubset(allowed):
            raise ValueError(
                "hypothesis request fields do not match the typed contract"
            )
        entry = catalog.get(capability)
        contract = entry.get("request_contract") if isinstance(entry, dict) else None
        if not isinstance(contract, dict):
            raise ValueError("hypothesis capability contract is unavailable")
        if parameters.get("kind") not in (contract.get("allowed_kind_values") or []):
            raise ValueError("hypothesis kind is not allowed for this capability")
        if parameters.get("status") not in (
            contract.get("allowed_status_values") or []
        ):
            raise ValueError("hypothesis status is not allowed for this capability")
        templates = entry.get("exact_request_templates")
        matching_template_cases = [
            template
            for template in templates or []
            if isinstance(template, dict)
            and _is_exact_hypothesis_template_case(parameters, template)
        ]
        if matching_template_cases and not any(
            compact_json(parameters) == compact_json(template)
            for template in matching_template_cases
        ):
            raise ValueError("hypothesis request must match one exact catalog template")


__all__ = ["CapabilityDispatchMixin"]
