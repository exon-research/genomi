from __future__ import annotations

import unittest

from genomi.evidence import envelope as evidence_envelope
from genomi.lab.disease_relation_contract import REGISTER_DISEASE_RELATION
from genomi.lab.evidence_normalization import normalize_fixture_response
from genomi.lab.evidence_types import SourceDocumentState
from genomi.lab.provider_policy import EvidenceRequest, SourceFamily
from tests.test_genomilab_disease_investigation import (
    _DiseaseInvestigationTestSupport,
)


class GenomiLabDiseaseRelationContractTests(
    _DiseaseInvestigationTestSupport, unittest.TestCase
):
    def test_disease_relation_contract_rejects_spoofed_or_misaligned_evidence(
        self,
    ) -> None:
        personal = self.store.commit_evidence(
            self.investigation["investigation_id"],
            source_family="personal_genome",
            operation="variant.resolve",
            evidence={
                "status": "completed",
                "evidence_envelope": evidence_envelope.evidence_present(
                    operation="variant.resolve",
                    answer_readiness=(evidence_envelope.NEEDS_CLINICAL_CONFIRMATION),
                ),
            },
            deduplication_key="personal-relation-source",
        )
        with self.assertRaisesRegex(ValueError, "non-personal, non-model"):
            self.store.commit_disease_relation(
                self.investigation["investigation_id"],
                self._relation_parameters(personal["evidence_record_id"]),
            )

        disguised_model = self.store.commit_evidence(
            self.investigation["investigation_id"],
            source_family="literature",
            operation="model.verify_claims",
            evidence={
                "status": "completed",
                "may_raise_answer_readiness": False,
                "model_verification": {"model": "synthetic"},
                "evidence_envelope": evidence_envelope.evidence_present(
                    operation="model.verify_claims",
                    observations={"independent_clinical_claim_ready": False},
                    answer_readiness=(evidence_envelope.NEEDS_CLINICAL_CONFIRMATION),
                ),
            },
            deduplication_key="disguised-model-relation-source",
        )
        with self.assertRaisesRegex(ValueError, "non-personal, non-model"):
            self.store.commit_disease_relation(
                self.investigation["investigation_id"],
                self._relation_parameters(disguised_model["evidence_record_id"]),
            )

        public_source = self._public_source_evidence(key="typed-relation-source")
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.store.commit_disease_relation(
                self.investigation["investigation_id"],
                self._relation_parameters(
                    public_source["evidence_record_id"],
                    disease_scope="Another disease",
                ),
            )
        malformed = self._relation_parameters(public_source["evidence_record_id"])
        malformed["direction"] = "causes"
        with self.assertRaisesRegex(ValueError, "declared disease-relation vocabulary"):
            self.store.commit_disease_relation(
                self.investigation["investigation_id"], malformed
            )
        malformed_context = self._relation_parameters(
            public_source["evidence_record_id"]
        )
        malformed_context["tissue_context"] = {
            "state": "not_reported",
            "description": "invented tissue",
            "source_locator": None,
        }
        with self.assertRaisesRegex(ValueError, "cannot carry source details"):
            self.store.commit_disease_relation(
                self.investigation["investigation_id"], malformed_context
            )
        with self.assertRaisesRegex(ValueError, "commit_disease_relation"):
            self.store.commit_evidence(
                self.investigation["investigation_id"],
                source_family="literature",
                operation=REGISTER_DISEASE_RELATION,
                evidence={
                    "status": "committed_relation",
                    "record_type": "disease_mechanism_relation",
                    "disease_relation": self._relation_parameters(
                        public_source["evidence_record_id"]
                    ),
                    "evidence_envelope": evidence_envelope.evidence_present(
                        operation=REGISTER_DISEASE_RELATION,
                        answer_readiness=(
                            evidence_envelope.NEEDS_CLINICAL_CONFIRMATION
                        ),
                    ),
                },
                deduplication_key="forged-disease-relation",
            )

        refuting = self.store.commit_disease_relation(
            self.investigation["investigation_id"],
            self._relation_parameters(
                public_source["evidence_record_id"], direction="refutes"
            ),
        )
        with self.assertRaisesRegex(ValueError, "supporting disease-relation"):
            self.store.commit_hypothesis(
                self.investigation["investigation_id"],
                kind="candidate_mechanism",
                statement=(
                    "The finding remains a candidate mechanism despite refuting evidence."
                ),
                evidence_record_ids=[refuting["evidence_record_id"]],
                profile_revision_ids=[self.finding["observation_revision_id"]],
            )

        supporting = self.store.commit_disease_relation(
            self.investigation["investigation_id"],
            self._relation_parameters(public_source["evidence_record_id"]),
        )
        with self.assertRaisesRegex(ValueError, "refutes or mixed"):
            self.store.commit_hypothesis(
                self.investigation["investigation_id"],
                kind="counterevidence",
                statement="Counterevidence: The source evidence weighs against the candidate.",
                evidence_record_ids=[supporting["evidence_record_id"]],
                profile_revision_ids=[self.finding["observation_revision_id"]],
            )
        counterevidence = self.store.commit_hypothesis(
            self.investigation["investigation_id"],
            kind="counterevidence",
            statement=(
                "Counterevidence: The source evidence weighs against the "
                "rs900000001 candidate."
            ),
            evidence_record_ids=[refuting["evidence_record_id"]],
            profile_revision_ids=[self.finding["observation_revision_id"]],
        )
        self.assertEqual(counterevidence["kind"], "counterevidence")

    def test_candidate_relation_requires_the_exact_cited_profile_anchor_set(
        self,
    ) -> None:
        public_source = self._public_source_evidence(key="anchor-source")
        relation = self.store.commit_disease_relation(
            self.investigation["investigation_id"],
            self._relation_parameters(
                public_source["evidence_record_id"],
                profile_revision_ids=[
                    self.condition["observation_revision_id"],
                    self.finding["observation_revision_id"],
                ],
            ),
        )
        with self.assertRaisesRegex(ValueError, "exact cited profile anchors"):
            self.store.commit_hypothesis(
                self.investigation["investigation_id"],
                kind="candidate_mechanism",
                statement=(
                    "A relation over a different patient slice must not qualify as a "
                    "candidate mechanism."
                ),
                evidence_record_ids=[relation["evidence_record_id"]],
                profile_revision_ids=[self.finding["observation_revision_id"]],
            )

        personal = self.store.commit_evidence(
            self.investigation["investigation_id"],
            source_family="personal_genome",
            operation="variant.resolve",
            evidence={
                "status": "completed",
                "evidence_envelope": evidence_envelope.evidence_present(
                    operation="variant.resolve",
                    answer_readiness=(evidence_envelope.NEEDS_CLINICAL_CONFIRMATION),
                ),
            },
            deduplication_key="brief-bypass-personal-source",
        )
        with self.assertRaisesRegex(ValueError, "disease-relation"):
            self.store.commit_brief(
                self.investigation["investigation_id"],
                {
                    "title": "Unsafe candidate brief",
                    "summary": "Personal overlap alone must not become a candidate.",
                    "clinical_stage": "candidate_hypothesis",
                    "modality_badges": ["personal_genome", "reported_record"],
                    "timeline": [],
                    "claims": [
                        {
                            "statement": "The overlap is a candidate mechanism.",
                            "claim_role": "candidate_hypothesis",
                            "evidence_record_ids": [personal["evidence_record_id"]],
                            "profile_revision_ids": [
                                self.finding["observation_revision_id"]
                            ],
                        }
                    ],
                    "hypothesis_ids": ["hypothesis-legacy-bypass"],
                    "gap_ids": [],
                    "confirmation_needs": ["Clinical confirmation"],
                    "clinician_questions": [],
                    "clinical_boundary": "Research support only; this is not a diagnosis or treatment decision.",
                    "change_summary": "Initial research draft.",
                },
            )

    def test_weak_source_document_cannot_independently_ground_a_candidate_relation(
        self,
    ) -> None:
        cases = (
            (SourceDocumentState.ABSTRACT_ONLY, SourceFamily.LITERATURE),
            (SourceDocumentState.PREPRINT, SourceFamily.LITERATURE),
            (SourceDocumentState.TRIAL_REGISTRATION, SourceFamily.TRIAL_REGISTRY),
        )
        for document_state, source_family in cases:
            with self.subTest(document_state=document_state.value):
                request = EvidenceRequest(
                    query="synthetic disease mechanism",
                    source_family=source_family,
                    purpose="Investigate a possible disease relation",
                    operation="search",
                )
                normalized = normalize_fixture_response(
                    request,
                    {
                        "status": "data_returned",
                        "source_family": source_family.value,
                        "records": [
                            {
                                "source_id": f"synthetic:{document_state.value}",
                                "title": "Synthetic weak source",
                                "source_document_state": document_state.value,
                            }
                        ],
                    },
                ).to_dict()
                weak = self.store.commit_evidence(
                    self.investigation["investigation_id"],
                    source_family=source_family.value,
                    operation="public_evidence.search",
                    evidence=normalized,
                    deduplication_key=f"weak-source:{document_state.value}",
                )

                with self.assertRaisesRegex(
                    ValueError, "usable, non-personal, non-model public source"
                ):
                    self.store.commit_disease_relation(
                        self.investigation["investigation_id"],
                        self._relation_parameters(weak["evidence_record_id"]),
                    )

    def test_brief_rejects_unavailable_evidence_and_invalid_register_refs(self) -> None:
        unavailable = self.store.commit_evidence(
            self.investigation["investigation_id"],
            source_family="literature",
            operation="public_evidence.search",
            evidence={
                "status": "source_unavailable",
                "evidence_envelope": evidence_envelope.not_assessed(
                    operation="evidence_provider.literature",
                    reason="source_unavailable",
                ),
            },
            deduplication_key="unavailable-literature",
        )
        base = {
            "title": "Unsafe synthetic draft",
            "summary": "This draft must not be committed.",
            "clinical_stage": "research_observation",
            "modality_badges": ["public_source"],
            "timeline": [],
            "claims": [
                {
                    "statement": "The source supports a possible research observation.",
                    "claim_role": "observation",
                    "evidence_record_ids": [unavailable["evidence_record_id"]],
                    "profile_revision_ids": [],
                }
            ],
            "hypothesis_ids": [],
            "gap_ids": [],
            "confirmation_needs": ["Obtain usable evidence"],
            "clinician_questions": [],
            "clinical_boundary": "Research support only; this is not a diagnosis or treatment decision.",
            "change_summary": "Initial research draft.",
        }
        with self.assertRaisesRegex(ValueError, "unavailable, incomplete, or empty"):
            self.store.commit_brief(self.investigation["investigation_id"], base)

        anchored = {
            **base,
            "modality_badges": ["reported_record"],
            "claims": [
                {
                    "statement": "The issued record reports the finding.",
                    "claim_role": "observation",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [self.finding["observation_revision_id"]],
                }
            ],
            "hypothesis_ids": ["hypothesis-does-not-exist"],
        }
        with self.assertRaisesRegex(ValueError, "must belong to the investigation"):
            self.store.commit_brief(self.investigation["investigation_id"], anchored)

    def test_counterevidence_claim_requires_usable_evidence_and_exact_register_anchors(
        self,
    ) -> None:
        profile_only = {
            "title": "Unsafe counterevidence draft",
            "summary": (
                "Counterevidence: The public source weighs against the "
                "rs900000001 candidate."
            ),
            "clinical_stage": "research_observation",
            "modality_badges": ["reported_record"],
            "timeline": [],
            "claims": [
                {
                    "statement": (
                        "Counterevidence: The public source weighs against the "
                        "rs900000001 candidate."
                    ),
                    "claim_role": "counterevidence",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [self.finding["observation_revision_id"]],
                }
            ],
            "hypothesis_ids": [],
            "gap_ids": [],
            "confirmation_needs": ["Review independent counterevidence"],
            "clinician_questions": [],
            "clinical_boundary": "Research support only; this is not a diagnosis or treatment decision.",
            "change_summary": "Prepared a traceable rs900000001 research brief.",
        }
        with self.assertRaisesRegex(ValueError, "counterevidence claim requires both"):
            self.store.commit_brief(
                self.investigation["investigation_id"], profile_only
            )

        public_source = self._public_source_evidence(key="counterevidence-source")
        counterevidence = self.store.commit_hypothesis(
            self.investigation["investigation_id"],
            kind="counterevidence",
            statement=(
                "Counterevidence: The public source weighs against the "
                "rs900000001 candidate."
            ),
            evidence_record_ids=[public_source["evidence_record_id"]],
            profile_revision_ids=[self.finding["observation_revision_id"]],
            status="candidate",
        )
        evidence_backed = {
            **profile_only,
            "modality_badges": ["public_source", "reported_record"],
            "claims": [
                {
                    **profile_only["claims"][0],
                    "evidence_record_ids": [public_source["evidence_record_id"]],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "referenced saved hypothesis"):
            self.store.commit_brief(
                self.investigation["investigation_id"], evidence_backed
            )

        committed = self.store.commit_brief(
            self.investigation["investigation_id"],
            {
                **evidence_backed,
                "hypothesis_ids": [counterevidence["hypothesis_id"]],
            },
        )
        self.assertEqual(committed["version"], 1)

    def test_evidence_requires_a_canonical_envelope(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical evidence_envelope"):
            self.store.commit_evidence(
                self.investigation["investigation_id"],
                source_family="literature",
                operation="public_evidence.search",
                evidence={"status": "completed"},
                deduplication_key="missing-envelope",
            )
        with self.assertRaisesRegex(ValueError, "unknown answer_readiness"):
            self.store.commit_evidence(
                self.investigation["investigation_id"],
                source_family="literature",
                operation="public_evidence.search",
                evidence={
                    "status": "completed",
                    "evidence_envelope": {
                        "finding_state": "evidence_present",
                        "answer_readiness": "invented",
                        "negative_inference": {"allowed": False},
                    },
                },
                deduplication_key="invalid-envelope",
            )

    def test_vus_profile_record_cannot_become_actionable_or_self_support_causality(
        self,
    ) -> None:
        vus = self.store.add_profile_observation(
            "user-a",
            {
                "modality": "reported_germline_finding",
                "label": "Report lists an uncertain variant",
                "reported_variant": "rs900000002",
                "reported_classification": "variant of uncertain significance",
                "source_identifier": "synthetic-report-002",
                "source_class": "issued_record",
                "verification_state": "record_confirmed",
            },
        )
        other_investigation = self.store.create_investigation(
            "user-a",
            question="What does this uncertain result mean?",
            disease_scope="Synthetic condition",
        )
        candidate = self.store.profile_snapshot_candidate(
            "user-a",
            investigation_id=other_investigation["investigation_id"],
            purpose="Review the uncertain report",
            observation_revision_ids=[vus["observation_revision_id"]],
        )
        self.store.create_profile_snapshot(
            "user-a",
            workspace_session_id="session-a",
            investigation_id=other_investigation["investigation_id"],
            purpose="Review the uncertain report",
            observation_revision_ids=[vus["observation_revision_id"]],
            candidate_sha256=candidate["candidate_sha256"],
            approved=True,
        )
        hypothesis = self.store.commit_hypothesis(
            other_investigation["investigation_id"],
            kind="uncertainty",
            statement=(
                "Evidence limitation: The evidence for rs900000002 remains "
                "uncertain."
            ),
            evidence_record_ids=[],
            profile_revision_ids=[vus["observation_revision_id"]],
            status="open",
        )
        unsafe = {
            "title": "Unsafe VUS brief",
            "summary": "The record contains an uncertain result.",
            "clinical_stage": "candidate_hypothesis",
            "modality_badges": ["reported_record"],
            "timeline": [],
            "claims": [
                {
                    "statement": "The uncertain variant establishes the cause and calls for care changes now.",
                    "claim_role": "candidate_hypothesis",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [vus["observation_revision_id"]],
                }
            ],
            "hypothesis_ids": [hypothesis["hypothesis_id"]],
            "gap_ids": [],
            "confirmation_needs": ["Independent evidence and clinical confirmation"],
            "clinician_questions": [],
            "clinical_boundary": "Research support only; this is not a diagnosis or treatment decision.",
            "change_summary": "Initial research draft.",
        }
        with self.assertRaisesRegex(ValueError, "diagnosis or treatment directive"):
            self.store.commit_brief(other_investigation["investigation_id"], unsafe)

        non_actionable = {
            **unsafe,
            "claims": [
                {
                    "statement": (
                        "Model inference: the uncertain variant remains only a "
                        "candidate hypothesis."
                    ),
                    "claim_role": "candidate_hypothesis",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [vus["observation_revision_id"]],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "requires both usable evidence"):
            self.store.commit_brief(
                other_investigation["investigation_id"], non_actionable
            )
