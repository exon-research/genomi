from __future__ import annotations

from unittest import mock

from genomi.lab import agi_authority as investigation_access
from genomi.lab.service import LabError

from tests.genomilab_e2e_support import GenomiLabEndToEndCase, PATIENT_A_VCF


class GenomiLabContextRefreshEndToEndTests(GenomiLabEndToEndCase):
    """Exercise context refresh, revocation, rollback, and brief versioning."""

    def test_changed_context_requires_fresh_harness_basis_and_versions_brief(self) -> None:
        self._intake_current_user(
            PATIENT_A_VCF,
            nickname="Synthetic patient A",
            source_name="patient-a-refresh.vcf",
        )
        self.service.bootstrap_workspace()
        records = self._add_molecular_profile(self.service)
        investigation = self.service.create_investigation(
            {
                "question": "Could the molecular profile help investigate this condition?",
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        investigation_id = str(investigation["investigation_id"])
        self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="refresh-initial-plan",
            operation="start_task_run",
            artifact_kind="plan",
        )
        initial_snapshot = self._approve_patient_context(
            self.service, investigation_id, records
        )
        self.assertEqual(initial_snapshot["version"], 1)

        # The harness replans against the newly approved context, executes the
        # exact Genomi query it selected, then registers its bounded hypothesis
        # and gap on a second pass over the committed evidence.
        self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="refresh-initial-context-plan",
            operation="send_task_message",
            instruction="Replan using the approved molecular context.",
            artifact_kind="plan",
        )
        self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="refresh-initial-synthesis-plan",
            operation="replace_task_binding",
            instruction="Replan using the committed evidence and register bounded findings.",
            artifact_kind="plan",
            reason="Start a fresh tool-free planning task after evidence changed.",
        )
        first_brief_result = self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="refresh-initial-brief",
            operation="send_task_message",
            instruction="Draft the current patient-friendly research brief.",
            artifact_kind="brief_draft",
        )
        self.assertEqual(first_brief_result["committed_artifact"]["version"], 1)
        before_renewal = self.service.investigation(investigation_id)
        first_brief = dict(before_renewal["brief_versions"][0])
        first_evidence_ids = {
            item["evidence_record_id"]
            for item in before_renewal["current_evidence_records"]
        }
        first_hypothesis_ids = {
            item["hypothesis_id"] for item in before_renewal["current_hypotheses"]
        }
        self.assertEqual(before_renewal["refresh_lifecycle"]["state"], "current")

        # Reopening the application invalidates session consent, but approving
        # the exact same manifest renews authorization without inventing a new
        # profile, evidence, hypothesis, plan, or brief version.
        self.service.close()
        renewed_service = self._new_service("workspace-session-refresh-renewal")
        renewed_service.bootstrap_workspace()
        renewed = self._approve_patient_context(
            renewed_service, investigation_id, records
        )
        self.assertEqual(renewed["context_change"], "authorization_renewed")
        self.assertFalse(renewed["snapshot_created"])
        self.assertEqual(
            renewed["patient_molecular_snapshot_id"],
            initial_snapshot["patient_molecular_snapshot_id"],
        )
        self.assertEqual(renewed["version"], 1)
        self.assertNotEqual(
            renewed["consent_receipt_id"], initial_snapshot["consent_receipt_id"]
        )
        after_renewal = renewed_service.investigation(investigation_id)
        self.assertEqual(len(after_renewal["profile_snapshot_history"]), 1)
        self.assertEqual(after_renewal["brief"], first_brief["brief"])
        self.assertEqual(after_renewal["refresh_lifecycle"]["state"], "current")

        added_phenotype = renewed_service.add_profile_observation(
            {
                "modality": "phenotype",
                "label": "Newly documented exercise intolerance",
                "original_wording": "Exercise intolerance was newly documented",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
                "source_class": "patient_reported",
            }
        )
        refreshed_observation_ids = [
            records[key]["observation_revision_id"]
            for key in ("condition", "phenotype", "finding")
        ] + [added_phenotype["observation_revision_id"]]
        refresh_candidate_payload = {
            "purpose": initial_snapshot["purpose"],
            "observation_revision_ids": refreshed_observation_ids,
            "use_current_agi": True,
        }
        comparison = renewed_service.compare_investigation_context(
            investigation_id, refresh_candidate_payload
        )
        self.assertEqual(comparison["status"], "changed")
        self.assertEqual(
            comparison["comparison"]["observation_revision_ids"]["added"],
            [added_phenotype["observation_revision_id"]],
        )
        candidate = comparison["candidate"]
        refreshed_snapshot = renewed_service.approve_investigation_context(
            investigation_id,
            {
                key: candidate[key]
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
            | {"approved": True, "refresh": True},
        )
        self.assertEqual(refreshed_snapshot["context_change"], "profile_refreshed")
        self.assertEqual(refreshed_snapshot["version"], 2)
        self.assertEqual(
            refreshed_snapshot["prior_patient_molecular_snapshot_id"],
            initial_snapshot["patient_molecular_snapshot_id"],
        )
        self.assertTrue(refreshed_snapshot["brief_refresh_required"])
        self.assertEqual(
            set(
                refreshed_snapshot["evidence_snapshot"]["diff"][
                    "evidence_record_ids"
                ]["removed"]
            ),
            first_evidence_ids,
        )

        awaiting_refresh = renewed_service.investigation(investigation_id)
        self.assertEqual(awaiting_refresh["status"], "awaiting_plan")
        self.assertIsNone(awaiting_refresh["plan"])
        self.assertIsNone(awaiting_refresh["brief"])
        self.assertEqual(awaiting_refresh["current_evidence_records"], [])
        self.assertEqual(awaiting_refresh["current_hypotheses"], [])
        self.assertEqual(len(awaiting_refresh["evidence_records"]), len(first_evidence_ids))
        self.assertEqual(len(awaiting_refresh["hypotheses"]), len(first_hypothesis_ids))
        self.assertEqual(awaiting_refresh["brief_versions"], [first_brief])
        self.assertEqual(
            awaiting_refresh["refresh_lifecycle"]["state"], "replan_required"
        )
        self.assertTrue(awaiting_refresh["refresh_lifecycle"]["requires_replan"])
        self.assertTrue(
            awaiting_refresh["refresh_lifecycle"]["requires_evidence_rerun"]
        )
        self.assertTrue(
            awaiting_refresh["refresh_lifecycle"]["requires_hypothesis_refresh"]
        )
        self.assertTrue(
            awaiting_refresh["refresh_lifecycle"]["requires_new_brief"]
        )

        stale_disclosure = renewed_service.harness_disclosure_candidate(
            investigation_id,
            operation="replace_task_binding",
            instruction="Replan after the approved profile refresh.",
            artifact_kind="plan",
            reason="Start a fresh tool-free planning task after the approved context changed.",
            command_id="refresh-current-plan-preview",
        )
        disclosed_context = stale_disclosure["payload"]["approved_context"]
        self.assertNotIn("evidence_records", disclosed_context)
        self.assertNotIn("hypotheses", disclosed_context)

        self._approve_harness_call(
            renewed_service,
            investigation_id,
            command_id="refresh-current-context-plan",
            operation="replace_task_binding",
            instruction="Replan after the approved profile refresh.",
            artifact_kind="plan",
            reason="Start a fresh tool-free planning task after the approved context changed.",
        )
        after_evidence_rerun = renewed_service.investigation(investigation_id)
        second_evidence_ids = {
            item["evidence_record_id"]
            for item in after_evidence_rerun["current_evidence_records"]
        }
        self.assertTrue(second_evidence_ids)
        self.assertTrue(first_evidence_ids.isdisjoint(second_evidence_ids))
        self.assertTrue(
            after_evidence_rerun["refresh_lifecycle"]["requires_replan"]
        )
        self.assertFalse(
            after_evidence_rerun["refresh_lifecycle"]["requires_evidence_rerun"]
        )
        self.assertTrue(
            after_evidence_rerun["refresh_lifecycle"]["requires_hypothesis_refresh"]
        )

        self._approve_harness_call(
            renewed_service,
            investigation_id,
            command_id="refresh-current-synthesis-plan",
            operation="replace_task_binding",
            instruction="Replan using only the refreshed context and evidence.",
            artifact_kind="plan",
            reason="Start a fresh tool-free planning task after evidence changed.",
        )
        self._approve_harness_call(
            renewed_service,
            investigation_id,
            command_id="refresh-current-candidate-plan",
            operation="replace_task_binding",
            instruction="Register a bounded candidate only after the typed disease relation is committed.",
            artifact_kind="plan",
            reason="Start a fresh tool-free planning task after evidence changed.",
        )
        before_new_brief = renewed_service.investigation(investigation_id)
        refreshed_basis_ids = {
            item["evidence_record_id"]
            for item in before_new_brief["current_evidence_records"]
        }
        second_hypothesis_ids = {
            item["hypothesis_id"]
            for item in before_new_brief["current_hypotheses"]
        }
        self.assertTrue(second_hypothesis_ids)
        self.assertTrue(first_hypothesis_ids.isdisjoint(second_hypothesis_ids))
        self.assertEqual(
            before_new_brief["refresh_lifecycle"]["state"], "new_brief_required"
        )

        second_brief_result = self._approve_harness_call(
            renewed_service,
            investigation_id,
            command_id="refresh-current-brief",
            operation="send_task_message",
            instruction="Draft a new brief from only the refreshed basis.",
            artifact_kind="brief_draft",
        )
        second_brief = second_brief_result["committed_artifact"]
        self.assertEqual(second_brief["version"], 2)
        self.assertEqual(
            second_brief["prior_brief_version_id"], first_brief["brief_version_id"]
        )
        self.assertEqual(
            second_brief["patient_molecular_snapshot_id"],
            refreshed_snapshot["patient_molecular_snapshot_id"],
        )
        self.assertTrue(
            second_brief["diff"]["patient_molecular_snapshot"]["changed"]
        )
        self.assertEqual(
            set(
                second_brief["diff"]["evidence_snapshot"][
                    "evidence_record_ids"
                ]["removed"]
            ),
            first_evidence_ids,
        )
        self.assertEqual(
            set(
                second_brief["diff"]["evidence_snapshot"][
                    "evidence_record_ids"
                ]["added"]
            ),
            refreshed_basis_ids,
        )
        completed = renewed_service.investigation(investigation_id)
        self.assertEqual(completed["refresh_lifecycle"]["state"], "current")
        self.assertFalse(completed["refresh_lifecycle"]["requires_new_brief"])
        self.assertEqual(len(completed["profile_snapshot_history"]), 2)
        self.assertEqual(len(completed["brief_versions"]), 2)
        self.assertEqual(completed["brief_versions"][0], first_brief)
        self.assertEqual(
            completed["current_brief_version"]["brief_version_id"],
            second_brief["brief_version_id"],
        )

    def test_genome_free_refresh_revokes_the_prior_exact_agi_handle(self) -> None:
        self._intake_current_user(
            PATIENT_A_VCF,
            nickname="Synthetic patient A",
            source_name="patient-a-remove-genome.vcf",
        )
        self.service.bootstrap_workspace()
        records = self._add_molecular_profile(self.service)
        investigation = self.service.create_investigation(
            {
                "question": "Could the molecular profile help investigate this condition?",
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        investigation_id = str(investigation["investigation_id"])
        initial = self._approve_patient_context(
            self.service, investigation_id, records
        )
        old_handle = self.service._agi_authorizations[investigation_id]

        # An opaque bearer for the same investigation ID is still unusable
        # when its snapshot, consent, session, purpose, or exact scope differs
        # from the currently pinned molecular context.
        mismatched_handle = (
            investigation_access.issue_investigation_agi_authorization(
                workspace_session_id="different-workspace-session",
                user_id=str(initial["user_id"]),
                investigation_id=investigation_id,
                patient_molecular_snapshot_id="different-molecular-snapshot",
                consent_receipt_id="different-consent-receipt",
                agi_id=str(initial["agi_id"]),
                agi_snapshot_id=str(initial["agi_snapshot_id"]),
                purpose="Different approved purpose",
                genomic_scope={
                    "operation": "variant.resolve",
                    "rsid": "rs900000002",
                },
            )
        )
        self.service._agi_authorizations[investigation_id] = mismatched_handle
        with self.assertRaises(LabError) as mismatch:
            self.service.invoke_investigation_genome(
                investigation_id,
                operation="variant.resolve",
                params={"rsid": "rs900000001"},
            )
        self.assertEqual(
            mismatch.exception.code, "private_context_renewal_required"
        )
        self.assertNotIn(investigation_id, self.service._agi_authorizations)
        self.service._agi_authorizations[investigation_id] = old_handle

        candidate = self.service.investigation_context_candidate(
            investigation_id,
            {
                "purpose": initial["purpose"],
                "observation_revision_ids": initial["observation_revision_ids"],
                "use_current_agi": True,
                "exclude_genome": True,
            },
        )
        refreshed = self.service.approve_investigation_context(
            investigation_id,
            {
                key: candidate[key]
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
            | {"approved": True, "refresh": True},
        )

        self.assertEqual(refreshed["context_change"], "profile_refreshed")
        self.assertIsNone(refreshed["agi_id"])
        self.assertIsNone(refreshed["agi_snapshot_id"])
        self.assertEqual(refreshed["private_genome_access"], "not_included")
        self.assertNotIn(investigation_id, self.service._agi_authorizations)
        with self.assertRaises(LabError) as missing:
            self.service.invoke_investigation_genome(
                investigation_id,
                operation="variant.resolve",
                params={"rsid": "rs900000001"},
            )
        self.assertEqual(missing.exception.code, "private_context_required")
        with self.assertRaises(
            investigation_access.InvestigationAgiAuthorizationError
        ) as revoked:
            investigation_access.execution_context_for_investigation_authorization(
                old_handle,
                operation="variant.resolve",
                params={"rsid": "rs900000001"},
            )
        self.assertEqual(
            revoked.exception.code,
            "investigation_agi_authorization_revoked",
        )

    def test_refresh_authorization_failure_rolls_back_and_exact_retry_completes(self) -> None:
        self._intake_current_user(
            PATIENT_A_VCF,
            nickname="Synthetic patient A",
            source_name="patient-a-refresh-issuance-failure.vcf",
        )
        self.service.bootstrap_workspace()
        records = self._add_molecular_profile(self.service)
        investigation = self.service.create_investigation(
            {
                "question": "Could the molecular profile help investigate this condition?",
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        investigation_id = str(investigation["investigation_id"])
        initial = self._approve_patient_context(
            self.service, investigation_id, records
        )
        initial_handle = self.service._agi_authorizations[investigation_id]
        added = self.service.add_profile_observation(
            {
                "modality": "phenotype",
                "label": "Newly documented exercise intolerance",
                "original_wording": "Exercise intolerance was newly documented",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
                "source_class": "patient_reported",
            }
        )
        candidate = self.service.investigation_context_candidate(
            investigation_id,
            {
                "purpose": initial["purpose"],
                "observation_revision_ids": [
                    *initial["observation_revision_ids"],
                    added["observation_revision_id"],
                ],
                "use_current_agi": True,
            },
        )
        approval = {
            key: candidate[key]
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
        } | {"approved": True, "refresh": True}

        real_issuer = investigation_access.issue_investigation_agi_authorization
        issue_count = 0

        def fail_final_issuance(**claims: object) -> object:
            nonlocal issue_count
            issue_count += 1
            if issue_count == 1:
                raise investigation_access.InvestigationAgiAuthorizationError(
                    "investigation_agi_authorization_context_mismatch",
                    "Synthetic final authorization issuance failure.",
                )
            return real_issuer(**claims)

        with mock.patch(
            "genomi.lab.profile_context_application.issue_investigation_agi_authorization",
            side_effect=fail_final_issuance,
        ):
            with self.assertRaises(LabError) as failed:
                self.service.approve_investigation_context(
                    investigation_id, approval
                )
        self.assertEqual(
            failed.exception.code,
            "investigation_agi_authorization_context_mismatch",
        )
        after_failure = self.service.investigation(investigation_id)
        self.assertEqual(
            after_failure["patient_molecular_snapshot_id"],
            initial["patient_molecular_snapshot_id"],
        )
        self.assertEqual(len(after_failure["profile_snapshot_history"]), 1)
        self.assertEqual(
            after_failure["active_consent_receipt_id"],
            initial["consent_receipt_id"],
        )
        self.assertIs(
            self.service._agi_authorizations[investigation_id], initial_handle
        )

        retried = self.service.approve_investigation_context(
            investigation_id, approval
        )
        self.assertEqual(issue_count, 1)
        self.assertEqual(retried["context_change"], "profile_refreshed")
        self.assertEqual(retried["version"], 2)
        self.assertIsNotNone(retried["evidence_snapshot"])
        self.assertTrue(retried["brief_refresh_required"])
        self.assertEqual(retried["refresh_lifecycle"]["state"], "replan_required")
        after_retry = self.service.investigation(investigation_id)
        self.assertEqual(after_retry["status"], "awaiting_plan")
        self.assertEqual(len(after_retry["profile_snapshot_history"]), 2)
        self.assertIsNot(
            self.service._agi_authorizations[investigation_id], initial_handle
        )
        with self.assertRaises(
            investigation_access.InvestigationAgiAuthorizationError
        ) as revoked:
            investigation_access.execution_context_for_investigation_authorization(
                initial_handle,
                operation="variant.resolve",
                params={"rsid": "rs900000001"},
            )
        self.assertEqual(
            revoked.exception.code,
            "investigation_agi_authorization_revoked",
        )

    def test_late_refresh_failure_rolls_back_snapshot_evidence_and_consent(self) -> None:
        self._intake_current_user(
            PATIENT_A_VCF,
            nickname="Synthetic patient A",
            source_name="patient-a-refresh-late-failure.vcf",
        )
        self.service.bootstrap_workspace()
        records = self._add_molecular_profile(self.service)
        investigation = self.service.create_investigation(
            {
                "question": "Could the molecular profile help investigate this condition?",
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        investigation_id = str(investigation["investigation_id"])
        initial = self._approve_patient_context(
            self.service, investigation_id, records
        )
        initial_handle = self.service._agi_authorizations[investigation_id]
        added = self.service.add_profile_observation(
            {
                "modality": "phenotype",
                "label": "Newly documented exercise intolerance",
                "original_wording": "Exercise intolerance was newly documented",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
                "source_class": "patient_reported",
            }
        )
        candidate = self.service.investigation_context_candidate(
            investigation_id,
            {
                "purpose": initial["purpose"],
                "observation_revision_ids": [
                    *initial["observation_revision_ids"],
                    added["observation_revision_id"],
                ],
                "use_current_agi": True,
            },
        )
        approval = {
            key: candidate[key]
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
        } | {"approved": True, "refresh": True}
        staged_handles: list[object] = []
        real_issuer = investigation_access.issue_investigation_agi_authorization

        def capture_issuance(**claims: object) -> object:
            handle = real_issuer(**claims)
            staged_handles.append(handle)
            return handle

        with (
            mock.patch(
                "genomi.lab.profile_context_application.issue_investigation_agi_authorization",
                side_effect=capture_issuance,
            ),
            mock.patch.object(
                self.service.store,
                "set_investigation_status",
                side_effect=RuntimeError("synthetic late refresh failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "synthetic late refresh failure"),
        ):
            self.service.approve_investigation_context(investigation_id, approval)

        self.assertEqual(len(staged_handles), 1)
        after_failure = self.service.investigation(investigation_id)
        self.assertEqual(
            after_failure["patient_molecular_snapshot_id"],
            initial["patient_molecular_snapshot_id"],
        )
        self.assertEqual(
            after_failure["active_consent_receipt_id"], initial["consent_receipt_id"]
        )
        self.assertEqual(len(after_failure["profile_snapshot_history"]), 1)
        self.assertEqual(after_failure["evidence_snapshots"], [])
        self.assertEqual(after_failure["status"], "approved")
        self.assertIs(
            self.service._agi_authorizations[investigation_id], initial_handle
        )
        with self.assertRaises(
            investigation_access.InvestigationAgiAuthorizationError
        ) as revoked:
            investigation_access.execution_context_for_investigation_authorization(
                staged_handles[0],
                operation="variant.resolve",
                params={"rsid": "rs900000001"},
            )
        self.assertEqual(
            revoked.exception.code,
            "investigation_agi_authorization_revoked",
        )

        retried = self.service.approve_investigation_context(
            investigation_id, approval
        )
        self.assertEqual(retried["context_change"], "profile_refreshed")
        self.assertIsNotNone(retried["evidence_snapshot"])


if __name__ == "__main__":
    import unittest

    unittest.main()
