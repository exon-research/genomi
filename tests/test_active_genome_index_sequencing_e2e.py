from __future__ import annotations

import gzip
import random
import shutil
import tempfile
import unittest
from pathlib import Path

import pysam

from genomi.operations import call_operation

from _genomi_runtime_helpers import GenomiRuntimeTestCase

SYNTHETIC_ALT_READ_COUNT = 12


def _has_tools(*names: str) -> bool:
    return all(shutil.which(name) for name in names)


@unittest.skipUnless(
    _has_tools("samtools", "bcftools", "minimap2"),
    "native sequencing e2e tests require samtools, bcftools, and minimap2",
)
class ActiveGenomeIndexSequencingE2ETests(GenomiRuntimeTestCase):
    def _reference_and_variant(self, root: Path) -> tuple[Path, int, str, str, str]:
        rng = random.Random(17)
        bases = [rng.choice("ACGT") for _ in range(1000)]
        pos = 251
        ref = bases[pos - 1]
        alt = {"A": "G", "C": "T", "G": "A", "T": "C"}[ref]
        reference = root / "reference.fa"
        sequence = "".join(bases)
        reference.write_text(f">1\n{sequence}\n", encoding="utf-8")
        (root / "reference.fa.fai").write_text(
            f"1\t{len(sequence)}\t3\t{len(sequence)}\t{len(sequence) + 1}\n",
            encoding="utf-8",
        )
        return reference, pos, ref, alt, sequence

    def _alt_read(self, sequence: str, *, pos: int, alt: str) -> tuple[int, str]:
        start = 80
        length = 420
        read = list(sequence[start : start + length])
        read[pos - 1 - start] = alt
        return start, "".join(read)

    def _write_bam(self, path: Path, *, start: int, read: str) -> None:
        header = {"HD": {"VN": "1.6"}, "SQ": [{"SN": "1", "LN": 1000}]}
        with pysam.AlignmentFile(str(path), "wb", header=header) as handle:
            for index in range(SYNTHETIC_ALT_READ_COUNT):
                segment = pysam.AlignedSegment()
                segment.query_name = f"alt{index}"
                segment.query_sequence = read
                segment.flag = 0
                segment.reference_id = 0
                segment.reference_start = start
                segment.mapping_quality = 60
                segment.cigartuples = [(0, len(read))]
                segment.query_qualities = pysam.qualitystring_to_array("I" * len(read))
                handle.write(segment)

    def _write_fastq_pair(self, root: Path, read: str) -> Path:
        r1 = root / "PGP_PUBLIC_SA_L001_R1_001.fastq.gz"
        r2 = root / "PGP_PUBLIC_SA_L001_R2_001.fastq.gz"
        records = "".join(
            f"@alt{index}\n{read}\n+\n{'I' * len(read)}\n"
            for index in range(SYNTHETIC_ALT_READ_COUNT)
        ).encode("utf-8")
        with gzip.open(r1, "wb") as handle:
            handle.write(records)
        with gzip.open(r2, "wb") as handle:
            handle.write(records)
        return r1

    def _assert_variant_support(self, *, pos: int, ref: str, alt: str, source_format: str) -> None:
        support = call_operation(
            "active_genome_index.classify_genotype_support",
            {
                "chrom": "1",
                "pos": pos,
                "ref": ref,
                "alt": alt,
                "genome_build": "GRCh37",
            },
        )
        self.assertEqual(support["status"], "completed", support)
        self.assertEqual(support["support_status"], "supported", support)
        self.assertEqual(support["sample_observation"]["agi_source_format"], source_format)

    def test_bam_parse_calls_variants_with_native_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference, pos, ref, alt, sequence = self._reference_and_variant(root)
            start, read = self._alt_read(sequence, pos=pos, alt=alt)
            bam = root / "PGP_PUBLIC_NATIVE.bam"
            self._write_bam(bam, start=start, read=read)

            self.approve_access()
            parsed = call_operation(
                "genomi.parse_source",
                {
                    "source": str(bam),
                    "reference_fasta": str(reference),
                    "genome_build": "GRCh37",
                    "force": True,
                },
            )

            self.assertEqual(parsed["status"], "completed", parsed)
            self.assertEqual(parsed["source_format"], "bam")
            self.assertIn(
                "materialize-variants-from-bam",
                [step["name"] for step in parsed["steps"]],
            )
            self.assertTrue(Path(parsed["outputs"]["derived_vcf"]).exists())
            self._assert_variant_support(pos=pos, ref=ref, alt=alt, source_format="bam")

    def test_fastq_parse_aligns_and_calls_variants_with_native_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference, pos, ref, alt, sequence = self._reference_and_variant(root)
            _start, read = self._alt_read(sequence, pos=pos, alt=alt)
            r1 = self._write_fastq_pair(root, read)

            self.approve_access()
            parsed = call_operation(
                "genomi.parse_source",
                {
                    "source": str(r1),
                    "reference_fasta": str(reference),
                    "genome_build": "GRCh37",
                    "force": True,
                },
            )

            self.assertEqual(parsed["status"], "completed", parsed)
            self.assertEqual(parsed["source_format"], "fastq")
            self.assertEqual(parsed["aligner"], "minimap2")
            self.assertIn("align-fastq-to-bam", [step["name"] for step in parsed["steps"]])
            self.assertIn("digitize-derived-bam", [step["name"] for step in parsed["steps"]])
            self.assertTrue(Path(parsed["outputs"]["aligned_bam"]).exists())
            self._assert_variant_support(pos=pos, ref=ref, alt=alt, source_format="fastq")


if __name__ == "__main__":
    unittest.main()
