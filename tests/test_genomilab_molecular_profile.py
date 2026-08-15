from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context


class GenomiLabMolecularProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._temporary_home.name) / "home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "genomilab-profile-entities",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore()
        self.store.open_workspace("user-a", "Synthetic user")

    def _issued_assay(
        self,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        artifact = self.store.add_source_artifact(
            "user-a",
            {
                "content_sha256": "a" * 64,
                "source_type": "laboratory_report",
                "title": "Synthetic molecular report",
                "source_identifier": "report-001",
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
        assay = self.store.add_assay(
            "user-a",
            {
                "artifact_id": artifact["artifact_id"],
                "specimen_id": specimen["specimen_id"],
                "assay_type": "targeted germline panel",
                "laboratory": "Synthetic laboratory",
                "genome_build": "GRCh38",
                "assay_scope": {"genes": ["SYNTH1", "SYNTH2"]},
                "detection_limits": {"snv_vaf_percent": 20},
            },
        )
        return artifact, specimen, assay

    def test_sources_specimens_and_assays_are_owned_profile_entities(self) -> None:
        artifact, specimen, assay = self._issued_assay()
        finding = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "reported_germline_finding",
                "label": "Report states rs900000001",
                "reported_variant": "rs900000001",
                "artifact_id": artifact["artifact_id"],
                "specimen_id": specimen["specimen_id"],
                "assay_id": assay["assay_id"],
                "source_class": "issued_record",
                "verification_state": "record_confirmed",
            },
        )
        profile = self.store.get_workspace("user-a")["profile"]
        self.assertEqual(profile["source_artifacts"], [artifact])
        self.assertEqual(profile["specimens"], [specimen])
        self.assertEqual(profile["assays"], [assay])
        self.assertEqual(finding["artifact_id"], artifact["artifact_id"])

        self.store.open_workspace("user-b", "Other user")
        with self.assertRaisesRegex(ValueError, "current user"):
            self.store.add_profile_observation(
                "user-b",
                {
                    "modality": "condition",
                    "label": "Cross-user reference",
                    "artifact_id": artifact["artifact_id"],
                },
            )

        self.assertEqual(
            self.store.add_source_artifact(
                "user-a",
                {
                    "content_sha256": "a" * 64,
                    "source_type": "laboratory_report",
                    "title": "Synthetic molecular report",
                    "source_identifier": "report-001",
                },
            ),
            artifact,
        )
        with self.assertRaisesRegex(ValueError, "different immutable metadata"):
            self.store.add_source_artifact(
                "user-a",
                {
                    "content_sha256": "a" * 64,
                    "source_type": "pathology_report",
                    "title": "Conflicting title",
                },
            )

    def test_explicit_negative_requires_a_scoped_assay_with_detection_limits(
        self,
    ) -> None:
        artifact, _, assay = self._issued_assay()
        negative = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "reported_germline_finding",
                "label": "SYNTH2 not detected within the panel scope",
                "reported_variant": "SYNTH2 report negative",
                "assertion_status": "absent",
                "coverage_state": "explicitly_not_detected_within_declared_assay_scope",
                "assay_id": assay["assay_id"],
                "source_class": "issued_record",
                "verification_state": "record_confirmed",
            },
        )
        self.assertEqual(
            negative["coverage_state"],
            "explicitly_not_detected_within_declared_assay_scope",
        )
        self.assertEqual(negative["artifact_id"], artifact["artifact_id"])
        with self.assertRaisesRegex(ValueError, "change at least one field"):
            self.store.review_or_supersede_observation(
                "user-a",
                str(negative["observation_revision_id"]),
                {"artifact_id": None},
            )
        with self.assertRaisesRegex(ValueError, "scope and detection limits"):
            self.store.add_profile_observation(
                "user-a",
                {
                    "modality": "condition",
                    "label": "Unsupported negative",
                    "assertion_status": "absent",
                    "coverage_state": "explicitly_not_detected_within_declared_assay_scope",
                },
            )

        for modality, assertion_status in (
            ("condition", "present"),
            ("condition", "unknown"),
            ("pathology", "present"),
        ):
            with (
                self.subTest(modality=modality, assertion_status=assertion_status),
                self.assertRaisesRegex(ValueError, "requires an absent"),
            ):
                self.store.add_profile_observation(
                    "user-a",
                    {
                        "modality": modality,
                        "label": "Contradictory non-detection state",
                        "assertion_status": assertion_status,
                        "coverage_state": "explicitly_not_detected_within_declared_assay_scope",
                        "assay_id": assay["assay_id"],
                    },
                )

    def test_absence_cannot_be_inferred_from_missing_non_molecular_coverage(
        self,
    ) -> None:
        for modality in ("condition", "phenotype", "pathology", "measurement"):
            for coverage_state in (
                "not_measured",
                "not_provided",
                "unavailable",
                "out_of_scope",
            ):
                with (
                    self.subTest(
                        modality=modality,
                        coverage_state=coverage_state,
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "absent observation cannot use missing",
                    ),
                ):
                    self.store.add_profile_observation(
                        "user-a",
                        {
                            "modality": modality,
                            "label": "Synthetic absence",
                            "assertion_status": "absent",
                            "coverage_state": coverage_state,
                        },
                    )

    def test_free_text_molecular_finding_preserves_report_wording(self) -> None:
        artifact, specimen, assay = self._issued_assay()
        finding = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "reported_somatic_finding",
                "label": "Report states an ALK fusion",
                "artifact_id": artifact["artifact_id"],
                "specimen_id": specimen["specimen_id"],
                "assay_id": assay["assay_id"],
                "source_class": "issued_record",
                "verification_state": "record_confirmed",
            },
        )
        self.assertEqual(finding["reported_variant"], "Report states an ALK fusion")
        self.assertEqual(finding["normalization_state"], "needs_review")

    def test_model_extraction_requires_a_named_human_review_revision(self) -> None:
        extracted = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "phenotype",
                "label": "Possible weakness",
                "source_class": "model_extracted",
                "verification_state": "unreviewed",
                "normalization_provenance": {
                    "software": "fixture-extractor",
                    "version": "1.0",
                },
            },
        )
        with self.assertRaisesRegex(ValueError, "named human review"):
            self.store.review_or_supersede_observation(
                "user-a",
                extracted["observation_revision_id"],
                {"verification_state": "user_confirmed"},
            )
        reviewed = self.store.review_or_supersede_observation(
            "user-a",
            extracted["observation_revision_id"],
            {
                "verification_state": "user_confirmed",
                "reviewed_by": "current_user",
                "label": "Intermittent weakness",
            },
        )
        self.assertEqual(
            reviewed["supersedes_revision_id"], extracted["observation_revision_id"]
        )
        self.assertEqual(
            reviewed["normalization_provenance"]["software"], "fixture-extractor"
        )
        self.assertEqual(
            self.store.get_profile_observation(
                "user-a", extracted["observation_revision_id"]
            )["verification_state"],
            "unreviewed",
        )

    def test_snapshot_closes_over_sources_specimens_assays_and_compare_does_not_mint(
        self,
    ) -> None:
        artifact, specimen, assay = self._issued_assay()
        finding = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "reported_germline_finding",
                "label": "Report states rs900000001",
                "reported_variant": "rs900000001",
                "artifact_id": artifact["artifact_id"],
                "specimen_id": specimen["specimen_id"],
                "assay_id": assay["assay_id"],
                "source_class": "issued_record",
                "verification_state": "record_confirmed",
            },
        )
        investigation = self.store.create_investigation(
            "user-a", question="Could this finding relate to the condition?"
        )
        scope = {"operation": "variant.resolve", "rsid": "rs900000001"}
        candidate = self.store.profile_snapshot_candidate(
            "user-a",
            investigation_id=investigation["investigation_id"],
            purpose="Investigate the reported finding",
            observation_revision_ids=[finding["observation_revision_id"]],
            agi_id="agi-a",
            agi_snapshot_id="agi-snapshot-a",
            genomic_scope=scope,
        )
        self.assertEqual(candidate["artifact_ids"], [artifact["artifact_id"]])
        self.assertEqual(candidate["specimen_ids"], [specimen["specimen_id"]])
        self.assertEqual(candidate["assay_ids"], [assay["assay_id"]])
        snapshot = self.store.create_profile_snapshot(
            "user-a",
            workspace_session_id="session-a",
            approved=True,
            **{
                key: value
                for key, value in candidate.items()
                if key
                in {
                    "investigation_id",
                    "purpose",
                    "observation_revision_ids",
                    "artifact_ids",
                    "specimen_ids",
                    "assay_ids",
                    "agi_id",
                    "agi_snapshot_id",
                    "genomic_scope",
                    "candidate_sha256",
                }
            },
        )
        self.assertEqual(snapshot["genomic_scope"], scope)
        receipt = self.store.consent_receipt(snapshot["consent_receipt_id"])
        self.assertEqual(receipt["artifact_ids"], [artifact["artifact_id"]])
        comparison = self.store.compare_profile_snapshot(
            snapshot["patient_molecular_snapshot_id"], candidate
        )
        self.assertEqual(comparison["status"], "unchanged")
        self.assertFalse(comparison["snapshot_created"])


if __name__ == "__main__":
    unittest.main()
