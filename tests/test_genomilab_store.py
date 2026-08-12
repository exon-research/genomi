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

    def test_profile_without_genome_is_a_persisted_first_class_record(self) -> None:
        store = GenomiLabStore()

        created = store.create_profile("  Synthetic patient  ")

        self.assertEqual(created["display_name"], "Synthetic patient")
        self.assertIsNone(created["genome"])
        self.assertEqual(created["health_facts"], [])
        self.assertEqual(created["reported_findings"], [])
        self.assertEqual(created["investigations"], [])

        reopened = GenomiLabStore()
        persisted = reopened.get_profile(created["profile_id"])
        self.assertEqual(persisted["profile_id"], created["profile_id"])
        self.assertIsNone(persisted["genome"])
        self.assertEqual(reopened.list_profiles()[0]["health_fact_count"], 0)
        self.assertEqual(reopened.list_profiles()[0]["finding_count"], 0)

        with self.assertRaisesRegex(ValueError, "display_name is required"):
            store.create_profile("   ")

    def test_health_facts_and_findings_validate_modes_and_persist_by_profile(self) -> None:
        store = GenomiLabStore()
        patient = store.create_profile("Synthetic patient A")
        other = store.create_profile("Synthetic patient B")
        patient_id = str(patient["profile_id"])
        other_id = str(other["profile_id"])

        health_fact_kinds = {
            "condition",
            "symptom",
            "medication",
            "allergy",
            "measurement",
            "procedure",
            "family_history",
            "exposure",
        }
        assertion_statuses = {"present", "absent", "unknown"}
        verification_states = {
            "unreviewed",
            "user_confirmed",
            "record_confirmed",
            "clinician_confirmed",
        }

        accepted_kinds = {
            store.add_health_fact(
                patient_id,
                kind=kind,
                label=f"Accepted {kind}",
            )["kind"]
            for kind in health_fact_kinds
        }
        self.assertEqual(accepted_kinds, health_fact_kinds)

        accepted_assertions = {
            store.add_health_fact(
                patient_id,
                kind="condition",
                label=f"Assertion {assertion}",
                assertion_status=assertion,
            )["assertion_status"]
            for assertion in assertion_statuses
        }
        self.assertEqual(accepted_assertions, assertion_statuses)

        accepted_verifications = {
            store.add_health_fact(
                patient_id,
                kind="symptom",
                label=f"Verification {verification}",
                verification_state=verification,
            )["verification_state"]
            for verification in verification_states
        }
        self.assertEqual(accepted_verifications, verification_states)

        original = store.add_health_fact(
            patient_id,
            kind="medication",
            label="Synthetic medication",
            onset="2026-01",
            source_type="patient_reported",
        )
        replacement = store.add_health_fact(
            patient_id,
            kind="medication",
            label="Synthetic medication, corrected",
            supersedes_fact_id=original["fact_id"],
        )
        self.assertEqual(replacement["supersedes_fact_id"], original["fact_id"])

        other_fact = store.add_health_fact(
            other_id,
            kind="condition",
            label="Other profile condition",
        )
        with self.assertRaisesRegex(ValueError, "must name a fact in this profile"):
            store.add_health_fact(
                patient_id,
                kind="condition",
                label="Invalid cross-profile replacement",
                supersedes_fact_id=other_fact["fact_id"],
            )

        invalid_health_values = (
            {"kind": "unsupported", "label": "Label"},
            {"kind": "condition", "label": "", "assertion_status": "present"},
            {"kind": "condition", "label": "Label", "assertion_status": "maybe"},
            {"kind": "condition", "label": "Label", "verification_state": "guessed"},
        )
        for payload in invalid_health_values:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                store.add_health_fact(patient_id, **payload)

        rsid = store.add_reported_finding(
            patient_id,
            variant="RS900000001",
            gene="SYNTH1",
            reported_classification="research finding",
            source_label="synthetic fixture",
        )
        exact = store.add_reported_finding(
            patient_id,
            variant="chr1:100:A:C",
        )
        review = store.add_reported_finding(
            patient_id,
            variant="c.123A>G",
        )
        self.assertEqual((rsid["variant"], rsid["normalization_state"]), ("rs900000001", "rsid_ready"))
        self.assertEqual(exact["normalization_state"], "exact_genomic_allele_ready")
        self.assertEqual(review["normalization_state"], "needs_review")
        with self.assertRaisesRegex(ValueError, "variant is required"):
            store.add_reported_finding(patient_id, variant=" ")

        reopened = GenomiLabStore()
        persisted = reopened.get_profile(patient_id)
        self.assertEqual(
            {item["finding_id"] for item in persisted["reported_findings"]},
            {rsid["finding_id"], exact["finding_id"], review["finding_id"]},
        )
        self.assertNotIn(other_fact["fact_id"], {item["fact_id"] for item in persisted["health_facts"]})
        summaries = {item["profile_id"]: item for item in reopened.list_profiles()}
        self.assertEqual(summaries[patient_id]["finding_count"], 3)
        self.assertEqual(summaries[other_id]["health_fact_count"], 1)

    def test_store_uses_private_wal_storage_and_declared_query_indexes(self) -> None:
        store = GenomiLabStore()
        store.create_profile("Synthetic patient")

        self.assertEqual(store.path, self.genomi_home / "lab" / "genomilab.sqlite3")
        with sqlite3.connect(store.path) as connection:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(str(journal_mode).lower(), "wal")

        expected_indexes = {
            "health_facts": "health_facts_profile_created",
            "reported_findings": "reported_findings_profile_created",
            "portal_jobs": "portal_jobs_profile_created",
            "consent_receipts": "consent_profile_session",
            "investigations": "investigations_profile_created",
        }
        for table, expected in expected_indexes.items():
            with self.subTest(table=table):
                self.assertIn(expected, store.indexes_for(table))
        with self.assertRaisesRegex(ValueError, "unsupported table"):
            store.indexes_for("profiles")

        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(store.path.parent.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
