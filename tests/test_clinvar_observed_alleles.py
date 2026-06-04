from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from genomi.active_genome_index.active_genome_index import ActiveGenomeIndexNeed, create_active_genome_index, open_reader
from genomi.evidence import (
    import_clinvar_vcf,
    match_clinvar_variants,
    match_clinvar_variants_from_active_genome_index,
)


class ClinvarObservedAlleleTests(unittest.TestCase):
    def test_raw_vcf_multiallelic_matching_uses_observed_sample_alleles(self) -> None:
        cases = [
            ("0/1", ["C"], 1),
            ("1/2", ["C", "G"], 2),
            ("0/0", [], 0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            clinvar_vcf = self._write_clinvar_vcf(Path(tmp) / "clinvar.vcf")
            import_clinvar_vcf(clinvar_vcf, db, source_version="fixture")

            for genotype, expected_alts, expected_queries in cases:
                with self.subTest(genotype=genotype):
                    sample_vcf = self._write_sample_vcf(Path(tmp) / f"sample-{genotype.replace('/', '')}.vcf", genotype)
                    output = Path(tmp) / f"raw-{genotype.replace('/', '')}.jsonl"

                    result = match_clinvar_variants(sample_vcf, db, output)

                    self.assertEqual(result["stats"]["queried_alleles"], expected_queries)
                    self.assertEqual(result["stats"]["matched_alleles"], len(expected_alts))
                    self.assertEqual(result["stats"]["written_records"], len(expected_alts))
                    self.assertEqual(self._sample_alts(output), expected_alts)

    def test_active_genome_index_multiallelic_matching_uses_observed_sample_alleles(self) -> None:
        cases = [
            ("0/1", ["C"], 1),
            ("1/2", ["C", "G"], 2),
            ("0/0", [], 0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            clinvar_vcf = self._write_clinvar_vcf(Path(tmp) / "clinvar.vcf")
            import_clinvar_vcf(clinvar_vcf, db, source_version="fixture")

            for genotype, expected_alts, expected_queries in cases:
                with self.subTest(genotype=genotype):
                    sample_vcf = self._write_sample_vcf(Path(tmp) / f"sample-{genotype.replace('/', '')}.vcf", genotype)
                    agi_path = Path(tmp) / f"sample-{genotype.replace('/', '')}.sqlite"
                    output = Path(tmp) / f"agi-{genotype.replace('/', '')}.jsonl"
                    create_active_genome_index(sample_vcf, agi_path, reuse_existing=False)

                    reader = open_reader(agi_path, need=ActiveGenomeIndexNeed.VARIANT, genome_build="GRCh38")
                    result = match_clinvar_variants_from_active_genome_index(reader, db, output)

                    self.assertEqual(result["stats"]["queried_alleles"], expected_queries)
                    self.assertEqual(result["stats"]["matched_alleles"], len(expected_alts))
                    self.assertEqual(result["stats"]["written_records"], len(expected_alts))
                    self.assertEqual(self._sample_alts(output), expected_alts)

    def _write_clinvar_vcf(self, path: Path) -> Path:
        path.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                    "1\t100\t1000\tA\tC,G\t.\t.\tALLELEID=1;CLNSIG=Benign;CLNREVSTAT=criteria_provided,_single_submitter;CLNDN=condition;GENEINFO=GENE1:1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _write_sample_vcf(self, path: Path, genotype: str) -> Path:
        path.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                    f"1\t100\trsMulti\tA\tC,G\t.\tPASS\t.\tGT\t{genotype}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _sample_alts(self, output: Path) -> list[str]:
        return [json.loads(line)["sample_variant"]["alt"] for line in output.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
