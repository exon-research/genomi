from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from genomi.lab.encrypted_sqlite import StaticEncryptionKeyProvider
from genomi.lab.harness import (
    HarnessCommand,
    HarnessJobIdentity,
    HarnessJobState,
    HarnessJobSubmission,
    SimulatedHarnessAdapter,
)
from genomi.lab.harness_codex_background import (
    CodexBackgroundController,
    codex_background_job_id,
)
from genomi.lab.service import GenomiLabService
from genomi.lab.store import GenomiLabStore


class _CurrentUserOperations:
    def __call__(
        self,
        operation: str,
        params: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        del params
        if operation == "genomi.describe_context":
            return {
                "active_user_id": "user-recovery",
                "active_user": {"nickname": "Recovery test user"},
                "active_agi_id": None,
                "active_genome_index": None,
            }
        if operation == "active_genome_index.revoke_access":
            return {"status": "revoked"}
        raise AssertionError(f"unexpected operation: {operation}")


class _UnexpectedlyFailingAdapter(SimulatedHarnessAdapter):
    def __init__(self) -> None:
        super().__init__(adapter_id="simulated-recovery")
        self.start_calls = 0

    def start_task_run(self, command: HarnessCommand):  # type: ignore[no-untyped-def]
        del command
        self.start_calls += 1
        raise RuntimeError("synthetic unexpected adapter failure")


class _CountingAdapter(SimulatedHarnessAdapter):
    def __init__(self) -> None:
        super().__init__(adapter_id="simulated-recovery")
        self.start_calls = 0

    def start_task_run(self, command: HarnessCommand):  # type: ignore[no-untyped-def]
        self.start_calls += 1
        return super().start_task_run(command)


class _ProcessLocalBackgroundAdapter(SimulatedHarnessAdapter):
    def __init__(self) -> None:
        super().__init__(adapter_id="simulated-recovery")
        self._manifest = replace(
            self.manifest,
            background_job_attach=True,
            background_job_cancel=True,
        )
        self.dispatch_count = 0
        self.jobs: dict[str, HarnessJobSubmission] = {}

    def dispatch_background(
        self,
        command: HarnessCommand,
        *,
        submission_callback: Any,
        identity_callback: Any,
        completion_callback: Any,
    ) -> HarnessJobSubmission:
        del completion_callback
        self.dispatch_count += 1
        job_id = f"harness-job-{command.command_id}"
        task_id = self._generated_id("sim-task", command.command_id)
        run_id = self._generated_id("run", command.command_id)
        submission_callback(HarnessJobSubmission(job_id, HarnessJobState.QUEUED))
        identity_callback(HarnessJobIdentity(job_id, task_id, run_id))
        running = HarnessJobSubmission(job_id, HarnessJobState.RUNNING, task_id, run_id)
        self.jobs[job_id] = running
        return running

    def background_job(self, job_id: str) -> HarnessJobSubmission | None:
        return self.jobs.get(job_id)


class _PostSubmissionFailingAdapter(SimulatedHarnessAdapter):
    def __init__(self) -> None:
        super().__init__(adapter_id="simulated-recovery")
        self._manifest = replace(
            self.manifest,
            background_job_attach=True,
            background_job_cancel=True,
        )
        self.dispatch_count = 0

    def dispatch_background(
        self,
        command: HarnessCommand,
        *,
        submission_callback: Any,
        identity_callback: Any,
        completion_callback: Any,
    ) -> HarnessJobSubmission:
        del identity_callback, completion_callback
        self.dispatch_count += 1
        submission_callback(
            HarnessJobSubmission(
                f"harness-job-{command.command_id}", HarnessJobState.QUEUED
            )
        )
        raise RuntimeError("synthetic launch failure after durable submission")


class _RecoverableCompletionBackgroundAdapter(SimulatedHarnessAdapter):
    """Exercise Codex's retryable completion boundary without a host process."""

    def __init__(self) -> None:
        super().__init__(adapter_id="simulated-recovery")
        self._manifest = replace(
            self.manifest,
            background_job_attach=True,
            background_job_cancel=True,
        )
        self.controller = CodexBackgroundController(1)
        self.execution_count = 0

    def dispatch_background(
        self,
        command: HarnessCommand,
        *,
        submission_callback: Any,
        identity_callback: Any,
        completion_callback: Any,
    ) -> HarnessJobSubmission:
        def execute(current: HarnessCommand):  # type: ignore[no-untyped-def]
            self.execution_count += 1
            response = SimulatedHarnessAdapter.start_task_run(self, current)
            assert response.result is not None
            identity_callback(
                HarnessJobIdentity(
                    codex_background_job_id(current.command_id),
                    response.result.task_id,
                    response.result.run_id,
                )
            )
            return response

        return self.controller.dispatch(
            command,
            submission_callback=submission_callback,
            identity_callback=identity_callback,
            completion_callback=completion_callback,
            execute=execute,
            failure_response=lambda _job: self.fail_unexpected_execution_failure(),
        )

    @staticmethod
    def fail_unexpected_execution_failure():  # type: ignore[no-untyped-def]
        raise AssertionError("synthetic background execution should not fail")

    def background_job(self, job_id: str) -> HarnessJobSubmission | None:
        return self.controller.background_job(job_id)

    def retry_background_completion(
        self, job_id: str
    ) -> HarnessJobSubmission | None:
        return self.controller.retry_completion(job_id)

    def close(self) -> None:
        self.controller.close()
        super().close()


class GenomiLabHarnessRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store_path = Path(self.temporary.name) / "genomilab.sqlite3"
        self.key_provider = StaticEncryptionKeyProvider(b"r" * 32)
        self.operations = _CurrentUserOperations()
        self.services: list[GenomiLabService] = []
        self.addCleanup(self._close_services)

    def _service(
        self,
        adapter: SimulatedHarnessAdapter,
        *,
        session_id: str = "workspace-session-recovery",
    ) -> GenomiLabService:
        service = GenomiLabService(
            store=GenomiLabStore(
                self.store_path,
                key_provider=self.key_provider,
            ),
            session_id=session_id,
            operation_call=self.operations,
            harness_adapter=adapter,
        )
        self.services.append(service)
        service.bootstrap_workspace()
        return service

    def _new_command(
        self,
        service: GenomiLabService,
        *,
        command_id: str,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        investigation = service.create_investigation(
            {"question": "Investigate an interrupted synthetic harness task."}
        )
        investigation_id = str(investigation["investigation_id"])
        preview = service.harness_disclosure_candidate(
            investigation_id,
            command_id=command_id,
        )
        command_context = preview["payload"]["command_context"]
        request = {
            "approved": True,
            "payload_sha256": preview["payload_sha256"],
            "command_id": command_context["command_id"],
            "expected_revision": command_context["expected_revision"],
        }
        return investigation_id, preview, request

    def _close_services(self) -> None:
        for service in reversed(self.services):
            service.close()

    def test_unexpected_adapter_exception_is_terminal_and_never_redispatched(
        self,
    ) -> None:
        failing = _UnexpectedlyFailingAdapter()
        service = self._service(failing)
        investigation_id, _preview, request = self._new_command(
            service,
            command_id="command-adapter-exception",
        )

        first = service._start_harness_for_conformance(investigation_id, request)
        same_process_retry = service._start_harness_for_conformance(investigation_id, request)

        self.assertEqual(first, same_process_retry)
        self.assertEqual(first["status"], "harness_dispatch_outcome_unknown")
        self.assertEqual(first["dispatch_outcome"], "unknown")
        self.assertFalse(first["retry_safe"])
        self.assertTrue(first["requires_manual_reconciliation"])
        self.assertEqual(failing.start_calls, 1)
        self.assertEqual(
            service.store.harness_command("command-adapter-exception")["command_state"],
            "failed",
        )

        service.close()
        replacement_process_adapter = _CountingAdapter()
        restarted = self._service(replacement_process_adapter)
        after_restart = restarted._start_harness_for_conformance(investigation_id, request)

        self.assertEqual(after_restart, first)
        self.assertEqual(replacement_process_adapter.start_calls, 0)

    def test_foreground_late_completion_failure_rolls_back_domain_transition(
        self,
    ) -> None:
        service = self._service(_CountingAdapter())
        investigation_id, _preview, request = self._new_command(
            service,
            command_id="command-foreground-atomic-rollback",
        )
        investigation_before = service.store.get_investigation(investigation_id)
        events_before = service.store.replay_harness_events(investigation_id)
        original_complete = service.store.complete_harness_command

        def fail_after_command_completion(
            command_id: str,
            response: dict[str, Any],
            *,
            succeeded: bool,
        ) -> dict[str, Any]:
            saved = original_complete(command_id, response, succeeded=succeeded)
            if response.get("status") == "accepted":
                raise RuntimeError("synthetic late foreground completion failure")
            return saved

        service.store.complete_harness_command = fail_after_command_completion  # type: ignore[method-assign]

        result = service._start_harness_for_conformance(investigation_id, request)

        self.assertEqual(result["status"], "harness_dispatch_outcome_unknown")
        self.assertEqual(
            result["dispatch_outcome"], "response_received_commit_incomplete"
        )
        self.assertIsNone(service.store.active_harness_binding(investigation_id))
        self.assertEqual(
            service.store.replay_harness_events(investigation_id), events_before
        )
        investigation_after = service.store.get_investigation(investigation_id)
        self.assertEqual(investigation_after["status"], investigation_before["status"])
        self.assertEqual(
            investigation_after["domain_revision"],
            investigation_before["domain_revision"],
        )
        self.assertIsNone(investigation_after.get("current_plan_version"))
        command = service.store.harness_command("command-foreground-atomic-rollback")
        assert command is not None
        self.assertEqual(command["command_state"], "failed")
        self.assertEqual(
            command["response"]["status"], "harness_dispatch_outcome_unknown"
        )

    def test_background_launch_failure_terminalizes_the_durable_job(self) -> None:
        adapter = _PostSubmissionFailingAdapter()
        service = self._service(adapter)
        investigation_id, _preview, request = self._new_command(
            service,
            command_id="command-background-post-submission-failure",
        )

        first = service._start_harness_for_conformance(investigation_id, request)
        replayed = service._start_harness_for_conformance(investigation_id, request)

        self.assertEqual(first, replayed)
        self.assertEqual(first["status"], "harness_dispatch_outcome_unknown")
        self.assertEqual(adapter.dispatch_count, 1)
        command = service.store.harness_command(
            "command-background-post-submission-failure"
        )
        assert command is not None
        self.assertEqual(command["command_state"], "failed")
        job = service.store.harness_job_for_command(
            "command-background-post-submission-failure"
        )
        assert job is not None
        self.assertEqual(job["job_state"], "failed")
        self.assertEqual(job["terminal_response"], first)

    def test_completion_persistence_recovers_without_reexecuting_agent_turn(
        self,
    ) -> None:
        adapter = _RecoverableCompletionBackgroundAdapter()
        service = self._service(adapter)
        investigation_id, _preview, request = self._new_command(
            service,
            command_id="command-recoverable-background-completion",
        )
        original_complete = service.store.complete_harness_command
        completion_attempts = 0

        def fail_normal_and_fail_closed_completion(
            command_id: str,
            response: dict[str, Any],
            *,
            succeeded: bool,
        ) -> dict[str, Any]:
            nonlocal completion_attempts
            completion_attempts += 1
            if completion_attempts <= 2:
                raise RuntimeError("synthetic durable completion outage")
            return original_complete(command_id, response, succeeded=succeeded)

        service.store.complete_harness_command = (  # type: ignore[method-assign]
            fail_normal_and_fail_closed_completion
        )

        started = service._start_harness_for_conformance(investigation_id, request)
        terminal = adapter.controller.wait_for_background_job(
            str(started["job_id"]), timeout_seconds=1
        )

        self.assertEqual(started["status"], "in_progress")
        self.assertIsNotNone(terminal)
        assert terminal is not None
        self.assertEqual(terminal.state, HarnessJobState.COMPLETED)
        self.assertEqual(adapter.execution_count, 1)
        pending_command = service.store.harness_command(
            "command-recoverable-background-completion"
        )
        pending_job = service.store.harness_job(str(started["job_id"]))
        assert pending_command is not None and pending_job is not None
        self.assertEqual(pending_command["command_state"], "dispatching")
        self.assertEqual(pending_job["job_state"], "running")
        self.assertIsNone(pending_job["terminal_response"])

        recovered = service._start_harness_for_conformance(investigation_id, request)
        replayed = service._start_harness_for_conformance(investigation_id, request)

        self.assertEqual(recovered["status"], "accepted")
        self.assertEqual(replayed, recovered)
        self.assertEqual(adapter.execution_count, 1)
        saved_command = service.store.harness_command(
            "command-recoverable-background-completion"
        )
        saved_job = service.store.harness_job(str(started["job_id"]))
        assert saved_command is not None and saved_job is not None
        self.assertEqual(saved_command["command_state"], "completed")
        self.assertEqual(saved_job["job_state"], "completed")
        self.assertEqual(saved_job["terminal_response"], recovered)

    def test_restart_reconciles_an_orphaned_dispatch_marker_without_dispatching(
        self,
    ) -> None:
        service = self._service(_CountingAdapter())
        investigation_id, preview, request = self._new_command(
            service,
            command_id="command-orphaned-dispatch",
        )
        user_id = "user-recovery"
        service.store.begin_harness_command(
            command_id="command-orphaned-dispatch",
            investigation_id=investigation_id,
            workspace_session_id=service.session_id,
            user_id=user_id,
            operation="start_task_run",
            command_fingerprint=preview["payload_sha256"],
        )
        receipt = service.store.create_outbound_disclosure_receipt(
            user_id,
            workspace_session_id=service.session_id,
            investigation_id=investigation_id,
            recipient_kind="installed_harness",
            recipient_id=preview["recipient_id"],
            purpose="start_task_run for disease investigation",
            destination=preview["destination"],
            data_categories=preview["data_categories"],
            payload=preview["payload"],
            policy_versions={"harness_protocol": "genomilab.harness.v1"},
            approved=True,
        )
        service.store.attach_harness_command_disclosure(
            "command-orphaned-dispatch",
            str(receipt["disclosure_receipt_id"]),
        )
        service.store.claim_harness_command_dispatch("command-orphaned-dispatch")
        self.assertEqual(
            service.store.harness_command("command-orphaned-dispatch")["command_state"],
            "dispatching",
        )

        service.close()
        restarted_adapter = _CountingAdapter()
        restarted = self._service(restarted_adapter)
        recovered = restarted._start_harness_for_conformance(investigation_id, request)
        replayed = restarted._start_harness_for_conformance(investigation_id, request)

        self.assertEqual(recovered, replayed)
        self.assertEqual(recovered["status"], "harness_dispatch_outcome_unknown")
        self.assertFalse(recovered["retry_safe"])
        self.assertEqual(restarted_adapter.start_calls, 0)
        saved = restarted.store.harness_command("command-orphaned-dispatch")
        self.assertEqual(saved["command_state"], "failed")
        self.assertEqual(saved["response"], recovered)

    def test_restart_fails_closed_when_new_adapter_cannot_reattach_saved_job(
        self,
    ) -> None:
        original_adapter = _ProcessLocalBackgroundAdapter()
        service = self._service(original_adapter)
        investigation_id, _preview, request = self._new_command(
            service,
            command_id="command-process-local-job",
        )
        started = service._start_harness_for_conformance(investigation_id, request)
        self.assertEqual(started["status"], "in_progress")
        self.assertEqual(original_adapter.dispatch_count, 1)

        restarted_adapter = _ProcessLocalBackgroundAdapter()
        restarted = self._service(restarted_adapter)
        recovered = restarted._start_harness_for_conformance(investigation_id, request)
        replayed = restarted._start_harness_for_conformance(investigation_id, request)

        self.assertEqual(recovered, replayed)
        self.assertEqual(recovered["status"], "harness_job_recovery_failed")
        self.assertFalse(recovered["retry_safe"])
        self.assertTrue(recovered["requires_explicit_replacement"])
        self.assertIsNone(recovered["committed_artifact"])
        self.assertEqual(restarted_adapter.dispatch_count, 0)
        saved_job = restarted.store.harness_job(str(started["job_id"]))
        assert saved_job is not None
        self.assertEqual(saved_job["job_state"], "failed")
        self.assertEqual(
            restarted.store.harness_command("command-process-local-job")[
                "command_state"
            ],
            "failed",
        )

        replacement_preview = restarted.harness_disclosure_candidate(
            investigation_id,
            operation="replace_task_binding",
            artifact_kind="plan",
            instruction="Restart planning in a newly approved harness task.",
            reason="The prior process-local harness job could not be reattached.",
            command_id="command-process-local-replacement",
        )
        context = replacement_preview["payload"]["command_context"]
        replacement = restarted._replace_harness_for_conformance(
            investigation_id,
            {
                "approved": True,
                "payload_sha256": replacement_preview["payload_sha256"],
                "command_id": "command-process-local-replacement",
                "expected_revision": context["expected_revision"],
                "artifact_kind": "plan",
                "message": "Restart planning in a newly approved harness task.",
                "reason": (
                    "The prior process-local harness job could not be reattached."
                ),
            },
        )
        self.assertEqual(replacement["status"], "in_progress")
        self.assertEqual(restarted_adapter.dispatch_count, 1)


if __name__ == "__main__":
    unittest.main()
