from __future__ import annotations

from unittest.mock import patch

from genomi.capabilities.pharmacogenomics.review import review_medication_interaction

from tests._pgx_review_helpers import PGxMedicationReviewTestBase


class PGxMedicationReviewCompositionTests(PGxMedicationReviewTestBase):
    def test_review_invalid_target_exposes_agent_question_alias(self) -> None:
        result = review_medication_interaction(drug="")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "invalid_target")
        self.assertEqual(result["unanswered_answer_components"][0]["component"], "medication_target")
        self.assertEqual(result["unanswered_answer_components"][0]["missing_inputs"], ["drug", "atc_code", "drugbank_id"])

    def test_review_uses_host_semantic_drug_and_gene_terms_for_retrieval(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx", "api_url": "https://api.pharmgkb.org/v1"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "clinical_annotations": [],
            "sample_follow_up_targets": {"rsids": [], "genes": [{"symbol": "CYP2C19"}]},
            "raw_calls": [{"url": "https://api.pharmgkb.org/v1/data/guidelineAnnotation", "status": 200}],
            "record_research_payloads": [{"target": {"type": "drug", "drug": "clopidogrel"}}],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb", "api_url": "https://pgx-db.org/rest-api"},
            "summary": {"pgx_record_count": 0},
            "pgx_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result) as clinpgx_lookup,
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result) as pgxdb_lookup,
        ):
            result = review_medication_interaction(
                drug="blood thinner after stent",
                semantic_context={
                    "raw_query": "blood thinner after stent",
                    "host_expansions": ["clopidogrel", "Plavix", "CYP2C19 antiplatelet response"],
                    "host_entities": [
                        {"text": "clopidogrel", "type": "drug"},
                        {"text": "CYP2C19", "type": "gene"},
                    ],
                },
            )

        self.assertEqual(clinpgx_lookup.call_args.kwargs["drug"], "clopidogrel")
        self.assertEqual(clinpgx_lookup.call_args.kwargs["gene"], "CYP2C19")
        self.assertEqual(pgxdb_lookup.call_args.kwargs["drug"], "clopidogrel")
        self.assertEqual(result["query"]["drug"], "clopidogrel")
        self.assertEqual(result["query"]["raw_drug"], "blood thinner after stent")
        accepted = {item["text"] for item in result["semantic_context"]["term_matches"]}
        self.assertIn("clopidogrel", accepted)

    def test_review_does_not_override_exact_drug_with_host_guess(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0},
            "pgx_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result) as clinpgx_lookup,
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
        ):
            result = review_medication_interaction(
                drug="warfarin",
                semantic_context={
                    "raw_query": "warfarin",
                    "host_expansions": ["clopidogrel"],
                    "host_entities": [{"text": "clopidogrel", "type": "drug"}],
                },
            )

        self.assertEqual(clinpgx_lookup.call_args.kwargs["drug"], "warfarin")
        self.assertEqual(result["query"]["drug"], "warfarin")

    def test_review_composes_public_pgx_and_sample_lookup(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx", "api_url": "https://api.pharmgkb.org/v1"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 1, "label_annotation_count": 1},
            "clinical_annotations": [
                {
                    "id": 1043858794,
                    "accession_id": "PA166134797",
                    "evidence_class": "clinical_annotation",
                    "display_name": "CYP2C19*2; clopidogrel",
                    "level_of_evidence": "1A",
                    "summary": "CYP2C19 no-function alleles affect clopidogrel response.",
                    "related_genes": [{"id": "PA124", "symbol": "CYP2C19", "name": "cytochrome P450 family 2 subfamily C member 19"}],
                    "haplotypes": [{"id": f"PA{i}", "symbol": f"CYP2C19*{i}"} for i in range(1, 20)],
                    "history": [{"description": "large nested source metadata that should stay out of the compact review"}],
                }
            ],
            "sample_follow_up_targets": {"rsids": ["rs4244285"], "genes": [{"symbol": "CYP2C19"}]},
            "clinical_verification": {
                "requires_before_personal_actionability": ["clinical context such as indication and clinician review"]
            },
            "raw_calls": [{"url": "https://api.pharmgkb.org/v1/data/guidelineAnnotation", "status": 200}],
            "record_research_payloads": [{"target": {"type": "drug", "drug": "clopidogrel"}}],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb", "api_url": "https://pgx-db.org/rest-api"},
            "summary": {"pgx_record_count": 1},
            "pgx_records": [
                {
                    "rsid": "rs4244285",
                    "variant_or_haplotype": "rs4244285",
                    "drug": "clopidogrel",
                    "alleles": "AA + AG",
                    "direction_of_effect": "decreased",
                    "pd_pk_terms": "response to",
                    "phenotype_category": "Efficacy",
                    "significance": "yes",
                    "sentence": "Genotypes AA + AG are associated with decreased response to clopidogrel.",
                    "pmid": "123",
                    "atc_code": "B01AC04",
                }
            ],
            "raw_calls": [{"url": "https://pgx-db.org/rest-api/atc/pgx/B01AC04/", "status": 200}],
            "record_research_payloads": [{"target": {"type": "topic", "topic": "rs4244285 clopidogrel"}}],
        }
        variant_result = {
            "sample_context": {"count": 1, "matches": [{"rsid": "rs4244285", "genotype": "AG"}]},
            "support_context": {"genotype_support": [{"support_status": "supported"}]},
        }
        star_result = {
            "schema": "genomi-pgx-star-allele-call-v1",
            "ok": True,
            "status": "completed",
            "gene": "CYP2C19",
            "marker_calls": [{"evidence_status": "observed_effect_allele"}],
            "called_star_alleles": [{"star_allele": "*2"}],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result) as clinpgx_lookup,
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result) as pgxdb_lookup,
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant", return_value=variant_result) as variant_lookup,
            patch("genomi.capabilities.pharmacogenomics.review.pgx_star.call_star_alleles", return_value=star_result) as star_lookup,
        ):
            result = review_medication_interaction(drug="clopidogrel", gene="CYP2C19", has_active_genome_index_context=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sample_evidence"]["rsid_targets"], ["rs4244285"])
        self.assertEqual(result["sample_evidence"]["sample_match_count"], 1)
        self.assertEqual(result["sample_evidence"]["star_gene_targets"], ["CYP2C19"])
        self.assertEqual(result["sample_evidence"]["star_allele_call_count"], 1)
        self.assertEqual(result["sample_evidence"]["star_marker_match_count"], 1)
        self.assertEqual(result["public_evidence"]["source_availability"]["status"], "source_evidence_available")
        self.assertEqual(result["answer_support"]["status"], "source_and_sample_evidence_present")
        self.assertEqual(result["answer_support"]["technical_sample_support"]["status"], "ready")
        self.assertEqual(result["answer_support"]["matched_variant_associations"][0]["match_status"], "reported_genotype_matches_sample")
        self.assertEqual(result["answer_support"]["matched_variant_associations"][0]["sample"]["canonical_genotype"], "AG")
        self.assertEqual(result["answer_support"]["star_diplotype_summaries"][0]["gene"], "CYP2C19")
        self.assertTrue(result["answer_support"]["source_recommendation_summaries"])
        view = result["evidence_view"]
        self.assertEqual(view["schema"], "genomi-candidate-evidence-view-v1")
        self.assertEqual(view["task_profile"]["profile_id"], "pgx_medication_review")
        self.assertEqual(view["coverage"]["candidate_count"], 1)
        self.assertEqual(view["candidate_matrix"], result["candidate_matrix"])
        self.assertEqual(view["top_observed"]["answerability"], "direct_source_supported")
        self.assertTrue(view["agent_decision_required"])
        self.assertEqual(result["evidence_matrix"]["schema"], "genomi-pgx-evidence-matrix-v1")
        self.assertGreaterEqual(result["evidence_matrix"]["role_counts"]["medication_source_evidence"], 2)
        self.assertGreaterEqual(result["evidence_matrix"]["role_counts"]["sample_pgx_evidence"], 2)
        matrix_traceability = result["evidence_matrix"]["traceability"]
        self.assertEqual(matrix_traceability["schema"], "genomi-pgx-evidence-matrix-traceability-v1")
        self.assertTrue(matrix_traceability["all_items_have_stable_ids"])
        self.assertTrue(matrix_traceability["all_items_have_verification"])
        self.assertGreaterEqual(matrix_traceability["source_traceable_item_count"], 2)
        self.assertIn("clinpgx", matrix_traceability["source_ids"])
        self.assertIn("pgxdb", matrix_traceability["source_ids"])
        self.assertIn("https://pgx-db.org/rest-api/atc/pgx/B01AC04/", matrix_traceability["source_url_counts"])
        self.assertIn("123", matrix_traceability["pmids"])
        self.assertGreaterEqual(matrix_traceability["unique_source_url_count"], 2)
        self.assertGreaterEqual(matrix_traceability["local_sample_item_count"], 2)
        self.assertGreaterEqual(matrix_traceability["observed_marker_item_count"], 1)
        self.assertEqual(matrix_traceability["marker_definition_item_count"], 0)
        self.assertEqual(matrix_traceability["item_count"], len(result["evidence_matrix"]["items"]))
        self.assertEqual(
            result["traceability"]["evidence_matrix_traceability"]["item_ids"],
            matrix_traceability["item_ids"],
        )
        self.assertTrue(all(item["evidence_id"].startswith("pgxev_") for item in result["evidence_matrix"]["items"]))
        pgxdb_matrix_item = next(
            item
            for item in result["evidence_matrix"]["items"]
            if item["evidence_class"] == "pgxdb_pharmacogenomic_association"
        )
        self.assertEqual(pgxdb_matrix_item["target"]["rsid"], "rs4244285")
        self.assertEqual(pgxdb_matrix_item["finding"]["direction_of_effect"], "decreased")
        self.assertEqual(pgxdb_matrix_item["citations"][0]["id"], "123")
        self.assertEqual(pgxdb_matrix_item["verification"]["status"], "source_traceable")
        self.assertTrue(any(item["evidence_class"] == "active_genome_index_variant_match" for item in result["evidence_matrix"]["items"]))
        star_matrix_item = next(
            item
            for item in result["evidence_matrix"]["items"]
            if item["evidence_class"] == "pgx_star_allele_marker_call"
        )
        self.assertEqual(star_matrix_item["verification"]["status"], "observed_marker_evidence")
        self.assertEqual(result["evidence_state"]["schema"], "genomi-pgx-evidence-state-v1")
        self.assertTrue(result["evidence_state"]["has_public_pgx_evidence"])
        self.assertTrue(result["evidence_state"]["has_sample_evidence"])
        self.assertTrue(result["evidence_state"]["has_vcf_technical_support"])
        self.assertEqual(result["pgx_evidence_scope"]["schema"], "genomi-pgx-evidence-scope-v1")
        self.assertEqual(result["pgx_evidence_scope"]["model"], "bounded_target_scoped_evidence")
        self.assertEqual(result["pgx_evidence_scope"]["scope"]["selected_public_targets"]["drug"], "clopidogrel")
        self.assertTrue(result["pgx_evidence_scope"]["scope"]["sample_context_requested"])
        self.assertTrue(result["pgx_evidence_scope"]["traceability"]["all_items_have_stable_ids"])
        self.assertEqual(
            result["traceability"]["pgx_evidence_scope"]["traceability"]["verification_status_counts"],
            result["evidence_matrix"]["traceability"]["verification_status_counts"],
        )
        self.assertNotIn("raw_calls", result["public_evidence"]["clinpgx"])
        self.assertNotIn("record_research_payloads", result["public_evidence"]["clinpgx"])
        self.assertNotIn("history", result["public_evidence"]["clinpgx"]["clinical_annotations"][0])
        self.assertLessEqual(len(result["public_evidence"]["clinpgx"]["clinical_annotations"][0]["haplotypes"]), 12)
        self.assertEqual(result["public_evidence"]["clinpgx"]["clinical_annotations"][0]["related_genes"][0]["symbol"], "CYP2C19")
        self.assertEqual(result["interpretation_readiness"]["personal_statement_support"], "source_and_sample_evidence_present")
        self.assertFalse(result["interpretation_readiness"]["supported_star_marker_coverage"])
        self.assertEqual(result["interpretation_readiness"]["status"], "informational_evidence_review_requires_clinical_confirmation")
        self.assertEqual(result["evidence_components"]["schema"], "genomi-pgx-evidence-components-v1")
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertEqual(components["public_pgx_evidence"]["state"], "present")
        self.assertEqual(components["sample_variant_or_marker_evidence"]["state"], "present")
        self.assertEqual(components["technical_sample_support"]["state"], "present")
        self.assertEqual(components["broad_pgx_call_artifact"]["state"], "available")
        self.assertEqual(components["clinical_context"]["state"], "partial")
        self.assertIn("indication", components["clinical_context"]["evidence"]["missing"])
        unanswered = {item["component"]: item for item in result["unanswered_answer_components"]}
        self.assertEqual(unanswered["clinical_context"]["component"], "clinical_context")
        self.assertIn("indication", unanswered["clinical_context"]["missing_inputs"])
        self.assertEqual(result["target_inventory"]["rsid_targets"], ["rs4244285"])
        self.assertEqual(result["target_inventory"]["pharmacogene_targets"], ["CYP2C19"])
        self.assertEqual(result["target_inventory"]["implemented_marker_definition_genes"], ["CYP2C19"])
        self.assertTrue(result["target_inventory"]["pharmcat_context"]["active_genome_index_context_available"])
        self.assertEqual(result["traceability"]["record_research_payload_count"], 2)
        self.assertEqual(len(result["traceability"]["record_research_payload_summaries"]), 2)
        self.assertNotIn("record_research_payloads", result["traceability"])
        clinpgx_lookup.assert_called_once()
        pgxdb_lookup.assert_called_once()
        variant_lookup.assert_called_once()
        star_lookup.assert_called_once()

    def test_review_reports_missing_sample_target(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": [{"symbol": "CYP2D6"}]},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0},
            "pgx_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant") as variant_lookup,
        ):
            result = review_medication_interaction(drug="codeine", gene="CYP2D6", include_active_genome_index=True)

        self.assertEqual(result["interpretation_readiness"]["personal_statement_support"], "needs_more_evidence")
        self.assertTrue(result["evidence_state"]["has_public_pgx_evidence"])
        self.assertFalse(result["evidence_state"]["has_sample_evidence"])
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertEqual(components["sample_variant_or_marker_evidence"]["state"], "target_selected_without_sample_evidence")
        self.assertEqual(components["technical_sample_support"]["state"], "absent")
        self.assertEqual(components["broad_pgx_call_artifact"]["state"], "absent")
        self.assertEqual(components["specialized_pgx_call_evidence"]["state"], "absent")
        unanswered = {item["component"]: item for item in result["unanswered_answer_components"]}
        self.assertIn("sample_variant_or_marker_evidence", unanswered)
        self.assertIn("specialized_pgx_call_evidence", unanswered)
        self.assertEqual(result["target_inventory"]["outside_call_genes"], ["CYP2D6"])
        self.assertFalse(result["target_inventory"]["pharmcat_context"]["active_genome_index_context_available"])
        self.assertIn(
            "supported pharmacogene star-allele, diplotype, phenotype, or specialized PGx caller evidence",
            result["interpretation_readiness"]["requires_before_personal_actionability"],
        )
        variant_lookup.assert_not_called()

    def test_public_only_review_does_not_ask_for_sample_or_clinical_context(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 0, "clinical_annotation_count": 1, "label_annotation_count": 0},
            "clinical_annotations": [
                {
                    "id": 1444704321,
                    "evidence_class": "clinical_annotation",
                    "name": "rs1061622 and infliximab",
                    "summary": "TNFRSF1B rs1061622 has public drug-response evidence for infliximab.",
                    "source_url": "https://api.pharmgkb.org/v1/data/clinicalAnnotation/1444704321",
                    "related_genes": [{"symbol": "TNFRSF1B"}],
                    "related_chemicals": [{"name": "infliximab"}],
                }
            ],
            "sample_follow_up_targets": {"rsids": ["rs1061622"], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": ["matching sample evidence"]},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 1, "medication_scoped_gene_drug_record_count": 0},
            "pgx_records": [
                {
                    "drug": "Infliximab",
                    "drugbank_id": "DB00065",
                    "atc_code": "L04AB02",
                    "rsid": "rs1061622",
                    "variant_or_haplotype": "rs1061622",
                    "sentence": "Allele G is associated with decreased response to infliximab.",
                    "pmid": "18565259",
                }
            ],
            "raw_calls": [],
            "record_research_payloads": [],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant") as variant_lookup,
        ):
            result = review_medication_interaction(
                drug="Infliximab",
                rsid="rs1061622",
            )

        self.assertEqual(result["answer_support"]["status"], "public_source_evidence_present")
        self.assertEqual(result["interpretation_readiness"]["personal_statement_support"], "public_source_evidence_only")
        self.assertFalse(result["sample_evidence"]["sample_context_requested"])
        self.assertFalse(result["evidence_state"]["sample_context_requested"])
        self.assertEqual(result["pgx_evidence_scope"]["status"], "bounded_evidence_ready")
        self.assertFalse(result["pgx_evidence_scope"]["scope"]["sample_context_requested"])
        self.assertFalse(result["pgx_evidence_scope"]["scope"]["clinical_context_requested"])
        self.assertEqual(result["pgx_evidence_scope"]["unresolved_components"], [])
        self.assertEqual(result["unanswered_answer_components"], [])
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertEqual(components["sample_target_selection"]["state"], "not_requested")
        self.assertEqual(components["sample_variant_or_marker_evidence"]["state"], "not_requested")
        self.assertEqual(components["technical_sample_support"]["state"], "not_requested")
        self.assertEqual(components["broad_pgx_call_artifact"]["state"], "not_requested")
        self.assertEqual(components["clinical_context"]["state"], "partial")
        self.assertNotIn("matching sample evidence", result["interpretation_readiness"]["requires_before_personal_actionability"])
        variant_lookup.assert_not_called()

    def test_evidence_ids_are_stable_across_source_access_timestamps(self) -> None:
        def clinpgx_result(accessed_at: str) -> dict[str, object]:
            return {
                "source": {"source_id": "clinpgx", "api_url": "https://api.pharmgkb.org/v1", "accessed_at": accessed_at},
                "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
                "guideline_annotations": [
                    {
                        "id": 123,
                        "evidence_class": "guideline_annotation",
                        "name": "Clopidogrel and CYP2C19",
                        "guideline_source": "CPIC",
                        "summary": "CYP2C19 alleles affect clopidogrel response.",
                        "source_url": "https://api.pharmgkb.org/v1/data/guidelineAnnotation/123",
                        "related_genes": [{"symbol": "CYP2C19"}],
                    }
                ],
                "sample_follow_up_targets": {"rsids": [], "genes": []},
                "clinical_verification": {"requires_before_personal_actionability": []},
                "raw_calls": [],
                "record_research_payloads": [],
            }

        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0, "gene_drug_record_count": 0, "variant_context_record_count": 0},
            "pgx_records": [],
            "gene_drug_records": [],
            "variant_context_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }

        results = []
        for accessed_at in ("2026-05-14T00:00:00Z", "2026-05-15T00:00:00Z"):
            with (
                patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result(accessed_at)),
                patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            ):
                results.append(
                    review_medication_interaction(
                        drug="clopidogrel",
                        gene="CYP2C19",
                        include_stored_research=False,
                    )
                )

        first_ids = [item["evidence_id"] for item in results[0]["evidence_matrix"]["items"]]
        second_ids = [item["evidence_id"] for item in results[1]["evidence_matrix"]["items"]]
        self.assertEqual(first_ids, second_ids)
        self.assertTrue(results[0]["evidence_matrix"]["traceability"]["all_items_have_stable_ids"])
        self.assertTrue(results[1]["evidence_matrix"]["traceability"]["all_items_have_stable_ids"])

    def test_review_does_not_treat_star_definition_only_as_sample_evidence(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": [{"symbol": "CYP2C19"}]},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0},
            "pgx_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        star_result = {
            "schema": "genomi-pgx-star-allele-call-v1",
            "ok": True,
            "status": "completed",
            "gene": "CYP2C19",
            "marker_calls": [{"evidence_status": "not_observed_in_active_genome_index"}],
            "called_star_alleles": [],
            "diplotype": {
                "marker_support_status": "marker_evidence_only",
                "possible_diplotype": None,
                "predicted_phenotype": None,
            },
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgx_star.call_star_alleles", return_value=star_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", gene="CYP2C19", include_active_genome_index=True)

        self.assertEqual(result["sample_evidence"]["star_allele_call_count"], 1)
        self.assertEqual(result["sample_evidence"]["star_marker_match_count"], 0)
        self.assertFalse(
            any(item["evidence_class"] == "pgx_star_allele_marker_call" for item in result["evidence_matrix"]["items"])
        )
        matrix_traceability = result["evidence_matrix"]["traceability"]
        self.assertEqual(matrix_traceability["local_sample_item_count"], 0)
        self.assertEqual(matrix_traceability["observed_marker_item_count"], 0)
        self.assertEqual(result["answer_support"]["status"], "public_source_evidence_present")

    def test_review_does_not_treat_no_context_star_markers_as_sample_evidence(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": [{"symbol": "CYP2C19"}]},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0},
            "pgx_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        star_result = {
            "schema": "genomi-pgx-star-allele-call-v1",
            "ok": False,
            "status": "no_sample_context",
            "gene": "CYP2C19",
            "marker_calls": [{"evidence_status": "no_active_genome_index_selected"}],
            "called_star_alleles": [],
            "diplotype": {"marker_support_status": "marker_evidence_only"},
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgx_star.call_star_alleles", return_value=star_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", gene="CYP2C19", include_active_genome_index=True)

        self.assertEqual(result["sample_evidence"]["star_marker_match_count"], 0)
        self.assertFalse(result["interpretation_readiness"]["supported_star_marker_coverage"])
        self.assertFalse(any(item["evidence_class"] == "pgx_star_allele_marker_call" for item in result["evidence_matrix"]["items"]))
        self.assertEqual(result["answer_support"]["status"], "public_source_evidence_present")



if __name__ == "__main__":
    import unittest

    unittest.main()
