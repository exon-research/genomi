from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


class GenomiLabSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self.genomi_home = Path(self._temporary_home.name) / "genomi-home"
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "genomilab-snapshot-tests",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
        self.store.open_workspace("user-a", "Synthetic user")
        self.observation = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "reported_germline_finding",
                "label": "Report states rs900000001",
                "original_wording": "rs900000001 was listed on the report",
                "reported_variant": "rs900000001",
                "gene": "SYNTH1",
                "source_identifier": "synthetic-report-001",
                "source_class": "issued_record",
                "verification_state": "record_confirmed",
            },
        )
        self.investigation = self.store.create_investigation(
            "user-a",
            question="Could this finding relate to the synthetic condition?",
            disease_scope="Synthetic condition",
        )

    def test_snapshot_requires_approval_and_exact_agi_pair(self) -> None:
        common = {
            "workspace_session_id": "session-a",
            "investigation_id": self.investigation["investigation_id"],
            "purpose": "Investigate the synthetic condition",
            "observation_revision_ids": [self.observation["observation_revision_id"]],
        }
        with self.assertRaisesRegex(ValueError, "explicit approval"):
            self.store.create_profile_snapshot("user-a", **common)
        with self.assertRaisesRegex(ValueError, "supplied together"):
            self.store.create_profile_snapshot(
                "user-a", **common, approved=True, agi_id="agi-a"
            )

    def test_snapshot_candidate_requires_an_explicit_nonempty_observation_selection(
        self,
    ) -> None:
        for selection in (None, []):
            with (
                self.subTest(selection=selection),
                self.assertRaisesRegex(
                    ValueError, "select at least one profile observation"
                ),
            ):
                self.store.profile_snapshot_candidate(
                    "user-a",
                    investigation_id=self.investigation["investigation_id"],
                    purpose="Investigate the synthetic condition",
                    observation_revision_ids=selection,
                )

    def test_snapshot_approval_is_bound_to_exact_preview(self) -> None:
        candidate = self.store.profile_snapshot_candidate(
            "user-a",
            investigation_id=self.investigation["investigation_id"],
            purpose="Investigate the synthetic condition",
            observation_revision_ids=[self.observation["observation_revision_id"]],
        )
        with self.assertRaisesRegex(ValueError, "changed after preview"):
            self.store.create_profile_snapshot(
                "user-a",
                workspace_session_id="session-a",
                investigation_id=self.investigation["investigation_id"],
                purpose="A widened and unreviewed purpose",
                observation_revision_ids=[self.observation["observation_revision_id"]],
                candidate_sha256=candidate["candidate_sha256"],
                approved=True,
            )

    def test_approved_snapshot_round_trips_without_raw_genome(self) -> None:
        candidate = self.store.profile_snapshot_candidate(
            "user-a",
            investigation_id=self.investigation["investigation_id"],
            purpose="Investigate the synthetic condition",
            observation_revision_ids=[self.observation["observation_revision_id"]],
            agi_id="agi-a",
            agi_snapshot_id="agi-snapshot-a",
            genomic_scope={"operation": "variant.resolve", "rsid": "rs900000001"},
        )
        snapshot = self.store.create_profile_snapshot(
            "user-a",
            workspace_session_id="session-a",
            investigation_id=self.investigation["investigation_id"],
            purpose="Investigate the synthetic condition",
            observation_revision_ids=[self.observation["observation_revision_id"]],
            agi_id="agi-a",
            agi_snapshot_id="agi-snapshot-a",
            genomic_scope={"operation": "variant.resolve", "rsid": "rs900000001"},
            candidate_sha256=candidate["candidate_sha256"],
            approved=True,
        )
        reopened = GenomiLabStore(
            self.store.path, key_provider=TEST_LAB_KEY_PROVIDER
        ).get_profile_snapshot(snapshot["patient_molecular_snapshot_id"])
        self.assertEqual(reopened["agi_id"], "agi-a")
        self.assertEqual(reopened["agi_snapshot_id"], "agi-snapshot-a")
        self.assertEqual(
            reopened["observation_revision_ids"],
            [self.observation["observation_revision_id"]],
        )
        receipt = self.store.consent_receipt(reopened["consent_receipt_id"])
        self.assertEqual(
            receipt["patient_molecular_snapshot_id"],
            reopened["patient_molecular_snapshot_id"],
        )
        serialized = json.dumps(reopened)
        for forbidden in ("source_path", "agi_path", "raw_agi_rows", "patient.vcf"):
            self.assertNotIn(forbidden, serialized)

        investigation = self.store.get_investigation(
            self.investigation["investigation_id"]
        )
        self.assertEqual(
            investigation["patient_molecular_snapshot_id"],
            reopened["patient_molecular_snapshot_id"],
        )
        self.assertEqual(investigation["agi_snapshot_id"], reopened["agi_snapshot_id"])

    def test_same_context_renewal_atomically_supersedes_prior_consent(self) -> None:
        candidate = self.store.profile_snapshot_candidate(
            "user-a",
            investigation_id=self.investigation["investigation_id"],
            purpose="Investigate the synthetic condition",
            observation_revision_ids=[self.observation["observation_revision_id"]],
        )
        arguments = {
            "investigation_id": self.investigation["investigation_id"],
            "purpose": "Investigate the synthetic condition",
            "observation_revision_ids": [self.observation["observation_revision_id"]],
            "candidate_sha256": candidate["candidate_sha256"],
            "approved": True,
        }
        original = self.store.create_profile_snapshot(
            "user-a", workspace_session_id="session-a", **arguments
        )

        def fail_authorization(_claims: dict[str, object]) -> None:
            raise RuntimeError("synthetic authorization failure")

        with self.assertRaisesRegex(RuntimeError, "synthetic authorization failure"):
            self.store.create_profile_snapshot(
                "user-a",
                workspace_session_id="session-b",
                expected_base_patient_molecular_snapshot_id=original[
                    "patient_molecular_snapshot_id"
                ],
                authorization_before_commit=fail_authorization,
                **arguments,
            )
        after_failure = self.store.get_investigation(
            self.investigation["investigation_id"]
        )
        self.assertEqual(
            after_failure["active_consent_receipt_id"],
            original["consent_receipt_id"],
        )
        self.assertIsNone(
            self.store.consent_receipt(original["consent_receipt_id"])["revoked_at"]
        )
        self.assertEqual(
            len(self.store.workspace_activity("user-a")["context_approvals"]), 1
        )

        renewed = self.store.create_profile_snapshot(
            "user-a",
            workspace_session_id="session-b",
            expected_base_patient_molecular_snapshot_id=original[
                "patient_molecular_snapshot_id"
            ],
            **arguments,
        )
        self.assertEqual(renewed["context_change"], "authorization_renewed")
        self.assertFalse(renewed["snapshot_created"])
        activity = self.store.workspace_activity("user-a")["context_approvals"]
        active = [item for item in activity if item["revoked_at"] is None]
        self.assertEqual(
            [item["consent_receipt_id"] for item in active],
            [renewed["consent_receipt_id"]],
        )
        self.assertIsNotNone(
            self.store.consent_receipt(original["consent_receipt_id"])["revoked_at"]
        )

    def test_concurrent_refreshes_atomically_reject_a_stale_preview(self) -> None:
        original_candidate = self.store.profile_snapshot_candidate(
            "user-a",
            investigation_id=self.investigation["investigation_id"],
            purpose="Investigate the synthetic condition",
            observation_revision_ids=[self.observation["observation_revision_id"]],
        )
        original = self.store.create_profile_snapshot(
            "user-a",
            workspace_session_id="session-a",
            investigation_id=self.investigation["investigation_id"],
            purpose="Investigate the synthetic condition",
            observation_revision_ids=[self.observation["observation_revision_id"]],
            candidate_sha256=original_candidate["candidate_sha256"],
            approved=True,
        )
        second_observation = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "reported_somatic_finding",
                "label": "Report states SYNTH2 p.V2A",
                "original_wording": "SYNTH2 p.V2A was listed on the report",
                "reported_variant": "SYNTH2 p.V2A",
                "gene": "SYNTH2",
                "source_identifier": "synthetic-report-002",
                "source_class": "issued_record",
                "verification_state": "record_confirmed",
            },
        )
        selections = (
            [second_observation["observation_revision_id"]],
            [
                self.observation["observation_revision_id"],
                second_observation["observation_revision_id"],
            ],
        )
        candidates = [
            self.store.profile_snapshot_candidate(
                "user-a",
                investigation_id=self.investigation["investigation_id"],
                purpose="Investigate the synthetic condition",
                observation_revision_ids=selection,
            )
            for selection in selections
        ]
        stores = (
            GenomiLabStore(self.store.path, key_provider=TEST_LAB_KEY_PROVIDER),
            GenomiLabStore(self.store.path, key_provider=TEST_LAB_KEY_PROVIDER),
        )
        barrier = threading.Barrier(2)

        def approve(index: int) -> dict[str, object]:
            barrier.wait(timeout=5)
            return stores[index].create_profile_snapshot(
                "user-a",
                workspace_session_id=f"session-refresh-{index}",
                investigation_id=self.investigation["investigation_id"],
                purpose="Investigate the synthetic condition",
                observation_revision_ids=selections[index],
                candidate_sha256=candidates[index]["candidate_sha256"],
                approved=True,
                refresh=True,
                expected_base_patient_molecular_snapshot_id=original[
                    "patient_molecular_snapshot_id"
                ],
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(approve, index) for index in range(2)]
            results: list[dict[str, object]] = []
            failures: list[BaseException] = []
            for future in futures:
                try:
                    results.append(future.result(timeout=10))
                except BaseException as exc:  # noqa: BLE001 - test captures the race loser
                    failures.append(exc)

        self.assertEqual(len(results), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], ValueError)
        self.assertIn("context changed after preview", str(failures[0]))
        investigation = self.store.get_investigation(
            self.investigation["investigation_id"]
        )
        self.assertEqual(
            investigation["patient_molecular_snapshot_id"],
            results[0]["patient_molecular_snapshot_id"],
        )

    def test_observation_change_does_not_mutate_or_auto_mint_snapshot(self) -> None:
        candidate = self.store.profile_snapshot_candidate(
            "user-a",
            investigation_id=self.investigation["investigation_id"],
            purpose="Investigate the synthetic condition",
            observation_revision_ids=[self.observation["observation_revision_id"]],
        )
        snapshot = self.store.create_profile_snapshot(
            "user-a",
            workspace_session_id="session-a",
            investigation_id=self.investigation["investigation_id"],
            purpose="Investigate the synthetic condition",
            observation_revision_ids=[self.observation["observation_revision_id"]],
            candidate_sha256=candidate["candidate_sha256"],
            approved=True,
        )
        revised = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "reported_germline_finding",
                "label": "Corrected report entry",
                "original_wording": "Corrected report entry",
                "reported_variant": "rs900000002",
                "source_identifier": "synthetic-report-001",
                "source_class": "issued_record",
                "verification_state": "record_confirmed",
                "supersedes_revision_id": self.observation["observation_revision_id"],
            },
        )
        unchanged = self.store.get_profile_snapshot(
            snapshot["patient_molecular_snapshot_id"]
        )
        self.assertEqual(
            unchanged["observation_revision_ids"],
            [self.observation["observation_revision_id"]],
        )
        self.assertNotIn(
            revised["observation_revision_id"], unchanged["observation_revision_ids"]
        )


if __name__ == "__main__":
    unittest.main()
