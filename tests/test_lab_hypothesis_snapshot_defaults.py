from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from genomi.lab import operations as lab_operations
from genomi.lab.store import GenomiLabStore
from genomi.operations import OperationError
from genomi.runtime import context as runtime_context


class LabHypothesisSnapshotDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._temporary_home.name) / "home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "lab-hypothesis-snapshot-tests",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore()
        self.store.open_workspace("user-a", "Synthetic user")

    def test_competing_hypotheses_default_to_current_captured_evidence(self) -> None:
        state = self._capture_public_literature_evidence()

        @contextmanager
        def authorized_store():
            yield self.store, "user-a", "session-a"

        common = {
            "investigation_id": state["investigation_id"],
            "cycle_id": state["cycle_id"],
            "status": "open",
            "supporting_evidence_record_ids": [state["evidence_record_id"]],
            "contradicting_evidence_record_ids": [],
            "contextual_evidence_record_ids": [],
            "unresolved_gaps": ["Patient-specific mechanism remains unresolved"],
        }
        with mock.patch.object(
            lab_operations, "_authorized_store", authorized_store
        ):
            first = lab_operations.create_hypothesis(
                {
                    **common,
                    "statement": "The reported features may share an immune mechanism.",
                    "category": "shared_mechanism",
                    "revision_rationale": "Open one evidence-grounded explanation.",
                    "command_id": "create-first-hypothesis",
                    "expected_revision": state["domain_revision"],
                }
            )
            second = lab_operations.create_hypothesis(
                {
                    **common,
                    "statement": "The reported features may instead have independent causes.",
                    "category": "independent_causes",
                    "revision_rationale": "Preserve a competing evidence-grounded explanation.",
                    "command_id": "create-second-hypothesis",
                    "expected_revision": first["domain_revision"],
                }
            )

            with self.assertRaises(OperationError) as raised:
                lab_operations.create_hypothesis(
                    {
                        **common,
                        "statement": "An explicitly stale evidence anchor must be rejected.",
                        "profile_snapshot_id": state["profile_snapshot_id"],
                        "evidence_snapshot_id": "evidence-snapshot-stale",
                        "revision_rationale": "Exercise strict explicit-anchor validation.",
                        "command_id": "create-stale-anchor-hypothesis",
                        "expected_revision": second["domain_revision"],
                    }
                )

        for result in (first, second):
            version = result["hypothesis_version"]
            self.assertEqual(
                version["patient_molecular_snapshot_id"],
                state["profile_snapshot_id"],
            )
            self.assertEqual(
                version["evidence_snapshot_id"], state["evidence_snapshot_id"]
            )
        self.assertNotEqual(
            first["hypothesis_version"]["logical_hypothesis_id"],
            second["hypothesis_version"]["logical_hypothesis_id"],
        )
        self.assertEqual(raised.exception.code, "invalid_lab_request")

    def _capture_public_literature_evidence(self) -> dict[str, object]:
        created = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Could the synthetic features have a shared explanation?",
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
                    "label": "Synthetic private feature",
                    "original_wording": "Synthetic private wording",
                }
            ],
            purpose="Capture the reported feature",
            command_id="update-profile",
            expected_revision=1,
        )
        cycle = self.store.create_investigation_cycle(
            investigation_id,
            purpose="Research a general mechanism",
            command_id="create-cycle",
            expected_revision=2,
        )
        cycle_id = str(cycle["cycle"]["cycle_id"])
        brief = self.store.prepare_specialist_brief(
            investigation_id,
            cycle_id=cycle_id,
            specialist_role="Public evidence reviewer",
            execution_policy="public_literature",
            research_question="Compare public evidence for a reference mechanism.",
            public_concepts=[],
            abstract_relations=[],
            public_evidence_record_ids=[],
            source_fact_ids=updated["source_fact_ids"],
            rationale="Research a general mechanism",
            purpose="Research a general mechanism",
            workspace_session_id="session-a",
            command_id="prepare-brief",
            expected_revision=3,
        )
        assignment = self.store.create_specialist_assignment(
            investigation_id,
            cycle_id=cycle_id,
            specialist_brief_id=brief["specialist_brief_id"],
            command_id="create-assignment",
            expected_revision=4,
        )
        assignment_id = str(
            assignment["assignment"]["specialist_assignment_id"]
        )
        self.store.transition_specialist_assignment(
            investigation_id,
            specialist_assignment_id=assignment_id,
            to_state="spawned",
            assignment_expected_revision=1,
            command_id="spawn-assignment",
            expected_revision=5,
            native_agent_id="native-specialist-a",
        )
        completed = self.store.transition_specialist_assignment(
            investigation_id,
            specialist_assignment_id=assignment_id,
            to_state="completed",
            assignment_expected_revision=2,
            command_id="complete-assignment",
            expected_revision=6,
            analysis={
                "general_analysis": "Synthetic public analysis",
                "uncertainty": [],
                "alternatives": [],
                "gaps": [],
            },
        )
        receipt_id = self.store.issue_provider_result_receipt(
            provider="paperclip",
            result_kind="public_source_evidence",
            operation="paperclip.retrieve_document_evidence",
            exact_result={
                "status": "completed",
                "evidence_envelope": {
                    "operation": "paperclip.retrieve_document_evidence",
                    "headline": "paperclip.retrieve_document_evidence: data_returned",
                    "finding_state": "evidence_present",
                    "answer_readiness": "answer_supported",
                    "guidance": [],
                    "negative_inference": {"allowed": False, "requires": []},
                    "coverage": {"consulted_sources": ["pmc"]},
                },
                "document": {"title": "Synthetic public result", "record_id": "PMC1"},
                "excerpts": [
                    {"line_start": 12, "line_end": 12, "text": "Synthetic public evidence."}
                ],
            },
            specialist_assignment_id=assignment_id,
            specialist_brief_id=brief["specialist_brief_id"],
            provider_provenance={"provider": "paperclip", "source": "pmc"},
        )
        captured = self.store.capture_provider_result(
            investigation_id,
            cycle_id=cycle_id,
            assignment_id=assignment_id,
            specialist_brief_id=brief["specialist_brief_id"],
            provider_result_receipt_id=receipt_id,
            purpose="Capture public specialist evidence",
            command_id="capture-provider-result",
            expected_revision=completed["domain_revision"],
        )
        return {
            "investigation_id": investigation_id,
            "cycle_id": cycle_id,
            "profile_snapshot_id": updated["profile_snapshot"][
                "patient_molecular_snapshot_id"
            ],
            "evidence_record_id": captured["evidence_record"][
                "evidence_record_id"
            ],
            "evidence_snapshot_id": captured["evidence_snapshot"][
                "evidence_snapshot_id"
            ],
            "domain_revision": captured["domain_revision"],
        }


if __name__ == "__main__":
    unittest.main()
