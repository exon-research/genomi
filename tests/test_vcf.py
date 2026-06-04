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
    ActiveGenomeIndexNeed,
    append_reference_pass,
    connect_existing,
    coverage_query,
    create_active_genome_index,
    ensure_active_genome_index_complete,
    failure_summary,
    active_genome_index_readiness,
    active_genome_index_summary,
    open_reader,
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


class ParallelWorkerScalingTests(unittest.TestCase):
    def _large_plain_vcf(self, tmp: str) -> Path:
        # A real plain-VCF header, then a sparse truncate to a multi-GB logical
        # size so the size threshold is crossed without writing GBs of data.
        vcf = Path(tmp) / "big.vcf"
        vcf.write_text(
            "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n",
            encoding="utf-8",
        )
        with vcf.open("r+b") as handle:
            handle.truncate(4 * 1024 * 1024 * 1024)  # 4 GB sparse
        return vcf

    def test_worker_count_scales_with_host_cores_not_a_fixed_cap(self) -> None:
        from unittest import mock

        from genomi.active_genome_index import _agi_build

        with tempfile.TemporaryDirectory() as tmp:
            vcf = self._large_plain_vcf(tmp)
            # 4 GB / 16 MB = 256, so the file-size bound does not clamp below
            # the core count for these core counts; the result tracks cpu-1.
            with mock.patch.object(_agi_build.os, "cpu_count", return_value=32):
                self.assertEqual(
                    _agi_build._resolved_parallel_workers(vcf, parallel_workers=None, max_records=None),
                    31,
                )
            with mock.patch.object(_agi_build.os, "cpu_count", return_value=12):
                self.assertEqual(
                    _agi_build._resolved_parallel_workers(vcf, parallel_workers=None, max_records=None),
                    11,
                )
            # Explicit override always wins.
            with mock.patch.object(_agi_build.os, "cpu_count", return_value=32):
                self.assertEqual(
                    _agi_build._resolved_parallel_workers(vcf, parallel_workers=3, max_records=None),
                    3,
                )


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

    def test_parallel_index_preserves_query_behavior(self) -> None:
        # The canonical is bgzip with a `.gzi`, so the parse partitions it by
        # bgzip block across worker processes (genomi.active_genome_index.
        # parallel_build). Enough records to span multiple bgzip blocks so the
        # build genuinely runs more than one worker; query behavior must match
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

    def test_parallel_and_serial_agree_on_gvcf_with_reference_blocks(self) -> None:
        # A WGS gVCF is mostly contiguous reference blocks. Both the serial and
        # the bgzip-parallel build coalesce those runs, so the two paths must
        # report identical stats and identical coverage for the same input.
        # The all-variant parallel test above never exercised reference-block
        # coalescing in the parallel worker; this one does.
        def _write_gvcf(path: Path) -> None:
            with path.open("w", encoding="utf-8") as handle:
                handle.write("##fileformat=VCFv4.2\n")
                handle.write('##INFO=<ID=END,Number=1,Type=Integer,Description="End">\n')
                handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n")
                # Contiguous same-GQ reference blocks (coalesce into one run),
                # interrupted by occasional variants, repeated across enough
                # positions to span multiple bgzip blocks.
                for pos in range(1, 6001):
                    if pos % 500 == 0:
                        handle.write(
                            f"1\t{pos}\trs{pos}\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:42:99\n"
                        )
                    else:
                        handle.write(
                            f"1\t{pos}\t.\tA\t<NON_REF>\t.\tPASS\tEND={pos}\tGT:DP:GQ\t0/0:35:50\n"
                        )

        with tempfile.TemporaryDirectory() as tmp:
            serial_vcf = Path(tmp) / "serial.vcf"
            parallel_vcf = Path(tmp) / "parallel.vcf"
            serial_index = Path(tmp) / "serial.sqlite"
            parallel_index = Path(tmp) / "parallel.sqlite"
            _write_gvcf(serial_vcf)
            _write_gvcf(parallel_vcf)

            serial = create_active_genome_index(serial_vcf, serial_index, parallel_workers=1)
            parallel = create_active_genome_index(parallel_vcf, parallel_index, parallel_workers=4)

            serial_coverage = coverage_query(serial_vcf, "1", 1, 6000, serial_index)
            parallel_coverage = coverage_query(parallel_vcf, "1", 1, 6000, parallel_index)

        # Parallelism actually fired and both saw the same raw record counts.
        self.assertEqual(serial["parallel_workers"], 1)
        self.assertGreater(parallel["parallel_workers"], 1)
        self.assertEqual(parallel["stats"]["total_records"], serial["stats"]["total_records"])
        self.assertEqual(parallel["stats"]["variant_records"], serial["stats"]["variant_records"])
        self.assertEqual(parallel["stats"]["reference_records"], serial["stats"]["reference_records"])
        # Coalesced reference runs cover the same positions regardless of path.
        self.assertEqual(parallel_coverage["covered_fraction"], serial_coverage["covered_fraction"])

    def test_two_phase_gvcf_build_is_variants_ready_then_completed(self) -> None:
        # A gVCF can be built variants-first: Phase A stores every variant and
        # marks the index variants_ready (queryable now); Phase B appends the
        # reference-block tail and flips it to completed. The variants_ready
        # index must match the variant rows of a single-phase build, and the
        # completed two-phase index must be byte-for-byte equivalent in counts.
        def _write_gvcf(path: Path) -> None:
            with path.open("w", encoding="utf-8") as handle:
                handle.write("##fileformat=VCFv4.2\n")
                handle.write('##INFO=<ID=END,Number=1,Type=Integer,Description="End">\n')
                handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n")
                for pos in range(1, 6001):
                    if pos % 500 == 0:
                        handle.write(f"1\t{pos}\trs{pos}\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:42:99\n")
                    else:
                        handle.write(f"1\t{pos}\t.\tA\t<NON_REF>\t.\tPASS\tEND={pos}\tGT:DP:GQ\t0/0:35:50\n")

        with tempfile.TemporaryDirectory() as tmp:
            full_vcf = Path(tmp) / "full.vcf"
            two_vcf = Path(tmp) / "two.vcf"
            full_index = Path(tmp) / "full.sqlite"
            two_index = Path(tmp) / "two.sqlite"
            _write_gvcf(full_vcf)
            _write_gvcf(two_vcf)

            full = create_active_genome_index(full_vcf, full_index, parallel_workers=4)
            phase_a = create_active_genome_index(two_vcf, two_index, parallel_workers=4, defer_reference=True)

            # Phase A: variants_ready, parallelism fired, and stats already final
            # (every record was counted even though reference rows aren't stored).
            self.assertEqual(phase_a["status"], "variants_ready")
            self.assertTrue(phase_a["reference_pending"])
            self.assertGreater(phase_a["parallel_workers"], 1)
            self.assertEqual(phase_a["stats"], full["stats"])

            readiness_a = active_genome_index_readiness(two_index)
            self.assertEqual(readiness_a["status"], "variants_ready")
            self.assertFalse(readiness_a["complete"])
            self.assertTrue(readiness_a["variants_ready"])
            self.assertTrue(readiness_a["reference_pending"])
            # The relaxed gate must let variant reads through at variants_ready.
            ensure_active_genome_index_complete(two_index)

            # Variant lookups are correct now; reference coverage is provisional
            # (empty). reference_pending is surfaced by the central reader's
            # parse-state (and stamped on operation results by the dispatch
            # chokepoint) — not by the library coverage_query itself.
            self.assertEqual(len(query_rsid(two_vcf, "rs500", two_index)), 1)
            cov_a = coverage_query(two_vcf, "1", 1, 499, two_index)
            self.assertEqual(cov_a["covered_fraction"], 0.0)
            reader_a = open_reader(two_index, need=ActiveGenomeIndexNeed.REFERENCE)
            self.assertTrue(reader_a.reference_pending)
            self.assertTrue(reader_a.parse_state()["reference_pending"])

            # Phase B: append the reference tail, flip to completed.
            phase_b = append_reference_pass(two_index)
            self.assertEqual(phase_b["status"], "completed")
            readiness_b = active_genome_index_readiness(two_index)
            self.assertEqual(readiness_b["status"], "completed")
            self.assertTrue(readiness_b["complete"])

            # Completed two-phase coverage now matches the single-phase build,
            # segment-for-segment, across the whole region and carries no pending
            # flag. (Raw stored row counts can differ by coalescing granularity /
            # shard-seam count — the semantic invariant is coverage + stats, the
            # same equivalence test_parallel_and_serial_agree relies on.)
            cov_b = coverage_query(two_vcf, "1", 1, 6000, two_index)
            cov_full = coverage_query(full_vcf, "1", 1, 6000, full_index)
            self.assertEqual(cov_b["covered_fraction"], cov_full["covered_fraction"])
            self.assertEqual(cov_b["covered_bases"], cov_full["covered_bases"])
            self.assertEqual(cov_b["segments"], cov_full["segments"])
            self.assertNotIn("reference_pending", cov_b)
            self.assertFalse(open_reader(two_index, need=ActiveGenomeIndexNeed.REFERENCE).reference_pending)
            # The completed two-phase index reports the same stats as single-phase.
            self.assertEqual(
                active_genome_index_summary(two_index)["stats"],
                active_genome_index_summary(full_index)["stats"],
            )

            # Idempotent: re-running Phase B on a completed index is a no-op.
            again = append_reference_pass(two_index)
            self.assertEqual(again["status"], "completed")

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
            # The line qualifies only through Sample1's ALT, but the non-variant
            # `unknown` (0/0) column must still be emitted so the row matches the
            # #CHROM header — otherwise strict parsers (PharmCAT) reject the file
            # with "got 10 vs. 11 columns".
            self.assertEqual(records[0].split("\t"), ["1", "100", "rs1", "A", "G", ".", "PASS", ".", "GT", "0/0", "0/1"])

    def test_export_variants_rows_match_header_width_for_multi_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf_path = Path(tmp) / "multi.vcf"
            active_genome_index_path = Path(tmp) / "multi.sqlite"
            output_path = Path(tmp) / "variants.vcf"
            vcf_path.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tunknown\tSample1",
                        # Each line qualifies through a different sample, exercising
                        # both column positions for the dropped non-variant call.
                        "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/0\t0/1",
                        "1\t200\trs2\tC\tT\t.\tPASS\t.\tGT\t0/1\t1/1",
                        "1\t300\trs3\tG\tA\t.\tPASS\t.\tGT\t1/1\t0/0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            create_active_genome_index(vcf_path, active_genome_index_path)

            export_variants(vcf_path, output_path, active_genome_index_path)
            lines = output_path.read_text(encoding="utf-8").splitlines()
            header_width = next(len(line.split("\t")) for line in lines if line.startswith("#CHROM"))
            data_rows = [line.split("\t") for line in lines if not line.startswith("#")]

            self.assertEqual(len(data_rows), 3)
            for row in data_rows:
                self.assertEqual(len(row), header_width, f"ragged row breaks strict VCF parsers: {row}")

    def test_preflight_is_bounded(self) -> None:
        result = preflight(FIXTURE, scan_records=2)

        self.assertEqual(result["scan_record_limit"], 2)
        self.assertEqual(result["scan_summary"]["scanned_records"], 2)
        self.assertEqual(result["scan_summary"]["variant_records"], 1)
        self.assertIn("ALT='.' records are reference or gVCF block records, not variant calls.", result["notes"])


