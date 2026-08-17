from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from genomi.lab.encrypted_sqlite import StaticEncryptionKeyProvider
from genomi.lab.service import GenomiLabService, LabError
from genomi.lab.store import GenomiLabStore
from tests.genomilab_support import synthetic_ready_agi_context


class _CurrentGenomiContext:
    def __init__(self) -> None:
        self.agi_id = "agi-portal-context"
        self.agi_snapshot_id = "agi-snapshot-portal-context"

    def __call__(
        self,
        operation: str,
        params: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        del params
        if operation == "genomi.describe_context":
            return synthetic_ready_agi_context(
                "portal-context-user",
                "Portal context user",
                agi_id=self.agi_id,
                agi_snapshot_id=self.agi_snapshot_id,
            )
        if operation == "active_genome_index.revoke_access":
            return {"status": "revoked"}
        raise AssertionError(f"unexpected operation: {operation}")


class GenomiLabPortalContextTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.genomi_context = _CurrentGenomiContext()
        self.service = GenomiLabService(
            store=GenomiLabStore(
                Path(temporary.name) / "genomilab.sqlite3",
                key_provider=StaticEncryptionKeyProvider(b"p" * 32),
            ),
            session_id="portal-context-session",
            operation_call=self.genomi_context,
        )
        self.addCleanup(self.service.close)
        self.service.bootstrap_workspace()
        self.report = self.service.add_source_artifact(
            {
                "content_sha256": "1" * 64,
                "source_type": "laboratory_report",
                "title": "Synthetic portal-context report",
            }
        )
        self.finding = self.service.add_profile_observation(
            {
                "modality": "reported_germline_finding",
                "label": "A reported variant",
                "reported_variant": "rs123",
                "assertion_status": "present",
                "source_class": "issued_record",
                "verification_state": "user_confirmed",
                "artifact_id": self.report["artifact_id"],
            }
        )
        self.phenotype = self.service.add_profile_observation(
            {
                "modality": "phenotype",
                "label": "A reviewed phenotype",
                "assertion_status": "present",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            }
        )
        investigation = self.service.create_investigation(
            {
                "question": "Could this reported finding help explain the condition?",
                "disease_scope": "Synthetic condition",
            }
        )
        self.investigation_id = str(investigation["investigation_id"])

    @staticmethod
    def _approval(
        candidate: dict[str, Any], *, refresh: bool = False
    ) -> dict[str, Any]:
        approval = {
            key: candidate[key]
            for key in (
                "purpose",
                "observation_revision_ids",
                "artifact_ids",
                "specimen_ids",
                "assay_ids",
                "agi_id",
                "agi_snapshot_id",
                "genomic_scope",
                "candidate_sha256",
                "candidate_receipt",
            )
        } | {"approved": True}
        if refresh:
            approval["refresh"] = True
        return approval

    def test_domain_compiles_the_exact_genomi_scope_for_portal_review(self) -> None:
        candidate = self.service.investigation_context_candidate(
            self.investigation_id,
            {
                "purpose": "Investigate the synthetic condition",
                "use_current_agi": False,
                "observation_revision_ids": [self.finding["observation_revision_id"]],
            },
        )

        self.assertEqual(candidate["agi_id"], "agi-portal-context")
        self.assertEqual(candidate["agi_snapshot_id"], "agi-snapshot-portal-context")
        self.assertEqual(
            candidate["genomic_scope"],
            {
                "operation": "variant.resolve",
                "genome_build": "GRCh38",
                "include_fail": False,
                "limit": 20,
                "rsid": "rs123",
            },
        )
        self.assertEqual(
            candidate["observation_revision_ids"],
            [self.finding["observation_revision_id"]],
        )

    def test_portal_requires_an_explicit_nonempty_profile_selection(self) -> None:
        for payload in (
            {"purpose": "Investigate the synthetic condition"},
            {
                "purpose": "Investigate the synthetic condition",
                "observation_revision_ids": [],
            },
        ):
            with self.subTest(payload=payload), self.assertRaises(LabError) as raised:
                self.service.investigation_context_candidate(
                    self.investigation_id, payload
                )
            self.assertEqual(raised.exception.code, "invalid_context_selection")

    def test_reviewed_phenotype_authorizes_only_bounded_candidate_gene_reads(
        self,
    ) -> None:
        candidate = self.service.investigation_context_candidate(
            self.investigation_id,
            {
                "purpose": "Investigate the reviewed phenotype",
                "observation_revision_ids": [self.phenotype["observation_revision_id"]],
            },
        )
        approval = self._approval(candidate)
        with (
            mock.patch(
                "genomi.lab.profile_context_application."
                "issue_investigation_agi_authorization",
                return_value=object(),
            ),
            mock.patch(
                "genomi.lab.profile_context_application."
                "revoke_investigation_agi_authorizations_for_investigation"
            ),
        ):
            self.service._approve_context_for_conformance(
                self.investigation_id, approval
            )

        projected = self.service.investigation_profile(self.investigation_id)

        self.assertEqual(
            [
                observation["observation_revision_id"]
                for observation in projected["observations"]
            ],
            [self.phenotype["observation_revision_id"]],
        )
        self.assertFalse(projected["source_artifacts"])
        self.assertEqual(
            projected["agi_snapshot_id"], "agi-snapshot-portal-context"
        )
        self.assertEqual(
            candidate["genomic_scope"],
            {
                "operation": "variant.find_gene_variants",
                "genome_build": "GRCh38",
                "gene_count_limit": 10,
                "passing_filters_only": True,
                "per_gene_limit": 100,
                "match_basis": "gencode_gene_interval_overlap",
            },
        )

    def test_refresh_rejects_a_superseded_observation_revision(self) -> None:
        revised = self.service.review_or_supersede_observation(
            str(self.phenotype["observation_revision_id"]),
            {"label": "A corrected reviewed phenotype"},
        )
        self.assertNotEqual(
            revised["observation_revision_id"],
            self.phenotype["observation_revision_id"],
        )

        with self.assertRaises(LabError) as raised:
            self.service.investigation_context_candidate(
                self.investigation_id,
                {
                    "purpose": "Investigate the reviewed phenotype",
                    "observation_revision_ids": [
                        self.phenotype["observation_revision_id"]
                    ],
                    "use_current_agi": True,
                },
            )

        self.assertEqual(raised.exception.code, "invalid_context_selection")

    def test_portal_cannot_supply_or_widen_a_genomi_operation_scope(self) -> None:
        forbidden = (
            {
                "purpose": "Synthetic purpose",
                "include_genome": True,
            },
            {
                "purpose": "Synthetic purpose",
                "genomic_scope": {
                    "operation": "variant.resolve",
                    "rsid": "rs999",
                },
            },
            {
                "purpose": "Synthetic purpose",
                "operation": "variant.resolve",
            },
        )
        for payload in forbidden:
            with self.subTest(payload=payload), self.assertRaises(LabError) as raised:
                self.service.investigation_context_candidate(
                    self.investigation_id, payload
                )
            self.assertEqual(raised.exception.code, "invalid_context_selection")

    def test_ambiguous_reported_variants_do_not_create_a_genome_scope(self) -> None:
        second_finding = self.service.add_profile_observation(
            {
                "modality": "reported_germline_finding",
                "label": "A second reported variant",
                "reported_variant": "rs456",
                "assertion_status": "present",
                "source_class": "issued_record",
                "verification_state": "user_confirmed",
                "artifact_id": self.report["artifact_id"],
            }
        )

        candidate = self.service.investigation_context_candidate(
            self.investigation_id,
            {
                "purpose": "Investigate ambiguous reported findings",
                "observation_revision_ids": [
                    self.finding["observation_revision_id"],
                    second_finding["observation_revision_id"],
                ],
            },
        )

        self.assertIsNone(candidate["agi_id"])
        self.assertIsNone(candidate["agi_snapshot_id"])
        self.assertIsNone(candidate["genomic_scope"])

    def test_refresh_receipt_is_bound_to_the_snapshot_compared(self) -> None:
        initial = self.service.investigation_context_candidate(
            self.investigation_id,
            {
                "purpose": "Investigate the reviewed phenotype",
                "observation_revision_ids": [self.phenotype["observation_revision_id"]],
                "exclude_genome": True,
            },
        )
        self.service._approve_context_for_conformance(
            self.investigation_id, self._approval(initial)
        )
        broad = self.service.investigation_context_candidate(
            self.investigation_id,
            {
                "purpose": "Investigate the broader current profile",
                "observation_revision_ids": [
                    self.finding["observation_revision_id"],
                    self.phenotype["observation_revision_id"],
                ],
                "use_current_agi": True,
            },
        )
        narrow = self.service.investigation_context_candidate(
            self.investigation_id,
            {
                "purpose": "Keep the selected phenotype only",
                "observation_revision_ids": [self.phenotype["observation_revision_id"]],
                "use_current_agi": True,
                "exclude_genome": True,
            },
        )
        self.service._approve_context_for_conformance(
            self.investigation_id, self._approval(narrow, refresh=True)
        )

        with self.assertRaises(LabError) as stale:
            self.service._approve_context_for_conformance(
                self.investigation_id, self._approval(broad, refresh=True)
            )
        self.assertEqual(stale.exception.code, "invalid_context_approval")

    def test_initial_candidate_rejects_an_agi_that_changed_after_preview(self) -> None:
        candidate = self.service.investigation_context_candidate(
            self.investigation_id,
            {
                "purpose": "Investigate the reported finding",
                "observation_revision_ids": [self.finding["observation_revision_id"]],
            },
        )
        self.genomi_context.agi_id = "agi-replaced"
        self.genomi_context.agi_snapshot_id = "agi-snapshot-replaced"

        with self.assertRaises(LabError) as stale:
            self.service._approve_context_for_conformance(
                self.investigation_id, self._approval(candidate)
            )
        self.assertEqual(stale.exception.code, "invalid_context_approval")


if __name__ == "__main__":
    unittest.main()
