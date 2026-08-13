from __future__ import annotations

import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from genomi.lab.encrypted_sqlite import StaticEncryptionKeyProvider
from genomi.lab.harness import (
    HarnessDynamicToolCall,
    HarnessJobIdentity,
    HarnessJobState,
    HarnessJobSubmission,
    SimulatedHarnessAdapter,
)
from genomi.lab.service import GenomiLabService, LabError
from genomi.lab.store import GenomiLabStore


class _MutableCurrentUser:
    def __init__(self) -> None:
        self.user_id = "user-async-a"

    def __call__(
        self,
        operation: str,
        params: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        del params
        if operation == "genomi.describe_context":
            return {
                "active_user_id": self.user_id,
                "active_user": {"nickname": self.user_id},
                "active_agi_id": None,
                "active_genome_index": None,
            }
        if operation == "active_genome_index.revoke_access":
            return {"status": "revoked"}
        raise AssertionError(f"unexpected operation: {operation}")


class _DeferredHarnessAdapter(SimulatedHarnessAdapter):
    def __init__(self) -> None:
        super().__init__(adapter_id="deferred-security-harness")
        self._manifest = replace(
            self.manifest,
            background_job_attach=True,
            background_job_cancel=True,
        )
        self.dispatch_count = 0
        self._pending: dict[str, tuple[Any, Any, str, str]] = {}
        self._jobs: dict[str, HarnessJobSubmission] = {}

    def dispatch_background(
        self,
        command: Any,
        *,
        submission_callback: Any,
        identity_callback: Any,
        completion_callback: Any,
    ) -> HarnessJobSubmission:
        self.dispatch_count += 1
        job_id = f"harness-job-{command.command_id}"
        task_id = self._generated_id("sim-task", command.command_id)
        run_id = self._generated_id("run", command.command_id)
        submission_callback(HarnessJobSubmission(job_id, HarnessJobState.QUEUED))
        identity_callback(HarnessJobIdentity(job_id, task_id, run_id))
        running = HarnessJobSubmission(job_id, HarnessJobState.RUNNING, task_id, run_id)
        self._pending[command.command_id] = (
            command,
            completion_callback,
            job_id,
            run_id,
        )
        self._jobs[job_id] = running
        return running

    def background_job(self, job_id: str) -> HarnessJobSubmission | None:
        return self._jobs.get(job_id)

    def finish(
        self,
        state: HarnessJobState = HarnessJobState.COMPLETED,
        *,
        command_id: str = "command-async-security",
    ) -> None:
        command, callback, job_id, _run_id = self._pending[command_id]
        operation = {
            "start_task_run": self.start_task_run,
            "replace_task_binding": self.replace_task_binding,
        }[command.operation.value]
        response = operation(command)
        callback(job_id, state, response)
        self._jobs[job_id] = HarnessJobSubmission(
            job_id,
            state,
            self._jobs[job_id].task_id,
            self._jobs[job_id].run_id,
        )


class _DelayedIdentityHarnessAdapter(_DeferredHarnessAdapter):
    def __init__(self) -> None:
        super().__init__()
        self._identity_callbacks: dict[str, Any] = {}
        self._identities: dict[str, HarnessJobIdentity] = {}

    def dispatch_background(
        self,
        command: Any,
        *,
        submission_callback: Any,
        identity_callback: Any,
        completion_callback: Any,
    ) -> HarnessJobSubmission:
        self.dispatch_count += 1
        job_id = f"harness-job-{command.command_id}"
        task_id = self._generated_id("sim-task", command.command_id)
        run_id = self._generated_id("run", command.command_id)
        submission_callback(HarnessJobSubmission(job_id, HarnessJobState.QUEUED))
        self._identity_callbacks[command.command_id] = identity_callback
        self._identities[command.command_id] = HarnessJobIdentity(
            job_id, task_id, run_id
        )
        running = HarnessJobSubmission(job_id, HarnessJobState.RUNNING, task_id, run_id)
        self._pending[command.command_id] = (
            command,
            completion_callback,
            job_id,
            run_id,
        )
        self._jobs[job_id] = running
        return running

    def attach_identity(self, command_id: str = "command-async-security") -> None:
        self._identity_callbacks[command_id](self._identities[command_id])


class GenomiLabHarnessAsyncSecurityTests(unittest.TestCase):
    def _started_case(
        self,
        adapter: _DeferredHarnessAdapter | None = None,
    ) -> tuple[
        GenomiLabService,
        _MutableCurrentUser,
        _DeferredHarnessAdapter,
        str,
        dict[str, Any],
    ]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        operations = _MutableCurrentUser()
        adapter = adapter or _DeferredHarnessAdapter()
        service = GenomiLabService(
            store=GenomiLabStore(
                Path(temporary.name) / "genomilab.sqlite3",
                key_provider=StaticEncryptionKeyProvider(b"a" * 32),
            ),
            session_id="workspace-session-async-security",
            operation_call=operations,
            harness_adapter=adapter,
        )
        self.addCleanup(service.close)
        service.bootstrap_workspace()
        observation = service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Synthetic condition",
                "original_wording": "Synthetic condition",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            }
        )
        investigation = service.create_investigation(
            {
                "question": "Could the molecular profile inform this synthetic condition?",
                "disease_scope": "Synthetic condition",
            }
        )
        investigation_id = str(investigation["investigation_id"])
        context = service.investigation_context_candidate(
            investigation_id,
            {
                "purpose": "Investigate the synthetic condition",
                "observation_revision_ids": [observation["observation_revision_id"]],
            },
        )
        service.approve_investigation_context(
            investigation_id,
            {
                key: context[key]
                for key in (
                    "purpose",
                    "observation_revision_ids",
                    "artifact_ids",
                    "specimen_ids",
                    "assay_ids",
                    "agi_id",
                    "agi_snapshot_id",
                    "genomic_scope",
                    "candidate_sha256",
                    "candidate_receipt",
                )
            }
            | {"approved": True},
        )
        preview = service.harness_disclosure_candidate(
            investigation_id, command_id="command-async-security"
        )
        request = {
            "approved": True,
            "payload_sha256": preview["payload_sha256"],
            "command_id": "command-async-security",
            "expected_revision": 0,
        }
        started = service.start_investigation(investigation_id, request)
        self.assertEqual(started["status"], "in_progress")
        same = service.start_investigation(investigation_id, request)
        self.assertEqual(same["job_id"], started["job_id"])
        self.assertEqual(adapter.dispatch_count, 1)
        return service, operations, adapter, investigation_id, started

    @staticmethod
    def _run_in_thread(callback: Any) -> tuple[threading.Thread, list[object]]:
        outcomes: list[object] = []

        def run() -> None:
            try:
                outcomes.append(callback())
            except Exception as exc:  # asserted by each race test
                outcomes.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        return worker, outcomes

    def _assert_completion_rejected(
        self,
        service: GenomiLabService,
        adapter: _DeferredHarnessAdapter,
        investigation_id: str,
        started: dict[str, Any],
    ) -> None:
        adapter.finish()
        command = service.store.harness_command("command-async-security")
        assert command is not None
        self.assertEqual(
            command["response"]["status"],
            "harness_result_rejected_context_inactive",
        )
        job = service.store.harness_job(str(started["job_id"]))
        assert job is not None
        self.assertEqual(job["job_state"], "failed")
        self.assertIsNone(service.store.get_investigation(investigation_id).get("plan"))

    def test_revoked_context_rejects_late_harness_artifact(self) -> None:
        service, _operations, adapter, investigation_id, started = self._started_case()
        service.revoke_private_context(investigation_id)
        self._assert_completion_rejected(service, adapter, investigation_id, started)

    def test_user_switch_during_dynamic_tool_callback_returns_no_prior_user_result(
        self,
    ) -> None:
        service, operations, _adapter, investigation_id, _started = self._started_case()
        entered = threading.Event()
        release = threading.Event()

        def blocked_capability(_call: object) -> dict[str, object]:
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return {"status": "completed", "patient_a_secret": "must-not-return"}

        service._execute_bound_harness_capability = blocked_capability  # type: ignore[method-assign]
        call = HarnessDynamicToolCall(
            command_id="command-async-security",
            investigation_id=investigation_id,
            thread_id="synthetic-task",
            turn_id="synthetic-turn",
            call_id="synthetic-call",
            capability="investigation.project_profile",
            request_id="request-profile",
        )
        worker, outcomes = self._run_in_thread(
            lambda: service._execute_guarded_harness_capability(call)
        )
        self.assertTrue(entered.wait(timeout=5))
        operations.user_id = "user-async-b"
        release.set()
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], LabError)
        self.assertEqual(outcomes[0].code, "genomi_user_changed")
        self.assertNotIn("must-not-return", repr(outcomes[0]))

    def test_user_switch_during_identity_callback_binds_no_prior_user_task(
        self,
    ) -> None:
        delayed = _DelayedIdentityHarnessAdapter()
        service, operations, adapter, investigation_id, started = self._started_case(
            delayed
        )
        entered = threading.Event()
        release = threading.Event()
        original_bind = service.store.attach_and_bind_harness_job_identity

        def blocked_bind(*args: Any, **kwargs: Any) -> dict[str, object]:
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return original_bind(*args, **kwargs)

        service.store.attach_and_bind_harness_job_identity = blocked_bind  # type: ignore[method-assign]
        worker, outcomes = self._run_in_thread(adapter.attach_identity)
        self.assertTrue(entered.wait(timeout=5))
        operations.user_id = "user-async-b"
        release.set()
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], LabError)
        self.assertEqual(outcomes[0].code, "genomi_user_changed")
        self.assertIsNone(service.store.active_harness_binding(investigation_id))
        job = service.store.harness_job(str(started["job_id"]))
        assert job is not None
        self.assertIsNone(job["task_id"])
        self.assertIsNone(job["run_id"])
        self.assertEqual(job["job_state"], "queued")

    def test_user_switch_between_completion_check_and_commit_fails_closed(
        self,
    ) -> None:
        service, operations, adapter, investigation_id, started = self._started_case()
        entered = threading.Event()
        release = threading.Event()
        original_commit = service._commit_harness_response

        def blocked_commit(*args: Any, **kwargs: Any) -> dict[str, object]:
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return original_commit(*args, **kwargs)

        service._commit_harness_response = blocked_commit  # type: ignore[method-assign]
        worker, outcomes = self._run_in_thread(adapter.finish)
        self.assertTrue(entered.wait(timeout=5))
        operations.user_id = "user-async-b"
        release.set()
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(outcomes, [None])
        command = service.store.harness_command("command-async-security")
        assert command is not None
        rejected = command["response"]
        self.assertEqual(rejected["status"], "harness_result_rejected_context_inactive")
        self.assertIsNone(rejected["binding"])
        self.assertEqual(rejected["events"], [])
        self.assertEqual(rejected["capability_results"], [])
        self.assertIsNone(rejected["committed_artifact"])
        job = service.store.harness_job(str(started["job_id"]))
        assert job is not None
        self.assertEqual(job["job_state"], "failed")
        self.assertIsNone(service.store.get_investigation(investigation_id).get("plan"))

    def test_background_late_completion_failure_rolls_back_domain_transition(
        self,
    ) -> None:
        service, _operations, adapter, investigation_id, started = self._started_case()
        binding_before = service.store.active_harness_binding(investigation_id)
        assert binding_before is not None
        events_before = service.store.replay_harness_events(investigation_id)
        investigation_before = service.store.get_investigation(investigation_id)
        original_complete = service.store.complete_harness_job

        def fail_after_job_completion(
            job_id: str,
            *,
            job_state: str,
            response: dict[str, Any],
        ) -> dict[str, Any]:
            saved = original_complete(
                job_id,
                job_state=job_state,
                response=response,
            )
            if job_state == HarnessJobState.COMPLETED.value:
                raise RuntimeError("synthetic late background completion failure")
            return saved

        service.store.complete_harness_job = fail_after_job_completion  # type: ignore[method-assign]

        adapter.finish()

        self.assertEqual(
            service.store.active_harness_binding(investigation_id), binding_before
        )
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
        command = service.store.harness_command("command-async-security")
        assert command is not None
        self.assertEqual(command["command_state"], "failed")
        self.assertEqual(
            command["response"]["status"],
            "harness_result_rejected_context_inactive",
        )
        job = service.store.harness_job(str(started["job_id"]))
        assert job is not None
        self.assertEqual(job["job_state"], "failed")
        self.assertEqual(
            job["terminal_response"]["status"],
            "harness_result_rejected_context_inactive",
        )

    def test_switched_user_rejects_late_harness_artifact(self) -> None:
        service, operations, adapter, investigation_id, started = self._started_case()
        operations.user_id = "user-async-b"
        self._assert_completion_rejected(service, adapter, investigation_id, started)

    def test_closed_session_rejects_late_harness_artifact(self) -> None:
        service, _operations, adapter, investigation_id, started = self._started_case()
        service.close()
        self._assert_completion_rejected(service, adapter, investigation_id, started)

    def test_confirmed_interrupt_keeps_cancelled_state_and_commits_no_artifact(
        self,
    ) -> None:
        service, _operations, adapter, investigation_id, started = self._started_case()
        preview = service.harness_disclosure_candidate(
            investigation_id,
            operation="cancel_task_work",
            reason="Cancel the synthetic running turn.",
            command_id="command-cancel-async-security",
        )
        context = preview["payload"]["command_context"]
        cancelled = service.cancel_background_work(
            investigation_id,
            {
                "approved": True,
                "payload_sha256": preview["payload_sha256"],
                "command_id": context["command_id"],
                "expected_revision": context["expected_revision"],
                "reason": preview["payload"]["reason"],
            },
        )
        self.assertEqual(cancelled["status"], "accepted")
        self.assertEqual(
            cancelled["harness_response"]["result"]["outcome"], "cancelled"
        )
        self.assertEqual(cancelled["binding"]["harness_status"], "cancelled")

        adapter.finish(HarnessJobState.CANCELLED)

        original = service.store.harness_command("command-async-security")
        assert original is not None
        self.assertEqual(original["command_state"], "completed")
        self.assertEqual(original["response"]["status"], "cancelled")
        self.assertIsNone(original["response"]["committed_artifact"])
        job = service.store.harness_job(str(started["job_id"]))
        assert job is not None
        self.assertEqual(job["job_state"], "cancelled")
        self.assertIsNone(service.store.get_investigation(investigation_id).get("plan"))
        binding = service.store.active_harness_binding(investigation_id)
        assert binding is not None
        self.assertEqual(binding["harness_status"], "cancelled")

    def test_cancelled_callback_after_context_revocation_fails_closed(
        self,
    ) -> None:
        service, _operations, adapter, investigation_id, started = self._started_case()
        service.revoke_private_context(investigation_id)

        adapter.finish(HarnessJobState.CANCELLED)

        command = service.store.harness_command("command-async-security")
        assert command is not None
        rejected = command["response"]
        self.assertEqual(rejected["status"], "harness_result_rejected_context_inactive")
        self.assertIsNone(rejected["binding"])
        self.assertEqual(rejected["events"], [])
        self.assertEqual(rejected["capability_results"], [])
        self.assertIsNone(rejected["committed_artifact"])
        job = service.store.harness_job(str(started["job_id"]))
        assert job is not None
        self.assertEqual(job["job_state"], "failed")
        self.assertIsNone(service.store.get_investigation(investigation_id).get("plan"))

    def test_replaced_task_cannot_commit_a_late_background_artifact(self) -> None:
        service, _operations, adapter, investigation_id, started = self._started_case()
        preview = service.harness_disclosure_candidate(
            investigation_id,
            operation="replace_task_binding",
            artifact_kind="plan",
            instruction="Replace the still-running planning task.",
            reason="Continue in a newly approved harness task.",
            command_id="command-replace-async-security",
        )
        context = preview["payload"]["command_context"]
        replacement = service.replace_harness_binding(
            investigation_id,
            {
                "approved": True,
                "payload_sha256": preview["payload_sha256"],
                "command_id": "command-replace-async-security",
                "expected_revision": context["expected_revision"],
                "artifact_kind": "plan",
                "message": "Replace the still-running planning task.",
                "reason": "Continue in a newly approved harness task.",
            },
        )
        self.assertEqual(replacement["status"], "in_progress")
        active = service.store.active_harness_binding(investigation_id)
        assert active is not None
        self.assertEqual(active["command_id"], "command-replace-async-security")

        adapter.finish(command_id="command-async-security")

        original = service.store.harness_command("command-async-security")
        assert original is not None
        self.assertEqual(
            original["response"]["status"],
            "harness_result_rejected_context_inactive",
        )
        self.assertIsNone(original["response"]["committed_artifact"])
        self.assertEqual(original["response"].get("capability_results", []), [])
        self.assertIsNone(service.store.get_investigation(investigation_id).get("plan"))
        old_job = service.store.harness_job(str(started["job_id"]))
        assert old_job is not None
        self.assertEqual(old_job["job_state"], "failed")
        still_active = service.store.active_harness_binding(investigation_id)
        assert still_active is not None
        self.assertEqual(still_active["command_id"], "command-replace-async-security")

    def test_delayed_replacement_identity_cannot_roll_back_newer_binding(self) -> None:
        delayed = _DelayedIdentityHarnessAdapter()
        service, _operations, adapter, investigation_id, _started = self._started_case(
            delayed
        )
        adapter.attach_identity()
        initial = service.store.active_harness_binding(investigation_id)
        assert initial is not None
        self.assertEqual(initial["harness_revision"], 1)

        def dispatch_replacement(command_id: str) -> dict[str, Any]:
            preview = service.harness_disclosure_candidate(
                investigation_id,
                operation="replace_task_binding",
                artifact_kind="plan",
                instruction="Replace the running planning task.",
                reason="Continue with separately approved harness work.",
                command_id=command_id,
            )
            context = preview["payload"]["command_context"]
            return service.replace_harness_binding(
                investigation_id,
                {
                    "approved": True,
                    "payload_sha256": preview["payload_sha256"],
                    "command_id": command_id,
                    "expected_revision": context["expected_revision"],
                    "artifact_kind": "plan",
                    "message": "Replace the running planning task.",
                    "reason": "Continue with separately approved harness work.",
                },
            )

        replacement_a = dispatch_replacement("command-replacement-a")
        replacement_b = dispatch_replacement("command-replacement-b")
        self.assertEqual(replacement_a["status"], "in_progress")
        self.assertEqual(replacement_b["status"], "in_progress")

        adapter.attach_identity("command-replacement-b")
        active_b = service.store.active_harness_binding(investigation_id)
        assert active_b is not None
        self.assertEqual(active_b["command_id"], "command-replacement-b")

        with self.assertRaisesRegex(ValueError, "superseded"):
            adapter.attach_identity("command-replacement-a")

        active_after_stale = service.store.active_harness_binding(investigation_id)
        assert active_after_stale is not None
        self.assertEqual(active_after_stale["binding_id"], active_b["binding_id"])
        self.assertEqual(active_after_stale["command_id"], "command-replacement-b")
        stale_command = service.store.harness_command("command-replacement-a")
        stale_job = service.store.harness_job_for_command("command-replacement-a")
        assert stale_command is not None and stale_job is not None
        self.assertEqual(stale_command["command_state"], "failed")
        self.assertEqual(
            stale_command["response"]["status"],
            "harness_identity_rejected_stale",
        )
        self.assertEqual(stale_job["job_state"], "failed")
        current_job = service.store.harness_job_for_command("command-replacement-b")
        assert current_job is not None
        self.assertEqual(current_job["job_state"], "running")


if __name__ == "__main__":
    unittest.main()
