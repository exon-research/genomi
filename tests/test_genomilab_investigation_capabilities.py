from __future__ import annotations

import unittest
from typing import Any

from genomi.evidence import envelope as evidence_envelope
from genomi.interfaces.presentation import present_result
from genomi.lab.disease_relation_contract import (
    DISEASE_RELATION_RECORD_TYPE,
    REGISTER_DISEASE_RELATION,
    relation_kind_accepts_source_family,
)
from genomi.lab.agent_artifacts import (
    DEFAULT_BRIEF_TITLE,
    artifact_schema,
    brief_case_narrative_contract,
    decode_wire_artifact,
    validate_artifact,
)
from genomi.lab.artifact_types import AgentArtifactKind
from genomi.lab.investigation_capabilities import (
    GENOMI_VARIANT_FIND_GENE_VARIANTS,
    GENOMI_VARIANT_RESOLVE,
    PUBLIC_EVIDENCE_RETRIEVE,
    REGISTER_GAP,
    REGISTER_HYPOTHESIS,
    InvestigationCapabilityMixin,
)
from genomi.lab.service_errors import LabError


EXACT_ALLELE_PARAMETERS = {
    "chrom": "1",
    "pos": 100,
    "ref": "A",
    "alt": "G",
    "genome_build": "GRCh38",
    "include_fail": True,
    "limit": 7,
}


class _SnapshotStore:
    def __init__(
        self, genomic_scope: dict[str, object], observation_revision_id: str
    ) -> None:
        self.genomic_scope = genomic_scope
        self.observation_revision_id = observation_revision_id
        self.relation_commits: list[tuple[str, dict[str, object]]] = []

    def get_profile_snapshot(self, _: str) -> dict[str, object]:
        return {
            "patient_molecular_snapshot_id": "snapshot-a",
            "genomic_scope": self.genomic_scope,
            "observation_revision_ids": [self.observation_revision_id],
            "agi_id": "agi-a",
            "agi_snapshot_id": "agi-snapshot-a",
        }

    def commit_disease_relation(
        self,
        investigation_id: str,
        parameters: dict[str, object],
        **_authority: object,
    ) -> dict[str, object]:
        self.relation_commits.append((investigation_id, parameters))
        return {"evidence_record_id": "evidence-relation-a"}


