from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._external_layers_helpers import (
    TINY_CLINVAR,
    TINY_POPULATION,
    TINY_VCF,
    EvidenceImportTestBase,
    build_clinvar_gene_index,
    build_static_annotation,
    create_active_genome_index,
    extract_clinvar_candidates,
    fetch_static_population,
    import_clinvar_vcf,
    import_population_vcf,
    infer_genome_build_from_vcf,
    init_evidence_db,
    match_clinvar_variants,
    match_static_clinvar,
    prepare_investigation_packet,
    query_population_frequency,
    record_research_findings,
    resolve_genome_build,
    run_static_genotype_support,
    _gnomad_population_batch,
)


class StaticRunTests(EvidenceImportTestBase):
    def test_static_run_builds_static_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vcf = tmp_path / "sample.vcf"
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                result = build_static_annotation(vcf.name, clinvar_vcf=TINY_CLINVAR, max_records=10)
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(result["workflow_area"], "static")
            self.assertEqual(result["status"], "completed_with_warnings")
            self.assertEqual(result["static_profile"], "bounded")
            self.assertEqual(result["agi_intake_source_path"], vcf.name)
            self.assertIn("export-variants", result["long_running_steps_deferred"])
            self.assertEqual(result["shared_sync"]["inserted"]["clinvar_variants"], 3)
            step_names = [step["name"] for step in result["steps"]]
            self.assertIn("build-active-genome-index", step_names)
            self.assertIn("match-clinvar", step_names)
            self.assertEqual(result["evidence_context"]["id"], "research")
            self.assertEqual(result["evidence_context"]["skill_contract"]["path"], "SKILL.md")
            for step in result["steps"]:
                self.assertIn("evidence_context", step)
                self.assertEqual(step["evidence_context"]["skill_contract"]["path"], "SKILL.md")
            self.assertTrue((tmp_path / result["outputs"]["clinvar_matches"]).exists())
            self.assertTrue((tmp_path / result["outputs"]["clinvar_annotations"]).exists())
            self.assertTrue((tmp_path / result["shared_evidence_db"]).exists())

    def test_static_run_links_shared_static_evidence_without_copying(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shared_db = tmp_path / "shared.sqlite"
            import_clinvar_vcf(TINY_CLINVAR, shared_db, source_version="fixture", genome_build="GRCh37")
            build_clinvar_gene_index(shared_db)
            vcf = tmp_path / "sample.vcf"
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                result = build_static_annotation(
                    vcf.name,
                    source_evidence_db=shared_db,
                    shared_evidence_db=shared_db,
                    population_vcf=TINY_POPULATION,
                    population_source="fixture_population",
                    sync_shared=False,
                    genome_build="GRCh37",
                    force=True,
                    max_records=10,
                )
            finally:
                os.chdir(previous_cwd)

            evidence_db = tmp_path / result["evidence_db"]
            with sqlite3.connect(evidence_db) as connection:
                local_clinvar_rows = connection.execute("select count(*) from clinvar_variants").fetchone()[0]
                local_population_rows = connection.execute("select count(*) from population_frequencies").fetchone()[0]
            with sqlite3.connect(shared_db) as connection:
                shared_population_rows = connection.execute("select count(*) from population_frequencies").fetchone()[0]
            self.assertEqual(local_clinvar_rows, 0)
            self.assertGreater(local_population_rows, 0)
            self.assertEqual(shared_population_rows, 0)
            self.assertLess(evidence_db.stat().st_size, 1_000_000)
            self.assertEqual(result["evidence_summary"]["tables"]["clinvar_variants"], 3)
            self.assertGreater(result["evidence_summary"]["tables"]["population_frequencies"], 0)
            self.assertIn("match-clinvar", [step["name"] for step in result["steps"]])

    def test_static_run_auto_ensures_clinvar_when_not_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vcf = tmp_path / "sample.vcf"
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                with (
                    patch("genomi.runtime.libraries.manager.refresh") as ensure,
                    patch("genomi.runtime.libraries.manager.status") as status,
                ):
                    ensure.return_value = {
                        "status": "completed",
                        "library": "clinvar-grch38",
                        "output": str(TINY_CLINVAR),
                    }
                    status.return_value = {
                        "library": "clinvar-grch38",
                        "installed": False,
                        "status": "missing",
                        "required_paths": [str(TINY_CLINVAR)],
                    }
                    result = build_static_annotation(
                        vcf.name,
                        genome_build="GRCh38",
                        max_records=10,
                        allow_long_running_static=True,
                    )
            finally:
                os.chdir(previous_cwd)

            ensure.assert_called_once()
            self.assertEqual(result["genome_build"], "GRCh38")
            step_names = [step["name"] for step in result["steps"]]
            self.assertIn("ensure-clinvar", step_names)
            self.assertIn("import-clinvar", step_names)
            self.assertIn("match-clinvar", step_names)
            self.assertTrue((tmp_path / result["outputs"]["clinvar_matches"]).exists())

    def test_static_run_auto_reference_fasta_publishes_and_uses_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vcf = tmp_path / "sample.vcf"
            reference = tmp_path / "reference.fa"
            normalized = tmp_path / "normalized.vcf.gz"
            reference.write_text(">1\nACGT\n", encoding="utf-8")
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                reference_refresh = {
                    "status": "completed",
                    "library": "reference-grch38",
                    "output": str(reference),
                    "fai": str(reference) + ".fai",
                }
                clinvar_refresh = {
                    "status": "completed",
                    "library": "clinvar-grch38",
                    "output": str(TINY_CLINVAR),
                }

                def refresh_side_effect(library, *args, **kwargs):
                    if str(library).startswith("reference-"):
                        return reference_refresh
                    return clinvar_refresh

                with (
                    patch(
                        "genomi.runtime.libraries.manager.refresh",
                        side_effect=refresh_side_effect,
                    ) as ensure_reference,
                    patch("genomi.runtime.libraries.manager.status") as status,
                    patch("genomi.capabilities.clinvar.static_annotation.build.normalize_vcf") as normalize,
                ):
                    status.return_value = {
                        "library": "clinvar-grch38",
                        "installed": False,
                        "status": "missing",
                        "required_paths": [str(TINY_CLINVAR)],
                    }
                    normalize.return_value = {
                        "status": "completed",
                        "output": str(normalized),
                    }
                    result = build_static_annotation(
                        vcf.name,
                        genome_build="GRCh38",
                        auto_reference_fasta=True,
                        sync_shared=False,
                        max_records=10,
                        allow_long_running_static=True,
                    )
            finally:
                os.chdir(previous_cwd)

            ensure_reference.assert_called()
            normalize.assert_called_once()
            self.assertEqual(normalize.call_args.args[1], reference)
            self.assertTrue(normalize.call_args.kwargs["allow_malformed_tags"])
            self.assertEqual(result["reference_fasta"], str(reference))
            self.assertEqual(result["genotype_reference_fasta"], str(reference))
            self.assertEqual(result["agi_comparable_variant_export"], str(normalized))
            step_names = [step["name"] for step in result["steps"]]
            self.assertIn("ensure-reference-fasta", step_names)
            self.assertIn("normalize", step_names)

    def test_static_run_bounded_profile_defers_timeout_prone_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vcf = tmp_path / "sample.vcf"
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(tmp_path)
            try:
                with (
                    patch("genomi.runtime.libraries.manager.refresh") as refresh,
                    patch("genomi.capabilities.clinvar.static_annotation.build.export_variants") as export,
                    patch("genomi.capabilities.clinvar.static_annotation.build.normalize_vcf") as normalize,
                ):
                    result = build_static_annotation(
                        vcf.name,
                        genome_build="GRCh38",
                        auto_reference_fasta=True,
                        sync_shared=False,
                        max_records=10,
                    )
            finally:
                os.chdir(previous_cwd)

            refresh.assert_not_called()
            export.assert_not_called()
            normalize.assert_not_called()
            self.assertEqual(result["status"], "completed_with_warnings")
            self.assertEqual(result["static_profile"], "bounded")
            self.assertIn("ensure-reference-fasta", result["long_running_steps_deferred"])
            self.assertIn("export-variants", result["long_running_steps_deferred"])
            self.assertTrue(any(item["stage"] == "ensure-clinvar" for item in result["warnings"]))
            clinvar_warning = next(item for item in result["warnings"] if item["stage"] == "ensure-clinvar")
            self.assertEqual(clinvar_warning["status"], "requires_library_install")
            self.assertIn("install_command", clinvar_warning["library_install_request"]["missing_library"])

    def test_clinvar_match_reports_missing_library_install_request(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"GENOMI_HOME": str(Path(tmp) / "genomi-home")}),
        ):
            tmp_path = Path(tmp)
            vcf = tmp_path / "sample.vcf"
            db = tmp_path / "evidence.sqlite"
            vcf.write_text(TINY_VCF.read_text(encoding="utf-8"), encoding="utf-8")
            init_evidence_db(db)
            # ClinVar matching reads the Active Genome Index, so build it first;
            # with the ClinVar library absent, the match must surface the
            # library-install requirement.
            create_active_genome_index(vcf)

            result = match_static_clinvar(vcf, evidence_db=db, genome_build="GRCh38")

        self.assertEqual(result["status"], "requires_library_install")
        self.assertFalse(result["tool_will_work"])
        self.assertEqual(result["operation"], "clinvar.match_variants")
        self.assertEqual(result["missing_library"]["library"], "clinvar-grch38")
        self.assertIn("--libraries clinvar-grch38", result["ask_user"]["install_command"])

    def test_static_run_infers_g1k37_vcf_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "##reference=file:///references/G1K.37.fa",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(infer_genome_build_from_vcf(vcf), "GRCh37")
            self.assertEqual(resolve_genome_build(vcf, "auto"), "GRCh37")

    def test_static_run_infers_g1k37_from_wrapped_vcf_reference(self) -> None:
        import bz2
        import lzma
        import zipfile

        body = (
            "##fileformat=VCFv4.2\n"
            "##reference=file:///references/G1K.37.fa\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
            "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bz2_path = root / "sample.vcf.bz2"
            bz2_path.write_bytes(bz2.compress(body.encode()))
            xz_path = root / "sample.vcf.xz"
            xz_path.write_bytes(lzma.compress(body.encode()))
            zip_path = root / "sample.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("README.txt", "not genomic")
                archive.writestr("sample.vcf", body)

            for path in (bz2_path, xz_path, zip_path):
                with self.subTest(path=path.name):
                    self.assertEqual(infer_genome_build_from_vcf(path), "GRCh37")
                    self.assertEqual(resolve_genome_build(path, "auto"), "GRCh37")

    def test_investigation_packet_bundles_stored_research_sources_and_writeback_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            record_research_findings(
                db,
                {
                    "target": {"type": "drug", "drug": "Warfarin"},
                    "source": {
                        "title": "Example CPIC Warfarin",
                        "url": "https://example.test/cpic-warfarin",
                        "type": "pgx_guideline",
                        "accessed_at": "2026-05-07T00:00:00+00:00",
                    },
                    "finding": {
                        "text": "Short warfarin pharmacogenomic finding.",
                        "summary": "Warfarin source context.",
                        "type": "pharmacogenomic_guideline",
                    },
                },
            )

            packet = prepare_investigation_packet(db, "drug", drug="Warfarin")
            source_ids = {source["source_id"] for source in packet["source_catalog"]["sources"]}
            action_tools = {action["tool"] for action in packet["available_operations"]}

            self.assertEqual(packet["target"]["target_type"], "drug")
            self.assertEqual(packet["stored_research"]["count"], 1)
            self.assertIn("cpic", source_ids)
            self.assertIn("pharmgkb", source_ids)
            self.assertIn("research.query", action_tools)
            self.assertIn("research.search", action_tools)
            self.assertIn("research.record", action_tools)
            self.assertEqual(packet["record_research_template"]["target"]["type"], "drug")
            self.assertEqual(packet["record_research_template"]["target"]["drug"], "Warfarin")
            self.assertIn("source_catalog", packet)


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
            self.assertEqual(result["summary"]["selected_candidate_variants"], 1)
            view = result["evidence_view"]
            self.assertEqual(view["task_profile"]["profile_id"], "clinvar_candidate_scan")
            self.assertEqual(view["coverage_state"], "data_returned")
            self.assertEqual(view["coverage"]["candidate_count"], len(result["candidate_matrix"]))
            self.assertEqual(view["candidate_matrix"], result["candidate_matrix"])
            self.assertEqual(result["top_observed_candidate"], result["candidate_matrix"][0]["candidate_id"])
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

            cached = extract_clinvar_candidates(matches, db, output)
            self.assertEqual(cached["status"], "cached")
            self.assertEqual(cached["summary"]["selected_candidate_variants"], 1)
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
            self.assertEqual(default_result["summary"]["selected_candidate_variants"], 0)
            self.assertIn(
                ["clinvar_risk_association_protective", 1],
                default_result["summary"]["available_evidence_group_counts"],
            )
            self.assertIn(["clinvar_drug_response", 1], default_result["summary"]["available_evidence_group_counts"])
            self.assertIn("evidence_options", default_result)

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


class PopulationFrequencyTests(EvidenceImportTestBase):
    def test_gnomad_population_batch_calculates_population_af(self) -> None:
        variant = {
            "variant_id": "1-10250-A-C",
            "rsids": ["rs1"],
            "chrom": "1",
            "pos": 10250,
            "ref": "A",
            "alt": "C",
            "exome": {
                "ac": 10,
                "an": 100,
                "af": 0.1,
                "homozygote_count": 1,
                "populations": [
                    {"id": "nfe", "ac": 2, "an": 50, "homozygote_count": 0},
                ],
            },
            "genome": None,
        }

        batch = _gnomad_population_batch(
            variant,
            dataset="gnomad_r4",
            genome_build="GRCh38",
            api_url="https://example.test/api",
            imported_at="2026-01-01T00:00:00+00:00",
        )

        self.assertEqual(len(batch), 2)
        self.assertEqual(batch[0][5], "gnomad_r4_exome")
        self.assertEqual(batch[0][7], "global")
        self.assertEqual(batch[0][10], 0.1)
        self.assertEqual(batch[1][7], "nfe")
        self.assertEqual(batch[1][10], 0.04)

    def test_fetch_population_writes_directly_to_shared_for_linked_run_db(self) -> None:
        variant = {
            "variant_id": "1-10250-A-C",
            "rsids": ["rs1"],
            "chrom": "1",
            "pos": 10250,
            "ref": "A",
            "alt": "C",
            "exome": {
                "ac": 10,
                "an": 100,
                "af": 0.1,
                "homozygote_count": 1,
                "populations": [
                    {"id": "nfe", "ac": 2, "an": 50, "homozygote_count": 0},
                ],
            },
            "genome": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_db = tmp_path / "run.sqlite"
            shared_db = tmp_path / "shared.sqlite"
            init_evidence_db(run_db)
            with sqlite3.connect(run_db) as connection:
                for key in ("source_evidence_db", "shared_evidence_db"):
                    connection.execute(
                        """
                        insert into metadata(key, value) values(?, ?)
                        on conflict(key) do update set value = excluded.value
                        """,
                        (key, json.dumps(str(shared_db))),
                    )
                connection.commit()

            with patch("genomi.evidence._post_graphql", return_value={"data": {"variant": variant}}):
                result = fetch_static_population(
                    run_db,
                    "1",
                    10250,
                    "A",
                    "C",
                    shared_evidence_db=shared_db,
                    sync_shared=True,
                )

            self.assertEqual(result["public_write_db"], str(shared_db))
            self.assertEqual(result["shared_sync"]["status"], "direct_shared_write")
            with sqlite3.connect(run_db) as connection:
                local_rows = connection.execute("select count(*) from population_frequencies").fetchone()[0]
            with sqlite3.connect(shared_db) as connection:
                shared_rows = connection.execute("select count(*) from population_frequencies").fetchone()[0]
            self.assertEqual(local_rows, 0)
            self.assertEqual(shared_rows, 2)
            visible = query_population_frequency(run_db, "1", 10250, "A", "C")
            self.assertEqual(visible["count"], 2)

    def test_fetch_population_returns_structured_status_when_gnomad_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_db = tmp_path / "run.sqlite"
            shared_db = tmp_path / "shared.sqlite"
            init_evidence_db(run_db)

            with patch("genomi.evidence._post_graphql", side_effect=RuntimeError("gnomAD API request failed: offline")):
                result = fetch_static_population(
                    run_db,
                    "1",
                    10250,
                    "A",
                    "C",
                    shared_evidence_db=shared_db,
                    sync_shared=True,
                )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "source_unavailable")
            self.assertEqual(result["inserted_rows"], 0)
            self.assertEqual(result["population_frequency"]["count"], 0)
            self.assertIn("offline", result["error"])
            self.assertEqual(result["shared_sync"]["status"], "direct_shared_write")


if __name__ == "__main__":
    unittest.main()
