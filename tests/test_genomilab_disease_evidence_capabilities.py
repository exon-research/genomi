from __future__ import annotations

import unittest
from typing import Any

from genomi.evidence import envelope as evidence_envelope
from genomi.lab.capability_registry import capability_definition
from genomi.lab.disease_evidence_capabilities import (
    GENE_DISEASE_ASSOCIATIONS,
    PATHWAY_MEMBERS,
    PHENOTYPE_GENE_COMPARE,
    PHENOTYPE_NORMALIZE,
    build_local_disease_evidence_catalog,
    validate_local_disease_evidence_request,
)
from genomi.lab.disease_evidence_external import (
    BIOMARKER_DRUG_EVIDENCE,
    EXPRESSION_QTL_EVIDENCE,
    INHERITANCE_CONSEQUENCE_EVIDENCE,
    PDB_EVIDENCE,
    PERTURBATION_EVIDENCE,
    REGULATORY_EVIDENCE,
    TRIAL_EVIDENCE,
    UNIPROT_EVIDENCE,
    build_external_evidence_catalog,
    validate_external_evidence_request,
)
from genomi.lab.disease_relation_contract import (
    eligible_public_context_source,
    eligible_public_relation_source,
)
from genomi.lab.disease_relations import DiseaseRelationStoreMixin
from genomi.lab.investigation_capabilities import (
    PUBLIC_EVIDENCE_RETRIEVE,
    InvestigationCapabilityMixin,
)


def _profile() -> dict[str, object]:
    return {
        "patient_molecular_snapshot_id": "snapshot-a",
        "observations": [
            {
                "observation_revision_id": "phenotype-a",
                "modality": "phenotype",
                "original_wording": "Intermittent muscle weakness",
                "normalized_code": "HP:0001324",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
            },
            {
                "observation_revision_id": "finding-a",
                "modality": "reported_germline_finding",
                "gene": "SYNTH1",
                "assertion_status": "present",
                "verification_state": "record_confirmed",
            },
            {
                "observation_revision_id": "phenotype-b",
                "modality": "phenotype",
                "original_wording": "Exercise intolerance",
                "assertion_status": "present",
                "verification_state": "user_confirmed",
            },
            {
                "observation_revision_id": "unreviewed-a",
                "modality": "reported_germline_finding",
                "gene": "UNREVIEWED1",
                "assertion_status": "present",
                "verification_state": "unreviewed",
            },
        ],
    }


def _present_envelope(operation: str) -> dict[str, object]:
    return evidence_envelope.evidence_present(
        operation=operation,
        answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
    )


class _EvidenceStore:
    def __init__(self) -> None:
        self.commits: list[dict[str, object]] = []

    def get_profile_snapshot(self, _: str) -> dict[str, object]:
        return {
            "observation_revision_ids": ["phenotype-a", "finding-a"],
            "genomic_scope": None,
        }

    def commit_evidence(
        self, investigation_id: str, **kwargs: object
    ) -> dict[str, object]:
        commit = {"investigation_id": investigation_id, **kwargs}
        self.commits.append(commit)
        return {
            "evidence_record_id": "evidence-local-a",
            **commit,
            "evidence_envelope": kwargs["evidence"]["evidence_envelope"],
        }


