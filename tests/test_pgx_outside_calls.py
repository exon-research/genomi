from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genomi.capabilities.pharmacogenomics.pgx_outside_calls import (
    prepare_outside_call_file,
    validate_outside_call_file,
)
from genomi.operations import call_operation, list_operations


class PGxOutsideCallTests(unittest.TestCase):
    def test_validates_pharmcat_outside_call_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.tsv"
            outside.write_text(
                "gene\tdiplotype\tphenotype\tactivityScore\n"
                "CYP2D6\t*1/*4\tIntermediate Metabolizer\t1.0\n",
                encoding="utf-8",
            )

            result = validate_outside_call_file(outside)

        self.assertTrue(result["ok"])
        self.assertEqual(result["schema"], "genomi-pgx-outside-call-validation-v1")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["genes"], ["CYP2D6"])
        self.assertEqual(result["rows"][0]["gene"], "CYP2D6")
        self.assertEqual(result["rows"][0]["diplotype"], "*1/*4")
        self.assertEqual(result["rows"][0]["phenotype"], "Intermediate Metabolizer")
        self.assertEqual(result["rows"][0]["activity_score"], "1.0")
        self.assertTrue(result["input"]["hidden_intake_source"])
        self.assertNotIn(str(outside), str(result))

    def test_rejects_rows_without_call_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.tsv"
            outside.write_text("CYP2D6\n", encoding="utf-8")

            result = validate_outside_call_file(outside)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "invalid_outside_call_file")
        self.assertEqual(result["invalid_rows"][0]["reason"], "missing_diplotype_phenotype_or_activity_score")

    def test_missing_outside_call_file_asks_for_file(self) -> None:
        result = validate_outside_call_file("missing.tsv")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "missing_outside_call_file")

    def test_rejects_too_many_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.tsv"
            outside.write_text("CYP2D6\t*1/*4\tIntermediate Metabolizer\t1.0\textra\n", encoding="utf-8")

            result = validate_outside_call_file(outside)

        self.assertFalse(result["ok"])
        self.assertEqual(result["invalid_rows"][0]["reason"], "too_many_fields")

    def test_rejects_non_utf8_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.tsv"
            outside.write_bytes(b"CYP2D6\t*1/*4\t\xff\n")

            result = validate_outside_call_file(outside)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "encoding_error")
        self.assertNotIn(str(outside), str(result))

    def test_outside_call_validation_is_agent_operation(self) -> None:
        tools = {tool["name"]: tool for tool in list_operations(capability="pharmacogenomics")}

        self.assertIn("pharmacogenomics.validate_outside_call_tsv", tools)
        self.assertIn("pharmacogenomics.prepare_outside_call_tsv", tools)
        annotations = tools["pharmacogenomics.validate_outside_call_tsv"]["annotations"]
        self.assertEqual(annotations["operationScope"], "read")
        self.assertFalse(annotations["mutating"])
        self.assertEqual(annotations["privacyScope"], "local_private")
        self.assertIn("pharmcat_outside_call_validation", annotations["produces"])
        prepare_annotations = tools["pharmacogenomics.prepare_outside_call_tsv"]["annotations"]
        self.assertEqual(prepare_annotations["operationScope"], "write")
        self.assertTrue(prepare_annotations["mutating"])
        self.assertIn("pharmcat_outside_call_file", prepare_annotations["produces"])

    def test_call_operation_validates_outside_call_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.tsv"
            outside.write_text("HLA-B\t*57:01\n", encoding="utf-8")

            result = call_operation("pharmacogenomics.validate_outside_call_tsv", {"outside_call_file": str(outside)})

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["genes"], ["HLA-B"])

    def test_call_operation_asks_for_missing_outside_call_file(self) -> None:
        result = call_operation("pharmacogenomics.validate_outside_call_tsv", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "missing_outside_call_file")

    def test_prepares_optitype_hla_output_for_pharmcat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            optitype = Path(tmp) / "result.tsv"
            output = Path(tmp) / "outside.tsv"
            optitype.write_text(
                "\tA1\tA2\tB1\tB2\tC1\tC2\tReads\tObjective\n"
                "0\tA*32:01\tA*68:03\tB*07:02\tB*35:01\tC*07:02\tC*07:02\t10191.0\t9915.8\n",
                encoding="utf-8",
            )

            result = prepare_outside_call_file(optitype, caller_format="optitype", output_file=output)

            self.assertTrue(result["ok"])
            self.assertEqual(result["schema"], "genomi-pgx-outside-call-prepare-v1")
            self.assertEqual(result["caller_format"], "optitype")
            self.assertEqual(result["summary"]["genes"], ["HLA-A", "HLA-B"])
            self.assertEqual(result["rows"][0]["diplotype"], "*32:01/*68:03")
            self.assertEqual(result["rows"][1]["diplotype"], "*07:02/*35:01")
            self.assertTrue(output.exists())
            self.assertIn("HLA-A\t*32:01/*68:03", output.read_text(encoding="utf-8"))
            self.assertEqual(result["validation"]["status"], "completed")
            self.assertEqual(result["prepared_artifact"]["outside_call_file"], str(output.resolve(strict=False)))
            self.assertEqual(result["prepared_artifact"]["artifact_type"], "pharmcat_outside_call_tsv")
            self.assertNotIn(str(optitype), str(result))

    def test_call_operation_asks_for_missing_caller_output_file(self) -> None:
        result = call_operation("pharmacogenomics.prepare_outside_call_tsv", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "missing_caller_output_file")

    def test_prepares_generic_gene_call_table_for_pharmcat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / "calls.csv"
            output = Path(tmp) / "outside.tsv"
            table.write_text(
                "gene,diplotype,phenotype,activity_score\n"
                "CYP2D6,*1/*4,Intermediate Metabolizer,1.0\n",
                encoding="utf-8",
            )

            result = call_operation(
                "pharmacogenomics.prepare_outside_call_tsv",
                {"caller_output_file": str(table), "caller_format": "generic_table", "output_file": str(output)},
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["summary"]["genes"], ["CYP2D6"])
            self.assertEqual(result["validation"]["rows"][0]["phenotype"], "Intermediate Metabolizer")
            self.assertIn("CYP2D6\t*1/*4\tIntermediate Metabolizer\t1.0", output.read_text(encoding="utf-8"))

    def test_prepares_stellarpgx_summary_for_selected_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "stellar_summary.txt"
            output = Path(tmp) / "outside.tsv"
            summary.write_text(
                "HG00436\t*71/*2x2\n"
                "HG01086\t[*1/*31]\tPossible novel allele or suballele present\n",
                encoding="utf-8",
            )

            result = prepare_outside_call_file(
                summary,
                caller_format="stellarpgx_summary",
                sample="HG01086",
                output_file=output,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["sample"], "HG01086")
            self.assertEqual(result["summary"]["genes"], ["CYP2D6"])
            self.assertEqual(result["rows"][0]["diplotype"], "*1/*31")
            self.assertEqual(result["warnings"][0]["code"], "stellarpgx_note")
            self.assertIn("CYP2D6\t*1/*31", output.read_text(encoding="utf-8"))

    def test_stellarpgx_summary_requires_sample_when_multiple_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "stellar_summary.txt"
            summary.write_text("HG00436\t*71/*2x2\nHG01086\t*1/*31\n", encoding="utf-8")

            result = prepare_outside_call_file(summary, caller_format="stellarpgx_summary")

        self.assertFalse(result["ok"])
        self.assertEqual(result["invalid_rows"][0]["reason"], "multiple_samples_require_sample")


if __name__ == "__main__":
    unittest.main()
