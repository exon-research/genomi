"""Typed disease-investigation capabilities selected by the installed harness.

The harness chooses requests in a proposed plan.  This application boundary
validates that choice against the current investigation, executes only the
small allowlist below, and commits results through their canonical owners.
"""

from __future__ import annotations

import hashlib

from .capability_store import CAPABILITY_RETRY_OPERATION
from .models import JsonObject, compact_json, required_text
from .service_errors import LabError
from .capability_registry import (
    BackgroundJobOwner,
    CAPABILITY_ALLOWLIST,
    GENOMI_VARIANT_RESOLVE,  # noqa: F401 - public capability identifier
    PROFILE_PROJECT,  # noqa: F401 - public capability identifier
    PUBLIC_EVIDENCE_RETRIEVE,  # noqa: F401 - public capability identifier
    REGISTER_GAP,  # noqa: F401 - public capability identifier
    REGISTER_HYPOTHESIS,  # noqa: F401 - public capability identifier
    capability_definition,
)
from .investigation_capability_support import (
    _background_job_metadata,
)
from .investigation_capability_dispatch import CapabilityDispatchMixin
from .investigation_capability_catalog import (
    build_investigation_capability_catalog,
)
from .investigation_capability_protocols import (
    CapabilityApplication as _CapabilityApplication,
)

_HARNESS_CAPABILITY_EXECUTION_AUTHORITY = object()


