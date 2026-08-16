from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from genomi.lab import operations as lab_operations
from genomi.lab.result_receipts import _validate_capturable_provider_result
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
        repository_root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(repository_root / "src")
        issued = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from genomi.operations.registry.evidence_result_receipts "
                    "import EVIDENCE_RESULT_RECEIPTS; "
                    "print(EVIDENCE_RESULT_RECEIPTS.issue("
                    "session_id='session-a', "
                    "operation='paperclip.retrieve_document_evidence', "
                    "params={'document_id': 'PMC1', 'collection': 'papers', "
                    "'patterns': ['synthetic mechanism']}, "
                    "result={'status': 'completed', 'evidence_envelope': {"
                    "'operation': 'paperclip.retrieve_document_evidence', "
                    "'headline': 'paperclip.retrieve_document_evidence: data_returned', "
                    "'finding_state': 'evidence_present', "
                    "'answer_readiness': 'answer_supported', "
                    "'guidance': [], "
                    "'negative_inference': {'allowed': False, 'requires': []}, "
                    "'coverage': {'consulted_sources': ['paperclip:papers/PMC1']}}, "
                    "'document': {'title': 'Synthetic public result', "
                    "'record_id': 'PMC1'}, 'excerpts': [{'line_start': 12, "
                    "'line_end': 12, 'text': 'Synthetic public evidence.'}]}))"
                ),
            ],
            cwd=repository_root,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        process_receipt_id = issued.stdout.strip()

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

    def test_paperclip_search_receipt_remains_discovery_only(self) -> None:
        state = self._completed_public_literature_assignment()
        process_receipt_id = EVIDENCE_RESULT_RECEIPTS.issue(
            session_id="session-a",
            operation="paperclip.search_biomedical",
            params={"query": "synthetic public mechanism"},
            result={
                "status": "completed",
                "records": [{"title": "Synthetic discovery result"}],
                "evidence_envelope": {
                    "operation": "paperclip.search_biomedical",
                    "headline": "paperclip.search_biomedical: data_returned",
                    "finding_state": "evidence_present",
                    "answer_readiness": "scoped_answer_only",
                    "guidance": [
                        "evidence_present:use_as_scoped_public_literature_evidence"
                    ],
                    "negative_inference": {"allowed": False, "requires": []},
                    "coverage": {"consulted_sources": ["paperclip:pmc"]},
                },
            },
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
                    "purpose": "Reject discovery-only search output",
                    "command_id": "reject-search-result",
                    "expected_revision": state["domain_revision"],
                }
            )

        self.assertEqual(raised.exception.code, "invalid_lab_request")
        EVIDENCE_RESULT_RECEIPTS.resolve(
            process_receipt_id, session_id="session-a"
        )
        self.assertEqual(
            self.store.get_investigation(state["investigation_id"])[
                "evidence_snapshot_id"
            ],
            state["evidence_snapshot_id"],
        )

    def test_provider_capture_rejects_every_noncompleted_result_state(self) -> None:
        for provider, operation in (
            ("paperclip", "paperclip.retrieve_document_evidence"),
            ("biohub-esm", "biohub.compare_protein_embeddings"),
            ("proto", "proto.run_tool"),
        ):
            for status in (
                "source_unavailable",
                "in_progress",
                "in_scope_empty",
                "out_of_scope_for_input",
                "failed",
            ):
                with self.subTest(provider=provider, status=status), self.assertRaisesRegex(
                    ValueError, "only completed provider results can be captured"
                ):
                    _validate_capturable_provider_result(
                        {
                            "provider": provider,
                            "operation": operation,
                            "exact_result": {"status": status},
                        }
                    )

    def test_completed_empty_provider_result_is_not_data_returned(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "only data-returned provider results can be captured"
        ):
            _validate_capturable_provider_result(
                {
                    "provider": "paperclip",
                    "operation": "paperclip.retrieve_document_evidence",
                    "exact_result": {
                        "status": "completed",
                        "evidence_envelope": {
                            "operation": "paperclip.retrieve_document_evidence",
                            "headline": "paperclip.retrieve_document_evidence: not_observed_in_consulted_scope",
                            "finding_state": "not_observed_in_consulted_scope",
                            "answer_readiness": "scoped_answer_only",
                            "guidance": [
                                "not_observed_in_consulted_scope:do_not_imply_biomedical_negative"
                            ],
                            "negative_inference": {"allowed": False, "requires": []},
                            "coverage": {"consulted_sources": ["paperclip:papers/PMC1"]},
                        },
                    },
                }
            )

    def test_completed_data_returned_results_pass_capture_policy(self) -> None:
        for provider, operation in (
            ("paperclip", "paperclip.retrieve_document_evidence"),
            ("biohub-esm", "biohub.compare_protein_embeddings"),
            ("proto", "proto.run_tool"),
        ):
            with self.subTest(provider=provider):
                exact_result = {
                    "status": "completed",
                    "evidence_envelope": {
                        "operation": operation,
                        "headline": f"{operation}: data_returned",
                        "finding_state": "evidence_present",
                        "answer_readiness": "scoped_answer_only",
                        "guidance": [
                            "evidence_present:use_only_within_declared_scope"
                        ],
                        "negative_inference": {
                            "allowed": False,
                            "requires": [],
                        },
                        "coverage": {"consulted_sources": [provider]},
                    },
                }
                if provider == "paperclip":
                    exact_result["excerpts"] = [
                        {
                            "line_start": 12,
                            "line_end": 12,
                            "text": "Synthetic public evidence.",
                        }
                    ]
                _validate_capturable_provider_result(
                    {
                        "provider": provider,
                        "operation": operation,
                        "exact_result": exact_result,
                    }
                )

    def test_direct_provider_result_cannot_bypass_specialist_artifact_policy(self) -> None:
        created = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Compare a public protein model without patient context.",
            public_only=True,
            command_id="create-public-protein-investigation",
        )
        investigation_id = str(created["investigation"]["investigation_id"])
        cycle = self.store.create_investigation_cycle(
            investigation_id,
            purpose="Run public protein research",
            public_only=True,
            command_id="create-public-protein-cycle",
            expected_revision=1,
        )
        operation = "biohub.compare_protein_embeddings"
        receipt_id = self.store.issue_genomi_result_receipt(
            operation=operation,
            params={
                "reference_sequence": "A" * 20,
                "alternate_sequence": "A" * 19 + "V",
                "sequence_scope": "public_reference",
            },
            presented_result={
                "status": "completed",
                "evidence_envelope": {
                    "operation": operation,
                    "headline": f"{operation}: data_returned",
                    "finding_state": "evidence_present",
                    "answer_readiness": "scoped_answer_only",
                    "guidance": [
                        "evidence_present:use_only_as_nonclinical_protein_model_signal"
                    ],
                    "negative_inference": {"allowed": False, "requires": []},
                    "coverage": {"consulted_sources": ["biohub:esmc"]},
                },
                "comparison": {"cosine_similarity": 0.99},
            },
            investigation_id=investigation_id,
            workspace_session_id="session-a",
        )

        with self.assertRaisesRegex(
            ValueError, "external provider results require a completed specialist"
        ):
            self.store.capture_evidence_result(
                investigation_id,
                cycle_id=cycle["cycle"]["cycle_id"],
                result_receipt_id=receipt_id,
                purpose="Reject direct provider capture",
                command_id="reject-direct-provider-capture",
                expected_revision=cycle["domain_revision"],
            )

        self.assertIsNone(
            self.store.get_investigation(investigation_id)["evidence_snapshot_id"]
        )

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
            "evidence_snapshot_id": updated["evidence_snapshot"][
                "evidence_snapshot_id"
            ],
            "domain_revision": completed["domain_revision"],
        }


if __name__ == "__main__":
    unittest.main()
