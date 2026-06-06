from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from genomi.active_genome_index.active_genome_index import ActiveGenomeIndexNeed, create_active_genome_index, open_reader
from genomi.active_genome_index.source_intake.dispatch import parse_source
from genomi.clinvar_match_model import (
    MATCH_BASIS_EXACT_ALLELE,
    MATCH_BASIS_LIFTOVER_EXACT_ALLELE,
    MATCH_BASIS_LIFTOVER_MULTIALLELIC_ALT,
    MATCH_BASIS_MULTIALLELIC_ALT,
    match_basis_for_sample_mode,
)
from genomi.evidence import (
    import_clinvar_vcf,
    match_clinvar_variants,
    match_clinvar_variants_from_active_genome_index,
)
from genomi.evidence.store.clinvar_match_provenance import (
    build_clinvar_match_payload,
    match_basis_from_record,
)
from genomi.evidence.store import clinvar_import as clinvar_import_module
from genomi.runtime.sqlite_support import connect_sqlite


class ClinvarObservedAlleleTests(unittest.TestCase):
    def test_force_clinvar_rebuild_checkpoints_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            clinvar_vcf = self._write_clinvar_vcf(Path(tmp) / "clinvar.vcf")
            import_clinvar_vcf(clinvar_vcf, db, source_version="fixture")

            with mock.patch.object(
                clinvar_import_module,
                "_checkpoint_truncate_wal",
                wraps=clinvar_import_module._checkpoint_truncate_wal,
            ) as checkpoint:
                result = import_clinvar_vcf(
                    clinvar_vcf,
                    db,
                    source_version="fixture",
                    force=True,
                )

            wal_path = Path(str(db) + "-wal")
            self.assertEqual(result["status"], "completed")
            self.assertGreaterEqual(checkpoint.call_count, 2)
            self.assertFalse(wal_path.exists() and wal_path.stat().st_size > 0)

    def test_match_basis_is_required_for_match_payloads(self) -> None:
        with self.assertRaisesRegex(ValueError, "match_basis is required"):
            build_clinvar_match_payload(
                sample_variant={"chrom": "1", "pos": 100, "ref": "A", "alt": "C"},
                clinvar={"chrom": "1", "pos": 100, "ref": "A", "alt": "C"},
                match_basis="",
            )
        with self.assertRaisesRegex(ValueError, "missing required match_basis"):
            match_basis_from_record({"sample_variant": {}, "clinvar": {}})
        with self.assertRaisesRegex(ValueError, "unknown ClinVar match_basis"):
            match_basis_from_record({"match_provenance": {"match_basis": "unsupported_exact"}})

    def test_match_model_maps_active_genome_index_sample_modes_to_public_provenance(self) -> None:
        self.assertEqual(match_basis_for_sample_mode(MATCH_BASIS_EXACT_ALLELE), MATCH_BASIS_EXACT_ALLELE)
        self.assertEqual(
            match_basis_for_sample_mode(MATCH_BASIS_MULTIALLELIC_ALT),
            MATCH_BASIS_MULTIALLELIC_ALT,
        )
        self.assertEqual(
            match_basis_for_sample_mode(MATCH_BASIS_EXACT_ALLELE, cross_build=True),
            MATCH_BASIS_LIFTOVER_EXACT_ALLELE,
        )
        self.assertEqual(
            match_basis_for_sample_mode(MATCH_BASIS_MULTIALLELIC_ALT, cross_build=True),
            MATCH_BASIS_LIFTOVER_MULTIALLELIC_ALT,
        )

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

    def test_active_genome_index_reader_stages_clinvar_match_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sample_vcf = self._write_sample_vcf(Path(tmp) / "sample.vcf", "1/2")
            agi_path = Path(tmp) / "sample.sqlite"
            create_active_genome_index(sample_vcf, agi_path, reuse_existing=False)
            reader = open_reader(agi_path, need=ActiveGenomeIndexNeed.VARIANT, genome_build="GRCh38")

            with connect_sqlite(":memory:") as connection:
                reader.stage_clinvar_match_records(connection)
                rows = connection.execute(
                    """
                    select clinvar_match_mode, clinvar_match_alt, clinvar_batch_id, record_kind
                    from temp.selected_active_genome_index_records
                    order by clinvar_match_alt
                    """
                ).fetchall()

        self.assertEqual(
            [(row["clinvar_match_mode"], row["clinvar_match_alt"], row["record_kind"]) for row in rows],
            [
                ("multiallelic_alt", "C", "variant_call"),
                ("multiallelic_alt", "G", "variant_call"),
            ],
        )
        self.assertEqual([row["clinvar_batch_id"].split(":")[-1] for row in rows], ["C", "G"])

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

    def test_active_genome_index_matching_reports_non_pass_rows_and_source_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            clinvar_vcf = self._write_clinvar_vcf(Path(tmp) / "clinvar.vcf")
            import_clinvar_vcf(clinvar_vcf, db, source_version="fixture")
            sample_vcf = Path(tmp) / "sample-non-pass.vcf"
            sample_vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t100\trsFiltered\tA\tC\t.\tLowQual\t.\tGT\t0/1",
                        "1\t100\trsPassing\tA\tC\t.\tPASS\t.\tGT\t0/1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            agi_path = Path(tmp) / "sample-non-pass.sqlite"
            output = Path(tmp) / "agi-non-pass.jsonl"
            create_active_genome_index(sample_vcf, agi_path, include_reference=False, reuse_existing=False)

            reader = open_reader(agi_path, need=ActiveGenomeIndexNeed.VARIANT, genome_build="GRCh38")
            result = match_clinvar_variants_from_active_genome_index(reader, db, output)
            payload = json.loads(output.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(result["stats"]["skipped_non_pass_records"], 1)
        self.assertEqual(result["stats"]["scanned_records"], 1)
        self.assertEqual(sorted(payload), ["clinvar", "match_provenance", "sample_variant"])
        self.assertEqual(payload["match_provenance"]["source_format"], "vcf")
        self.assertEqual(payload["match_provenance"]["agi_record"]["source_format"], "vcf")

    def test_active_genome_index_max_records_windows_before_pass_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            clinvar_vcf = self._write_clinvar_vcf(Path(tmp) / "clinvar.vcf")
            import_clinvar_vcf(clinvar_vcf, db, source_version="fixture")
            sample_vcf = Path(tmp) / "sample-window.vcf"
            sample_vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                        "1\t100\trsFiltered\tA\tC\t.\tLowQual\t.\tGT\t0/1",
                        "1\t100\trsPassing\tA\tC\t.\tPASS\t.\tGT\t0/1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            agi_path = Path(tmp) / "sample-window.sqlite"
            output = Path(tmp) / "agi-window.jsonl"
            create_active_genome_index(sample_vcf, agi_path, include_reference=False, reuse_existing=False)

            reader = open_reader(agi_path, need=ActiveGenomeIndexNeed.VARIANT, genome_build="GRCh38")
            result = match_clinvar_variants_from_active_genome_index(
                reader,
                db,
                output,
                max_records=1,
            )
            output_text = output.read_text(encoding="utf-8")

        self.assertEqual(result["stats"]["skipped_non_pass_records"], 1)
        self.assertEqual(result["stats"]["scanned_records"], 0)
        self.assertEqual(result["stats"]["queried_alleles"], 0)
        self.assertEqual(result["stats"]["matched_alleles"], 0)
        self.assertEqual(result["stats"]["written_records"], 0)
        self.assertEqual(output_text, "")

    def test_consumer_array_matching_uses_each_observed_alt_allele(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            clinvar_vcf = Path(tmp) / "clinvar-array.vcf"
            clinvar_vcf.write_text(
                "\n".join(
                    [
                        "##fileformat=VCFv4.2",
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                        "1\t200\t2000\tC\tA,G\t.\t.\tALLELEID=2;CLNSIG=Pathogenic;CLNREVSTAT=criteria_provided,_single_submitter;CLNDN=condition;GENEINFO=GENE2:2",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            import_clinvar_vcf(clinvar_vcf, db, source_version="fixture", genome_build="GRCh37")
            array_source = Path(tmp) / "genome_23andme.txt"
            array_source.write_text(
                "\n".join(
                    [
                        "# 23andMe raw data",
                        "# rsid\tchromosome\tposition\tgenotype",
                        "rsArray\t1\t200\tAG",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            parsed = parse_source(array_source, evidence_db=Path(tmp) / "array-evidence.sqlite", force=True)
            agi_path = Path(str(parsed["outputs"]["agi_path"]))
            output = Path(tmp) / "array-matches.jsonl"

            reader = open_reader(agi_path, need=ActiveGenomeIndexNeed.VARIANT, genome_build="GRCh37")
            result = match_clinvar_variants_from_active_genome_index(
                reader,
                db,
                output,
                genome_build="GRCh37",
            )
            payloads = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(result["stats"]["queried_alleles"], 2)
        self.assertEqual(result["stats"]["matched_alleles"], 2)
        self.assertEqual(result["stats"]["written_records"], 2)
        self.assertEqual([payload["clinvar"]["alt"] for payload in payloads], ["A", "G"])
        self.assertEqual(
            [payload["match_provenance"]["match_basis"] for payload in payloads],
            ["consumer_array_allele_inference", "consumer_array_allele_inference"],
        )
        for payload in payloads:
            self.assertEqual(payload["sample_variant"]["observed_alleles"], ["A", "G"])
            self.assertEqual(payload["match_provenance"]["agi_record"]["observed_alleles"], ["A", "G"])
            self.assertEqual(payload["match_provenance"]["evidence_scope"], "consumer_array_inferred_allele")
            self.assertEqual(
                payload["match_provenance"]["inferred_clinvar_allele"],
                {
                    "chrom": payload["clinvar"]["chrom"],
                    "pos": payload["clinvar"]["pos"],
                    "ref": payload["clinvar"]["ref"],
                    "alt": payload["clinvar"]["alt"],
                },
            )

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
