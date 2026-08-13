from __future__ import annotations

import unittest
from typing import Any

from genomi.evidence import envelope as evidence_envelope
from genomi.lab.disease_relation_contract import (
    DISEASE_RELATION_RECORD_TYPE,
    REGISTER_DISEASE_RELATION,
    relation_kind_accepts_source_family,
)
from genomi.lab.harness import (
    HarnessCommand,
    HarnessOperation,
    SimulatedHarnessAdapter,
    StartTaskRunPayload,
)
from genomi.lab.investigation_capabilities import (
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
    def __init__(self, genomic_scope: dict[str, object]) -> None:
        self.genomic_scope = genomic_scope
        self.relation_commits: list[tuple[str, dict[str, object]]] = []

    def get_profile_snapshot(self, _: str) -> dict[str, object]:
        return {
            "genomic_scope": self.genomic_scope,
            "observation_revision_ids": ["observation-revision-a"],
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
    ) -> None:
        self.store = _SnapshotStore(genomic_scope)
        self.invocations: list[dict[str, object]] = []
        self.evidence_records = evidence_records or []
        self.profile_modality = profile_modality
        self.provider_calls = 0

    def investigation(self, investigation_id: str) -> dict[str, object]:
        return {
            "investigation_id": investigation_id,
            "patient_molecular_snapshot_id": "snapshot-a",
            "disease_scope": "Synthetic condition",
            "current_evidence_records": self.evidence_records,
            "current_plan_version": {"plan_version_id": "plan-a"},
        }

    def _accepted_current_plan(self, investigation_id: str) -> dict[str, object]:
        return self.investigation(investigation_id)

    def investigation_profile(self, _: str) -> dict[str, object]:
        return {
            "patient_molecular_snapshot_id": "snapshot-a",
            "observations": [
                {
                    "observation_revision_id": "observation-revision-a",
                    "modality": self.profile_modality,
                }
            ],
        }

    def invoke_investigation_genome(
        self,
        investigation_id: str,
        *,
        operation: str,
        params: dict[str, Any],
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> dict[str, object]:
        del expected_plan_version_id, expected_consent_receipt_id
        self.invocations.append(
            {
                "investigation_id": investigation_id,
                "operation": operation,
                "params": params,
            }
        )
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


class GenomiLabInvestigationCapabilityTests(unittest.TestCase):
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
        application.validate_harness_capability_plan("investigation-a", plan)
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
            application.validate_harness_capability_plan("investigation-a", plan)

        renamed = dict(parameters)
        renamed["context"] = renamed.pop("population_context")
        plan["capability_requests"][0]["parameters"] = renamed
        with self.assertRaisesRegex(ValueError, "typed contract"):
            application.validate_harness_capability_plan("investigation-a", plan)

    def test_candidate_template_carries_patient_genome_and_exact_safe_narrative(
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
        template = application.investigation_capability_catalog("investigation-a")[
            REGISTER_HYPOTHESIS
        ]["exact_request_templates"][0]
        self.assertEqual(
            template["evidence_record_ids"],
            ["evidence-personal-a", "evidence-relation-a"],
        )
        self.assertEqual(
            template["statement"],
            "Model inference: The finding may contribute to the reported condition, "
            "but this remains only a candidate hypothesis; causality, mechanism, "
            "and clinical significance are unestablished.",
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
                    "parameters": template,
                }
            ],
        }
        application.validate_harness_capability_plan("investigation-a", plan)
        plan["capability_requests"][0]["parameters"] = {
            **template,
            "statement": "Model inference: altered prose.",
        }
        with self.assertRaisesRegex(ValueError, "exact catalog template"):
            application.validate_harness_capability_plan("investigation-a", plan)

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
        candidate_template = catalog[REGISTER_HYPOTHESIS]["exact_request_templates"][0]
        confirmation_template = catalog[REGISTER_GAP]["exact_request_templates"][0]

        reachable_requests = [
            (
                REGISTER_HYPOTHESIS,
                {
                    "kind": "counterevidence",
                    "statement": "Counterevidence: The source evidence weighs against the candidate.",
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
                    "statement": "Evidence limitation: The available evidence remains uncertain.",
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
                    "statement": "Evidence gap: Independent evidence remains unavailable.",
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
                    "status": "supported",
                },
            ),
            (
                REGISTER_HYPOTHESIS,
                {
                    **candidate_template,
                    "supersedes_hypothesis_id": "hypothesis-prior-candidate",
                },
            ),
            (
                REGISTER_GAP,
                {
                    **confirmation_template,
                    "status": "resolved",
                },
            ),
            (
                REGISTER_GAP,
                {
                    **confirmation_template,
                    "supersedes_hypothesis_id": "hypothesis-prior-confirmation",
                },
            ),
        ]
        for capability, parameters in reachable_requests:
            with self.subTest(capability=capability, kind=parameters["kind"]):
                application.validate_harness_capability_plan(
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
            biomarker.validate_harness_capability_plan(
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
        application.validate_harness_capability_plan("investigation-a", plan)
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
            application.validate_harness_capability_plan(
                "investigation-a", _variant_plan(widened)
            )

        missing_filter = dict(EXACT_ALLELE_PARAMETERS)
        missing_filter.pop("include_fail")
        with self.assertRaisesRegex(ValueError, "exceeds the approved genomic scope"):
            application.validate_harness_capability_plan(
                "investigation-a", _variant_plan(missing_filter)
            )

        type_confused = dict(EXACT_ALLELE_PARAMETERS)
        type_confused["pos"] = True
        with self.assertRaisesRegex(ValueError, "exceeds the approved genomic scope"):
            application.validate_harness_capability_plan(
                "investigation-a", _variant_plan(type_confused)
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

    def test_simulated_harness_requests_the_entire_exact_allele_scope(self) -> None:
        adapter = SimulatedHarnessAdapter(adapter_id="exact-allele-harness")
        response = adapter.start_task_run(
            HarnessCommand(
                operation=HarnessOperation.START_TASK_RUN,
                workspace_session_id="session-a",
                command_id="command-exact-allele",
                user_id="user-a",
                investigation_id="investigation-a",
                expected_revision=0,
                payload=StartTaskRunPayload(
                    "Investigate the molecular finding",
                    {
                        "disease_scope": "Synthetic condition",
                        "capability_catalog": {
                            GENOMI_VARIANT_RESOLVE: {
                                "available": True,
                                "parameters": EXACT_ALLELE_PARAMETERS,
                            }
                        },
                    },
                ),
            )
        )

        self.assertTrue(response.ok)
        assert response.result is not None
        request = next(
            item
            for item in response.result.proposed_artifact["capability_requests"]
            if item["capability"] == GENOMI_VARIANT_RESOLVE
        )
        self.assertEqual(dict(request["parameters"]), EXACT_ALLELE_PARAMETERS)


if __name__ == "__main__":
    unittest.main()
