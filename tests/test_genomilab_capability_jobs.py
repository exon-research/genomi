from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from genomi.lab.capability_store import CAPABILITY_RETRY_OPERATION
from genomi.lab.evidence_service import DirectEvidenceSource
from genomi.lab.harness import SimulatedHarnessAdapter
from genomi.lab.investigation_capabilities import (
    PROFILE_PROJECT,
    PUBLIC_EVIDENCE_RETRIEVE,
    InvestigationCapabilityMixin,
)
from genomi.lab.paperclip_adapter import PaperclipOperation
from genomi.lab.provider_policy import EvidenceRequest, SourceFamily
from genomi.lab.service import GenomiLabService, LabError
from genomi.lab.store import GenomiLabStore
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


class _DurableCapabilityApplication(InvestigationCapabilityMixin):
    def __init__(
        self,
        store: GenomiLabStore,
        *,
        outcome: dict[str, object] | Exception,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.store = store
        self.session_id = "session-capability-jobs"
        self.outcome = outcome
        self.started = started
        self.release = release
        self.calls = 0
        self._calls_lock = threading.Lock()

    def _execute_capability_request(
        self,
        investigation_id: str,
        request: dict[str, Any],
        *,
        approval: dict[str, Any] | None,
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> dict[str, Any]:
        del (
            investigation_id,
            request,
            approval,
            expected_plan_version_id,
            expected_consent_receipt_id,
        )
        with self._calls_lock:
            self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(timeout=5)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return dict(self.outcome)

    def investigation(self, investigation_id: str) -> dict[str, object]:
        return self.store.get_investigation(investigation_id)

    def _accepted_current_plan(self, investigation_id: str) -> dict[str, object]:
        investigation = self.investigation(investigation_id)
        current = investigation.get("current_plan_version")
        if not isinstance(current, dict) or current.get("review_status") != "accepted":
            raise LabError("plan_acceptance_required", "Plan acceptance required.")
        return investigation

    def _active_context_receipt(
        self,
        investigation: dict[str, object],
        snapshot: dict[str, object],
    ) -> dict[str, object]:
        del snapshot
        return self.store.consent_receipt(
            str(investigation["active_consent_receipt_id"])
        )


class _ApprovalCapabilityApplication(_DurableCapabilityApplication):
    def __init__(self, store: GenomiLabStore) -> None:
        super().__init__(store, outcome={})

    def _execute_capability_request(
        self,
        investigation_id: str,
        request: dict[str, Any],
        *,
        approval: dict[str, Any] | None,
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> dict[str, Any]:
        del (
            investigation_id,
            request,
            expected_plan_version_id,
            expected_consent_receipt_id,
        )
        self.calls += 1
        if approval is None:
            return {
                "status": "approval_required",
                "candidate": {
                    "selected_provider": "gxl_paperclip",
                    "payload_sha256": "a" * 64,
                    "payload": {"request": {"query": "synthetic mechanism"}},
                },
            }
        return {"status": "committed", "evidence_record_id": "evidence-a"}


class _ResumableCapabilityApplication(_DurableCapabilityApplication):
    def __init__(
        self,
        store: GenomiLabStore,
        *,
        investigation_id: str,
        plan_version_id: str,
        capability: str,
        check_results: list[dict[str, object]],
    ) -> None:
        super().__init__(store, outcome={})
        self.investigation_id = investigation_id
        self.plan_version_id = plan_version_id
        self.capability = capability
        self.check_results = check_results
        self.check_calls = 0

    def investigation(self, investigation_id: str) -> dict[str, object]:
        if investigation_id != self.investigation_id:
            raise AssertionError("unexpected investigation")
        return {
            "investigation_id": investigation_id,
            "current_plan_version": {
                "plan_version_id": self.plan_version_id,
                "review_status": "accepted",
            },
        }

    def _accepted_current_plan(self, investigation_id: str) -> dict[str, object]:
        return self.investigation(investigation_id)

    def check_investigation_genome_job(
        self,
        investigation_id: str,
        *,
        job_id: str,
        resume_operation: str,
        expected_plan_version_id: str,
        expected_consent_receipt_id: str,
    ) -> dict[str, object]:
        del (
            investigation_id,
            job_id,
            resume_operation,
            expected_plan_version_id,
            expected_consent_receipt_id,
        )
        self.check_calls += 1
        return dict(self.check_results.pop(0))

    def resume_public_evidence_job(
        self,
        investigation_id: str,
        *,
        execution: dict[str, object],
        job_id: str,
        resume_operation: str,
    ) -> dict[str, object]:
        del investigation_id, execution, job_id, resume_operation
        self.check_calls += 1
        return dict(self.check_results.pop(0))


class _MutableUserContext:
    def __init__(self, user_id: str = "user-capability") -> None:
        self.user_id = user_id

    def __call__(
        self,
        operation: str,
        _params: dict[str, object] | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        if operation == "genomi.describe_context":
            return {
                "status": "completed",
                "active_user_id": self.user_id,
                "active_user": {
                    "user_id": self.user_id,
                    "nickname": "Synthetic capability user",
                    "active_agi_id": None,
                    "agi_ids": [],
                },
                "active_agi_id": None,
                "active_genome_index": None,
            }
        if operation == "active_genome_index.revoke_access":
            return {"status": "completed"}
        raise AssertionError(f"unexpected Genomi operation: {operation}")


class _CapabilityJobTestSupport:
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.store_path = Path(self._temporary_directory.name) / "lab.sqlite3"
        self.store = self._open_store()
        self.store.open_workspace("user-capability", "Synthetic capability user")
        investigation = self.store.create_investigation(
            "user-capability",
            question="Investigate a synthetic molecular mechanism",
            disease_scope="Synthetic condition",
        )
        self.investigation_id = str(investigation["investigation_id"])
        observation = self.store.add_profile_observation(
            "user-capability",
            {
                "modality": "condition",
                "label": "Synthetic condition",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            },
        )
        candidate = self.store.profile_snapshot_candidate(
            "user-capability",
            investigation_id=self.investigation_id,
            purpose="Exercise harness-selected capability durability",
            observation_revision_ids=[observation["observation_revision_id"]],
        )
        self.store.create_profile_snapshot(
            "user-capability",
            workspace_session_id="session-capability-jobs",
            investigation_id=self.investigation_id,
            purpose=candidate["purpose"],
            observation_revision_ids=candidate["observation_revision_ids"],
            candidate_sha256=candidate["candidate_sha256"],
            approved=True,
        )
        committed_plan = self.store.commit_plan(
            self.investigation_id,
            {
                "summary": "Review a synthetic research question.",
                "steps": [
                    {
                        "id": "step-a",
                        "title": "Review the approved evidence scope",
                        "capabilities": [PROFILE_PROJECT],
                        "proposed_agent_role": "evidence_reviewer",
                    }
                ],
                "capability_requests": [self._request()],
            },
        )
        self.plan_version_id = str(committed_plan["plan_version_id"])
        current_plan = self.store.get_investigation(self.investigation_id)[
            "current_plan_version"
        ]
        self.store.accept_plan(
            self.investigation_id,
            plan_version_id=self.plan_version_id,
            user_id="user-capability",
            workspace_session_id="session-capability-jobs",
            plan_sha256=current_plan["plan_sha256"],
            approved=True,
        )

    def _open_store(self) -> GenomiLabStore:
        return GenomiLabStore(
            self.store_path,
            key_provider=TEST_LAB_KEY_PROVIDER,
        )

    @staticmethod
    def _request(
        *,
        request_id: str = "request-a",
        capability: str = PROFILE_PROJECT,
        parameters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "id": request_id,
            "step_id": "step-a",
            "assigned_agent_role": "evidence_reviewer",
            "capability": capability,
            "parameters": parameters or {},
        }

    def _execute(
        self,
        application: InvestigationCapabilityMixin,
        request: dict[str, object],
        *,
        approval: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return application._execute_capability_request_idempotently(
            self.investigation_id,
            request,
            approval=approval,
            plan_version_id=self.plan_version_id,
        )


class GenomiLabCapabilityJobTests(_CapabilityJobTestSupport, unittest.TestCase):
    def test_concurrent_duplicate_is_claimed_before_side_effect_and_not_run_twice(
        self,
    ) -> None:
        started = threading.Event()
        release = threading.Event()
        application = _DurableCapabilityApplication(
            self.store,
            outcome={"status": "committed", "value": "one"},
            started=started,
            release=release,
        )
        first_results: list[dict[str, object]] = []
        first = threading.Thread(
            target=lambda: first_results.append(
                self._execute(application, self._request())
            )
        )
        first.start()
        self.assertTrue(started.wait(timeout=5))

        duplicate = self._execute(application, self._request())

        self.assertEqual(duplicate["status"], "in_progress")
        self.assertEqual(duplicate["resume_operation"], CAPABILITY_RETRY_OPERATION)
        self.assertEqual(application.calls, 1)
        release.set()
        first.join(timeout=5)
        self.assertFalse(first.is_alive())
        self.assertEqual(first_results, [{"status": "committed", "value": "one"}])

        replay = self._execute(application, self._request())
        self.assertEqual(replay, first_results[0])
        self.assertEqual(application.calls, 1)
        execution = self.store.get_capability_execution(
            self.investigation_id, self.plan_version_id, "request-a"
        )
        assert execution is not None
        self.assertEqual(execution["status"], "completed")
        self.assertEqual(len(execution["attempts"]), 1)
        self.assertTrue(execution["attempts"][0]["claim_job_id"])

    def test_request_fingerprint_collision_is_rejected_without_another_side_effect(
        self,
    ) -> None:
        application = _DurableCapabilityApplication(
            self.store, outcome={"status": "committed"}
        )
        self._execute(application, self._request())
        changed = self._request(parameters={"unexpected": True})

        with self.assertRaisesRegex(ValueError, "different parameters"):
            self._execute(application, changed)

        self.assertEqual(application.calls, 1)

    def test_exact_approval_continuation_preserves_both_attempts(self) -> None:
        application = _ApprovalCapabilityApplication(self.store)
        request = self._request(capability=PUBLIC_EVIDENCE_RETRIEVE)
        initial = self._execute(application, request)
        self.assertEqual(initial["status"], "approval_required")
        approval = {
            "request_id": "request-a",
            "approved": True,
            "recipient_provider": "gxl_paperclip",
            "payload_sha256": "a" * 64,
        }

        completed = self._execute(application, request, approval=approval)
        replay = self._execute(application, request, approval=approval)

        self.assertEqual(completed["status"], "committed")
        self.assertEqual(replay, completed)
        self.assertEqual(application.calls, 2)
        execution = self.store.get_capability_execution(
            self.investigation_id, self.plan_version_id, "request-a"
        )
        assert execution is not None
        self.assertEqual(execution["status"], "completed")
        self.assertEqual(
            [attempt["attempt_kind"] for attempt in execution["attempts"]],
            ["initial", "approval_continuation"],
        )
        self.assertEqual(execution["attempts"][0]["status"], "approval_required")
        self.assertEqual(
            execution["attempts"][0]["result"]["candidate"]["payload_sha256"],
            "a" * 64,
        )
        self.assertEqual(execution["attempts"][1]["approval_provider"], "gxl_paperclip")
        self.assertEqual(execution["attempts"][1]["approval_payload_sha256"], "a" * 64)

    def test_changed_approval_is_rejected_without_overwriting_preview_attempt(
        self,
    ) -> None:
        application = _ApprovalCapabilityApplication(self.store)
        request = self._request(capability=PUBLIC_EVIDENCE_RETRIEVE)
        self._execute(application, request)

        with self.assertRaisesRegex(Exception, "changed after preview"):
            self._execute(
                application,
                request,
                approval={
                    "request_id": "request-a",
                    "approved": True,
                    "recipient_provider": "other-provider",
                    "payload_sha256": "a" * 64,
                },
            )

        execution = self.store.get_capability_execution(
            self.investigation_id, self.plan_version_id, "request-a"
        )
        assert execution is not None
        self.assertEqual(execution["status"], "approval_required")
        self.assertEqual(len(execution["attempts"]), 1)
        self.assertEqual(application.calls, 1)

        with self.assertRaisesRegex(Exception, "request changed after preview"):
            self._execute(
                application,
                request,
                approval={
                    "request_id": "request-other",
                    "approved": True,
                    "recipient_provider": "gxl_paperclip",
                    "payload_sha256": "a" * 64,
                },
            )

    def test_failed_attempt_is_durable_and_is_not_retried(self) -> None:
        application = _DurableCapabilityApplication(
            self.store, outcome=ValueError("synthetic invalid capability result")
        )

        first = self._execute(application, self._request())
        replay = self._execute(application, self._request())

        self.assertEqual(first["status"], "capability_request_rejected")
        self.assertEqual(replay, first)
        self.assertEqual(application.calls, 1)
        execution = self.store.get_capability_execution(
            self.investigation_id, self.plan_version_id, "request-a"
        )
        assert execution is not None
        self.assertEqual(execution["status"], "failed")

    def test_upstream_job_is_persisted_and_reloaded_without_duplicate_dispatch(
        self,
    ) -> None:
        application = _DurableCapabilityApplication(
            self.store,
            outcome={
                "status": "committed",
                "provider_result": {
                    "status": "in_progress",
                    "job_id": "paperclip-job-a",
                    "resume_operation": "paperclip.check_background_job",
                    "poll_after_seconds": 3,
                },
            },
        )
        first = self._execute(application, self._request())
        self.assertEqual(first["status"], "in_progress")
        self.assertEqual(first["job_id"], "paperclip-job-a")

        reopened_application = _DurableCapabilityApplication(
            self._open_store(), outcome={"status": "committed", "wrong": True}
        )
        replay = self._execute(reopened_application, self._request())

        self.assertEqual(replay, first)
        self.assertEqual(reopened_application.calls, 0)
        execution = reopened_application.store.get_capability_execution(
            self.investigation_id, self.plan_version_id, "request-a"
        )
        assert execution is not None
        self.assertEqual(execution["status"], "in_progress")
        self.assertEqual(execution["job_id"], "paperclip-job-a")
        self.assertEqual(
            execution["resume_operation"], "paperclip.check_background_job"
        )

    def test_unresolved_local_claim_can_be_reconciled_without_dispatch(self) -> None:
        request = self._request()
        claimed = self.store.claim_capability_execution(
            investigation_id=self.investigation_id,
            plan_version_id=self.plan_version_id,
            consent_receipt_id=self.store.get_investigation(self.investigation_id)[
                "active_consent_receipt_id"
            ],
            request_id=request["id"],
            capability=request["capability"],
            request_fingerprint="b" * 64,
            attempt_fingerprint="c" * 64,
            attempt_kind="initial",
        )

        reopened = self._open_store()
        persisted = reopened.get_capability_execution(
            self.investigation_id, self.plan_version_id, "request-a"
        )
        assert persisted is not None
        self.assertEqual(persisted["status"], "in_progress")
        reconciled = reopened.reconcile_capability_execution(
            str(claimed["capability_execution_id"]),
            expected_job_id=str(claimed["job_id"]),
        )

        self.assertEqual(reconciled["status"], "failed")
        self.assertEqual(
            reconciled["result"]["status"],
            "capability_dispatch_outcome_unknown",
        )
        self.assertFalse(reconciled["result"]["retry_safe"])


class _CapabilityJobResumeSupport(_CapabilityJobTestSupport):
    def _persist_upstream_job(
        self,
        *,
        capability: str,
        job_id: str,
        resume_operation: str,
    ) -> dict[str, object]:
        request = self._request(capability=capability)
        application = _DurableCapabilityApplication(
            self.store,
            outcome={
                "status": "in_progress",
                "job_id": job_id,
                "resume_operation": resume_operation,
                "poll_after_seconds": 2,
            },
        )
        self._execute(application, request)
        return request

    def _check_payload(
        self,
        *,
        job_id: str,
        resume_operation: str,
        plan_version_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "request_id": "request-a",
            "plan_version_id": plan_version_id or self.plan_version_id,
            "job_id": job_id,
            "resume_operation": resume_operation,
        }

    @staticmethod
    def _public_evidence_parameters() -> dict[str, object]:
        return {
            "operation": "search",
            "query": "Synthetic disease",
            "query_terms": ["Synthetic disease"],
            "filters": {},
            "source_family": "literature",
            "purpose": (
                "Investigate disease relevance against the approved molecular profile"
            ),
        }

    @classmethod
    def _public_evidence_plan(cls, *, summary: str) -> dict[str, object]:
        return {
            "summary": summary,
            "steps": [
                {
                    "id": "step-public",
                    "title": "Review public disease evidence",
                    "capabilities": [PUBLIC_EVIDENCE_RETRIEVE],
                    "proposed_agent_role": "evidence_reviewer",
                }
            ],
            "capability_requests": [
                {
                    "id": "request-public",
                    "step_id": "step-public",
                    "assigned_agent_role": "evidence_reviewer",
                    "capability": PUBLIC_EVIDENCE_RETRIEVE,
                    "parameters": cls._public_evidence_parameters(),
                }
            ],
        }

    @staticmethod
    def _completed_direct_response() -> dict[str, object]:
        return {
            "status": "in_scope_empty",
            "source_family": "literature",
            "records": [],
            "coverage": {
                "consulted": ["Synthetic PubMed scope"],
                "misses": ["synthetic disease mechanism"],
            },
        }

    def _start_direct_evidence_job(
        self,
        *,
        session_id: str,
        on_poll: Any | None = None,
    ) -> dict[str, Any]:
        context = _MutableUserContext()
        service = GenomiLabService(
            store=self._open_store(),
            session_id=session_id,
            operation_call=context,
            harness_adapter=SimulatedHarnessAdapter(),
        )
        self.addCleanup(service.close)
        state: dict[str, Any] = {
            "service": service,
            "context": context,
            "initial_calls": [],
            "poll_calls": [],
        }
        job_id = f"pubmed-job-{session_id}"
        resume_operation = "pubmed.check_background_job"

        def initial_transport(
            operation: PaperclipOperation, request: EvidenceRequest
        ) -> dict[str, object]:
            state["initial_calls"].append((operation, request.query))
            return {
                "status": "in_progress",
                "source_family": "literature",
                "records": [],
                "job_id": job_id,
                "resume_operation": resume_operation,
                "poll_after_seconds": 1,
            }

        def job_transport(
            operation: PaperclipOperation,
            request: EvidenceRequest,
            returned_job_id: str,
        ) -> dict[str, object]:
            state["poll_calls"].append((operation, request.query, returned_job_id))
            if on_poll is not None:
                return on_poll(state)
            return self._completed_direct_response()

        direct = DirectEvidenceSource(
            source_family=SourceFamily.LITERATURE,
            provider="pubmed",
            destination="https://pubmed.ncbi.nlm.nih.gov/",
            transport=initial_transport,
            background_job_transport=job_transport,
            background_job_resume_operation=resume_operation,
        )
        service.configure_evidence_gateway(
            direct_sources={SourceFamily.LITERATURE: direct}
        )
        service.bootstrap_workspace()
        investigation = service.create_investigation(
            {
                "question": "What public evidence could explain this synthetic disease?",
                "disease_scope": "Synthetic disease",
            }
        )
        investigation_id = str(investigation["investigation_id"])
        observation = service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Synthetic disease",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            }
        )
        context_candidate = service.investigation_context_candidate(
            investigation_id,
            {
                "purpose": "Retrieve public evidence for the approved disease question",
                "observation_revision_ids": [observation["observation_revision_id"]],
            },
        )
        service.approve_investigation_context(
            investigation_id,
            {
                key: context_candidate[key]
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
        service.store.commit_plan(
            investigation_id,
            self._public_evidence_plan(summary="Review the synthetic evidence scope."),
        )
        current_plan = service.investigation(investigation_id)["current_plan_version"]
        service.accept_current_plan(
            investigation_id,
            {
                "plan_version_id": current_plan["plan_version_id"],
                "plan_sha256": current_plan["plan_sha256"],
                "approved": True,
            },
        )
        service.store.bind_harness_task(
            investigation_id,
            command_id=f"planning-binding-{session_id}",
            host_id=service.harness_adapter.manifest.adapter_id,
            task_id=f"planning-task-{session_id}",
            run_id=f"planning-run-{session_id}",
            harness_status="waiting",
            harness_revision=1,
        )
        command_id = f"execution-command-{session_id}"
        execution_preview = service.harness_disclosure_candidate(
            investigation_id,
            operation="replace_task_binding",
            instruction="Execute the exact accepted public-evidence request.",
            artifact_kind="execution_report",
            reason="Run the separately approved evidence execution task.",
            command_id=command_id,
            expected_revision=1,
        )
        execution = service.replace_harness_binding(
            investigation_id,
            {
                "approved": True,
                "payload_sha256": execution_preview["payload_sha256"],
                "command_id": command_id,
                "expected_revision": 1,
                "instruction": "Execute the exact accepted public-evidence request.",
                "artifact_kind": "execution_report",
                "reason": "Run the separately approved evidence execution task.",
            },
        )
        self.assertEqual(execution["status"], "accepted")
        self.assertEqual(len(execution["capability_results"]), 1)
        preview = execution["capability_results"][0]["result"]["candidate"]
        launched = service.continue_harness_capability_after_approval(
            investigation_id,
            {
                "request_id": "request-public",
                "approved": True,
                "recipient_provider": preview["selected_provider"],
                "payload_sha256": preview["payload_sha256"],
            },
        )
        self.assertEqual(launched["status"], "in_progress")
        activity = service.store.workspace_activity("user-capability")
        receipts = [
            item
            for item in activity["outbound_disclosures"]
            if item["recipient_kind"] == "evidence_provider"
            and item["revoked_at"] is None
        ]
        self.assertEqual(len(receipts), 1)
        state.update(
            {
                "direct_source": direct,
                "investigation_id": investigation_id,
                "plan_version_id": current_plan["plan_version_id"],
                "job_id": job_id,
                "resume_operation": resume_operation,
                "receipt_id": receipts[0]["disclosure_receipt_id"],
                "check_payload": {
                    "request_id": "request-public",
                    "plan_version_id": current_plan["plan_version_id"],
                    "job_id": job_id,
                    "resume_operation": resume_operation,
                },
            }
        )
        return state
