from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.capabilities.decode import dashboard as decode_dashboard

_DECODE_BUILDER_PATCH = (
    "genomi.operations.registry.handlers_screen_journal."
    "decode_evidence_builder.build_dashboard_evidence"
)


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


NAV_LABELS = (
    "Overview",
    "Variants",
    "Pharmacogenomics",
    "Risk Review",
    "Ancestry",
    "Nutrigenomics",
)


class RenderDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = Path(self._tmp.name)

    def test_render_full_writes_self_contained_html(self) -> None:
        out = self.tmpdir / "dashboard output" / "dash.html"
        evidence = {
            "overview": {
                "sampleId": "HG-TEST-01",
                "genomeBuild": "GRCh38",
                "variantCount": 4500000,
            },
            "variants": [
                {"rsid": "rs429358", "gene": "APOE", "chrom": "19", "pos": 44908684,
                 "ref": "T", "alt": "C", "zygosity": "hom",
                 "clinvarSignificance": "risk_factor", "conditionShort": "Alzheimer"},
            ],
        }
        result = decode_dashboard.render_dashboard(
            evidence=evidence, mode="full", output=out
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["mode"], "full")
        self.assertTrue(out.is_file())
        html = out.read_text(encoding="utf-8")
        # Self-contained: inline logo data URL
        self.assertIn("data:image/png;base64,", html)
        # Renders offline: React/ReactDOM/app JS are inlined and the template
        # placeholders have all been resolved.
        unresolved = re.findall(
            r"__(?:GENOMI_VENDOR_SCRIPTS|GENOMI_APP_JS|GENOMI_LOGO_DATA_URL|GENOMI_EVIDENCE)__",
            html,
        )
        self.assertEqual(unresolved, [])
        self.assertEqual(re.findall(r'<script[^>]+src="(https?://[^"]+)"', html), [])
        self.assertEqual(re.findall(r'<script[^>]+type="([^"]+)"', html), [])
        self.assertIn("ReactDOM", html)  # vendored runtime is inlined
        # Evidence blob present and contains keys
        parsed = _extract_evidence(html)
        self.assertEqual(parsed["overview"]["sampleId"], "HG-TEST-01")
        self.assertEqual(parsed["variants"][0]["rsid"], "rs429358")
        # All seven nav labels render
        for label in NAV_LABELS:
            self.assertIn(label, html)
        # Serve hint surfaces a localhost URL + http.server command the agent can run
        serve = result["serve"]
        self.assertEqual(serve["status"], "ready_to_start")
        self.assertEqual(serve["filename"], "dash.html")
        self.assertEqual(serve["directory"], str(out.parent.resolve()))
        self.assertIn("127.0.0.1", serve["url"])
        self.assertTrue(serve["url"].endswith("/dash.html"))
        self.assertIn("python3 -m http.server", serve["command"])
        self.assertIn("--bind 127.0.0.1", serve["command"])
        self.assertIn(f"--directory {shlex.quote(str(out.parent.resolve()))}", serve["command"])

    def test_render_serve_metadata_avoids_busy_default_port(self) -> None:
        out = self.tmpdir / "dash.html"

        def available(port: int) -> bool:
            return port != 8765

        with mock.patch.object(decode_dashboard.local_server, "_port_available", side_effect=available):
            result = decode_dashboard.render_dashboard(
                evidence={"overview": {"sampleId": "HG-PORT", "variantCount": 1}},
                mode="full",
                output=out,
            )
        self.assertNotEqual(result["serve"]["port"], 8765)
        self.assertIn(f":{result['serve']['port']}/dash.html", result["serve"]["url"])

    def test_render_can_autostart_local_dashboard_server(self) -> None:
        out = self.tmpdir / "dash.html"
        process = mock.Mock(pid=12345)
        with (
            mock.patch.dict(os.environ, {"GENOMI_DASHBOARD_AUTOSERVE": "1"}),
            mock.patch.object(decode_dashboard.local_server.subprocess, "Popen", return_value=process) as popen,
            mock.patch.object(decode_dashboard.local_server, "_verify_url", return_value=200),
        ):
            result = decode_dashboard.render_dashboard(
                evidence={"overview": {"sampleId": "HG-SERVE", "variantCount": 1}},
                mode="full",
                output=out,
                start_server=True,
            )

        self.assertEqual(result["serve"]["status"], "started")
        self.assertEqual(result["serve"]["pid"], 12345)
        self.assertEqual(result["serve"]["http_status"], 200)
        popen.assert_called_once()

    def test_render_full_unavailable_panel_states(self) -> None:
        out = self.tmpdir / "dash.html"
        overview = {"sampleId": "HG-TEST-02", "variantCount": 4500000}
        result = decode_dashboard.render_dashboard(
            evidence={"overview": overview},
            mode="full",
            output=out,
            panel_states=[
                {"panel": "overview", "status": "data_returned"},
                {"panel": "pgx", "status": "position_aware_pharmcat_export_required"},
            ],
            panels_requested=["overview", "pgx"],
        )
        html = out.read_text(encoding="utf-8")
        parsed = _extract_evidence(html)
        dashboard_meta = parsed["__dashboard"]
        self.assertEqual(dashboard_meta["panelStates"][1]["panel"], "pgx")
        self.assertEqual(dashboard_meta["panelStates"][1]["status"], "position_aware_pharmcat_export_required")
        self.assertEqual(dashboard_meta["panelsRequested"], ["overview", "pgx"])
        pgx_unavailable = next(item for item in dashboard_meta["unavailablePanels"] if item["panel"] == "pgx")
        self.assertEqual(pgx_unavailable["state"], "blocked_position_aware_export")
        self.assertEqual(pgx_unavailable["source_status"], "position_aware_pharmcat_export_required")
        self.assertIn("position-aware Active Genome Index export", html)
        self.assertNotIn("Ask the agent to run", html)
        self.assertNotIn("genomi.invoke", html)
        self.assertNotIn("Not gathered yet", html)
        self.assertEqual(set(result["panels_empty"]), {
            "variants", "variants_all", "pgx", "risk", "ancestry", "nutrigenomics",
        })
        self.assertEqual(result["panels_rendered"], ["overview"])

    def test_render_running_panel_state(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={"overview": {"sampleId": "HG-RUNNING", "variantCount": 1}},
            mode="full",
            output=out,
            panel_states=[
                {
                    "panel": "pgx",
                    "status": "in_progress",
                    "source_operation": "pharmacogenomics.run_pharmcat",
                    "job_id": "pharmacogenomics-run-pharmcat-1",
                    "check": {
                        "operation": "genomi.check_background_job",
                        "params": {"job_id": "pharmacogenomics-run-pharmcat-1"},
                    },
                }
            ],
            panels_requested=["overview", "pgx"],
        )
        html = out.read_text(encoding="utf-8")
        parsed = _extract_evidence(html)
        pgx_unavailable = next(item for item in parsed["__dashboard"]["unavailablePanels"] if item["panel"] == "pgx")
        self.assertEqual(pgx_unavailable["state"], "running")
        self.assertEqual(pgx_unavailable["job_id"], "pharmacogenomics-run-pharmcat-1")
        self.assertEqual(
            pgx_unavailable["check"],
            {"operation": "genomi.check_background_job", "params": {"job_id": "pharmacogenomics-run-pharmcat-1"}},
        )
        self.assertIn("still running in background job", html)

    def test_render_update_merges_panels(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-MERGE", "genomeBuild": "GRCh38",
                             "variantCount": 4500000},
                "variants": [{"rsid": "rs1", "gene": "G1"}],
            },
            mode="full",
            output=out,
        )
        result = decode_dashboard.render_dashboard(
            evidence={"pgx": [{"gene": "CYP2C19", "diplotype": "*1/*2",
                               "phenotype": "Intermediate", "impact": "reduced"}]},
            mode="update",
            output=out,
        )
        self.assertEqual(result["mode"], "update")
        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        # Original overview retained
        self.assertEqual(parsed["overview"]["sampleId"], "HG-MERGE")
        # Variants retained
        self.assertEqual(parsed["variants"][0]["rsid"], "rs1")
        # New pgx merged in
        self.assertEqual(parsed["pgx"][0]["gene"], "CYP2C19")

    def test_render_update_empty_panels_clear_stale_list_panels(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-CLEAR", "variantCount": 4500000},
                "variants": [{"rsid": "rs1", "gene": "G1"}],
                "pgx": [{"gene": "CYP2C19", "phenotype": "Intermediate"}],
                "risk": [{"trait": "LDL cholesterol", "percentile": 72}],
            },
            mode="full",
            output=out,
        )

        result = decode_dashboard.render_dashboard(
            evidence={"variants": [], "pgx": [], "risk": []},
            mode="update",
            output=out,
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(parsed["overview"]["sampleId"], "HG-CLEAR")
        self.assertEqual(_panel_keys(parsed), {"overview"})
        self.assertTrue({"variants", "pgx", "risk"}.issubset(set(result["panels_empty"])))
        self.assertEqual(result["panels_rendered"], ["overview"])

    def test_render_update_clear_panels_preserves_omitted_panels(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-CLEAR-MARKER", "variantCount": 4500000},
                "variants": [{"rsid": "rs1", "gene": "G1"}],
                "risk": [{"trait": "T2D", "percentile": 44}],
            },
            mode="full",
            output=out,
        )

        result = decode_dashboard.render_dashboard(
            evidence={},
            mode="update",
            output=out,
            clear_panels=["risk"],
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(parsed["variants"][0]["rsid"], "rs1")
        self.assertEqual(_panel_keys(parsed), {"overview", "variants"})
        self.assertTrue({"risk"}.issubset(set(result["panels_empty"])))
        self.assertEqual(set(result["panels_rendered"]), {"overview", "variants"})

    def test_render_update_empty_variants_all_not_refilled_from_source(self) -> None:
        out = self.tmpdir / "dash.html"
        source = self.tmpdir / "clinvar.matches.jsonl"
        source.write_text(
            json.dumps({
                "sample_variant": {"id": "rs-source", "chrom": "1", "pos": 10},
                "clinvar": {"clinical_significance": "risk_factor"},
            }) + "\n",
            encoding="utf-8",
        )
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-SOURCE-CLEAR", "variantCount": 4500000},
                "variants_all": [{"rsid": "rs-old", "gene": "OLD"}],
            },
            mode="full",
            output=out,
        )

        result = decode_dashboard.render_dashboard(
            evidence={"variants_all": []},
            mode="update",
            output=out,
            variants_all_source=source,
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(_panel_keys(parsed), {"overview"})
        self.assertTrue({"variants_all"}.issubset(set(result["panels_empty"])))

    def test_render_update_empty_variants_all_source_clears_stale_panel(self) -> None:
        out = self.tmpdir / "dash.html"
        source = self.tmpdir / "empty-clinvar.matches.jsonl"
        source.write_text("", encoding="utf-8")
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-SOURCE-EMPTY", "variantCount": 4500000},
                "variants_all": [{"rsid": "rs-old", "gene": "OLD"}],
            },
            mode="full",
            output=out,
        )

        result = decode_dashboard.render_dashboard(
            evidence={},
            mode="update",
            output=out,
            variants_all_source=source,
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(_panel_keys(parsed), {"overview"})
        self.assertIn("variants_all", result["panels_empty"])

    def test_render_update_missing_variants_all_source_raises(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-SOURCE-MISSING", "variantCount": 4500000},
                "variants_all": [{"rsid": "rs-old", "gene": "OLD"}],
            },
            mode="full",
            output=out,
        )

        with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
            decode_dashboard.render_dashboard(
                evidence={},
                mode="update",
                output=out,
                variants_all_source=self.tmpdir / "missing.jsonl",
            )

        self.assertEqual(ctx.exception.code, "variants_all_source_not_found")

    def test_render_update_malformed_variants_all_source_raises(self) -> None:
        out = self.tmpdir / "dash.html"
        for source_name, content, expected_message in (
            ("bad-json.jsonl", "{not json}\n", "not valid JSON"),
            (
                "unmapped-row.jsonl",
                json.dumps({"unmapped_dashboard_field": "x"}) + "\n",
                "did not map to a dashboard variant row",
            ),
        ):
            with self.subTest(source_name=source_name):
                source = self.tmpdir / source_name
                source.write_text(content, encoding="utf-8")
                decode_dashboard.render_dashboard(
                    evidence={
                        "overview": {"sampleId": "HG-SOURCE-BAD", "variantCount": 4500000},
                        "variants_all": [{"rsid": "rs-old", "gene": "OLD"}],
                    },
                    mode="full",
                    output=out,
                )

                with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
                    decode_dashboard.render_dashboard(
                        evidence={},
                        mode="update",
                        output=out,
                        variants_all_source=source,
                    )

                self.assertEqual(ctx.exception.code, "variants_all_source_malformed")
                self.assertIn("line 1", ctx.exception.message)
                self.assertIn(expected_message, ctx.exception.message)

    def test_render_update_reads_existing_evidence_with_brace_semicolon_text(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {
                    "sampleId": "HG-BRACE",
                    "variantCount": 4500000,
                    "genomeSource": "literal }; sequence from upstream metadata",
                },
            },
            mode="full",
            output=out,
        )

        decode_dashboard.render_dashboard(
            evidence={
                "pgx": [{"gene": "CYP2C19", "phenotype": "Intermediate"}],
            },
            mode="update",
            output=out,
        )

        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        self.assertEqual(parsed["overview"]["sampleId"], "HG-BRACE")
        self.assertEqual(parsed["pgx"][0]["gene"], "CYP2C19")

    def test_normalizes_ancestry_nearest_reference_groups(self) -> None:
        """ancestry.estimate_population_context keys map to neighbors[]."""
        out = self.tmpdir / "dash.html"
        result = decode_dashboard.render_dashboard(
            evidence={
                "ancestry": {
                    "nearest_reference_groups": [
                        {"label": "EUR", "centroid_distance": 0.39},
                        {"label": "AMR", "centroid_distance": 0.82},
                    ],
                    "sample_qc": {
                        "marker_overlap_quality": "low",
                        "overlap_fraction": 0.56,
                    },
                    "reference_panel": {"panel_id": "1000g-30x-grch38"},
                },
            },
            mode="full",
            output=out,
        )
        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        anc = parsed["ancestry"]
        self.assertEqual(anc["dominantAncestry"], "EUR")
        self.assertEqual(anc["neighbors"][0], {"population": "EUR", "similarity": 0.39})
        self.assertIn("ancestry", result["panels_rendered"])

    def test_supplied_overview_unmappable_raises(self) -> None:
        """A content-bearing panel that maps to no schema field fails loudly."""
        out = self.tmpdir / "dash.html"
        with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
            decode_dashboard.render_dashboard(
                evidence={"overview": {"random_unrelated_key": "x"}},
                mode="full",
                output=out,
            )
        self.assertEqual(ctx.exception.code, "panel_schema_mismatch")

    def test_supplied_overview_missing_required_field_raises(self) -> None:
        """Overview with content but no variant count is rejected, not blanked."""
        out = self.tmpdir / "dash.html"
        with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
            decode_dashboard.render_dashboard(
                evidence={"overview": {"sampleId": "HG-X", "genomeBuild": "GRCh38"}},
                mode="full",
                output=out,
            )
        self.assertEqual(ctx.exception.code, "panel_schema_mismatch")
        self.assertIn("variantCount", ctx.exception.message)

    def test_normalizes_real_summarize_overview(self) -> None:
        """The current active_genome_index.summarize result maps to overview."""
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {
                    "workflow_area": "static_annotation",
                    "active_genome_index": {
                        "agi_path": "/tmp/private.active-genome-index.sqlite",
                        "stats": {"variant_records": 5_151_074,
                                  "pass_records": 11_778_439,
                                  "total_records": 12_410_160},
                        "metadata": {"header": {"samples": ["SQ73VL33"],
                                                "reference": "GRCh38.p13",
                                                "dataSourceType": "WGS"}},
                    },
                    "outputs": {"clinvar_matches": "/tmp/private/clinvar.matches.jsonl"},
                },
            },
            mode="full",
            output=out,
        )
        ov = _extract_evidence(out.read_text(encoding="utf-8"))["overview"]
        self.assertEqual(ov["variantCount"], 5_151_074)
        self.assertEqual(ov["sampleId"], "SQ73VL33")
        self.assertEqual(ov["genomeBuild"], "GRCh38.p13")
        self.assertEqual(ov["genotypeQuality"], 94.9)
        self.assertEqual(set(ov), {
            "sampleId",
            "genomeBuild",
            "variantCount",
            "variantCountLabel",
            "genotypeQuality",
            "genomeSource",
        })

    def test_normalizes_consumer_array_overview_marker_count(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {
                    "active_genome_index": {
                        "metadata": {
                            "source_format": "23andme",
                            "source_kind": "consumer_genotype_array",
                            "genome_build": "GRCh37",
                        },
                        "stats": {
                            "total_records": 643_161,
                            "variant_records": 0,
                            "pass_records": 633_413,
                            "fail_records": 9_748,
                            "array_call_records": 633_413,
                            "array_no_call_records": 9_748,
                        },
                    },
                    "sample_slug": "23andme-fixture",
                },
            },
            mode="full",
            output=out,
        )
        html = out.read_text(encoding="utf-8")
        ov = _extract_evidence(html)["overview"]
        self.assertEqual(ov["variantCount"], 633_413)
        self.assertEqual(ov["variantCountLabel"], "Markers Indexed")
        self.assertEqual(ov["genomeBuild"], "GRCh37")
        self.assertEqual(ov["genotypeQuality"], 98.5)
        self.assertIn("Markers Indexed", html)

    def test_supplied_list_panel_wrong_type_raises(self) -> None:
        """A list panel handed a dict fails loudly instead of rendering odd."""
        out = self.tmpdir / "dash.html"
        with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
            decode_dashboard.render_dashboard(
                evidence={
                    "overview": {"sampleId": "HG-L", "variantCount": 10},
                    "risk": {"trait": "T2D", "score": 1.0},
                },
                mode="full",
                output=out,
            )
        self.assertEqual(ctx.exception.code, "panel_schema_mismatch")

    def test_supplied_list_row_without_dashboard_fields_raises(self) -> None:
        out = self.tmpdir / "dash.html"
        with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
            decode_dashboard.render_dashboard(
                evidence={
                    "overview": {"sampleId": "HG-L", "variantCount": 10},
                    "pgx": [{"drug": "contractdrug", "sampleMatchCount": 1}],
                },
                mode="full",
                output=out,
            )
        self.assertEqual(ctx.exception.code, "panel_schema_mismatch")
        self.assertIn("no recognized dashboard field", ctx.exception.message)

    def test_supplied_normalized_list_panel_unmapped_row_raises(self) -> None:
        for panel in ("variants", "nutrigenomics"):
            with self.subTest(panel=panel):
                out = self.tmpdir / f"{panel}.html"
                with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
                    decode_dashboard.render_dashboard(
                        evidence={
                            "overview": {"sampleId": "HG-BAD-ROW", "variantCount": 10},
                            panel: [{"unmapped_dashboard_field": "x"}],
                        },
                        mode="full",
                        output=out,
                    )
                self.assertEqual(ctx.exception.code, "panel_schema_mismatch")
                self.assertIn(f"Panel '{panel}' row 0", ctx.exception.message)

    def test_overview_renders_panel_highlights_when_panels_have_data(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {
                    "sampleId": "HG-HI",
                    "genomeBuild": "GRCh38",
                    "variantCount": 1000,
                    "parsedAt": "2026-05-25T00:00:00Z",
                },
                "variants": [
                    {"rsid": "rs429358", "gene": "APOE",
                     "clinvarSignificance": "risk_factor"},
                ],
                "pgx": [
                    {"gene": "CYP2C19", "diplotype": "*1/*2",
                     "phenotype": "Intermediate", "impact": "reduced"},
                ],
                "ancestry": {
                    "dominantAncestry": "EUR",
                    "neighbors": [{"population": "EUR", "similarity": 0.9}],
                    "pcaPoints": [{"x": 1, "y": 2, "cluster": "sample"}],
                },
            },
            mode="full",
            output=out,
        )
        html = out.read_text(encoding="utf-8")
        # Highlight card headers render in the inline script.
        self.assertIn("Top Variants", html)
        self.assertIn("Pharmacogenomics", html)
        self.assertIn("Ancestry", html)

    def test_source_coverage_uses_canonical_name_and_state_keys(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "overview": {
                    "sampleId": "HG-SRC",
                    "genomeBuild": "GRCh38",
                    "variantCount": 100,
                    "parsedAt": "2026-05-25T00:00:00Z",
                    "sourceCoverage": [
                        {"name": "ClinVar", "coverageState": "data_returned", "percent": 100},
                        {"name": "PharmCAT"},
                    ],
                },
            },
            mode="full",
            output=out,
        )
        html = out.read_text(encoding="utf-8")
        self.assertIn("ClinVar", html)
        self.assertIn("PharmCAT", html)
        parsed = _extract_evidence(html)
        sources = parsed["overview"]["sourceCoverage"]
        self.assertEqual(sources[0]["name"], "ClinVar")
        self.assertEqual(sources[0]["coverageState"], "data_returned")
        self.assertEqual(sources[1]["name"], "PharmCAT")
        self.assertEqual(sources[1]["coverageState"], "data_returned")
        self.assertEqual(sources[0]["percent"], 100)

    def test_ancestry_pca_empty_shows_placeholder(self) -> None:
        out = self.tmpdir / "dash.html"
        decode_dashboard.render_dashboard(
            evidence={
                "ancestry": {
                    "dominantAncestry": "EUR",
                    "neighbors": [{"population": "EUR", "similarity": 0.9}],
                },
            },
            mode="full",
            output=out,
        )
        html = out.read_text(encoding="utf-8")
        self.assertIn("No PCA points in evidence", html)

    def test_render_update_missing_file_errors(self) -> None:
        missing = self.tmpdir / "nope" / "dash.html"
        with self.assertRaises(decode_dashboard.DashboardRenderError) as ctx:
            decode_dashboard.render_dashboard(
                evidence={"overview": {"sampleId": "x"}},
                mode="update",
                output=missing,
            )
        self.assertEqual(ctx.exception.code, "dashboard_not_found")
