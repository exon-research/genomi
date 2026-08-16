from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context


class LabPublicResearchCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._temporary_home.name) / "home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "lab-public-research-cycle-tests",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore()
        self.store.open_workspace("user-a", "Synthetic user")

    def test_private_investigation_can_chain_a_public_only_research_cycle(self) -> None:
        created = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Could several reported observations share an explanation?",
            command_id="create-investigation",
        )
        investigation_id = str(created["investigation"]["investigation_id"])
        updated = self.store.update_health_profile(
            "user-a",
            investigation_id,
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Synthetic recurring observation",
                    "original_wording": "A recurring observation was reported",
                }
            ],
            purpose="Capture the reported observation",
            command_id="update-profile",
            expected_revision=1,
        )
        profile_snapshot_id = str(
            updated["profile_snapshot"]["patient_molecular_snapshot_id"]
        )
        evidence_snapshot = self.store.create_evidence_snapshot(
            investigation_id,
            reason="Pin the evidence basis before research",
        )
        evidence_snapshot_id = str(evidence_snapshot["evidence_snapshot_id"])

        private_cycle = self.store.create_investigation_cycle(
            investigation_id,
            purpose="Assess the approved private context",
            command_id="create-private-cycle",
            expected_revision=3,
        )
        self.assertEqual(
            private_cycle["cycle"]["patient_molecular_snapshot_id"],
            profile_snapshot_id,
        )
        self.assertEqual(
            private_cycle["cycle"]["evidence_snapshot_id"],
            evidence_snapshot_id,
        )

        with self.assertRaisesRegex(
            ValueError, "public_only cycles cannot include a profile snapshot"
        ):
            self.store.create_investigation_cycle(
                investigation_id,
                purpose="Reject an explicit private snapshot in public research",
                patient_molecular_snapshot_id=profile_snapshot_id,
                prior_cycle_id=private_cycle["cycle"]["cycle_id"],
                public_only=True,
                command_id="reject-private-snapshot",
                expected_revision=4,
            )

        public_cycle = self.store.create_investigation_cycle(
            investigation_id,
            purpose="Research a public reference mechanism",
            prior_cycle_id=private_cycle["cycle"]["cycle_id"],
            public_only=True,
            command_id="create-public-cycle",
            expected_revision=4,
        )

        self.assertEqual(public_cycle["cycle"]["investigation_id"], investigation_id)
        self.assertEqual(public_cycle["cycle"]["ordinal"], 2)
        self.assertEqual(
            public_cycle["cycle"]["prior_cycle_id"],
            private_cycle["cycle"]["cycle_id"],
        )
        self.assertTrue(public_cycle["cycle"]["public_only"])
        self.assertIsNone(public_cycle["cycle"]["patient_molecular_snapshot_id"])
        self.assertEqual(
            public_cycle["cycle"]["evidence_snapshot_id"],
            evidence_snapshot_id,
        )

        brief = self.store.prepare_specialist_brief(
            investigation_id,
            cycle_id=public_cycle["cycle"]["cycle_id"],
            specialist_role="Public protein-model reviewer",
            execution_policy="protein_model_research",
            research_question="Compare public reference protein representations.",
            public_concepts=[
                {
                    "type": "protein",
                    "identifier": "public-reference-protein",
                    "label": "Public reference protein",
                }
            ],
            abstract_relations=[],
            public_evidence_record_ids=[],
            source_fact_ids=[],
            rationale="Evaluate a public research-only model output",
            purpose="Public reference research",
            workspace_session_id="session-a",
            command_id="prepare-model-brief",
            expected_revision=5,
        )
        assignment = self.store.create_specialist_assignment(
            investigation_id,
            cycle_id=public_cycle["cycle"]["cycle_id"],
            specialist_brief_id=brief["specialist_brief_id"],
            command_id="create-model-assignment",
            expected_revision=6,
        )
        assignment_id = str(
            assignment["assignment"]["specialist_assignment_id"]
        )
        self.store.transition_specialist_assignment(
            investigation_id,
            specialist_assignment_id=assignment_id,
            to_state="spawned",
            assignment_expected_revision=1,
            native_agent_id="native-model-specialist",
            command_id="spawn-model-assignment",
            expected_revision=7,
        )
        completed = self.store.transition_specialist_assignment(
            investigation_id,
            specialist_assignment_id=assignment_id,
            to_state="completed",
            assignment_expected_revision=2,
            analysis={
                "general_analysis": "A research-only public model comparison completed.",
                "uncertainty": [],
                "alternatives": [],
                "gaps": [],
            },
            command_id="complete-model-assignment",
            expected_revision=8,
        )
        receipt_id = self.store.issue_provider_result_receipt(
            provider="biohub-esm",
            result_kind="research_artifact",
            operation="biohub.compare_protein_embeddings",
            exact_result={"comparison": {"state": "research_only"}},
            specialist_assignment_id=assignment_id,
            specialist_brief_id=brief["specialist_brief_id"],
            provider_provenance={"provider": "biohub-esm"},
        )
        captured = self.store.capture_provider_result(
            investigation_id,
            cycle_id=public_cycle["cycle"]["cycle_id"],
            assignment_id=assignment_id,
            specialist_brief_id=brief["specialist_brief_id"],
            provider_result_receipt_id=receipt_id,
            purpose="Retain the research artifact without promoting it to evidence",
            command_id="capture-model-artifact",
            expected_revision=completed["domain_revision"],
        )
        artifact_id = str(captured["research_artifact"]["research_artifact_id"])

        self.assertIsNone(captured["evidence_record"])
        self.assertIsNone(captured["evidence_snapshot"])
        self.assertEqual(
            self.store.get_investigation(investigation_id)["evidence_snapshot_id"],
            evidence_snapshot_id,
        )
        with self.assertRaisesRegex(
            ValueError,
            "hypothesis evidence must belong to the selected evidence snapshot",
        ):
            self.store.create_hypothesis(
                investigation_id,
                cycle_id=public_cycle["cycle"]["cycle_id"],
                statement="A research artifact must not become patient evidence.",
                status="open",
                profile_snapshot_id=profile_snapshot_id,
                evidence_snapshot_id=evidence_snapshot_id,
                supporting_evidence_record_ids=[artifact_id],
                contradicting_evidence_record_ids=[],
                contextual_evidence_record_ids=[],
                unresolved_gaps=["Clinical evidence remains required"],
                revision_rationale="Verify research artifacts cannot enter hypotheses",
                command_id="reject-artifact-as-evidence",
                expected_revision=captured["domain_revision"],
            )


if __name__ == "__main__":
    unittest.main()
