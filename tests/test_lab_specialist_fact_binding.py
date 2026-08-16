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

    def test_repeated_fact_across_investigations_reuses_one_logical_observation(
        self,
    ) -> None:
        first = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="First synthetic inquiry",
            command_id="create-first-dedup-investigation",
        )
        first_update = self.store.update_health_profile(
            "user-a",
            first["investigation"]["investigation_id"],
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Synthetic recurring feature",
                    "original_wording": "I repeatedly observe the synthetic feature",
                }
            ],
            purpose="Capture the first inquiry",
            command_id="update-first-dedup-investigation",
            expected_revision=1,
        )
        second = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Second synthetic inquiry",
            command_id="create-second-dedup-investigation",
        )
        second_update = self.store.update_health_profile(
            "user-a",
            second["investigation"]["investigation_id"],
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Synthetic recurring feature",
                    "original_wording": "I repeatedly observe the synthetic feature",
                }
            ],
            purpose="Capture the second inquiry",
            command_id="update-second-dedup-investigation",
            expected_revision=1,
        )

        first_observation = first_update["observations"][0]
        repeated_observation = second_update["observations"][0]
        self.assertEqual(
            repeated_observation["observation_revision_id"],
            first_observation["observation_revision_id"],
        )
        self.assertEqual(
            second_update["source_fact_ids"],
            [first_observation["observation_revision_id"]],
        )
        self.assertEqual(
            len(self.store.list_profile_observations("user-a", current_only=True)),
            1,
        )
        self.assertEqual(len(self.store.list_profile_observations("user-a")), 1)

        revised = self.store.update_health_profile(
            "user-a",
            second["investigation"]["investigation_id"],
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Synthetic recurring feature, clarified",
                    "original_wording": "I repeatedly observe the synthetic feature",
                }
            ],
            purpose="Preserve a corrected extraction as a revision",
            command_id="revise-second-dedup-investigation",
            expected_revision=2,
        )
        revised_observation = revised["observations"][0]
        self.assertNotEqual(
            revised_observation["observation_revision_id"],
            first_observation["observation_revision_id"],
        )
        self.assertEqual(
            revised_observation["logical_observation_id"],
            first_observation["logical_observation_id"],
        )
        self.assertEqual(
            revised_observation["supersedes_revision_id"],
            first_observation["observation_revision_id"],
        )
        self.assertEqual(
            len(self.store.list_profile_observations("user-a", current_only=True)),
            1,
        )
        self.assertEqual(len(self.store.list_profile_observations("user-a")), 2)

    def test_specialist_brief_defaults_to_deduped_current_profile_snapshot(
        self,
    ) -> None:
        first = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="First synthetic inquiry",
            command_id="create-first-brief-default-investigation",
        )
        self.store.update_health_profile(
            "user-a",
            first["investigation"]["investigation_id"],
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Recurrent synthetic episodes",
                    "original_wording": "The synthetic episodes keep happening",
                }
            ],
            purpose="Capture the first extraction",
            command_id="update-first-brief-default-investigation",
            expected_revision=1,
        )
        second = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Second synthetic inquiry",
            command_id="create-second-brief-default-investigation",
        )
        updated = self.store.update_health_profile(
            "user-a",
            second["investigation"]["investigation_id"],
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Repeated synthetic episode",
                    "original_wording": "I continue to experience the synthetic event",
                }
            ],
            purpose="Capture the equivalent extraction",
            command_id="update-second-brief-default-investigation",
            expected_revision=1,
        )
        cycle = self.store.create_investigation_cycle(
            second["investigation"]["investigation_id"],
            purpose="Research a public mechanism",
            command_id="create-brief-default-cycle",
            expected_revision=2,
        )

        brief = self.store.prepare_specialist_brief(
            second["investigation"]["investigation_id"],
            cycle_id=cycle["cycle"]["cycle_id"],
            specialist_role="Public evidence reviewer",
            execution_policy="reasoning_only",
            research_question="Compare public evidence for a reference mechanism.",
            public_concepts=[],
            abstract_relations=[],
            public_evidence_record_ids=[],
            source_fact_ids=None,
            rationale="Research a public mechanism",
            purpose="Research a public mechanism",
            workspace_session_id="session-a",
            command_id="prepare-brief-from-current-snapshot",
            expected_revision=3,
        )

        self.assertEqual(
            brief["internal_derivation"]["source_fact_ids"],
            updated["profile_snapshot"]["observation_revision_ids"],
        )

    def test_semantic_fact_identity_survives_conservative_extraction_drift(
        self,
    ) -> None:
        first = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="First phrasing of a synthetic inquiry",
            command_id="create-first-semantic-identity-investigation",
        )
        first_update = self.store.update_health_profile(
            "user-a",
            first["investigation"]["investigation_id"],
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Recurrent synthetic episodes",
                    "original_wording": "The synthetic episodes keep happening",
                }
            ],
            purpose="Capture the first extraction",
            command_id="update-first-semantic-identity-investigation",
            expected_revision=1,
        )
        second = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Second phrasing of the synthetic inquiry",
            command_id="create-second-semantic-identity-investigation",
        )
        second_update = self.store.update_health_profile(
            "user-a",
            second["investigation"]["investigation_id"],
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Repeated synthetic episode",
                    "original_wording": "I continue to experience the synthetic event",
                    "onset_or_event_time": "historical synthetic period",
                }
            ],
            purpose="Capture the semantically equivalent extraction",
            command_id="update-second-semantic-identity-investigation",
            expected_revision=1,
        )

        original = first_update["observations"][0]
        revised = second_update["observations"][0]
        self.assertEqual(
            revised["logical_observation_id"], original["logical_observation_id"]
        )
        self.assertEqual(
            revised["supersedes_revision_id"], original["observation_revision_id"]
        )
        self.assertEqual(
            second_update["source_fact_ids"],
            [revised["observation_revision_id"]],
        )
        self.assertEqual(
            len(self.store.list_profile_observations("user-a", current_only=True)),
            1,
        )
        self.assertEqual(len(self.store.list_profile_observations("user-a")), 2)

    def test_semantic_fact_identity_keeps_distinct_features_separate(self) -> None:
        created = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Two distinct synthetic features",
            command_id="create-distinct-semantic-features",
        )
        updated = self.store.update_health_profile(
            "user-a",
            created["investigation"]["investigation_id"],
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Recurrent synthetic alpha episodes",
                    "original_wording": "Synthetic alpha events keep happening",
                },
                {
                    "modality": "phenotype",
                    "label": "Repeated synthetic beta episode",
                    "original_wording": "Synthetic beta events keep happening",
                },
            ],
            purpose="Keep distinct reported features separate",
            command_id="update-distinct-semantic-features",
            expected_revision=1,
        )

        self.assertEqual(len(updated["source_fact_ids"]), 2)
        self.assertEqual(
            len(self.store.list_profile_observations("user-a", current_only=True)),
            2,
        )

    def test_semantic_fact_identity_keeps_distinct_explicit_events_separate(
        self,
    ) -> None:
        created = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Two explicitly distinct synthetic events",
            command_id="create-distinct-semantic-events",
        )
        updated = self.store.update_health_profile(
            "user-a",
            created["investigation"]["investigation_id"],
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "measurement",
                    "label": "Synthetic measurement",
                    "original_wording": "The synthetic measurement was reported",
                    "onset_or_event_time": "synthetic period one",
                },
                {
                    "modality": "measurement",
                    "label": "Synthetic measurement",
                    "original_wording": "The synthetic measurement was reported",
                    "onset_or_event_time": "synthetic period two",
                },
            ],
            purpose="Keep distinct explicit events separate",
            command_id="update-distinct-semantic-events",
            expected_revision=1,
        )

        self.assertEqual(len(updated["source_fact_ids"]), 2)
        self.assertEqual(
            len(self.store.list_profile_observations("user-a", current_only=True)),
            2,
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
