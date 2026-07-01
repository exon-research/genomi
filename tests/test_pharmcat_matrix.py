from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from genomi.capabilities.decode.panel_adapters import normalize_pgx_panel
from genomi.capabilities.pharmacogenomics.pharmcat import (
    _parse_calls_only_tsv,
    build_medication_review_targets,
    build_sample_pgx_matrix,
    import_pharmcat_artifacts,
)

_REAL_CALLS_ONLY_TSV = (
    "PharmCAT 3.2.0\n"
    "Gene\tSource Diplotype\tPhenotype\tActivity Score\n"
    "CYP2C19\t*1/*2\tIntermediate Metabolizer\t\n"
    "CYP3A5\t*3/*3\tPoor Metabolizer\t\n"
)


class PharmCATMatrixTests(unittest.TestCase):
    def test_parsed_calls_only_rows_map_into_decode_pgx_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.report.tsv"
            path.write_text(_REAL_CALLS_ONLY_TSV, encoding="utf-8")
            parsed = _parse_calls_only_tsv(path, max_calls=200)

        rows = normalize_pgx_panel({"sample_pgx_matrix": build_sample_pgx_matrix({"calls_only": parsed})})

        self.assertIsNotNone(rows)
        by_gene = {row["gene"]: row for row in rows}
        self.assertEqual(by_gene["CYP2C19"]["diplotype"], "*1/*2")
        self.assertEqual(by_gene["CYP2C19"]["phenotype"], "Intermediate Metabolizer")
        self.assertEqual(by_gene["CYP3A5"]["phenotype"], "Poor Metabolizer")

    def test_gene_only_pharmcat_artifacts_emit_sample_only_rows(self) -> None:
        matrix = build_sample_pgx_matrix(
            {
                "phenotype_json": {
                    "artifact": {"artifact_id": "pharmcat_artifact_sha256:phenotype"},
                    "records": [
                        {
                            "gene": "CYP2D6",
                            "source_diplotypes": [{"label": "*1/*4", "phenotypes": ["Intermediate Metabolizer"]}],
                        }
                    ],
                },
                "named_allele_match_json": {
                    "artifact": {"artifact_id": "pharmcat_artifact_sha256:match"},
                    "records": [{"gene": "CYP2D6", "diplotypes": [{"name": "*1/*4"}]}],
                },
            }
        )

        row_types_by_class = {row["evidence_classes"][0]: row["row_type"] for row in matrix["rows"]}
        self.assertEqual(row_types_by_class["pharmcat_sample_pgx_phenotype"], "sample_only")
        self.assertEqual(row_types_by_class["pharmcat_sample_pgx_match"], "sample_only")

    def test_medication_review_targets_preserve_distinct_sample_row_ids(self) -> None:
        matrix = {
            "policy_id": "pharmcat_sample_pgx_matrix_v1",
            "rows": [
                {
                    "row_id": "samplepgx_clopidogrel_label",
                    "row_type": "drug_gene_diplotype",
                    "drug": "clopidogrel",
                    "gene": "CYP2C19",
                    "diplotype": "*1/*2",
                    "phenotype": "Intermediate Metabolizer",
                    "evidence_classes": ["pharmcat_sample_pgx_recommendation"],
                },
                {
                    "row_id": "samplepgx_clopidogrel_phenotype",
                    "row_type": "drug_gene_diplotype",
                    "drug": "clopidogrel",
                    "gene": "CYP2C19",
                    "diplotype": "*1/*2",
                    "phenotype": "Intermediate Metabolizer",
                    "evidence_classes": ["pharmcat_sample_pgx_phenotype"],
                },
            ],
        }

        targets = build_medication_review_targets(matrix)

        self.assertEqual(targets["target_count"], 2)
        self.assertEqual(
            [target["source_sample_pgx_row_id"] for target in targets["targets"]],
            ["samplepgx_clopidogrel_label", "samplepgx_clopidogrel_phenotype"],
        )

    def test_imported_artifacts_emit_sample_matrix_and_medication_review_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = root / "sample.report.tsv"
            report = root / "sample.report.json"
            phenotype = root / "sample.phenotypes.json"
            match = root / "sample.match.json"
            calls.write_text(_REAL_CALLS_ONLY_TSV, encoding="utf-8")
            report.write_text(json.dumps(_report_json()), encoding="utf-8")
            phenotype.write_text(
                json.dumps(
                    {
                        "matcherMetadata": {"pharmcatVersion": "3.2.0", "genomeBuild": "GRCh38"},
                        "geneReports": {
                            "CYP2C19": {
                                "geneSymbol": "CYP2C19",
                                "sourceDiplotypes": [{"label": "*1/*2", "phenotypes": ["Intermediate Metabolizer"]}],
                                "recommendationDiplotypes": [{"label": "*1/*2", "phenotypes": ["Intermediate Metabolizer"]}],
                            },
                            "CYP2D6": {
                                "geneSymbol": "CYP2D6",
                                "sourceDiplotypes": [{"label": "Unknown/Unknown", "phenotypes": ["No Result"]}],
                                "recommendationDiplotypes": [{"label": "Unknown/Unknown", "phenotypes": ["No Result"]}],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            match.write_text(
                json.dumps(
                    {
                        "metadata": {"pharmcatVersion": "3.2.0", "genomeBuild": "GRCh38"},
                        "results": [
                            {"gene": "CYP2C19", "diplotypes": [{"name": "*1/*2"}]},
                            {"gene": "CYP2D6", "diplotypes": [{"name": "Unknown/Unknown"}]},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = import_pharmcat_artifacts(
                report_json=report,
                calls_only_tsv=calls,
                match_json=match,
                phenotype_json=phenotype,
            )

        sample_matrix = result["sample_pgx_matrix"]
        self.assertEqual(sample_matrix["policy_id"], "pharmcat_sample_pgx_matrix_v1")
        self.assertGreaterEqual(sample_matrix["row_count"], 4)
        self.assertEqual({row["sample_relevance"]["state"] for row in sample_matrix["rows"]}, {"sample_target_observed"})
        self.assertIn(
            "pharmcat_sample_pgx_recommendation",
            {evidence_class for row in sample_matrix["rows"] for evidence_class in row["evidence_classes"]},
        )
        self.assertIn(
            "pharmcat_sample_pgx_call",
            {evidence_class for row in sample_matrix["rows"] for evidence_class in row["evidence_classes"]},
        )
        review_targets = result["medication_review_targets"]
        self.assertEqual(review_targets["policy_id"], "pharmcat_medication_review_targets_v1")
        self.assertEqual(review_targets["target_count"], 1)
        self.assertEqual(review_targets["targets"][0]["drug"], "clopidogrel")
        self.assertEqual(review_targets["targets"][0]["gene"], "CYP2C19")
        self.assertEqual(review_targets["targets"][0]["known_pgx_source"], "pharmcat_sample_pgx_matrix")
        self.assertNotIn("CYP2D6", {target.get("gene") for target in review_targets["targets"]})


def _report_json() -> dict[str, object]:
    return {
        "title": "PharmCAT Report",
        "pharmcatVersion": "3.2.0",
        "drugs": {
            "CPIC Guideline Annotation": {
                "clopidogrel": {
                    "name": "clopidogrel",
                    "source": "CPIC",
                    "guidelines": [
                        {
                            "id": "CPIC:CYP2C19-clopidogrel",
                            "name": "CYP2C19 and clopidogrel",
                            "source": "CPIC",
                            "annotations": [
                                {
                                    "classification": "Strong",
                                    "population": "ACS/PCI",
                                    "drugRecommendation": "Consider an alternative antiplatelet therapy.",
                                    "implications": ["Reduced active metabolite formation and antiplatelet response."],
                                    "genotypes": [
                                        {
                                            "diplotypes": [
                                                {
                                                    "gene": "CYP2C19",
                                                    "allele1": {"name": "*1"},
                                                    "allele2": {"name": "*2"},
                                                    "phenotypes": ["Intermediate Metabolizer"],
                                                }
                                            ]
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
