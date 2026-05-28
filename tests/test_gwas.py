from __future__ import annotations

import unittest

from _candidate_helper import compare_candidate_payload
from _gwas_helpers import _association, _v2_association

from genomi.capabilities.gwas.gwas import (
    compare_gwas_gene_evidence,
)
from genomi.capabilities.phenotype.gene_identification import (
    retrieve_trait_gene_records,
)
from genomi.evidence.sources import evidence_source_catalog
from genomi.operations import call_operation


class GwasCatalogTests(unittest.TestCase):
    def test_compare_gwas_gene_evidence_ranks_gene_list_without_rsid_inputs(self) -> None:
        result = compare_gwas_gene_evidence(
            "LDL cholesterol",
            ["APOB", "PCSK9"],
            source_records=[
                _association("rs1", "LDL cholesterol", 2e-9, "rs1-A", "PCSK9", "GCST11", "111"),
                _association("rs2", "unrelated trait", 1e-40, "rs2-A", "APOB", "GCST12", "112"),
            ],
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["top_observed"]["candidate_id"], "PCSK9")
        self.assertEqual(result["top_observed"]["answerability"], "direct_source_supported")
        kras = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "APOB")
        self.assertEqual(kras["answerability"], "not_supported")

    def test_compare_gwas_gene_evidence_uses_host_semantic_trait_hint_for_source_records(self) -> None:
        result = compare_gwas_gene_evidence(
            "early heart disease",
            ["PCSK9", "APOB"],
            source_records=[_v2_association("coronary artery disease", "PCSK9", 1e-20, "2201")],
            semantic_context={
                "raw_query": "Am I at risk for early heart disease?",
                "host_expansions": ["coronary artery disease"],
                "host_entities": [{"text": "coronary artery disease", "type": "trait_or_condition"}],
            },
        )

        self.assertEqual(result["top_observed"]["candidate_id"], "PCSK9")
        accepted = {item["text"] for item in result["semantic_context"]["term_matches"]}
        self.assertIn("coronary artery disease", accepted)

    def test_gwas_gene_operation_is_registered(self) -> None:
        result = compare_candidate_payload({
                "phenotype": "LDL cholesterol",
                "genes": ["PCSK9"],
                "download_hpo_annotations": False,
                "search_stored_research": False,
                "gwas_source_records": [_association("rs1", "LDL cholesterol", 2e-9, "rs1-A", "PCSK9", "GCST11", "111")],
            })

        self.assertNotIn("answer", result)
        self.assertTrue(result["agent_decision_required"])
        panel = result["evidence_panels"]["gwas_catalog_association"]
        self.assertEqual(panel["ranking"][0]["candidate"], "PCSK9")
        self.assertEqual(panel["evidence_records"][0]["candidate"], "PCSK9")
        self.assertEqual(panel["decision_evidence"]["top_observed_candidate"], "PCSK9")
        self.assertEqual(result["decision_evidence"]["gwas_catalog_association"]["top_observed_candidate"], "PCSK9")
        self.assertEqual(result["cross_prior_summary"]["top_candidates_by_prior"]["gwas_catalog_association"], "PCSK9")

    def test_bare_phenotype_gene_list_returns_multi_prior_evidence(self) -> None:
        result = compare_candidate_payload({
                "phenotype": "LDL cholesterol",
                "genes": ["APOB", "PCSK9"],
                "include_gwas": True,
                "download_hpo_annotations": False,
                "search_stored_research": False,
                "gwas_source_records": [_association("rs1", "LDL cholesterol", 2e-9, "rs1-A", "PCSK9", "GCST11", "111")],
            })

        self.assertNotIn("answer", result)
        self.assertEqual(result["status"], "evidence_panels_returned")
        self.assertEqual(result["evidence_panels"]["gwas_catalog_association"]["ranking"][0]["candidate"], "PCSK9")
        self.assertEqual(result["prior_fit"]["context_aligned_prior"], "gwas_catalog_association")
        self.assertIn("GWAS-specific source records", " ".join(result["prior_fit"]["fits"]["gwas_catalog_association"]["signals"]))
        kras = next(row for row in result["candidate_evidence_matrix"] if row["candidate"] == "APOB")
        self.assertIsNone(kras["priors"]["gwas_catalog_association"]["rank"])
        self.assertIn("gwas_catalog_association", result["coverage"])

    def test_cross_source_gene_comparison_exposes_prior_conflicts_without_answer(self) -> None:
        result = compare_candidate_payload({
                "phenotype": "LDL cholesterol",
                "drug": "example drug",
                "genes": ["APOB", "PCSK9"],
                "download_hpo_annotations": False,
                "search_stored_research": False,
                "gwas_source_records": [_association("rs1", "LDL cholesterol", 2e-9, "rs1-A", "PCSK9", "GCST11", "111")],
                "target_source_records": [
                    {
                        "record_id": "chembl-kras",
                        "source_id": "chembl",
                        "source_type": "drug mechanism target",
                        "source_title": "ChEMBL example target",
                        "source_url": "https://example.test/chembl/kras",
                        "finding": "Example drug targets APOB.",
                        "verified_fields": {
                            "genes": ["APOB"],
                            "drugs": ["example drug"],
                            "target_relationships": ["drug target"],
                        },
                    }
                ],
            })

        self.assertNotIn("answer", result)
        self.assertTrue(result["agent_decision_required"])
        self.assertTrue(result["cross_prior_summary"]["priors_disagree"])
        self.assertEqual(result["cross_prior_summary"]["top_candidates_by_prior"]["gwas_catalog_association"], "PCSK9")
        self.assertEqual(result["cross_prior_summary"]["top_candidates_by_prior"]["drug_target_mechanism"], "APOB")
        self.assertEqual(result["prior_fit"]["context_aligned_prior"], "drug_target_mechanism")
        self.assertEqual(result["cross_prior_summary"]["context_aligned_prior"], "drug_target_mechanism")

    def test_gene_comparison_uses_task_text_for_prior_fit(self) -> None:
        result = compare_candidate_payload({
                "task_text": "Use the GWAS Catalog mapped gene evidence for this trait.",
                "phenotype": "LDL cholesterol",
                "genes": ["APOB", "PCSK9"],
                "download_hpo_annotations": False,
                "search_stored_research": False,
                "gwas_source_records": [_association("rs1", "LDL cholesterol", 2e-9, "rs1-A", "PCSK9", "GCST11", "111")],
            })

        self.assertNotIn("answer", result)
        self.assertEqual(result["prior_fit"]["context_aligned_prior"], "gwas_catalog_association")
        self.assertEqual(result["prior_fit"]["support_level"], "high")
        self.assertIn("gwas_catalog_association", result["prior_fit"]["fits"])

    def test_gene_comparison_exposes_locus_to_gene_prior_evidence(self) -> None:
        result = compare_candidate_payload({
                "task_text": "Use variant-to-gene colocalization evidence for this risk locus.",
                "phenotype": "asthma",
                "genes": ["SLC39A8", "ORMDL3"],
                "download_hpo_annotations": False,
                "search_stored_research": False,
                "use_opentargets": False,
                "include_gwas": False,
                "locus_source_records": [
                    {
                        "record_id": "v2g-1",
                        "source_id": "opentargets_v2g",
                        "source_title": "Open Targets variant-to-gene",
                        "source_url": "https://example.test/v2g/1",
                        "evidence_type": "variant-to-gene colocalization",
                        "gene": "ORMDL3",
                        "variant": "rs7216389",
                        "locus": "17q12",
                        "l2g_score": 0.91,
                        "finding": "rs7216389 colocalizes with ORMDL3 expression at the 17q12 asthma locus.",
                        "support_span": "ORMDL3 has high variant-to-gene colocalization support.",
                    },
                    {
                        "record_id": "nearest-1",
                        "source_id": "nearest_gene",
                        "evidence_type": "nearest gene",
                        "gene": "SLC39A8",
                        "variant": "rs7216389",
                        "locus": "17q12",
                        "score": 0.4,
                        "finding": "SLC39A8 is listed as a nearby mapped gene.",
                    },
                ],
            })

        panel = result["evidence_panels"]["locus_to_gene_prioritization"]
        self.assertEqual(panel["ranking"][0]["candidate"], "ORMDL3")
        self.assertEqual(result["prior_fit"]["context_aligned_prior"], "locus_to_gene_prioritization")
        self.assertIn("variant-to-gene", " ".join(result["prior_fit"]["fits"]["locus_to_gene_prioritization"]["signals"]))
        top_evidence = result["decision_evidence"]["locus_to_gene_prioritization"]["top_observed_evidence"]
        self.assertEqual(top_evidence["candidate"], "ORMDL3")
        self.assertEqual(top_evidence["supporting_evidence"][0]["record_id"], "v2g-1")
        self.assertEqual(top_evidence["supporting_evidence"][0]["support_span"], "ORMDL3 has high variant-to-gene colocalization support.")

    def test_weak_locus_neighbor_evidence_does_not_select_locus_prior(self) -> None:
        result = compare_candidate_payload({
                "task_text": "Given candidate genes at a trait-associated risk locus for asthma, name the causal gene.",
                "phenotype": "asthma",
                "genes": ["ADRB2", "ORMDL3"],
                "download_hpo_annotations": False,
                "search_stored_research": False,
                "use_opentargets": False,
                "include_gwas": False,
                "locus_source_records": [
                    {
                        "record_id": "nearest-ormdl3",
                        "source_id": "nearest_gene",
                        "evidence_type": "nearest gene",
                        "gene": "ORMDL3",
                        "variant": "rs7216389",
                        "locus": "17q12",
                        "score": 0.4,
                        "finding": "ORMDL3 is listed as a nearby mapped gene at the asthma locus.",
                    }
                ],
            })

        self.assertNotEqual(result["prior_fit"]["context_aligned_prior"], "locus_to_gene_prioritization")
        locus_fit = result["prior_fit"]["fits"]["locus_to_gene_prioritization"]
        self.assertEqual(locus_fit["fit"], "weak")
        self.assertIn("weak locus-neighbor", " ".join(locus_fit["signals"]))
        self.assertIn("nearest, mapped, or generic risk-locus", " ".join(locus_fit["cautions"]))
        self.assertEqual(
            result["evidence_panels"]["locus_to_gene_prioritization"]["ranking"][0]["support"],
            "same_gene_or_locus",
        )

    def test_causal_locus_question_downgrades_gwas_gene_fields(self) -> None:
        result = compare_candidate_payload({
                "task_text": "Given candidate genes at a trait-associated risk locus for asthma, name the causal gene.",
                "phenotype": "asthma",
                "genes": ["ADRB2", "ORMDL3"],
                "download_hpo_annotations": False,
                "search_stored_research": False,
                "use_opentargets": False,
                "gwas_source_records": [_association("rs1", "asthma", 2e-9, "rs1-A", "ADRB2", "GCST11", "111")],
                "locus_source_records": [
                    {
                        "record_id": "nearest-ormdl3",
                        "source_id": "nearest_gene",
                        "evidence_type": "nearest gene",
                        "gene": "ORMDL3",
                        "variant": "rs7216389",
                        "locus": "17q12",
                        "score": 0.4,
                        "finding": "ORMDL3 is listed as a nearby mapped gene at the asthma locus.",
                    }
                ],
            })

        self.assertIsNone(result["prior_fit"]["context_aligned_prior"])
        self.assertEqual(result["prior_fit"]["support_level"], "low")
        self.assertEqual(result["cross_prior_summary"]["top_candidates_by_prior"]["gwas_catalog_association"], "ADRB2")
        self.assertEqual(result["cross_prior_summary"]["top_candidates_by_prior"]["locus_to_gene_prioritization"], "ORMDL3")
        gwas_panel = result["evidence_panels"]["gwas_catalog_association"]
        self.assertEqual(gwas_panel["ranking"][0]["candidate"], "ADRB2")
        self.assertEqual(gwas_panel["ranking"][0]["support"], "same_gene_or_locus")
        self.assertEqual(gwas_panel["ranking"][0]["evidence_support_level"], "none")
        self.assertIsNone(gwas_panel["decision_evidence"]["top_observed_candidate"])
        self.assertEqual(gwas_panel["source_local_ordering"]["ordered_candidates"][0]["candidate"], "ADRB2")
        self.assertEqual(
            gwas_panel["evidence_records"][0]["record"]["evidence_regime"],
            "association_only_not_causal",
        )
        self.assertIn(
            "association-only",
            " ".join(result["prior_fit"]["fits"]["gwas_catalog_association"]["cautions"]),
        )
        self.assertEqual(result["trait_gene_records"]["status"], "no_trait_gene_records")
        self.assertIn("no native trait-to-gene", " ".join(result["warnings"]))

    def test_trait_gene_records_returns_empty_without_native_records(self) -> None:
        result = retrieve_trait_gene_records(
            trait="LDL cholesterol",
            genes=["PCSK9", "SLC18A1"],
            use_opentargets=False,
        )

        self.assertNotIn("answer", result)
        self.assertTrue(result["agent_decision_required"])
        self.assertEqual(result["status"], "no_trait_gene_records")
        self.assertEqual(result["coverage_state"], "in_scope_empty")
        by_gene = {row["gene"]: row for row in result["gene_records"]}
        self.assertEqual(by_gene["PCSK9"]["direct_record_count"], 0)
        self.assertEqual(by_gene["SLC18A1"]["association_record_count"], 0)
        self.assertEqual(result["comparison_inputs"]["source_records"], [])
        self.assertEqual(result["source_records"], [])

    def test_trait_gene_records_retrieves_opentargets_records_natively(self) -> None:
        calls = []

        def fake_fetch(query: str, variables: dict) -> dict:
            calls.append(variables)
            if "SearchDiseases" in query:
                return {
                    "data": {
                        "search": {
                            "hits": [
                                {"id": "EFO_0004611", "name": "low density lipoprotein cholesterol measurement", "entity": "disease"}
                            ]
                        }
                    }
                }
            return {
                "data": {
                    "disease": {
                        "id": "EFO_0004611",
                        "name": "low density lipoprotein cholesterol measurement",
                        "associatedTargets": {
                            "rows": [
                                {
                                    "score": 0.74,
                                    "target": {
                                        "id": "ENSG00000169174",
                                        "approvedSymbol": "PCSK9",
                                        "approvedName": "proprotein convertase subtilisin/kexin type 9",
                                    },
                                },
                                {
                                    "score": 0.10,
                                    "target": {
                                        "id": "ENSG00000161847",
                                        "approvedSymbol": "SLC18A1",
                                        "approvedName": "solute carrier family 18 member A1",
                                    },
                                },
                            ]
                        },
                    }
                }
            }

        result = retrieve_trait_gene_records(
            trait="LDL cholesterol",
            genes=["PCSK9", "SLC18A1"],
            fetch_opentargets_graphql=fake_fetch,
        )

        self.assertEqual(result["status"], "trait_gene_records_found")
        self.assertEqual(result["coverage_state"], "data_returned")
        by_gene = {row["gene"]: row for row in result["gene_records"]}
        self.assertTrue(by_gene["PCSK9"]["direct_record_count"])
        self.assertEqual(result["coverage"]["native_retrieval"]["status"], "completed")
        self.assertEqual(result["source_records"][0]["source_id"], "opentargets")
        self.assertTrue(calls)

    def test_trait_gene_records_can_run_without_gene_filter(self) -> None:
        def fake_fetch(query: str, variables: dict) -> dict:
            if "SearchDiseases" in query:
                return {
                    "data": {
                        "search": {
                            "hits": [
                                {"id": "EFO_0004611", "name": "low density lipoprotein cholesterol measurement", "entity": "disease"}
                            ]
                        }
                    }
                }
            if "drugAndClinicalCandidates" in query:
                return {"data": {"disease": {"drugAndClinicalCandidates": {"count": 0, "rows": []}}}}
            return {
                "data": {
                    "disease": {
                        "id": "EFO_0004611",
                        "name": "low density lipoprotein cholesterol measurement",
                        "associatedTargets": {
                            "rows": [
                                {
                                    "score": 0.74,
                                    "target": {
                                        "id": "ENSG00000169174",
                                        "approvedSymbol": "PCSK9",
                                        "approvedName": "proprotein convertase subtilisin/kexin type 9",
                                    },
                                }
                            ]
                        },
                    }
                }
            }

        result = retrieve_trait_gene_records(
            trait="LDL cholesterol",
            fetch_opentargets_graphql=fake_fetch,
        )

        self.assertEqual(result["status"], "trait_gene_records_found")
        self.assertEqual(result["query"]["genes_filter"], [])
        self.assertEqual(result["gene_records"][0]["gene"], "PCSK9")

    def test_trait_gene_records_includes_clinical_drug_target_records(self) -> None:
        def fake_fetch(query: str, variables: dict) -> dict:
            if "SearchDiseases" in query or "DiseaseSearch" in query:
                return {
                    "data": {
                        "search": {
                            "hits": [
                                {"id": "MONDO_0004979", "name": "asthma", "entity": "disease"}
                            ]
                        }
                    }
                }
            if "drugAndClinicalCandidates" in query:
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
            return {
                "data": {
                    "disease": {
                        "id": "MONDO_0004979",
                        "name": "asthma",
                        "associatedTargets": {"rows": []},
                    }
                }
            }

        result = retrieve_trait_gene_records(
            trait="asthma",
            genes=["ADRB2", "IL13"],
            fetch_opentargets_graphql=fake_fetch,
        )

        self.assertEqual(result["status"], "trait_gene_records_found")
        by_gene = {row["gene"]: row for row in result["gene_records"]}
        self.assertEqual(by_gene["ADRB2"]["direct_record_count"], 1)
        self.assertEqual(result["coverage"]["clinical_drug_target_retrieval"]["status"], "completed")
        self.assertEqual(result["source_records"][0]["finding_type"], "clinical_drug_target")

    def test_gene_comparison_attaches_trait_gene_records_without_answering(self) -> None:
        result = compare_candidate_payload({
                "task_text": "Given candidate genes at a GWAS locus for LDL cholesterol, identify the causal gene.",
                "phenotype": "LDL cholesterol",
                "genes": ["PCSK9", "SLC18A1"],
                "download_hpo_annotations": False,
                "search_stored_research": False,
                "use_opentargets": False,
                "include_gwas": False,
                "source_records": [
                    {
                        "record_id": "ot-pcsk9",
                        "source_id": "opentargets genetics",
                        "source_type": "target-disease mechanism",
                        "source_title": "Open Targets Genetics PCSK9",
                        "source_url": "https://example.test/ot/pcsk9",
                        "gene": "PCSK9",
                        "condition": "LDL cholesterol",
                        "finding": "PCSK9 has canonical causal gene support for LDL cholesterol.",
                        "verified_fields": {"genes": ["PCSK9"], "conditions": ["LDL cholesterol"]},
                    }
                ],
            })

        self.assertNotIn("answer", result)
        self.assertEqual(result["trait_gene_records"]["status"], "no_trait_gene_records")
        self.assertEqual(result["trait_gene_records"]["gene_records"][0]["gene"], "PCSK9")
        self.assertEqual(result["trait_gene_records"]["gene_records"][0]["direct_record_count"], 0)

    def test_gene_comparison_exposes_all_evidence_for_ranked_candidate(self) -> None:
        result = compare_candidate_payload({
                "task_text": "Use GWAS Catalog mapped gene evidence for this trait.",
                "phenotype": "LDL cholesterol",
                "genes": ["PCSK9"],
                "download_hpo_annotations": False,
                "search_stored_research": False,
                "gwas_source_records": [
                    _association("rs1", "LDL cholesterol", 2e-9, "rs1-A", "PCSK9", "GCST11", "111"),
                    _association("rs2", "LDL cholesterol", 3e-8, "rs2-A", "PCSK9", "GCST12", "112"),
                ],
            })

        top_evidence = result["decision_evidence"]["gwas_catalog_association"]["top_observed_evidence"]
        self.assertEqual(top_evidence["candidate"], "PCSK9")
        self.assertEqual(top_evidence["evidence_trace"]["supporting_evidence_count"], 2)
        self.assertEqual(top_evidence["evidence_trace"]["supporting_record_ids"], ["111", "112"])
        self.assertEqual(len(top_evidence["supporting_evidence"]), 2)
        self.assertEqual(
            {record["study_accession"] for record in top_evidence["supporting_evidence"]},
            {"GCST11", "GCST12"},
        )

    def test_gene_comparison_marks_hpo_context_as_phenotype_prior(self) -> None:
        result = compare_candidate_payload({
                "task_text": "Patient phenotype matching from HPO terms.",
                "hpo_ids": ["HP:0001251"],
                "genes": ["PNKP", "SPG7"],
                "use_hpo_annotations": False,
                "download_hpo_annotations": False,
                "search_stored_research": False,
            })

        self.assertNotIn("answer", result)
        self.assertEqual(result["evidence_route"]["mode"], "single_prior")
        self.assertEqual(result["evidence_route"]["active_source_priors"], ["expert_phenotype_annotation"])
        self.assertEqual(set(result["evidence_panels"]), {"expert_phenotype_annotation"})
        self.assertNotIn("gwas_catalog_association", result["decision_evidence"])
        self.assertEqual(result["prior_fit"]["context_aligned_prior"], "expert_phenotype_annotation")
        self.assertIn("HPO IDs were supplied", result["prior_fit"]["fits"]["expert_phenotype_annotation"]["signals"])

    def test_gene_identifier_requires_context(self) -> None:
        with self.assertRaisesRegex(Exception, "requires phenotype, HPO IDs, drug, drug_class, or mechanism"):
            compare_candidate_payload({
                    "genes": ["APOB", "PCSK9"],
                    "download_hpo_annotations": False,
                    "search_stored_research": False,
                })

    def test_gwas_gene_list_can_use_source_specific_ranker(self) -> None:
        result = call_operation(
            "gwas.compare_gene_associations",
            {
                "phenotype": "LDL cholesterol",
                "genes": ["PCSK9"],
                "source_records": [_association("rs1", "LDL cholesterol", 2e-9, "rs1-A", "PCSK9", "GCST11", "111")],
            },
        )

        self.assertNotIn("answer", result)
        self.assertEqual(result["top_observed_candidate"], "PCSK9")
        self.assertEqual(result["source_prior"], "gwas_catalog_association")
        self.assertEqual(result["ranking"][0]["candidate"], "PCSK9")
        self.assertEqual(result["evidence_records"][0]["candidate"], "PCSK9")

    def test_gwas_gene_operation_defaults_to_gene_field_intent(self) -> None:
        result = call_operation(
            "gwas.compare_gene_associations",
            {
                "phenotype": "LDL cholesterol",
                "genes": ["PCSK9"],
                "source_records": [_association("rs1", "LDL cholesterol", 2e-9, "rs1-A", "PCSK9", "GCST11", "111")],
            },
        )
        self.assertEqual(result["source_prior"], "gwas_catalog_association")
        self.assertEqual(result["top_observed_candidate"], "PCSK9")

    def test_gwas_gene_evidence_refuses_causal_locus_question(self) -> None:
        result = compare_gwas_gene_evidence(
            "smoking initiation",
            ["BDNF", "METTL15"],
            task_text="Identify the causal gene within the locus for this GWAS phenotype.",
            evidence_intent="gwas_catalog_gene_field_evidence",
            source_records=[
                _association("rs1", "smoking initiation", 4e-18, "rs1-A", "METTL15", "GCST23", "123"),
            ],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "wrong_evidence_regime")
        self.assertEqual(result["coverage_state"], "out_of_scope_for_input")
        self.assertIsNone(result["top_observed_candidate"])
        self.assertEqual(result["routing_hint"]["recommended_operation"], "phenotype.retrieve_trait_gene_records")
        self.assertIn("causal-gene oracle", result["decision_policy"]["rule"])

    def test_gwas_gene_evidence_preserves_source_gene_fields(self) -> None:
        reported = _association("rs1", "breast cancer", 2e-8, "rs1-A", "CCDC170", "GCST21", "121")
        mapped = _association("rs2", "breast cancer", 1e-20, "rs2-A", "ESR1", "GCST22", "122")
        mapped["loci"][0]["authorReportedGenes"] = [{"geneName": "LOC105372440"}]

        result = compare_gwas_gene_evidence(
            "breast cancer",
            ["ESR1", "CCDC170"],
            source_records=[mapped, reported],
        )

        self.assertEqual(result["top_observed"]["candidate_id"], "CCDC170")
        self.assertEqual(result["top_observed"]["source_gene_match"]["field"], "reported_genes")
        ccdc_record = result["top_observed"]["supporting_evidence"][0]
        self.assertEqual(ccdc_record["reported_genes"], ["CCDC170"])
        self.assertEqual(ccdc_record["mapped_genes"], ["CCDC170"])
        self.assertEqual(ccdc_record["candidate_source_gene_match"]["field"], "reported_genes")
        esr1 = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "ESR1")
        self.assertEqual(esr1["source_gene_match"]["field"], "mapped_genes")
        self.assertEqual(esr1["answerability"], "adjacent_source_supported")
        self.assertEqual(esr1["best_evidence_lane"], "same_gene_or_locus")
        self.assertIn("not causal assignment", esr1["evidence_lanes"]["same_gene_or_locus"]["note"])

    def test_gene_comparison_carries_gwas_source_field_discriminators(self) -> None:
        reported = _association("rs1", "breast cancer", 2e-8, "rs1-A", "CCDC170", "GCST21", "121")
        mapped = _association("rs2", "breast cancer", 1e-20, "rs2-A", "ESR1", "GCST22", "122")
        mapped["loci"][0]["authorReportedGenes"] = [{"geneName": "LOC105372440"}]

        result = compare_candidate_payload({
                "task_text": "Use GWAS Catalog reported gene evidence for this trait.",
                "phenotype": "breast cancer",
                "genes": ["ESR1", "CCDC170"],
                "download_hpo_annotations": False,
                "search_stored_research": False,
                "gwas_source_records": [mapped, reported],
            })

        panel = result["evidence_panels"]["gwas_catalog_association"]
        self.assertEqual(panel["ranking"][0]["candidate"], "CCDC170")
        self.assertEqual(panel["ranking"][0]["evidence_discriminators"]["source_gene_match"]["field"], "reported_genes")
        self.assertEqual(
            panel["evidence_records"][0]["record"]["candidate_source_gene_match"]["field"],
            "reported_genes",
        )
        top_evidence = result["decision_evidence"]["gwas_catalog_association"]["top_observed_evidence"]
        self.assertEqual(top_evidence["evidence_discriminators"]["source_gene_match"]["field"], "reported_genes")
        esr1 = next(row for row in result["candidate_evidence_matrix"] if row["candidate"] == "ESR1")
        self.assertEqual(
            esr1["priors"]["gwas_catalog_association"]["evidence_discriminators"]["source_gene_match"]["field"],
            "mapped_genes",
        )

    def test_compare_gwas_gene_evidence_parses_current_v2_api_shapes(self) -> None:
        def fake_fetch(url: str) -> dict:
            if "/efo-traits?" in url:
                return {
                    "_embedded": {
                        "efo_traits": [
                            {"efo_id": "EFO_0004340", "efo_trait": "body mass index"},
                        ]
                    }
                }
            if "efo_id=EFO_0004340" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _v2_association("height-adjusted body mass index", "FTO", 9e-10, "2001"),
                        ]
                    }
                }
            if "mapped_gene=MC4R" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _v2_association("standing height", "MC4R", 1e-30, "2002"),
                        ]
                    }
                }
            return {"_embedded": {"associations": []}}

        result = compare_gwas_gene_evidence(
            "body mass index",
            ["FTO", "MC4R"],
            fetch_json=fake_fetch,
        )

        self.assertEqual(result["top_observed"]["candidate_id"], "FTO")
        self.assertIn("/efo-traits?", result["source"]["queried_url"])
        self.assertTrue(any("mapped_gene=MC4R" in url for url in result["source"]["queried_urls"]))
        self.assertEqual(result["association_records"][0]["traits"][0], "height-adjusted body mass index")

    def test_gwas_catalog_is_marked_as_implemented_adapter(self) -> None:
        catalog = evidence_source_catalog(source_id="gwas_catalog")
        self.assertEqual(catalog["summary"]["source_count"], 1)
        source = catalog["sources"][0]
        self.assertEqual(source["adapter_status"], "implemented_api_fetch")
        self.assertIn("gwas.compare_variant_associations", source["genomi_operations"])
        self.assertIn("gwas.compare_gene_associations", source["genomi_operations"])


if __name__ == "__main__":
    unittest.main()