class CanonicalCompressionTests(unittest.TestCase):
    """The canonical builder decompresses bzip2/xz intakes, not just gzip.

    Some PGP exports (and Complete Genomics) ship VCFs as ``.vcf.bz2``. Feeding
    those bytes to bgzip as if they were plain text produced garbage; the
    builder must decompress them first.
    """

    _VCF_BODY = (
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n"
        "1\t800007\trs6681049\tT\tC\t.\t.\t.\tGT\t1/1\n"
        "1\t861808\trs13302982\tA\tG\t.\t.\t.\tGT\t1/1\n"
    )

    def _assert_canonical_roundtrips(self, intake: Path) -> None:
        import shutil

        from genomi.active_genome_index.canonical import build_canonical_bgzip

        if shutil.which("bgzip") is None:
            self.skipTest("bgzip CLI not available")
        with tempfile.TemporaryDirectory() as work:
            result = build_canonical_bgzip(intake, work)
            canonical = Path(result["canonical_path"])
            self.assertTrue(canonical.exists())
            with gzip.open(canonical, "rt", encoding="utf-8") as handle:
                recovered = handle.read()
            self.assertEqual(recovered, self._VCF_BODY)

    def test_bzip2_vcf_is_canonicalized(self) -> None:
        import bz2

        with tempfile.TemporaryDirectory() as tmp:
            intake = Path(tmp) / "sample.vcf.bz2"
            intake.write_bytes(bz2.compress(self._VCF_BODY.encode()))
            self._assert_canonical_roundtrips(intake)

    def test_xz_vcf_is_canonicalized(self) -> None:
        import lzma

        with tempfile.TemporaryDirectory() as tmp:
            intake = Path(tmp) / "sample.vcf.xz"
            intake.write_bytes(lzma.compress(self._VCF_BODY.encode()))
            self._assert_canonical_roundtrips(intake)


if __name__ == "__main__":
    unittest.main()
