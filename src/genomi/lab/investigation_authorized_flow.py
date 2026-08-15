"""Routine investigation orchestration under one patient authorization."""

from __future__ import annotations

from .authorization_store import (
    AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
    AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
)
from .harness import HarnessArtifactKind, HarnessCommand, HarnessOperation
from .harness_authorized_service import (
    _INVESTIGATION_HARNESS_AUTHORITY,
    authorized_harness_command_id,
)
from .models import JsonObject
from .service_errors import LabError


class InvestigationAuthorizedFlowMixin:
    """Advance planning, execution, follow-ups, and resume without repeat gates."""

    def investigation_authorization_candidate(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Build the one review sheet for context plus routine harness work."""

        return self._investigation_authorizations.candidate(
            investigation_id, payload
        )

    def authorize_and_start_investigation(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Commit one scoped authorization and start deterministic planning."""

        with self._operation_lock:
            return self._investigation_authorizations.authorize_and_start(
                investigation_id, payload
            )

    def _require_investigation_authorization(
        self,
        investigation_id: str,
        *,
        intent: str,
        receipt: JsonObject | None = None,
    ) -> JsonObject:
        return self._investigation_authorizations.require_current(
            investigation_id, intent=intent, receipt=receipt
        )

    def _require_authorized_harness_disclosure(
        self,
        investigation_id: str,
        disclosure_receipt_id: str,
        intent: str,
    ) -> JsonObject:
        try:
            derived = self.store.investigation_authorization_for_subject(
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=disclosure_receipt_id,
            )
        except (KeyError, ValueError) as exc:
            raise LabError(
                "investigation_authorization_required",
                "Review and authorize this investigation before continuing.",
                http_status=409,
            ) from exc
        authorization = (
            derived.get("authorization") if isinstance(derived, dict) else None
        )
        if not isinstance(authorization, dict):
            raise LabError(
                "investigation_authorization_required",
                "Review and authorize this investigation before continuing.",
                http_status=409,
            )
        return self._require_investigation_authorization(
            investigation_id,
            intent=intent,
            receipt=authorization,
        )

    def _ensure_authorized_planning_started(
        self, investigation_id: str, authorization: JsonObject
    ) -> JsonObject:
        command_key = {
            "authorization_receipt_id": authorization[
                "authorization_receipt_id"
            ],
            "stage": "planning",
        }
        initial_command_id = authorized_harness_command_id(
            str(authorization["authorization_receipt_id"]),
            intent="plan",
            operation=HarnessOperation.START_TASK_RUN,
            artifact_kind=HarnessArtifactKind.PLAN,
            command_key=command_key,
        )
        binding = self.store.active_harness_binding(investigation_id)
        operation = (
            HarnessOperation.START_TASK_RUN
            if self.store.harness_command(initial_command_id) is not None
            or not isinstance(binding, dict)
            else HarnessOperation.REPLACE_TASK_BINDING
        )
        return self._execute_authorized_harness_command(
            investigation_id,
            intent="plan",
            operation=operation,
            artifact_kind=HarnessArtifactKind.PLAN,
            instruction=str(self.investigation(investigation_id)["question"]),
            reason=(
                "Replan after the patient authorized the current molecular profile."
                if operation == HarnessOperation.REPLACE_TASK_BINDING
                else ""
            ),
            command_key=command_key,
            _authority=_INVESTIGATION_HARNESS_AUTHORITY,
        )

    def advance_authorized_investigation_plan(
        self, investigation_id: str
    ) -> JsonObject:
        """Adopt the current in-scope plan and immediately run its next stage."""

        authorization = self._require_investigation_authorization(
            investigation_id, intent="execute_accepted_plan"
        )
        investigation = self.investigation(investigation_id)
        current = investigation.get("current_plan_version")
        if not isinstance(current, dict):
            raise LabError(
                "harness_plan_required",
                "The installed harness has not proposed a working plan yet.",
                http_status=409,
            )
        plan = current.get("plan")
        if not isinstance(plan, dict):
            raise LabError(
                "harness_plan_required",
                "The current working plan is unavailable.",
                http_status=409,
            )
        self.validate_harness_capability_plan(investigation_id, plan)
        accepted = self._workspace.accept_current_plan(
            investigation_id,
            {
                "approved": True,
                "plan_version_id": current.get("plan_version_id"),
                "plan_sha256": current.get("plan_sha256"),
            },
        )
        acceptance = accepted.get("plan_acceptance")
        if not isinstance(acceptance, dict):
            raise RuntimeError("authorized plan adoption produced no acceptance")
        self.store.derive_investigation_authorization_subject(
            authorization["authorization_receipt_id"],
            subject_kind=AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
            subject_id=acceptance["plan_acceptance_id"],
        )
        self.store.require_investigation_authorization_subject(
            authorization["authorization_receipt_id"],
            subject_kind=AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
            subject_id=acceptance["plan_acceptance_id"],
        )
        has_capabilities = bool(plan.get("capability_requests"))
        artifact_kind = (
            HarnessArtifactKind.EXECUTION_REPORT
            if has_capabilities
            else HarnessArtifactKind.BRIEF_DRAFT
        )
        harness = self._execute_authorized_harness_command(
            investigation_id,
            intent="execute_accepted_plan",
            operation=HarnessOperation.REPLACE_TASK_BINDING,
            artifact_kind=artifact_kind,
            instruction=(
                "Execute the exact adopted investigation plan."
                if has_capabilities
                else (
                    "Draft the patient research brief from the adopted plan "
                    "and committed evidence."
                )
            ),
            reason=(
                "Continue the investigation under its active patient authorization."
            ),
            command_key={
                "authorization_receipt_id": authorization[
                    "authorization_receipt_id"
                ],
                "plan_version_id": current["plan_version_id"],
                "stage": artifact_kind.value,
            },
            _authority=_INVESTIGATION_HARNESS_AUTHORITY,
        )
        return {
            **accepted,
            "acceptance_basis": "investigation_authorization",
            "harness": harness,
        }

    def send_authorized_investigation_message(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Send a patient-authored follow-up without a redundant approval."""

        unexpected = set(payload) - {"instruction", "message", "artifact_kind"}
        if unexpected:
            raise LabError(
                "invalid_harness_message",
                "The follow-up contains unsupported fields.",
            )
        instruction = str(
            payload.get("instruction") or payload.get("message") or ""
        ).strip()
        if not instruction:
            raise LabError(
                "invalid_harness_message", "Enter a follow-up instruction."
            )
        try:
            artifact_kind = HarnessArtifactKind(
                str(
                    payload.get("artifact_kind")
                    or HarnessArtifactKind.BRIEF_DRAFT.value
                )
            )
        except ValueError as exc:
            raise LabError(
                "invalid_harness_message",
                "The requested research output is not supported.",
            ) from exc
        binding = self.store.active_harness_binding(investigation_id)
        binding_revision = (
            binding.get("harness_revision") if isinstance(binding, dict) else None
        )
        if artifact_kind == HarnessArtifactKind.PLAN:
            operation = HarnessOperation.REPLACE_TASK_BINDING
            intent = "plan"
            reason = "The patient requested a change to the working plan."
        else:
            operation = HarnessOperation.SEND_TASK_MESSAGE
            intent = "user_followup"
            reason = ""
        return self._execute_authorized_harness_command(
            investigation_id,
            intent=intent,
            operation=operation,
            artifact_kind=artifact_kind,
            instruction=instruction,
            reason=reason,
            command_key={
                "instruction": instruction,
                "artifact_kind": artifact_kind.value,
                "binding_revision": binding_revision,
            },
            _authority=_INVESTIGATION_HARNESS_AUTHORITY,
        )

    def cancel_authorized_background_work(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        if payload:
            raise LabError(
                "invalid_harness_cancellation",
                "Cancellation does not accept additional fields.",
            )
        binding = self.store.active_harness_binding(investigation_id)
        return self._execute_authorized_harness_command(
            investigation_id,
            intent="cancel",
            operation=HarnessOperation.CANCEL_TASK_WORK,
            artifact_kind=HarnessArtifactKind.PLAN,
            reason=(
                "Cancelled by the local patient from the GenomiLab Research Desk."
            ),
            command_key={
                "binding_id": (
                    binding.get("binding_id")
                    if isinstance(binding, dict)
                    else None
                ),
                "binding_revision": (
                    binding.get("harness_revision")
                    if isinstance(binding, dict)
                    else None
                ),
                "stage": "cancel",
            },
            _authority=_INVESTIGATION_HARNESS_AUTHORITY,
        )

    def _authorization_intent_for_harness_command(
        self, command: HarnessCommand
    ) -> str:
        if command.operation == HarnessOperation.CANCEL_TASK_WORK:
            return "cancel"
        payload = command.payload.to_dict()
        artifact_kind = str(payload.get("artifact_kind") or "")
        if (
            command.operation == HarnessOperation.START_TASK_RUN
            or artifact_kind == HarnessArtifactKind.PLAN.value
        ):
            return "plan"
        if command.operation == HarnessOperation.SEND_TASK_MESSAGE:
            return "user_followup"
        if command.operation == HarnessOperation.RESUME_TASK_RUN:
            return "resume"
        return "execute_accepted_plan"

    def _continue_authorized_harness_flow(
        self,
        command: HarnessCommand,
        committed: JsonObject,
        *,
        receipt_id: str,
    ) -> None:
        """Resume an authorized background completion at its durable checkpoint."""

        self._continue_authorized_harness_result(
            command.investigation_id,
            intent=self._authorization_intent_for_harness_command(command),
            committed=committed,
            receipt_id=receipt_id,
        )

    def _continue_authorized_harness_result(
        self,
        investigation_id: str,
        *,
        intent: str,
        committed: JsonObject,
        receipt_id: str,
    ) -> None:
        """Advance only a committed result derived from active parent authority."""

        try:
            derived = self.store.investigation_authorization_for_subject(
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=receipt_id,
            )
            if not isinstance(derived, dict):
                return
            authorization = derived.get("authorization")
            if not isinstance(authorization, dict):
                return
            self._require_investigation_authorization(
                investigation_id,
                intent=intent,
                receipt=authorization,
            )
            response = committed.get("harness_response")
            result = response.get("result") if isinstance(response, dict) else None
            reference = (
                result.get("proposed_artifact_reference")
                if isinstance(result, dict)
                else None
            )
            kind = (
                str(reference.get("kind") or "")
                if isinstance(reference, dict)
                else ""
            )
            if committed.get("status") != "accepted" or not committed.get(
                "committed_artifact"
            ):
                return
            if kind == HarnessArtifactKind.PLAN.value:
                self.advance_authorized_investigation_plan(
                    investigation_id
                )
                return
            if kind != HarnessArtifactKind.EXECUTION_REPORT.value:
                return
            investigation = self.investigation(investigation_id)
            if investigation.get("status") != "running":
                return
            current = investigation.get("current_plan_version")
            if not isinstance(current, dict):
                return
            self._execute_authorized_harness_command(
                investigation_id,
                intent="user_followup",
                operation=HarnessOperation.SEND_TASK_MESSAGE,
                artifact_kind=HarnessArtifactKind.BRIEF_DRAFT,
                instruction=(
                    "Draft the patient-friendly research brief from the adopted "
                    "plan and all currently committed evidence."
                ),
                command_key={
                    "plan_version_id": current.get("plan_version_id"),
                    "domain_revision": investigation.get("domain_revision"),
                    "stage": "automatic_brief",
                },
                _authority=_INVESTIGATION_HARNESS_AUTHORITY,
            )
        except (KeyError, ValueError, LabError):
            # The completed command remains durable. A scope change or an
            # unavailable next turn leaves the visible work at its checkpoint.
            return

    def approve_and_continue_harness_capability(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        with self._operation_lock:
            self._require_investigation_authorization(
                investigation_id, intent="resume"
            )
            result = self._continue_harness_capability_after_approval(
                investigation_id, payload
            )
            return self._continue_after_capability_result(
                investigation_id, payload, result
            )

    def check_and_continue_harness_capability(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        with self._operation_lock:
            self._require_investigation_authorization(
                investigation_id, intent="resume"
            )
            result = self._resume_harness_capability_job(
                investigation_id, payload
            )
            return self._continue_after_capability_result(
                investigation_id, payload, result
            )

    def _continue_after_capability_result(
        self,
        investigation_id: str,
        request: JsonObject,
        result: JsonObject,
    ) -> JsonObject:
        if result.get("status") != "completed":
            return result
        try:
            harness = self._execute_authorized_harness_command(
                investigation_id,
                intent="resume",
                operation=HarnessOperation.SEND_TASK_MESSAGE,
                artifact_kind=HarnessArtifactKind.EXECUTION_REPORT,
                instruction=(
                    "Continue the exact adopted plan using the newly committed "
                    "approved evidence, then report the request results."
                ),
                command_key={
                    "request_id": request.get("request_id"),
                    "capability_execution_id": result.get(
                        "capability_execution_id"
                    ),
                    "stage": "approved_evidence_continuation",
                },
                _authority=_INVESTIGATION_HARNESS_AUTHORITY,
            )
        except (KeyError, ValueError, LabError):
            return result
        return {**result, "harness_continuation": harness}


__all__ = ["InvestigationAuthorizedFlowMixin"]
