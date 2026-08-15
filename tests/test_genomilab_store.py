from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


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
        store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
        created = store.open_workspace("user-a", "Synthetic user A")
        reopened = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER).open_workspace(
            "user-a", "Renamed display"
        )

        self.assertEqual(created["workspace_id"], reopened["workspace_id"])
        self.assertEqual(reopened["user_id"], "user-a")
        self.assertEqual(store.list_workspace_user_ids(), ["user-a"])
        self.assertFalse(hasattr(store, "create_profile"))
        self.assertFalse(hasattr(store, "list_profiles"))

    def test_provider_connection_command_and_event_persist_atomically_redacted(
        self,
    ) -> None:
        store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
        result = {
            "provider": "paperclip",
            "connection_state": "configured_unverified",
            "credential_state": "stored",
            "execution_location": "remote",
            "policy_state": "blocked_missing_deployment_authorization",
            "investigation_operations": [],
            "investigation_routes": [],
            "investigation_purposes": [],
            "last_verified_at": None,
            "use_scope": "fixed_public_connection_probe",
            "verification_kind": "fixed_public_search",
            "verification_may_consume_credits": True,
            "verification_available": True,
        }

        command_id = store.record_provider_connection_command(
            workspace_session_id="genomilab-store-tests",
            provider="paperclip",
            action="connect",
            result=result,
        )
        persisted = store.list_provider_connection_commands("genomilab-store-tests")
        events = store.list_provider_connection_events("genomilab-store-tests")

        self.assertEqual(persisted[0]["command_id"], command_id)
        self.assertEqual(persisted[0]["result"], result)
        self.assertEqual(events[0]["command_id"], command_id)
        self.assertEqual(
            events[0]["event_type"], "provider_connection_connect_recorded"
        )
        self.assertEqual(events[0]["payload"], result)
        self.assertNotIn("api_key", repr([persisted, events]))
        with self.assertRaisesRegex(ValueError, "not redacted"):
            store.record_provider_connection_command(
                workspace_session_id="genomilab-store-tests",
                provider="paperclip",
                action="connect",
                result={"provider": "paperclip", "api_key": "must-not-persist"},
            )

    def test_provider_connection_event_failure_rolls_back_command(self) -> None:
        store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
        with store._connect() as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_provider_connection_event
                BEFORE INSERT ON provider_connection_events
                BEGIN
                    SELECT RAISE(ABORT, 'synthetic event failure');
                END
                """
            )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic event failure"):
            store.record_provider_connection_command(
                workspace_session_id="genomilab-store-tests",
                provider="paperclip",
                action="connect",
                result={
                    "provider": "paperclip",
                    "connection_state": "configured_unverified",
                },
            )

        self.assertEqual(
            store.list_provider_connection_commands("genomilab-store-tests"), []
        )
        self.assertEqual(
            store.list_provider_connection_events("genomilab-store-tests"), []
        )

    def test_observation_revisions_preserve_history_and_current_view(self) -> None:
        store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
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

    def test_store_uses_encrypted_private_storage_and_declared_indexes(self) -> None:
        store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
        store.open_workspace("user-a", "Synthetic user")

        self.assertEqual(store.path, self.genomi_home / "lab" / "genomilab.sqlite3")
        ciphertext = store.path.read_bytes()
        self.assertFalse(ciphertext.startswith(b"SQLite format 3\x00"))
        self.assertNotIn(b"Synthetic user", ciphertext)
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
        store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
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
