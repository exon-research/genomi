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
                    "status": "completed",
                    "medication_review_matrix": {
                        "policy_id": "pgx_medication_review_matrix_v1",
                        "row_count": 1,
                        "rows": [
                            {
                                "row_id": "pgxrow_1",
                                "row_type": "drug_gene_diplotype",
                                "drug": "clopidogrel",
                                "gene": "CYP2C19",
                                "diplotype": "*1/*2",
                                "phenotype": "Intermediate Metabolizer",
                                "recommendation_text": "Consider an alternative antiplatelet therapy.",
                                "evidence_classes": ["clinpgx_drug_label_annotation"],
                                "sample_relevance": {"state": "sample_target_observed"},
                                "readiness": "needs_clinical_confirmation",
                            }
                        ],
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
        self.assertEqual(row["impact"], "reduced")
        self.assertEqual(row["drugs"][0]["name"], "clopidogrel")
        self.assertIn("alternative antiplatelet", row["drugs"][0]["recommendation"])
        self.assertIn("pgx", result["panels_rendered"])

    def test_normalizes_native_pharmcat_result(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "pgx": {
                    "status": "completed",
                    "sample_pgx_matrix": {
                        "policy_id": "pharmcat_sample_pgx_matrix_v1",
                        "row_count": 1,
                        "rows": [
                            {
                                "row_id": "samplepgx_1",
                                "row_type": "drug_gene_diplotype",
                                "drug": "clopidogrel",
                                "gene": "CYP2C19",
                                "diplotype": "*1/*2",
                                "phenotype": "Intermediate Metabolizer",
                                "recommendation_text": "Consider an alternative antiplatelet therapy.",
                                "evidence_classes": ["pharmcat_sample_pgx_recommendation"],
                                "sample_relevance": {"state": "sample_target_observed"},
                                "readiness": "needs_clinical_confirmation",
                            }
                        ],
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

    def test_pgx_matrix_preserves_separate_medication_rows_for_same_gene(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "pgx": {
                    "status": "completed",
                    "medication_review_matrix": {
                        "policy_id": "pgx_medication_review_matrix_v1",
                        "row_count": 2,
                        "rows": [
                            {
                                "row_id": "pgxrow_clopidogrel",
                                "row_type": "drug_gene_diplotype",
                                "drug": "clopidogrel",
                                "gene": "CYP2C19",
                                "diplotype": "*1/*2",
                                "phenotype": "Intermediate Metabolizer",
                                "recommendation_text": "Consider an alternative antiplatelet therapy.",
                                "evidence_classes": ["clinpgx_drug_label_annotation"],
                                "sample_relevance": {"state": "sample_target_observed"},
                            },
                            {
                                "row_id": "pgxrow_voriconazole",
                                "row_type": "drug_gene_diplotype",
                                "drug": "voriconazole",
                                "gene": "CYP2C19",
                                "diplotype": "*1/*2",
                                "phenotype": "Intermediate Metabolizer",
                                "recommendation_text": "Review voriconazole dosing guidance.",
                                "evidence_classes": ["clinpgx_drug_label_annotation"],
                                "sample_relevance": {"state": "sample_target_observed"},
                            },
                        ],
                    },
                },
            },
            mode="full",
            output=out,
        )

        rows = _extract_evidence(out.read_text(encoding="utf-8"))["pgx"]
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["drugs"][0]["name"] for row in rows}, {"clopidogrel", "voriconazole"})

    def test_normalizes_mixed_native_pgx_result_list(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "pgx": [
                    {"status": "requires_library_install", "missing_library": {"library": "pharmcat"}},
                    {
                        "status": "completed",
                        "sample_pgx_matrix": {
                            "policy_id": "pharmcat_sample_pgx_matrix_v1",
                            "row_count": 1,
                            "rows": [
                                {
                                    "row_id": "samplepgx_clopidogrel",
                                    "row_type": "drug_gene_diplotype",
                                    "drug": "clopidogrel",
                                    "gene": "CYP2C19",
                                    "diplotype": "*1/*2",
                                    "phenotype": "Intermediate Metabolizer",
                                    "recommendation_text": "Review antiplatelet guidance.",
                                }
                            ],
                        },
                    },
                    {
                        "status": "completed",
                        "medication_review_matrix": {
                            "policy_id": "pgx_medication_review_matrix_v1",
                            "row_count": 1,
                            "rows": [
                                {
                                    "row_id": "pgxrow_warfarin",
                                    "row_type": "drug_gene_variant",
                                    "drug": "warfarin",
                                    "gene": "VKORC1",
                                    "rsid": "rs9923231",
                                    "recommendation_text": "Review warfarin dosing evidence.",
                                }
                            ],
                        },
                    },
                ],
            },
            mode="full",
            output=out,
        )

        rows = _extract_evidence(out.read_text(encoding="utf-8"))["pgx"]
        self.assertEqual({row["drugs"][0]["name"] for row in rows}, {"clopidogrel", "warfarin"})

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
        self.assertEqual(row["row_type"], "polygenic_score")
        self.assertEqual(row["score_id"], "PGS900001")
        self.assertEqual(row["overlap"], "4/4 variants")
        self.assertEqual(row["sources"], ["PGS900001"])
        self.assertIn("raw weighted", row["note"])

    def test_normalizes_mixed_native_risk_result_list(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "risk": [
                    {"status": "requires_score_import"},
                    {
                        "status": "completed",
                        "target": {"investigation_type": "carrier_review"},
                        "candidate_matrix": [
                            {
                                "candidate_id": "carrier_review:CAPN3",
                                "candidate_type": "clinvar_review_group",
                                "score": 1.0,
                                "supporting_evidence": [
                                    {
                                        "group_type": "carrier_relevance",
                                        "gene": "CAPN3",
                                        "condition": "limb-girdle muscular dystrophy",
                                        "interpretation_gates": {
                                            "inheritance": {"required": True, "state": "needed"}
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            },
            mode="full",
            output=out,
        )

        rows = _extract_evidence(out.read_text(encoding="utf-8"))["risk"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["row_type"], "phenotype_review_target")
        self.assertEqual(rows[0]["trait"], "CAPN3 / limb-girdle muscular dystrophy")
        self.assertEqual(rows[0]["group_type"], "carrier_relevance")
        self.assertEqual(rows[0]["missing_interpretation_gates"], ["inheritance"])

    def test_normalizes_clinvar_review_groups_in_risk_result_list(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "risk": [
                    {
                        "status": "completed",
                        "candidate_review_groups": {
                            "policy_id": "clinvar_candidate_review_groups_v1",
                            "group_count": 1,
                            "groups": [
                                {
                                    "group_id": "clinvar_group_brca1",
                                    "group_type": "carrier_relevance",
                                    "gene": "BRCA1",
                                    "condition": "hereditary breast and ovarian cancer",
                                    "interpretation_gates": {
                                        "clinical_confirmation": {"required": True, "state": "needed"}
                                    },
                                }
                            ],
                        },
                    },
                    {"status": "requires_score_import"},
                ],
            },
            mode="full",
            output=out,
        )

        rows = _extract_evidence(out.read_text(encoding="utf-8"))["risk"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["row_type"], "clinvar_review_group")
        self.assertEqual(rows[0]["trait"], "BRCA1 / hereditary breast and ovarian cancer")
        self.assertEqual(rows[0]["group_type"], "carrier_relevance")
        self.assertEqual(rows[0]["sources"], ["ClinVar"])
        self.assertEqual(rows[0]["missing_interpretation_gates"], ["clinical_confirmation"])

    def test_clinvar_review_groups_do_not_render_as_variant_rows(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "variants": {
                    "status": "completed",
                    "candidate_inventory": [],
                    "candidate_review_groups": {
                        "policy_id": "clinvar_candidate_review_groups_v1",
                        "group_count": 1,
                        "groups": [
                            {
                                "group_id": "clinvar_group_brca1",
                                "group_type": "carrier_relevance",
                                "gene": "BRCA1",
                                "condition": "hereditary breast and ovarian cancer",
                            }
                        ],
                    },
                },
                "risk": [
                    {
                        "status": "completed",
                        "candidate_review_groups": {
                            "policy_id": "clinvar_candidate_review_groups_v1",
                            "group_count": 1,
                            "groups": [
                                {
                                    "group_id": "clinvar_group_brca1",
                                    "group_type": "carrier_relevance",
                                    "gene": "BRCA1",
                                    "condition": "hereditary breast and ovarian cancer",
                                }
                            ],
                        },
                    }
                ],
            },
            mode="full",
            output=out,
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(_panel_keys(parsed), {"risk"})
        self.assertEqual(parsed["risk"][0]["row_type"], "clinvar_review_group")

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

    def test_native_empty_results_clear_stale_clinvar_and_nutrigenomics_panels(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-NATIVE-EMPTY-2", "variantCount": 10},
                "variants": [{"rsid": "rs1", "gene": "GENE1"}],
                "variants_all": [{"rsid": "rs2", "gene": "GENE2"}],
                "nutrigenomics": [{"marker": "Folate Metabolism", "gene": "MTHFR"}],
            },
            mode="full",
            output=out,
        )

        result = decode_dashboard.render_dashboard(
            evidence={
                "variants": {"status": "completed", "candidate_inventory": []},
                "variants_all": {"status": "requires_library_install", "missing_library": {"library": "clinvar-grch38"}},
                "nutrigenomics": {"coverage_state": "in_scope_empty", "markers": []},
            },
            mode="update",
            output=out,
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(_panel_keys(parsed), {"overview"})
        self.assertTrue({"variants", "variants_all", "nutrigenomics"}.issubset(set(result["panels_empty"])))

    def test_normalizes_native_clinvar_and_nutrigenomics_results(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "variants": {
                    "status": "completed",
                    "candidate_inventory": [
                        {
                            "variant": {"id": "rs777", "chrom": "1", "pos": 100, "ref": "A", "alt": "G", "genotype": "0/1"},
                            "clinvar": {
                                "clinical_significance_counts": [["Pathogenic", 1]],
                                "conditions": ["example_condition"],
                            },
                            "genes": ["GENE7"],
                        }
                    ],
                },
                "nutrigenomics": {
                    "coverage_state": "data_returned",
                    "markers": [
                        {
                            "domain": "folate_metabolism",
                            "gene": {"symbol": "MTHFR"},
                            "variant": {"rsid": "rs1801133"},
                            "established_effect": {"claim": "Associated with folate and homocysteine markers."},
                            "evidence_tier": "established",
                        }
                    ],
                },
            },
            mode="full",
            output=out,
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(parsed["variants"][0]["rsid"], "rs777")
        self.assertEqual(parsed["variants"][0]["gene"], "GENE7")
        self.assertEqual(parsed["variants"][0]["zygosity"], "het")
        self.assertEqual(parsed["nutrigenomics"][0]["gene"], "MTHFR")
        self.assertEqual(parsed["nutrigenomics"][0]["marker"], "Folate Metabolism")

    def test_direct_panel_rows_reject_native_only_fields(self) -> None:
        cases = [
            (
                "pgx",
                {"pgx": [{"Gene": "CYP2C19", "Source Diplotype": "*1/*2"}]},
            ),
            (
                "risk",
                {"risk": [{"reported_trait": "Synthetic common trait", "score": 2.0}]},
            ),
            (
                "variants",
                {
                    "variants": [
                        {
                            "sample_variant": {"id": "rs777", "chrom": "1", "pos": 100},
                            "clinvar": {"clinical_significance": "Pathogenic"},
                        }
                    ]
                },
            ),
            (
                "nutrigenomics",
                {
                    "nutrigenomics": [
                        {
                            "domain": "folate_metabolism",
                            "variant": {"rsid": "rs1801133"},
                        }
                    ]
                },
            ),
        ]
        for name, evidence in cases:
            with self.subTest(name=name):
                with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
                    decode_dashboard.render_dashboard(
                        evidence=evidence,
                        mode="full",
                        output=self.tmpdir / f"{name}-direct-native.html",
                    )
                self.assertEqual(ctx.exception.code, "panel_schema_mismatch")

    def test_native_pgx_drug_label_row_renders_for_dashboard_cards(self) -> None:
        out = self.tmpdir / "dash.html"
        result = decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-RSID-PGX", "variantCount": 10},
                "pgx": {
                    "status": "completed",
                    "medication_review_matrix": {
                        "policy_id": "pgx_medication_review_matrix_v1",
                        "row_count": 1,
                        "rows": [
                            {
                                "row_id": "pgxrow_label",
                                "row_type": "drug_label",
                                "drug": "example-drug",
                                "recommendation_text": "Label contains pharmacogenomic context.",
                                "evidence_classes": ["fda_pharmacogenomic_biomarker_labeling"],
                                "sample_relevance": {"state": "public_only"},
                            }
                        ],
                    },
                },
            },
            mode="full",
            output=out,
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(_panel_keys(parsed), {"overview", "pgx"})
        self.assertEqual(parsed["pgx"][0]["drugs"][0]["name"], "example-drug")
        self.assertIn("pgx", result["panels_rendered"])

    def test_malformed_native_adapter_rows_raise(self) -> None:
        cases = [
            (
                "pgx",
                {
                    "pgx": {
                        "status": "completed",
                        "sample_pgx_matrix": {
                            "policy_id": "pharmcat_sample_pgx_matrix_v1",
                            "row_count": 1,
                            "rows": [{"row_id": "bad", "row_type": "sample_only"}],
                        },
                    },
                },
                "sample_pgx_matrix row 0",
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
