from __future__ import annotations

import gzip
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from genomi.active_genome_index.export import export_variants
from genomi.active_genome_index.active_genome_index import (
    connect_existing,
    coverage_query,
    create_active_genome_index,
    failure_summary,
    active_genome_index_readiness,
    active_genome_index_summary,
    preflight,
    query_region,
    query_rsid,
    query_variant,
    read_header_from_active_genome_index,
)
from genomi.active_genome_index.vcf import (
    extract_info_genes,
    iter_records,
    iter_sample_records,
    parse_info,
    parse_region,
    parse_sample,
    read_header,
    read_header_lines,
)

FIXTURE = Path(__file__).parent / "data" / "tiny.gvcf.vcf"


class VcfParsingTests(unittest.TestCase):
    def test_header_parses_metadata_and_samples(self) -> None:
        header = read_header(FIXTURE)

        self.assertEqual(header.first_meta_value("fileformat"), "VCFv4.2")
        self.assertEqual(header.first_meta_value("reference"), "GRCh38.p13")
        self.assertEqual(header.samples, ["SAMPLE1"])
        self.assertEqual(header.contigs(), ["1"])

    def test_header_lines_include_chrom_line(self) -> None:
        lines = read_header_lines(FIXTURE)

        self.assertTrue(lines[0].startswith("##fileformat="))
        self.assertTrue(lines[-1].startswith("#CHROM"))

    def test_suffixless_gzip_vcf_is_detected_by_magic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "PGP_VCF_WITHOUT_GZ_SUFFIX"
            content = (
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1\n"
            )
            with gzip.open(vcf_path, "wb") as handle:
                handle.write(content.encode("utf-8"))

            header = read_header(vcf_path)
            records = list(iter_records(vcf_path))

        self.assertEqual(header.samples, ["SAMPLE"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_id, "rs1")

    def test_record_properties_distinguish_reference_blocks_from_variants(self) -> None:
        records = list(iter_records(FIXTURE))

        self.assertEqual(records[0].end, 10249)
        self.assertFalse(records[0].is_variant)
        self.assertEqual(records[1].record_id, "rs199706086")
        self.assertEqual(records[1].alts, ["C"])
        self.assertTrue(records[1].is_variant)
        self.assertEqual(records[1].genotype, "0/1")
        self.assertEqual(records[1].depth, 50)
        self.assertEqual(records[1].genotype_quality, 124)

    def test_variant_status_uses_sample_genotype_and_ignores_non_ref_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "sample-aware.vcf"
            vcf_path.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/0",
                        "1\t101\t.\tA\t<NON_REF>\t.\tPASS\tEND=110\tGT\t0/0",
                        "1\t111\trs2\tA\tG,<NON_REF>\t.\tPASS\t.\tGT\t0/1",
                        "1\t112\t.\tA\tG,<NON_REF>\t.\tPASS\t.\tGT\t0/2",
                        "1\t113\trs3\tA\tG\t.\tPASS\t.\tGT\t0/1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            records = list(iter_records(vcf_path))

        self.assertEqual([record.is_variant for record in records], [False, False, True, False, True])

    def test_field_parsers(self) -> None:
        self.assertEqual(parse_info("END=10249;FLAG"), {"END": "10249", "FLAG": True})
        self.assertEqual(parse_sample("GT:DP:GQ", "0/1:50:124"), {"GT": "0/1", "DP": "50", "GQ": "124"})
        self.assertEqual(parse_region("1:10,001-10,249"), ("1", 10001, 10249))
        self.assertEqual(extract_info_genes("ANN=G|missense_variant|MODERATE|HFE|ENSG1"), ["HFE"])
        self.assertEqual(extract_info_genes("SNPEFF_GENE_NAME=BRCA1;SNPEFF_IMPACT=HIGH"), ["BRCA1"])

    def test_iter_sample_records_preserves_multiple_sample_genotypes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "multi.vcf"
            vcf_path.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tunknown\tSample1",
                        "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/0:20:60\t0/1:22:70",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            records = list(iter_sample_records(vcf_path))

        self.assertEqual([record.sample_name for record in records], ["unknown", "Sample1"])
        self.assertEqual([record.sample_index for record in records], [0, 1])
        self.assertEqual([record.genotype for record in records], ["0/0", "0/1"])


class IndexTests(unittest.TestCase):
    def test_index_and_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active_genome_index_path = Path(tmp) / "tiny.sqlite"

            summary = create_active_genome_index(FIXTURE, active_genome_index_path)

            self.assertEqual(summary["stats"]["total_records"], 5)
            self.assertEqual(summary["stats"]["variant_records"], 2)
            self.assertEqual(summary["stats"]["reference_records"], 3)

            rsid_records = query_rsid(FIXTURE, "rs199706086", active_genome_index_path)
            self.assertEqual(len(rsid_records), 1)
            self.assertEqual(rsid_records[0]["variant_key"], "1:10250:A:C")

            variant_records = query_variant(FIXTURE, "1", 10257, "A", "C", active_genome_index_path)
            self.assertEqual(len(variant_records), 1)
            self.assertEqual(variant_records[0]["id"], "rs111200574")

            region_records = query_region(FIXTURE, "1", 10250, 10257, active_genome_index_path, variants_only=True)
            self.assertEqual([record["pos"] for record in region_records], [10250, 10257])

            pass_only_records = query_region(
                FIXTURE,
                "1",
                10595,
                10595,
                active_genome_index_path,
                variants_only=False,
                pass_only=True,
            )
            self.assertEqual(pass_only_records, [])

            coverage = coverage_query(FIXTURE, "1", 10001, 10249, active_genome_index_path)
            self.assertEqual(coverage["covered_fraction"], 1)
            self.assertEqual(coverage["segments"], [{"start": 10001, "end": 10249}])

            failures = failure_summary(FIXTURE, active_genome_index_path, example_limit=2)
            self.assertEqual(failures["filter"], "FAIL")
            self.assertEqual(failures["by_variant_status"], [{"status": "reference_or_no_call", "records": 1}])
            self.assertEqual(len(failures["examples"]), 1)

    def test_create_active_genome_index_reuses_existing_matching_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active_genome_index_path = Path(tmp) / "tiny.sqlite"

            first = create_active_genome_index(FIXTURE, active_genome_index_path)
            first_mtime = active_genome_index_path.stat().st_mtime_ns
            second = create_active_genome_index(FIXTURE, active_genome_index_path)

            self.assertEqual(first["status"], "completed")
            self.assertEqual(second["status"], "cached")
            self.assertEqual(second["stats"], first["stats"])
            self.assertEqual(active_genome_index_path.stat().st_mtime_ns, first_mtime)

    def test_create_active_genome_index_reuses_full_index_for_later_capped_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active_genome_index_path = Path(tmp) / "tiny.sqlite"

            first = create_active_genome_index(FIXTURE, active_genome_index_path)
            first_mtime = active_genome_index_path.stat().st_mtime_ns
            second = create_active_genome_index(FIXTURE, active_genome_index_path, max_records=1)

            self.assertEqual(first["status"], "completed")
            self.assertEqual(first["stats"]["total_records"], 5)
            self.assertEqual(second["status"], "cached")
            self.assertEqual(second["stats"], first["stats"])
            self.assertEqual(active_genome_index_path.stat().st_mtime_ns, first_mtime)

    def test_create_active_genome_index_rebuilds_capped_index_for_later_full_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active_genome_index_path = Path(tmp) / "tiny.sqlite"

            first = create_active_genome_index(FIXTURE, active_genome_index_path, max_records=1)
            second = create_active_genome_index(FIXTURE, active_genome_index_path)

            self.assertEqual(first["status"], "completed")
            self.assertEqual(first["stats"]["total_records"], 1)
            self.assertEqual(second["status"], "completed")
            self.assertEqual(second["stats"]["total_records"], 5)

    def test_create_active_genome_index_rebuilds_incomplete_existing_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active_genome_index_path = Path(tmp) / "tiny.sqlite"

            create_active_genome_index(FIXTURE, active_genome_index_path)
            with sqlite3.connect(active_genome_index_path) as connection:
                connection.execute(
                    "update metadata set value = ? where key = 'active_genome_index_complete'",
                    (json.dumps(False),),
                )
                connection.execute(
                    "update metadata set value = ? where key = 'active_genome_index_build_status'",
                    (json.dumps("in_progress"),),
                )
                connection.execute("update stats set value = '999' where key = 'total_records'")
                connection.commit()

            readiness = active_genome_index_readiness(active_genome_index_path)
            second = create_active_genome_index(FIXTURE, active_genome_index_path)

        self.assertFalse(readiness["complete"])
        self.assertEqual(second["status"], "completed")
        self.assertTrue(second["active_genome_index_complete"])
        self.assertEqual(second["stats"]["total_records"], 5)

    def test_queries_reject_incomplete_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active_genome_index_path = Path(tmp) / "tiny.sqlite"
            create_active_genome_index(FIXTURE, active_genome_index_path)
            with sqlite3.connect(active_genome_index_path) as connection:
                connection.execute(
                    "update metadata set value = ? where key = 'active_genome_index_complete'",
                    (json.dumps(False),),
                )
                connection.commit()

            summary = active_genome_index_summary(active_genome_index_path)
            with self.assertRaisesRegex(RuntimeError, "Active Genome Index is not complete"):
                query_rsid(FIXTURE, "rs199706086", active_genome_index_path)

        self.assertFalse(summary["active_genome_index_readiness"]["complete"])
        self.assertEqual(summary["active_genome_index_readiness"]["reason"], "completion_marker_missing_or_false")

    def test_create_active_genome_index_reuses_index_after_same_sized_materialized_vcf_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "input.vcf"
            active_genome_index_path = Path(tmp) / "tiny.sqlite"
            vcf_path.write_bytes(FIXTURE.read_bytes())

            first = create_active_genome_index(vcf_path, active_genome_index_path)
            first_mtime = active_genome_index_path.stat().st_mtime_ns
            os.utime(vcf_path, ns=(vcf_path.stat().st_atime_ns, vcf_path.stat().st_mtime_ns + 1_000_000_000))
            second = create_active_genome_index(vcf_path, active_genome_index_path)

            self.assertEqual(first["status"], "completed")
            self.assertEqual(second["status"], "cached")
            self.assertEqual(second["stats"], first["stats"])
            self.assertEqual(active_genome_index_path.stat().st_mtime_ns, first_mtime)

    def test_read_queries_do_not_create_missing_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active_genome_index_path = Path(tmp) / "missing.sqlite"

            with self.assertRaises(FileNotFoundError):
                active_genome_index_summary(active_genome_index_path)

            self.assertFalse(active_genome_index_path.exists())

    def test_index_queries_return_each_sample_genotype(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "multi.vcf"
            active_genome_index_path = Path(tmp) / "multi.sqlite"
            vcf_path.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tunknown\tSample1",
                        "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/0:20:60\t0/1:22:70",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            summary = create_active_genome_index(vcf_path, active_genome_index_path)
            records = query_rsid(vcf_path, "rs1", active_genome_index_path)

        self.assertEqual(summary["stats"]["total_records"], 2)
        self.assertEqual([record["sample_name"] for record in records], ["unknown", "Sample1"])
        self.assertEqual([record["sample_index"] for record in records], [0, 1])
        self.assertEqual([record["genotype"] for record in records], ["0/0", "0/1"])

    def test_index_preserves_vcf_info_gene_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "ann.vcf"
            active_genome_index_path = Path(tmp) / "ann.sqlite"
            vcf_path.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1",
                        "1\t100\trs1\tA\tG\t.\tPASS\tANN=G|missense_variant|MODERATE|HFE|ENSG1\tGT\t0/1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            create_active_genome_index(vcf_path, active_genome_index_path)
            records = query_rsid(vcf_path, "rs1", active_genome_index_path)

        self.assertEqual(records[0]["info_genes"], ["HFE"])

    def test_parallel_index_preserves_query_semantics(self) -> None:
        # The canonical is bgzip with a `.gzi`, so the parse partitions it by
        # bgzip block across worker processes (genomi.active_genome_index.
        # parallel_build). Enough records to span multiple bgzip blocks so the
        # build genuinely runs more than one worker; query semantics must match
        # a single-threaded build.
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "parallel.vcf"
            active_genome_index_path = Path(tmp) / "parallel.sqlite"
            with vcf_path.open("w", encoding="utf-8") as handle:
                handle.write("##fileformat=VCFv4.2\n")
                handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n")
                for pos in range(1, 8001):
                    handle.write(
                        f"1\t{pos}\trs{pos}\tA\tG\t.\tPASS\tANN=G|missense_variant|MODERATE|HFE|ENSG1;END={pos}\tGT:DP:GQ\t0/1:42:99\n"
                    )

            summary = create_active_genome_index(vcf_path, active_genome_index_path, parallel_workers=4)
            records = query_rsid(vcf_path, "rs7999", active_genome_index_path)

        # Parallelism actually fired (multiple bgzip blocks → multiple workers).
        self.assertGreater(summary["parallel_workers"], 1)
        self.assertEqual(summary["stats"]["total_records"], 8000)
        self.assertEqual(summary["stats"]["variant_records"], 8000)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["rsid"], "rs7999")
        self.assertEqual(records[0]["info_genes"], ["HFE"])

    def test_header_reconstructable_from_index_after_source_removed(self) -> None:
        # Parse self-sufficiency: the source VCF header is persisted into the
        # index at parse time, so it reconstructs from the structured index
        # alone — with the source and canonical bgzip both deleted.
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "withheader.vcf"
            agi_path = Path(tmp) / "withheader.sqlite"
            meta = [
                "##fileformat=VCFv4.2",
                "##reference=GRCh38",
                '##INFO=<ID=END,Number=1,Type=Integer,Description="End">',
                '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            ]
            chrom_line = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1"
            vcf_path.write_text(
                "\n".join(meta + [chrom_line, "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1"]) + "\n",
                encoding="utf-8",
            )
            create_active_genome_index(vcf_path, agi_path)
            # Remove the source AND the index-owned canonical bgzip so a header
            # read can only come from the structured index.
            vcf_path.unlink()
            for stale in (agi_path.parent / "source").glob("*"):
                stale.unlink()

            with connect_existing(agi_path) as connection:
                header = read_header_from_active_genome_index(connection)

        self.assertEqual(header.first_meta_value("fileformat"), "VCFv4.2")
        self.assertEqual(header.first_meta_value("reference"), "GRCh38")
        self.assertIn("##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">", header.meta)
        self.assertEqual(header.samples, ["SAMPLE1"])

    def test_index_queries_are_available_after_raw_vcf_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "digitized.vcf"
            active_genome_index_path = Path(tmp) / "digitized.sqlite"
            vcf_path.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1",
                        "1\t100\trs1\tA\tG\t.\tPASS\tANN=G|missense_variant|MODERATE|HFE|ENSG1\tGT:DP:GQ\t0/1:42:99",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            create_active_genome_index(vcf_path, active_genome_index_path)
            vcf_path.unlink()

            records = query_rsid(vcf_path, "rs1", active_genome_index_path)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["genotype"], "0/1")
        self.assertEqual(records[0]["sample"], {"GT": "0/1", "DP": "42", "GQ": "99"})
        self.assertEqual(records[0]["sample_raw"], "0/1:42:99")
        self.assertEqual(records[0]["format"], ["GT", "DP", "GQ"])
        self.assertEqual(records[0]["format_raw"], "GT:DP:GQ")
        self.assertEqual(records[0]["info"]["ANN"], "G|missense_variant|MODERATE|HFE|ENSG1")
        self.assertEqual(records[0]["info_genes"], ["HFE"])

    def test_index_includes_offset_sample_lookup_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active_genome_index_path = Path(tmp) / "tiny.sqlite"
            create_active_genome_index(FIXTURE, active_genome_index_path)

            with sqlite3.connect(active_genome_index_path) as connection:
                index_names = {
                    row[0]
                    for row in connection.execute(
                        "select name from sqlite_master where type = 'index'"
                    )
                }

        self.assertIn("records_offset_sample_idx", index_names)
        self.assertIn("records_export_idx", index_names)

    def test_index_build_does_not_leave_bulk_load_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active_genome_index_path = Path(tmp) / "tiny.sqlite"

            create_active_genome_index(FIXTURE, active_genome_index_path)

            self.assertFalse(Path(f"{active_genome_index_path}-wal").exists())
            self.assertFalse(Path(f"{active_genome_index_path}-journal").exists())

    def test_point_region_query_finds_covering_record_beyond_lookback_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "spanning.vcf"
            active_genome_index_path = Path(tmp) / "spanning.sqlite"
            rows = [
                "##fileformat=VCFv4.2",
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                "1\t100\t.\tA\t.\t.\tPASS\tEND=1000\tGT:DP:GQ\t0/0:30:60",
            ]
            rows.extend(
                f"1\t{pos}\trs{pos}\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:20:50"
                for pos in range(900, 930)
            )
            vcf_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

            create_active_genome_index(vcf_path, active_genome_index_path)
            records = query_region(vcf_path, "1", 950, 950, active_genome_index_path, variants_only=False)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["pos"], 100)
        self.assertEqual(records[0]["end"], 1000)

    def test_export_variants_writes_plain_vcf_from_index_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active_genome_index_path = Path(tmp) / "tiny.sqlite"
            output_path = Path(tmp) / "variants.vcf"
            create_active_genome_index(FIXTURE, active_genome_index_path)

            result = export_variants(
                FIXTURE,
                output_path,
                active_genome_index_path,
                pass_only=True,
                primary_contigs_only=True,
            )

            self.assertEqual(result["exported_records"], 2)
            lines = output_path.read_text(encoding="utf-8").splitlines()
            self.assertIn("##genomiExport=variants", lines)
            records = [line for line in lines if not line.startswith("#")]
            self.assertEqual(len(records), 2)
            self.assertTrue(records[0].startswith("1\t10250\trs199706086"))
            self.assertTrue(records[1].startswith("1\t10257\trs111200574"))

            cached = export_variants(
                FIXTURE,
                output_path,
                active_genome_index_path,
                pass_only=True,
                primary_contigs_only=True,
            )
            self.assertEqual(cached["status"], "cached")
            self.assertEqual(cached["exported_records"], 2)

    def test_export_variants_can_rewrite_chr_prefixed_contigs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "chr.vcf"
            active_genome_index_path = Path(tmp) / "chr.sqlite"
            output_path = Path(tmp) / "variants.vcf"
            vcf_path.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "##contig=<ID=chr1,length=248956422>",
                        "##contig=<ID=chrM,length=16569>",
                        "##FILTER=<ID=PASS,Description=\"All filters passed\">",
                        "##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1",
                        "chr1\t10250\trs199706086\tA\tC\t123.38\tPASS\t.\tGT\t0/1",
                        "chrM\t150\t.\tA\tG\t50\tPASS\t.\tGT\t0/1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            create_active_genome_index(vcf_path, active_genome_index_path)

            result = export_variants(
                vcf_path,
                output_path,
                active_genome_index_path,
                pass_only=True,
                primary_contigs_only=True,
                chrom_style="no-chr",
            )

            self.assertEqual(result["exported_records"], 2)
            lines = output_path.read_text(encoding="utf-8").splitlines()
            self.assertIn("##contig=<ID=1,length=248956422>", lines)
            self.assertIn("##contig=<ID=MT,length=16569>", lines)
            records = [line for line in lines if not line.startswith("#")]
            self.assertTrue(records[0].startswith("1\t10250\trs199706086"))
            self.assertTrue(records[1].startswith("MT\t150\t."))

    def test_export_variants_deduplicates_multi_sample_index_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "multi.vcf"
            active_genome_index_path = Path(tmp) / "multi.sqlite"
            output_path = Path(tmp) / "variants.vcf"
            vcf_path.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tunknown\tSample1",
                        "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/0\t0/1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            create_active_genome_index(vcf_path, active_genome_index_path)

            result = export_variants(vcf_path, output_path, active_genome_index_path)
            records = [
                line for line in output_path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")
            ]

            self.assertEqual(result["candidate_records"], 1)
            self.assertEqual(result["exported_records"], 1)
            self.assertEqual(len(records), 1)

    def test_preflight_is_bounded(self) -> None:
        result = preflight(FIXTURE, scan_records=2)

        self.assertEqual(result["scan_record_limit"], 2)
        self.assertEqual(result["scan_summary"]["scanned_records"], 2)
        self.assertEqual(result["scan_summary"]["variant_records"], 1)
        self.assertIn("ALT='.' records are reference or gVCF block records, not variant calls.", result["notes"])


if __name__ == "__main__":
    unittest.main()