class InvestigationCapabilityMixin(CapabilityDispatchMixin):
    """Execute harness-selected requests without giving the harness credentials."""

    def investigation_capability_catalog(
        self: _CapabilityApplication, investigation_id: str
    ) -> JsonObject:
        return build_investigation_capability_catalog(self, investigation_id)

    def validate_harness_capability_plan(
        self: _CapabilityApplication,
        investigation_id: str,
        plan: JsonObject,
    ) -> None:
        catalog = self.investigation_capability_catalog(investigation_id)
        steps = {
            str(step["id"]): step
            for step in plan.get("steps") or []
            if isinstance(step, dict) and isinstance(step.get("id"), str)
        }
        seen: set[str] = set()
        for request in plan.get("capability_requests") or []:
            request_id = required_text(request.get("id"), "capability request id", 200)
            if request_id in seen:
                raise ValueError(
                    "capability request identifiers must be unique within a plan"
                )
            seen.add(request_id)
            capability = required_text(request.get("capability"), "capability", 200)
            catalog_entry = catalog.get(capability)
            if (
                capability not in CAPABILITY_ALLOWLIST
                or not isinstance(catalog_entry, dict)
                or catalog_entry.get("available") is not True
            ):
                raise ValueError(
                    "the harness requested a capability unavailable to this investigation"
                )
            step = steps.get(str(request.get("step_id") or ""))
            if step is None:
                raise ValueError("capability request must reference a plan step")
            if capability not in (step.get("capabilities") or []):
                raise ValueError("capability request must be declared by its plan step")
            if request.get("assigned_agent_role") != step.get("proposed_agent_role"):
                raise ValueError("capability request role must match its plan step")
            self._validate_capability_parameters(
                capability, request.get("parameters"), catalog
            )

    def _execute_harness_capability_request(
        self: _CapabilityApplication,
        investigation_id: str,
        payload: JsonObject,
        *,
        _authority: object,
    ) -> JsonObject:
        if _authority is not _HARNESS_CAPABILITY_EXECUTION_AUTHORITY:
            raise LabError(
                "harness_execution_authority_required",
                "Only the approved harness execution task may invoke this request.",
                http_status=409,
            )
        investigation = self._accepted_current_plan(investigation_id)
        plan = investigation.get("plan")
        if not isinstance(plan, dict):
            raise LabError(
                "harness_plan_required",
                "The installed harness must propose a plan before capabilities run.",
                http_status=409,
            )
        self.validate_harness_capability_plan(investigation_id, plan)
        request_id = required_text(payload.get("request_id"), "request_id", 200)
        matches = [
            item
            for item in plan.get("capability_requests") or []
            if isinstance(item, dict) and item.get("id") == request_id
        ]
        if len(matches) != 1:
            raise LabError(
                "capability_request_not_found",
                "That capability request is not in the current harness plan.",
                http_status=404,
            )
        approval = payload if payload.get("approved") is True else None
        current_plan_version = investigation.get("current_plan_version")
        plan_version_id = (
            str(current_plan_version.get("plan_version_id") or "")
            if isinstance(current_plan_version, dict)
            else None
        )
        result = self._execute_capability_request_idempotently(
            investigation_id,
            matches[0],
            approval=approval,
            plan_version_id=plan_version_id,
        )
        return {
            "status": "completed"
            if result.get("status") in {"committed", "projected", "registered"}
            else result.get("status", "completed"),
            "request_id": request_id,
            "capability": matches[0]["capability"],
            "result": result,
        }

    def _continue_harness_capability_after_approval(
        self: _CapabilityApplication,
        investigation_id: str,
        payload: JsonObject,
    ) -> JsonObject:
        """Continue one paused request after the application validates authority."""

        allowed = {
            "request_id",
            "approved",
            "recipient_provider",
            "payload_sha256",
            "approval_sha256",
        }
        if not isinstance(payload, dict) or set(payload) != allowed:
            raise LabError(
                "invalid_evidence_disclosure",
                "Approve the exact provider and query shown by the harness request.",
                http_status=409,
            )
        investigation = self._accepted_current_plan(investigation_id)
        current_plan = investigation.get("current_plan_version")
        plan_version_id = (
            str(current_plan.get("plan_version_id") or "")
            if isinstance(current_plan, dict)
            else ""
        )
        request_id = required_text(payload.get("request_id"), "request_id", 200)
        execution = self.store.get_capability_execution(
            investigation_id, plan_version_id, request_id
        )
        if (
            not isinstance(execution, dict)
            or execution.get("status") != "approval_required"
        ):
            raise LabError(
                "evidence_disclosure_preview_required",
                "The installed harness must first run this exact request and pause for provider approval.",
                http_status=409,
            )
        return self._execute_harness_capability_request(
            investigation_id,
            payload,
            _authority=_HARNESS_CAPABILITY_EXECUTION_AUTHORITY,
        )

    def _resume_harness_capability_job(
        self: _CapabilityApplication,
        investigation_id: str,
        payload: JsonObject,
    ) -> JsonObject:
        """Check one persisted upstream job without repeating its request."""

        allowed = {
            "request_id",
            "job_id",
            "resume_operation",
            "plan_version_id",
        }
        if not isinstance(payload, dict) or set(payload) != allowed:
            raise LabError(
                "invalid_capability_job_check",
                "A capability job check requires exactly its request, job, and resume operation.",
                http_status=409,
            )
        request_id = required_text(payload.get("request_id"), "request_id", 200)
        job_id = required_text(payload.get("job_id"), "job_id", 500)
        resume_operation = required_text(
            payload.get("resume_operation"), "resume_operation", 200
        )
        requested_plan_version_id = required_text(
            payload.get("plan_version_id"), "plan_version_id", 200
        )
        investigation = self._accepted_current_plan(investigation_id)
        current_plan = investigation.get("current_plan_version")
        plan_version_id = (
            str(current_plan.get("plan_version_id") or "")
            if isinstance(current_plan, dict)
            else ""
        )
        if not plan_version_id:
            raise LabError(
                "harness_plan_required",
                "The current harness plan is unavailable for this capability job.",
                http_status=409,
            )
        if requested_plan_version_id != plan_version_id:
            raise LabError(
                "capability_plan_superseded",
                "This capability job belongs to a superseded harness plan.",
                http_status=409,
            )
        execution = self.store.get_capability_execution(
            investigation_id, plan_version_id, request_id
        )
        if not isinstance(execution, dict):
            raise LabError(
                "capability_job_not_found",
                "That capability job is not part of the current harness plan.",
                http_status=404,
            )
        expected_job_id = str(execution.get("job_id") or "")
        expected_operation = str(execution.get("resume_operation") or "")
        if expected_job_id != job_id or expected_operation != resume_operation:
            raise LabError(
                "capability_job_binding_mismatch",
                "The job or resume operation does not match the persisted capability work.",
                http_status=409,
            )
        if execution.get("status") != "in_progress":
            return self._capability_job_response(execution)
        if resume_operation == CAPABILITY_RETRY_OPERATION:
            raise LabError(
                "capability_job_outcome_unknown",
                "The original capability dispatch did not expose a safe upstream check operation.",
                http_status=409,
            )

        capability = str(execution.get("capability") or "")
        job_owner = capability_definition(capability).background_job_owner
        if job_owner is BackgroundJobOwner.GENOMI:
            checked = self.check_investigation_genome_job(
                investigation_id,
                job_id=job_id,
                resume_operation=resume_operation,
                expected_plan_version_id=plan_version_id,
                expected_consent_receipt_id=str(
                    execution.get("consent_receipt_id") or ""
                ),
            )
        elif job_owner is BackgroundJobOwner.PUBLIC_EVIDENCE:
            checked = self.resume_public_evidence_job(
                investigation_id,
                execution=execution,
                job_id=job_id,
                resume_operation=resume_operation,
            )
        else:
            raise LabError(
                "capability_job_resume_unsupported",
                "This capability has no allowlisted background-job owner.",
                http_status=409,
            )

        latest = self._accepted_current_plan(investigation_id)
        latest_plan = latest.get("current_plan_version")
        if (
            not isinstance(latest_plan, dict)
            or latest_plan.get("plan_version_id") != plan_version_id
        ):
            raise LabError(
                "capability_plan_superseded",
                "The capability result arrived after its accepted plan changed.",
                http_status=409,
            )

        checked, background = self._normalize_capability_execution_result(checked)
        if background is not None and (
            background.get("job_id") != job_id
            or background.get("resume_operation") != resume_operation
        ):
            raise LabError(
                "capability_job_binding_mismatch",
                "The capability owner returned a different job or resume operation.",
                http_status=409,
            )
        execution_status = self._capability_execution_status(checked)
        finished = self.store.finish_capability_execution(
            str(execution["capability_execution_id"]),
            attempt_number=int(execution["active_attempt_number"]),
            claimed_job_id=str(execution["claim_job_id"]),
            status=execution_status,
            result=checked,
            job_id=(background or {}).get("job_id"),
            resume_operation=(background or {}).get("resume_operation"),
            poll_after_seconds=(background or {}).get("poll_after_seconds"),
        )
        return self._capability_job_response(finished)

    @staticmethod
    def _capability_job_response(execution: JsonObject) -> JsonObject:
        result = InvestigationCapabilityMixin._persisted_capability_result(execution)
        state = str(execution.get("status") or "failed")
        return {
            "status": state,
            "request_id": execution.get("request_id"),
            "capability": execution.get("capability"),
            "job_id": execution.get("job_id"),
            "resume_operation": execution.get("resume_operation"),
            "result": result,
        }

    def _execute_capability_request_idempotently(
        self: _CapabilityApplication,
        investigation_id: str,
        request: JsonObject,
        *,
        approval: JsonObject | None,
        plan_version_id: str | None,
    ) -> JsonObject:
        request_id = required_text(request.get("id"), "capability request id", 200)
        capability = required_text(request.get("capability"), "capability", 200)
        authority = self._capability_commit_authority(
            investigation_id, plan_version_id=plan_version_id
        )
        plan_version = required_text(plan_version_id, "plan_version_id", 200)
        request_fingerprint = hashlib.sha256(
            compact_json(
                {
                    "plan_version_id": plan_version,
                    "request": request,
                }
            ).encode("utf-8")
        ).hexdigest()
        existing = self.store.get_capability_execution(
            investigation_id, plan_version, request_id
        )
        approval_binding: JsonObject | None = None
        attempt_kind = "initial"
        if approval is not None:
            approval_binding = self._validated_approval_binding(
                capability, approval, existing
            )
            attempt_kind = "approval_continuation"
        attempt_fingerprint = hashlib.sha256(
            compact_json(
                {
                    "request_fingerprint": request_fingerprint,
                    "attempt_kind": attempt_kind,
                    "approval": approval_binding,
                }
            ).encode("utf-8")
        ).hexdigest()
        claimed = self.store.claim_capability_execution(
            investigation_id=investigation_id,
            plan_version_id=plan_version,
            consent_receipt_id=authority["consent_receipt_id"],
            request_id=request_id,
            capability=capability,
            request_fingerprint=request_fingerprint,
            attempt_fingerprint=attempt_fingerprint,
            attempt_kind=attempt_kind,
            approval_provider=(approval_binding or {}).get("recipient_provider"),
            approval_payload_sha256=(approval_binding or {}).get("payload_sha256"),
        )
        if claimed.get("claimed") is not True:
            return self._persisted_capability_result(claimed)

        try:
            result = self._execute_capability_request(
                investigation_id,
                request,
                approval=approval,
                expected_plan_version_id=authority["plan_version_id"],
                expected_consent_receipt_id=authority["consent_receipt_id"],
            )
        except LabError as exc:
            result = {
                "status": exc.code,
                "message": exc.message,
                "retry_after_approval": exc.http_status == 409,
            }
        except (KeyError, ValueError) as exc:
            result = {
                "status": "capability_request_rejected",
                "message": str(exc),
                "retry_after_approval": False,
            }
        result, background = self._normalize_capability_execution_result(result)
        execution_status = self._capability_execution_status(result)
        finished = self.store.finish_capability_execution(
            str(claimed["capability_execution_id"]),
            attempt_number=int(claimed["active_attempt_number"]),
            claimed_job_id=str(claimed["job_id"]),
            status=execution_status,
            result=result,
            job_id=(background or {}).get("job_id"),
            resume_operation=(background or {}).get("resume_operation"),
            poll_after_seconds=(background or {}).get("poll_after_seconds"),
        )
        return self._persisted_capability_result(finished)

    def _capability_commit_authority(
        self: _CapabilityApplication,
        investigation_id: str,
        *,
        plan_version_id: str | None,
    ) -> JsonObject:
        """Capture the exact accepted plan and live private-context authority."""

        investigation = self._accepted_current_plan(investigation_id)
        current_plan = investigation.get("current_plan_version")
        current_plan_id = (
            str(current_plan.get("plan_version_id") or "")
            if isinstance(current_plan, dict)
            else ""
        )
        expected_plan_id = required_text(
            plan_version_id or current_plan_id, "plan_version_id", 200
        )
        if current_plan_id != expected_plan_id:
            raise LabError(
                "capability_plan_superseded",
                "This capability request does not belong to the current accepted plan.",
                http_status=409,
            )
        snapshot_id = str(investigation.get("patient_molecular_snapshot_id") or "")
        if not snapshot_id:
            raise LabError(
                "private_context_required",
                "Approve the investigation's molecular context before its capabilities run.",
                http_status=409,
            )
        snapshot = self.store.get_profile_snapshot(snapshot_id)
        receipt = self._active_context_receipt(investigation, snapshot)
        consent_receipt_id = str(receipt.get("consent_receipt_id") or "")
        if (
            not consent_receipt_id
            or receipt.get("revoked_at")
            or receipt.get("workspace_session_id") != getattr(self, "session_id", None)
            or receipt.get("patient_molecular_snapshot_id") != snapshot_id
        ):
            raise LabError(
                "private_context_renewal_required",
                "Approve this molecular context again for the current workspace session.",
                http_status=409,
            )
        return {
            "plan_version_id": current_plan_id,
            "patient_molecular_snapshot_id": snapshot_id,
            "consent_receipt_id": consent_receipt_id,
        }

    def require_capability_commit_authority(
        self: _CapabilityApplication,
        investigation_id: str,
        *,
        expected_plan_version_id: str | None,
        expected_consent_receipt_id: str | None,
    ) -> JsonObject:
        current = self._capability_commit_authority(
            investigation_id,
            plan_version_id=expected_plan_version_id,
        )
        if current["consent_receipt_id"] != expected_consent_receipt_id:
            raise LabError(
                "private_context_renewal_required",
                "The molecular-context consent changed while the capability was running.",
                http_status=409,
            )
        return current

    @staticmethod
    def _validated_approval_binding(
        capability: str,
        approval: JsonObject,
        execution: JsonObject | None,
    ) -> JsonObject:
        if not capability_definition(capability).requires_exact_egress_approval:
            raise LabError(
                "capability_approval_not_supported",
                "That capability does not accept an external-provider approval.",
                http_status=409,
            )
        allowed = {
            "request_id",
            "approved",
            "recipient_provider",
            "payload_sha256",
            "approval_sha256",
        }
        if approval.get("approved") is not True or set(approval) != allowed:
            raise LabError(
                "invalid_evidence_disclosure",
                "Approve the exact provider and query shown in the preview.",
                http_status=409,
            )
        if not isinstance(execution, dict):
            raise LabError(
                "evidence_disclosure_preview_required",
                "Run the evidence request preview before approving provider egress.",
                http_status=409,
            )
        if approval.get("request_id") != execution.get("request_id"):
            raise LabError(
                "evidence_disclosure_changed",
                "The capability request changed after preview; review it again.",
                http_status=409,
            )
        approval_attempt = next(
            (
                attempt
                for attempt in reversed(execution.get("attempts") or [])
                if isinstance(attempt, dict)
                and attempt.get("status") == "approval_required"
                and isinstance(attempt.get("result"), dict)
            ),
            None,
        )
        candidate = (
            approval_attempt["result"].get("candidate")
            if isinstance(approval_attempt, dict)
            else None
        )
        if not isinstance(candidate, dict):
            raise LabError(
                "evidence_disclosure_preview_required",
                "Run the evidence request preview before approving provider egress.",
                http_status=409,
            )
        provider = required_text(
            approval.get("recipient_provider"), "recipient_provider", 200
        )
        payload_hash = required_text(
            approval.get("payload_sha256"), "payload_sha256", 128
        )
        approval_hash = required_text(
            approval.get("approval_sha256"), "approval_sha256", 128
        )
        if provider != candidate.get(
            "selected_provider"
        ) or payload_hash != candidate.get(
            "payload_sha256"
        ) or approval_hash != candidate.get("approval_sha256"):
            raise LabError(
                "evidence_disclosure_changed",
                "The provider or evidence query changed after preview; review it again.",
                http_status=409,
            )
        return {
            "recipient_provider": provider,
            "payload_sha256": payload_hash,
            "approval_sha256": approval_hash,
        }

    @staticmethod
    def _persisted_capability_result(execution: JsonObject) -> JsonObject:
        result = execution.get("result")
        if isinstance(result, dict):
            return result
        if execution.get("status") == "in_progress":
            return {
                "status": "in_progress",
                "job_id": execution.get("job_id"),
                "resume_operation": execution.get("resume_operation")
                or CAPABILITY_RETRY_OPERATION,
                "poll_after_seconds": execution.get("poll_after_seconds") or 1,
            }
        return {"status": str(execution.get("status") or "failed")}

    @staticmethod
    def _normalize_capability_execution_result(
        result: JsonObject,
    ) -> tuple[JsonObject, JsonObject | None]:
        background = _background_job_metadata(result)
        if result.get("status") == "in_progress" and background is None:
            return (
                {
                    "status": "capability_result_invalid",
                    "message": (
                        "The capability reported in-progress work without a job ID "
                        "and resume operation."
                    ),
                    "retry_after_approval": False,
                },
                None,
            )
        if background is None:
            return result, None
        if result.get("status") == "in_progress":
            normalized = dict(result)
        else:
            normalized = {
                "status": "in_progress",
                **background,
                "capability_result": result,
            }
        return normalized, background

    @staticmethod
    def _capability_execution_status(result: JsonObject) -> str:
        status = str(result.get("status") or "")
        if status == "approval_required":
            return "approval_required"
        if status == "in_progress":
            return "in_progress"
        if status in {
            "committed",
            "completed",
            "projected",
            "registered",
            "data_returned",
        }:
            return "completed"
        return "failed"
