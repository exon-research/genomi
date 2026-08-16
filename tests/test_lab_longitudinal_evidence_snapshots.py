from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context


class LabLongitudinalEvidenceSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._temporary_home.name) / "home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "lab-longitudinal-evidence-tests",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore()
        self.store.open_workspace("user-a", "Synthetic user")

    def test_profile_refresh_carries_public_evidence_into_current_snapshot(self) -> None:
        created = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Could the synthetic observations share an explanation?",
            command_id="create-investigation",
        )
        investigation_id = str(created["investigation"]["investigation_id"])
        first_profile = self.store.update_health_profile(
            "user-a",
            investigation_id,
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Synthetic recurring observation",
                    "original_wording": "A synthetic observation was reported",
                }
            ],
            purpose="Capture the initial report",
            command_id="initial-profile",
            expected_revision=1,
        )
        self.assertEqual(first_profile["domain_revision"], 2)
        self.assertEqual(first_profile["evidence_snapshot"]["evidence_record_ids"], [])

        cycle = self.store.create_investigation_cycle(
            investigation_id,
            purpose="Consult public evidence",
            command_id="initial-cycle",
            expected_revision=2,
        )
        operation = "variant.resolve"
        receipt_id = self.store.issue_genomi_result_receipt(
            operation=operation,
            params={"rsid": "rs000000"},
            presented_result={
                "status": "completed",
                "evidence_envelope": {
                    "operation": operation,
                    "headline": f"{operation}: data_returned",
                    "finding_state": "evidence_present",
                    "answer_readiness": "answer_supported",
                    "guidance": [],
                    "negative_inference": {"allowed": False, "requires": []},
                    "coverage": {"consulted_sources": ["synthetic-public-source"]},
                },
                "records": [{"identifier": "public-record"}],
            },
            investigation_id=investigation_id,
            workspace_session_id="session-a",
        )
        captured = self.store.capture_evidence_result(
            investigation_id,
            cycle_id=cycle["cycle"]["cycle_id"],
            result_receipt_id=receipt_id,
            purpose="Capture public evidence",
            command_id="capture-public-evidence",
            expected_revision=cycle["domain_revision"],
        )
        evidence_id = str(captured["evidence_record"]["evidence_record_id"])

        refreshed = self.store.update_health_profile(
            "user-a",
            investigation_id,
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Synthetic recurring observation",
                    "original_wording": "A synthetic observation was reported",
                },
                {
                    "modality": "measurement",
                    "label": "Synthetic follow-up measurement",
                    "original_wording": "A follow-up synthetic measurement was reported",
                },
            ],
            purpose="Add longitudinal follow-up",
            command_id="refresh-profile",
            expected_revision=captured["domain_revision"],
        )

        self.assertNotEqual(
            refreshed["profile_snapshot"]["patient_molecular_snapshot_id"],
            first_profile["profile_snapshot"]["patient_molecular_snapshot_id"],
        )
        self.assertEqual(
            refreshed["evidence_snapshot"]["patient_molecular_snapshot_id"],
            refreshed["profile_snapshot"]["patient_molecular_snapshot_id"],
        )
        self.assertEqual(
            refreshed["evidence_snapshot"]["evidence_record_ids"], [evidence_id]
        )
        self.assertEqual(
            self.store.get_investigation(investigation_id)["evidence_snapshot_id"],
            refreshed["evidence_snapshot"]["evidence_snapshot_id"],
        )


if __name__ == "__main__":
    unittest.main()
