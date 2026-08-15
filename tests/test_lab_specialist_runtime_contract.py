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
from genomi.operations.registry.evidence_result_receipts import EVIDENCE_RESULT_RECEIPTS
from genomi.runtime import context as runtime_context


class LabSpecialistRuntimeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._temporary_home.name) / "home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "lab-specialist-runtime-tests",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        EVIDENCE_RESULT_RECEIPTS.clear()
        self.addCleanup(EVIDENCE_RESULT_RECEIPTS.clear)
        self.store = GenomiLabStore()
        self.store.open_workspace("user-a", "Synthetic user")

    def test_public_literature_receipt_is_redeemed_into_assignment_evidence(self) -> None:
        state = self._completed_public_literature_assignment()
        self.assertEqual(
            state["outbound_brief"]["allowed_tools"],
            ["paperclip.search_biomedical", "paperclip.retrieve_document_evidence"],
        )
        process_receipt_id = EVIDENCE_RESULT_RECEIPTS.issue(
            session_id="session-a",
            operation="paperclip.search_biomedical",
            params={"query": "synthetic public mechanism"},
            result={
                "evidence_envelope": {
                    "operation": "paperclip.search_biomedical",
                    "headline": "paperclip.search_biomedical: data_returned",
                    "finding_state": "evidence_present",
                    "answer_readiness": "answer_supported",
                    "guidance": [],
                    "negative_inference": {"allowed": False, "requires": []},
                    "coverage": {"consulted_sources": ["pmc"]},
                },
                "records": [{"title": "Synthetic public result", "source": "pmc"}],
            },
        )

        @contextmanager
        def authorized_store():
            yield self.store, "user-a", "session-a"

        with mock.patch.object(
            lab_operations, "_authorized_store", authorized_store
        ):
            captured = lab_operations.capture_provider_result(
                {
                    "investigation_id": state["investigation_id"],
                    "cycle_id": state["cycle_id"],
                    "assignment_id": state["assignment_id"],
                    "specialist_brief_id": state["specialist_brief_id"],
                    "result_receipt_id": process_receipt_id,
                    "purpose": "Bind exact specialist literature evidence",
                    "command_id": "capture-provider-result",
                    "expected_revision": state["domain_revision"],
                }
            )

        self.assertEqual(captured["evidence_record"]["source_family"], "paperclip")
        self.assertIsNone(captured["research_artifact"])
        with self.assertRaises(ValueError):
            EVIDENCE_RESULT_RECEIPTS.resolve(
                process_receipt_id, session_id="session-a"
            )

    def test_provider_receipt_outside_assignment_policy_is_rejected(self) -> None:
        state = self._completed_public_literature_assignment()
        process_receipt_id = EVIDENCE_RESULT_RECEIPTS.issue(
            session_id="session-a",
            operation="biohub.compare_protein_embeddings",
            params={},
            result={"status": "completed"},
        )

        @contextmanager
        def authorized_store():
            yield self.store, "user-a", "session-a"

        with mock.patch.object(
            lab_operations, "_authorized_store", authorized_store
        ), self.assertRaises(OperationError) as raised:
            lab_operations.capture_provider_result(
                {
                    "investigation_id": state["investigation_id"],
                    "cycle_id": state["cycle_id"],
                    "assignment_id": state["assignment_id"],
                    "specialist_brief_id": state["specialist_brief_id"],
                    "result_receipt_id": process_receipt_id,
                    "purpose": "Reject wrong provider",
                    "command_id": "capture-wrong-provider",
                    "expected_revision": state["domain_revision"],
                }
            )

        self.assertEqual(raised.exception.code, "invalid_lab_request")
        EVIDENCE_RESULT_RECEIPTS.resolve(process_receipt_id, session_id="session-a")

    def _completed_public_literature_assignment(self) -> dict[str, object]:
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
        return {
            "investigation_id": investigation_id,
            "cycle_id": cycle_id,
            "specialist_brief_id": brief["specialist_brief_id"],
            "outbound_brief": brief["outbound_brief"],
            "assignment_id": assignment_id,
            "domain_revision": completed["domain_revision"],
        }


if __name__ == "__main__":
    unittest.main()
