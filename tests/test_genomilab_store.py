from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context


class GenomiLabStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self.genomi_home = Path(self._temporary_home.name) / "genomi-home"
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "genomilab-store-tests",
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)

    def test_workspace_is_stable_and_keyed_only_to_genomi_user(self) -> None:
        store = GenomiLabStore()
        created = store.open_workspace("user-a", "Synthetic user A")
        reopened = GenomiLabStore().open_workspace(
            "user-a", "Renamed display"
        )

        self.assertEqual(created["workspace_id"], reopened["workspace_id"])
        self.assertEqual(reopened["user_id"], "user-a")
        self.assertEqual(store.list_workspace_user_ids(), ["user-a"])
        self.assertFalse(hasattr(store, "create_profile"))
        self.assertFalse(hasattr(store, "list_profiles"))

    def test_observation_revisions_preserve_history_and_current_view(self) -> None:
        store = GenomiLabStore()
        store.open_workspace("user-a", "Synthetic user A")
        original = store.add_profile_observation(
            "user-a",
            {
                "modality": "phenotype",
                "label": "Intermittent weakness",
                "original_wording": "Sometimes my muscles feel weak",
                "verification_state": "user_confirmed",
                "source_class": "patient_reported",
            },
        )
        revision = store.add_profile_observation(
            "user-a",
            {
                "modality": "phenotype",
                "label": "Progressive muscle weakness",
                "original_wording": "Weakness has become progressive",
                "verification_state": "user_confirmed",
                "source_class": "patient_reported",
                "supersedes_revision_id": original["observation_revision_id"],
            },
        )

        self.assertEqual(
            original["logical_observation_id"], revision["logical_observation_id"]
        )
        self.assertEqual(len(store.list_profile_observations("user-a")), 2)
        self.assertEqual(
            [
                row["observation_revision_id"]
                for row in store.list_profile_observations("user-a", current_only=True)
            ],
            [revision["observation_revision_id"]],
        )

        with self.assertRaisesRegex(ValueError, "must remain unreviewed"):
            store.add_profile_observation(
                "user-a",
                {
                    "modality": "condition",
                    "label": "Extracted diagnosis",
                    "source_class": "model_extracted",
                    "verification_state": "record_confirmed",
                },
            )
        with self.assertRaisesRegex(ValueError, "explicit negative requires"):
            store.add_profile_observation(
                "user-a",
                {
                    "modality": "biomarker",
                    "label": "Marker not detected",
                    "assertion_status": "absent",
                    "source_identifier": "synthetic-report-negative",
                    "source_class": "issued_record",
                    "verification_state": "record_confirmed",
                    "coverage_state": "explicitly_not_detected_within_declared_assay_scope",
                },
            )
        for coverage_state in ("observed", "not_measured"):
            with (
                self.subTest(coverage_state=coverage_state),
                self.assertRaisesRegex(
                    ValueError, "requires explicit within-scope coverage"
                ),
            ):
                store.add_profile_observation(
                    "user-a",
                    {
                        "modality": "reported_germline_finding",
                        "label": "Reported variant absent",
                        "assertion_status": "absent",
                        "source_identifier": "synthetic-report-negative",
                        "source_class": "issued_record",
                        "verification_state": "record_confirmed",
                        "coverage_state": coverage_state,
                    },
                )

    def test_store_uses_private_sqlite_storage_and_declared_indexes(self) -> None:
        store = GenomiLabStore()
        store.open_workspace("user-a", "Synthetic user")

        self.assertEqual(store.path, self.genomi_home / "lab" / "lab.sqlite3")
        database = store.path.read_bytes()
        self.assertTrue(database.startswith(b"SQLite format 3\x00"))
        self.assertFalse(store.path.with_name(f"{store.path.name}-wal").exists())
        self.assertFalse(store.path.with_name(f"{store.path.name}-shm").exists())
        expected = {
            "molecular_observations": "idx_observations_user_created",
            "profile_snapshots": "idx_snapshots_user_created",
            "consent_receipts": "idx_consents_session_user",
            "investigations": "idx_investigations_user_created",
            "evidence_records": "idx_evidence_investigation_created",
        }
        for table, index in expected.items():
            with self.subTest(table=table):
                self.assertIn(index, store.indexes_for(table))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(store.path.parent.stat().st_mode), 0o700)

    def test_atomic_write_rolls_back_the_complete_multi_repository_transition(
        self,
    ) -> None:
        store = GenomiLabStore()
        store.open_workspace("user-a", "Synthetic user A")

        with self.assertRaisesRegex(RuntimeError, "late transition failure"):
            with store.atomic_write():
                store.open_workspace("user-b", "Synthetic user B")
                store.add_profile_observation(
                    "user-b",
                    {
                        "modality": "phenotype",
                        "label": "Transient observation",
                        "source_class": "patient_reported",
                        "verification_state": "user_confirmed",
                    },
                )
                raise RuntimeError("late transition failure")

        self.assertEqual(store.list_workspace_user_ids(), ["user-a"])


if __name__ == "__main__":
    unittest.main()
