from __future__ import annotations

import gzip
import tempfile
from pathlib import Path

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.capabilities.analytical_grounding.analytical_grounding.library import (
    analytical_library_path,
)
from genomi.evidence import envelope as evidence_envelope
from genomi.operations import call_operation
from genomi.operations.registry.errors import OperationError

from tests.support.runtime.genomi import GenomiRuntimeTestCase


class GeneVariantScanTests(GenomiRuntimeTestCase):
    def _write_gencode(self, *rows: str, genome_build: str = "GRCh38") -> Path:
        library = f"gencode-{genome_build.lower()}"
        path = analytical_library_path(library)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write("##description: test GENCODE subset\n")
            for row in rows:
                handle.write(row.rstrip("\n") + "\n")
        return path

    def _assign_sample(self, *records: str, genome_build: str = "GRCh38") -> None:
        self.genomi_home.mkdir(parents=True, exist_ok=True)
        fixture_dir = Path(tempfile.mkdtemp(dir=self.genomi_home))
        vcf = fixture_dir / "sample.vcf"
        vcf.write_text(
            "##fileformat=VCFv4.2\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tPATIENT\n"
            + "".join(record.rstrip("\n") + "\n" for record in records),
            encoding="utf-8",
        )
        agi = fixture_dir / "active-genome-index.sqlite"
        create_active_genome_index(vcf, agi, reuse_existing=False)
        call_operation(
            "active_genome_index.assign_user_genome",
            {
                "nickname": "Gene scan patient",
                "source": str(vcf),
                "agi_path": str(agi),
                "genome_build": genome_build,
            },
        )

    def test_finds_unannotated_ctla4_like_variant_by_gene_interval(self) -> None:
        self._write_gencode(
            'chr2\tHAVANA\tgene\t203867786\t203895962\t.\t+\t.\tgene_id "ENSG00000163599.18"; gene_type "protein_coding"; gene_name "CTLA4";'
        )
        self._assign_sample(
            "2\t203870704\trs2469719303\tG\tC\t.\tPASS\t.\tGT:DP:GQ\t0/1:38:99"
        )

        result = call_operation(
            "variant.find_gene_variants",
            {"genes": ["CTLA4"], "genome_build": "GRCh38"},
        )

        self.assertEqual(result["status"], "variants_found")
        self.assertEqual(result["coverage"]["returned_variant_count"], 1)
        variant = result["variants"][0]
        self.assertEqual(variant["rsid"], "rs2469719303")
        self.assertEqual(variant["genotype"], "0/1")
        self.assertEqual(variant["info_genes"], [])
        self.assertEqual(variant["matched_candidate_genes"], ["CTLA4"])
        self.assertEqual(variant["match_basis"], "gencode_gene_interval_overlap")
        self.assertTrue(variant["matched_gene_interval_ids"])
        envelope = result["evidence_envelope"]
        evidence_envelope.validate(envelope)
        self.assertEqual(envelope["finding_state"], "evidence_present")
        self.assertEqual(envelope["answer_readiness"], "needs_clinical_confirmation")

    def test_scan_is_passing_only_and_reports_per_gene_truncation(self) -> None:
        self._write_gencode(
            'chr2\tHAVANA\tgene\t100\t300\t.\t+\t.\tgene_id "ENSG_CTLA4"; gene_type "protein_coding"; gene_name "CTLA4";'
        )
        self._assign_sample(
            "2\t150\trs-pass-1\tA\tG\t.\tPASS\t.\tGT\t0/1",
            "2\t160\trs-lowqual\tC\tT\t.\tLowQual\t.\tGT\t0/1",
            "2\t170\trs-pass-2\tG\tA\t.\tPASS\t.\tGT\t0/1",
        )

        result = call_operation(
            "variant.find_gene_variants",
            {"genes": ["CTLA4"], "per_gene_limit": 1},
        )

        self.assertEqual([row["rsid"] for row in result["variants"]], ["rs-pass-1"])
        self.assertTrue(result["coverage"]["truncated"])
        self.assertEqual(result["coverage"]["truncated_genes"], ["CTLA4"])
        self.assertEqual(result["gene_results"][0]["returned_variant_count"], 1)
        self.assertIn(
            "increase_per_gene_limit",
            {
                item["action"]
                for item in result["evidence_envelope"]["next_actions"]
            },
        )
        defaults = {
            item["parameter"]: item["value"]
            for item in result["defaults_applied"]
        }
        self.assertEqual(defaults["genome_build"], "GRCh38")

    def test_distinct_structural_variants_do_not_collapse_across_gene_intervals(self) -> None:
        self._write_gencode(
            'chr1\tHAVANA\tgene\t120\t140\t.\t+\t.\tgene_id "ENSG_A"; gene_type "protein_coding"; gene_name "GENEA";',
            'chr1\tHAVANA\tgene\t350\t360\t.\t+\t.\tgene_id "ENSG_B"; gene_type "protein_coding"; gene_name "GENEB";',
        )
        self._assign_sample(
            "1\t100\t.\tN\t<DEL>\t.\tPASS\tEND=150\tGT\t0/1",
            "1\t100\t.\tN\t<DEL>\t.\tPASS\tEND=400\tGT\t0/1",
        )

        result = call_operation(
            "variant.find_gene_variants",
            {"genes": ["GENEA", "GENEB"]},
        )

        self.assertEqual(result["coverage"]["returned_variant_count"], 2)
        by_end = {variant["end"]: variant for variant in result["variants"]}
        self.assertEqual(by_end[150]["matched_candidate_genes"], ["GENEA"])
        self.assertEqual(
            by_end[400]["matched_candidate_genes"],
            ["GENEA", "GENEB"],
        )
        self.assertNotEqual(by_end[150]["record_key"], by_end[400]["record_key"])

    def test_empty_scan_is_scoped_and_cannot_support_clinical_negative(self) -> None:
        self._write_gencode(
            'chr2\tHAVANA\tgene\t100\t300\t.\t+\t.\tgene_id "ENSG_CTLA4"; gene_type "protein_coding"; gene_name "CTLA4";'
        )
        self._assign_sample("2\t900\trs-outside\tA\tG\t.\tPASS\t.\tGT\t0/1")

        result = call_operation(
            "variant.find_gene_variants",
            {"genes": ["CTLA4"]},
        )

        self.assertEqual(result["status"], "in_scope_empty")
        self.assertEqual(result["coverage_state"], "in_scope_empty")
        envelope = result["evidence_envelope"]
        self.assertEqual(
            envelope["finding_state"],
            "not_observed_in_consulted_scope",
        )
        self.assertFalse(envelope["negative_inference"]["allowed"])
        self.assertIn(
            "not_observed_in_consulted_scope:do_not_imply_clinical_negative",
            envelope["guidance"],
        )

    def test_missing_matching_gencode_library_is_structured_block(self) -> None:
        self._assign_sample(
            "2\t203870704\trs2469719303\tG\tC\t.\tPASS\t.\tGT\t0/1"
        )

        result = call_operation(
            "variant.find_gene_variants",
            {"genes": ["CTLA4"], "genome_build": "GRCh38"},
        )

        self.assertEqual(result["status"], "requires_library_install")
        self.assertEqual(result["coverage_state"], "blocked_missing_library")
        self.assertEqual(result["missing_library"]["library"], "gencode-grch38")
        self.assertIn("gencode-grch38", result["ask_user"]["install_command"])
        self.assertNotIn("required_paths", result["missing_library"])
        envelope = result["evidence_envelope"]
        self.assertEqual(envelope["finding_state"], "blocked_missing_library")
        self.assertEqual(envelope["answer_readiness"], "needs_user_install")
        self.assertFalse(envelope["negative_inference"]["allowed"])

    def test_unresolved_gene_and_build_mismatch_are_not_empty_genome_results(self) -> None:
        self._write_gencode(
            'chr2\tHAVANA\tgene\t100\t300\t.\t+\t.\tgene_id "ENSG_CTLA4"; gene_type "protein_coding"; gene_name "CTLA4";'
        )
        self._assign_sample("2\t150\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1")

        unresolved = call_operation(
            "variant.find_gene_variants",
            {"genes": ["NOT_A_GENCODE_GENE"]},
        )
        self.assertEqual(unresolved["status"], "out_of_scope_for_input")
        self.assertEqual(
            unresolved["evidence_envelope"]["finding_state"],
            "not_assessed",
        )
        self.assertEqual(
            unresolved["evidence_envelope"]["coverage"]["consulted_sources"],
            ["managed_gencode_gtf"],
        )

        partial = call_operation(
            "variant.find_gene_variants",
            {"genes": ["CTLA4", "NOT_A_GENCODE_GENE"]},
        )
        self.assertEqual(partial["coverage"]["gene_scope_state"], "partial")
        self.assertEqual(partial["query"]["consulted_genes"], ["CTLA4"])
        self.assertEqual(
            partial["query"]["unassessed_genes"],
            ["NOT_A_GENCODE_GENE"],
        )
        self.assertEqual(
            partial["gene_results"][1]["coverage_state"],
            "out_of_scope_for_input",
        )

        mismatch = call_operation(
            "variant.find_gene_variants",
            {"genes": ["CTLA4"], "genome_build": "GRCh37"},
        )
        self.assertEqual(mismatch["status"], "out_of_scope_for_input")
        self.assertEqual(mismatch["active_genome_index_genome_build"], "GRCh38")
        self.assertEqual(mismatch["variants"], [])

    def test_candidate_gene_and_limit_bounds_are_enforced(self) -> None:
        self._assign_sample("2\t150\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1")

        invalid_gene_sets = (
            [],
            ["CTLA4", "ctla4"],
            [f"GENE{index}" for index in range(11)],
        )
        for genes in invalid_gene_sets:
            with self.subTest(genes=genes):
                with self.assertRaises(OperationError) as raised:
                    call_operation("variant.find_gene_variants", {"genes": genes})
                self.assertEqual(raised.exception.code, "invalid_params")

        for limit in (0, 201, True, "1", 1.0, 1.9):
            with self.subTest(per_gene_limit=limit):
                with self.assertRaises(OperationError) as raised:
                    call_operation(
                        "variant.find_gene_variants",
                        {"genes": ["CTLA4"], "per_gene_limit": limit},
                    )
                self.assertEqual(raised.exception.code, "invalid_params")


if __name__ == "__main__":
    import unittest

    unittest.main()
