from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genomi.capabilities.phenotype.risk import prepare_risk_investigation
from genomi.evidence import (
    import_clinvar_vcf,
    match_clinvar_variants,
    record_research_findings,
)
from genomi.evidence.sources import evidence_source_catalog

DATA_DIR = Path(__file__).parent / "data"
TINY_VCF = DATA_DIR / "tiny.gvcf.vcf"
TINY_CLINVAR = DATA_DIR / "tiny.clinvar.vcf"


class RiskInvestigationTests(unittest.TestCase):
    def test_public_cancer_question_plans_genecards_review_without_sample_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            record_research_findings(
                db,
                {
                    "target": {"type": "gene", "gene": "BRCA1"},
                    "source": {
                        "title": "Example Hereditary Cancer Source",
                        "url": "https://example.test/brca1",
                        "accessed_at": "2026-05-16T00:00:00+00:00",
                    },
                    "finding": {
                        "type": "hereditary_cancer_context",
                        "text": "BRCA1 is used here as a source-backed hereditary cancer review target.",
                    },
                },
            )

            result = prepare_risk_investigation(
                db,
                question="BRCA1 hereditary breast cancer risk",
                gene="BRCA1",
                investigation_type="cancer_risk",
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["context_scope"], "public_only")
        self.assertEqual(result["target"]["investigation_type"], "cancer_risk")
        self.assertEqual(result["active_genome_index_evidence"]["status"], "not_selected")
        source_ids = [source["source_id"] for source in result["source_plan"]["source_order"]]
        self.assertIn("genecards", source_ids)
        self.assertIn("malacards", source_ids)
        self.assertIn("nci_cancer_genetics", source_ids)
        self.assertIn("cosmic_cancer_gene_census", source_ids)
        self.assertIn("BRCA1", result["source_plan"]["safe_external_targets"]["genes"])
        self.assertEqual(result["evidence_view"]["task_profile"]["profile_id"], "rare_disease_cancer_risk_investigation")
        self.assertEqual(result["evidence_view"]["coverage_state"], "data_returned")
        self.assertTrue(result["evidence_view"]["agent_decision_required"])
        self.assertEqual(result["top_observed_candidate"], "gene:BRCA1")
        self.assertEqual(result["candidate_matrix"][0]["candidate_id"], "gene:BRCA1")
        self.assertEqual(result["candidate_matrix"][0]["best_evidence_lane"], "direct_source_match")

    def test_active_index_rare_disease_investigation_summarizes_matching_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            match_clinvar_variants(TINY_VCF, db, matches)

            result = prepare_risk_investigation(
                db,
                question="rare disease review for GENE2",
                gene="GENE2",
                matches=matches,
                investigation_type="rare_disease",
            )

        self.assertEqual(result["context_scope"], "active_genome_index_selected")
        self.assertEqual(result["active_genome_index_evidence"]["status"], "available")
        self.assertEqual(result["active_genome_index_evidence"]["summary"]["candidate_count"], 1)
        self.assertEqual(result["active_genome_index_evidence"]["result_state"], "candidate_inventory_hits_present")
        candidate = result["active_genome_index_evidence"]["candidate_summaries"][0]
        self.assertEqual(candidate["candidate_id"], "variant:1-10257-A-C")
        self.assertIn("GENE2", candidate["genes"])
        self.assertEqual(candidate["target_match_status"], "requested_gene_match")
        scores = [row["score"] for row in result["candidate_matrix"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        review_rows = [
            row
            for row in result["candidate_matrix"]
            if row["candidate_type"] == "clinvar_review_group"
        ]
        self.assertTrue(
            any(row["supporting_evidence"][0]["group_type"] == "uncertain_or_conflicting" for row in review_rows)
        )
        self.assertTrue(any(row["candidate_id"] == "gene:GENE2" for row in result["candidate_matrix"]))
        self.assertTrue(
            any(row["candidate_id"] == "variant:1-10257-A-C" for row in result["candidate_matrix"])
        )
        self.assertTrue(result["evidence_view"]["agent_decision_required"])

    def test_auto_active_index_review_resolves_to_observed_condition_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            match_clinvar_variants(TINY_VCF, db, matches)

            result = prepare_risk_investigation(
                db,
                matches=matches,
                investigation_type="auto",
            )

        self.assertEqual(result["target"]["investigation_type"], "observed_condition_review")
        self.assertEqual(result["source_plan"]["investigation_type"], "observed_condition_review")
        self.assertEqual(result["evidence_envelope"]["query_scope"]["investigation_type"], "observed_condition_review")

    def test_missing_active_index_matches_reports_materialization_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            missing_matches = Path(tmp) / "missing.matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")

            result = prepare_risk_investigation(
                db,
                question="rare disease review for GENE2",
                gene="GENE2",
                matches=missing_matches,
                investigation_type="rare_disease",
            )

        self.assertEqual(result["status"], "materialization_incomplete")
        self.assertEqual(result["context_scope"], "active_genome_index_selected")
        self.assertEqual(result["coverage_state"], "materialization_incomplete")
        self.assertEqual(result["active_genome_index_evidence"]["status"], "materialization_incomplete")
        self.assertEqual(
            result["active_genome_index_evidence"]["result_state"],
            "clinvar_candidate_inventory_not_materialized",
        )
        self.assertEqual(result["stored_research"]["status"], "not_searched")
        self.assertEqual(result["next_actions"][0]["operation"], "clinvar.scan_candidates")
        self.assertEqual(result["next_actions"][0]["materializes"], "clinvar_candidate_inventory")
        env = result["evidence_envelope"]
        self.assertEqual(env["finding_state"], "materialization_incomplete")
        self.assertEqual(env["answer_readiness"], "needs_materialization")
        self.assertTrue(env["personal_context"]["uses_personal_dna"])
        self.assertEqual(env["personal_context"]["source"], "clinvar_candidate_inventory")
        self.assertIn("clinvar_candidate_inventory", env["coverage"]["unavailable_sources"])
        self.assertEqual(env["coverage"]["libraries"][0]["library"], "clinvar-grch38")
        self.assertEqual(env["coverage"]["libraries"][0]["state"], "not_materialized")
        self.assertIn("materialization_incomplete:wait_or_poll_background_job", env["guidance"])
        self.assertNotIn(str(missing_matches), str(result))

    def test_missing_active_index_matches_reports_build_specific_clinvar_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            missing_matches = Path(tmp) / "missing.matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")

            result = prepare_risk_investigation(
                db,
                question="rare disease review for GENE2",
                gene="GENE2",
                matches=missing_matches,
                genome_build="GRCh37",
                investigation_type="rare_disease",
            )

        active = result["active_genome_index_evidence"]
        env = result["evidence_envelope"]
        self.assertEqual(active["materialization"]["library"], "clinvar-grch37")
        self.assertEqual(active["materialization"]["genome_build"], "GRCh37")
        self.assertEqual(env["coverage"]["libraries"][0]["library"], "clinvar-grch37")

    def test_carrier_review_ranks_carrier_relevance_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            matches.write_text(
                '{"match_provenance":{"match_basis":"exact_allele"},'
                '"sample_variant":{"chrom":"14","pos":94847262,"ref":"T","alt":"A","filter":"PASS",'
                '"genotype":"0/1","depth":"35","genotype_quality":"60"},'
                '"clinvar":{"clinical_significance":"Pathogenic/Pathogenic,_low_penetrance|other",'
                '"review_status":"criteria_provided,_multiple_submitters,_no_conflicts","gene_info":"SERPINA1:5265",'
                '"conditions":"Alpha-1-antitrypsin_deficiency|PI_S","clinvar_id":"17969"}}\n',
                encoding="utf-8",
            )

            result = prepare_risk_investigation(
                db,
                question="carrier relevance review",
                matches=matches,
                investigation_type="carrier_review",
            )

        active = result["active_genome_index_evidence"]
        self.assertEqual(result["target"]["investigation_type"], "carrier_review")
        self.assertEqual(active["candidate_review_groups"]["group_count"], 1)
        group = active["candidate_review_groups"]["groups"][0]
        self.assertEqual(group["group_type"], "carrier_relevance")
        self.assertEqual(group["gene"], "SERPINA1")
        self.assertEqual(group["zygosity_counts"], [["heterozygous", 1]])
        self.assertEqual(result["candidate_matrix"][0]["candidate_type"], "clinvar_review_group")
        self.assertEqual(result["candidate_matrix"][0]["supporting_evidence"][0]["group_type"], "carrier_relevance")
        env = result["evidence_envelope"]
        self.assertEqual(env["answer_readiness"], "needs_clinical_confirmation")
        missing_gates = {item["gate"] for item in env["observations"]["missing_interpretation_gates"]}
        self.assertIn("inheritance", missing_gates)
        self.assertIn("phase", missing_gates)

    def test_observed_condition_review_keeps_group_types_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            matches.write_text(
                "\n".join(
                    [
                        '{"match_provenance":{"match_basis":"exact_allele"},'
                        '"sample_variant":{"chrom":"1","pos":10250,"ref":"A","alt":"C","filter":"PASS",'
                        '"genotype":"0/1","depth":"20","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"Conflicting_classifications_of_pathogenicity|protective",'
                        '"review_status":"criteria_provided,_conflicting_classifications","gene_info":"GENE1:1",'
                        '"conditions":"condition","clinvar_id":"123"}}',
                        '{"match_provenance":{"match_basis":"exact_allele"},'
                        '"sample_variant":{"chrom":"2","pos":20250,"ref":"G","alt":"T","filter":"PASS",'
                        '"genotype":"0/1","depth":"22","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"Benign","review_status":"criteria_provided,_single_submitter",'
                        '"gene_info":"GENE2:2","conditions":"condition","clinvar_id":"456"}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = prepare_risk_investigation(
                db,
                question="observed ClinVar condition review",
                matches=matches,
                investigation_type="observed_condition_review",
            )

        group_types = {
            group["group_type"]
            for group in result["active_genome_index_evidence"]["candidate_review_groups"]["groups"]
        }
        self.assertIn("uncertain_or_conflicting", group_types)
        self.assertIn("risk_association", group_types)
        self.assertIn("benign_or_counterevidence", group_types)
        self.assertIn("quality_or_population_context", group_types)
        self.assertNotIn("drug_response", group_types)
        self.assertEqual(result["candidate_matrix"][0]["candidate_type"], "clinvar_review_group")

    def test_review_group_limit_is_applied_after_evidence_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            matches.write_text(
                "\n".join(
                    [
                        '{"match_provenance":{"match_basis":"exact_allele"},'
                        '"sample_variant":{"chrom":"1","pos":101,"ref":"A","alt":"C","filter":"PASS",'
                        '"genotype":"0/1","depth":"20","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"Benign","review_status":"criteria_provided,_single_submitter",'
                        '"gene_info":"GENE_LOW:1","conditions":"condition","clinvar_id":"low"}}',
                        '{"match_provenance":{"match_basis":"exact_allele"},'
                        '"sample_variant":{"chrom":"2","pos":202,"ref":"G","alt":"T","filter":"PASS",'
                        '"genotype":"1/1","depth":"20","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"Pathogenic","review_status":"criteria_provided,_multiple_submitters,_no_conflicts",'
                        '"gene_info":"GENE_HIGH:2","conditions":"condition","clinvar_id":"high"}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = prepare_risk_investigation(
                db,
                matches=matches,
                investigation_type="observed_condition_review",
                limit=1,
            )

        groups = result["active_genome_index_evidence"]["candidate_review_groups"]["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["gene"], "GENE_HIGH")

    def test_broad_active_index_zero_candidates_emits_scoped_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            matches.write_text("", encoding="utf-8")

            result = prepare_risk_investigation(
                db,
                question="any inherited genetic disease or cancer-risk findings worth worrying about?",
                matches=matches,
                investigation_type="cancer_risk",
            )

        active = result["active_genome_index_evidence"]
        self.assertEqual(active["status"], "available")
        self.assertEqual(active["summary"]["candidate_count"], 0)
        self.assertEqual(active["result_state"], "no_candidate_inventory_hits_in_selected_evidence_groups")
        # The unified envelope encodes the scoped-result and disallowed-negative.
        env = result["evidence_envelope"]
        self.assertEqual(env["operation"], "phenotype.plan_risk_investigation")
        self.assertEqual(env["finding_state"], "not_observed_in_consulted_scope")
        self.assertEqual(env["answer_readiness"], "scoped_answer_only")
        self.assertFalse(env["negative_inference"]["allowed"])
        self.assertIn("library_coverage", env["negative_inference"]["requires"])
        self.assertTrue(env["personal_context"]["uses_personal_dna"])
        self.assertEqual(env["personal_context"]["source"], "clinvar_candidate_inventory")
        # Guidance is centrally rendered.
        self.assertIn("not_observed_in_consulted_scope:do_not_imply_clinical_negative", env["guidance"])
        self.assertIn("negative_inference_disallowed:do_not_state_clinical_negative", env["guidance"])

    def test_source_catalog_includes_gene_cards_suite_for_risk_review(self) -> None:
        catalog = evidence_source_catalog(target_type="gene")
        source_ids = {source["source_id"] for source in catalog["sources"]}

        self.assertIn("genecards", source_ids)
        self.assertIn("malacards", source_ids)
        genecards = next(source for source in catalog["sources"] if source["source_id"] == "genecards")
        self.assertEqual(genecards["agent_contract"]["query_mode"], "focused_source_review")
        self.assertIn("phenotype.plan_risk_investigation", genecards["agent_contract"]["available_operations"])


if __name__ == "__main__":
    unittest.main()
