from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genomi.lab.harness import SimulatedHarnessAdapter
from genomi.lab.service import GenomiLabService, LabError
from genomi.lab.store import GenomiLabStore

from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


class _CurrentUserWithoutGenome:
    def __call__(
        self, operation: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        del params
        if operation == "genomi.describe_context":
            return {
                "status": "completed",
                "active_user_id": "authorization-user",
                "active_user": {
                    "user_id": "authorization-user",
                    "nickname": "Authorization Patient",
                    "active_agi_id": None,
                    "agi_ids": [],
                },
                "has_active_genome_index": False,
                "active_agi_id": None,
                "active_genome_index": None,
            }
        if operation == "active_genome_index.revoke_access":
            return {"status": "completed"}
        raise AssertionError(f"unexpected Genomi operation: {operation}")


class InvestigationAuthorizationFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "genomilab.sqlite3"
        self.service = GenomiLabService(
            store=GenomiLabStore(path, key_provider=TEST_LAB_KEY_PROVIDER),
            session_id="authorization-session",
            operation_call=_CurrentUserWithoutGenome(),
            harness_adapter=SimulatedHarnessAdapter(
                adapter_id="authorization-test-harness"
            ),
        )
        self.addCleanup(self.service.close)
        self.service.store.open_workspace(
            "authorization-user", "Authorization Patient"
        )
        self.observation = self.service.add_profile_observation(
            {
                "modality": "condition",
                "label": "Synthetic condition",
                "original_wording": "Synthetic condition",
                "assertion_status": "present",
                "source_class": "patient_reported",
            }
        )
        investigation = self.service.create_investigation(
            {
                "question": "What could be driving this synthetic condition?",
            }
        )
        self.investigation_id = str(investigation["investigation_id"])

    def _candidate(self) -> dict[str, object]:
        return self.service.investigation_authorization_candidate(
            self.investigation_id,
            {
                "purpose": "Investigate the synthetic condition",
                "observation_revision_ids": [
                    self.observation["observation_revision_id"]
                ],
            },
        )

    @staticmethod
    def _approval(candidate: dict[str, object]) -> dict[str, object]:
        return {
            key: value
            for key, value in candidate.items()
            if key
            not in {
                "status",
                "requires_explicit_approval",
                "user_id",
                "investigation_id",
            }
        } | {"approved": True}

    def test_one_authorization_runs_routine_flow_and_retries_exactly_once(
        self,
    ) -> None:
        candidate = self._candidate()
        self.assertEqual(candidate["status"], "authorization_required")
        self.assertEqual(candidate["authorization_scope"]["providers"], [])

        approval = self._approval(candidate)
        started = self.service.authorize_and_start_investigation(
            self.investigation_id, approval
        )
        self.assertFalse(started["retry_reused"])

        investigation = self.service.investigation(self.investigation_id)
        self.assertEqual(
            investigation["current_plan_version"]["review_status"], "accepted"
        )
        self.assertEqual(investigation["status"], "completed")
        self.assertEqual(len(investigation["brief_versions"]), 1)

        activity = self.service.store.workspace_activity("authorization-user")
        self.assertEqual(len(activity["context_approvals"]), 1)
        self.assertEqual(len(activity["investigation_authorizations"]), 1)
        self.assertEqual(len(activity["plan_acceptances"]), 1)
        self.assertTrue(
            activity["plan_acceptances"][0]["authorization_receipt_id"]
        )
        self.assertGreaterEqual(len(activity["outbound_disclosures"]), 3)
        self.assertTrue(
            all(
                disclosure["authorization_receipt_id"]
                for disclosure in activity["outbound_disclosures"]
            )
        )

        followed_up = self.service.send_authorized_investigation_message(
            self.investigation_id,
            {"message": "Explain the strongest limitation in plain language."},
        )
        self.assertEqual(followed_up["status"], "accepted")
        after_follow_up = self.service.store.workspace_activity(
            "authorization-user"
        )
        self.assertEqual(
            len(after_follow_up["investigation_authorizations"]), 1
        )
        self.assertEqual(
            len(after_follow_up["outbound_disclosures"]),
            len(activity["outbound_disclosures"]) + 1,
        )
        self.assertTrue(
            after_follow_up["outbound_disclosures"][0][
                "authorization_receipt_id"
            ]
        )

        retried = self.service.authorize_and_start_investigation(
            self.investigation_id, approval
        )
        self.assertTrue(retried["retry_reused"])
        retried_activity = self.service.store.workspace_activity(
            "authorization-user"
        )
        self.assertEqual(
            len(retried_activity["outbound_disclosures"]),
            len(after_follow_up["outbound_disclosures"]),
        )
        self.assertEqual(
            len(retried_activity["investigation_authorizations"]), 1
        )
        self.assertEqual(
            self.service.investigation(self.investigation_id)["status"],
            "completed",
        )

    def test_retry_resumes_after_committed_plan_before_automatic_continuation(
        self,
    ) -> None:
        candidate = self._candidate()
        approval = self._approval(candidate)
        continue_result = self.service._continue_authorized_harness_result
        self.service._continue_authorized_harness_result = (
            lambda *_args, **_kwargs: None
        )
        try:
            self.service.authorize_and_start_investigation(
                self.investigation_id, approval
            )
        finally:
            self.service._continue_authorized_harness_result = continue_result

        interrupted = self.service.investigation(self.investigation_id)
        self.assertEqual(interrupted["status"], "awaiting_plan_review")
        self.assertEqual(
            interrupted["current_plan_version"]["review_status"], "proposed"
        )

        retried = self.service.authorize_and_start_investigation(
            self.investigation_id, approval
        )
        self.assertTrue(retried["retry_reused"])
        resumed = self.service.investigation(self.investigation_id)
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(len(resumed["brief_versions"]), 1)

    def test_retry_repairs_disclosure_saved_before_parent_derivation(self) -> None:
        candidate = self._candidate()
        approval = self._approval(candidate)
        derive = self.service.store.derive_investigation_authorization_subject

        def interrupt_derivation(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("simulated interruption before derivation")

        self.service.store.derive_investigation_authorization_subject = (
            interrupt_derivation
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "before derivation"):
                self.service.authorize_and_start_investigation(
                    self.investigation_id, approval
                )
        finally:
            self.service.store.derive_investigation_authorization_subject = derive

        activity = self.service.store.workspace_activity("authorization-user")
        self.assertEqual(len(activity["investigation_authorizations"]), 1)
        self.assertEqual(len(activity["outbound_disclosures"]), 1)
        self.assertIsNone(
            activity["outbound_disclosures"][0]["authorization_receipt_id"]
        )

        retried = self.service.authorize_and_start_investigation(
            self.investigation_id, approval
        )
        self.assertTrue(retried["retry_reused"])
        resumed = self.service.investigation(self.investigation_id)
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(len(resumed["brief_versions"]), 1)
        linked = self.service.store.workspace_activity("authorization-user")
        self.assertTrue(
            all(
                item["authorization_receipt_id"]
                for item in linked["outbound_disclosures"]
            )
        )

    def test_retry_repairs_command_reserved_before_disclosure_receipt(self) -> None:
        candidate = self._candidate()
        approval = self._approval(candidate)
        create_receipt = self.service.store.create_outbound_disclosure_receipt
        interrupted = False

        def interrupt_once(*args: object, **kwargs: object) -> object:
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise RuntimeError("simulated interruption before disclosure receipt")
            return create_receipt(*args, **kwargs)

        self.service.store.create_outbound_disclosure_receipt = interrupt_once
        try:
            with self.assertRaisesRegex(RuntimeError, "before disclosure receipt"):
                self.service.authorize_and_start_investigation(
                    self.investigation_id, approval
                )
        finally:
            self.service.store.create_outbound_disclosure_receipt = create_receipt

        with self.service.store._connect() as connection:
            command_row = connection.execute(
                "SELECT command_id FROM harness_commands ORDER BY created_at LIMIT 1"
            ).fetchone()
        command = self.service.store.harness_command(command_row["command_id"])
        self.assertEqual(command["command_state"], "accepted")
        self.assertIsNone(command["disclosure_receipt_id"])

        retried = self.service.authorize_and_start_investigation(
            self.investigation_id, approval
        )
        self.assertTrue(retried["retry_reused"])
        resumed = self.service.investigation(self.investigation_id)
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(len(resumed["brief_versions"]), 1)
        activity = self.service.store.workspace_activity("authorization-user")
        self.assertTrue(
            all(
                item["authorization_receipt_id"]
                for item in activity["outbound_disclosures"]
            )
        )

    def test_candidate_tampering_and_revocation_fail_closed(self) -> None:
        candidate = self._candidate()
        tampered = self._approval(candidate)
        tampered["authorization_scope"] = {
            **candidate["authorization_scope"],
            "providers": ["paperclip"],
        }
        with self.assertRaisesRegex(LabError, "changed after it was reviewed"):
            self.service.authorize_and_start_investigation(
                self.investigation_id, tampered
            )

        self.service.authorize_and_start_investigation(
            self.investigation_id, self._approval(candidate)
        )
        self.service.revoke_private_context(self.investigation_id)
        with self.assertRaisesRegex(LabError, "authorize this investigation"):
            self.service.send_authorized_investigation_message(
                self.investigation_id,
                {"message": "Continue the investigation."},
            )

    def test_revoked_parent_blocks_provider_continuation_and_job_check(self) -> None:
        candidate = self._candidate()
        self.service.authorize_and_start_investigation(
            self.investigation_id, self._approval(candidate)
        )
        investigation = self.service.investigation(self.investigation_id)
        consent_id = str(investigation["active_consent_receipt_id"])
        activity = self.service.store.workspace_activity("authorization-user")
        authorization_id = str(
            activity["investigation_authorizations"][0][
                "authorization_receipt_id"
            ]
        )
        self.assertTrue(
            self.service.store.revoke_investigation_authorization(authorization_id)
        )
        self.assertIsNone(self.service.store.consent_receipt(consent_id)["revoked_at"])

        lower_calls: list[str] = []
        self.service._continue_harness_capability_after_approval = (
            lambda *_args, **_kwargs: lower_calls.append("provider") or {}
        )
        self.service._resume_harness_capability_job = (
            lambda *_args, **_kwargs: lower_calls.append("job") or {}
        )

        with self.assertRaises(LabError) as provider:
            self.service.approve_and_continue_harness_capability(
                self.investigation_id, {}
            )
        self.assertEqual(provider.exception.code, "investigation_authorization_required")
        with self.assertRaises(LabError) as job:
            self.service.check_and_continue_harness_capability(
                self.investigation_id, {}
            )
        self.assertEqual(job.exception.code, "investigation_authorization_required")
        self.assertEqual(lower_calls, [])


if __name__ == "__main__":
    unittest.main()
