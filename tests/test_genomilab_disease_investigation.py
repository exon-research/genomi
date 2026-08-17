from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.evidence import envelope as evidence_envelope
from genomi.lab.disease_relation_contract import REGISTER_DISEASE_RELATION
from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


class _DiseaseInvestigationTestSupport:
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._temporary_home.name) / "home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "genomilab-disease-tests",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore(key_provider=TEST_LAB_KEY_PROVIDER)
        self.store.open_workspace("user-a", "Synthetic user")
        self.condition = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "condition",
                "label": "Synthetic neuromuscular condition",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            },
        )
        self.finding = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "reported_germline_finding",
                "label": "Report states rs900000001",
                "reported_variant": "rs900000001",
                "gene": "SYNTH1",
                "source_identifier": "synthetic-report-001",
                "source_class": "issued_record",
                "verification_state": "record_confirmed",
            },
        )
        self.investigation = self.store.create_investigation(
            "user-a",
            question="Could this molecular finding relate to the condition?",
            disease_scope="Synthetic neuromuscular condition",
        )
        snapshot_candidate = self.store.profile_snapshot_candidate(
            "user-a",
            investigation_id=self.investigation["investigation_id"],
            purpose="Investigate disease against the molecular profile",
            observation_revision_ids=[
                self.condition["observation_revision_id"],
                self.finding["observation_revision_id"],
            ],
            agi_id="agi-a",
            agi_snapshot_id="agi-snapshot-a",
            genomic_scope={"operation": "variant.resolve", "rsid": "rs900000001"},
        )
        self.snapshot = self.store.create_profile_snapshot(
            "user-a",
            workspace_session_id="session-a",
            investigation_id=self.investigation["investigation_id"],
            purpose="Investigate disease against the molecular profile",
            observation_revision_ids=[
                self.condition["observation_revision_id"],
                self.finding["observation_revision_id"],
            ],
            agi_id="agi-a",
            agi_snapshot_id="agi-snapshot-a",
            genomic_scope={"operation": "variant.resolve", "rsid": "rs900000001"},
            candidate_sha256=snapshot_candidate["candidate_sha256"],
            approved=True,
        )

    def _public_source_evidence(
        self, *, key: str = "synthetic-public-source"
    ) -> dict[str, object]:
        return self.store.commit_evidence(
            self.investigation["investigation_id"],
            source_family="literature",
            operation="public_evidence.search",
            evidence={
                "status": "data_returned",
                "records": [{"source_id": "PMID:SYNTHETIC"}],
                "evidence_envelope": evidence_envelope.evidence_present(
                    operation="evidence_provider.literature",
                    coverage={"consulted_sources": ["synthetic-literature"]},
                    observations={"observation_count": 1},
                    answer_readiness=(evidence_envelope.NEEDS_CLINICAL_CONFIRMATION),
                ),
            },
            deduplication_key=key,
        )

    def _relation_parameters(
        self,
        source_evidence_record_id: str,
        *,
        profile_revision_ids: list[str] | None = None,
        disease_scope: str = "Synthetic neuromuscular condition",
        direction: str = "supports",
    ) -> dict[str, object]:
        return {
            "disease_scope": disease_scope,
            "profile_revision_ids": profile_revision_ids
            or [self.finding["observation_revision_id"]],
            "source_evidence_record_ids": [source_evidence_record_id],
            "relation_kind": "variant_disease",
            "direction": direction,
            "source_supplied_strength": {
                "state": "reported",
                "scheme": "source wording",
                "raw_label": "supportive research evidence",
                "raw_value": None,
                "source_locator": "PMID:SYNTHETIC#result",
            },
            "population_context": {
                "state": "reported",
                "description": "Synthetic affected cohort",
                "source_locator": "PMID:SYNTHETIC#cohort",
            },
            "tissue_context": {
                "state": "not_reported",
                "description": None,
                "source_locator": None,
            },
            "specimen_context": {
                "state": "not_applicable",
                "description": None,
                "source_locator": None,
            },
            "conflicts": [],
            "uncertainty": ["association_not_causation"],
        }

