from __future__ import annotations

import unittest

from _candidate_helper import compare_candidate_payload

from genomi.capabilities.phenotype.targets import (
    compare_target_gene_evidence,
    retrieve_disease_clinical_drug_targets,
)
from genomi.operations import call_operation


class DrugTargetEvidenceComparisonTests(unittest.TestCase):
    def test_retrieve_disease_clinical_drug_targets_from_opentargets(self) -> None:
        calls = []

        def fake_fetch(query: str, variables: dict) -> dict:
            calls.append(variables)
            if "DiseaseSearch" in query:
                return {
                    "data": {
                        "search": {
                            "hits": [
                                {"id": "MONDO_0004979", "name": "asthma", "entity": "disease", "score": 10.0}
                            ]
                        }
                    }
                }
            return {
                "data": {
                    "disease": {
                        "id": "MONDO_0004979",
                        "name": "asthma",
                        "drugAndClinicalCandidates": {
                            "count": 2,
                            "rows": [
                                {
                                    "id": "candidate-1",
                                    "maxClinicalStage": "PHASE_3",
                                    "drug": {
                                        "id": "CHEMBL1",
                                        "name": "Example beta agonist",
                                        "drugType": "Small molecule",
                                        "maximumClinicalStage": "PHASE_3",
                                        "mechanismsOfAction": {
                                            "rows": [
                                                {
                                                    "mechanismOfAction": "Beta-2 adrenergic receptor agonist",
                                                    "actionType": "AGONIST",
                                                    "targetName": "Beta-2 adrenergic receptor",
                                                    "targets": [
                                                        {
                                                            "id": "ENSG00000169252",
                                                            "approvedSymbol": "ADRB2",
                                                            "approvedName": "adrenoceptor beta 2",
                                                        }
                                                    ],
                                                    "references": [
                                                        {"source": "ChEMBL", "ids": ["CHEMBL1"], "urls": ["https://example.test/chembl"]}
                                                    ],
                                                }
                                            ]
                                        },
                                    },
                                    "clinicalReports": [
                                        {
                                            "source": "AACT",
                                            "clinicalStage": "PHASE_3",
                                            "trialOverallStatus": "COMPLETED",
                                            "url": "https://clinicaltrials.gov/study/NCT1",
                                            "title": "Example asthma trial",
                                        }
                                    ],
                                },
                                {
                                    "id": "candidate-2",
                                    "maxClinicalStage": "PHASE_1",
                                    "drug": {
                                        "id": "CHEMBL2",
                                        "name": "Early exploratory drug",
                                        "mechanismsOfAction": {
                                            "rows": [
                                                {
                                                    "mechanismOfAction": "Early target",
                                                    "actionType": "INHIBITOR",
                                                    "targetName": "Early target",
                                                    "targets": [{"id": "ENSG0", "approvedSymbol": "GENE1", "approvedName": "gene 1"}],
                                                    "references": [],
                                                }
                                            ]
                                        },
                                    },
                                    "clinicalReports": [],
                                },
                            ],
                        },
                    }
                }
            }

        result = retrieve_disease_clinical_drug_targets(
            disease="asthma",
            genes=["ADRB2", "GENE1"],
            fetch_opentargets_graphql=fake_fetch,
            minimum_clinical_stage="PHASE_2",
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual([target["gene"] for target in result["targets"]], ["ADRB2"])
        self.assertTrue(result["targets"][0]["candidate_match"])
        self.assertEqual(result["targets"][0]["max_clinical_stage"], "PHASE_3")
        self.assertEqual(result["source_records"][0]["verified_fields"]["genes"], ["ADRB2"])
        self.assertTrue(calls)

    def test_retrieve_disease_clinical_drug_targets_returns_clean_empty(self) -> None:
        def fake_fetch(query: str, variables: dict) -> dict:
            if "DiseaseSearch" in query:
                return {
                    "data": {
                        "search": {
                            "hits": [
                                {"id": "MONDO_1", "name": "condition", "entity": "disease", "score": 10.0}
                            ]
                        }
                    }
                }
            return {
                "data": {
                    "disease": {
                        "id": "MONDO_1",
                        "name": "condition",
                        "drugAndClinicalCandidates": {"count": 0, "rows": []},
                    }
                }
            }

        result = retrieve_disease_clinical_drug_targets(
            disease="condition",
            fetch_opentargets_graphql=fake_fetch,
        )

        self.assertEqual(result["status"], "no_clinical_drug_targets")
        self.assertEqual(result["coverage_state"], "in_scope_empty")
        self.assertEqual(result["targets"], [])
        self.assertEqual(result["source_records"], [])
        self.assertIn("Open Targets Platform disease drug and clinical candidates", result["source_coverage"]["sources_consulted_and_empty"])

    def test_retrieve_disease_clinical_drug_targets_gene_membership_projection(self) -> None:
        def fake_fetch(query: str, variables: dict) -> dict:
            if "DiseaseSearch" in query:
                return {
                    "data": {
                        "search": {
                            "hits": [
                                {"id": "MONDO_0004979", "name": "asthma", "entity": "disease", "score": 10.0}
                            ]
                        }
                    }
                }
            return {
                "data": {
                    "disease": {
                        "id": "MONDO_0004979",
                        "name": "asthma",
                        "drugAndClinicalCandidates": {
                            "count": 1,
                            "rows": [
                                {
                                    "id": "candidate-1",
                                    "maxClinicalStage": "PHASE_3",
                                    "drug": {
                                        "id": "CHEMBL1",
                                        "name": "Example beta agonist",
                                        "drugType": "Small molecule",
                                        "mechanismsOfAction": {
                                            "rows": [
                                                {
                                                    "mechanismOfAction": "Beta-2 adrenergic receptor agonist",
                                                    "actionType": "AGONIST",
                                                    "targetName": "Beta-2 adrenergic receptor",
                                                    "targets": [
                                                        {
                                                            "id": "ENSG00000169252",
                                                            "approvedSymbol": "ADRB2",
                                                            "approvedName": "adrenoceptor beta 2",
                                                        }
                                                    ],
                                                    "references": [],
                                                }
                                            ]
                                        },
                                    },
                                    "clinicalReports": [],
                                },
                                {
                                    "id": "candidate-2",
                                    "maxClinicalStage": "PHASE_2",
                                    "drug": {
                                        "id": "CHEMBL2",
                                        "name": "Example target modulator",
                                        "drugType": "Small molecule",
                                        "mechanismsOfAction": {
                                            "rows": [
                                                {
                                                    "mechanismOfAction": "GENE1 modulation",
                                                    "actionType": "MODULATOR",
                                                    "targetName": "gene 1",
                                                    "targets": [
                                                        {
                                                            "id": "ENSG0",
                                                            "approvedSymbol": "GENE1",
                                                            "approvedName": "gene 1",
                                                        }
                                                    ],
                                                    "references": [],
                                                }
                                            ]
                                        },
                                    },
                                    "clinicalReports": [],
                                }
                            ],
                        },
                    }
                }
            }

        result = retrieve_disease_clinical_drug_targets(
            disease="asthma",
            genes=["ADRB2", "GENE1"],
            mode="gene_membership",
            limit=1,
            fetch_opentargets_graphql=fake_fetch,
        )

        self.assertEqual(result["mode"], "gene_membership")
        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["gene_membership"][0]["gene_symbol"], "ADRB2")
        self.assertTrue(result["gene_membership"][0]["is_clinical_target"])
        self.assertEqual(result["gene_membership"][0]["highest_phase"], "PHASE_3")
        self.assertEqual(result["gene_membership"][0]["evidence_record_count"], 1)
        self.assertTrue(result["gene_membership"][0]["source_record_ids"])
        self.assertEqual(result["gene_membership"][1]["gene_symbol"], "GENE1")
        self.assertTrue(result["gene_membership"][1]["is_clinical_target"])
        self.assertEqual(result["gene_membership"][1]["highest_phase"], "PHASE_2")
        self.assertEqual(result["gene_membership"][1]["evidence_record_count"], 1)
        self.assertEqual(len(result["source_records"]), 1)

    def test_compare_drug_target_prefers_direct_mechanism_source(self) -> None:
        result = compare_target_gene_evidence(
            drug_class="beta agonist",
            indication="cancer",
            genes=["IL13", "ADRB2"],
            search_stored_research=False,
            source_records=[
                {
                    "record_id": "chembl-tubb",
                    "source_id": "chembl",
                    "source_type": "drug mechanism target",
                    "source_title": "ChEMBL beta agonist mechanism",
                    "source_url": "https://example.test/chembl/tubb",
                    "finding": "Beta agonist source supports ADRB2 as a receptor target.",
                    "verified_fields": {
                        "genes": ["ADRB2"],
                        "drug_classes": ["beta agonist"],
                        "target_relationships": ["drug target"],
                    },
                    "support_spans": [
                        {
                            "field": "gene",
                            "value": "ADRB2",
                            "source_text": "Beta agonist source supports ADRB2 as a receptor target.",
                        },
                        {
                            "field": "drug_class",
                            "value": "beta agonist",
                            "source_text": "Beta agonist source supports ADRB2 as a receptor target.",
                        },
                    ],
                },
                {
                    "record_id": "ot-vegfa",
                    "source_id": "opentargets",
                    "source_type": "target disease association",
                    "source_title": "Open Targets IL13 cancer",
                    "source_url": "https://example.test/opentargets/vegfa",
                    "finding": "IL13 has target-disease association context in cancer.",
                    "verified_fields": {
                        "genes": ["IL13"],
                        "indications": ["cancer"],
                        "target_relationships": ["target disease association"],
                    },
                },
            ],
        )

        self.assertEqual(result["status"], "direct_source_supported")
        self.assertEqual(result["top_observed"]["candidate_id"], "ADRB2")
        self.assertEqual(result["top_observed"]["best_evidence_lane"], "direct_source_match")
        vegfa = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "IL13")
        self.assertEqual(vegfa["best_source_family"], "association_source")
        self.assertNotEqual(vegfa["answerability"], "direct_source_supported")

    def test_compare_drug_target_uses_host_semantic_drug_class_hint(self) -> None:
        result = compare_target_gene_evidence(
            indication="asthma",
            genes=["ADRB2"],
            search_stored_research=False,
            semantic_context={
                "raw_query": "Which gene matters for an inhaler?",
                "host_expansions": ["beta agonist"],
                "host_entities": [{"text": "beta agonist", "type": "drug_class"}],
            },
            source_records=[
                {
                    "record_id": "chembl-adrb2",
                    "source_id": "chembl",
                    "source_type": "drug mechanism target",
                    "source_title": "ChEMBL beta agonist mechanism",
                    "finding": "Beta agonist source supports ADRB2 as a receptor target.",
                    "verified_fields": {
                        "genes": ["ADRB2"],
                        "drug_classes": ["beta agonist"],
                        "target_relationships": ["drug target"],
                    },
                }
            ],
        )

        self.assertEqual(result["top_observed"]["candidate_id"], "ADRB2")
        accepted = {item["text"] for item in result["semantic_context"]["term_matches"]}
        self.assertIn("beta agonist", accepted)

    def test_association_only_source_does_not_recommend_identifier(self) -> None:
        result = compare_target_gene_evidence(
            drug_class="bronchodilator",
            indication="asthma",
            genes=["ADRB2"],
            search_stored_research=False,
            source_records=[
                {
                    "record_id": "ot-adrb2",
                    "source_id": "opentargets",
                    "source_type": "target disease association",
                    "source_title": "Open Targets ADRB2 asthma",
                    "source_url": "https://example.test/opentargets/adrb2",
                    "finding": "ADRB2 has target-disease association evidence for asthma.",
                    "verified_fields": {
                        "genes": ["ADRB2"],
                        "indications": ["asthma"],
                        "target_relationships": ["target disease association"],
                    },
                }
            ],
        )

        self.assertEqual(result["top_observed"]["candidate_id"], "ADRB2")
        self.assertEqual(result["top_observed"]["best_source_family"], "association_source")
        self.assertIn("Association-only", " ".join(result["warnings"]))

    def test_target_rejects_indication_only_context(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires drug, drug_class, or mechanism"):
            compare_target_gene_evidence(
                indication="asthma",
                genes=["ADRB2"],
                search_stored_research=False,
                source_records=[],
            )

    def test_cross_source_gene_comparator_reports_no_matching_panels(self) -> None:
        result = compare_candidate_payload({
                "drug": "example drug",
                "genes": ["GENE1"],
                "search_stored_research": False,
                "source_records": [],
            })

        self.assertEqual(result["status"], "no_matching_evidence_panels")
        self.assertNotIn("answer", result)
        self.assertIn("evidence_panels", result)
        self.assertIn("candidate_evidence_matrix", result)

    def test_drug_target_operation_returns_source_specific_answer_and_evidence(self) -> None:
        result = call_operation(
            "phenotype.compare_drug_target_evidence",
            {
                "drug_class": "beta agonist",
                "genes": ["IL13", "ADRB2"],
                "search_stored_research": False,
                "source_records": [
                    {
                        "record_id": "chembl-tubb",
                        "source_id": "chembl",
                        "source_type": "drug mechanism target",
                        "source_title": "ChEMBL beta agonist mechanism",
                        "source_url": "https://example.test/chembl/tubb",
                        "finding": "Beta agonist source supports ADRB2 as a receptor target.",
                        "verified_fields": {
                            "genes": ["ADRB2"],
                            "drug_classes": ["beta agonist"],
                            "target_relationships": ["drug target"],
                        },
                        "support_spans": [
                            {
                                "field": "gene",
                                "value": "ADRB2",
                                "source_text": "Beta agonist source supports ADRB2 as a receptor target.",
                            }
                        ],
                    }
                ],
            },
        )

        self.assertNotIn("answer", result)
        self.assertEqual(result["top_observed_candidate"], "ADRB2")
        self.assertEqual(result["source_prior"], "drug_target_mechanism")
        self.assertEqual(result["ranking"][0]["candidate"], "ADRB2")
        self.assertEqual(result["evidence_records"][0]["candidate"], "ADRB2")


if __name__ == "__main__":
    unittest.main()
