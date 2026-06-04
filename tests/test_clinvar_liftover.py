from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.evidence import (
    import_clinvar_vcf,
    match_clinvar_variants,
    match_clinvar_variants_from_active_genome_index,
)
from genomi.runtime.liftover import liftover_preflight


def _liftover_available() -> bool:
    return liftover_preflight("GRCh37", "GRCh38").get("status") == "available"


# APOE rs429358 lifts cleanly between builds (UCSC chain verified):
# GRCh38 chr19:44908684 T>C  <->  GRCh37 chr19:45411941 T>C
_APOE_GRCH38_POS = 44908684
_APOE_GRCH37_POS = 45411941


@unittest.skipUnless(
    _liftover_available(),
    "liftover setup unavailable; install liftover-chains and pyliftover",
)
class CrossBuildClinvarMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_grch37_sample_matches_grch38_clinvar_via_lift(self) -> None:
        # The ClinVar cache holds a GRCh38 entry for APOE rs429358; the
        # sample VCF carries the same SNP on GRCh37 at the lifted coordinate.
        # match_clinvar_variants must lift the sample position and find the
        # ClinVar hit, attaching liftover provenance to the payload.
        clinvar_vcf = self.tmp / "clinvar_grch38.vcf"
        clinvar_vcf.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    "##source=TestSyntheticClinvarFixture",
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                    f"19\t{_APOE_GRCH38_POS}\t12345\tT\tC\t.\t.\tALLELEID=999;CLNSIG=Likely_pathogenic;CLNREVSTAT=criteria_provided,_single_submitter;CLNDN=APOE;GENEINFO=APOE:348;CLNHGVS=NC_000019.10:g.{_APOE_GRCH38_POS}T>C",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        sample_vcf = self.tmp / "sample_grch37.vcf"
        sample_vcf.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                    f"19\t{_APOE_GRCH37_POS}\trs429358\tT\tC\t.\tPASS\t.\tGT\t0/1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        db_path = self.tmp / "evidence.sqlite"
        output_path = self.tmp / "matches.jsonl"

        import_clinvar_vcf(clinvar_vcf, db_path, source_version="fixture", genome_build="GRCh38")
        result = match_clinvar_variants(
            sample_vcf,
            db_path,
            output_path,
            genome_build="GRCh37",
            cache_genome_build="GRCh38",
        )

        self.assertEqual(result["stats"]["matched_alleles"], 1)
        self.assertEqual(result["stats"]["lifted_alleles"], 1)
        self.assertEqual(result["stats"]["lift_dropped_alleles"], 0)
        self.assertEqual(result["stats"]["written_records"], 1)

        lines = output_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        # Sample coordinates stay on the sample's GRCh37 build for audit.
        self.assertEqual(payload["sample_variant"]["pos"], _APOE_GRCH37_POS)
        self.assertEqual(payload["sample_variant"]["genome_build"], "GRCh37")
        # Liftover block records how the query reached the GRCh38 cache row.
        self.assertEqual(payload["liftover"]["source_build"], "GRCh37")
        self.assertEqual(payload["liftover"]["target_build"], "GRCh38")
        self.assertEqual(payload["liftover"]["lifted_pos"], _APOE_GRCH38_POS)

    def test_grch37_sample_matches_grch38_clinvar_via_from_index_path(self) -> None:
        # The indexed batch path (used by clinvar.scan_candidates against an
        # AGI) must lift sample coordinates the same way the VCF path does:
        # build an AGI index from a GRCh37 sample, point match_clinvar_
        # variants_from_index at a GRCh38 ClinVar cache, and confirm the
        # JSONL payload carries the liftover provenance block.
        clinvar_vcf = self.tmp / "clinvar_grch38.vcf"
        clinvar_vcf.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    "##source=TestSyntheticClinvarFixture",
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                    f"19\t{_APOE_GRCH38_POS}\t12345\tT\tC\t.\t.\tALLELEID=999;CLNSIG=Likely_pathogenic;CLNREVSTAT=criteria_provided,_single_submitter;CLNDN=APOE;GENEINFO=APOE:348;CLNHGVS=NC_000019.10:g.{_APOE_GRCH38_POS}T>C",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        sample_vcf = self.tmp / "sample_grch37.vcf"
        sample_vcf.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                    f"19\t{_APOE_GRCH37_POS}\trs429358\tT\tC\t.\tPASS\t.\tGT\t0/1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        db_path = self.tmp / "evidence.sqlite"
        index_path = self.tmp / "sample.index.sqlite"
        output_path = self.tmp / "matches.jsonl"

        import_clinvar_vcf(clinvar_vcf, db_path, source_version="fixture", genome_build="GRCh38")
        create_active_genome_index(sample_vcf, index_path)
        result = match_clinvar_variants_from_active_genome_index(
            index_path,
            db_path,
            output_path,
            genome_build="GRCh37",
            cache_genome_build="GRCh38",
        )

        self.assertEqual(result["stats"]["matched_alleles"], 1)
        self.assertEqual(result["stats"]["lifted_alleles"], 1)
        self.assertEqual(result["stats"]["written_records"], 1)
        lines = output_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["sample_variant"]["pos"], _APOE_GRCH37_POS)
        self.assertEqual(payload["sample_variant"]["genome_build"], "GRCh37")
        self.assertEqual(payload["liftover"]["source_build"], "GRCh37")
        self.assertEqual(payload["liftover"]["target_build"], "GRCh38")
        self.assertEqual(payload["liftover"]["lifted_pos"], _APOE_GRCH38_POS)
        # ClinVar coordinates stay on the cache's GRCh38 build.
        self.assertEqual(payload["clinvar"]["pos"], _APOE_GRCH38_POS)
        self.assertEqual(payload["clinvar"]["genome_build"], "GRCh38")

    def test_same_build_match_does_not_emit_liftover_block(self) -> None:
        # A GRCh38 sample against a GRCh38 cache must take the no-lift fast
        # path; the payload has no liftover field and the stats counters are
        # zero. This guards against accidentally enabling the lift path for
        # the common same-build case.
        clinvar_vcf = self.tmp / "clinvar_grch38.vcf"
        clinvar_vcf.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    "##source=TestSyntheticClinvarFixture",
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                    f"19\t{_APOE_GRCH38_POS}\t12345\tT\tC\t.\t.\tALLELEID=999;CLNSIG=Benign;CLNREVSTAT=criteria_provided,_single_submitter;CLNDN=APOE;GENEINFO=APOE:348",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        sample_vcf = self.tmp / "sample_grch38.vcf"
        sample_vcf.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                    f"19\t{_APOE_GRCH38_POS}\trs429358\tT\tC\t.\tPASS\t.\tGT\t0/1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        db_path = self.tmp / "evidence.sqlite"
        output_path = self.tmp / "matches.jsonl"

        import_clinvar_vcf(clinvar_vcf, db_path, source_version="fixture", genome_build="GRCh38")
        result = match_clinvar_variants(
            sample_vcf,
            db_path,
            output_path,
            genome_build="GRCh38",
        )

        self.assertEqual(result["stats"]["matched_alleles"], 1)
        self.assertEqual(result["stats"]["lifted_alleles"], 0)
        payload = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertNotIn("liftover", payload)


if __name__ == "__main__":
    unittest.main()
