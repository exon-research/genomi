from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


class GenomiLabProfileIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._temporary_home.name) / "home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "genomilab-profile-integrity",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
        self.store.open_workspace("user-a", "Synthetic user")

    def _phenotype(self, label: str, **updates: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "modality": "phenotype",
            "label": label,
            "original_wording": label,
            "source_class": "patient_reported",
            "verification_state": "user_confirmed",
        }
        payload.update(updates)
        return self.store.add_profile_observation("user-a", payload)

    def test_only_clinician_provenance_can_be_clinician_confirmed(self) -> None:
        disallowed = (
            ("patient_reported", "patient"),
            ("caregiver_reported", "caregiver"),
            ("issued_record", "imported_record"),
            ("issued_record", "clinician"),
            ("model_extracted", "model"),
            ("clinician_entered", "patient"),
        )
        for source_class, assertion_author in disallowed:
            with (
                self.subTest(
                    source_class=source_class, assertion_author=assertion_author
                ),
                self.assertRaisesRegex(ValueError, "clinician-entered"),
            ):
                self.store.add_profile_observation(
                    "user-a",
                    {
                        "modality": "condition",
                        "label": "Reported condition",
                        "source_class": source_class,
                        "assertion_author": assertion_author,
                        "verification_state": "clinician_confirmed",
                        "reviewed_by": "self-asserted reviewer",
                    },
                )

        patient_observation = self._phenotype("Patient-reported weakness")
        with self.assertRaisesRegex(ValueError, "clinician-entered"):
            self.store.review_or_supersede_observation(
                "user-a",
                str(patient_observation["observation_revision_id"]),
                {
                    "verification_state": "clinician_confirmed",
                    "reviewed_by": "self-asserted reviewer",
                },
            )

        with self.assertRaisesRegex(ValueError, "reviewed_by"):
            self.store.add_profile_observation(
                "user-a",
                {
                    "modality": "condition",
                    "label": "Clinician-entered condition",
                    "source_class": "clinician_entered",
                    "assertion_author": "clinician",
                    "verification_state": "clinician_confirmed",
                },
            )

        confirmed = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "condition",
                "label": "Clinician-entered condition",
                "source_class": "clinician_entered",
                "assertion_author": "clinician",
                "verification_state": "clinician_confirmed",
                "reviewed_by": "clinician:synthetic-reviewer",
            },
        )
        self.assertEqual(confirmed["verification_state"], "clinician_confirmed")
        self.assertEqual(confirmed["assertion_author"], "clinician")

    def test_database_rejects_in_place_observation_rewrites(self) -> None:
        observation = self._phenotype("Patient-reported weakness")
        investigation = self.store.create_investigation(
            "user-a", question="Could this phenotype relate to the condition?"
        )
        candidate = self.store.profile_snapshot_candidate(
            "user-a",
            investigation_id=investigation["investigation_id"],
            purpose="Investigate the selected phenotype",
            observation_revision_ids=[observation["observation_revision_id"]],
        )
        self.store.create_profile_snapshot(
            "user-a",
            workspace_session_id="session-a",
            investigation_id=investigation["investigation_id"],
            purpose="Investigate the selected phenotype",
            observation_revision_ids=[observation["observation_revision_id"]],
            candidate_sha256=candidate["candidate_sha256"],
            approved=True,
        )
        before = self.store.project_investigation_profile(
            str(investigation["investigation_id"])
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "revisions are immutable"):
            with self.store._connect() as connection:
                connection.execute(
                    "UPDATE molecular_observations "
                    "SET verification_state = 'clinician_confirmed', "
                    "reviewed_by = 'self-asserted reviewer' "
                    "WHERE observation_revision_id = ?",
                    (observation["observation_revision_id"],),
                )
        after = self.store.project_investigation_profile(
            str(investigation["investigation_id"])
        )
        self.assertEqual(after, before)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "revisions are immutable"):
            with self.store._connect() as connection:
                connection.execute(
                    "DELETE FROM molecular_observations "
                    "WHERE observation_revision_id = ?",
                    (observation["observation_revision_id"],),
                )
        self.assertEqual(
            self.store.project_investigation_profile(
                str(investigation["investigation_id"])
            ),
            before,
        )
        with self.store._connect() as connection:
            connection.execute(
                "DROP TRIGGER molecular_observations_revision_delete_immutable"
            )
            connection.execute(
                "DELETE FROM molecular_observations WHERE observation_revision_id = ?",
                (observation["observation_revision_id"],),
            )
        with self.assertRaisesRegex(ValueError, "missing observation revisions"):
            self.store.project_investigation_profile(
                str(investigation["investigation_id"])
            )

    def test_database_rejects_in_place_profile_entity_rewrites(self) -> None:
        artifact = self.store.add_source_artifact(
            "user-a",
            {
                "content_sha256": "7" * 64,
                "source_type": "laboratory_report",
                "title": "Immutable report",
            },
        )
        specimen = self.store.add_specimen(
            "user-a",
            {
                "artifact_id": artifact["artifact_id"],
                "specimen_type": "blood",
                "tumor_normal_role": "germline",
            },
        )
        self.store.add_assay(
            "user-a",
            {
                "artifact_id": artifact["artifact_id"],
                "specimen_id": specimen["specimen_id"],
                "assay_type": "synthetic panel",
                "assay_scope": {"genes": ["SYNTH1"]},
                "detection_limits": {"minimum_vaf": 0.2},
            },
        )
        mutations = (
            ("source_artifacts", "title", "Rewritten", "source artifacts"),
            ("specimens", "body_site", "Rewritten", "specimens"),
            ("assays", "assay_scope_json", "{}", "assays"),
        )
        for table, column, value, message in mutations:
            with (
                self.subTest(table=table),
                self.assertRaisesRegex(sqlite3.IntegrityError, message),
            ):
                with self.store._connect() as connection:
                    connection.execute(
                        f"UPDATE {table} SET {column} = ? WHERE user_id = ?",
                        (value, "user-a"),
                    )
            with (
                self.subTest(table=f"{table}_delete"),
                self.assertRaisesRegex(sqlite3.IntegrityError, message),
            ):
                with self.store._connect() as connection:
                    connection.execute(
                        f"DELETE FROM {table} WHERE user_id = ?", ("user-a",)
                    )
        entities = self.store.list_profile_entities("user-a")
        self.assertEqual(entities["source_artifacts"][0]["title"], "Immutable report")
        self.assertIsNone(entities["specimens"][0]["body_site"])
        self.assertEqual(entities["assays"][0]["assay_scope"], {"genes": ["SYNTH1"]})

    def test_revision_target_has_exactly_one_successor_under_concurrency(self) -> None:
        original = self._phenotype("Original phenotype")
        original_id = str(original["observation_revision_id"])
        barrier = threading.Barrier(2)

        def supersede(label: str) -> tuple[str, object]:
            store = GenomiLabStore(self.store.path, key_provider=TEST_LAB_KEY_PROVIDER)
            barrier.wait(timeout=5)
            try:
                result = store.add_profile_observation(
                    "user-a",
                    {
                        "modality": "phenotype",
                        "label": label,
                        "source_class": "patient_reported",
                        "verification_state": "user_confirmed",
                        "supersedes_revision_id": original_id,
                    },
                )
                return "created", result
            except ValueError as exc:
                return "rejected", str(exc)

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    supersede, ("Concurrent correction A", "Concurrent correction B")
                )
            )

        self.assertEqual([state for state, _ in outcomes].count("created"), 1)
        self.assertEqual([state for state, _ in outcomes].count("rejected"), 1)
        rejection = next(value for state, value in outcomes if state == "rejected")
        self.assertIn("current observation revision", str(rejection))

        history = self.store.list_profile_observations("user-a")
        children = [
            row for row in history if row["supersedes_revision_id"] == original_id
        ]
        self.assertEqual(len(children), 1)
        self.assertIn(
            "idx_observations_one_successor",
            self.store.indexes_for("molecular_observations"),
        )

    def test_new_root_rejects_caller_logical_identity_under_concurrency(self) -> None:
        barrier = threading.Barrier(2)

        def create_root(label: str) -> tuple[str, object]:
            store = GenomiLabStore(self.store.path, key_provider=TEST_LAB_KEY_PROVIDER)
            barrier.wait(timeout=5)
            try:
                return (
                    "created",
                    store.add_profile_observation(
                        "user-a",
                        {
                            "modality": "phenotype",
                            "label": label,
                            "logical_observation_id": "observation-caller-forged",
                        },
                    ),
                )
            except ValueError as exc:
                return "rejected", str(exc)

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(create_root, ("Forged root A", "Forged root B"))
            )

        self.assertEqual([state for state, _ in outcomes], ["rejected", "rejected"])
        self.assertTrue(
            all("assigned by GenomiLab" in str(value) for _, value in outcomes)
        )
        self.assertEqual(self.store.list_profile_observations("user-a"), [])

    def test_logical_identity_is_retained_only_by_a_valid_successor(self) -> None:
        original = self._phenotype("Original phenotype")
        with self.assertRaisesRegex(ValueError, "retain its logical_observation_id"):
            self._phenotype(
                "Forged successor",
                supersedes_revision_id=original["observation_revision_id"],
                logical_observation_id="observation-not-the-prior-identity",
            )
        successor = self._phenotype(
            "Valid successor",
            supersedes_revision_id=original["observation_revision_id"],
            logical_observation_id=original["logical_observation_id"],
        )
        self.assertEqual(
            successor["logical_observation_id"], original["logical_observation_id"]
        )

    def test_database_rejects_a_forged_root_logical_identity(self) -> None:
        original = self._phenotype("Original phenotype")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "invalid logical identity"):
            with self.store._connect() as connection:
                columns = [
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(molecular_observations)"
                    ).fetchall()
                ]
                replacements = {
                    "observation_revision_id": "?",
                    "created_at": "?",
                }
                projection = ", ".join(
                    replacements.get(column, f'"{column}"') for column in columns
                )
                connection.execute(
                    f"INSERT INTO molecular_observations "
                    f"({', '.join(columns)}) "
                    f"SELECT {projection} FROM molecular_observations "
                    f"WHERE observation_revision_id = ?",
                    (
                        "observation-revision-forged-root",
                        "2099-01-01T00:00:00Z",
                        original["observation_revision_id"],
                    ),
                )

    def test_reopen_repairs_legacy_duplicate_roots_before_installing_invariant(
        self,
    ) -> None:
        original = self._phenotype("Legacy root")
        successor = self._phenotype(
            "Legacy successor",
            supersedes_revision_id=original["observation_revision_id"],
        )
        with self.store._connect() as connection:
            connection.execute("DROP INDEX idx_observations_one_root")
            connection.execute(
                "DROP TRIGGER molecular_observations_root_identity_insert"
            )
            connection.execute("DROP TRIGGER molecular_observations_revision_immutable")
            columns = [
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(molecular_observations)"
                ).fetchall()
            ]
            replacements = {
                "observation_revision_id": "?",
                "label": "?",
                "created_at": "?",
            }
            projection = ", ".join(
                replacements.get(column, f'"{column}"') for column in columns
            )
            connection.execute(
                f"INSERT INTO molecular_observations "
                f"({', '.join(columns)}) "
                f"SELECT {projection} FROM molecular_observations "
                f"WHERE observation_revision_id = ?",
                (
                    "observation-revision-legacy-duplicate-root",
                    "Legacy duplicate root",
                    "2099-01-01T00:00:00Z",
                    original["observation_revision_id"],
                ),
            )

        reopened = GenomiLabStore(self.store.path, key_provider=TEST_LAB_KEY_PROVIDER)
        heads = reopened.list_profile_observations("user-a", current_only=True)
        self.assertEqual(len(heads), 2)
        self.assertEqual(len({row["logical_observation_id"] for row in heads}), 2)
        migrated_original = reopened.get_profile_observation(
            "user-a", str(original["observation_revision_id"])
        )
        migrated_successor = reopened.get_profile_observation(
            "user-a", str(successor["observation_revision_id"])
        )
        self.assertEqual(
            migrated_successor["logical_observation_id"],
            migrated_original["logical_observation_id"],
        )
        self.assertIn(
            "idx_observations_one_root",
            reopened.indexes_for("molecular_observations"),
        )

    def test_database_uniqueness_rejects_a_second_revision_branch(self) -> None:
        original = self._phenotype("Original phenotype")
        original_id = str(original["observation_revision_id"])
        first = self._phenotype("First correction", supersedes_revision_id=original_id)

        with self.assertRaises(sqlite3.IntegrityError):
            with self.store._connect() as connection:
                columns = [
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(molecular_observations)"
                    ).fetchall()
                ]
                replacements = {
                    "observation_revision_id": "?",
                    "supersedes_revision_id": "?",
                    "created_at": "?",
                }
                projection = ", ".join(
                    replacements.get(column, f'"{column}"') for column in columns
                )
                connection.execute(
                    f"INSERT INTO molecular_observations "
                    f"({', '.join(columns)}) "
                    f"SELECT {projection} FROM molecular_observations "
                    f"WHERE observation_revision_id = ?",
                    (
                        "observation-revision-forged-branch",
                        original_id,
                        "2099-01-01T00:00:00Z",
                        first["observation_revision_id"],
                    ),
                )

    def test_revision_target_must_be_the_current_head_not_only_childless(self) -> None:
        original = self._phenotype("Original phenotype")
        successor = self._phenotype(
            "First correction",
            supersedes_revision_id=original["observation_revision_id"],
        )
        with self.assertRaisesRegex(ValueError, "current observation revision"):
            self.store.add_profile_observation(
                "user-a",
                {
                    "modality": "phenotype",
                    "label": "Attempted branch",
                    "source_class": "patient_reported",
                    "verification_state": "user_confirmed",
                    "supersedes_revision_id": original["observation_revision_id"],
                },
            )
        current = self._phenotype(
            "Second correction",
            supersedes_revision_id=successor["observation_revision_id"],
        )
        self.assertEqual(
            current["logical_observation_id"], original["logical_observation_id"]
        )

    def test_existing_workspace_installs_integrity_objects_when_reopened(self) -> None:
        with self.store._connect() as connection:
            connection.execute("PRAGMA user_version = 999")
            connection.execute("DROP INDEX idx_observations_one_successor")
            connection.execute(
                "DROP TRIGGER molecular_observations_revision_chain_insert"
            )
            connection.execute(
                "DROP TRIGGER molecular_observations_root_identity_insert"
            )
            connection.execute("DROP TRIGGER molecular_observations_revision_immutable")
            connection.execute("DROP TRIGGER molecular_observations_clinician_insert")
            connection.execute("DROP TRIGGER source_artifacts_immutable")
            connection.execute("DROP TRIGGER specimens_immutable")
            connection.execute("DROP TRIGGER assays_immutable")

        reopened = GenomiLabStore(self.store.path, key_provider=TEST_LAB_KEY_PROVIDER)
        self.assertEqual(reopened.list_workspace_user_ids(), ["user-a"])
        self.assertIn(
            "idx_observations_one_successor",
            reopened.indexes_for("molecular_observations"),
        )
        with reopened._connect() as connection:
            names = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'trigger' "
                    "AND name LIKE 'molecular_observations_%'"
                ).fetchall()
            }
        self.assertEqual(
            names,
            {
                "molecular_observations_revision_chain_insert",
                "molecular_observations_root_identity_insert",
                "molecular_observations_revision_immutable",
                "molecular_observations_revision_delete_immutable",
                "molecular_observations_clinician_insert",
                "molecular_observations_issued_source_insert",
                "molecular_observations_issued_artifact_insert",
                "molecular_observations_record_confirmation_source_insert",
            },
        )

    def test_snapshot_coverage_is_derived_from_exact_selected_revisions(self) -> None:
        observed = self._phenotype(
            "Observed weakness", coverage_state="observed", assertion_status="present"
        )
        not_provided = self._phenotype(
            "History not provided",
            coverage_state="not_provided",
            assertion_status="unknown",
        )
        investigation = self.store.create_investigation(
            "user-a", question="Could the reported finding relate to this condition?"
        )
        candidate_arguments = {
            "investigation_id": investigation["investigation_id"],
            "purpose": "Investigate selected phenotype context",
            "observation_revision_ids": [observed["observation_revision_id"]],
        }
        observed_only = self.store.profile_snapshot_candidate(
            "user-a", **candidate_arguments
        )
        self.assertEqual(
            observed_only["modality_coverage"],
            [
                {
                    "modality": "phenotype",
                    "coverage_state": "observed",
                    "observation_revision_ids": [observed["observation_revision_id"]],
                    "assertion_statuses": ["present"],
                }
            ],
        )

        self._phenotype("Later unavailable history", coverage_state="unavailable")
        same_selection = self.store.profile_snapshot_candidate(
            "user-a", **candidate_arguments
        )
        self.assertEqual(
            same_selection["modality_coverage"], observed_only["modality_coverage"]
        )
        self.assertEqual(
            same_selection["candidate_sha256"], observed_only["candidate_sha256"]
        )

        mixed = self.store.profile_snapshot_candidate(
            "user-a",
            investigation_id=investigation["investigation_id"],
            purpose="Investigate selected phenotype context",
            observation_revision_ids=[
                not_provided["observation_revision_id"],
                observed["observation_revision_id"],
            ],
        )
        by_state = {
            entry["coverage_state"]: entry for entry in mixed["modality_coverage"]
        }
        self.assertEqual(set(by_state), {"observed", "not_provided"})
        self.assertEqual(
            by_state["observed"]["observation_revision_ids"],
            [observed["observation_revision_id"]],
        )
        self.assertEqual(by_state["observed"]["assertion_statuses"], ["present"])
        self.assertEqual(
            by_state["not_provided"]["observation_revision_ids"],
            [not_provided["observation_revision_id"]],
        )
        self.assertEqual(by_state["not_provided"]["assertion_statuses"], ["unknown"])

        snapshot = self.store.create_profile_snapshot(
            "user-a",
            workspace_session_id="session-a",
            investigation_id=investigation["investigation_id"],
            purpose="Investigate selected phenotype context",
            observation_revision_ids=mixed["observation_revision_ids"],
            candidate_sha256=mixed["candidate_sha256"],
            approved=True,
        )
        self.assertEqual(snapshot["modality_coverage"], mixed["modality_coverage"])


if __name__ == "__main__":
    unittest.main()
