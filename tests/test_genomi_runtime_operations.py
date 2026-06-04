from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.evidence import init_evidence_db
from genomi.operations import OperationError, all_operations, call_operation
from genomi.operations.registry.table import _stamp_reference_pending_if_due
from genomi.runtime import context as runtime_context

from _genomi_runtime_helpers import GenomiRuntimeTestCase


class GenomiRuntimeOperationsTests(GenomiRuntimeTestCase):
    def test_region_features_requires_explicit_assembly(self) -> None:
        result = call_operation("region.retrieve_features", {"region": "1:100-200"})

        self.assertEqual(result["status"], "unsupported_assembly")
        self.assertEqual(result["coverage_status"], "out_of_scope_for_input")

    def test_resources_check_libraries_reports_missing_install_command(self) -> None:
        result = call_operation("genomi.check_libraries", {"libraries": ["clinvar-grch38"]})

        self.assertEqual(len(result["libraries"]), 1)
        self.assertEqual(result["libraries"][0]["library"], "clinvar-grch38")
        self.assertIn("install_command", result["libraries"][0])
        self.assertIn("--libraries clinvar-grch38", result["libraries"][0]["install_command"])

    def test_candidate_decision_operations_expose_decision_evidence(self) -> None:
        decision_shapes = {"answer", "candidate_matrix", "ranking", "top_observed_candidate"}

        for tool in all_operations():
            produces = set(tool["annotations"].get("produces") or [])
            if produces & decision_shapes:
                self.assertIn("decision_evidence", produces, tool["name"])

    def test_reference_dependent_operations_declare_agi_need_metadata(self) -> None:
        by_name = {tool["name"]: tool for tool in all_operations()}
        expected_reference = {
            "active_genome_index.classify_callset_qc",
            "active_genome_index.classify_genotype_support",
            "active_genome_index.classify_region_callability",
            "ancestry.check_sample_overlap",
            "ancestry.project_pca",
            "ancestry.estimate_population_context",
            "pharmacogenomics.preflight_pharmcat",
            "decode.render_dashboard",
        }

        actual_reference = {
            name
            for name, tool in by_name.items()
            if tool["annotations"].get("agiNeed") == "reference"
        }

        self.assertEqual(actual_reference, expected_reference)

        actual_variant = {
            name
            for name, tool in by_name.items()
            if tool["annotations"].get("agiNeed") == "variant"
        }
        self.assertEqual(actual_variant, {"prs.check_score_overlap", "prs.calculate_score"})

    def test_prs_variant_operations_do_not_get_reference_pending_stamp(self) -> None:
        with mock.patch(
            "genomi.operations.registry.agi_access.reference_state_for_call",
            return_value={"note": "reference tail pending"},
        ):
            result = _stamp_reference_pending_if_due("prs.calculate_score", {}, {"status": "completed"})

        self.assertEqual(result, {"status": "completed"})

    def test_public_only_risk_investigation_uses_shared_evidence_by_default(self) -> None:
        result = call_operation(
            "phenotype.plan_risk_investigation",
            {
                "question": "BRCA1 hereditary breast cancer risk",
                "gene": "BRCA1",
                "investigation_type": "cancer_risk",
            },
        )

        self.assertEqual(result["context_scope"], "public_only")
        self.assertEqual(result["active_genome_index_evidence"]["status"], "not_selected")
        self.assertEqual(result["top_observed_candidate"], "gene:BRCA1")

    def test_risk_investigation_requires_approval_before_using_active_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            init_evidence_db(db)
            matches.write_text("", encoding="utf-8")

            with self.assertRaises(OperationError) as raised:
                call_operation(
                    "phenotype.plan_risk_investigation",
                    {
                        "question": "rare disease review for GENE2",
                        "gene": "GENE2",
                        "db": str(db),
                        "matches": str(matches),
                    },
                )

        self.assertEqual(raised.exception.code, "active_genome_index_approval_required")

    def test_public_only_pgx_operations_keep_shared_evidence_out_of_private_db_slot(self) -> None:
        expected_shared = str(self.genomi_home / "shared-evidence.sqlite")

        with mock.patch(
            "genomi.operations.pgx.review_medication_interaction",
            return_value={"schema": "genomi-pgx-medication-review-v1", "status": "completed"},
        ) as review:
            call_operation("pharmacogenomics.review_medication", {"drug": "clopidogrel"})

        self.assertIsNone(review.call_args.kwargs["db"])
        self.assertEqual(review.call_args.kwargs["shared_db"], expected_shared)
        self.assertFalse(review.call_args.kwargs["include_active_genome_index"])
        self.assertFalse(review.call_args.kwargs["has_active_genome_index_context"])

    def test_medication_review_uses_sample_context_when_active_index_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                index = Path("sample.active-genome-index.sqlite")
                evidence_db = Path("evidence.sqlite")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )
                create_active_genome_index(vcf, index)
                init_evidence_db(evidence_db)
                runtime_context.set_active_agi_from_source(
                    vcf,
                    status="parsed",
                    operation_result={
                        "sample_slug": "sample",
                        "vcf": str(vcf),
                        "evidence_db": str(evidence_db),
                        "outputs": {"agi_path": str(index)},
                    },
                )
                self.approve_access()

                with mock.patch(
                    "genomi.operations.pgx.review_medication_interaction",
                    return_value={"schema": "genomi-pgx-medication-review-v1", "status": "completed"},
                ) as review:
                    call_operation("pharmacogenomics.review_medication", {"drug": "clopidogrel"})

                self.assertEqual(Path(str(review.call_args.kwargs["db"])).resolve(), evidence_db.resolve())
                self.assertTrue(review.call_args.kwargs["include_active_genome_index"])
                self.assertTrue(review.call_args.kwargs["has_active_genome_index_context"])
            finally:
                os.chdir(previous)

    def test_medication_review_respects_explicit_public_only_with_active_index_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                index = Path("sample.active-genome-index.sqlite")
                evidence_db = Path("evidence.sqlite")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )
                create_active_genome_index(vcf, index)
                init_evidence_db(evidence_db)
                runtime_context.set_active_agi_from_source(
                    vcf,
                    status="parsed",
                    operation_result={
                        "sample_slug": "sample",
                        "vcf": str(vcf),
                        "evidence_db": str(evidence_db),
                        "outputs": {"agi_path": str(index)},
                    },
                )
                self.approve_access()
                expected_shared = str(self.genomi_home / "shared-evidence.sqlite")

                with mock.patch(
                    "genomi.operations.pgx.review_medication_interaction",
                    return_value={"schema": "genomi-pgx-medication-review-v1", "status": "completed"},
                ) as review:
                    call_operation(
                        "pharmacogenomics.review_medication",
                        {"drug": "clopidogrel", "include_active_genome_index": False},
                    )

                self.assertIsNone(review.call_args.kwargs["db"])
                self.assertEqual(review.call_args.kwargs["shared_db"], expected_shared)
                self.assertFalse(review.call_args.kwargs["include_active_genome_index"])
                self.assertFalse(review.call_args.kwargs["has_active_genome_index_context"])
            finally:
                os.chdir(previous)

    def test_clinvar_scan_materializes_missing_matches_from_active_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                index = Path("sample.active-genome-index.sqlite")
                evidence_db = Path("evidence.sqlite")
                matches = Path("clinvar.matches.jsonl")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )
                index.write_text("placeholder Active Genome Index", encoding="utf-8")
                init_evidence_db(evidence_db)
                runtime_context.set_active_agi_from_source(
                    vcf,
                    status="parsed",
                    operation_result={
                        "sample_slug": "sample",
                        "vcf": str(vcf),
                        "evidence_db": str(evidence_db),
                        "genome_build": "GRCh38",
                        "outputs": {"agi_path": str(index), "clinvar_matches": str(matches)},
                    },
                )
                self.approve_access()

                with (
                    mock.patch(
                        "genomi.operations.static_annotation.match_static_clinvar_from_active_genome_index",
                        return_value={"status": "completed", "output": str(matches)},
                    ) as materialize,
                    mock.patch(
                        "genomi.operations.static_annotation.scan_static_candidates",
                        return_value={"status": "completed", "input": str(matches)},
                    ) as scan,
                ):
                    result = call_operation("clinvar.scan_candidates", {})

                self.assertEqual(result["status"], "completed")
                materialize.assert_called_once()
                reader = materialize.call_args.args[0]
                self.assertEqual(reader.agi_path.resolve(), index.resolve())
                self.assertEqual(Path(materialize.call_args.kwargs["evidence_db"]).resolve(), evidence_db.resolve())
                self.assertEqual(Path(materialize.call_args.kwargs["output"]).resolve(), matches.resolve())
                scan.assert_called_once()
                self.assertEqual(Path(scan.call_args.args[0]).resolve(), matches.resolve())
            finally:
                os.chdir(previous)

if __name__ == "__main__":
    import unittest

    unittest.main()
