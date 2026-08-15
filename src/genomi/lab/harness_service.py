"""GenomiLab application orchestration for an installed agent harness."""

from __future__ import annotations

import secrets
from typing import Any

from .artifact_validation import validate_research_narrative
from .harness import (
    BindingStatus,
    CancelTaskWorkPayload,
    CancellationOutcome,
    EventReplay,
    HarnessArtifactKind,
    HarnessCommand,
    HarnessJobState,
    HarnessOperation,
    ReplaceTaskBindingPayload,
    ReplayStatus,
    ResumeTaskRunPayload,
    SendTaskMessagePayload,
    StartTaskRunPayload,
)
from .harness_application_contract import HarnessApplication as _HarnessApplication
from .harness_authorized_service import AuthorizedHarnessApplicationMixin
from .harness_background_service import HarnessBackgroundApplicationMixin
from .harness_event_service import HarnessEventApplicationMixin
from .harness_execution_attestation import HarnessExecutionAttestationMixin
from .models import JsonObject, required_text
from .service_errors import LabError


class HarnessApplicationMixin(
    AuthorizedHarnessApplicationMixin,
    HarnessBackgroundApplicationMixin,
    HarnessEventApplicationMixin,
    HarnessExecutionAttestationMixin,
):
    """Transport approved slices and commit only validated domain artifacts."""

    def harness_capability_manifest(self: _HarnessApplication) -> JsonObject:
        return self.harness_adapter.capability_manifest().to_dict()

    def harness_disclosure_candidate(
        self: _HarnessApplication,
        investigation_id: str,
        *,
        operation: object = "start_task_run",
        instruction: object = None,
        artifact_kind: object = "plan",
        reason: object = None,
        command_id: object = None,
        expected_revision: object = None,
    ) -> JsonObject:
        investigation = self.investigation(investigation_id)
        _, user_id = self._current_context()
        operation_value = HarnessOperation(str(operation))
        artifact_kind_value = HarnessArtifactKind(str(artifact_kind))
        manifest = self.harness_adapter.capability_manifest()
        if not manifest.supports(operation_value):
            raise LabError(
                "harness_capability_unavailable",
                f"The installed harness does not support {operation_value.value}.",
                http_status=409,
            )
        if operation_value == HarnessOperation.START_TASK_RUN:
            instruction_value = str(investigation["question"])
        elif operation_value == HarnessOperation.REPLACE_TASK_BINDING:
            instruction_value = str(instruction or investigation["question"])
        elif operation_value == HarnessOperation.CANCEL_TASK_WORK:
            instruction_value = ""
        else:
            instruction_value = required_text(instruction, "instruction", 20_000)
        reason_value = None
        if operation_value in {
            HarnessOperation.CANCEL_TASK_WORK,
            HarnessOperation.REPLACE_TASK_BINDING,
        }:
            reason_value = required_text(reason, "reason", 2_000)
        binding = self.store.active_harness_binding(investigation_id)
        if operation_value == HarnessOperation.START_TASK_RUN and (
            artifact_kind_value != HarnessArtifactKind.PLAN
        ):
            raise LabError(
                "invalid_harness_artifact_flow",
                "A new investigation harness task must begin with a reviewable plan.",
                http_status=409,
            )
        accepted_plan_context: JsonObject | None = None
        if (
            operation_value != HarnessOperation.CANCEL_TASK_WORK
            and artifact_kind_value != HarnessArtifactKind.PLAN
        ):
            accepted = self._accepted_current_plan(investigation_id)
            accepted_plan_context = self._accepted_plan_transport_context(accepted)
            if operation_value != HarnessOperation.REPLACE_TASK_BINDING and not (
                binding
                and self._binding_matches_accepted_plan(binding, accepted_plan_context)
            ):
                raise LabError(
                    "harness_execution_task_required",
                    "Start the separately owned harness execution task for this adopted plan.",
                    http_status=409,
                )
        elif (
            artifact_kind_value == HarnessArtifactKind.PLAN
            and operation_value
            in {HarnessOperation.RESUME_TASK_RUN, HarnessOperation.SEND_TASK_MESSAGE}
            and binding
            and self._binding_accepted_plan_context(binding) is not None
        ):
            raise LabError(
                "harness_planning_task_required",
                "Plan changes require a fresh tool-free harness planning task.",
                http_status=409,
            )
        command_id_value = required_text(
            command_id or f"genomilab-command-{secrets.token_urlsafe(18)}",
            "command_id",
            200,
        )
        if operation_value == HarnessOperation.START_TASK_RUN:
            expected_revision_value = 0
        else:
            if binding is None:
                raise LabError(
                    "harness_binding_not_found",
                    "Start the installed harness for this investigation first.",
                    http_status=409,
                )
            try:
                expected_revision_value = int(
                    binding["harness_revision"]
                    if expected_revision is None
                    else expected_revision
                )
            except (TypeError, ValueError) as exc:
                raise LabError(
                    "invalid_harness_revision",
                    "The expected harness revision must be an integer.",
                ) from exc
        categories = ["local_user_identifier", "investigation_binding"]
        approved_context: JsonObject = {
            "investigation_id": investigation_id,
            "disease_scope": investigation.get("disease_scope"),
            "private_context_status": "not_approved",
            "capability_catalog": self.investigation_capability_catalog(
                investigation_id
            ),
        }
        if accepted_plan_context is not None:
            approved_context["accepted_plan"] = accepted_plan_context
            categories.append("accepted_investigation_plan")
        if operation_value != HarnessOperation.CANCEL_TASK_WORK:
            categories.append("investigation_question")
        if operation_value != HarnessOperation.CANCEL_TASK_WORK and investigation.get(
            "patient_molecular_snapshot_id"
        ):
            approved_context["molecular_profile"] = (
                self._approved_investigation_profile(investigation_id)
            )
            approved_context["private_context_status"] = "approved_snapshot"
            approved_context["private_context_authority"] = {
                "patient_molecular_snapshot_id": investigation[
                    "patient_molecular_snapshot_id"
                ],
                "consent_receipt_id": investigation["active_consent_receipt_id"],
            }
            categories.append("molecular_profile_slice")
        if investigation.get("current_evidence_records") or investigation.get(
            "current_hypotheses"
        ):
            approved_context["evidence_records"] = investigation.get(
                "current_evidence_records", []
            )
            approved_context["hypotheses"] = investigation.get("current_hypotheses", [])
            categories.append("investigation_evidence")
        transport_payload: JsonObject = {
            "operation": operation_value.value,
            "instruction": instruction_value,
            "artifact_kind": artifact_kind_value.value,
            "approved_context": approved_context,
            "command_context": {
                "workspace_session_id": self.session_id,
                "command_id": command_id_value,
                "user_id": user_id,
                "investigation_id": investigation_id,
                "task_id": binding.get("task_id") if binding else None,
                "run_id": binding.get("run_id") if binding else None,
                "expected_revision": expected_revision_value,
                "current_binding_revision": binding.get("harness_revision")
                if binding
                else None,
                "binding_status": binding.get("harness_status") if binding else None,
                "latest_event_cursor": self._latest_transport_cursor(investigation_id),
            },
        }
        if reason_value is not None:
            transport_payload["reason"] = reason_value
        from .approval_store import disclosure_payload_sha256

        return {
            "status": "approval_required",
            "investigation_id": investigation_id,
            "recipient_kind": "installed_harness",
            "recipient_id": manifest.adapter_id,
            "destination": manifest.execution_location,
            "data_categories": categories,
            "payload": transport_payload,
            "payload_sha256": disclosure_payload_sha256(transport_payload),
            "capability_manifest": manifest.to_dict(),
        }

    @staticmethod
    def _accepted_plan_transport_context(investigation: JsonObject) -> JsonObject:
        current = investigation.get("current_plan_version")
        if not isinstance(current, dict) or current.get("review_status") != "accepted":
            raise LabError(
                "plan_acceptance_required",
                "Review and accept the current harness plan before its capabilities run.",
                http_status=409,
            )
        plan = current.get("plan")
        acceptance = current.get("acceptance")
        if not isinstance(plan, dict) or not isinstance(acceptance, dict):
            raise LabError(
                "plan_acceptance_required",
                "The exact accepted harness plan is unavailable.",
                http_status=409,
            )
        return {
            "plan_version_id": current["plan_version_id"],
            "plan_sha256": current["plan_sha256"],
            "patient_molecular_snapshot_id": current.get(
                "patient_molecular_snapshot_id"
            ),
            "plan_acceptance_id": acceptance["plan_acceptance_id"],
            "accepted_at": acceptance["accepted_at"],
            "plan": plan,
        }

    def _binding_accepted_plan_context(
        self: _HarnessApplication, binding: JsonObject
    ) -> JsonObject | None:
        command = self.store.harness_command(str(binding.get("command_id") or ""))
        if not isinstance(command, dict):
            return None
        receipt_id = command.get("disclosure_receipt_id")
        if not isinstance(receipt_id, str) or not receipt_id:
            return None
        try:
            receipt = self.store.outbound_disclosure_receipt(receipt_id)
        except KeyError:
            return None
        payload = receipt.get("payload")
        approved_context = (
            payload.get("approved_context") if isinstance(payload, dict) else None
        )
        accepted_plan = (
            approved_context.get("accepted_plan")
            if isinstance(approved_context, dict)
            else None
        )
        return dict(accepted_plan) if isinstance(accepted_plan, dict) else None

    def _binding_matches_accepted_plan(
        self: _HarnessApplication,
        binding: JsonObject,
        accepted_plan: JsonObject,
    ) -> bool:
        bound = self._binding_accepted_plan_context(binding)
        return bool(
            isinstance(bound, dict)
            and bound.get("plan_version_id") == accepted_plan.get("plan_version_id")
            and bound.get("plan_sha256") == accepted_plan.get("plan_sha256")
        )

    def _start_harness_for_conformance(
        self: _HarnessApplication, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Exercise the lower-level adapter contract in internal tests only."""

        return self._execute_harness_command(
            investigation_id,
            payload,
            operation=HarnessOperation.START_TASK_RUN,
            artifact_kind=HarnessArtifactKind.PLAN,
        )

    def _resume_harness_for_conformance(
        self: _HarnessApplication, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Exercise the lower-level adapter contract in internal tests only."""

        artifact_kind = HarnessArtifactKind(
            str(payload.get("artifact_kind") or HarnessArtifactKind.PLAN.value)
        )
        return self._execute_harness_command(
            investigation_id,
            payload,
            operation=HarnessOperation.RESUME_TASK_RUN,
            artifact_kind=artifact_kind,
        )

    def _send_harness_message_for_conformance(
        self: _HarnessApplication, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Exercise the lower-level adapter contract in internal tests only."""

        artifact_kind = HarnessArtifactKind(
            str(payload.get("artifact_kind") or HarnessArtifactKind.BRIEF_DRAFT.value)
        )
        return self._execute_harness_command(
            investigation_id,
            payload,
            operation=HarnessOperation.SEND_TASK_MESSAGE,
            artifact_kind=artifact_kind,
        )

    def _replace_harness_for_conformance(
        self: _HarnessApplication, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Exercise the lower-level adapter contract in internal tests only."""

        artifact_kind = HarnessArtifactKind(
            str(payload.get("artifact_kind") or HarnessArtifactKind.PLAN.value)
        )
        return self._execute_harness_command(
            investigation_id,
            payload,
            operation=HarnessOperation.REPLACE_TASK_BINDING,
            artifact_kind=artifact_kind,
        )

    def _cancel_harness_for_conformance(
        self: _HarnessApplication, investigation_id: str, payload: JsonObject
    ) -> JsonObject:
        """Exercise the lower-level adapter contract in internal tests only."""

        return self._execute_harness_command(
            investigation_id,
            payload,
            operation=HarnessOperation.CANCEL_TASK_WORK,
            artifact_kind=HarnessArtifactKind.PLAN,
        )

    def _execute_harness_command(
        self: _HarnessApplication,
        investigation_id: str,
        request: JsonObject,
        *,
        operation: HarnessOperation,
        artifact_kind: HarnessArtifactKind,
        authorization_receipt_id: str | None = None,
    ) -> JsonObject:
        # The HTTP server is threaded.  Serializing the claim/call/terminal
        # write boundary prevents a concurrent retry in this process from
        # mistaking a live dispatch for an interrupted one.
        with self._operation_lock:
            return self._execute_harness_command_locked(
                investigation_id,
                request,
                operation=operation,
                artifact_kind=artifact_kind,
                authorization_receipt_id=authorization_receipt_id,
            )

    def _execute_harness_command_locked(
        self: _HarnessApplication,
        investigation_id: str,
        request: JsonObject,
        *,
        operation: HarnessOperation,
        artifact_kind: HarnessArtifactKind,
        authorization_receipt_id: str | None = None,
    ) -> JsonObject:
        _, user_id = self._current_context()
        investigation = self.investigation(investigation_id)
        command_id = required_text(request.get("command_id"), "command_id", 200)
        approved_hash = required_text(
            request.get("payload_sha256"), "payload_sha256", 128
        )
        existing = self.store.harness_command(command_id)
        if existing is not None:
            same_domain_command = (
                existing.get("investigation_id") == investigation_id
                and existing.get("user_id") == user_id
            )
            if same_domain_command and existing.get("command_state") == "dispatching":
                active_job = self.store.harness_job_for_command(command_id)
                if active_job is not None and active_job.get("job_state") in {
                    HarnessJobState.QUEUED.value,
                    HarnessJobState.RUNNING.value,
                }:
                    live_job = self.harness_adapter.background_job(
                        str(active_job["job_id"])
                    )
                    if live_job is None:
                        return self._reconcile_unowned_harness_job(existing, active_job)
                    if live_job.state in {
                        HarnessJobState.COMPLETED,
                        HarnessJobState.CANCELLED,
                        HarnessJobState.FAILED,
                    }:
                        recovered = self.harness_adapter.retry_background_completion(
                            str(active_job["job_id"])
                        )
                        if recovered is None:
                            return self._reconcile_unowned_harness_job(
                                existing, active_job
                            )
                        refreshed_command = self.store.harness_command(command_id)
                        if isinstance(refreshed_command, dict) and isinstance(
                            refreshed_command.get("response"), dict
                        ):
                            return dict(refreshed_command["response"])
                        refreshed_job = self.store.harness_job(
                            str(active_job["job_id"])
                        )
                        if not isinstance(refreshed_job, dict):
                            raise RuntimeError(
                                "durable harness job disappeared during completion recovery"
                            )
                        return self._reconcile_unacknowledged_terminal_harness_job(
                            existing, refreshed_job
                        )
                    return self._background_job_response(existing, active_job)
                saved_operation = HarnessOperation(str(existing["operation"]))
                existing = self.store.reconcile_interrupted_harness_command(
                    command_id,
                    self._interrupted_dispatch_response(
                        command_id=command_id,
                        operation=saved_operation,
                        disclosure_receipt_id=existing.get("disclosure_receipt_id"),
                        binding=self.store.active_harness_binding(investigation_id),
                    ),
                )
            expected = {
                "investigation_id": investigation_id,
                "workspace_session_id": self.session_id,
                "user_id": user_id,
                "operation": operation.value,
                "command_fingerprint": approved_hash,
            }
            if any(existing.get(key) != value for key, value in expected.items()):
                raise LabError(
                    "harness_command_id_collision",
                    "This harness command identifier was already used for different work.",
                    http_status=409,
                )
            if isinstance(existing.get("response"), dict):
                return dict(existing["response"])
        instruction = request.get("instruction") or request.get("message")
        candidate = self.harness_disclosure_candidate(
            investigation_id,
            operation=operation.value,
            instruction=instruction,
            artifact_kind=artifact_kind.value,
            reason=request.get("reason"),
            command_id=command_id,
            expected_revision=request.get("expected_revision"),
        )
        if authorization_receipt_id is None and request.get("approved") is not True:
            raise LabError(
                "outbound_disclosure_approval_required",
                "Review and approve the exact harness disclosure first.",
                http_status=409,
            )
        if request.get("payload_sha256") != candidate["payload_sha256"]:
            raise LabError(
                "outbound_disclosure_changed",
                "The harness payload changed after preview; review it again.",
                http_status=409,
            )
        record = self.store.begin_harness_command(
            command_id=command_id,
            investigation_id=investigation_id,
            workspace_session_id=self.session_id,
            user_id=user_id,
            operation=operation.value,
            command_fingerprint=approved_hash,
        )
        if record.get("duplicate") and isinstance(record.get("response"), dict):
            return dict(record["response"])
        receipt_id = record.get("disclosure_receipt_id")
        if not receipt_id:
            receipt = self.store.create_outbound_disclosure_receipt(
                user_id,
                workspace_session_id=self.session_id,
                investigation_id=investigation_id,
                recipient_kind="installed_harness",
                recipient_id=candidate["recipient_id"],
                purpose=f"{operation.value} for disease investigation",
                destination=candidate["destination"],
                data_categories=candidate["data_categories"],
                payload=candidate["payload"],
                policy_versions={"harness_protocol": "genomilab.harness.v1"},
                approved=True,
            )
            receipt_id = str(receipt["disclosure_receipt_id"])
            self.store.attach_harness_command_disclosure(command_id, receipt_id)
        self.store.require_outbound_disclosure(
            str(receipt_id),
            workspace_session_id=self.session_id,
            user_id=user_id,
            investigation_id=investigation_id,
            recipient_kind="installed_harness",
            recipient_id=str(candidate["recipient_id"]),
            purpose=f"{operation.value} for disease investigation",
            destination=str(candidate["destination"]),
            data_categories=list(candidate["data_categories"]),
            payload=candidate["payload"],
            policy_versions={"harness_protocol": "genomilab.harness.v1"},
        )
        if authorization_receipt_id is not None:
            from .authorization_store import (
                AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
            )

            self.store.derive_investigation_authorization_subject(
                authorization_receipt_id,
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=str(receipt_id),
            )
            self.store.require_investigation_authorization_subject(
                authorization_receipt_id,
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=str(receipt_id),
            )
        binding = self.store.active_harness_binding(investigation_id)
        approved_context = candidate["payload"]["approved_context"]
        command_context = candidate["payload"]["command_context"]
        if operation == HarnessOperation.START_TASK_RUN:
            if binding is not None:
                raise LabError(
                    "harness_binding_conflict",
                    "Resume or replace the existing harness task.",
                    http_status=409,
                )
            command_payload = StartTaskRunPayload(
                str(investigation["question"]), approved_context
            )
            expected_revision = int(command_context["expected_revision"])
            task_id = None
            run_id = None
            binding_status = None
            latest_event_cursor = None
            current_binding_revision = None
        else:
            if binding is None:
                raise LabError(
                    "harness_binding_not_found",
                    "Start the installed harness for this investigation first.",
                    http_status=409,
                )
            expected_revision = int(command_context["expected_revision"])
            task_id = str(binding["task_id"])
            run_id = binding.get("run_id")
            binding_status = BindingStatus(str(binding["harness_status"]))
            latest_event_cursor = int(command_context["latest_event_cursor"])
            current_binding_revision = int(binding["harness_revision"])
            instruction_value = str(candidate["payload"]["instruction"])
            if operation == HarnessOperation.RESUME_TASK_RUN:
                command_payload = ResumeTaskRunPayload(
                    instruction_value, approved_context, artifact_kind
                )
            elif operation == HarnessOperation.SEND_TASK_MESSAGE:
                command_payload = SendTaskMessagePayload(
                    instruction_value, approved_context, artifact_kind
                )
            elif operation == HarnessOperation.REPLACE_TASK_BINDING:
                command_payload = ReplaceTaskBindingPayload(
                    str(candidate["payload"]["reason"]),
                    instruction_value,
                    approved_context,
                    artifact_kind,
                )
            else:
                command_payload = CancelTaskWorkPayload(
                    str(candidate["payload"]["reason"])
                )
        command = HarnessCommand(
            operation=operation,
            workspace_session_id=self.session_id,
            command_id=command_id,
            user_id=user_id,
            investigation_id=investigation_id,
            task_id=task_id,
            run_id=run_id,
            binding_status=binding_status,
            latest_event_cursor=latest_event_cursor,
            current_binding_revision=current_binding_revision,
            expected_revision=expected_revision,
            payload=command_payload,
        )
        self.store.claim_harness_command_dispatch(command_id)
        if (
            operation != HarnessOperation.CANCEL_TASK_WORK
            and self.harness_adapter.manifest.background_job_attach
        ):
            return self._dispatch_harness_background(
                command,
                receipt_id=receipt_id,
                existing_binding=binding,
            )
        try:
            response = {
                HarnessOperation.START_TASK_RUN: self.harness_adapter.start_task_run,
                HarnessOperation.RESUME_TASK_RUN: self.harness_adapter.resume_task_run,
                HarnessOperation.SEND_TASK_MESSAGE: self.harness_adapter.send_task_message,
                HarnessOperation.REPLACE_TASK_BINDING: self.harness_adapter.replace_task_binding,
                HarnessOperation.CANCEL_TASK_WORK: self.harness_adapter.cancel_task_work,
            }[operation](command)
        except Exception:
            interrupted = self._interrupted_dispatch_response(
                command_id=command_id,
                operation=operation,
                disclosure_receipt_id=receipt_id,
                binding=binding,
            )
            reconciled = self.store.reconcile_interrupted_harness_command(
                command_id, interrupted
            )
            saved_response = reconciled.get("response")
            return (
                dict(saved_response)
                if isinstance(saved_response, dict)
                else interrupted
            )
        try:
            self._require_current_harness_completion_authorization(
                command,
                receipt_id=str(receipt_id),
            )
        except Exception:
            with self.store.atomic_write():
                rejected = {
                    "status": "harness_result_rejected_context_inactive",
                    "command_id": command_id,
                    "operation": operation.value,
                    "retry_safe": False,
                    "message": (
                        "Harness work ended after its approved plan, private context, "
                        "disclosure, user, or session became inactive. No returned artifact "
                        "or capability side effect was committed."
                    ),
                    "binding": self.store.active_harness_binding(investigation_id),
                    "events": self._commit_pending_harness_events(investigation_id),
                    "committed_artifact": None,
                    "capability_results": [],
                    "artifact_error": "completion authorization is inactive",
                    "disclosure_receipt_id": receipt_id,
                }
                self.store.complete_harness_command(
                    command_id, rejected, succeeded=False
                )
            return rejected
        try:
            replay = self.harness_adapter.replay_events(
                command.investigation_id,
                after_cursor=self._latest_transport_cursor(command.investigation_id),
            )
            with self.store.atomic_write():
                committed = self._commit_harness_response(
                    command, response, binding=binding, replay=replay
                )
                committed["disclosure_receipt_id"] = receipt_id
                committed["command_id"] = command_id
                self.store.complete_harness_command(
                    command_id,
                    committed,
                    succeeded=committed["status"] in {"accepted", "artifact_rejected"},
                )
        except Exception:
            interrupted = self._interrupted_dispatch_response(
                command_id=command_id,
                operation=operation,
                disclosure_receipt_id=receipt_id,
                binding=self.store.active_harness_binding(investigation_id),
                dispatch_outcome="response_received_commit_incomplete",
            )
            reconciled = self.store.reconcile_interrupted_harness_command(
                command_id, interrupted
            )
            saved_response = reconciled.get("response")
            return (
                dict(saved_response)
                if isinstance(saved_response, dict)
                else interrupted
            )
        return committed

    @staticmethod
    def _interrupted_dispatch_response(
        *,
        command_id: str,
        operation: HarnessOperation,
        disclosure_receipt_id: object,
        binding: JsonObject | None,
        dispatch_outcome: str = "unknown",
    ) -> JsonObject:
        return {
            "status": "harness_dispatch_outcome_unknown",
            "command_id": command_id,
            "operation": operation.value,
            "dispatch_outcome": dispatch_outcome,
            "retry_safe": False,
            "requires_manual_reconciliation": True,
            "message": (
                "The harness call was interrupted after dispatch began. "
                "GenomiLab did not dispatch this command again. Check the installed "
                "harness before explicitly starting replacement work."
            ),
            "disclosure_receipt_id": disclosure_receipt_id,
            "binding": binding,
            "events": [],
            "committed_artifact": None,
            "artifact_error": None,
        }

    def _commit_harness_response(
        self: _HarnessApplication,
        command: HarnessCommand,
        response: Any,
        *,
        binding: JsonObject | None,
        replay: EventReplay | None = None,
    ) -> JsonObject:
        response_payload = response.to_dict()
        if not response.ok:
            error = response_payload.get("error") or {}
            return {
                "status": error.get("code", "harness_error"),
                "harness_response": response_payload,
            }
        result = response.result
        if result is None:
            raise LabError(
                "invalid_harness_response",
                "The installed harness returned no result.",
                http_status=500,
            )
        result_payload = result.to_dict()
        artifact = result_payload.get("proposed_artifact")
        reference = result_payload.get("proposed_artifact_reference") or {}
        attested_capability_executions: dict[str, JsonObject] | None = None
        if isinstance(artifact, dict):
            try:
                if reference.get("kind") == HarnessArtifactKind.PLAN.value:
                    self.store.validate_plan(command.investigation_id, artifact)
                    self.validate_harness_capability_plan(
                        command.investigation_id, artifact
                    )
                elif (
                    reference.get("kind") == HarnessArtifactKind.EXECUTION_REPORT.value
                ):
                    validate_research_narrative(
                        artifact.get("summary"),
                        "execution report summary",
                        kind="execution_summary",
                    )
                    current = self.store.get_investigation(command.investigation_id)
                    current_plan = current.get("current_plan_version")
                    if (
                        not isinstance(current_plan, dict)
                        or current_plan.get("review_status") != "accepted"
                    ):
                        raise ValueError(
                            "an execution report requires the patient's accepted current plan"
                        )
                    attested_capability_executions = (
                        self._attest_execution_report_to_capability_ledger(
                            command.investigation_id,
                            investigation=current,
                            current_plan=current_plan,
                            artifact=artifact,
                        )
                    )
                elif reference.get("kind") == HarnessArtifactKind.BRIEF_DRAFT.value:
                    current = self.store.get_investigation(command.investigation_id)
                    current_plan = current.get("current_plan_version")
                    if (
                        not isinstance(current_plan, dict)
                        or current_plan.get("review_status") != "accepted"
                    ):
                        raise ValueError(
                            "a brief requires the patient's accepted current plan"
                        )
                    self.store.validate_brief(command.investigation_id, artifact)
                else:
                    raise ValueError("the harness proposed an unknown artifact kind")
            except (KeyError, ValueError) as exc:
                return {
                    "status": "artifact_rejected",
                    "harness_response": response_payload,
                    "binding": binding,
                    "events": [],
                    "committed_artifact": None,
                    "artifact_error": str(exc),
                }
        if command.operation == HarnessOperation.CANCEL_TASK_WORK:
            if binding is None:
                raise LabError(
                    "harness_binding_not_found",
                    "This investigation has no active harness work.",
                    http_status=409,
                )
            outcome = CancellationOutcome(str(result_payload.get("outcome")))
            if outcome == CancellationOutcome.CANCELLED:
                harness_status = BindingStatus.CANCELLED.value
            elif outcome == CancellationOutcome.ALREADY_COMPLETED:
                harness_status = BindingStatus.COMPLETED.value
            elif outcome == CancellationOutcome.FAILED:
                harness_status = BindingStatus.FAILED.value
            else:
                harness_status = str(binding["harness_status"])
            binding = self.store.update_harness_binding(
                str(binding["binding_id"]),
                task_id=result_payload.get("task_id"),
                run_id=result_payload.get("run_id"),
                harness_status=harness_status,
                harness_revision=response.current_revision,
            )
        elif (
            binding is None
            or command.operation == HarnessOperation.REPLACE_TASK_BINDING
        ):
            binding = self.store.bind_harness_task(
                command.investigation_id,
                command_id=command.command_id,
                host_id=self.harness_adapter.manifest.adapter_id,
                task_id=result_payload.get("task_id"),
                run_id=result_payload.get("run_id"),
                harness_status=result_payload.get("binding_status", "waiting"),
                harness_revision=response.current_revision,
            )
        else:
            binding = self.store.update_harness_binding(
                str(binding["binding_id"]),
                task_id=result_payload.get("task_id"),
                run_id=result_payload.get("run_id"),
                harness_status=result_payload.get("binding_status", "waiting"),
                harness_revision=response.current_revision,
            )
        if replay is None:
            replay = self.harness_adapter.replay_events(
                command.investigation_id,
                after_cursor=self._latest_transport_cursor(command.investigation_id),
            )
        committed_events: list[JsonObject] = []
        if replay.status == ReplayStatus.EVENTS:
            for event in replay.events:
                committed_events.append(
                    self.store.commit_harness_event(
                        command.investigation_id,
                        str(binding["binding_id"]),
                        event_id=event.event_id,
                        event_type=event.kind.value,
                        payload=self._persistable_harness_event(event),
                    )
                )
        committed_artifact: JsonObject | None = None
        capability_results: list[JsonObject] = []
        if isinstance(artifact, dict):
            if reference.get("kind") == HarnessArtifactKind.PLAN.value:
                committed_artifact = self.store.commit_plan(
                    command.investigation_id, artifact
                )
                self.store.set_investigation_status(
                    command.investigation_id, "awaiting_plan_review"
                )
            elif reference.get("kind") == HarnessArtifactKind.BRIEF_DRAFT.value:
                committed_artifact = self.store.commit_brief(
                    command.investigation_id, artifact
                )
            else:
                committed_artifact = {
                    "kind": HarnessArtifactKind.EXECUTION_REPORT.value,
                    "report": artifact,
                }
                if attested_capability_executions is None:
                    raise RuntimeError(
                        "execution report reached commit without capability attestation"
                    )
                for request_id, execution in attested_capability_executions.items():
                    capability_results.append(
                        {
                            "request_id": request_id,
                            "capability": execution.get("capability"),
                            "result": self._persisted_capability_result(execution),
                        }
                    )
                if any(
                    item.get("status") == "approval_required"
                    for item in artifact.get("request_results") or []
                    if isinstance(item, dict)
                ):
                    self.store.set_investigation_status(
                        command.investigation_id, "needs_user_input"
                    )
                else:
                    self.store.set_investigation_status(
                        command.investigation_id, "running"
                    )
        elif command.operation == HarnessOperation.CANCEL_TASK_WORK:
            outcome = CancellationOutcome(str(result_payload.get("outcome")))
            if outcome == CancellationOutcome.CANCELLED:
                self.store.set_investigation_status(
                    command.investigation_id, "cancelled"
                )
        return {
            "status": "accepted",
            "harness_response": response_payload,
            "binding": binding,
            "events": committed_events,
            "committed_artifact": committed_artifact,
            "capability_results": capability_results,
            "artifact_error": None,
        }