class _Application(InvestigationCapabilityMixin):
    def __init__(self, *, operation_status: str = "completed") -> None:
        self.store = _EvidenceStore()
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.operation_status = operation_status

    def investigation(self, investigation_id: str) -> dict[str, object]:
        return {
            "investigation_id": investigation_id,
            "patient_molecular_snapshot_id": "snapshot-a",
            "disease_scope": "Synthetic neuromuscular condition",
            "current_evidence_records": [],
            "current_plan_version": {"plan_version_id": "plan-a"},
        }

    def _accepted_current_plan(self, investigation_id: str) -> dict[str, object]:
        return self.investigation(investigation_id)

    def investigation_profile(self, _: str) -> dict[str, object]:
        return _profile()

    def evidence_capability_manifest(self) -> dict[str, object]:
        return {"gateway": "GenomiLab"}

    def _safe_call(
        self, operation: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        request = dict(params or {})
        self.calls.append((operation, request))
        if operation == "phenotype.normalize_terms":
            return {"status": "completed", "normalized_phenotypes": []}
        result = {
            "status": self.operation_status,
            "source_coverage": {"consulted": [operation]},
            "evidence_envelope": _present_envelope(operation),
        }
        if self.operation_status == "requires_library_install":
            result.update(
                {
                    "missing_library": "hpo",
                    "how_it_helps": "HPO supplies curated phenotype-gene annotations.",
                    "ask_user": {"question": "Install HPO?"},
                }
            )
        return result

    def invoke_investigation_genome(
        self,
        investigation_id: str,
        *,
        operation: str,
        params: dict[str, Any],
    ) -> dict[str, object]:
        raise AssertionError("local public evidence must not use an AGI authorization")


class GenomiLabDiseaseEvidenceCapabilityTests(unittest.TestCase):
    def test_catalog_projects_only_reviewed_pinned_values_and_source_priors(
        self,
    ) -> None:
        application = _Application()
        catalog = application.investigation_capability_catalog("investigation-a")

        self.assertTrue(catalog[PHENOTYPE_NORMALIZE]["available"])
        self.assertTrue(catalog[GENE_DISEASE_ASSOCIATIONS]["available"])
        self.assertTrue(catalog[PHENOTYPE_GENE_COMPARE]["available"])
        self.assertTrue(catalog[PATHWAY_MEMBERS]["available"])
        self.assertEqual(
            catalog[GENE_DISEASE_ASSOCIATIONS]["request_contract"]["fields"]["genes"][
                "allowed_values"
            ],
            ["SYNTH1"],
        )
        self.assertEqual(
            catalog[PHENOTYPE_NORMALIZE]["request_contract"]["fields"]["hpo_ids"][
                "allowed_values"
            ],
            ["HP:0001324"],
        )
        self.assertEqual(
            catalog[PUBLIC_EVIDENCE_RETRIEVE]["source_priors"]["trial_registry"][
                "prior"
            ],
            "trial_registration_not_trial_result",
        )
        self.assertTrue(catalog)
        for capability, entry in catalog.items():
            with self.subTest(capability=capability):
                self.assertEqual(
                    entry["privacy"], capability_definition(capability).privacy
                )

    def test_every_advertised_local_contract_constructs_a_valid_request(self) -> None:
        catalog = build_local_disease_evidence_catalog(_profile())
        requests = {
            PHENOTYPE_NORMALIZE: {
                "profile_revision_ids": ["phenotype-a"],
                "phenotypes": ["Intermittent muscle weakness"],
                "hpo_ids": ["HP:0001324"],
            },
            GENE_DISEASE_ASSOCIATIONS: {
                "profile_revision_ids": ["finding-a"],
                "genes": ["SYNTH1"],
                "classifications": ["Definitive", "Strong"],
                "limit": 25,
            },
            PHENOTYPE_GENE_COMPARE: {
                "profile_revision_ids": ["phenotype-a", "finding-a"],
                "phenotypes": ["Intermittent muscle weakness"],
                "hpo_ids": ["HP:0001324"],
                "genes": ["SYNTH1"],
                "limit": 25,
            },
        }
        for capability, request in requests.items():
            with self.subTest(capability=capability):
                entry = catalog[capability]
                self.assertTrue(entry["available"])
                self.assertEqual(
                    set(entry["request_contract"]["required_fields"]),
                    set(request),
                )
                call = validate_local_disease_evidence_request(
                    capability, request, entry
                )
                self.assertTrue(call.profile_revision_ids)

        pathway_entry = catalog[PATHWAY_MEMBERS]
        pathway_contract = pathway_entry["request_contract"]
        pathway_request = {
            "profile_revision_ids": [
                pathway_contract["fields"]["profile_revision_ids"]["allowed_values"][0]
            ],
            "pathway_id_or_name": "HALLMARK_DNA_REPAIR",
            "source": pathway_contract["fields"]["source"]["fixed_value"],
            "limit": pathway_contract["fields"]["limit"]["suggested_value"],
        }
        pathway_call = validate_local_disease_evidence_request(
            PATHWAY_MEMBERS, pathway_request, pathway_entry
        )
        self.assertEqual(pathway_call.source_family, "msigdb_hallmark")

    def test_hpo_comparison_is_anchor_bound_local_and_source_separated(self) -> None:
        application = _Application()
        catalog = application.investigation_capability_catalog("investigation-a")
        params = {
            "profile_revision_ids": ["phenotype-a", "finding-a"],
            "phenotypes": ["Intermittent muscle weakness"],
            "hpo_ids": ["HP:0001324"],
            "genes": ["SYNTH1"],
            "limit": 25,
        }
        application._validate_capability_parameters(
            PHENOTYPE_GENE_COMPARE, params, catalog
        )
        result = application._execute_capability_request(
            "investigation-a",
            {"capability": PHENOTYPE_GENE_COMPARE, "parameters": params},
            approval=None,
        )

        self.assertEqual(result["status"], "committed")
        self.assertEqual(
            application.calls,
            [
                (
                    "phenotype.compare_gene_hpo_evidence",
                    {
                        "phenotypes": ["Intermittent muscle weakness"],
                        "hpo_ids": ["HP:0001324"],
                        "genes": ["SYNTH1"],
                        "search_stored_research": False,
                        "use_hpo_annotations": True,
                        "limit": 25,
                    },
                )
            ],
        )
        commit = application.store.commits[0]
        self.assertEqual(commit["source_family"], "hpo")
        context = commit["evidence"]["genomilab_context"]
        self.assertEqual(context["profile_revision_ids"], ["phenotype-a", "finding-a"])
        self.assertEqual(context["source_prior"], "hpo")

    def test_private_values_cannot_be_rebound_or_widened_with_paths(self) -> None:
        catalog = build_local_disease_evidence_catalog(_profile())
        with self.assertRaisesRegex(ValueError, "not bound"):
            validate_local_disease_evidence_request(
                PHENOTYPE_NORMALIZE,
                {
                    "profile_revision_ids": ["phenotype-b"],
                    "phenotypes": ["Intermittent muscle weakness"],
                    "hpo_ids": [],
                },
                catalog[PHENOTYPE_NORMALIZE],
            )
        with self.assertRaisesRegex(ValueError, "typed contract"):
            validate_local_disease_evidence_request(
                GENE_DISEASE_ASSOCIATIONS,
                {
                    "profile_revision_ids": ["finding-a"],
                    "genes": ["SYNTH1"],
                    "classifications": ["Definitive"],
                    "limit": 25,
                    "gencc_file": "/tmp/private.tsv",
                },
                catalog[GENE_DISEASE_ASSOCIATIONS],
            )

    def test_pathway_contract_is_local_msigdb_and_requires_controlled_id(self) -> None:
        catalog = build_local_disease_evidence_catalog(_profile())
        call = validate_local_disease_evidence_request(
            PATHWAY_MEMBERS,
            {
                "profile_revision_ids": ["finding-a"],
                "pathway_id_or_name": "HALLMARK_DNA_REPAIR",
                "source": "msigdb_hallmark",
                "limit": 100,
            },
            catalog[PATHWAY_MEMBERS],
        )
        self.assertEqual(call.operation, "pathway.retrieve_members")
        self.assertEqual(call.source_family, "msigdb_hallmark")
        with self.assertRaisesRegex(ValueError, "controlled HALLMARK"):
            validate_local_disease_evidence_request(
                PATHWAY_MEMBERS,
                {
                    "profile_revision_ids": ["finding-a"],
                    "pathway_id_or_name": "some pathway",
                    "source": "msigdb_hallmark",
                    "limit": 100,
                },
                catalog[PATHWAY_MEMBERS],
            )

    def test_missing_local_library_is_committed_as_unavailable_not_a_negative(
        self,
    ) -> None:
        application = _Application(operation_status="requires_library_install")
        params = {
            "profile_revision_ids": ["phenotype-a", "finding-a"],
            "phenotypes": ["Intermittent muscle weakness"],
            "hpo_ids": ["HP:0001324"],
            "genes": ["SYNTH1"],
            "limit": 25,
        }
        result = application._execute_capability_request(
            "investigation-a",
            {"capability": PHENOTYPE_GENE_COMPARE, "parameters": params},
            approval=None,
        )
        self.assertEqual(result["status"], "requires_library_install")
        self.assertEqual(result["missing_library"], "hpo")
        self.assertEqual(len(application.store.commits), 1)


class _ExternalApplication(_Application):
    def __init__(self) -> None:
        super().__init__()
        self.provider_payloads: list[dict[str, object]] = []

    def evidence_capability_manifest(self) -> dict[str, object]:
        return {
            "paperclip": {"live_state": "hard_disabled"},
            "direct_sources": [],
            "fixture_source_families": [
                "literature",
                "regulatory",
                "trial_registry",
                "uniprot",
                "pdb",
                "chembl",
            ],
        }

    def evidence_disclosure_candidate(
        self, investigation_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        return {"selected_provider": "fixture"}

    def retrieve_public_evidence(
        self,
        investigation_id: str,
        payload: dict[str, object],
        *,
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> dict[str, object]:
        del expected_consent_receipt_id
        self.provider_payloads.append(dict(payload))
        return {
            "status": "committed",
            "expected_plan_version_id": expected_plan_version_id,
        }


class GenomiLabExternalDiseaseEvidenceCapabilityTests(unittest.TestCase):
    def test_catalog_exposes_each_supported_source_prior_separately(self) -> None:
        manifest = _ExternalApplication().evidence_capability_manifest()
        catalog = build_external_evidence_catalog(
            ["phenotype-a", "finding-a"], manifest
        )
        expected = {
            INHERITANCE_CONSEQUENCE_EVIDENCE: "literature",
            EXPRESSION_QTL_EVIDENCE: "literature",
            PERTURBATION_EVIDENCE: "literature",
            UNIPROT_EVIDENCE: "uniprot",
            PDB_EVIDENCE: "pdb",
            BIOMARKER_DRUG_EVIDENCE: "chembl",
            REGULATORY_EVIDENCE: "regulatory",
            TRIAL_EVIDENCE: "trial_registry",
        }
        for capability, family in expected.items():
            with self.subTest(capability=capability):
                self.assertTrue(catalog[capability]["available"])
                self.assertEqual(
                    catalog[capability]["fixed_source_family"],
                    family,
                )
                contract = catalog[capability]["request_contract"]
                operation = contract["fields"]["operation"]["allowed_values"][0]
                provider_request = validate_external_evidence_request(
                    capability,
                    {
                        "profile_revision_ids": ["finding-a"],
                        "operation": operation,
                        "query": "reported finding evidence",
                        "query_terms": ["reported finding"],
                        "filters": {},
                        "purpose": "Investigate the approved disease question",
                    },
                    catalog[capability],
                )
                self.assertEqual(provider_request["source_family"], family)
        self.assertEqual(
            catalog[TRIAL_EVIDENCE]["source_prior"],
            "trial_registration_not_trial_result",
        )

    def test_source_specific_wrapper_strips_local_anchors_before_gateway(self) -> None:
        application = _ExternalApplication()
        catalog = application.investigation_capability_catalog("investigation-a")
        params = {
            "profile_revision_ids": ["finding-a"],
            "operation": "lookup",
            "query": "SYNTH1 protein function",
            "query_terms": ["SYNTH1", "protein function"],
            "filters": {"reviewed": "true"},
            "purpose": "Investigate protein function for the approved disease question",
        }
        application._validate_capability_parameters(UNIPROT_EVIDENCE, params, catalog)
        result = application._execute_capability_request(
            "investigation-a",
            {"capability": UNIPROT_EVIDENCE, "parameters": params},
            approval=None,
        )
        self.assertEqual(result["status"], "committed")
        self.assertEqual(result["expected_plan_version_id"], "plan-a")
        self.assertEqual(
            application.provider_payloads,
            [
                {
                    "operation": "lookup",
                    "query": "SYNTH1 protein function",
                    "query_terms": ["SYNTH1", "protein function"],
                    "filters": {
                        "reviewed": "true",
                        "evidence_domain": (
                            "protein_function_isoform_and_feature_annotation"
                        ),
                    },
                    "source_family": "uniprot",
                    "purpose": (
                        "Investigate protein function for the approved disease question"
                    ),
                }
            ],
        )

    def test_external_request_rejects_raw_sequence_paths_and_wrong_prior(self) -> None:
        manifest = _ExternalApplication().evidence_capability_manifest()
        catalog = build_external_evidence_catalog(["finding-a"], manifest)
        base = {
            "profile_revision_ids": ["finding-a"],
            "operation": "search",
            "query": "SYNTH1 consequence",
            "query_terms": ["SYNTH1"],
            "filters": {},
            "purpose": "Investigate the reported finding",
        }
        with self.assertRaisesRegex(ValueError, "raw nucleotide sequence"):
            validate_external_evidence_request(
                INHERITANCE_CONSEQUENCE_EVIDENCE,
                {**base, "query": "ACGTACGTACGTACGTACGTACGTACGTACGT"},
                catalog[INHERITANCE_CONSEQUENCE_EVIDENCE],
            )
        with self.assertRaisesRegex(ValueError, "raw protein sequence"):
            validate_external_evidence_request(
                UNIPROT_EVIDENCE,
                {
                    **base,
                    "query": "MKWVTFISLLLLFSSAYSRGVFRRDTHKSEIAHRFKDLGE",
                },
                catalog[UNIPROT_EVIDENCE],
            )
        with self.assertRaisesRegex(ValueError, "local paths"):
            validate_external_evidence_request(
                INHERITANCE_CONSEQUENCE_EVIDENCE,
                {**base, "query": "inspect /Users/example/sample.vcf"},
                catalog[INHERITANCE_CONSEQUENCE_EVIDENCE],
            )
        with self.assertRaisesRegex(ValueError, "not allowed"):
            validate_external_evidence_request(
                TRIAL_EVIDENCE,
                {**base, "operation": "verify_claim"},
                catalog[TRIAL_EVIDENCE],
            )

    def test_source_specific_request_accepts_only_its_exact_disclosure_preview(
        self,
    ) -> None:
        execution = {
            "request_id": "request-protein",
            "attempts": [
                {
                    "status": "approval_required",
                    "result": {
                        "candidate": {
                            "selected_provider": "paperclip",
                            "payload_sha256": "a" * 64,
                        }
                    },
                }
            ],
        }
        binding = InvestigationCapabilityMixin._validated_approval_binding(
            UNIPROT_EVIDENCE,
            {
                "request_id": "request-protein",
                "approved": True,
                "recipient_provider": "paperclip",
                "payload_sha256": "a" * 64,
            },
            execution,
        )
        self.assertEqual(
            binding,
            {"recipient_provider": "paperclip", "payload_sha256": "a" * 64},
        )


class _RelationStore(DiseaseRelationStoreMixin):
    def __init__(
        self, source_family: str, *, document_state: str | None = None
    ) -> None:
        envelope = _present_envelope(f"evidence_provider.{source_family}")
        evidence: dict[str, object] = {"evidence_envelope": envelope}
        if document_state is not None:
            evidence["records"] = [{"source_document_state": document_state}]
        self.record = {
            "evidence_record_id": "evidence-source-a",
            "source_family": source_family,
            "operation": "source.retrieve",
            "evidence": evidence,
            "evidence_envelope": envelope,
        }

    def get_investigation(self, _: str) -> dict[str, object]:
        return {"disease_scope": "Synthetic condition"}

    def _validate_claim_anchors(self, *args: object, **kwargs: object) -> None:
        return None

    def _disease_relation_source_records(
        self, investigation_id: str, evidence_record_ids: list[str]
    ) -> dict[str, dict[str, object]]:
        return {"evidence-source-a": self.record}

    def commit_evidence(
        self, investigation_id: str, **kwargs: object
    ) -> dict[str, object]:
        return {"evidence_record_id": "relation-a", **kwargs}


def _relation_parameters(kind: str) -> dict[str, object]:
    return {
        "disease_scope": "Synthetic condition",
        "profile_revision_ids": ["phenotype-a"],
        "source_evidence_record_ids": ["evidence-source-a"],
        "relation_kind": kind,
        "direction": "supports",
        "source_supplied_strength": {
            "state": "not_reported",
            "scheme": None,
            "raw_label": None,
            "raw_value": None,
            "source_locator": None,
        },
        "population_context": {
            "state": "not_reported",
            "description": None,
            "source_locator": None,
        },
        "tissue_context": {
            "state": "not_reported",
            "description": None,
            "source_locator": None,
        },
        "specimen_context": {
            "state": "not_reported",
            "description": None,
            "source_locator": None,
        },
        "conflicts": [],
        "uncertainty": ["source_not_reported"],
    }


class GenomiLabDiseaseRelationPriorTests(unittest.TestCase):
    def test_local_curated_sources_are_eligible_but_relation_kind_stays_typed(
        self,
    ) -> None:
        store = _RelationStore("hpo")
        self.assertTrue(eligible_public_relation_source(store.record))
        relation = store.commit_disease_relation(
            "investigation-a", _relation_parameters("phenotype_disease")
        )
        self.assertEqual(relation["source_family"], "hpo")
        with self.assertRaisesRegex(ValueError, "source-family prior"):
            store.commit_disease_relation(
                "investigation-a", _relation_parameters("regulatory_status")
            )

    def test_trial_registration_can_only_be_context_not_clinical_support(self) -> None:
        store = _RelationStore("trial_registry", document_state="trial_registration")
        self.assertTrue(eligible_public_context_source(store.record))
        self.assertFalse(eligible_public_relation_source(store.record))
        context = _relation_parameters("trial_relevance")
        context["direction"] = "context_only"
        committed = store.commit_disease_relation("investigation-a", context)
        self.assertEqual(committed["source_family"], "trial_registry")
        with self.assertRaisesRegex(ValueError, "usable"):
            store.commit_disease_relation(
                "investigation-a", _relation_parameters("trial_relevance")
            )


if __name__ == "__main__":
    unittest.main()
