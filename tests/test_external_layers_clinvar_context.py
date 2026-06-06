from __future__ import annotations

import json
import tempfile
from pathlib import Path

from genomi.active_genome_index.active_genome_index import ActiveGenomeIndexIncomplete, ActiveGenomeIndexNeed, open_reader
from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.evidence import (
    build_clinvar_annotation_index,
    build_clinvar_gene_index,
    build_clinvar_rsid_annotation_index,
    build_clinvar_rsid_index,
    fetch_gene_evidence,
    gather_variant_evidence,
    import_clinvar_vcf,
    import_population_vcf,
    match_clinvar_variants,
    match_clinvar_variants_from_active_genome_index,
    query_population_frequency,
    record_research_findings,
    summarize_clinvar_matches,
)
from genomi.runtime.sqlite_support import connect_sqlite
from tests.support.capabilities.external_layers import (
    TINY_CLINVAR,
    TINY_POPULATION,
    TINY_VCF,
    EvidenceImportTestBase,
)


class ExternalClinvarContextTests(EvidenceImportTestBase):
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
            self.assertEqual({payload["match_provenance"]["match_basis"] for payload in payloads}, {"exact_allele"})
            self.assertEqual(sorted(payloads[0]), ["clinvar", "match_provenance", "sample_variant"])
            self.assertEqual(payloads[0]["match_provenance"]["source_format"], "vcf")
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
            self.assertEqual(active_payload["match_provenance"]["match_basis"], "exact_allele")
            self.assertEqual(active_payload["sample_variant"]["agi_record_ref"], active_payload["sample_variant"]["ref"])

            incomplete_active_genome_index = Path(tmp) / "incomplete-active-genome-index.sqlite"
            with connect_sqlite(incomplete_active_genome_index) as connection:
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
                            "agi_record_ref": ".",
                            "agi_record_alt": ".",
                            "agi_record_format": "GT_ARRAY",
                            "agi_record_record_kind": "array_call",
                            "agi_record_observed_alleles": ["T", "G"],
                            "agi_record_info": ".",
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
                            "source_format": "23andme",
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
        self.assertEqual(variant["agi_record_record_kind"], "array_call")
        self.assertEqual(variant["agi_record_observed_alleles"], ["T", "G"])
        self.assertEqual(variant["agi_record_info"], ".")

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
            self.assertEqual({payload["match_provenance"]["match_basis"] for payload in payloads}, {"multiallelic_alt"})
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
