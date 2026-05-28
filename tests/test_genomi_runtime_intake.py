from __future__ import annotations

import gzip
import json
import os
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from genomi.operations import call_operation

from _genomi_runtime_helpers import GenomiRuntimeTestCase


class GenomiRuntimeIntakeTests(GenomiRuntimeTestCase):
    def test_active_genome_index_parse_materializes_vcf_index_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("targeted.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )

                self.approve_agi_access()
                parsed = call_operation(
                    "genomi.parse_source",
                    {"source": str(vcf), "genome_build": "GRCh38"},
                )

                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "vcf")
                self.assertEqual(parsed["annotation_scope"], "active_genome_index")
                self.assertTrue(parsed["active_genome_index"]["digitized"])
                self.assertEqual([step["name"] for step in parsed["steps"]], ["build-active-genome-index"])
                self.assertEqual(parsed["warnings"], [])
                self.assertEqual(set(parsed["outputs"]), {"active_genome_index_path"})
                self.assertNotIn("static_profile", parsed)
                self.assertNotIn("long_running_steps_deferred", parsed)
                self.assertNotIn("clinvar_matches", parsed["outputs"])
                self.assertNotIn(str(vcf), json.dumps(parsed))
                self.assertNotIn(str(vcf.resolve(strict=False)), json.dumps(parsed))

                lookup = call_operation("variant.resolve", {"rsid": "rs4244285"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
                match = lookup["sample_context"]["matches"][0]
                self.assertEqual(match["genotype"], "0/1")
                self.assertEqual(match["source_format"], "vcf")
                self.assertNotIn(str(vcf), json.dumps(lookup))
                self.assertNotIn(str(vcf.resolve(strict=False)), json.dumps(lookup))
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_defaults_to_vcf_index_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("targeted.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )

                self.approve_agi_access()
                parsed = call_operation(
                    "genomi.parse_source",
                    {"source": str(vcf), "genome_build": "GRCh38"},
                )

                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["annotation_scope"], "active_genome_index")
                self.assertEqual([step["name"] for step in parsed["steps"]], ["build-active-genome-index"])
                lookup = call_operation("variant.resolve", {"rsid": "rs4244285"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_omits_static_materialization_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("targeted.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )

                self.approve_agi_access()
                parsed = call_operation(
                    "genomi.parse_source",
                    {"source": str(vcf), "genome_build": "GRCh38"},
                )

                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["annotation_scope"], "active_genome_index")
                self.assertEqual(parsed["warnings"], [])
                self.assertNotIn("static_profile", parsed)
                self.assertNotIn("long_running_steps_deferred", parsed)
                self.assertNotIn("evidence_summary", parsed)
                self.assertNotIn("clinvar_matches", parsed["outputs"])
                lookup = call_operation("variant.resolve", {"rsid": "rs4244285"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_accepts_23andme_raw_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                raw = Path("genome_James_Jones_v5_Full_20230726173828.txt")
                raw.write_text(
                    "# This data file generated by 23andMe at: Wed Jul 26 17:38:28 2023\n"
                    "# We are using reference human assembly build 37 (also known as Annotation Release 104).\n"
                    "# rsid\tchromosome\tposition\tgenotype\n"
                    "rs123\t1\t100\tAG\n"
                    "rs999\t2\t200\t--\n",
                    encoding="utf-8",
                )

                self.approve_agi_access()
                parsed = call_operation("genomi.parse_source", {"source": str(raw)})
                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "23andme")
                self.assertIn("active_genome_index", parsed)
                self.assertNotIn(str(raw.resolve(strict=False)), json.dumps(parsed))
                self.assertNotIn(str(raw), json.dumps(parsed))

                current = call_operation("genomi.describe_context")
                self.assertTrue(current["has_active_genome_index"])
                self.assertEqual(current["active_genome_index"]["source_format"], "23andme")
                self.assertNotIn(str(raw.resolve(strict=False)), json.dumps(current))

                lookup = call_operation("variant.resolve", {"rsid": "rs123"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
                match = lookup["sample_context"]["matches"][0]
                self.assertEqual(match["genotype"], "AG")
                self.assertEqual(match["source_format"], "23andme")
                self.assertEqual(match["observation_semantics"]["kind"], "consumer_genotype_array_call")
                self.assertNotIn(str(raw.resolve(strict=False)), json.dumps(lookup))
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_accepts_ancestrydna_raw_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                raw = Path("AncestryDNA.txt")
                raw.write_text(
                    "#AncestryDNA raw data download\n"
                    "#This file was generated by AncestryDNA at: 11/18/2024 17:49:40 UTC\n"
                    "#Data was collected using AncestryDNA array version: V2.0\n"
                    "#Genetic data is reported using human reference build 37.1 coordinates.\n"
                    "rsid\tchromosome\tposition\tallele1\tallele2\n"
                    "rs3131972\t1\t752721\tA\tG\n"
                    "rs999\t2\t200\t0\t0\n",
                    encoding="utf-8",
                )

                self.approve_agi_access()
                parsed = call_operation("genomi.parse_source", {"source": str(raw)})
                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "ancestrydna")
                self.assertEqual(parsed["source_kind"], "consumer_genotype_array")
                self.assertIn("active_genome_index", parsed)
                self.assertNotIn(str(raw.resolve(strict=False)), json.dumps(parsed))
                self.assertNotIn(str(raw), json.dumps(parsed))

                current = call_operation("genomi.describe_context")
                self.assertTrue(current["has_active_genome_index"])
                self.assertEqual(current["active_genome_index"]["source_format"], "ancestrydna")
                self.assertNotIn(str(raw.resolve(strict=False)), json.dumps(current))

                lookup = call_operation("variant.resolve", {"rsid": "rs3131972"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
                match = lookup["sample_context"]["matches"][0]
                self.assertEqual(match["genotype"], "AG")
                self.assertEqual(match["source_format"], "ancestrydna")
                self.assertEqual(match["observation_semantics"]["kind"], "consumer_genotype_array_call")
                self.assertEqual(match["observation_semantics"]["source_format"], "ancestrydna")
                self.assertNotIn(str(raw.resolve(strict=False)), json.dumps(lookup))
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_accepts_ancestrydna_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                archive_path = Path("dna-data-2023-04-26.zip")
                content = (
                    "#AncestryDNA raw data download\n"
                    "#This file was generated by AncestryDNA at: 04/26/2023 04:30:29 UTC\n"
                    "#Data is formatted using AncestryDNA converter version: V1.0\n"
                    "#Genetic data is provided using human reference build 37.1 coordinates.\n"
                    "rsid\tchromosome\tposition\tallele1\tallele2\n"
                    "rs3131972\t1\t752721\tG\tG\n"
                )
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr("AncestryDNA.txt", content)

                self.approve_agi_access()
                parsed = call_operation("genomi.parse_source", {"source": str(archive_path)})
                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "ancestrydna")
                self.assertEqual(parsed["source_member"], "AncestryDNA.txt")
                self.assertNotIn(str(archive_path.resolve(strict=False)), json.dumps(parsed))

                lookup = call_operation("variant.resolve", {"rsid": "rs3131972"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
                self.assertEqual(lookup["sample_context"]["matches"][0]["genotype"], "GG")
                self.assertEqual(lookup["sample_context"]["matches"][0]["source_format"], "ancestrydna")
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_accepts_myheritage_raw_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                raw = Path("MyHeritage_raw_dna_data.csv")
                raw.write_text(
                    "# MyHeritage DNA raw data.\n"
                    "# This file was generated on 2018-01-01 02:34:37 \n"
                    "# Reported with respect to human reference build 37.\n"
                    "RSID,CHROMOSOME,POSITION,RESULT\n"
                    '"rs3131972","1","752721","GG"\n'
                    '"rs999","2","200","--"\n',
                    encoding="utf-8",
                )

                self.approve_agi_access()
                parsed = call_operation("genomi.parse_source", {"source": str(raw)})
                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "myheritage")
                self.assertEqual(parsed["source_kind"], "consumer_genotype_array")
                self.assertEqual(parsed["provider"], "myheritage")

                lookup = call_operation("variant.resolve", {"rsid": "rs3131972"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
                match = lookup["sample_context"]["matches"][0]
                self.assertEqual(match["genotype"], "GG")
                self.assertEqual(match["source_format"], "myheritage")
                self.assertEqual(match["observation_semantics"]["kind"], "consumer_genotype_array_call")
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_accepts_myheritage_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                archive_path = Path("MyHeritage_raw_dna_data.zip")
                content = (
                    "# MyHeritage DNA raw data.\n"
                    "# Reported with respect to human reference build 37.\n"
                    "RSID,CHROMOSOME,POSITION,RESULT\n"
                    '"rs3131972","1","752721","GG"\n'
                )
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr("MyHeritage_raw_dna_data.csv", content)

                self.approve_agi_access()
                parsed = call_operation("genomi.parse_source", {"source": str(archive_path)})
                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "myheritage")
                self.assertEqual(parsed["source_member"], "MyHeritage_raw_dna_data.csv")

                lookup = call_operation("variant.resolve", {"rsid": "rs3131972"})
                self.assertEqual(lookup["sample_context"]["matches"][0]["genotype"], "GG")
                self.assertEqual(lookup["sample_context"]["matches"][0]["source_format"], "myheritage")
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_accepts_ftdna_raw_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                raw = Path("691234_Autosomal_o37_Results_20190228.csv")
                raw.write_text(
                    "RSID,CHROMOSOME,POSITION,RESULT\n"
                    '"rs3131972","1","752721","GG"\n'
                    '"rs999","2","200","--"\n',
                    encoding="utf-8",
                )

                self.approve_agi_access()
                parsed = call_operation("genomi.parse_source", {"source": str(raw)})
                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "ftdna")
                self.assertEqual(parsed["source_kind"], "consumer_genotype_array")
                self.assertEqual(parsed["provider"], "ftdna")

                lookup = call_operation("variant.resolve", {"rsid": "rs3131972"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
                match = lookup["sample_context"]["matches"][0]
                self.assertEqual(match["genotype"], "GG")
                self.assertEqual(match["source_format"], "ftdna")
                self.assertEqual(match["observation_semantics"]["kind"], "consumer_genotype_array_call")
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_accepts_ftdna_gzip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                archive_path = Path("691234_Autosomal_o37_Results_20190228.csv.gz")
                content = (
                    "RSID,CHROMOSOME,POSITION,RESULT\n"
                    '"rs3131972","1","752721","GG"\n'
                ).encode("utf-8")
                with gzip.open(archive_path, "wb") as handle:
                    handle.write(content)

                self.approve_agi_access()
                parsed = call_operation("genomi.parse_source", {"source": str(archive_path)})
                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "ftdna")

                lookup = call_operation("variant.resolve", {"rsid": "rs3131972"})
                self.assertEqual(lookup["sample_context"]["matches"][0]["genotype"], "GG")
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_accepts_livingdna_raw_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                raw = Path("living-dna-LD0251144A-autosomal.txt")
                raw.write_text(
                    "# Living DNA customer genotype data download file version: 1.0.2\n"
                    "# Human Genome Reference Build 37 (GRCh37.p13).\n"
                    "#\n"
                    "# rsid\tchromosome\tposition\tgenotype\n"
                    "rs3131972\t1\t752721\tGG\n"
                    "rs999\t2\t200\t--\n",
                    encoding="utf-8",
                )

                self.approve_agi_access()
                parsed = call_operation("genomi.parse_source", {"source": str(raw)})
                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "livingdna")
                self.assertEqual(parsed["source_kind"], "consumer_genotype_array")
                self.assertEqual(parsed["provider"], "livingdna")

                lookup = call_operation("variant.resolve", {"rsid": "rs3131972"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
                match = lookup["sample_context"]["matches"][0]
                self.assertEqual(match["genotype"], "GG")
                self.assertEqual(match["source_format"], "livingdna")
                self.assertEqual(match["observation_semantics"]["kind"], "consumer_genotype_array_call")
            finally:
                os.chdir(previous)

    def test_detect_source_tags_vcf_provider_for_sequencingdotcom(self) -> None:
        from genomi.active_genome_index.source_intake import detect_source

        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "##source=Sequencing.com (30x WGS)\n"
                "##dataAnalysisProvider=Sequencing.com\n"
                "##reference=GRCh38.p13\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNG1ABCDEFG\n",
                encoding="utf-8",
            )
            detection = detect_source(vcf)
            self.assertEqual(detection.source_format, "vcf")
            self.assertEqual(detection.provider, "sequencingdotcom")
            self.assertEqual(detection.reference_build, "GRCh38")

    def test_detect_source_tags_vcf_provider_for_dantelabs(self) -> None:
        from genomi.active_genome_index.source_intake import detect_source

        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "DTC7U778.raw.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                '##DRAGENCommandLine=<ID=dragen,Version="SW: 05.121.645.4.0.3">\n'
                "##reference=file:///references/grch37/reference.bin\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tDTC7U778\n",
                encoding="utf-8",
            )
            detection = detect_source(vcf)
            self.assertEqual(detection.source_format, "vcf")
            self.assertEqual(detection.provider, "dantelabs")
            self.assertEqual(detection.reference_build, "GRCh37")

    def test_detect_source_tags_vcf_provider_for_nebula_via_sample_id(self) -> None:
        from genomi.active_genome_index.source_intake import detect_source

        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "NG176JZTG8.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "##reference=file:///mnt/ssd/MegaBOLT_scheduler/reference/hg38.fa\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNG176JZTG8\n",
                encoding="utf-8",
            )
            detection = detect_source(vcf)
            self.assertEqual(detection.source_format, "vcf")
            self.assertEqual(detection.provider, "nebula")
            self.assertEqual(detection.reference_build, "GRCh38")

    def test_fastq_detect_source_recognizes_paired_inputs(self) -> None:
        from genomi.active_genome_index.alignment import detect_paired_fastq
        from genomi.active_genome_index.source_intake import detect_source

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                for r1_name, r2_name in [
                    ("sample_R1_001.fastq", "sample_R2_001.fastq"),
                    ("foo_1.fastq.gz", "foo_2.fastq.gz"),
                ]:
                    Path(r1_name).write_text("@r\nACGT\n+\nIIII\n", encoding="utf-8")
                    Path(r2_name).write_text("@r\nACGT\n+\nIIII\n", encoding="utf-8")
                    detection = detect_source(r1_name)
                    self.assertEqual(detection.source_format, "fastq")
                    self.assertEqual(detection.source_kind, "paired_reads_input")
                    pair = detect_paired_fastq(Path(r1_name))
                    self.assertIsNotNone(pair)
                    assert pair is not None
                    self.assertEqual(pair[1].name, r2_name)
                    Path(r1_name).unlink()
                    Path(r2_name).unlink()
            finally:
                os.chdir(previous)

    def test_fastq_aligner_pick_uses_median_read_length(self) -> None:
        from genomi.active_genome_index.alignment import pick_aligner_for_reads, sniff_fastq_read_length

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                short = Path("short_R1.fastq")
                short_seq = "ACGT" * 37 + "AC"  # 150 bp
                short.write_text(f"@s\n{short_seq}\n+\n{'I' * len(short_seq)}\n", encoding="utf-8")
                self.assertEqual(sniff_fastq_read_length(short), 150)
                self.assertEqual(pick_aligner_for_reads(sniff_fastq_read_length(short)), "bwa-mem2")

                long_path = Path("long_R1.fastq")
                long_seq = "ACGT" * 200  # 800 bp
                long_path.write_text(f"@l\n{long_seq}\n+\n{'I' * len(long_seq)}\n", encoding="utf-8")
                self.assertEqual(sniff_fastq_read_length(long_path), 800)
                self.assertEqual(pick_aligner_for_reads(sniff_fastq_read_length(long_path)), "minimap2")
            finally:
                os.chdir(previous)

    def test_fastq_parse_returns_requires_library_install_when_aligner_missing(self) -> None:
        from genomi.active_genome_index import alignment, source_intake

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                r1 = Path("sample_R1_001.fastq.gz")
                r2 = Path("sample_R2_001.fastq.gz")
                short_seq = "ACGT" * 37 + "AC"  # 150 bp
                record = f"@r\n{short_seq}\n+\n{'I' * len(short_seq)}\n".encode("utf-8")
                with gzip.open(r1, "wb") as handle:
                    handle.write(record)
                with gzip.open(r2, "wb") as handle:
                    handle.write(record)
                reference = Path("reference.fa")
                reference.write_text(">chr1\n" + "A" * 200 + "\n", encoding="utf-8")

                with (
                    mock.patch.object(alignment, "resolve_aligner_binary", return_value=None),
                    mock.patch.object(alignment.shutil, "which", return_value=None),
                ):
                    result = source_intake.parse_source(
                        r1,
                        reference_fasta=reference,
                        auto_reference_fasta=False,
                    )

                self.assertEqual(result["status"], "requires_library_install")
                self.assertEqual(result["source_format"], "fastq")
                binaries = {entry["binary"] for entry in result["missing_libraries"]}
                self.assertIn("bwa-mem2", binaries)
                self.assertIn("samtools", binaries)
                libs = {entry["install_library"] for entry in result["missing_libraries"]}
                self.assertIn("bwa-mem2-binary", libs)
            finally:
                os.chdir(previous)

    def test_fastq_parse_raises_when_r2_sibling_missing(self) -> None:
        from genomi.active_genome_index import source_intake

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                r1 = Path("orphan_R1_001.fastq")
                r1.write_text("@r\nACGT\n+\nIIII\n", encoding="utf-8")
                reference = Path("reference.fa")
                reference.write_text(">chr1\nA\n", encoding="utf-8")

                with self.assertRaises(ValueError) as ctx:
                    source_intake.parse_source(
                        r1,
                        reference_fasta=reference,
                        auto_reference_fasta=False,
                    )
                self.assertIn("paired-end R1", str(ctx.exception))
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_accepts_bam_by_materializing_derived_vcf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                bam = Path("sample.bam")
                bam.write_bytes(b"BAM\x01")
                reference = Path("reference.fa")
                reference.write_text(">chr1\n" + "A" * 200 + "\n", encoding="utf-8")

                def fake_materialize_bam_variant_vcf(
                    bam_path: Path,
                    reference_fasta: Path,
                    output_vcf: Path,
                    *,
                    force: bool = False,
                ) -> dict[str, object]:
                    del bam_path, reference_fasta, force
                    Path(output_vcf).write_text(
                        "##fileformat=VCFv4.2\n"
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n"
                        "1\t100\trs555\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                        encoding="utf-8",
                    )
                    return {
                        "status": "completed",
                        "output": str(output_vcf),
                        "manifest_path": str(Path(f"{output_vcf}.genomi-manifest.json")),
                    }

                with (
                    mock.patch("genomi.active_genome_index.source_intake.infer_genome_build_from_bam", return_value="GRCh38"),
                    mock.patch(
                        "genomi.active_genome_index.source_intake.materialize_bam_variant_vcf",
                        side_effect=fake_materialize_bam_variant_vcf,
                    ),
                ):
                    self.approve_agi_access()
                    parsed = call_operation(
                        "genomi.parse_source",
                        {"source": str(bam), "reference_fasta": str(reference)},
                    )

                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "bam")
                self.assertEqual(parsed["source_kind"], "alignment_reads")
                self.assertIn("active_genome_index", parsed)
                self.assertEqual([step["name"] for step in parsed["steps"]], ["init-source", "materialize-variants-from-bam", "build-active-genome-index-from-derived-vcf"])
                self.assertEqual(set(parsed["outputs"]), {"active_genome_index_path", "bam_variant_call_manifest"})
                self.assertNotIn("clinvar_matches", parsed["outputs"])
                self.assertNotIn("genotype_reference_fasta", parsed)
                self.assertNotIn("evidence_summary", parsed)
                self.assertNotIn(str(bam.resolve(strict=False)), json.dumps(parsed))
                self.assertNotIn(str(bam), json.dumps(parsed))

                current = call_operation("genomi.describe_context")
                self.assertTrue(current["has_active_genome_index"])
                self.assertEqual(current["active_genome_index"]["source_format"], "bam")
                self.assertTrue(current["active_genome_index"]["digitized"])
                self.assertNotIn(str(bam.resolve(strict=False)), json.dumps(current))
            finally:
                os.chdir(previous)

if __name__ == "__main__":
    import unittest

    unittest.main()
