from __future__ import annotations

import unittest
from typing import Any

from genomi.lab.harness import SimulatedHarnessAdapter
from genomi.lab.investigation_capabilities import (
    GENOMI_VARIANT_RESOLVE,
    PUBLIC_EVIDENCE_RETRIEVE,
)
from genomi.lab.provider_policy import SourceFamily
from genomi.lab.service import GenomiLabService, LabError
from tests.test_genomilab_capability_jobs import (
    _CapabilityJobResumeSupport,
    _ResumableCapabilityApplication,
)


class GenomiLabCapabilityJobResumeTests(
    _CapabilityJobResumeSupport, unittest.TestCase
):
    def test_upstream_job_check_advances_still_running_then_completed_idempotently(
        self,
    ) -> None:
        job_id = "genomi-job-a"
        resume_operation = "genomi.check_background_job"
        self._persist_upstream_job(
            capability=GENOMI_VARIANT_RESOLVE,
            job_id=job_id,
            resume_operation=resume_operation,
        )
        application = _ResumableCapabilityApplication(
            self._open_store(),
            investigation_id=self.investigation_id,
            plan_version_id=self.plan_version_id,
            capability=GENOMI_VARIANT_RESOLVE,
            check_results=[
                {
                    "status": "in_progress",
                    "job_id": job_id,
                    "resume_operation": resume_operation,
                    "poll_after_seconds": 4,
                },
                {"status": "committed", "evidence_record_id": "evidence-a"},
            ],
        )
        payload = self._check_payload(job_id=job_id, resume_operation=resume_operation)

        still_running = application.resume_harness_capability_job(
            self.investigation_id, payload
        )
        completed = application.resume_harness_capability_job(
            self.investigation_id, payload
        )
        replay = application.resume_harness_capability_job(
            self.investigation_id, payload
        )

        self.assertEqual(still_running["status"], "in_progress")
        self.assertEqual(still_running["result"]["poll_after_seconds"], 4)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["status"], "committed")
        self.assertEqual(replay, completed)
        self.assertEqual(application.check_calls, 2)

    def test_upstream_job_failure_is_terminal_and_restart_safe(self) -> None:
        job_id = "paperclip-job-a"
        resume_operation = "paperclip.check_background_job"
        self._persist_upstream_job(
            capability=PUBLIC_EVIDENCE_RETRIEVE,
            job_id=job_id,
            resume_operation=resume_operation,
        )
        application = _ResumableCapabilityApplication(
            self._open_store(),
            investigation_id=self.investigation_id,
            plan_version_id=self.plan_version_id,
            capability=PUBLIC_EVIDENCE_RETRIEVE,
            check_results=[
                {
                    "status": "source_unavailable",
                    "message": "Synthetic source unavailable.",
                    "retry_after_approval": False,
                }
            ],
        )
        payload = self._check_payload(job_id=job_id, resume_operation=resume_operation)

        failed = application.resume_harness_capability_job(
            self.investigation_id, payload
        )
        restarted = _ResumableCapabilityApplication(
            self._open_store(),
            investigation_id=self.investigation_id,
            plan_version_id=self.plan_version_id,
            capability=PUBLIC_EVIDENCE_RETRIEVE,
            check_results=[],
        )
        replay = restarted.resume_harness_capability_job(self.investigation_id, payload)

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["result"]["status"], "source_unavailable")
        self.assertEqual(replay, failed)
        self.assertEqual(restarted.check_calls, 0)

    def test_provider_job_restart_cannot_rebind_prior_private_consent(
        self,
    ) -> None:
        state = self._start_direct_evidence_job(session_id="provider-restart-one")
        original = state["service"]
        original.close()
        restarted = GenomiLabService(
            store=self._open_store(),
            session_id="provider-restart-two",
            operation_call=state["context"],
            harness_adapter=SimulatedHarnessAdapter(),
        )
        self.addCleanup(restarted.close)
        restarted.configure_evidence_gateway(
            direct_sources={SourceFamily.LITERATURE: state["direct_source"]}
        )
        restarted.bootstrap_workspace()

        with self.assertRaisesRegex(LabError, "consent is no longer active"):
            restarted.resume_harness_capability_job(
                state["investigation_id"], state["check_payload"]
            )
        self.assertEqual(state["poll_calls"], [])

        parameters = self._public_evidence_parameters()
        candidate = restarted.evidence_disclosure_candidate(
            state["investigation_id"], parameters
        )
        restarted.approve_evidence_disclosure(
            state["investigation_id"],
            {
                **parameters,
                "recipient_provider": candidate["selected_provider"],
                "payload_sha256": candidate["payload_sha256"],
                "approved": True,
            },
        )
        with self.assertRaisesRegex(LabError, "consent is no longer active"):
            restarted.resume_harness_capability_job(
                state["investigation_id"], state["check_payload"]
            )
        self.assertEqual(len(state["initial_calls"]), 1)
        self.assertEqual(state["poll_calls"], [])
        persisted = restarted.investigation(state["investigation_id"])
        self.assertEqual(persisted["evidence_records"], [])

    def test_provider_result_revoked_during_poll_is_not_committed(self) -> None:
        def revoke_before_return(state: dict[str, Any]) -> dict[str, object]:
            state["service"].store.revoke_outbound_disclosure(state["receipt_id"])
            return self._completed_direct_response()

        state = self._start_direct_evidence_job(
            session_id="provider-revocation-race",
            on_poll=revoke_before_return,
        )

        with self.assertRaisesRegex(LabError, "disclosure changed"):
            state["service"].resume_harness_capability_job(
                state["investigation_id"], state["check_payload"]
            )

        persisted = state["service"].store.get_investigation(state["investigation_id"])
        self.assertEqual(persisted["evidence_records"], [])
        execution = state["service"].store.get_capability_execution(
            state["investigation_id"],
            state["plan_version_id"],
            "request-public",
        )
        assert execution is not None
        self.assertEqual(execution["status"], "in_progress")
        self.assertEqual(len(state["initial_calls"]), 1)
        self.assertEqual(len(state["poll_calls"]), 1)

    def test_provider_late_result_fails_closed_after_context_or_plan_change(
        self,
    ) -> None:
        def switch_user(state: dict[str, Any]) -> dict[str, object]:
            state["context"].user_id = "different-user"
            return self._completed_direct_response()

        def close_session(state: dict[str, Any]) -> dict[str, object]:
            state["service"].close()
            return self._completed_direct_response()

        def supersede_plan(state: dict[str, Any]) -> dict[str, object]:
            superseding_plan = state["service"].store.commit_plan(
                state["investigation_id"],
                self._public_evidence_plan(summary="Review the current evidence plan."),
            )
            state["superseding_plan_version_id"] = superseding_plan["plan_version_id"]
            return self._completed_direct_response()

        cases = {
            "user_switch": switch_user,
            "session_close": close_session,
            "plan_supersession": supersede_plan,
        }
        for name, callback in cases.items():
            with self.subTest(name=name):
                state = self._start_direct_evidence_job(
                    session_id=f"provider-race-{name}",
                    on_poll=callback,
                )
                with self.assertRaises(LabError):
                    state["service"].resume_harness_capability_job(
                        state["investigation_id"], state["check_payload"]
                    )
                persisted = state["service"].store.get_investigation(
                    state["investigation_id"]
                )
                self.assertEqual(persisted["evidence_records"], [])
                if name == "plan_supersession":
                    self.assertEqual(
                        persisted["current_plan_version"]["plan_version_id"],
                        state["superseding_plan_version_id"],
                    )
                    self.assertEqual(
                        persisted["current_plan_version"]["review_status"],
                        "proposed",
                    )
                self.assertEqual(len(state["initial_calls"]), 1)
                self.assertEqual(len(state["poll_calls"]), 1)

    def test_wrong_job_operation_or_superseded_plan_never_calls_owner(self) -> None:
        job_id = "genomi-job-a"
        resume_operation = "genomi.check_background_job"
        self._persist_upstream_job(
            capability=GENOMI_VARIANT_RESOLVE,
            job_id=job_id,
            resume_operation=resume_operation,
        )
        application = _ResumableCapabilityApplication(
            self.store,
            investigation_id=self.investigation_id,
            plan_version_id=self.plan_version_id,
            capability=GENOMI_VARIANT_RESOLVE,
            check_results=[],
        )
        cases = [
            self._check_payload(
                job_id="genomi-job-other", resume_operation=resume_operation
            ),
            self._check_payload(
                job_id=job_id,
                resume_operation="paperclip.check_background_job",
            ),
            self._check_payload(
                job_id=job_id,
                resume_operation=resume_operation,
                plan_version_id="plan-superseded",
            ),
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(Exception):
                application.resume_harness_capability_job(
                    self.investigation_id, payload
                )
        self.assertEqual(application.check_calls, 0)