class _CapabilityApplication(InvestigationCapabilityMixin):
    def __init__(
        self,
        genomic_scope: dict[str, object],
        *,
        evidence_records: list[dict[str, object]] | None = None,
        profile_modality: str = "reported_germline_finding",
        disease_scope: str = "Synthetic condition",
        observation_revision_id: str = "observation-revision-a",
        profile_fields: dict[str, object] | None = None,
    ) -> None:
        self.store = _SnapshotStore(genomic_scope, observation_revision_id)
        self.genomic_scope = genomic_scope
        self.invocations: list[dict[str, object]] = []
        self.evidence_records = evidence_records or []
        self.profile_modality = profile_modality
        self.disease_scope = disease_scope
        self.observation_revision_id = observation_revision_id
        self.profile_fields = profile_fields or {}
        self.provider_calls = 0

    def investigation(self, investigation_id: str) -> dict[str, object]:
        return {
            "investigation_id": investigation_id,
            "patient_molecular_snapshot_id": "snapshot-a",
            "disease_scope": self.disease_scope,
            "current_evidence_records": self.evidence_records,
            "current_plan_version": {"plan_version_id": "plan-a"},
            "specialist_board": {
                "members": [
                    {
                        "specialist_id": "specialist-phenotype",
                        "role": "Phenotype specialist",
                    },
                    {
                        "specialist_id": "specialist-skeptic",
                        "role": "Evidence skeptic",
                    },
                ]
            },
        }

    def _accepted_current_plan(self, investigation_id: str) -> dict[str, object]:
        return self.investigation(investigation_id)

    def investigation_profile(self, _: str) -> dict[str, object]:
        return {
            "patient_molecular_snapshot_id": "snapshot-a",
            "observations": [
                {
                    "observation_revision_id": self.observation_revision_id,
                    "modality": self.profile_modality,
                    **(
                        {
                            "reported_variant": self.genomic_scope["rsid"],
                            "normalization_state": "rsid_ready",
                        }
                        if isinstance(self.genomic_scope.get("rsid"), str)
                        else {}
                    ),
                    **self.profile_fields,
                }
            ],
        }

    def invoke_investigation_genome(
        self,
        investigation_id: str,
        *,
        operation: str,
        params: dict[str, Any],
        evidence_context: dict[str, Any] | None = None,
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> dict[str, object]:
        del expected_plan_version_id, expected_consent_receipt_id
        invocation = {
            "investigation_id": investigation_id,
            "operation": operation,
            "params": params,
        }
        if evidence_context is not None:
            invocation["evidence_context"] = evidence_context
        self.invocations.append(invocation)
        return {"status": "committed"}

    def evidence_capability_manifest(self) -> dict[str, object]:
        return {}

    def evidence_disclosure_candidate(
        self, investigation_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        self.provider_calls += 1
        raise AssertionError("a local disease relation must not call a provider")

    approve_evidence_disclosure = evidence_disclosure_candidate
    retrieve_public_evidence = evidence_disclosure_candidate


def _variant_plan(parameters: dict[str, object]) -> dict[str, object]:
    return {
        "steps": [
            {
                "id": "personal-genome",
                "capabilities": [GENOMI_VARIANT_RESOLVE],
                "proposed_agent_role": "genome_evidence_reviewer",
            }
        ],
        "capability_requests": [
            {
                "id": "request-personal-genome",
                "step_id": "personal-genome",
                "assigned_agent_role": "genome_evidence_reviewer",
                "capability": GENOMI_VARIANT_RESOLVE,
                "parameters": parameters,
            }
        ],
    }


def _single_capability_plan(
    capability: str, parameters: dict[str, object]
) -> dict[str, object]:
    return {
        "steps": [
            {
                "id": "review",
                "capabilities": [capability],
                "proposed_agent_role": "mechanism_synthesizer",
            }
        ],
        "capability_requests": [
            {
                "id": "request-review",
                "step_id": "review",
                "assigned_agent_role": "mechanism_synthesizer",
                "capability": capability,
                "parameters": parameters,
            }
        ],
    }


def _case_term(entry: dict[str, object]) -> str:
    contract = entry["request_contract"]
    assert isinstance(contract, dict)
    fields = contract["fields"]
    assert isinstance(fields, dict)
    statement = fields["statement"]
    assert isinstance(statement, dict)
    anchors = statement["anchors"]
    assert isinstance(anchors, list)
    return str(anchors[0]["text"])


class GenomiLabInvestigationCapabilityTests(unittest.TestCase):
    def test_working_hypothesis_is_available_from_profile_context_before_evidence(
        self,
    ) -> None:
        anchor = "Recurrent sinus and chest infections"
        application = _CapabilityApplication(
            {"operation": "variant.find_gene_variants", "genome_build": "GRCh38"},
            evidence_records=[],
            profile_modality="phenotype",
            profile_fields={
                "label": anchor,
                "verification_state": "user_confirmed",
            },
        )
        entry = application.investigation_capability_catalog("investigation-a")[
            REGISTER_HYPOTHESIS
        ]
        self.assertTrue(entry["available"])
        self.assertIn(
            "working_hypothesis",
            entry["request_contract"]["allowed_kind_values"],
        )
        request = next(
            item
            for item in entry["anchored_request_cases"]
            if item["kind"] == "working_hypothesis"
        )
        request = {
            **request,
            "statement": (
                "Working hypothesis: medication-related immune suppression. "
                f"Model inference: The reported record {anchor} may support "
                "this possible candidate hypothesis."
            ),
        }
        application.validate_agent_capability_plan(
            "investigation-a",
            _single_capability_plan(REGISTER_HYPOTHESIS, request),
        )

        with self.assertRaisesRegex(ValueError, "approved context"):
            application.validate_agent_capability_plan(
                "investigation-a",
                _single_capability_plan(
                    REGISTER_HYPOTHESIS,
                    {**request, "evidence_record_ids": ["evidence-not-approved"]},
                ),
            )

    def test_public_evidence_dispatch_rejects_a_superseded_plan_before_egress(
        self,
    ) -> None:
        application = _CapabilityApplication(
            {"operation": "variant.resolve", "rsid": "rs900000001"}
        )

        with self.assertRaises(LabError) as raised:
            application._execute_capability_request(
                "investigation-a",
                {
                    "capability": PUBLIC_EVIDENCE_RETRIEVE,
                    "parameters": {},
                },
                approval=None,
                expected_plan_version_id="plan-superseded",
                expected_consent_receipt_id="consent-a",
            )

        self.assertEqual(raised.exception.code, "capability_plan_superseded")
        self.assertEqual(application.provider_calls, 0)

    def test_disease_relation_is_a_typed_local_capability(self) -> None:
        source_record = {
            "evidence_record_id": "evidence-public-a",
            "source_family": "literature",
            "operation": "public_evidence.search",
            "evidence_envelope": evidence_envelope.evidence_present(
                operation="evidence_provider.literature",
                answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
            ),
        }
        application = _CapabilityApplication(
            {"operation": "variant.resolve", "rsid": "rs900000001"},
            evidence_records=[source_record],
        )
        catalog = application.investigation_capability_catalog("investigation-a")
        relation_contract = catalog[REGISTER_DISEASE_RELATION]
        self.assertTrue(relation_contract["available"])
        self.assertEqual(
            relation_contract["privacy"], "local_domain_only_no_provider_egress"
        )
        self.assertEqual(
            relation_contract["parameters"]["eligible_source_evidence_record_ids"],
            ["evidence-public-a"],
        )
        self.assertEqual(
            relation_contract["parameters"]["eligible_profile_revision_ids"],
            ["observation-revision-a"],
        )
        templates = relation_contract["exact_request_templates"]
        self.assertEqual(len(templates), 4)
        self.assertEqual(
            {template["direction"] for template in templates},
            {"supports", "refutes", "mixed", "context_only"},
        )
        parameters = dict(templates[0])
        self.assertEqual(parameters["direction"], "supports")
        self.assertEqual(parameters["profile_revision_ids"], ["observation-revision-a"])
        plan = {
            "steps": [
                {
                    "id": "bind-relation",
                    "capabilities": [REGISTER_DISEASE_RELATION],
                    "proposed_agent_role": "mechanism_synthesizer",
                }
            ],
            "capability_requests": [
                {
                    "id": "request-bind-relation",
                    "step_id": "bind-relation",
                    "assigned_agent_role": "mechanism_synthesizer",
                    "capability": REGISTER_DISEASE_RELATION,
                    "parameters": parameters,
                }
            ],
        }
        application.validate_agent_capability_plan("investigation-a", plan)
        result = application._execute_capability_request(
            "investigation-a",
            plan["capability_requests"][0],
            approval=None,
        )
        self.assertEqual(result["status"], "registered")
        self.assertEqual(
            application.store.relation_commits,
            [("investigation-a", parameters)],
        )
        self.assertEqual(application.provider_calls, 0)

        widened = dict(parameters)
        widened["profile_revision_ids"] = ["observation-revision-other"]
        plan["capability_requests"][0]["parameters"] = widened
        with self.assertRaisesRegex(ValueError, "exact catalog template"):
            application.validate_agent_capability_plan("investigation-a", plan)

        renamed = dict(parameters)
        renamed["context"] = renamed.pop("population_context")
        plan["capability_requests"][0]["parameters"] = renamed
        with self.assertRaisesRegex(ValueError, "typed contract"):
            application.validate_agent_capability_plan("investigation-a", plan)

    def test_candidate_case_carries_exact_anchors_and_host_supplied_narrative(
        self,
    ) -> None:
        public_record = {
            "evidence_record_id": "evidence-public-a",
            "source_family": "literature",
            "operation": "public_evidence.search",
            "evidence_envelope": evidence_envelope.evidence_present(
                operation="evidence_provider.literature",
                answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
            ),
        }
        seed = _CapabilityApplication(
            {"operation": "variant.resolve", "rsid": "rs900000001"},
            evidence_records=[public_record],
        )
        relation_parameters = seed.investigation_capability_catalog("investigation-a")[
            REGISTER_DISEASE_RELATION
        ]["exact_request_templates"][0]
        relation_record = {
            "evidence_record_id": "evidence-relation-a",
            "source_family": "literature",
            "operation": REGISTER_DISEASE_RELATION,
            "evidence": {
                "record_type": DISEASE_RELATION_RECORD_TYPE,
                "disease_relation": relation_parameters,
            },
            "evidence_envelope": evidence_envelope.evidence_present(
                operation=REGISTER_DISEASE_RELATION,
                answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
            ),
        }
        personal_record = {
            "evidence_record_id": "evidence-personal-a",
            "source_family": "personal_genome",
            "operation": "variant.resolve",
            "evidence_envelope": evidence_envelope.evidence_present(
                operation="variant.resolve",
                answer_readiness=evidence_envelope.SCOPED_ANSWER_ONLY,
            ),
        }
        application = _CapabilityApplication(
            {"operation": "variant.resolve", "rsid": "rs900000001"},
            evidence_records=[personal_record, public_record, relation_record],
        )
        entry = application.investigation_capability_catalog("investigation-a")[
            REGISTER_HYPOTHESIS
        ]
        template = entry["anchored_request_cases"][0]
        self.assertEqual(
            template["evidence_record_ids"],
            ["evidence-personal-a", "evidence-relation-a"],
        )
        self.assertIn(
            "statement", entry["request_contract"]["required_fields"]
        )
        case_term = _case_term(entry)
        statement = (
            f"Model inference: The finding may contribute to {case_term}, but this "
            "remains only a candidate hypothesis; causality, mechanism, and clinical "
            "significance are unestablished."
        )
        plan = {
            "steps": [
                {
                    "id": "candidate",
                    "capabilities": [REGISTER_HYPOTHESIS],
                    "proposed_agent_role": "mechanism_synthesizer",
                }
            ],
            "capability_requests": [
                {
                    "id": "request-candidate",
                    "step_id": "candidate",
                    "assigned_agent_role": "mechanism_synthesizer",
                    "capability": REGISTER_HYPOTHESIS,
                    "parameters": {**template, "statement": statement},
                }
            ],
        }
        application.validate_agent_capability_plan("investigation-a", plan)
        plan["capability_requests"][0]["parameters"] = {
            **template,
            "statement": (
                f"Model inference: The finding {case_term} might relate to the "
                "reported condition, but this remains a candidate hypothesis."
            ),
        }
        application.validate_agent_capability_plan("investigation-a", plan)
        plan["capability_requests"][0]["parameters"] = {
            **template,
            "statement": "Model inference: The finding remains a candidate hypothesis.",
        }
        with self.assertRaisesRegex(ValueError, "exact approved case anchor"):
            application.validate_agent_capability_plan("investigation-a", plan)

    def test_presented_contracts_accept_distinct_case_synthesis(self) -> None:
        narratives: list[tuple[str, str]] = []
        applications: list[_CapabilityApplication] = []
        cases = (
            (
                "Synthetic motor condition",
                "rs900000101",
                "MOTOR1",
                "motor",
            ),
            (
                "Synthetic retinal condition",
                "rs900000202",
                "RETINA2",
                "retinal",
            ),
        )
        for disease_scope, reported_variant, gene, suffix in cases:
            profile_revision_id = f"observation-{suffix}"
            public_record = {
                "evidence_record_id": f"evidence-public-{suffix}",
                "source_family": "literature",
                "operation": "public_evidence.search",
                "rsid": reported_variant,
                "title": f"Untrusted source prose for {suffix}",
                "evidence_envelope": evidence_envelope.evidence_present(
                    operation="evidence_provider.literature",
                    answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
                ),
            }
            application_arguments = {
                "disease_scope": disease_scope,
                "observation_revision_id": profile_revision_id,
                "profile_fields": {
                    "reported_variant": reported_variant,
                    "gene": gene,
                    "source_class": "issued_record",
                },
            }
            seed = _CapabilityApplication(
                {"operation": "variant.resolve", "rsid": reported_variant},
                evidence_records=[public_record],
                **application_arguments,
            )
            relation_parameters = seed.investigation_capability_catalog(
                "investigation-a"
            )[REGISTER_DISEASE_RELATION]["exact_request_templates"][0]
            relation_record = {
                "evidence_record_id": f"evidence-relation-{suffix}",
                "source_family": "literature",
                "operation": REGISTER_DISEASE_RELATION,
                "evidence": {
                    "record_type": DISEASE_RELATION_RECORD_TYPE,
                    "disease_relation": relation_parameters,
                },
                "evidence_envelope": evidence_envelope.evidence_present(
                    operation=REGISTER_DISEASE_RELATION,
                    answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
                ),
            }
            application = _CapabilityApplication(
                {"operation": "variant.resolve", "rsid": reported_variant},
                evidence_records=[public_record, relation_record],
                **application_arguments,
            )
            applications.append(application)
            catalog = application.investigation_capability_catalog(
                "investigation-a"
            )
            profile = application.investigation_profile("investigation-a")
            approved_context = {
                "disease_scope": disease_scope,
                "molecular_profile": profile,
                "evidence_records": [public_record, relation_record],
                "hypotheses": [
                    {
                        "hypothesis_id": f"hypothesis-{suffix}",
                        "kind": "candidate_mechanism",
                    }
                ],
            }
            published = present_result(
                "genomilab.inspect_investigation",
                {
                    "status": "ready",
                    "investigation": {
                        "investigation_id": "investigation-a",
                        "private_context_status": "approved_for_session",
                        "state_visibility": (
                            "authorized_for_current_agent_session"
                        ),
                    },
                    "capability_catalog": catalog,
                    "brief_authoring": {
                        "brief_title_fallback": DEFAULT_BRIEF_TITLE,
                        "brief_schema": artifact_schema(
                            AgentArtifactKind.BRIEF_DRAFT,
                            approved_context,
                        ),
                        "case_narrative_contract": (
                            brief_case_narrative_contract(approved_context)
                        ),
                    },
                },
            )
            hypothesis_entry = published["capability_catalog"][
                REGISTER_HYPOTHESIS
            ]
            statement_contract = hypothesis_entry["request_contract"][
                "fields"
            ]["statement"]
            composite_anchor = next(
                str(anchor["text"])
                for anchor in statement_contract["anchors"]
                if anchor.get("profile_revision_id") == profile_revision_id
                and anchor.get("text") == reported_variant
            )
            evidence_anchor = next(
                anchor
                for anchor in statement_contract["anchors"]
                if anchor.get("evidence_record_id")
                == f"evidence-public-{suffix}"
                and anchor.get("text") == reported_variant
            )
            self.assertEqual(evidence_anchor["source_family"], "literature")
            self.assertNotIn(
                f"Untrusted source prose for {suffix}",
                {anchor["text"] for anchor in statement_contract["anchors"]},
            )
            statement = (
                f"Model inference: The finding {composite_anchor} may contribute "
                "to the reported condition, but this remains only a candidate "
                "hypothesis; causality and clinical significance are unestablished."
            )
            request = {
                **hypothesis_entry["anchored_request_cases"][0],
                "statement": statement,
            }
            application.validate_agent_capability_plan(
                "investigation-a",
                _single_capability_plan(REGISTER_HYPOTHESIS, request),
            )

            schema = published["brief_authoring"]["brief_schema"]
            wire_brief = {
                "title": published["brief_authoring"]["brief_title_fallback"],
                "summary": statement,
                "clinical_stage": schema["properties"]["clinical_stage"][
                    "enum"
                ][0],
                "timeline": [],
                "claims": [
                    {
                        "statement": statement,
                        "claim_role": "candidate_hypothesis",
                        "evidence_record_ids": request["evidence_record_ids"],
                        "profile_revision_ids": request["profile_revision_ids"],
                    }
                ],
                "hypothesis_ids": [f"hypothesis-{suffix}"],
                "gap_ids": [],
                "confirmation_needs": [],
                "clinician_questions": [],
                "clinical_boundary": schema["properties"]["clinical_boundary"][
                    "enum"
                ][0],
                "change_summary": (
                    f"Prepared a traceable {composite_anchor} research brief."
                ),
            }
            decoded = decode_wire_artifact(
                AgentArtifactKind.BRIEF_DRAFT,
                wire_brief,
                approved_context=approved_context,
            )
            validate_artifact(
                AgentArtifactKind.BRIEF_DRAFT,
                decoded,
                approved_context,
            )
            narratives.append((statement, wire_brief["change_summary"]))

        self.assertNotEqual(narratives[0], narratives[1])
        self.assertIn("rs900000101", " ".join(narratives[0]))
        self.assertIn("rs900000202", " ".join(narratives[1]))
        first_entry = applications[0].investigation_capability_catalog(
            "investigation-a"
        )[REGISTER_HYPOTHESIS]
        cross_case_request = {
            **first_entry["anchored_request_cases"][0],
            "statement": narratives[1][0],
        }
        with self.assertRaisesRegex(
            ValueError, "approved case anchor|outside its approved case anchors"
        ):
            applications[0].validate_agent_capability_plan(
                "investigation-a",
                _single_capability_plan(REGISTER_HYPOTHESIS, cross_case_request),
            )

    def test_non_template_hypotheses_gaps_statuses_and_supersession_are_reachable(
        self,
    ) -> None:
        public_record = {
            "evidence_record_id": "evidence-public-a",
            "source_family": "literature",
            "operation": "public_evidence.search",
            "evidence_envelope": evidence_envelope.evidence_present(
                operation="evidence_provider.literature",
                answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
            ),
        }
        seed = _CapabilityApplication(
            {"operation": "variant.resolve", "rsid": "rs900000001"},
            evidence_records=[public_record],
        )
        relation_parameters = seed.investigation_capability_catalog("investigation-a")[
            REGISTER_DISEASE_RELATION
        ]["exact_request_templates"][0]
        relation_record = {
            "evidence_record_id": "evidence-relation-a",
            "source_family": "literature",
            "operation": REGISTER_DISEASE_RELATION,
            "evidence": {
                "record_type": DISEASE_RELATION_RECORD_TYPE,
                "disease_relation": relation_parameters,
            },
            "evidence_envelope": evidence_envelope.evidence_present(
                operation=REGISTER_DISEASE_RELATION,
                answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
            ),
        }
        application = _CapabilityApplication(
            {"operation": "variant.resolve", "rsid": "rs900000001"},
            evidence_records=[public_record, relation_record],
        )
        catalog = application.investigation_capability_catalog("investigation-a")
        hypothesis_entry = catalog[REGISTER_HYPOTHESIS]
        gap_entry = catalog[REGISTER_GAP]
        candidate_template = hypothesis_entry["anchored_request_cases"][0]
        confirmation_template = gap_entry["anchored_request_cases"][0]
        case_term = _case_term(hypothesis_entry)

        reachable_requests = [
            (
                REGISTER_HYPOTHESIS,
                {
                    "kind": "counterevidence",
                    "statement": (
                        "Counterevidence: The source evidence weighs against the "
                        f"{case_term} candidate."
                    ),
                    "evidence_record_ids": ["evidence-public-a"],
                    "profile_revision_ids": ["observation-revision-a"],
                    "status": "weakened",
                    "supersedes_hypothesis_id": "hypothesis-prior-counter",
                },
            ),
            (
                REGISTER_HYPOTHESIS,
                {
                    "kind": "uncertainty",
                    "statement": (
                        f"Evidence limitation: The evidence for {case_term} remains "
                        "uncertain."
                    ),
                    "evidence_record_ids": ["evidence-public-a"],
                    "profile_revision_ids": ["observation-revision-a"],
                    "status": "supported",
                    "supersedes_hypothesis_id": "hypothesis-prior-uncertainty",
                },
            ),
            (
                REGISTER_GAP,
                {
                    "kind": "evidence_gap",
                    "statement": (
                        f"Evidence gap: Independent evidence for {case_term} remains "
                        "unavailable."
                    ),
                    "evidence_record_ids": [],
                    "profile_revision_ids": ["observation-revision-a"],
                    "status": "resolved",
                    "supersedes_hypothesis_id": "hypothesis-prior-gap",
                },
            ),
            (
                REGISTER_HYPOTHESIS,
                {
                    **candidate_template,
                    "statement": (
                        f"Model inference: The finding may contribute to {case_term}, "
                        "but this remains only a candidate hypothesis."
                    ),
                    "status": "supported",
                },
            ),
            (
                REGISTER_HYPOTHESIS,
                {
                    **candidate_template,
                    "statement": (
                        f"Model inference: The finding may contribute to {case_term}, "
                        "but this remains only a candidate hypothesis."
                    ),
                    "supersedes_hypothesis_id": "hypothesis-prior-candidate",
                },
            ),
            (
                REGISTER_GAP,
                {
                    **confirmation_template,
                    "statement": (
                        f"Evidence gap: Independent confirmation for {case_term} "
                        "remains an open requirement."
                    ),
                    "status": "resolved",
                },
            ),
            (
                REGISTER_GAP,
                {
                    **confirmation_template,
                    "statement": (
                        f"Evidence gap: Independent confirmation for {case_term} "
                        "remains an open requirement."
                    ),
                    "supersedes_hypothesis_id": "hypothesis-prior-confirmation",
                },
            ),
        ]
        for capability, parameters in reachable_requests:
            with self.subTest(capability=capability, kind=parameters["kind"]):
                application.validate_agent_capability_plan(
                    "investigation-a",
                    _single_capability_plan(capability, parameters),
                )

    def test_relation_templates_filter_incompatible_uniprot_variant_pair(self) -> None:
        uniprot_record = {
            "evidence_record_id": "evidence-uniprot-a",
            "source_family": "uniprot",
            "operation": "public_evidence.lookup",
            "evidence_envelope": evidence_envelope.evidence_present(
                operation="evidence_provider.uniprot",
                answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
            ),
        }
        reported_variant = _CapabilityApplication(
            {"operation": "variant.resolve", "rsid": "rs900000001"},
            evidence_records=[uniprot_record],
        )
        incompatible = reported_variant.investigation_capability_catalog(
            "investigation-a"
        )[REGISTER_DISEASE_RELATION]
        self.assertFalse(incompatible["available"])
        self.assertEqual(incompatible["exact_request_templates"], [])

        biomarker = _CapabilityApplication(
            {"operation": "variant.resolve", "rsid": "rs900000001"},
            evidence_records=[uniprot_record],
            profile_modality="biomarker",
        )
        compatible = biomarker.investigation_capability_catalog("investigation-a")[
            REGISTER_DISEASE_RELATION
        ]
        self.assertTrue(compatible["available"])
        self.assertEqual(
            {item["relation_kind"] for item in compatible["exact_request_templates"]},
            {"molecular_feature_disease"},
        )
        for parameters in compatible["exact_request_templates"]:
            self.assertTrue(
                relation_kind_accepts_source_family(
                    parameters["relation_kind"],
                    "uniprot",
                    direction=parameters["direction"],
                )
            )
            biomarker.validate_agent_capability_plan(
                "investigation-a",
                _single_capability_plan(REGISTER_DISEASE_RELATION, parameters),
            )

    def test_exact_allele_scope_is_catalogued_executed_and_not_widened(self) -> None:
        scope = {"operation": "variant.resolve", **EXACT_ALLELE_PARAMETERS}
        application = _CapabilityApplication(scope)

        catalog = application.investigation_capability_catalog("investigation-a")
        self.assertEqual(
            catalog[GENOMI_VARIANT_RESOLVE]["parameters"],
            EXACT_ALLELE_PARAMETERS,
        )

        plan = _variant_plan(dict(EXACT_ALLELE_PARAMETERS))
        application.validate_agent_capability_plan("investigation-a", plan)
        result = application._execute_capability_request(
            "investigation-a",
            plan["capability_requests"][0],
            approval=None,
        )
        self.assertEqual(result["status"], "committed")
        self.assertEqual(
            application.invocations,
            [
                {
                    "investigation_id": "investigation-a",
                    "operation": "variant.resolve",
                    "params": EXACT_ALLELE_PARAMETERS,
                }
            ],
        )

        widened = dict(EXACT_ALLELE_PARAMETERS)
        widened["limit"] = 8
        with self.assertRaisesRegex(ValueError, "exceeds the approved genomic scope"):
            application.validate_agent_capability_plan(
                "investigation-a", _variant_plan(widened)
            )

        missing_filter = dict(EXACT_ALLELE_PARAMETERS)
        missing_filter.pop("include_fail")
        with self.assertRaisesRegex(ValueError, "exceeds the approved genomic scope"):
            application.validate_agent_capability_plan(
                "investigation-a", _variant_plan(missing_filter)
            )

        type_confused = dict(EXACT_ALLELE_PARAMETERS)
        type_confused["pos"] = True
        with self.assertRaisesRegex(ValueError, "exceeds the approved genomic scope"):
            application.validate_agent_capability_plan(
                "investigation-a", _variant_plan(type_confused)
            )

    def test_candidate_gene_set_is_lineage_bound_fingerprinted_and_main_only(
        self,
    ) -> None:
        scope = {
            "operation": "variant.find_gene_variants",
            "genome_build": "GRCh38",
            "gene_count_limit": 10,
            "passing_filters_only": True,
            "per_gene_limit": 100,
            "match_basis": "gencode_gene_interval_overlap",
        }
        application = _CapabilityApplication(
            scope,
            profile_modality="phenotype",
            profile_fields={"label": "Synthetic immune phenotype"},
        )
        catalog = application.investigation_capability_catalog("investigation-a")
        entry = catalog[GENOMI_VARIANT_FIND_GENE_VARIANTS]
        self.assertTrue(entry["available"])
        self.assertEqual(
            entry["execution_boundary"],
            {
                "execution_owner": "main_investigator",
                "specialist_active_genome_index_access": False,
            },
        )
        parameters = {
            "genes": ["CTLA4", "LRBA"],
            "agi_id": "agi-a",
            "agi_snapshot_id": "agi-snapshot-a",
            "genome_build": "GRCh38",
            "per_gene_limit": 100,
            "candidate_set_lineage": {
                "specialist_id": "specialist-phenotype",
                "profile_revision_ids": ["observation-revision-a"],
                "evidence_record_ids": [],
            },
        }
        plan = _single_capability_plan(
            GENOMI_VARIANT_FIND_GENE_VARIANTS, parameters
        )
        application.validate_agent_capability_plan("investigation-a", plan)
        result = application._execute_capability_request(
            "investigation-a",
            plan["capability_requests"][0],
            approval=None,
        )

        self.assertEqual(result["status"], "committed")
        invocation = application.invocations[-1]
        self.assertEqual(invocation["operation"], "variant.find_gene_variants")
        self.assertEqual(
            invocation["params"],
            {
                "genes": ["CTLA4", "LRBA"],
                "agi_id": "agi-a",
                "genome_build": "GRCh38",
                "per_gene_limit": 100,
            },
        )
        evidence_context = invocation["evidence_context"]
        self.assertEqual(evidence_context["candidate_genes"], ["CTLA4", "LRBA"])
        self.assertEqual(len(evidence_context["candidate_set_sha256"]), 64)
        self.assertEqual(
            evidence_context["candidate_set_lineage"],
            parameters["candidate_set_lineage"],
        )
        self.assertEqual(evidence_context["agi_id"], "agi-a")
        self.assertEqual(evidence_context["agi_snapshot_id"], "agi-snapshot-a")
        self.assertTrue(evidence_context["passing_filters_only"])
        self.assertFalse(evidence_context["specialist_active_genome_index_access"])

        invalid_cases = (
            {**parameters, "genes": [f"GENE{index}" for index in range(11)]},
            {**parameters, "agi_snapshot_id": "agi-snapshot-other"},
            {
                **parameters,
                "candidate_set_lineage": {
                    **parameters["candidate_set_lineage"],
                    "specialist_id": "specialist-not-on-board",
                },
            },
            {
                **parameters,
                "candidate_set_lineage": {
                    **parameters["candidate_set_lineage"],
                    "profile_revision_ids": ["observation-other"],
                },
            },
        )
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                application.validate_agent_capability_plan(
                    "investigation-a",
                    _single_capability_plan(
                        GENOMI_VARIANT_FIND_GENE_VARIANTS, invalid
                    ),
                )

    def test_rsid_scope_preserves_all_normalized_request_fields(self) -> None:
        parameters = {
            "rsid": "rs900000001",
            "genome_build": "GRCh38",
            "include_fail": False,
            "limit": 3,
        }
        application = _CapabilityApplication(
            {"operation": "variant.resolve", **parameters}
        )
        catalog = application.investigation_capability_catalog("investigation-a")
        self.assertEqual(catalog[GENOMI_VARIANT_RESOLVE]["parameters"], parameters)

if __name__ == "__main__":
    unittest.main()
