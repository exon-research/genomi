from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from genomi.capabilities.decode import dashboard as decode_dashboard


def _extract_evidence(html: str) -> dict:
    marker = "window.__GENOMI_DASHBOARD__"
    assignment_index = html.find(marker)
    assert assignment_index >= 0, "no __GENOMI_DASHBOARD__ block in HTML"
    json_start = html.find("{", assignment_index)
    assert json_start >= 0, "no __GENOMI_DASHBOARD__ object in HTML"
    parsed, _end = json.JSONDecoder().raw_decode(html[json_start:].replace("<\\/", "</"))
    assert isinstance(parsed, dict), "__GENOMI_DASHBOARD__ is not an object"
    return parsed


def _panel_keys(payload: dict) -> set[str]:
    return {key for key in payload if key in decode_dashboard.PANEL_KEYS}


class DecodeDashboardAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = Path(self._tmp.name)

    def test_normalizes_native_pgx_review_result(self) -> None:
        out = self.tmpdir / "dash.html"
        result = decode_dashboard.render_dashboard(
            evidence={
                "pgx": {
                    "schema": "genomi-pgx-medication-review-v1",
                    "status": "completed",
                    "query": {"drug": "clopidogrel", "gene": "CYP2C19"},
                    "answer_support": {
                        "star_diplotype_summaries": [
                            {
                                "gene": "CYP2C19",
                                "possible_diplotype": "*1/*2",
                                "predicted_phenotype": "Intermediate Metabolizer",
                            }
                        ],
                        "source_recommendation_summaries": [
                            {
                                "source": "ClinPGx",
                                "gene": "CYP2C19",
                                "drug": "clopidogrel",
                                "summary": "Consider an alternative antiplatelet therapy.",
                            }
                        ],
                    },
                    "sample_evidence": {"total_sample_evidence_count": 1},
                    "public_evidence": {"source_evidence_count": 1},
                },
            },
            mode="full",
            output=out,
        )
        row = _extract_evidence(out.read_text(encoding="utf-8"))["pgx"][0]
        self.assertEqual(row["gene"], "CYP2C19")
        self.assertEqual(row["diplotype"], "*1/*2")
        self.assertEqual(row["phenotype"], "Intermediate Metabolizer")
        self.assertEqual(row["impact"], "reduced")
        self.assertEqual(row["drugs"][0]["name"], "clopidogrel")
        self.assertIn("alternative antiplatelet", row["drugs"][0]["recommendation"])
        self.assertIn("pgx", result["panels_rendered"])

    def test_normalizes_native_pharmcat_result(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "pgx": {
                    "schema": "genomi-pharmcat-run-v1",
                    "status": "completed",
                    "artifacts": {
                        "calls_only": {
                            "available": True,
                            "rows": [
                                {
                                    "Gene": "CYP2C19",
                                    "Source Diplotype": "*1/*2",
                                    "Phenotype": "Intermediate Metabolizer",
                                }
                            ],
                        },
                        "report_json": {
                            "available": True,
                            "recommendations": {
                                "records": [
                                    {
                                        "drug": "clopidogrel",
                                        "genes": ["CYP2C19"],
                                        "phenotypes": ["Intermediate Metabolizer"],
                                        "diplotypes": ["CYP2C19 *1/*2"],
                                        "recommendation": "Consider an alternative antiplatelet therapy.",
                                    }
                                ]
                            },
                        },
                    },
                },
            },
            mode="full",
            output=out,
        )
        row = _extract_evidence(out.read_text(encoding="utf-8"))["pgx"][0]
        self.assertEqual(row["gene"], "CYP2C19")
        self.assertEqual(row["diplotype"], "*1/*2")
        self.assertEqual(row["phenotype"], "Intermediate Metabolizer")
        self.assertEqual(row["drugs"][0]["name"], "clopidogrel")

    def test_normalizes_native_prs_calculate_score_results(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "risk": [
                    {
                        "status": "completed",
                        "polygenic_score": {
                            "pgs_id": "PGS900001",
                            "name": "Synthetic common trait score",
                            "reported_trait": "Synthetic common trait",
                        },
                        "sample_qc": {
                            "matched_variant_count": 4,
                            "score_variant_count": 4,
                            "overlap_quality": "high",
                            "note": "The sample has enough direct overlap for a raw score calculation.",
                        },
                        "score_result": {
                            "raw_weighted_score": 2.0,
                            "calibration": {"status": "not_provided"},
                        },
                        "interpretation": {
                            "summary": "The raw weighted polygenic score was calculated from 4 matched score variants."
                        },
                    }
                ],
            },
            mode="full",
            output=out,
        )
        row = _extract_evidence(out.read_text(encoding="utf-8"))["risk"][0]
        self.assertEqual(row["trait"], "Synthetic common trait")
        self.assertEqual(row["score"], 2.0)
        self.assertEqual(row["overlap"], "4/4 variants")
        self.assertEqual(row["sources"], ["PGS900001"])
        self.assertIn("raw weighted", row["note"])

    def test_native_empty_results_clear_stale_pgx_and_risk_panels(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-NATIVE-EMPTY", "variantCount": 10},
                "pgx": [{"gene": "CYP2C19", "phenotype": "Intermediate"}],
                "risk": [{"trait": "T2D", "score": 1.0}],
            },
            mode="full",
            output=out,
        )

        result = decode_dashboard.render_dashboard(
            evidence={
                "pgx": {
                    "schema": "genomi-pharmcat-run-v1",
                    "status": "requires_library_install",
                    "missing_library": {"library": "pharmcat"},
                },
                "risk": [
                    {
                        "status": "requires_score_import",
                        "missing_library": {"library": "PGS900001"},
                    }
                ],
            },
            mode="update",
            output=out,
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(_panel_keys(parsed), {"overview"})
        self.assertTrue({"pgx", "risk"}.issubset(set(result["panels_empty"])))

    def test_gene_less_native_pgx_review_is_empty_for_dashboard_cards(self) -> None:
        out = self.tmpdir / "dash.html"
        result = decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-RSID-PGX", "variantCount": 10},
                "pgx": {
                    "schema": "genomi-pgx-medication-review-v1",
                    "status": "completed",
                    "query": {"drug": "example-drug"},
                    "sample_evidence": {
                        "total_sample_evidence_count": 1,
                        "user_provided_sample_evidence": [
                            {"rsid": "rsSynthetic", "observed_alleles": ["A"]}
                        ],
                    },
                    "public_evidence": {"source_evidence_count": 1},
                },
            },
            mode="full",
            output=out,
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(_panel_keys(parsed), {"overview"})
        self.assertIn("pgx", result["panels_empty"])

    def test_malformed_native_adapter_rows_raise(self) -> None:
        cases = [
            (
                "pgx",
                {
                    "pgx": {
                        "schema": "genomi-pharmcat-run-v1",
                        "status": "completed",
                        "artifacts": {
                            "calls_only": {
                                "available": True,
                                "rows": [{"Source Diplotype": "*1/*2"}],
                            }
                        },
                    },
                },
                "gene",
            ),
            (
                "risk",
                {"risk": [{"status": "completed", "score_result": {"raw_weighted_score": 1.0}}]},
                "risk",
            ),
        ]
        for name, evidence, message in cases:
            with self.subTest(name=name):
                with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
                    decode_dashboard.render_dashboard(
                        evidence=evidence,
                        mode="full",
                        output=self.tmpdir / f"{name}.html",
                    )
                self.assertEqual(ctx.exception.code, "panel_schema_mismatch")
                self.assertIn(message, ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