class GenomiLabDiseaseInvestigationTests(
    _DiseaseInvestigationTestSupport, unittest.TestCase
):
    def test_profile_projection_is_pinned_and_excludes_agi_evidence(self) -> None:
        projection = self.store.project_investigation_profile(
            self.investigation["investigation_id"]
        )
        self.assertEqual(
            {row["observation_revision_id"] for row in projection["observations"]},
            {
                self.condition["observation_revision_id"],
                self.finding["observation_revision_id"],
            },
        )
        self.assertEqual(projection["agi_snapshot_id"], "agi-snapshot-a")
        self.assertNotIn("sample_context", projection)
        self.assertNotIn("agi_rows", projection)

    def test_brief_commits_grounded_timeline_and_clinician_question_without_promoting_them_to_claims(
        self,
    ) -> None:
        question = (
            "Can the original laboratory report and rs900000001 finding be "
            "independently reviewed or clinically confirmed before interpretation?"
        )
        committed = self.store.commit_brief(
            self.investigation["investigation_id"],
            {
                "title": "Reported finding review",
                "summary": "Patient observation: The profile records rs900000001 as a research observation.",
                "clinical_stage": "research_observation",
                "modality_badges": ["reported_record"],
                "timeline": [
                    {
                        "statement": "Patient observation: The profile records rs900000001 as a research observation.",
                        "evidence_record_ids": [],
                        "profile_revision_ids": [
                            self.finding["observation_revision_id"]
                        ],
                    }
                ],
                "claims": [
                    {
                        "statement": "Patient observation: The profile records rs900000001 as a research observation.",
                        "claim_role": "observation",
                        "evidence_record_ids": [],
                        "profile_revision_ids": [
                            self.finding["observation_revision_id"]
                        ],
                    }
                ],
                "hypothesis_ids": [],
                "gap_ids": [],
                "confirmation_needs": ["Independent review before interpretation"],
                "clinician_questions": [
                    {
                        "question": question,
                        "evidence_record_ids": [],
                        "profile_revision_ids": [
                            self.finding["observation_revision_id"]
                        ],
                        "hypothesis_ids": [],
                        "gap_ids": [],
                    }
                ],
                "clinical_boundary": (
                    "Research support only; this is not a diagnosis or treatment decision."
                ),
                "change_summary": "Prepared a traceable rs900000001 research brief.",
            },
        )

        self.assertEqual(
            committed["brief"]["clinician_questions"][0]["question"], question
        )
        self.assertEqual(len(committed["brief"]["timeline"]), 1)

    def test_brief_commit_rolls_back_its_evidence_basis_after_late_failure(
        self,
    ) -> None:
        brief = {
            "title": "Reported finding review",
            "summary": "Patient observation: The profile records rs900000001 as a research observation.",
            "clinical_stage": "research_observation",
            "modality_badges": ["reported_record"],
            "timeline": [],
            "claims": [
                {
                    "statement": "Patient observation: The profile records rs900000001 as a research observation.",
                    "claim_role": "observation",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [
                        self.finding["observation_revision_id"]
                    ],
                }
            ],
            "hypothesis_ids": [],
            "gap_ids": [],
            "confirmation_needs": ["Independent review before interpretation"],
            "clinician_questions": [],
            "clinical_boundary": (
                "Research support only; this is not a diagnosis or treatment decision."
            ),
            "change_summary": "Prepared a traceable rs900000001 research brief.",
        }
        before = self.store.get_investigation(
            self.investigation["investigation_id"]
        )

        with (
            mock.patch.object(
                self.store,
                "_brief_version_diff",
                side_effect=RuntimeError("synthetic late brief failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "synthetic late brief failure"),
        ):
            self.store.commit_brief(self.investigation["investigation_id"], brief)

        after = self.store.get_investigation(self.investigation["investigation_id"])
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["evidence_snapshot_id"], before["evidence_snapshot_id"])
        self.assertEqual(after["evidence_snapshots"], before["evidence_snapshots"])
        self.assertEqual(after["brief_versions"], before["brief_versions"])

    def test_evidence_is_idempotent_and_envelope_is_unchanged(self) -> None:
        envelope = evidence_envelope.evidence_present(
            operation="variant.resolve",
            coverage={"consulted_sources": ["active_genome_index"]},
            observations={"observation_count": 1},
            answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
        )
        payload = {
            "status": "completed",
            "sample_context": {"count": 1, "matches": [{"rsid": "rs900000001"}]},
            "evidence_envelope": envelope,
        }
        first = self.store.commit_evidence(
            self.investigation["investigation_id"],
            source_family="personal_genome",
            operation="variant.resolve",
            evidence=payload,
            deduplication_key="variant.resolve:agi-snapshot-a:rs900000001",
        )
        replayed = self.store.commit_evidence(
            self.investigation["investigation_id"],
            source_family="personal_genome",
            operation="variant.resolve",
            evidence=payload,
            deduplication_key="variant.resolve:agi-snapshot-a:rs900000001",
        )
        self.assertEqual(first["evidence_record_id"], replayed["evidence_record_id"])
        self.assertEqual(first["evidence_envelope"], envelope)
        saved = self.store.get_investigation(self.investigation["investigation_id"])
        self.assertEqual(len(saved["evidence_records"]), 1)

    def test_hypothesis_gap_and_brief_require_pinned_traceability(self) -> None:
        evidence = self.store.commit_evidence(
            self.investigation["investigation_id"],
            source_family="personal_genome",
            operation="variant.resolve",
            evidence={
                "status": "completed",
                "evidence_envelope": evidence_envelope.evidence_present(
                    operation="variant.resolve",
                    observations={"observation_count": 1},
                    answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
                ),
            },
            deduplication_key="variant.resolve:agi-snapshot-a:rs900000001",
        )
        with self.assertRaisesRegex(ValueError, "disease-relation"):
            self.store.commit_hypothesis(
                self.investigation["investigation_id"],
                kind="candidate_mechanism",
                statement="Personal overlap alone must not become a candidate.",
                evidence_record_ids=[evidence["evidence_record_id"]],
                profile_revision_ids=[self.finding["observation_revision_id"]],
            )
        public_source = self._public_source_evidence()
        with self.assertRaisesRegex(ValueError, "disease-relation"):
            self.store.commit_hypothesis(
                self.investigation["investigation_id"],
                kind="candidate_mechanism",
                statement=(
                    "A generic public record remains only a candidate and still "
                    "lacks a typed relation."
                ),
                evidence_record_ids=[
                    evidence["evidence_record_id"],
                    public_source["evidence_record_id"],
                ],
                profile_revision_ids=[self.finding["observation_revision_id"]],
            )
        relation = self.store.commit_disease_relation(
            self.investigation["investigation_id"],
            self._relation_parameters(public_source["evidence_record_id"]),
        )
        replayed_relation = self.store.commit_disease_relation(
            self.investigation["investigation_id"],
            self._relation_parameters(public_source["evidence_record_id"]),
        )
        self.assertEqual(
            relation["evidence_record_id"], replayed_relation["evidence_record_id"]
        )
        self.assertEqual(relation["operation"], REGISTER_DISEASE_RELATION)
        self.assertEqual(
            relation["evidence"]["disease_relation"],
            self._relation_parameters(public_source["evidence_record_id"]),
        )
        hypothesis = self.store.commit_hypothesis(
            self.investigation["investigation_id"],
            kind="candidate_mechanism",
            statement=(
                "Model inference: The finding rs900000001 remains only a "
                "candidate hypothesis."
            ),
            evidence_record_ids=[
                evidence["evidence_record_id"],
                relation["evidence_record_id"],
            ],
            profile_revision_ids=[self.finding["observation_revision_id"]],
        )
        gap = self.store.commit_hypothesis(
            self.investigation["investigation_id"],
            kind="evidence_gap",
            statement=(
                "Evidence gap: Independent confirmation for rs900000001 remains "
                "an open requirement."
            ),
            evidence_record_ids=[],
            profile_revision_ids=[self.finding["observation_revision_id"]],
            status="open",
        )
        brief = self.store.commit_brief(
            self.investigation["investigation_id"],
            {
                "title": "Synthetic investigation brief",
                "summary": (
                    "Model inference: The finding rs900000001 remains only a "
                    "candidate hypothesis."
                ),
                "clinical_stage": "candidate_hypothesis",
                "modality_badges": [
                    "personal_genome",
                    "public_source",
                    "reported_record",
                ],
                "timeline": [],
                "claims": [
                    {
                        "statement": (
                            "Model inference: The finding rs900000001 remains only "
                            "a candidate hypothesis."
                        ),
                        "claim_role": "candidate_hypothesis",
                        "evidence_record_ids": [
                            evidence["evidence_record_id"],
                            relation["evidence_record_id"],
                        ],
                        "profile_revision_ids": [
                            self.finding["observation_revision_id"]
                        ],
                    },
                    {
                        "statement": (
                            "Evidence gap: Independent confirmation for "
                            "rs900000001 remains an open requirement."
                        ),
                        "claim_role": "limitation",
                        "evidence_record_ids": [],
                        "profile_revision_ids": [
                            self.finding["observation_revision_id"]
                        ],
                    },
                ],
                "hypothesis_ids": [hypothesis["hypothesis_id"]],
                "gap_ids": [gap["hypothesis_id"]],
                "confirmation_needs": ["Clinical laboratory confirmation"],
                "clinician_questions": [
                    {
                        "question": "What additional clinical evidence is needed for rs900000001?",
                        "evidence_record_ids": [relation["evidence_record_id"]],
                        "profile_revision_ids": [
                            self.finding["observation_revision_id"]
                        ],
                        "hypothesis_ids": [hypothesis["hypothesis_id"]],
                        "gap_ids": [gap["hypothesis_id"]],
                    }
                ],
                "clinical_boundary": "Research support only; this is not a diagnosis or treatment decision.",
                "change_summary": "Prepared a traceable rs900000001 research brief.",
            },
        )
        self.assertEqual(brief["version"], 1)
        with self.assertRaisesRegex(ValueError, "pinned snapshot"):
            self.store.commit_hypothesis(
                self.investigation["investigation_id"],
                kind="candidate_mechanism",
                statement="The finding remains an unpinned research candidate.",
                evidence_record_ids=[evidence["evidence_record_id"]],
                profile_revision_ids=["observation-revision-other"],
            )

    def test_confirmation_requirement_is_a_typed_brief_gap(self) -> None:
        confirmation = self.store.commit_hypothesis(
            self.investigation["investigation_id"],
            kind="confirmation_requirement",
            statement=(
                "Evidence gap: Independent confirmation for rs900000001 remains "
                "an open requirement."
            ),
            evidence_record_ids=[],
            profile_revision_ids=[self.finding["observation_revision_id"]],
            status="open",
        )

        brief_payload = {
            "title": "Synthetic confirmation brief",
            "summary": "Patient observation: The profile records rs900000001 as a research observation.",
            "clinical_stage": "research_observation",
            "modality_badges": ["reported_record"],
            "timeline": [],
            "claims": [
                {
                    "statement": "Patient observation: The profile records rs900000001 as a research observation.",
                    "claim_role": "observation",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [self.finding["observation_revision_id"]],
                },
                {
                    "statement": (
                        "Evidence gap: Independent confirmation for rs900000001 "
                        "remains an open requirement."
                    ),
                    "claim_role": "limitation",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [self.finding["observation_revision_id"]],
                },
            ],
            "hypothesis_ids": [],
            "gap_ids": [confirmation["hypothesis_id"]],
            "confirmation_needs": ["Independent clinical confirmation"],
            "clinician_questions": [],
            "clinical_boundary": (
                "Research support only; this is not a diagnosis or treatment decision."
            ),
            "change_summary": "Prepared a traceable rs900000001 research brief.",
        }
        with self.assertRaisesRegex(
            ValueError, "approved case anchors|exact saved anchors"
        ):
            self.store.commit_brief(
                self.investigation["investigation_id"],
                {
                    **brief_payload,
                    "modality_badges": ["patient_report", "reported_record"],
                    "claims": [
                        brief_payload["claims"][0],
                        {
                            **brief_payload["claims"][1],
                            "profile_revision_ids": [
                                self.condition["observation_revision_id"]
                            ],
                        },
                    ],
                },
            )

        brief = self.store.commit_brief(
            self.investigation["investigation_id"],
            brief_payload,
        )

        self.assertEqual(brief["brief"]["gap_ids"], [confirmation["hypothesis_id"]])

    def test_store_recomputes_exact_badges_from_claim_anchors(self) -> None:
        public_source = self._public_source_evidence(key="brief-badge-source")
        relation = self.store.commit_disease_relation(
            self.investigation["investigation_id"],
            self._relation_parameters(public_source["evidence_record_id"]),
        )
        hypothesis = self.store.commit_hypothesis(
            self.investigation["investigation_id"],
            kind="candidate_mechanism",
            statement=(
                "Model inference: The finding rs900000001 remains only a "
                "candidate hypothesis."
            ),
            evidence_record_ids=[relation["evidence_record_id"]],
            profile_revision_ids=[self.finding["observation_revision_id"]],
        )
        brief = {
            "title": "Synthetic badge-integrity brief",
            "summary": (
                "Model inference: The finding rs900000001 remains only a "
                "candidate hypothesis."
            ),
            "clinical_stage": "candidate_hypothesis",
            "modality_badges": ["public_source", "reported_record"],
            "timeline": [],
            "claims": [
                {
                    "statement": (
                        "Model inference: The finding rs900000001 remains only a "
                        "candidate hypothesis."
                    ),
                    "claim_role": "candidate_hypothesis",
                    "evidence_record_ids": [relation["evidence_record_id"]],
                    "profile_revision_ids": [self.finding["observation_revision_id"]],
                }
            ],
            "hypothesis_ids": [hypothesis["hypothesis_id"]],
            "gap_ids": [],
            "confirmation_needs": ["Independent clinical confirmation"],
            "clinician_questions": [],
            "clinical_boundary": (
                "Research support only; this is not a diagnosis or treatment decision."
            ),
            "change_summary": "Prepared a traceable rs900000001 research brief.",
        }

        with self.assertRaisesRegex(ValueError, "supported by the pinned profile"):
            self.store.commit_brief(
                self.investigation["investigation_id"],
                {
                    **brief,
                    "modality_badges": [
                        *brief["modality_badges"],
                        "computational_model_prediction",
                    ],
                },
            )

        committed = self.store.commit_brief(
            self.investigation["investigation_id"], brief
        )
        self.assertEqual(
            committed["brief"]["modality_badges"],
            ["public_source", "reported_record"],
        )
