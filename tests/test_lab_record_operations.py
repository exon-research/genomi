from __future__ import annotations

import base64
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from genomi.lab.store import GenomiLabStore
from genomi.operations import OperationError, all_operations, call_operation
from genomi.operations.registry.evidence_result_receipts import (
    EVIDENCE_RESULT_RECEIPTS,
)
from genomi.runtime.context import context_scope
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


class LabRecordOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.store = GenomiLabStore(
            Path(self._temporary.name) / "lab.sqlite3",
            key_provider=TEST_LAB_KEY_PROVIDER,
        )
        self.user_id = "record-user-a"
        self.store.open_workspace(self.user_id, "Record user A")
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMILAB_PORTAL_PROJECT_ID": "project-a",
                "GENOMILAB_PORTAL_FRAME_ID": "frame-a",
                "GENOMI_SESSION_ID": "portal-project-a-frame-a",
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self._authority = mock.patch(
            "genomi.operations.registry.handlers_genomilab._authorized_store",
            self._authorized_store,
        )
        self._authority.start()
        self.addCleanup(self._authority.stop)
        EVIDENCE_RESULT_RECEIPTS.clear()
        self.addCleanup(EVIDENCE_RESULT_RECEIPTS.clear)

    @contextmanager
    def _authorized_store(self):
        yield self.store, self.user_id, str(context_scope()["id"])

    def test_direct_lab_surface_is_separate_and_uses_no_user_parameter(self) -> None:
        tools = {
            tool["name"]: tool
            for tool in all_operations()
            if tool["name"].startswith("lab.")
        }

        self.assertIn("lab.start_investigation", tools)
        self.assertIn("lab.prepare_specialist_packet", tools)
        self.assertEqual(
            tools["lab.start_investigation"]["annotations"]["toolCapability"],
            "lab",
        )
        for tool in tools.values():
            self.assertNotIn("user_id", tool["inputSchema"]["properties"])
            self.assertEqual(tool["annotations"]["mcpExecution"], "inline_only")

    def test_start_and_cycle_writes_are_idempotent_and_revision_checked(self) -> None:
        params = {
            "question": "What explains the bounded synthetic phenotype?",
            "command_id": "start-command-a",
        }
        first = call_operation("lab.start_investigation", params)
        retried = call_operation("lab.start_investigation", params)

        investigation = first["investigation"]
        self.assertEqual(
            investigation["investigation_id"],
            retried["investigation"]["investigation_id"],
        )
        current = self.store.get_investigation(investigation["investigation_id"])
        cycle_params = {
            "investigation_id": investigation["investigation_id"],
            "objective": "First bounded review",
            "expected_revision": current["domain_revision"],
            "command_id": "cycle-command-a",
        }
        cycle = call_operation("lab.start_cycle", cycle_params)["cycle"]
        same_cycle = call_operation("lab.start_cycle", cycle_params)["cycle"]
        self.assertEqual(cycle["cycle_id"], same_cycle["cycle_id"])

        with self.assertRaises(OperationError) as conflict:
            call_operation(
                "lab.record_information_gap",
                {
                    "investigation_id": investigation["investigation_id"],
                    "cycle_id": cycle["cycle_id"],
                    "description": "A missing bounded fact",
                    "expected_revision": cycle["revision"] + 1,
                    "command_id": "gap-command-a",
                },
            )
        self.assertEqual(conflict.exception.code, "invalid_genomilab_request")

    def test_profile_approval_and_packet_use_only_selected_stored_fact_ids(
        self,
    ) -> None:
        started = call_operation(
            "lab.start_investigation",
            {
                "question": "Could the recorded symptom inform this inquiry?",
                "command_id": "start-profile-a",
            },
        )
        investigation_id = started["investigation"]["investigation_id"]
        observation = self.store.add_profile_observation(
            self.user_id,
            {
                "modality": "phenotype",
                "label": "Synthetic exertional fatigue",
                "original_wording": "Synthetic exertional fatigue after moderate activity.",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            },
        )
        fact_id = observation["observation_revision_id"]
        preview = call_operation(
            "lab.preview_profile_access",
            {
                "investigation_id": investigation_id,
                "purpose": "Evaluate the bounded inquiry",
                "observation_revision_ids": [fact_id],
            },
        )["profile_access"]
        approved = call_operation(
            "lab.approve_profile_access",
            {
                "investigation_id": investigation_id,
                "purpose": "Evaluate the bounded inquiry",
                "observation_revision_ids": [fact_id],
                "candidate_sha256": preview["candidate_sha256"],
                "approved": True,
                "command_id": "approve-profile-a",
            },
        )
        self.assertEqual(approved["status"], "approved")

        investigation = self.store.get_investigation(investigation_id)
        cycle = call_operation(
            "lab.start_cycle",
            {
                "investigation_id": investigation_id,
                "objective": "Review selected profile context",
                "expected_revision": investigation["domain_revision"],
                "command_id": "cycle-profile-a",
            },
        )["cycle"]
        packet = call_operation(
            "lab.prepare_specialist_packet",
            {
                "investigation_id": investigation_id,
                "cycle_id": cycle["cycle_id"],
                "specialist_role": "independent mechanism reviewer",
                "projection_kind": "phenotype_projection",
                "objective": "Review only the selected symptom context",
                "selected_profile_fact_ids": [fact_id],
                "selected_evidence_ids": [],
                "allowed_provider": "host_native",
                "purpose": "Independent bounded review",
                "expected_revision": cycle["revision"],
                "command_id": "packet-profile-a",
            },
        )["packet"]
        self.assertEqual(packet["selected_profile_fact_ids"], [fact_id])
        self.assertEqual(packet["packet"]["profile_facts"][0]["fact_id"], fact_id)
        self.assertEqual(packet["packet"]["evidence_references"], [])

    def test_application_schema_rejects_arbitrary_identity_and_raw_genome_fields(
        self,
    ) -> None:
        with self.assertRaises(OperationError) as identity:
            call_operation("lab.describe_workspace", {"user_id": "other-user"})
        self.assertEqual(identity.exception.code, "invalid_params")

        with self.assertRaises(OperationError) as raw:
            call_operation(
                "lab.start_investigation",
                {
                    "question": "A bounded inquiry",
                    "command_id": "raw-rejected",
                    "agi_rows": [{"chrom": "1", "pos": 1}],
                },
            )
        self.assertEqual(raw.exception.code, "invalid_params")

    def test_current_session_result_receipt_captures_exact_genomi_evidence(
        self,
    ) -> None:
        result = call_operation(
            "phenotype.normalize_terms",
            {"text": "recurrent infections and low platelets"},
        )
        receipt_id = result["result_receipt_id"]
        started = call_operation(
            "lab.start_investigation",
            {
                "question": "Could the bounded immune observations be connected?",
                "command_id": "receipt-start-a",
            },
        )
        investigation_id = started["investigation"]["investigation_id"]
        investigation = self.store.get_investigation(investigation_id)
        cycle = call_operation(
            "lab.start_cycle",
            {
                "investigation_id": investigation_id,
                "objective": "Capture exact normalized phenotype evidence",
                "expected_revision": investigation["domain_revision"],
                "command_id": "receipt-cycle-a",
            },
        )["cycle"]
        params = {
            "investigation_id": investigation_id,
            "cycle_id": cycle["cycle_id"],
            "result_receipt_id": receipt_id,
            "relationship": "context",
            "expected_revision": cycle["revision"],
            "command_id": "receipt-capture-a",
        }
        captured = call_operation("lab.capture_evidence_result", params)
        replayed = call_operation("lab.capture_evidence_result", params)

        evidence = captured["evidence_record"]["evidence"]
        self.assertEqual(
            evidence["normalized_phenotypes"], result["normalized_phenotypes"]
        )
        self.assertEqual(evidence["evidence_envelope"], result["evidence_envelope"])
        self.assertEqual(
            evidence["lab_capture"]["capture_boundary"],
            "opaque_current_session_result_receipt",
        )
        self.assertEqual(
            captured["evidence_record"]["evidence_record_id"],
            replayed["evidence_record"]["evidence_record_id"],
        )

        foreign_receipt = EVIDENCE_RESULT_RECEIPTS.issue(
            session_id="different-session",
            operation="phenotype.normalize_terms",
            result={
                key: value
                for key, value in result.items()
                if key != "result_receipt_id"
            },
        )
        current_cycle = self.store.get_cycle(cycle["cycle_id"])
        with self.assertRaises(OperationError) as rejected:
            call_operation(
                "lab.capture_evidence_result",
                {
                    **params,
                    "result_receipt_id": foreign_receipt,
                    "expected_revision": current_cycle["revision"],
                    "command_id": "receipt-capture-foreign",
                },
            )
        self.assertEqual(rejected.exception.code, "invalid_evidence_result_receipt")

    def test_report_bytes_stay_encrypted_until_review_creates_profile_facts(
        self,
    ) -> None:
        content = b"SYNTHETIC PRIVATE REPORT: IgG 410 mg/dL"
        params = {
            "content_base64": base64.b64encode(content).decode("ascii"),
            "source_type": "laboratory_report",
            "title": "Synthetic immune testing report",
            "media_type": "text/plain",
            "command_id": "report-ingest-a",
        }
        stored = call_operation("lab.ingest_report", params)
        replayed = call_operation("lab.ingest_report", params)
        report = stored["report"]

        self.assertEqual(report, replayed["report"])
        self.assertTrue(report["content_stored"])
        self.assertEqual(report["byte_size"], len(content))
        self.assertNotIn("content_base64", report)
        self.assertNotIn(content, self.store.path.read_bytes())
        self.assertEqual(
            self.store.read_report_content(self.user_id, report["artifact_id"]),
            (content, "text/plain"),
        )

        proposal = call_operation(
            "lab.propose_report_facts",
            {
                "artifact_id": report["artifact_id"],
                "proposals": [
                    {
                        "modality": "biomarker",
                        "label": "Synthetic low IgG",
                        "original_wording": "Synthetic report records IgG 410 mg/dL.",
                    }
                ],
                "command_id": "report-propose-a",
            },
        )["proposals"][0]
        self.assertEqual(
            self.store.list_profile_observations(self.user_id, current_only=True),
            [],
        )
        reviewed = call_operation(
            "lab.review_report_facts",
            {
                "decisions": [
                    {"proposal_id": proposal["proposal_id"], "action": "accept"}
                ],
                "reviewed_by": "current_patient",
                "command_id": "report-review-a",
            },
        )["proposals"][0]
        self.assertEqual(reviewed["status"], "accepted")
        observations = self.store.list_profile_observations(
            self.user_id, current_only=True
        )
        self.assertEqual(observations[0]["artifact_id"], report["artifact_id"])
        self.assertEqual(observations[0]["source_class"], "issued_record")


if __name__ == "__main__":
    unittest.main()
