from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from genomi.active_genome_index.active_genome_index import ActiveGenomeIndexIncomplete, ActiveGenomeIndexNeed, open_reader
from tests._external_layers_helpers import (
    SQLITE_BUSY_TIMEOUT_SECONDS,
    TINY_CLINVAR,
    TINY_POPULATION,
    TINY_VCF,
    EvidenceImportTestBase,
    build_clinvar_annotation_index,
    build_clinvar_gene_index,
    build_clinvar_rsid_annotation_index,
    build_clinvar_rsid_index,
    connect_evidence,
    create_active_genome_index,
    default_static_outputs,
    evidence_source_catalog,
    evidence_summary,
    fetch_gene_evidence,
    gather_variant_evidence,
    import_clinvar_vcf,
    import_population_vcf,
    init_evidence_db,
    match_clinvar_variants,
    match_clinvar_variants_from_active_genome_index,
    query_clinvar,
    query_population_frequency,
    query_research_findings,
    record_research_findings,
    search_research_findings,
    summarize_clinvar_matches,
    _reusable_static_db_with_clinvar,
    query_reviewed_research,
    record_reviewed_research,
    research_contract,
    run_static_callability,
    run_static_genotype_support,
    run_static_sample_qc,
    static_contract,
)


class EvidenceImportTests(EvidenceImportTestBase):
    def test_evidence_connections_wait_for_parallel_shared_writers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            init_evidence_db(db)

            with connect_evidence(db) as connection:
                timeout = connection.execute("pragma busy_timeout").fetchone()[0]

            self.assertEqual(timeout, SQLITE_BUSY_TIMEOUT_SECONDS * 1000)

    def test_schema_ensure_updates_existing_metadata_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            with sqlite3.connect(db) as connection:
                connection.execute("create table metadata (key text primary key, value text not null)")
                connection.execute("insert into metadata(key, value) values('schema_version', ?)", (json.dumps(2),))

            summary = evidence_summary(db)

            self.assertEqual(summary["metadata"]["schema_version"], 6)
            self.assertIn("research_findings", summary["tables"])
            self.assertIn("sample_qc", summary["tables"])

    def test_schema_ensure_migrates_existing_research_target_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            with sqlite3.connect(db) as connection:
                connection.execute("create table metadata (key text primary key, value text not null)")
                connection.execute("insert into metadata(key, value) values('schema_version', ?)", (json.dumps(4),))
                connection.execute(
                    """
                    create table research_findings (
                        finding_id text primary key,
                        target_type text not null,
                        target_id text not null,
                        chrom text,
                        pos integer,
                        ref text,
                        alt text,
                        gene text,
                        genome_build text,
                        source_title text not null,
                        source_url text not null,
                        source_type text,
                        source_published_at text,
                        source_accessed_at text not null,
                        searched_query text,
                        finding_text text not null,
                        finding_summary text,
                        finding_type text,
                        captured_by text not null,
                        captured_at text not null,
                        raw_json text not null
                    )
                    """
                )

            summary = evidence_summary(db)

            self.assertEqual(summary["metadata"]["schema_version"], 6)
            with sqlite3.connect(db) as connection:
                columns = {row[1] for row in connection.execute("pragma table_info(research_findings)")}
            self.assertIn("drug", columns)
            self.assertIn("condition", columns)
            self.assertIn("topic", columns)
            self.assertIn("research_scope", columns)

    def test_clinvar_import_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"

            init = init_evidence_db(db)
            self.assertEqual(init["schema_version"], 6)

            result = import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["scanned_records"], 2)
            self.assertEqual(result["inserted_alleles"], 3)

            cached = import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            self.assertEqual(cached["status"], "cached")
            self.assertEqual(cached["inserted_alleles"], 3)

            query = query_clinvar(db, "1", 10250, "A", "C")
            self.assertEqual(query["count"], 1)
            self.assertEqual(query["records"][0]["clinvar_id"], "12345")
            self.assertEqual(query["records"][0]["clinical_significance"], "Benign")

            split_query = query_clinvar(db, "1", 10257, "A", "G")
            self.assertEqual(split_query["count"], 1)
            self.assertEqual(split_query["records"][0]["clinical_significance"], "Uncertain_significance")

    def test_explicit_clinvar_import_is_preferred_over_existing_shared_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_db = Path(tmp) / "run.sqlite"
            shared_db = Path(tmp) / "shared.sqlite"
            import_clinvar_vcf(TINY_CLINVAR, run_db, source_version="run-fixture")
            import_clinvar_vcf(TINY_CLINVAR, shared_db, source_version="shared-fixture")

            selected = _reusable_static_db_with_clinvar(
                run_db,
                shared_db,
                "GRCh38",
                preferred_db=run_db,
            )

        self.assertEqual(selected, run_db)

    def test_sample_qc_records_evidence_boundaries_in_private_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            index = Path(tmp) / "active-genome-index.sqlite"
            output = Path(tmp) / "sample-qc.json"

            result = run_static_sample_qc(TINY_VCF, evidence_db=db, agi_path=index, output=output)
            summary = evidence_summary(db)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["input_type"], "callset_with_reference_blocks")
            self.assertTrue(result["has_reference_blocks"])
            self.assertTrue(result["absence_claims_allowed_by_default"])
            self.assertIn("evidence_boundaries", result["evidence_boundaries"])
            self.assertEqual(summary["tables"]["sample_qc"], 1)
            self.assertTrue(output.exists())

    def test_genotype_support_classifies_supported_and_weak_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            index = Path(tmp) / "active-genome-index.sqlite"

            supported = run_static_genotype_support(
                TINY_VCF,
                "1",
                10250,
                "A",
                "C",
                evidence_db=db,
                agi_path=index,
            )
            self.assertEqual(supported["support_status"], "supported")
            self.assertIn("genotype_support_supported", supported["accepted_report_evidence_classes"])

            weak_vcf = Path(tmp) / "weak.vcf"
            weak_vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "##reference=GRCh38",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t200\t.\tA\tG\t.\tLowQual\t.\tGT:DP:GQ\t0/1:4:9",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            weak = run_static_genotype_support(
                weak_vcf,
                "1",
                200,
                "A",
                "G",
                evidence_db=db,
                agi_path=Path(tmp) / "weak-active-genome-index.sqlite",
            )

            self.assertEqual(weak["support_status"], "weak")
            self.assertEqual(weak["evidence_class"], "genotype_support_weak")
            self.assertIn("limitation context", weak["evidence_boundaries"]["evidence_boundaries"][0])
            self.assertEqual(evidence_summary(db)["tables"]["genotype_support"], 2)

    def test_genotype_support_resolves_interior_gvcf_reference_block_with_fasta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            index = Path(tmp) / "active-genome-index.sqlite"
            fasta = Path(tmp) / "ref.fa"
            gvcf = Path(tmp) / "sample.g.vcf"
            fasta.write_text(">1\nAAAAACCCCCGGGGGTTTTT\n", encoding="utf-8")
            Path(f"{fasta}.fai").write_text("1\t20\t3\t20\t21\n", encoding="utf-8")
            gvcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "##reference=GRCh38",
                        "##contig=<ID=1,length=20>",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t5\t.\tA\t.\t.\tPASS\tEND=15\tGT:DP:GQ\t0/0:35:0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_static_genotype_support(
                gvcf,
                "1",
                10,
                "C",
                "T",
                evidence_db=db,
                agi_path=index,
                reference_fasta=fasta,
            )

            self.assertEqual(result["support_status"], "not_observed")
            self.assertEqual(result["sample_observation"]["observed_genotype"], "C/C")
            self.assertTrue(result["sample_observation"]["reference_call_supported"])
            self.assertEqual(result["sample_observation"]["matched_by"], "reference_block")
            self.assertIn("reference_inference_or_assay_completeness", result["accepted_report_evidence_classes"])

    def test_genotype_support_preserves_sample_specific_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            index = Path(tmp) / "active-genome-index.sqlite"
            vcf = Path(tmp) / "multi.vcf"
            vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "##reference=GRCh38",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tunknown\tSample1",
                        "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/0:20:60\t0/1:50:80",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_static_genotype_support(
                vcf,
                "1",
                100,
                "A",
                "G",
                evidence_db=db,
                agi_path=index,
            )

            self.assertEqual(result["support_status"], "supported")
            self.assertEqual(result["sample_observation"]["observed_genotype"], "A/G")
            self.assertEqual(result["sample_observation"]["source_record"]["sample_name"], "Sample1")

    def test_genotype_support_projects_simple_complex_record_to_target_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            index = Path(tmp) / "active-genome-index.sqlite"
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "##reference=GRCh38",
                        "##contig=<ID=1,length=200>",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t100\t.\tAC\tAT\t.\tPASS\t.\tGT:DP:GQ\t0/1:35:80",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_static_genotype_support(
                vcf,
                "1",
                101,
                "C",
                "T",
                evidence_db=db,
                agi_path=index,
            )

            self.assertEqual(result["support_status"], "supported")
            self.assertEqual(result["sample_observation"]["observed_genotype"], "C/T")
            self.assertEqual(result["sample_observation"]["matched_by"], "overlapping_variant_projection")
            self.assertEqual(result["sample_observation"]["record_type"], "complex_projection")

    def test_genotype_support_projects_deletion_allele_to_dash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            index = Path(tmp) / "active-genome-index.sqlite"
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "##reference=GRCh38",
                        "##contig=<ID=1,length=200>",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t100\t.\tAC\tA\t.\tPASS\t.\tGT:DP:GQ\t0/1:35:80",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_static_genotype_support(
                vcf,
                "1",
                101,
                "C",
                "-",
                evidence_db=db,
                agi_path=index,
            )

            self.assertEqual(result["support_status"], "supported")
            self.assertEqual(result["sample_observation"]["observed_genotype"], "C/-")
            self.assertEqual(result["sample_observation"]["matched_by"], "overlapping_variant_projection")

    def test_gather_variant_consumes_private_genotype_support_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            index = Path(tmp) / "active-genome-index.sqlite"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            match_clinvar_variants(TINY_VCF, db, matches)
            run_static_sample_qc(TINY_VCF, evidence_db=db, agi_path=index, output=Path(tmp) / "sample-qc.json")
            run_static_genotype_support(
                TINY_VCF,
                "1",
                10257,
                "A",
                "C",
                evidence_db=db,
                agi_path=index,
                min_depth=100,
            )

            result = gather_variant_evidence(db, "1", 10257, "A", "C", matches_path=matches)

            private_context = result["private_sample_context"]
            self.assertEqual(private_context["sample_qc"]["count"], 1)
            self.assertEqual(private_context["genotype_support"]["latest"]["support_status"], "weak")
            self.assertEqual(result["evidence_options"][0]["available_operation"], "active_genome_index.classify_genotype_support")

    def test_callability_requires_reference_blocks_for_negative_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            callable_result = run_static_callability(
                TINY_VCF,
                "1:10001-10249",
                evidence_db=db,
                agi_path=Path(tmp) / "active-genome-index.sqlite",
            )

            self.assertEqual(callable_result["callability_status"], "callable")
            self.assertTrue(callable_result["can_support_negative_or_reference_claim"])
            self.assertIn(
                "reference_inference_or_assay_completeness",
                callable_result["accepted_report_evidence_classes"],
            )

            variant_only_vcf = Path(tmp) / "variant-only.vcf"
            variant_only_vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "##reference=GRCh38",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t10250\t.\tA\tC\t.\tPASS\t.\tGT:DP:GQ\t0/1:50:99",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            unknown = run_static_callability(
                variant_only_vcf,
                "1:10251-10251",
                evidence_db=db,
                agi_path=Path(tmp) / "variant-only-active-genome-index.sqlite",
            )

            self.assertEqual(unknown["callability_status"], "unknown_no_reference_blocks")
            self.assertFalse(unknown["can_support_negative_or_reference_claim"])
            self.assertEqual(evidence_summary(db)["tables"]["region_callability"], 2)

    def test_clinvar_match_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            output = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")

            result = match_clinvar_variants(TINY_VCF, db, output)

            self.assertEqual(result["stats"]["queried_alleles"], 2)
            self.assertEqual(result["stats"]["matched_alleles"], 2)
            self.assertEqual(result["stats"]["written_records"], 2)
            cached = match_clinvar_variants(TINY_VCF, db, output)
            self.assertEqual(cached["status"], "cached")
            self.assertEqual(cached["stats"], result["stats"])
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn('"clinical_significance": "Benign"', lines[0])
            payloads = [json.loads(line) for line in lines]
            self.assertEqual({payload["match_basis"] for payload in payloads}, {"exact_allele"})
            self.assertEqual(payloads[0]["match_kind"], "exact_allele")
            self.assertEqual(payloads[0]["source_format"], "vcf")
            self.assertEqual(payloads[0]["sample_variant"]["source_record_ref"], payloads[0]["sample_variant"]["ref"])
            self.assertEqual(payloads[0]["sample_variant"]["source_record_alt"], payloads[0]["sample_variant"]["alt"])
            self.assertTrue(Path(result["manifest_path"]).exists())

            chr_vcf = Path(tmp) / "chr-input.vcf"
            chr_vcf.write_text(TINY_VCF.read_text(encoding="utf-8").replace("\n1\t", "\nchr1\t"), encoding="utf-8")
            chr_output = Path(tmp) / "chr-matches.jsonl"
            chr_result = match_clinvar_variants(chr_vcf, db, chr_output)
            self.assertEqual(chr_result["stats"]["matched_alleles"], 2)
            self.assertIn('"chrom": "chr1"', chr_output.read_text(encoding="utf-8").splitlines()[0])

            agi_path = Path(tmp) / "tiny-active-genome-index.sqlite"
            agi_output = Path(tmp) / "active-genome-index-matches.jsonl"
            create_active_genome_index(chr_vcf, agi_path)
            reader = open_reader(agi_path, need=ActiveGenomeIndexNeed.VARIANT, genome_build="GRCh38")
            agi_result = match_clinvar_variants_from_active_genome_index(reader, db, agi_output)
            self.assertEqual(agi_result["stats"]["matched_alleles"], 2)
            self.assertIn('"chrom": "chr1"', agi_output.read_text(encoding="utf-8").splitlines()[0])
            active_payload = json.loads(agi_output.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(active_payload["match_basis"], "exact_allele")
            self.assertEqual(active_payload["sample_variant"]["source_record_ref"], active_payload["sample_variant"]["ref"])

            incomplete_active_genome_index = Path(tmp) / "incomplete-active-genome-index.sqlite"
            with sqlite3.connect(incomplete_active_genome_index) as connection:
                connection.executescript(
                    """
                    create table stats (key text primary key, value text not null);
                    create table records (
                        chrom text, chrom_sort integer, pos integer, end integer, rsid text,
                        sample_index integer, sample_name text, info_genes text, info text,
                        ref text, alt text, qual text, filter text, is_variant integer,
                        format text, sample text, genotype text, depth integer,
                        genotype_quality integer, offset integer, line_length integer
                    );
                    create index records_rsid_idx on records(rsid);
                    """
                )
            with self.assertRaises(ActiveGenomeIndexIncomplete):
                incomplete_reader = open_reader(
                    incomplete_active_genome_index,
                    need=ActiveGenomeIndexNeed.VARIANT,
                    genome_build="GRCh38",
                )
                match_clinvar_variants_from_active_genome_index(incomplete_reader, db, Path(tmp) / "incomplete.jsonl")

            summary = summarize_clinvar_matches(output, Path(tmp) / "summary.json")
            self.assertEqual(summary["total_clinvar_match_records"], 2)
            self.assertEqual(summary["strict_pathogenic_or_likely_pathogenic_count"], 0)
            self.assertTrue(Path(summary["output"]).exists())
            cached_summary = summarize_clinvar_matches(output, Path(tmp) / "summary.json")
            self.assertEqual(cached_summary["status"], "cached")

            annotations = build_clinvar_annotation_index(output, Path(tmp) / "annotations.json")
            self.assertEqual(annotations["summary"]["total_match_records"], 2)
            self.assertEqual(annotations["summary"]["matched_variants"], 2)
            self.assertEqual(annotations["summary"]["exact_match_variants"], 2)
            self.assertEqual(annotations["summary"]["match_basis_counts"], [("exact_allele", 2)])
            self.assertEqual(annotations["annotations"][0]["genes"], ["GENE1"])
            self.assertEqual(annotations["annotations"][0]["match_provenance"]["primary_match_basis"], "exact_allele")
            self.assertEqual(annotations["annotations"][0]["clinvar"]["clinical_significance_counts"], [("Benign", 1)])
            cached_annotations = build_clinvar_annotation_index(output, Path(tmp) / "annotations.json")
            self.assertEqual(cached_annotations["status"], "cached")

            record_research_findings(
                db,
                {
                    "findings": [
                        {
                            "target": {"type": "gene", "gene": "GENE1"},
                            "source": {
                                "title": "Example Gene Source",
                                "url": "https://example.test/cache-gene",
                                "accessed_at": "2026-05-05T00:00:00+00:00",
                            },
                            "finding": {"text": "Short research text.", "summary": "Research summary."},
                        }
                    ]
                },
            )
            cached_after_record = match_clinvar_variants(TINY_VCF, db, output)
            self.assertEqual(cached_after_record["status"], "cached")

    def test_clinvar_annotation_index_preserves_array_inference_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matches = Path(tmp) / "array.matches.jsonl"
            matches.write_text(
                json.dumps(
                    {
                        "match_basis": "consumer_array_allele_inference",
                        "match_kind": "consumer_array_allele_inference",
                        "source_format": "23andme",
                        "sample_variant": {
                            "chrom": "1",
                            "pos": 200,
                            "ref": ".",
                            "alt": ".",
                            "genotype": "TG",
                            "filter": "PASS",
                            "source_format": "23andme",
                            "record_kind": "array_call",
                            "observed_alleles": ["T", "G"],
                            "source_record_ref": ".",
                            "source_record_alt": ".",
                            "source_record_format": "GT_ARRAY",
                            "source_record_record_kind": "array_call",
                            "source_record_observed_alleles": ["T", "G"],
                        },
                        "clinvar": {
                            "chrom": "1",
                            "pos": 200,
                            "ref": "T",
                            "alt": "G",
                            "clinical_significance": "Pathogenic",
                            "review_status": "criteria provided, single submitter",
                            "gene_info": "GENE2:2",
                            "conditions": "condition",
                            "clinvar_id": "RCV0002",
                        },
                        "match_provenance": {
                            "match_basis": "consumer_array_allele_inference",
                            "inferred_clinvar_allele": {"chrom": "1", "pos": 200, "ref": "T", "alt": "G"},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            annotations = build_clinvar_annotation_index(matches, Path(tmp) / "annotations.json")

        self.assertEqual(annotations["summary"]["matched_variants"], 1)
        self.assertEqual(annotations["summary"]["exact_match_variants"], 0)
        self.assertEqual(annotations["summary"]["match_basis_counts"], [("consumer_array_allele_inference", 1)])
        self.assertEqual(
            annotations["annotations"][0]["match_provenance"]["primary_match_basis"],
            "consumer_array_allele_inference",
        )
        variant = annotations["annotations"][0]["variant"]
        self.assertEqual(annotations["annotations"][0]["candidate_allele"], {"chrom": "1", "pos": 200, "ref": "T", "alt": "G"})
        self.assertEqual(variant["record_kind"], "array_call")
        self.assertEqual(variant["ref"], ".")
        self.assertEqual(variant["alt"], ".")
        self.assertEqual(variant["observed_alleles"], ["T", "G"])
        self.assertEqual(variant["source_record_record_kind"], "array_call")
        self.assertEqual(variant["source_record_observed_alleles"], ["T", "G"])

    def test_clinvar_match_report_marks_multiallelic_source_alt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            output = Path(tmp) / "matches.jsonl"
            sample_vcf = Path(tmp) / "multiallelic.vcf"
            sample_vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t10257\trs111200574\tA\tC,G\t.\tPASS\t.\tGT\t1/2",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")

            result = match_clinvar_variants(sample_vcf, db, output)

            self.assertEqual(result["stats"]["matched_alleles"], 2)
            payloads = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(payloads), 2)
            self.assertEqual({payload["match_basis"] for payload in payloads}, {"multiallelic_alt"})
            self.assertEqual({payload["sample_variant"]["alt"] for payload in payloads}, {"C", "G"})
            for payload in payloads:
                self.assertEqual(payload["sample_variant"]["source_record_alt"], "C,G")
                self.assertEqual(payload["match_provenance"]["source_record"]["alt"], "C,G")

    def test_gene_evidence_fetches_clinvar_and_sample_matches_without_interpretation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            output = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            match_clinvar_variants(TINY_VCF, db, output)

            result = fetch_gene_evidence("GENE1", db, matches_path=output)

            self.assertEqual(result["query"]["gene"], "GENE1")
            self.assertEqual(result["clinvar_gene"]["lookup_mode"], "gene_info_scan")
            self.assertEqual(result["clinvar_gene"]["total_records"], 1)
            self.assertEqual(result["sample_matches"]["total_records"], 1)
            self.assertEqual(result["sample_matches"]["records"][0]["clinvar"]["clinvar_id"], "12345")
            self.assertIn("evidence retrieval for host-agent interpretation", result["notes"][0])

            gene_index = build_clinvar_gene_index(db)
            self.assertEqual(gene_index["status"], "completed")
            self.assertEqual(gene_index["gene_links"], 3)

            indexed_result = fetch_gene_evidence("GENE1", db, matches_path=output)
            self.assertEqual(indexed_result["clinvar_gene"]["lookup_mode"], "gene_index")
            self.assertEqual(indexed_result["clinvar_gene"]["total_records"], 1)

    def test_population_frequency_import_query_and_gather_variant_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            import_population_vcf(TINY_POPULATION, db, source="tiny_pop", source_version="pop_fixture")
            match_clinvar_variants(TINY_VCF, db, matches)

            cached = import_population_vcf(TINY_POPULATION, db, source="tiny_pop", source_version="pop_fixture")
            self.assertEqual(cached["status"], "cached")
            self.assertEqual(cached["inserted_alleles"], 3)

            query = query_population_frequency(db, "1", 10257, "A", "G")
            self.assertEqual(query["count"], 1)
            self.assertEqual(query["records"][0]["source"], "tiny_pop")
            self.assertEqual(query["records"][0]["allele_count"], 4)
            self.assertEqual(query["records"][0]["allele_number"], 200)
            self.assertEqual(query["records"][0]["allele_frequency"], 0.02)
            self.assertEqual(query["records"][0]["homozygote_count"], 0)

            evidence = gather_variant_evidence(db, "1", 10250, "A", "C", matches_path=matches)
            self.assertEqual(evidence["sample_observation"]["total_records"], 1)
            self.assertEqual(evidence["curated_evidence"]["clinvar"]["count"], 1)
            self.assertEqual(evidence["curated_evidence"]["gene_symbols"], ["GENE1"])
            self.assertEqual(evidence["public_population_compare"]["count"], 1)
            self.assertEqual(evidence["public_population_summary"]["record_count"], 1)
            self.assertEqual(
                evidence["public_population_summary"]["global_rows"][0]["allele_frequency"],
                0.1,
            )
            self.assertIn("not_available_from_one_vcf", evidence["comparison_scope"])
            self.assertEqual(evidence["research_evidence"]["exact_variant"]["count"], 0)

    def test_clinvar_rsid_annotation_index_uses_vcf_rsids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db = tmp_path / "evidence.sqlite"
            clinvar = tmp_path / "clinvar.vcf"
            vcf = tmp_path / "sample.vcf"
            index = tmp_path / "active-genome-index.sqlite"
            clinvar.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "##source=TinyClinVarRsidFixture",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                        (
                            "1\t100\t12345\tA\tG\t.\t.\t"
                            "RS=rs123;ALLELEID=999;CLNSIG=Pathogenic;CLNREVSTAT=criteria_provided,_single_submitter;"
                            "CLNDN=condition;GENEINFO=GENE1:1"
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t100\trs123\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:50:99",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            import_clinvar_vcf(clinvar, db, source_version="fixture")
            rsid_index = build_clinvar_rsid_index(db)
            create_active_genome_index(vcf, index)
            reader = open_reader(index, need=ActiveGenomeIndexNeed.VARIANT, genome_build="GRCh38")
            annotations = build_clinvar_rsid_annotation_index(reader, db, tmp_path / "rsid-annotations.json")

        self.assertEqual(rsid_index["rsid_links"], 1)
        self.assertEqual(annotations["summary"]["matched_rsids"], 1)
        self.assertEqual(annotations["annotations"][0]["rsid"], "rs123")
        self.assertEqual(annotations["annotations"][0]["genes"], ["GENE1"])
        self.assertEqual(annotations["annotations"][0]["match_level"], "rsid")

    def test_research_findings_are_recorded_and_returned_with_gather_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            match_clinvar_variants(TINY_VCF, db, matches)

            recorded = record_research_findings(
                db,
                {
                    "findings": [
                        {
                            "target": {"type": "variant", "chrom": "1", "pos": 10250, "ref": "A", "alt": "C"},
                            "source": {
                                "title": "Example Variant Source",
                                "url": "https://example.test/variant",
                                "type": "source",
                                "accessed_at": "2026-05-05T00:00:00+00:00",
                            },
                            "finding": {
                                "text": "Original short finding text from the source.",
                                "summary": "Variant source says the fact.",
                                "type": "variant_assertion",
                            },
                            "searched_query": "1 10250 A C",
                        },
                        {
                            "target": {"type": "gene", "gene": "GENE1"},
                            "source": {
                                "title": "Example Gene Source",
                                "url": "https://example.test/gene",
                                "accessed_at": "2026-05-05T00:00:00+00:00",
                            },
                            "finding": {
                                "text": "Original gene finding text from the source.",
                                "summary": "Gene source says the fact.",
                            },
                        },
                    ]
                },
            )

            self.assertEqual(recorded["inserted_findings"], 2)
            variant_evidence = gather_variant_evidence(db, "1", 10250, "A", "C", matches_path=matches)
            self.assertEqual(variant_evidence["research_evidence"]["exact_variant"]["count"], 1)
            self.assertEqual(
                variant_evidence["research_evidence"]["exact_variant"]["records"][0]["source"]["url"],
                "https://example.test/variant",
            )
            self.assertEqual(variant_evidence["research_evidence"]["genes"]["GENE1"]["count"], 1)

            gene_evidence = fetch_gene_evidence("GENE1", db, matches_path=matches)
            self.assertEqual(gene_evidence["research_evidence"]["count"], 1)
            self.assertEqual(
                gene_evidence["research_evidence"]["records"][0]["finding"]["text"],
                "Original gene finding text from the source.",
            )

    def test_research_findings_support_drug_condition_and_topic_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"

            recorded = record_research_findings(
                db,
                {
                    "findings": [
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
                        {
                            "target": {"type": "condition", "condition": "Alpha-1 antitrypsin deficiency"},
                            "source": {
                                "title": "Example Condition Source",
                                "url": "https://example.test/aatd",
                                "accessed_at": "2026-05-07T00:00:00+00:00",
                            },
                            "finding": {"text": "Short condition finding."},
                        },
                        {
                            "target": {"type": "topic", "topic": "smoking related genetic risk"},
                            "source": {
                                "title": "Example Topic Source",
                                "url": "https://example.test/smoking-topic",
                                "accessed_at": "2026-05-07T00:00:00+00:00",
                            },
                            "finding": {"text": "Short topic finding."},
                        },
                    ]
                },
            )

            self.assertEqual(recorded["inserted_findings"], 3)
            self.assertEqual(
                {step["target_type"] for step in recorded["evidence_options"]},
                {"drug", "condition", "topic"},
            )

            drug = query_research_findings(db, "drug", drug="warfarin")
            self.assertEqual(drug["count"], 1)
            self.assertEqual(drug["query"]["drug"], "warfarin")
            self.assertEqual(drug["records"][0]["target"]["drug"], "Warfarin")
            self.assertEqual(drug["records"][0]["finding"]["type"], "pharmacogenomic_guideline")

            condition = query_research_findings(db, "condition", condition="Alpha-1 antitrypsin deficiency")
            self.assertEqual(condition["count"], 1)
            self.assertEqual(condition["records"][0]["target"]["condition"], "Alpha-1 antitrypsin deficiency")

            topic = query_research_findings(db, "topic", topic="smoking related genetic risk")
            self.assertEqual(topic["count"], 1)
            self.assertEqual(topic["records"][0]["target"]["topic"], "smoking related genetic risk")

            search = search_research_findings(db, "smoking risk")
            self.assertEqual(search["count"], 1)
            self.assertEqual(search["records"][0]["target"]["type"], "topic")

            semantic_search = search_research_findings(
                db,
                "blood thinner after stent",
                semantic_context={
                    "raw_query": "blood thinner after stent",
                    "host_expansions": ["warfarin"],
                    "host_entities": [{"text": "warfarin", "type": "drug"}],
                },
            )
            self.assertEqual(semantic_search["count"], 1)
            self.assertEqual(semantic_search["records"][0]["target"]["drug"], "Warfarin")
            self.assertIn(
                "warfarin",
                {item["text"] for item in semantic_search["semantic_context"]["term_matches"]},
            )

    def test_source_catalog_exposes_more_databases_and_storage_contract(self) -> None:
        catalog = evidence_source_catalog(target_type="drug")
        source_ids = {source["source_id"] for source in catalog["sources"]}

        self.assertIn("cpic", source_ids)
        self.assertIn("pharmgkb", source_ids)
        self.assertIn("fda_pharmacogenomics", source_ids)
        self.assertIn("fda_pharmacogenetic_associations", source_ids)
        self.assertIn("drug", catalog["storage_contract"]["record_research_target_types"])

    def test_intent_research_scope_separates_shared_and_private_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            shared_db = Path(tmp) / "shared.sqlite"
            shared = {
                "target": {"type": "gene", "gene": "GENE1"},
                "source": {
                    "title": "Shared Source",
                    "url": "https://example.test/shared-gene",
                    "accessed_at": "2026-05-07T00:00:00+00:00",
                },
                "finding": {"text": "Shared source finding.", "type": "clinical_review"},
            }
            private = {
                "target": {"type": "gene", "gene": "GENE1"},
                "source": {
                    "title": "Private Source",
                    "url": "https://example.test/private-gene",
                    "accessed_at": "2026-05-07T00:00:00+00:00",
                },
                "finding": {"text": "Private user-specific combination finding."},
            }

            shared_record = record_reviewed_research(db, shared, scope="shared", shared_evidence_db=shared_db)
            private_record = record_reviewed_research(db, private, scope="private", shared_evidence_db=shared_db)

            all_rows = query_reviewed_research(db, "gene", gene="GENE1")
            shared_rows = query_reviewed_research(db, "gene", gene="GENE1", scope="shared")
            private_rows = query_reviewed_research(db, "gene", gene="GENE1", scope="private")

            self.assertEqual(all_rows["count"], 2)
            self.assertEqual(shared_rows["count"], 1)
            self.assertEqual(private_rows["count"], 1)
            self.assertEqual(shared_rows["records"][0]["scope"], "shared")
            self.assertEqual(private_rows["records"][0]["scope"], "private")
            self.assertEqual(shared_record["shared_sync"]["status"], "completed")
            self.assertEqual(private_record["shared_sync"]["status"], "private_not_synced")
            shared_db_rows = query_reviewed_research(shared_db, "gene", gene="GENE1")
            self.assertEqual(shared_db_rows["count"], 1)
            self.assertEqual(shared_db_rows["records"][0]["scope"], "shared")

    def test_workflow_contracts_are_explicit(self) -> None:
        self.assertEqual(static_contract()["id"], "static")
        self.assertEqual(research_contract()["id"], "research")
        self.assertIn("local parsing, database import, and deterministic evidence checks", static_contract()["purpose"])
        self.assertNotIn("panel", " ".join(static_contract()["primary_outputs"]).lower())
        self.assertFalse({"panel_json", "panel_markdown"} & set(default_static_outputs(TINY_VCF)))
        self.assertIn("shared/private", research_contract()["purpose"])


if __name__ == "__main__":
    unittest.main()
