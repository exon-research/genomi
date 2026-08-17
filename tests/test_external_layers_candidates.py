from __future__ import annotations

import json
import tempfile
from pathlib import Path

from genomi.capabilities.clinvar.static_annotation import (
    run_static_genotype_support,
)
from genomi.evidence import (
    extract_clinvar_candidates,
    import_clinvar_vcf,
    import_population_vcf,
    match_clinvar_variants,
    record_research_findings,
)
from genomi.evidence.store.candidate_inventory_payload import (
    DEFAULT_RETURNED_CANDIDATE_LIMIT,
    MAX_RETURNED_CANDIDATE_LIMIT,
)
from genomi.operations.registry import defaults_applied_for_call
from tests.support.capabilities.external_layers import (
    TINY_CLINVAR,
    TINY_POPULATION,
    TINY_VCF,
    EvidenceImportTestBase,
)


class CandidateInventoryTests(EvidenceImportTestBase):
    def test_candidate_inventory_exposes_decision_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            output = Path(tmp) / "candidates.json"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            import_population_vcf(TINY_POPULATION, db, source="tiny_pop", source_version="pop_fixture")
            match_clinvar_variants(TINY_VCF, db, matches)

            result = extract_clinvar_candidates(matches, db, output)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["total_match_records"], 2)
            self.assertEqual(result["summary"]["selected_candidate_variants"], 2)
            view = result["evidence_view"]
            self.assertEqual(view["task_profile"]["profile_id"], "clinvar_candidate_scan")
            self.assertEqual(view["coverage_state"], "data_returned")
            self.assertEqual(view["coverage"]["candidate_count"], len(view["candidate_matrix"]))
            self.assertEqual(result["top_observed_candidate"], view["candidate_matrix"][0]["candidate_id"])
            self.assertEqual(result["evidence_envelope"]["personal_context"]["source"], "clinvar_matches")
            self.assertTrue(view["agent_decision_required"])
            self.assertEqual(result["candidate_inventory"][0]["variant"]["pos"], 10257)
            self.assertIn("clinvar_vus", result["candidate_inventory"][0]["tags"])
            self.assertIn("low_review_status", result["candidate_inventory"][0]["tags"])
            self.assertIn("population_evidence_present", result["candidate_inventory"][0]["tags"])
            self.assertIn("population_frequency_common", result["candidate_inventory"][0]["tags"])
            self.assertIn("clinvar_vus", result["candidate_inventory"][0]["buckets"])
            self.assertIn("population_common_context", result["candidate_inventory"][0]["buckets"])
            self.assertIn("bucket_counts", result["summary"])
            self.assertEqual(result["candidate_buckets"][0]["bucket"], "clinvar_vus")
            self.assertEqual(result["candidate_inventory"][0]["population_evidence"]["status"], "present")
            self.assertEqual(result["candidate_inventory"][0]["population_evidence"]["max_global_allele_frequency"], 0.05)
            self.assertEqual(
                result["candidate_inventory"][0]["population_evidence"]["freshness"]["status"],
                "available",
            )
            self.assertEqual(result["candidate_inventory"][0]["genotype_support"]["support_status"], "not_checked")
            self.assertTrue(
                any(
                    "genotype_support status not_checked" in point
                    for point in result["candidate_inventory"][0]["decision_points"]
                )
            )
            self.assertTrue(Path(result["manifest_path"]).exists())
            review_groups = result["candidate_review_groups"]
            self.assertEqual(review_groups["policy_id"], "clinvar_candidate_review_groups_v1")
            self.assertEqual(review_groups["group_count"], 4)
            self.assertIn(["uncertain_or_conflicting", 1], review_groups["group_counts_by_type"])
            self.assertIn(["benign_or_counterevidence", 1], review_groups["group_counts_by_type"])
            self.assertTrue(
                any(
                    group["group_type"] == "uncertain_or_conflicting"
                    and group["candidate_ids"] == ["variant:1-10257-A-C"]
                    for group in review_groups["groups"]
                )
            )

            cached = extract_clinvar_candidates(matches, db, output)
            self.assertEqual(cached["status"], "cached")
            self.assertEqual(cached["summary"]["selected_candidate_variants"], 2)
            self.assertEqual(cached["evidence_view"]["task_profile"]["profile_id"], "clinvar_candidate_scan")

            record_research_findings(
                db,
                {
                    "findings": [
                        {
                            "target": {"type": "gene", "gene": "GENE1"},
                            "source": {
                                "title": "Example Gene Source",
                                "url": "https://example.test/candidate-cache-gene",
                                "accessed_at": "2026-05-05T00:00:00+00:00",
                            },
                            "finding": {"text": "Short research text.", "summary": "Research summary."},
                        }
                    ]
                },
            )
            cached_after_record = extract_clinvar_candidates(matches, db, output)
            self.assertEqual(cached_after_record["status"], "cached")

    def test_candidate_inventory_uses_stored_genotype_support_as_source_of_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            output = Path(tmp) / "candidates.json"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            match_clinvar_variants(TINY_VCF, db, matches)
            run_static_genotype_support(
                TINY_VCF,
                "1",
                10257,
                "A",
                "C",
                evidence_db=db,
                agi_path=Path(tmp) / "active-genome-index.sqlite",
                min_depth=100,
            )

            result = extract_clinvar_candidates(matches, db, output)
            candidate = result["candidate_inventory"][0]

            self.assertEqual(candidate["genotype_support"]["source"], "private_db")
            self.assertEqual(candidate["genotype_support"]["support_status"], "weak")
            self.assertIn("quality_or_low_call_support_context", candidate["buckets"])
            self.assertTrue(any("genotype_support status weak" in point for point in candidate["decision_points"]))

    def test_candidate_inventory_marks_population_frequency_context_without_rescoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            output = Path(tmp) / "candidates.json"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            import_population_vcf(TINY_POPULATION, db, source="tiny_pop", source_version="pop_fixture")
            matches.write_text(
                "\n".join(
                    [
                        '{"match_provenance":{"match_basis":"exact_allele"},'
                        '"sample_variant":{"chrom":"1","pos":10250,"ref":"A","alt":"C","filter":"PASS",'
                        '"genotype":"0/1","depth":"20","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"Pathogenic","review_status":"criteria_provided,_single_submitter",'
                        '"gene_info":"GENE1:1","conditions":"condition","clinvar_id":"12345"}}',
                        '{"match_provenance":{"match_basis":"exact_allele"},'
                        '"sample_variant":{"chrom":"1","pos":99999,"ref":"A","alt":"G","filter":"PASS",'
                        '"genotype":"0/1","depth":"20","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"Pathogenic","review_status":"criteria_provided,_single_submitter",'
                        '"gene_info":"GENE2:2","conditions":"condition","clinvar_id":"67890"}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = extract_clinvar_candidates(matches, db, output)

            common = next(candidate for candidate in result["candidate_inventory"] if candidate["variant"]["pos"] == 10250)
            less_common = next(candidate for candidate in result["candidate_inventory"] if candidate["variant"]["pos"] == 99999)
            self.assertIn("population_frequency_context_needed", common["tags"])
            self.assertIn("population_homozygotes_present", common["tags"])
            self.assertIn("clinvar_p_lp_population_context_needed", common["buckets"])
            self.assertIn("heterozygous_p_lp_context_needed", common["buckets"])
            self.assertEqual(common["clinvar_triage_score"], less_common["clinvar_triage_score"])

    def test_candidate_inventory_reads_composite_clinsig_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "matches.jsonl"
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
                        '"sample_variant":{"chrom":"14","pos":94847262,"ref":"T","alt":"A","filter":"PASS",'
                        '"genotype":"0/1","depth":"35","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"Pathogenic/Pathogenic,_low_penetrance|other",'
                        '"review_status":"criteria_provided,_multiple_submitters,_no_conflicts","gene_info":"SERPINA1:5265",'
                        '"conditions":"Alpha-1-antitrypsin_deficiency|PI_S","clinvar_id":"17969"}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = extract_clinvar_candidates(matches)
            by_pos = {candidate["variant"]["pos"]: candidate for candidate in result["candidate_inventory"]}

            self.assertEqual(result["summary"]["selected_candidate_variants"], 2)
            conflict = by_pos[10250]
            self.assertIn("clinvar_conflicting", conflict["tags"])
            self.assertIn("clinvar_association_or_risk", conflict["tags"])
            self.assertIn("population_evidence_not_checked", conflict["tags"])
            self.assertIn("clinvar_conflicting", conflict["buckets"])
            self.assertIn("risk_factor_or_association", conflict["buckets"])
            self.assertEqual(conflict["population_evidence"]["status"], "not_checked")
            self.assertIn("population_evidence_not_checked", conflict["tags"])

            low_penetrance = by_pos[94847262]
            self.assertIn("clinvar_p_lp", low_penetrance["evidence_groups"])
            self.assertIn("clinvar_strict_p_lp", low_penetrance["tags"])
            self.assertIn("clinvar_low_penetrance", low_penetrance["tags"])
            self.assertIn("low_penetrance_or_carrier_context", low_penetrance["buckets"])
            self.assertIn("heterozygous_p_lp_context_needed", low_penetrance["buckets"])
            carrier_groups = [
                group
                for group in result["candidate_review_groups"]["groups"]
                if group["group_type"] == "carrier_relevance"
            ]
            self.assertEqual(len(carrier_groups), 1)
            self.assertEqual(carrier_groups[0]["candidate_ids"], ["variant:14-94847262-T-A"])
            self.assertEqual(carrier_groups[0]["zygosity_counts"], [["heterozygous", 1]])

    def test_candidate_inventory_selects_source_evidence_groups_not_intents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "matches.jsonl"
            matches.write_text(
                "\n".join(
                    [
                        '{"match_provenance":{"match_basis":"exact_allele"},'
                        '"sample_variant":{"chrom":"1","pos":10250,"ref":"A","alt":"C","filter":"PASS",'
                        '"genotype":"0/1","depth":"20","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"association","review_status":"no_assertion_criteria_provided",'
                        '"gene_info":"GENE1:1","conditions":"common trait","clinvar_id":"123"}}',
                        '{"match_provenance":{"match_basis":"exact_allele"},'
                        '"sample_variant":{"chrom":"1","pos":10257,"ref":"A","alt":"G","filter":"PASS",'
                        '"genotype":"0/1","depth":"20","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"drug_response","review_status":"criteria_provided,_single_submitter",'
                        '"gene_info":"GENE2:2","conditions":"drug response","clinvar_id":"456"}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            default_result = extract_clinvar_candidates(matches)
            self.assertEqual(default_result["summary"]["selected_candidate_variants"], 2)
            self.assertIn(
                ["clinvar_risk_association_protective", 1],
                default_result["summary"]["available_evidence_group_counts"],
            )
            self.assertIn(["clinvar_drug_response", 1], default_result["summary"]["available_evidence_group_counts"])
            self.assertIn("candidate_review_groups", default_result)
            self.assertIn(["risk_association", 1], default_result["candidate_review_groups"]["group_counts_by_type"])
            self.assertIn(["drug_response", 1], default_result["candidate_review_groups"]["group_counts_by_type"])

            risk_result = extract_clinvar_candidates(
                matches,
                evidence_groups=["clinvar_risk_association_protective"],
            )
            self.assertEqual(risk_result["summary"]["selected_candidate_variants"], 1)
            self.assertEqual(risk_result["candidate_inventory"][0]["variant"]["pos"], 10250)
            self.assertIn("clinvar_risk_association_protective", risk_result["candidate_inventory"][0]["evidence_groups"])

            drug_result = extract_clinvar_candidates(
                matches,
                evidence_groups=["clinvar_drug_response"],
            )
            self.assertEqual(drug_result["summary"]["selected_candidate_variants"], 1)
            self.assertEqual(drug_result["candidate_inventory"][0]["variant"]["pos"], 10257)
            self.assertIn("clinvar_drug_response", drug_result["candidate_inventory"][0]["evidence_groups"])

    def test_candidate_review_groups_use_full_selected_inventory_when_display_limited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "matches.jsonl"
            matches.write_text(
                "\n".join(
                    [
                        '{"match_provenance":{"match_basis":"exact_allele"},'
                        '"sample_variant":{"chrom":"1","pos":10250,"ref":"A","alt":"C","filter":"PASS",'
                        '"genotype":"0/1","depth":"20","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"association","review_status":"no_assertion_criteria_provided",'
                        '"gene_info":"GENE1:1","conditions":"common trait","clinvar_id":"123"}}',
                        '{"match_provenance":{"match_basis":"exact_allele"},'
                        '"sample_variant":{"chrom":"1","pos":10257,"ref":"A","alt":"G","filter":"PASS",'
                        '"genotype":"0/1","depth":"20","genotype_quality":"60"},'
                        '"clinvar":{"clinical_significance":"drug_response","review_status":"criteria_provided,_single_submitter",'
                        '"gene_info":"GENE2:2","conditions":"drug response","clinvar_id":"456"}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = extract_clinvar_candidates(matches, limit=1)

            self.assertEqual(result["summary"]["selected_candidate_variants"], 2)
            self.assertEqual(result["summary"]["emitted_candidate_variants"], 1)
            self.assertTrue(result["summary"]["truncated"])
            self.assertEqual(len(result["candidate_inventory"]), 1)
            self.assertGreater(result["candidate_review_groups"]["group_count"], len(result["candidate_inventory"]))
            self.assertIn(["risk_association", 1], result["candidate_review_groups"]["group_counts_by_type"])
            self.assertIn(["drug_response", 1], result["candidate_review_groups"]["group_counts_by_type"])


def _vus_match_line(pos: int, gene: str) -> str:
    return (
        '{"match_provenance":{"match_basis":"exact_allele"},'
        f'"sample_variant":{{"chrom":"1","pos":{pos},"ref":"A","alt":"C","filter":"PASS",'
        '"genotype":"0/1","depth":"20","genotype_quality":"60"},'
        '"clinvar":{"clinical_significance":"Uncertain_significance",'
        '"review_status":"criteria_provided,_single_submitter",'
        f'"gene_info":"{gene}:1","conditions":"condition_{gene}","clinvar_id":"{pos}"}}}}'
    )


def _write_many_matches(matches: Path, count: int) -> None:
    matches.write_text(
        "\n".join(_vus_match_line(10000 + index, f"GENE{index}") for index in range(count)) + "\n",
        encoding="utf-8",
    )


class CandidateInventoryReturnedWindowTests(EvidenceImportTestBase):
    """The returned inventory is a bounded window the host can page and narrow."""

    def test_default_returned_window_is_bounded_and_declares_how_to_reach_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "matches.jsonl"
            _write_many_matches(matches, 12)

            result = extract_clinvar_candidates(matches)

            window = result["returned_window"]
            self.assertEqual(window["limit"], DEFAULT_RETURNED_CANDIDATE_LIMIT)
            self.assertEqual(window["offset"], 0)
            self.assertEqual(window["returned_candidate_variants"], DEFAULT_RETURNED_CANDIDATE_LIMIT)
            self.assertEqual(window["total_selected_candidate_variants"], 12)
            self.assertTrue(window["has_more"])
            self.assertEqual(window["next_offset"], DEFAULT_RETURNED_CANDIDATE_LIMIT)
            self.assertEqual(
                window["select_remaining_with"]["operation"], "clinvar.scan_candidates"
            )
            self.assertEqual(len(result["candidate_inventory"]), DEFAULT_RETURNED_CANDIDATE_LIMIT)
            self.assertEqual(result["summary"]["total_match_records"], 12)
            self.assertEqual(result["summary"]["selected_candidate_variants"], 12)

            envelope = result["evidence_envelope"]
            self.assertIn(
                "bounded_candidate_window_returned:request_next_offset_or_narrow_by_gene_or_evidence_group",
                envelope["guidance"],
            )
            paging_action = next(
                action
                for action in envelope["next_actions"]
                if action["action"] == "request_next_candidate_window"
            )
            self.assertEqual(paging_action["offset"], DEFAULT_RETURNED_CANDIDATE_LIMIT)
            self.assertEqual(paging_action["total_selected_candidate_variants"], 12)
            self.assertEqual(paging_action["narrow_with_parameters"], ["gene", "evidence_groups"])

    def test_offset_pages_through_the_remaining_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "matches.jsonl"
            _write_many_matches(matches, 12)

            first = extract_clinvar_candidates(matches, limit=4)
            second = extract_clinvar_candidates(matches, limit=4, offset=4)
            last = extract_clinvar_candidates(matches, limit=4, offset=8)

            first_ids = [candidate["variant"]["pos"] for candidate in first["candidate_inventory"]]
            second_ids = [candidate["variant"]["pos"] for candidate in second["candidate_inventory"]]
            last_ids = [candidate["variant"]["pos"] for candidate in last["candidate_inventory"]]
            self.assertEqual(len(first_ids + second_ids + last_ids), 12)
            self.assertEqual(len(set(first_ids + second_ids + last_ids)), 12)
            self.assertEqual(second["returned_window"]["offset"], 4)
            self.assertTrue(second["returned_window"]["has_more"])
            self.assertFalse(last["returned_window"]["has_more"])
            self.assertIsNone(last["returned_window"]["next_offset"])
            for page in (first, second, last):
                self.assertEqual(page["returned_window"]["total_selected_candidate_variants"], 12)

    def test_gene_selection_narrows_candidates_and_review_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "matches.jsonl"
            _write_many_matches(matches, 12)

            result = extract_clinvar_candidates(matches, gene="gene7")

            self.assertEqual(result["selection"]["gene"], "GENE7")
            self.assertEqual(result["returned_window"]["total_selected_candidate_variants"], 1)
            self.assertFalse(result["returned_window"]["has_more"])
            self.assertEqual([c["genes"] for c in result["candidate_inventory"]], [["GENE7"]])
            self.assertEqual(
                {group["gene"] for group in result["candidate_review_groups"]["groups"]},
                {"GENE7"},
            )

    def test_output_file_keeps_the_full_inventory_while_the_return_stays_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "matches.jsonl"
            output = Path(tmp) / "candidates.json"
            _write_many_matches(matches, 12)

            result = extract_clinvar_candidates(matches, output_path=output, limit=3)

            self.assertEqual(len(result["candidate_inventory"]), 3)
            materialized = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(materialized["candidate_inventory"]), 12)
            self.assertEqual(materialized["summary"]["selected_candidate_variants"], 12)
            self.assertLess(
                len(json.dumps(result)),
                len(json.dumps(materialized)),
            )

    def test_cached_rebuild_serves_a_different_window_from_the_same_materialized_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "matches.jsonl"
            output = Path(tmp) / "candidates.json"
            _write_many_matches(matches, 12)

            extract_clinvar_candidates(matches, output_path=output, limit=3)
            cached = extract_clinvar_candidates(matches, output_path=output, limit=2, offset=6)

            self.assertEqual(cached["status"], "cached")
            self.assertEqual(len(cached["candidate_inventory"]), 2)
            self.assertEqual(cached["returned_window"]["offset"], 6)
            self.assertEqual(cached["returned_window"]["total_selected_candidate_variants"], 12)
            self.assertTrue(cached["returned_window"]["has_more"])

    def test_narrow_selection_leaves_the_shared_materialized_inventory_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "matches.jsonl"
            output = Path(tmp) / "candidates.json"
            _write_many_matches(matches, 12)

            extract_clinvar_candidates(matches, output_path=output)
            narrowed = extract_clinvar_candidates(matches, output_path=output, gene="GENE3")

            self.assertEqual(narrowed["returned_window"]["total_selected_candidate_variants"], 1)
            materialized = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(materialized["candidate_inventory"]), 12)
            self.assertIsNone(materialized["selection"]["gene"])
            # A later unnarrowed call still sees the whole inventory.
            reopened = extract_clinvar_candidates(matches, output_path=output, limit=12)
            self.assertEqual(len(reopened["candidate_inventory"]), 12)

    def test_limit_above_the_declared_maximum_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "matches.jsonl"
            _write_many_matches(matches, 2)

            with self.assertRaises(ValueError):
                extract_clinvar_candidates(matches, limit=MAX_RETURNED_CANDIDATE_LIMIT + 1)
            with self.assertRaises(ValueError):
                extract_clinvar_candidates(matches, offset=-1)

    def test_scan_candidates_declares_its_window_defaults_to_the_host(self) -> None:
        applied = {
            record["parameter"]: record
            for record in defaults_applied_for_call("clinvar.scan_candidates", {})
        }
        self.assertEqual(applied["limit"]["value"], DEFAULT_RETURNED_CANDIDATE_LIMIT)
        self.assertEqual(applied["offset"]["value"], 0)
        self.assertIn("evidence_groups", applied)

        overridden = {
            record["parameter"]
            for record in defaults_applied_for_call("clinvar.scan_candidates", {"limit": 20})
        }
        self.assertNotIn("limit", overridden)
        self.assertIn("offset", overridden)
