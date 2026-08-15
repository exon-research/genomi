from __future__ import annotations

import json

from genomi.lab.service import LabError
from genomi.operations import call_operation

from tests.genomilab_e2e_support import (
    GenomiLabEndToEndCase,
    PATIENT_A_VCF,
    PATIENT_B_VCF,
)


class GenomiLabEndToEndTests(GenomiLabEndToEndCase):
    """Exercise intake, evidence synthesis, persistence, and user isolation."""

    def test_plan_is_proposed_before_any_declared_capability_executes(self) -> None:
        self._intake_current_user(
            PATIENT_A_VCF,
            nickname="Synthetic plan reviewer",
            source_name="patient-plan-review.vcf",
        )
        self.service.bootstrap_workspace()
        records = self._add_molecular_profile(self.service)
        investigation = self.service.create_investigation(
            {
                "question": "Could this reported finding relate to the condition?",
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        investigation_id = str(investigation["investigation_id"])
        self._approve_patient_context(self.service, investigation_id, records)

        proposed = self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="plan-review-proposal",
            operation="start_task_run",
            artifact_kind="plan",
            accept_plan=False,
        )
        self.assertEqual(proposed["capability_results"], [])
        before = self.service.investigation(investigation_id)
        self.assertEqual(before["status"], "awaiting_plan_review")
        self.assertEqual(before["current_plan_version"]["review_status"], "proposed")
        self.assertEqual(before["current_evidence_records"], [])

        with self.assertRaisesRegex(LabError, "plan changed"):
            self.service._accept_plan_for_conformance(
                investigation_id,
                {
                    "approved": True,
                    "plan_version_id": before["current_plan_version"][
                        "plan_version_id"
                    ],
                    "plan_sha256": "0" * 64,
                },
            )
        accepted = self.service._accept_plan_for_conformance(
            investigation_id,
            {
                "approved": True,
                "plan_version_id": before["current_plan_version"]["plan_version_id"],
                "plan_sha256": before["current_plan_version"]["plan_sha256"],
            },
        )
        self.assertEqual(accepted["status"], "accepted")
        after = self.service.investigation(investigation_id)
        self.assertEqual(after["current_plan_version"]["review_status"], "accepted")
        self.assertEqual(accepted["capability_results"], [])
        self.assertEqual(after["current_capability_executions"], [])
        self.assertEqual(after["current_evidence_records"], [])
        next_action = accepted["next_harness_action"]
        self.assertIsInstance(next_action, dict)
        self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="plan-review-execution",
            operation=str(next_action["operation"]),
            instruction=str(next_action["instruction"]),
            artifact_kind=str(next_action["artifact_kind"]),
            reason=str(next_action["reason"]),
            accept_plan=False,
        )
        after = self.service.investigation(investigation_id)
        self.assertTrue(after["current_capability_executions"])
        self.assertTrue(after["current_evidence_records"])

    def test_patient_profile_to_harness_plan_evidence_hypothesis_and_brief(
        self,
    ) -> None:
        parsed, context = self._intake_current_user(
            PATIENT_A_VCF,
            nickname="Synthetic patient A",
            source_name="patient-a.vcf",
        )
        bootstrap = self.service.bootstrap_workspace()
        user_id = str(context["active_user_id"])
        self.assertEqual(bootstrap["status"], "ready")
        self.assertEqual(bootstrap["workspace"]["user_id"], user_id)
        self.assertEqual(
            bootstrap["workspace"]["profile"]["genome"]["agi_snapshot_id"],
            parsed["active_genome_index"]["agi_snapshot_id"],
        )

        records = self._add_molecular_profile(self.service)
        investigation = self.service.create_investigation(
            {
                "question": "Could the reported molecular finding help explain the patient's condition?",
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        investigation_id = str(investigation["investigation_id"])

        plan_result = self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="e2e-plan-command",
            operation="start_task_run",
            artifact_kind="plan",
        )
        plan = plan_result["committed_artifact"]["plan"]
        self.assertEqual(plan_result["committed_artifact"]["version"], 1)
        self.assertTrue(plan["proposed_agent_roles"])
        self.assertEqual(
            plan["steps"][0]["proposed_agent_role"],
            "patient_context_reviewer",
        )

        snapshot = self._approve_patient_context(
            self.service, investigation_id, records
        )
        projected_profile = self.service.investigation_profile(investigation_id)
        self.assertEqual(
            [item["artifact_id"] for item in projected_profile["source_artifacts"]],
            [records["artifact"]["artifact_id"]],
        )
        self.assertEqual(
            [item["specimen_id"] for item in projected_profile["specimens"]],
            [records["specimen"]["specimen_id"]],
        )
        self.assertEqual(
            [item["assay_id"] for item in projected_profile["assays"]],
            [records["assay"]["assay_id"]],
        )
        evidence_plan_result = self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="e2e-evidence-plan-command",
            operation="send_task_message",
            instruction="Investigate the disease using the approved molecular profile and public evidence.",
            artifact_kind="plan",
        )
        evidence_capabilities = {
            item["capability"]: item["result"]
            for item in evidence_plan_result["capability_results"]
        }
        self.assertEqual(
            set(evidence_capabilities),
            {
                "investigation.project_profile",
                "genomi.variant.resolve",
                "public_evidence.retrieve",
            },
        )
        self.assertEqual(
            evidence_capabilities["public_evidence.retrieve"]["provider_result"][
                "provider"
            ],
            "fixture",
        )
        evidence_after_harness = self.service.investigation(investigation_id)[
            "current_evidence_records"
        ]
        first_evidence = next(
            item
            for item in evidence_after_harness
            if item["source_family"] == "personal_genome"
        )
        public_source = next(
            item
            for item in evidence_after_harness
            if item["source_family"] == "literature"
        )
        self.assertEqual(first_evidence["source_family"], "personal_genome")
        self.assertEqual(first_evidence["evidence"]["sample_context"]["count"], 1)
        self.assertEqual(
            first_evidence["evidence"]["sample_context"]["matches"][0]["rsid"],
            "rs900000001",
        )
        self.assertEqual(
            first_evidence["evidence"]["sample_context"]["matches"][0]["genotype"],
            "0/1",
        )
        self.assertEqual(
            first_evidence["evidence_envelope"],
            first_evidence["evidence"]["evidence_envelope"],
        )
        finding_revision_id = str(records["finding"]["observation_revision_id"])
        relation_plan_result = self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="e2e-relation-plan-command",
            operation="replace_task_binding",
            instruction="Link the public disease evidence to the exact approved molecular finding.",
            artifact_kind="plan",
            reason="Start a fresh tool-free planning task after evidence changed.",
        )
        relation_result = next(
            item
            for item in relation_plan_result["capability_results"]
            if item["capability"] == "investigation.register_disease_relation"
        )
        self.assertEqual(relation_result["result"]["status"], "registered")
        relation = relation_result["result"]["disease_relation"]
        self.assertEqual(
            relation["evidence"]["disease_relation"]["profile_revision_ids"],
            [finding_revision_id],
        )
        self.assertEqual(
            relation["evidence"]["disease_relation"]["source_evidence_record_ids"],
            [public_source["evidence_record_id"]],
        )

        synthesis_plan_result = self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="e2e-synthesis-plan-command",
            operation="replace_task_binding",
            instruction="Synthesize only a traceable candidate and its remaining evidence gap.",
            artifact_kind="plan",
            reason="Start a fresh tool-free planning task after evidence changed.",
        )
        synthesis_results = {
            item["capability"]: item["result"]
            for item in synthesis_plan_result["capability_results"]
        }
        self.assertEqual(
            {
                "investigation.register_hypothesis",
                "investigation.register_gap",
            }.issubset(synthesis_results),
            True,
        )
        hypothesis = synthesis_results["investigation.register_hypothesis"][
            "hypothesis"
        ]
        gap = synthesis_results["investigation.register_gap"]["hypothesis"]

        brief_result = self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="e2e-brief-command",
            operation="send_task_message",
            instruction="Draft a patient-friendly research brief from the approved evidence and clearly state the clinical boundary.",
            artifact_kind="brief_draft",
        )
        self.assertEqual(brief_result["committed_artifact"]["version"], 1)
        saved = self.service.investigation(investigation_id)
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(len(saved["evidence_records"]), 3)
        self.assertEqual(
            {item["hypothesis_id"] for item in saved["hypotheses"]},
            {hypothesis["hypothesis_id"], gap["hypothesis_id"]},
        )
        self.assertEqual(saved["brief"]["clinical_stage"], "candidate_hypothesis")
        self.assertIn("personal_genome", saved["brief"]["modality_badges"])
        self.assertIn("public_source", saved["brief"]["modality_badges"])
        self.assertEqual(
            saved["brief"]["hypothesis_ids"], [hypothesis["hypothesis_id"]]
        )
        self.assertEqual(saved["brief"]["gap_ids"], [gap["hypothesis_id"]])
        claim = saved["brief"]["claims"][0]
        self.assertEqual(
            claim["evidence_record_ids"],
            [first_evidence["evidence_record_id"], relation["evidence_record_id"]],
        )
        self.assertEqual(
            set(claim["profile_revision_ids"]),
            {finding_revision_id},
        )
        self.assertIn("not a diagnosis", saved["brief"]["clinical_boundary"].lower())

        # A second investigation reuses Genomi's active index revision but receives
        # a separate immutable patient-profile snapshot.
        second = self.service.create_investigation(
            {
                "question": "What evidence remains unresolved for this condition?",
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        second_snapshot = self._approve_patient_context(
            self.service, str(second["investigation_id"]), records
        )
        self.assertEqual(second_snapshot["agi_id"], snapshot["agi_id"])
        self.assertEqual(
            second_snapshot["agi_snapshot_id"], snapshot["agi_snapshot_id"]
        )
        self.assertNotEqual(
            second_snapshot["patient_molecular_snapshot_id"],
            snapshot["patient_molecular_snapshot_id"],
        )
        self.assertEqual(
            self.service.store.get_profile_snapshot(
                str(snapshot["patient_molecular_snapshot_id"])
            )["agi_snapshot_id"],
            parsed["active_genome_index"]["agi_snapshot_id"],
        )

        serialized_domain = json.dumps(
            {
                "profile": self.service.molecular_profile(),
                "investigation": saved,
                "snapshot": snapshot,
            }
        )
        self.assertNotIn(str(PATIENT_A_VCF), serialized_domain)
        self.assertNotIn("patient-a.vcf", serialized_domain)
        self.assertNotIn("agi_path", serialized_domain)
        self.assertNotIn("raw_agi_rows", serialized_domain)
        encrypted_store = self.store_path.read_bytes()
        self.assertFalse(encrypted_store.startswith(b"SQLite format 3\x00"))
        self.assertNotIn(b"Synthetic neuromuscular condition", encrypted_store)

    def test_restart_requires_new_private_consent_and_current_user_isolation(
        self,
    ) -> None:
        _, context_a = self._intake_current_user(
            PATIENT_A_VCF,
            nickname="Synthetic patient A",
            source_name="patient-a.vcf",
        )
        user_a_id = str(context_a["active_user_id"])
        agi_a_id = str(context_a["active_agi_id"])
        agi_a_snapshot_id = str(context_a["active_genome_index"]["agi_snapshot_id"])
        self.service.bootstrap_workspace()
        records = self._add_molecular_profile(self.service)
        investigation = self.service.create_investigation(
            {
                "question": "Could rs900000001 relate to this patient's condition?",
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        investigation_id = str(investigation["investigation_id"])
        self._approve_harness_call(
            self.service,
            investigation_id,
            command_id="restart-plan-command",
            operation="start_task_run",
            artifact_kind="plan",
        )
        original_snapshot = self._approve_patient_context(
            self.service, investigation_id, records
        )
        self.service.close()

        restarted = self._new_service("workspace-session-after-restart")
        self.assertEqual(
            restarted.bootstrap_workspace()["workspace"]["user_id"], user_a_id
        )
        self.assertEqual(
            restarted.investigation(investigation_id)["patient_molecular_snapshot_id"],
            original_snapshot["patient_molecular_snapshot_id"],
        )
        with self.assertRaises(LabError) as raised:
            restarted.investigation_profile(investigation_id)
        self.assertEqual(raised.exception.code, "private_context_renewal_required")
        with self.assertRaises(LabError) as raised:
            restarted.invoke_investigation_genome(
                investigation_id,
                operation="variant.resolve",
                params={"rsid": "rs900000001"},
            )
        self.assertEqual(raised.exception.code, "private_context_renewal_required")

        renewed = self._approve_patient_context(restarted, investigation_id, records)
        self.assertNotEqual(
            renewed["consent_receipt_id"], original_snapshot["consent_receipt_id"]
        )
        replacement = self._approve_harness_call(
            restarted,
            investigation_id,
            command_id="restart-replacement-command",
            operation="replace_task_binding",
            artifact_kind="plan",
            reason="Reconnect the durable investigation after reopening the workspace.",
        )
        self.assertEqual(replacement["binding"]["binding_state"], "active")
        binding_states = {
            binding["binding_state"]
            for binding in restarted.investigation(investigation_id)["harness_bindings"]
        }
        self.assertEqual(binding_states, {"active", "replaced"})

        _, context_b = self._intake_current_user(
            PATIENT_B_VCF,
            nickname="Synthetic patient B",
            source_name="patient-b.vcf",
        )
        user_b_id = str(context_b["active_user_id"])
        self.assertNotEqual(user_a_id, user_b_id)
        self.assertNotEqual(agi_a_id, context_b["active_agi_id"])
        self.assertNotEqual(
            agi_a_snapshot_id,
            context_b["active_genome_index"]["agi_snapshot_id"],
        )
        workspace_b = restarted.bootstrap_workspace()["workspace"]
        self.assertEqual(workspace_b["user_id"], user_b_id)
        self.assertEqual(
            workspace_b["profile"]["genome"]["agi_id"],
            context_b["active_agi_id"],
        )
        self.assertEqual(workspace_b["profile"]["observations"], [])
        self.assertEqual(workspace_b["investigations"], [])
        with self.assertRaises(LabError) as raised:
            restarted.investigation(investigation_id)
        self.assertEqual(raised.exception.code, "investigation_not_found")

        call_operation("active_genome_index.select_user", {"user_id": user_a_id})
        restored_a = restarted.bootstrap_workspace()["workspace"]
        self.assertEqual(restored_a["user_id"], user_a_id)
        self.assertEqual(len(restored_a["profile"]["observations"]), 3)
        self.assertEqual(
            [item["investigation_id"] for item in restored_a["investigations"]],
            [investigation_id],
        )
        with self.assertRaises(LabError) as raised:
            restarted.investigation_profile(investigation_id)
        self.assertEqual(raised.exception.code, "private_context_renewal_required")


if __name__ == "__main__":
    import unittest

    unittest.main()
