from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from genomi.lab import operations as lab_operations
from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context


class LabSpecialistFactBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._temporary_home.name) / "home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "lab-specialist-fact-binding-tests",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore()
        self.store.open_workspace("user-a", "Synthetic user")

    def _authorized_store(self):
        @contextmanager
        def authorized():
            yield self.store, "user-a", "session-a"

        return authorized

    def test_profile_update_fact_binding_can_prepare_specialist_brief(self) -> None:
        created = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Could the reported features have a shared explanation?",
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

        self.assertEqual(
            updated["source_fact_ids"],
            updated["profile_snapshot"]["observation_revision_ids"],
        )
        cycle = self.store.create_investigation_cycle(
            investigation_id,
            purpose="Research a general mechanism",
            command_id="create-cycle",
            expected_revision=2,
        )
        brief = self.store.prepare_specialist_brief(
            investigation_id,
            cycle_id=cycle["cycle"]["cycle_id"],
            specialist_role="Public evidence reviewer",
            execution_policy="reasoning_only",
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

        self.assertEqual(
            brief["internal_derivation"]["source_fact_ids"],
            updated["source_fact_ids"],
        )

    def test_incomplete_selected_agi_is_an_evidence_gap_not_a_profile_blocker(
        self,
    ) -> None:
        created = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Could the reported features have a shared explanation?",
            command_id="create-investigation-with-pending-agi",
        )
        investigation_id = str(created["investigation"]["investigation_id"])
        incomplete_context = {
            "active_agi_id": "agi-selected",
            "active_genome_index_access": {"approved": True},
            "active_genome_index": {
                "agi_id": "agi-selected",
                "agi_snapshot_id": None,
                "active_genome_index_readiness": {
                    "status": "completed",
                    "complete": True,
                    "variants_ready": True,
                    "reason": "snapshot_identity_missing",
                    "retry_operation": "genomi.parse_source",
                },
            },
        }
        with (
            mock.patch.object(
                lab_operations, "_authorized_store", self._authorized_store()
            ),
            mock.patch.object(
                lab_operations, "describe_context", return_value=incomplete_context
            ),
        ):
            updated = lab_operations.update_health_profile(
                {
                    "investigation_id": investigation_id,
                    "facts": [
                        {
                            "modality": "phenotype",
                            "label": "Synthetic private feature",
                            "original_wording": "Synthetic private wording",
                        }
                    ],
                    "purpose": "Capture the reported feature",
                    "command_id": "update-profile-with-pending-agi",
                    "expected_revision": 1,
                }
            )

        self.assertIsNone(updated["profile_snapshot"]["agi_id"])
        self.assertEqual(
            updated["agi_evidence_gap"]["state"],
            "selected_active_genome_index_missing_snapshot_identity",
        )
        self.assertEqual(
            updated["agi_evidence_gap"]["blocked_evidence_scope"],
            ["sample_specific_genome_evidence"],
        )
        first_cycle = self.store.create_investigation_cycle(
            investigation_id,
            purpose="Start with public evidence",
            command_id="public-evidence-first-cycle",
            expected_revision=2,
        )
        self.assertIsNotNone(first_cycle["cycle"]["patient_molecular_snapshot_id"])
        first_snapshot_id = first_cycle["cycle"]["patient_molecular_snapshot_id"]
        with self.store._connect() as connection:
            first_snapshot = connection.execute(
                "SELECT agi_id, agi_snapshot_id FROM profile_snapshots "
                "WHERE patient_molecular_snapshot_id = ?",
                (first_snapshot_id,),
            ).fetchone()
        self.assertIsNone(first_snapshot["agi_id"])
        self.assertIsNone(first_snapshot["agi_snapshot_id"])

        ready_context = {
            "active_agi_id": "agi-selected",
            "active_genome_index_access": {"approved": True},
            "active_genome_index": {
                "agi_id": "agi-selected",
                "agi_snapshot_id": "agi-snapshot-ready",
                "active_genome_index_readiness": {
                    "status": "completed",
                    "complete": True,
                    "variants_ready": True,
                },
            },
        }
        with (
            mock.patch.object(
                lab_operations, "_authorized_store", self._authorized_store()
            ),
            mock.patch.object(
                lab_operations, "describe_context", return_value=ready_context
            ),
        ):
            rebound = lab_operations.update_health_profile(
                {
                    "investigation_id": investigation_id,
                    "facts": [
                        {
                            "modality": "measurement",
                            "label": "Synthetic follow-up measurement",
                            "original_wording": "Synthetic follow-up wording",
                        }
                    ],
                    "purpose": "Add follow-up context and bind the ready genome",
                    "command_id": "update-profile-with-ready-agi",
                    "expected_revision": 3,
                }
            )

        self.assertEqual(rebound["profile_snapshot"]["agi_id"], "agi-selected")
        self.assertEqual(
            rebound["profile_snapshot"]["agi_snapshot_id"],
            "agi-snapshot-ready",
        )
        self.assertNotIn("agi_evidence_gap", rebound)


if __name__ == "__main__":
    unittest.main()
