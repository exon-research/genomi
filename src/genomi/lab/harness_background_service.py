"""Background harness submission, ownership, and completion coordination."""

from __future__ import annotations

import threading
from typing import Any

from .harness import (
    BindingStatus,
    HarnessCommand,
    HarnessJobIdentity,
    HarnessJobState,
    HarnessOperation,
)
from .harness_application_contract import HarnessApplication
from .models import JsonObject


class HarnessBackgroundApplicationMixin:
    """Coordinate durable background jobs and fail-closed completion."""

    def _background_job_response(
        self: HarnessApplication,
        command: JsonObject,
        job: JsonObject,
    ) -> JsonObject:
        investigation_id = str(command["investigation_id"])
        return {
            "status": "in_progress",
            "command_id": command["command_id"],
            "operation": command["operation"],
            "job_id": job["job_id"],
            "task_id": job.get("task_id"),
            "run_id": job.get("run_id"),
            "job_state": job["job_state"],
            "attach": {
                "events_after_sequence": self._latest_domain_event_sequence(
                    investigation_id
                )
            },
            "disclosure_receipt_id": command.get("disclosure_receipt_id"),
        }

    def _reconcile_unowned_harness_job(
        self: HarnessApplication,
        command: JsonObject,
        job: JsonObject,
    ) -> JsonObject:
        """Fail closed when this adapter cannot truthfully reattach a durable job."""

        investigation_id = str(command["investigation_id"])
        with self.store.atomic_write():
            binding = self.store.active_harness_binding(investigation_id)
            if (
                isinstance(binding, dict)
                and job.get("task_id")
                and job.get("run_id")
                and binding.get("task_id") == job.get("task_id")
                and binding.get("run_id") == job.get("run_id")
            ):
                binding = self.store.update_harness_binding(
                    str(binding["binding_id"]),
                    task_id=binding["task_id"],
                    run_id=binding["run_id"],
                    harness_status=BindingStatus.FAILED.value,
                    harness_revision=int(binding["harness_revision"]),
                )
            response = {
                "status": "harness_job_recovery_failed",
                "command_id": command["command_id"],
                "operation": command["operation"],
                "job_id": job["job_id"],
                "retry_safe": False,
                "requires_explicit_replacement": True,
                "message": (
                    "The installed harness no longer owns this saved background turn, "
                    "so GenomiLab cannot truthfully attach, poll, or redispatch it. "
                    "Start explicitly approved replacement work to continue."
                ),
                "binding": binding,
                "events": self._commit_pending_harness_events(investigation_id),
                "committed_artifact": None,
                "capability_results": [],
                "artifact_error": "installed harness background ownership was lost",
                "disclosure_receipt_id": command.get("disclosure_receipt_id"),
            }
            self.store.complete_harness_command(
                str(command["command_id"]), response, succeeded=False
            )
            self.store.complete_harness_job(
                str(job["job_id"]),
                job_state=HarnessJobState.FAILED.value,
                response=response,
            )
        return response

    def _reconcile_unacknowledged_terminal_harness_job(
        self: HarnessApplication,
        command: JsonObject,
        job: JsonObject,
    ) -> JsonObject:
        """Terminalize an owned turn whose adapter cannot acknowledge persistence."""

        with self.store.atomic_write():
            saved_command = self.store.harness_command(str(command["command_id"]))
            saved_job = self.store.harness_job(str(job["job_id"]))
            if not isinstance(saved_command, dict) or not isinstance(saved_job, dict):
                raise ValueError("harness completion records disappeared")
            if saved_command.get("response") is not None:
                return dict(saved_command["response"])
            binding = self.store.active_harness_binding(
                str(command["investigation_id"])
            )
            if (
                isinstance(binding, dict)
                and saved_job.get("task_id")
                and saved_job.get("run_id")
                and binding.get("task_id") == saved_job.get("task_id")
                and binding.get("run_id") == saved_job.get("run_id")
            ):
                binding = self.store.update_harness_binding(
                    str(binding["binding_id"]),
                    task_id=binding["task_id"],
                    run_id=binding["run_id"],
                    harness_status=BindingStatus.FAILED.value,
                    harness_revision=int(binding["harness_revision"]),
                )
            response = {
                "status": "harness_job_completion_unacknowledged",
                "command_id": command["command_id"],
                "operation": command["operation"],
                "job_id": job["job_id"],
                "retry_safe": False,
                "requires_explicit_replacement": True,
                "message": (
                    "The installed harness turn ended, but its result could not be "
                    "durably acknowledged. GenomiLab did not run the turn again and "
                    "did not commit its returned artifact."
                ),
                "binding": binding,
                "events": [],
                "committed_artifact": None,
                "capability_results": [],
                "artifact_error": "durable harness completion was not acknowledged",
                "disclosure_receipt_id": command.get("disclosure_receipt_id"),
            }
            self.store.complete_harness_command(
                str(command["command_id"]), response, succeeded=False
            )
            self.store.complete_harness_job(
                str(job["job_id"]),
                job_state=HarnessJobState.FAILED.value,
                response=response,
            )
        return response

    def _dispatch_harness_background(
        self: HarnessApplication,
        command: HarnessCommand,
        *,
        receipt_id: object,
        existing_binding: JsonObject | None,
    ) -> JsonObject:
        completion_lock = threading.Lock()

        def persist_submission(submission: Any) -> None:
            def persist_current_submission() -> None:
                if getattr(self, "_closed", False):
                    raise ValueError("workspace session is closed")
                _, current_user_id = self._current_context()
                if current_user_id != command.user_id:
                    raise ValueError(
                        "harness submission is not bound to the current Genomi user"
                    )
                self.store.begin_harness_job(
                    job_id=submission.job_id,
                    command_id=command.command_id,
                    investigation_id=command.investigation_id,
                    user_id=command.user_id,
                    host_id=self.harness_adapter.manifest.adapter_id,
                )

            self._run_current_user_operation(persist_current_submission)

        def bind_identity(identity: HarnessJobIdentity) -> None:
            def commit_identity() -> None:
                if getattr(self, "_closed", False):
                    raise ValueError("workspace session is closed")
                _, current_user_id = self._current_context()
                if current_user_id != command.user_id:
                    raise ValueError(
                        "harness identity is not bound to the current Genomi user"
                    )
                with self._operation_lock, completion_lock:
                    try:
                        self.store.attach_and_bind_harness_job_identity(
                            job_id=identity.job_id,
                            command_id=command.command_id,
                            investigation_id=command.investigation_id,
                            user_id=command.user_id,
                            host_id=self.harness_adapter.manifest.adapter_id,
                            operation=command.operation.value,
                            expected_revision=command.expected_revision,
                            prior_task_id=command.task_id,
                            prior_run_id=command.run_id,
                            task_id=identity.task_id,
                            run_id=identity.run_id,
                        )
                    except ValueError as exc:
                        rejected = {
                            "status": "harness_identity_rejected_stale",
                            "command_id": command.command_id,
                            "operation": command.operation.value,
                            "job_id": identity.job_id,
                            "retry_safe": False,
                            "message": (
                                "The installed harness identity arrived after newer "
                                "approved work. It was not allowed to replace the current task."
                            ),
                            "binding": None,
                            "events": [],
                            "committed_artifact": None,
                            "capability_results": [],
                            "artifact_error": "harness identity was superseded",
                        }
                        self.store.reject_harness_job_identity(
                            job_id=identity.job_id,
                            command_id=command.command_id,
                            investigation_id=command.investigation_id,
                            user_id=command.user_id,
                            response=rejected,
                        )
                        raise ValueError(
                            "harness identity callback was superseded"
                        ) from exc
                    self._commit_pending_harness_events(command.investigation_id)

            self._run_current_user_operation(commit_identity)

        def complete(job_id: str, job_state: HarnessJobState, response: Any) -> None:
            committed_for_continuation: JsonObject | None = None

            def commit_current_result() -> None:
                nonlocal committed_for_continuation
                if getattr(self, "_closed", False):
                    raise ValueError("workspace session is closed")
                _, current_user_id = self._current_context()
                if current_user_id != command.user_id:
                    raise ValueError(
                        "harness completion is not bound to the current Genomi user"
                    )
                with self._operation_lock, completion_lock:
                    binding = self.store.active_harness_binding(
                        command.investigation_id
                    )
                    self._require_current_harness_completion_authorization(
                        command,
                        receipt_id=str(receipt_id),
                    )
                    if job_state == HarnessJobState.CANCELLED:
                        with self.store.atomic_write():
                            cancelled = {
                                "status": "cancelled",
                                "command_id": command.command_id,
                                "operation": command.operation.value,
                                "job_id": job_id,
                                "message": (
                                    "The installed harness confirmed that its turn was "
                                    "interrupted. No proposed artifact or capability side "
                                    "effect was committed."
                                ),
                                "binding": binding,
                                "events": self._commit_pending_harness_events(
                                    command.investigation_id
                                ),
                                "committed_artifact": None,
                                "capability_results": [],
                                "artifact_error": None,
                            }
                            self.store.complete_harness_command(
                                command.command_id, cancelled, succeeded=True
                            )
                            self.store.complete_harness_job(
                                job_id,
                                job_state=HarnessJobState.CANCELLED.value,
                                response=cancelled,
                            )
                        return

                    replay = self.harness_adapter.replay_events(
                        command.investigation_id,
                        after_cursor=self._latest_transport_cursor(
                            command.investigation_id
                        ),
                    )
                    with self.store.atomic_write():
                        committed = self._commit_harness_response(
                            command, response, binding=binding, replay=replay
                        )
                        committed["disclosure_receipt_id"] = receipt_id
                        committed["command_id"] = command.command_id
                        state = (
                            job_state.value
                            if committed["status"] in {"accepted", "artifact_rejected"}
                            else HarnessJobState.FAILED.value
                        )
                        self.store.complete_harness_command(
                            command.command_id,
                            committed,
                            succeeded=committed["status"]
                            in {"accepted", "artifact_rejected"},
                        )
                        self.store.complete_harness_job(
                            job_id, job_state=state, response=committed
                        )
                        committed_for_continuation = dict(committed)

            try:
                # The host owns this callback thread, so it must explicitly enter
                # the same current-user epoch as an ordinary application request.
                # The guard stays live through artifact and terminal-state commits.
                self._run_current_user_operation(commit_current_result)
            except Exception:
                self._fail_closed_background_completion(
                    command,
                    job_id=job_id,
                    completion_lock=completion_lock,
                )
            self._require_durable_background_completion(
                command,
                job_id=job_id,
            )
            if committed_for_continuation is not None:
                self._continue_authorized_harness_flow(
                    command,
                    committed_for_continuation,
                    receipt_id=str(receipt_id),
                )

        try:
            submission = self.harness_adapter.dispatch_background(
                command,
                submission_callback=persist_submission,
                identity_callback=bind_identity,
                completion_callback=complete,
            )
            job = self.store.harness_job(submission.job_id)
            if job is None:
                raise ValueError("background harness job was not durably claimed")
        except Exception:
            interrupted = self._interrupted_dispatch_response(
                command_id=command.command_id,
                operation=command.operation,
                disclosure_receipt_id=receipt_id,
                binding=existing_binding,
            )
            with self.store.atomic_write():
                job = self.store.harness_job_for_command(command.command_id)
                reconciled = self.store.reconcile_interrupted_harness_command(
                    command.command_id, interrupted
                )
                saved_response = reconciled.get("response")
                if not isinstance(saved_response, dict):
                    saved_response = interrupted
                if job is not None and job.get("terminal_response") is None:
                    succeeded = saved_response.get("status") in {
                        "accepted",
                        "artifact_rejected",
                    }
                    self.store.complete_harness_job(
                        str(job["job_id"]),
                        job_state=(
                            HarnessJobState.COMPLETED.value
                            if succeeded
                            else HarnessJobState.FAILED.value
                        ),
                        response=saved_response,
                    )
            return saved_response
        return {
            "status": "in_progress",
            "command_id": command.command_id,
            "operation": command.operation.value,
            "job_id": submission.job_id,
            "task_id": submission.task_id,
            "run_id": submission.run_id,
            "job_state": job["job_state"],
            "attach": {
                "events_after_sequence": self._latest_domain_event_sequence(
                    command.investigation_id
                )
            },
            "disclosure_receipt_id": receipt_id,
        }

    def _require_durable_background_completion(
        self: HarnessApplication,
        command: HarnessCommand,
        *,
        job_id: str,
    ) -> None:
        """Acknowledge only an exact, mutually consistent terminal command/job."""

        if not self.store.harness_completion_is_durable(
            job_id=job_id,
            command_id=command.command_id,
            investigation_id=command.investigation_id,
            workspace_session_id=command.workspace_session_id,
            user_id=command.user_id,
            operation=command.operation.value,
        ):
            raise RuntimeError(
                "harness background completion was not durably acknowledged"
            )

    def _fail_closed_background_completion(
        self: HarnessApplication,
        command: HarnessCommand,
        *,
        job_id: str,
        completion_lock: threading.Lock,
    ) -> None:
        """Terminally reject an old callback without reading patient artifacts.

        A user switch intentionally makes the normal patient authority guard
        unavailable to the old command.  This narrow administrative transition
        therefore uses only the already-bound command/job identifiers, writes a
        generic payload, and never commits or returns a harness artifact, event,
        capability result, profile value, or active binding.
        """

        rejected = {
            "status": "harness_result_rejected_context_inactive",
            "command_id": command.command_id,
            "operation": command.operation.value,
            "job_id": job_id,
            "retry_safe": False,
            "message": (
                "Harness work ended after its approved private context or session "
                "became inactive. No returned artifact or capability side effect "
                "was committed."
            ),
            "binding": None,
            "events": [],
            "committed_artifact": None,
            "capability_results": [],
            "artifact_error": "completion authorization is inactive",
        }
        with self._operation_lock, completion_lock, self.store.atomic_write():
            saved_command = self.store.harness_command(command.command_id)
            saved_job = self.store.harness_job(job_id)
            exact_command = bool(
                isinstance(saved_command, dict)
                and saved_command.get("investigation_id") == command.investigation_id
                and saved_command.get("workspace_session_id")
                == command.workspace_session_id
                and saved_command.get("user_id") == command.user_id
                and saved_command.get("operation") == command.operation.value
            )
            exact_job = bool(
                isinstance(saved_job, dict)
                and saved_job.get("command_id") == command.command_id
                and saved_job.get("investigation_id") == command.investigation_id
                and saved_job.get("user_id") == command.user_id
            )
            if not exact_command or not exact_job:
                return
            if saved_command.get("response") is None:
                self.store.complete_harness_command(
                    command.command_id, rejected, succeeded=False
                )
            if saved_job.get("terminal_response") is None:
                self.store.complete_harness_job(
                    job_id,
                    job_state=HarnessJobState.FAILED.value,
                    response=rejected,
                )

    def _require_current_harness_completion_authorization(
        self: HarnessApplication,
        command: HarnessCommand,
        *,
        receipt_id: str,
    ) -> None:
        """Revalidate every mutable authority immediately before domain commit."""

        if getattr(self, "_closed", False):
            raise ValueError("workspace session is closed")
        _, current_user_id = self._current_context()
        if current_user_id != command.user_id:
            raise ValueError("current Genomi user changed")
        investigation = self.investigation(command.investigation_id)
        saved_command = self.store.harness_command(command.command_id)
        if (
            saved_command is None
            or saved_command.get("disclosure_receipt_id") != receipt_id
            or saved_command.get("command_state") != "dispatching"
            or saved_command.get("workspace_session_id") != command.workspace_session_id
            or saved_command.get("user_id") != command.user_id
            or saved_command.get("operation") != command.operation.value
        ):
            raise ValueError("harness command or disclosure binding changed")
        binding = self.store.active_harness_binding(command.investigation_id)
        job = self.store.harness_job_for_command(command.command_id)
        if isinstance(job, dict):
            if (
                job.get("job_state")
                not in {
                    HarnessJobState.QUEUED.value,
                    HarnessJobState.RUNNING.value,
                }
                or job.get("user_id") != command.user_id
                or job.get("host_id") != self.harness_adapter.manifest.adapter_id
                or not job.get("task_id")
                or not job.get("run_id")
                or not isinstance(binding, dict)
                or binding.get("task_id") != job.get("task_id")
                or binding.get("run_id") != job.get("run_id")
                or (
                    command.operation
                    in {
                        HarnessOperation.START_TASK_RUN,
                        HarnessOperation.REPLACE_TASK_BINDING,
                    }
                    and binding.get("command_id") != command.command_id
                )
            ):
                raise ValueError(
                    "harness background completion lost its exact active task binding"
                )
        elif command.operation == HarnessOperation.START_TASK_RUN:
            if binding is not None:
                raise ValueError(
                    "foreground harness start no longer owns an unbound investigation"
                )
        elif command.operation == HarnessOperation.REPLACE_TASK_BINDING:
            if not isinstance(binding, dict):
                raise ValueError("foreground harness replacement lost its binding")
            replacement_already_bound = binding.get("command_id") == command.command_id
            prior_binding_is_current = (
                binding.get("task_id") == command.task_id
                and binding.get("run_id") == command.run_id
                and binding.get("harness_revision") == command.expected_revision
            )
            if not replacement_already_bound and not prior_binding_is_current:
                raise ValueError(
                    "foreground harness replacement was superseded before completion"
                )
        elif (
            not isinstance(binding, dict)
            or binding.get("task_id") != command.task_id
            or binding.get("run_id") != command.run_id
            or binding.get("harness_revision") != command.expected_revision
        ):
            raise ValueError("foreground harness command lost its active task binding")
        receipt = self.store.outbound_disclosure_receipt(receipt_id)
        manifest = self.harness_adapter.capability_manifest()
        if (
            receipt.get("revoked_at")
            or receipt.get("workspace_session_id") != command.workspace_session_id
            or receipt.get("user_id") != command.user_id
            or receipt.get("investigation_id") != command.investigation_id
        ):
            raise ValueError("harness disclosure receipt is inactive")
        self.store.require_outbound_disclosure(
            receipt_id,
            workspace_session_id=command.workspace_session_id,
            user_id=command.user_id,
            investigation_id=command.investigation_id,
            recipient_kind="installed_harness",
            recipient_id=manifest.adapter_id,
            purpose=f"{command.operation.value} for disease investigation",
            destination=manifest.execution_location,
            data_categories=list(receipt.get("data_categories") or []),
            payload=receipt.get("payload"),
            policy_versions={"harness_protocol": "genomilab.harness.v1"},
        )
        from .authorization_store import AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE

        derived = self.store.investigation_authorization_for_subject(
            subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
            subject_id=receipt_id,
        )
        if isinstance(derived, dict):
            authorization = derived.get("authorization")
            if not isinstance(authorization, dict):
                raise ValueError("derived harness disclosure lost its authorization")
            intent = self._authorization_intent_for_harness_command(command)
            current_authorization = self._require_investigation_authorization(
                command.investigation_id,
                intent=intent,
                receipt=authorization,
            )
            self.store.require_investigation_authorization_subject(
                current_authorization["authorization_receipt_id"],
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=receipt_id,
            )
        approved_context = command.payload.to_dict().get("approved_context")
        if not isinstance(approved_context, dict):
            return
        receipt_payload = receipt.get("payload")
        receipt_context = (
            receipt_payload.get("approved_context")
            if isinstance(receipt_payload, dict)
            else None
        )
        if receipt_context != approved_context:
            raise ValueError("harness command context differs from its disclosure")
        accepted_plan = approved_context.get("accepted_plan")
        if isinstance(accepted_plan, dict):
            current = investigation.get("current_plan_version")
            expected = self._accepted_plan_transport_context(investigation)
            if (
                not isinstance(current, dict)
                or accepted_plan != expected
                or accepted_plan.get("plan_version_id")
                != current.get("plan_version_id")
                or accepted_plan.get("plan_sha256") != current.get("plan_sha256")
                or accepted_plan.get("plan") != current.get("plan")
            ):
                raise ValueError("accepted harness plan authority changed")
        profile = approved_context.get("molecular_profile")
        if not isinstance(profile, dict):
            return
        snapshot_id = str(profile.get("patient_molecular_snapshot_id") or "")
        if (
            not snapshot_id
            or investigation.get("patient_molecular_snapshot_id") != snapshot_id
            or investigation.get("private_context_status") != "approved_for_session"
        ):
            raise ValueError("approved molecular-profile context is inactive")
        snapshot = self.store.get_profile_snapshot(snapshot_id)
        consent = self._active_context_receipt(investigation, snapshot)
        authority = approved_context.get("private_context_authority")
        if (
            consent.get("revoked_at")
            or not isinstance(authority, dict)
            or authority.get("patient_molecular_snapshot_id") != snapshot_id
            or authority.get("consent_receipt_id") != consent.get("consent_receipt_id")
            or consent.get("workspace_session_id") != command.workspace_session_id
        ):
            raise ValueError("profile consent is revoked")
