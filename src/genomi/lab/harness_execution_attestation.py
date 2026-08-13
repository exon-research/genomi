"""Attestation of harness execution reports against the capability ledger."""

from __future__ import annotations

import hashlib

from .harness_application_contract import HarnessApplication
from .models import JsonObject, compact_json


class HarnessExecutionAttestationMixin:
    """Validate reported capability outcomes against durable executions."""

    def _attest_execution_report_to_capability_ledger(
        self: HarnessApplication,
        investigation_id: str,
        *,
        investigation: JsonObject,
        current_plan: JsonObject,
        artifact: JsonObject,
    ) -> dict[str, JsonObject]:
        """Bind every reported request to its exact durable capability result."""

        plan = current_plan.get("plan")
        plan_version_id = str(current_plan.get("plan_version_id") or "")
        consent_receipt_id = str(investigation.get("active_consent_receipt_id") or "")
        if not isinstance(plan, dict) or not plan_version_id or not consent_receipt_id:
            raise ValueError(
                "execution report requires the current accepted plan and consent receipt"
            )
        plan_requests = plan.get("capability_requests")
        report_results = artifact.get("request_results")
        if not isinstance(plan_requests, list) or not isinstance(report_results, list):
            raise ValueError(
                "execution report must cover the exact accepted plan requests"
            )

        expected_by_id: dict[str, JsonObject] = {}
        for request in plan_requests:
            if not isinstance(request, dict):
                raise ValueError(
                    "execution report cannot attest a malformed accepted plan request"
                )
            request_id = str(request.get("id") or "")
            capability = str(request.get("capability") or "")
            if not request_id or not capability or request_id in expected_by_id:
                raise ValueError(
                    "execution report cannot attest malformed or duplicate accepted requests"
                )
            expected_by_id[request_id] = request

        reported_by_id: dict[str, JsonObject] = {}
        for item in report_results:
            if not isinstance(item, dict):
                raise ValueError("execution report request results must be objects")
            request_id = str(item.get("request_id") or "")
            capability = str(item.get("capability") or "")
            status = str(item.get("status") or "")
            if (
                not request_id
                or not capability
                or not status
                or request_id in reported_by_id
            ):
                raise ValueError(
                    "execution report must contain one nonempty result per accepted request"
                )
            reported_by_id[request_id] = item

        if set(reported_by_id) != set(expected_by_id):
            raise ValueError(
                "execution report must cover the exact accepted plan requests"
            )

        attested: dict[str, JsonObject] = {}
        for request_id, request in expected_by_id.items():
            capability = str(request["capability"])
            reported = reported_by_id[request_id]
            if str(reported.get("capability") or "") != capability:
                raise ValueError(
                    "execution report capability identities must match the accepted plan"
                )
            execution = self.store.get_capability_execution(
                investigation_id, plan_version_id, request_id
            )
            if not isinstance(execution, dict):
                raise ValueError(
                    "execution report requires a persisted capability execution for every accepted request"
                )
            expected_fingerprint = hashlib.sha256(
                compact_json(
                    {"plan_version_id": plan_version_id, "request": request}
                ).encode("utf-8")
            ).hexdigest()
            if (
                execution.get("investigation_id") != investigation_id
                or execution.get("plan_version_id") != plan_version_id
                or execution.get("consent_receipt_id") != consent_receipt_id
                or execution.get("request_id") != request_id
                or execution.get("capability") != capability
                or execution.get("request_fingerprint") != expected_fingerprint
            ):
                raise ValueError(
                    "execution report capability execution does not match the current accepted request and consent receipt"
                )
            persisted_report_status = self._persisted_execution_report_status(execution)
            if str(reported.get("status") or "") != persisted_report_status:
                raise ValueError(
                    "execution report status does not match the persisted capability result"
                )
            attested[request_id] = execution
        return attested

    @staticmethod
    def _persisted_execution_report_status(execution: JsonObject) -> str:
        """Return the status exposed to a harness for one durable execution."""

        result = execution.get("result")
        if not isinstance(result, dict):
            raise ValueError(
                "persisted capability execution lacks a typed result for attestation"
            )
        result_status = str(result.get("status") or "")
        if not result_status:
            raise ValueError(
                "persisted capability execution result lacks a typed status"
            )
        exposed_status = (
            "completed"
            if result_status in {"committed", "projected", "registered"}
            else result_status
        )
        if result_status == "approval_required":
            ledger_status = "approval_required"
        elif result_status == "in_progress":
            ledger_status = "in_progress"
        elif result_status in {
            "committed",
            "completed",
            "projected",
            "registered",
            "data_returned",
        }:
            ledger_status = "completed"
        else:
            ledger_status = "failed"
        if execution.get("status") != ledger_status:
            raise ValueError(
                "persisted capability execution status and result are inconsistent"
            )
        return exposed_status
